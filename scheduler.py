"""
Scheduler / reminder functions extracted from gui_app.py.

Each function accepts ``app`` as its first parameter (the App instance).
All former ``self.xxx`` references are replaced with ``app.xxx``.
"""

import os
import time
import datetime
import threading
import traceback
import tkinter as tk
from tkinter import ttk

import config
import utils
import cooldown_manager
import cooldown_watcher


# ---------- 定时任务调度 ----------

def start_scheduler(app):
    """启动定时检查线程，若线程已在运行则先停止再重启（以应用新设置）"""
    if app._schedule_thread and app._schedule_thread.is_alive():
        app._scheduler_stop_event.set()
        app._schedule_thread.join(timeout=5)
    app._scheduler_stop_event.clear()
    app._daily_loop = app.settings.get("run_mode") == "每日循环"
    times_str = app.settings.get("schedule_times", [])
    if not times_str:
        single = app.settings.get("start_time", "08:00")
        times_str = [single]
    # 标准化所有时间格式（补零）
    normalized = []
    for t in times_str:
        try:
            h, m = map(int, t.split(":"))
            normalized.append(f"{h:02d}:{m:02d}")
        except Exception:
            continue
    app._schedule_times = sorted(set(normalized))
    app._schedule_thread = threading.Thread(target=schedule_loop, args=(app,), daemon=True)
    app._schedule_thread.start()
    print(f"⏰ 已设置定时任务，时间点：{', '.join(app._schedule_times)}，"
          f"模式：{'每日循环' if app._daily_loop else '单次'}")
    # 设置唤醒定时器
    set_next_wake_timer(app)
    # 确保开机唤醒任务存在
    if app.settings.get("auto_startup_enabled", False):
        startup_time = app.settings.get("auto_startup_time", "07:00")
        utils.schedule_startup_task(startup_time)


def schedule_loop(app):
    """线程：每分钟检查一次时间，处理提醒、唤醒、触发执行和自动关机"""
    try:
        print(f"⏰ 定时调度线程已启动，目标时间点：{app._schedule_times}")
        if app._daily_loop:
            schedule_loop_daily(app)
        else:
            schedule_loop_single(app)
    except Exception as e:
        print(f"❌ 定时调度线程异常退出: {e}")
        traceback.print_exc()
        # 恢复机制：如果调度器意外退出且未被主动停止，5秒后自动重启
        if not app._scheduler_stop_event.is_set() and app.settings.get("auto_start", False):
            print("🔄 调度器将在 5 秒后自动重启...")
            app.root.after(5000, restart_scheduler)


def restart_scheduler(app):
    """调度器异常退出后的恢复入口（由 root.after 调度到主线程）"""
    if not app._scheduler_stop_event.is_set() and app.settings.get("auto_start", False):
        print("🔄 正在重启调度器...")
        start_scheduler(app)


def schedule_loop_daily(app):
    """每日循环模式：持续检查时间点（含30分钟容差，防止休眠唤醒后错过目标时间）"""
    executed_today = set()  # 记录今天已执行的 (日期, 时间点) 防止重复执行
    try:
        while not app._scheduler_stop_event.is_set():
            try:
                now = datetime.datetime.now()
                today_str = now.strftime("%Y-%m-%d")

                # 清理非当天的执行记录
                executed_today = {(d, t) for d, t in executed_today if d == today_str}

                # 1. 定时执行（带30分钟容差，覆盖休眠唤醒场景）
                matched_time = None
                for t in app._schedule_times:
                    if (today_str, t) in executed_today:
                        continue
                    h, m = map(int, t.split(":"))
                    scheduled_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    tolerance = datetime.timedelta(minutes=30)
                    if scheduled_dt <= now <= scheduled_dt + tolerance:
                        matched_time = t
                        break

                if matched_time is not None and not app.running:
                    if app._reminder_cancelled_time == matched_time:
                        # 用户取消了这个时间点，跳过但不标记为已执行（不影响其他时间点）
                        print(f"⏹ 用户取消了 {matched_time} 的定时运行")
                        executed_today.add((today_str, matched_time))
                        app._reminder_shown = False
                        app._reminder_target = None
                        app._reminder_cancelled_time = None
                    else:
                        executed_today.add((today_str, matched_time))
                        app.root.after(0, lambda mt=matched_time: execute_scheduled_run(app, mt))
                        app._reminder_cancelled_time = None
                    time.sleep(60)
                    continue

                # 在即将运行的时段阻止系统睡眠（唤醒后防止再次休眠）
                if is_within_pre_run_window(app, now, minutes=10):
                    utils.prevent_sleep()
                    if not app._wake_attempted:
                        utils.wake_display()
                        app._wake_attempted = True
                else:
                    if not app.running:
                        utils.allow_sleep()
                    app._wake_attempted = False

                # 2. 运行前提醒
                check_reminder_daily(app, now, executed_today)

                # 3. 自动关机（每天只触发一次）
                check_shutdown(app, now)
            except Exception as inner_e:
                print(f"⚠️ 调度循环内部异常（将继续运行）: {inner_e}")
                traceback.print_exc()

            time.sleep(30)
    except Exception as e:
        print(f"❌ 每日循环调度异常: {e}")
        traceback.print_exc()


def schedule_loop_single(app):
    """单次模式：等待下一个时间点（含 30 分钟容差，防止休眠唤醒后略过目标时间）"""
    try:
        now = datetime.datetime.now()
        targets = []
        for t in app._schedule_times:
            h, m = map(int, t.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            tolerance = datetime.timedelta(minutes=30)
            if target + tolerance < now:
                target += datetime.timedelta(days=1)
            targets.append(target)
        next_target = min(targets)
        print(f"⏰ 单次定时：将在 {next_target.strftime('%Y-%m-%d %H:%M')} 执行，当前时间 {now.strftime('%Y-%m-%d %H:%M:%S')}")

        while not app._scheduler_stop_event.is_set():
            try:
                now = datetime.datetime.now()

                # 在即将运行的时段阻止系统睡眠
                pre_run_start = next_target - datetime.timedelta(minutes=10)
                if pre_run_start <= now < next_target and not app.running:
                    utils.prevent_sleep()
                    if not app._wake_attempted:
                        utils.wake_display()
                        app._wake_attempted = True
                elif now >= next_target or now < pre_run_start:
                    if not app.running:
                        utils.allow_sleep()
                    app._wake_attempted = False

                # 提醒
                if app.settings.get("reminder_enabled", False) and not app._reminder_shown and not app.running:
                    reminder_min = app.settings.get("reminder_minutes", 5)
                    reminder_time = next_target - datetime.timedelta(minutes=reminder_min)
                    if reminder_time <= now < next_target:
                        app._next_run_time_str = next_target.strftime("%H:%M")
                        app._reminder_shown = True
                        app._reminder_target = next_target
                        print(f"🔔 触发运行提醒弹窗，将在 {app._next_run_time_str} 执行")
                        app.root.after(0, lambda: show_reminder(app, reminder_min))

                # 执行
                if now >= next_target:
                    target_str = next_target.strftime("%H:%M")
                    if app._reminder_cancelled_time == target_str:
                        print(f"⏹ 用户取消了 {target_str} 的定时运行，跳过本次")
                        app._reminder_cancelled_time = None
                        app._reminder_shown = False
                        # 单次模式：取消后跳过今天，自动计算明天的下一个时间点
                        app.root.after(0, lambda: reschedule_single(app, next_target))
                    else:
                        app.root.after(0, lambda ts=target_str: execute_scheduled_run(app, ts))
                        app.settings["auto_start"] = False
                        config.save_settings(app.settings)
                        app.root.after(0, lambda: update_ui_after_single(app))
                    break
            except Exception as inner_e:
                print(f"⚠️ 调度循环内部异常（将继续运行）: {inner_e}")
                traceback.print_exc()

            time.sleep(10)
    except Exception as e:
        print(f"❌ 单次定时调度异常: {e}")
        traceback.print_exc()


def check_reminder_daily(app, now, executed_today):
    """每日循环模式：检查是否需要弹出运行提醒"""
    if not app.settings.get("reminder_enabled", False) or app.running:
        return

    reminder_min = app.settings.get("reminder_minutes", 5)
    reminder_sec_offset = reminder_min * 60
    today_str = now.strftime("%Y-%m-%d")

    # 如果已有提醒目标且已过执行时间，重置提醒状态（允许下一个时间点触发提醒）
    if app._reminder_shown and app._reminder_target:
        h, m = map(int, app._reminder_target.split(":"))
        target_sec = h * 3600 + m * 60
        current_sec = now.hour * 3600 + now.minute * 60 + now.second
        if current_sec >= target_sec:
            app._reminder_shown = False
            app._reminder_target = None

    if app._reminder_shown:
        return

    for t in app._schedule_times:
        # 跳过已执行或已取消的时间点，防止提醒重复弹出
        if executed_today and (today_str, t) in executed_today:
            continue
        if app._reminder_cancelled_time == t:
            continue

        h, m = map(int, t.split(":"))
        scheduled_sec = h * 3600 + m * 60
        remind_sec = scheduled_sec - reminder_sec_offset

        # 处理跨天提醒（如 00:10 运行，23:55 提醒）
        current_sec = now.hour * 3600 + now.minute * 60 + now.second
        if remind_sec < 0:
            remind_sec += 86400
            scheduled_sec += 86400

        if remind_sec <= current_sec < scheduled_sec:
            app._next_run_time_str = t
            app._reminder_target = t
            app._reminder_shown = True
            print(f"🔔 触发运行提醒弹窗，将在 {t} 执行")
            app.root.after(0, lambda m=reminder_min: show_reminder(app, m))
            break


def check_shutdown(app, now):
    """检查是否需要触发自动关机"""
    if not app.settings.get("auto_shutdown_enabled", False) or app._shutdown_handled_today:
        return

    shutdown_time_str = app.settings.get("auto_shutdown_time", "22:00")
    try:
        h, m = map(int, shutdown_time_str.split(":"))
        shutdown_sec = h * 3600 + m * 60
        current_sec = now.hour * 3600 + now.minute * 60 + now.second

        # 在关机时间后的2分钟内触发
        if shutdown_sec <= current_sec < shutdown_sec + 120:
            if app.running:
                print("⏳ 任务正在运行，延迟关机...")
                return
            delay = 90
            utils.schedule_shutdown(delay)
            print(f"🔌 已到达关机时间 {shutdown_time_str}，系统将在 {delay} 秒后关机")
            app._shutdown_handled_today = True

            # 每日重置
            if current_sec < 60 and now.hour == 0:
                app._shutdown_handled_today = False
    except Exception as e:
        print(f"⚠️ 自动关机检查失败: {e}")


def is_within_pre_run_window(app, now, minutes=10):
    """检查当前时间是否在某个定时运行点的前N分钟窗口内（用于唤醒保持）"""
    if not app._schedule_times:
        return False
    for t in app._schedule_times:
        h, m = map(int, t.split(":"))
        scheduled_sec = h * 3600 + m * 60
        window_start = scheduled_sec - minutes * 60
        current_sec = now.hour * 3600 + now.minute * 60 + now.second
        # 处理跨天
        if window_start < 0:
            window_start += 86400
            scheduled_sec += 86400
        if window_start <= current_sec < scheduled_sec:
            return True
    return False


def execute_scheduled_run(app, time_str):
    """执行定时运行（关闭提醒窗口、确保唤醒状态、启动脚本）"""
    try:
        print(f"🚀 定时触发：{time_str}，当前时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        # 关闭提醒窗口
        if app._reminder_window:
            try:
                app._reminder_window.destroy()
            except Exception:
                pass
            app._reminder_window = None
        app._reminder_shown = False
        app._reminder_cancelled_time = None
        # 定时任务触发时临时忽略冷却检查，确保所有账号都能执行
        app._ignore_cooldown_this_run = True
        # 防止系统在运行时睡眠
        utils.prevent_sleep()
        # 尝试唤醒显示器（从睡眠/息屏状态恢复）
        utils.wake_display()
        time.sleep(2)
        app.root.after(0, app.start)
    except Exception as e:
        print(f"❌ 定时执行出错: {e}")
        traceback.print_exc()


def set_next_wake_timer(app):
    """计算下一个运行时间，提前5分钟设置唤醒定时器（支持定时和冷却两种模式）"""
    if not app.settings.get("wake_enabled", True):
        return
    try:
        # 取消旧定时器
        if app._wake_timer_handle:
            utils.cancel_wake_timer(app._wake_timer_handle)
            app._wake_timer_handle = None

        now = datetime.datetime.now()
        next_run = None

        # 定时执行模式
        for t in app._schedule_times:
            h, m = map(int, t.split(":"))
            run_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if run_time <= now:
                run_time += datetime.timedelta(days=1)
            if next_run is None or run_time < next_run:
                next_run = run_time

        # 冷却完立即运行模式：取最早冷却到期时间
        if app.settings.get("cooldown_run_immediately", False) and app.qq_account_images:
            for img_path in app.qq_account_images:
                fname = os.path.basename(img_path)
                cooling, next_time_str = cooldown_manager.is_cooling_down(fname)
                if cooling and next_time_str:
                    try:
                        cd_next = datetime.datetime.strptime(next_time_str, "%Y-%m-%d %H:%M:%S")
                        if next_run is None or cd_next < next_run:
                            next_run = cd_next
                    except Exception:
                        pass

        if next_run:
            wake_time = next_run - datetime.timedelta(minutes=5)
            # 只设置未来的唤醒时间（至少1分钟后）
            min_gap = datetime.timedelta(seconds=60)
            if wake_time > now + min_gap:
                # 唤醒时间未变化则跳过，避免重复日志
                if app._last_wake_time == wake_time:
                    return
                handle = utils.set_wake_timer(wake_time)
                if handle:
                    app._wake_timer_handle = handle
                    app._last_wake_time = wake_time
                    print(f"🔔 已设置唤醒定时器：{wake_time.strftime('%H:%M')}")
    except Exception as e:
        print(f"⚠️ 设置唤醒定时器失败: {e}")


def update_cooldown_wake_timer(app):
    """冷却监听专用：根据最早冷却到期时间更新唤醒定时器"""
    if not app.settings.get("wake_enabled", True):
        return
    if not app.settings.get("cooldown_run_immediately", False):
        return
    try:
        now = datetime.datetime.now()
        earliest_next = None
        if app.qq_account_images:
            for img_path in app.qq_account_images:
                fname = os.path.basename(img_path)
                cooling, next_time_str = cooldown_manager.is_cooling_down(fname)
                if cooling and next_time_str:
                    try:
                        cd_next = datetime.datetime.strptime(next_time_str, "%Y-%m-%d %H:%M:%S")
                        if earliest_next is None or cd_next < earliest_next:
                            earliest_next = cd_next
                    except Exception:
                        pass

        if earliest_next:
            wake_time = earliest_next - datetime.timedelta(minutes=5)
            min_gap = datetime.timedelta(seconds=60)
            if wake_time > now + min_gap:
                # 唤醒时间未变化则跳过，避免重复日志
                if app._last_wake_time == wake_time:
                    return
                # 取消旧定时器后重新设置
                if app._wake_timer_handle:
                    utils.cancel_wake_timer(app._wake_timer_handle)
                    app._wake_timer_handle = None
                handle = utils.set_wake_timer(wake_time)
                if handle:
                    app._wake_timer_handle = handle
                    app._last_wake_time = wake_time
                    print(f"🔔 已设置冷却唤醒定时器：{wake_time.strftime('%H:%M')}")
    except Exception as e:
        print(f"⚠️ 更新冷却唤醒定时器失败: {e}")


def show_reminder(app, minutes):
    """显示运行前提醒弹窗"""
    if app._reminder_window and app._reminder_window.winfo_exists():
        return

    app._reminder_window = tk.Toplevel(app.root)
    app._reminder_window.title("⏰ 运行提醒")
    app._reminder_window.geometry("420x200")
    app._reminder_window.resizable(False, False)
    app._reminder_window.transient(app.root)
    app._reminder_window.attributes('-topmost', True)

    # 居中
    app._reminder_window.update_idletasks()
    x = (app._reminder_window.winfo_screenwidth() - 420) // 2
    y = (app._reminder_window.winfo_screenheight() - 200) // 2
    app._reminder_window.geometry(f"420x200+{x}+{y}")

    frame = ttk.Frame(app._reminder_window, padding=20)
    frame.pack(fill=tk.BOTH, expand=True)

    ttk.Label(frame, text=f"程序即将在 {minutes} 分钟后运行",
             font=('Microsoft YaHei UI', 14, 'bold')).pack(pady=(10, 5))
    ttk.Label(frame, text=f"将于 {app._next_run_time_str} 开始执行任务",
             font=('Microsoft YaHei UI', 9)).pack(pady=(0, 15))

    btn_frame = ttk.Frame(frame)
    btn_frame.pack(fill=tk.X)

    ttk.Button(btn_frame, text="立即运行", style='Success.TButton',
              command=lambda: reminder_run_now(app), width=10).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_frame, text="取消本次", style='Danger.TButton',
              command=lambda: reminder_cancel(app), width=10).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_frame, text="关闭提醒", style='TButton',
              command=lambda: reminder_dismiss(app), width=10).pack(side=tk.LEFT)

    app._reminder_window.protocol("WM_DELETE_WINDOW", lambda: reminder_dismiss(app))


def reminder_run_now(app):
    """提醒窗口：立即运行"""
    if app._reminder_window:
        try:
            app._reminder_window.destroy()
        except Exception:
            pass
        app._reminder_window = None
    app._reminder_cancelled_time = None
    app._reminder_shown = False
    if not app.running:
        utils.prevent_sleep()
        app.start()


def reminder_cancel(app):
    """提醒窗口：取消本次运行（仅取消当前时间点，不影响其他时间点）"""
    if app._reminder_window:
        try:
            app._reminder_window.destroy()
        except Exception:
            pass
        app._reminder_window = None
    app._reminder_cancelled_time = app._next_run_time_str
    print(f"⏹ 用户取消了 {app._next_run_time_str} 的定时运行")


def reminder_dismiss(app):
    """提醒窗口：仅关闭弹窗，不影响定时运行"""
    if app._reminder_window:
        try:
            app._reminder_window.destroy()
        except Exception:
            pass
        app._reminder_window = None
    print(f"ℹ️ 已关闭提醒弹窗，定时任务 {app._next_run_time_str} 继续执行")


def update_ui_after_single(app):
    app.settings["auto_start"] = False
    config.save_settings(app.settings)


def reschedule_single(app, skipped_target):
    """单次模式取消后，自动跳到明天同一时间重新调度"""
    now = datetime.datetime.now()
    tomorrow = skipped_target + datetime.timedelta(days=1)
    h, m = map(int, app._schedule_times[0].split(":"))
    next_target = now.replace(hour=h, minute=m, second=0, microsecond=0) + datetime.timedelta(days=1)
    print(f"ℹ️ 单次定时已跳过，将在明天 {next_target.strftime('%Y-%m-%d %H:%M')} 重新执行")
    # 重新启动调度器
    app._reminder_shown = False
    app._reminder_cancelled_time = None
    start_scheduler(app)


def apply_auto_settings(app):
    """从设置窗口保存后应用自动任务设置"""
    if app.settings.get("auto_start", False):
        start_scheduler(app)
        # auto_start 启用时停止冷却监听（互斥）
        cooldown_watcher.stop_cooldown_watcher(app)
    else:
        if app._schedule_thread and app._schedule_thread.is_alive():
            app._scheduler_stop_event.set()
            app._schedule_thread.join(timeout=5)
        app._schedule_thread = None
        print("⏰ 已取消定时执行")
        if app._wake_timer_handle:
            utils.cancel_wake_timer(app._wake_timer_handle)
            app._wake_timer_handle = None
            app._last_wake_time = None

    # 冷却完立即运行监听
    if app.settings.get("cooldown_run_immediately", False):
        cooldown_watcher.start_cooldown_watcher(app)
    else:
        cooldown_watcher.stop_cooldown_watcher(app)
