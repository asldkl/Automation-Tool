"""
冷却到期监听模块
监控账号冷却状态，冷却到期时自动触发任务执行
"""
import os
import time
import datetime
import threading
import traceback

import config
import utils
import cooldown_manager
import email_notifier


def start_cooldown_watcher(app):
    """启动冷却到期监听线程（cooldown_run_immediately 模式）"""
    if hasattr(app, '_cooldown_watcher_thread') and app._cooldown_watcher_thread and app._cooldown_watcher_thread.is_alive():
        return

    # 首次启用时，为所有没有冷却记录的账号记录一次冷却时间
    # 防止所有账号在30秒内全部执行
    if app.settings.get("enable_cooldown", False):
        cd_hours = app.settings.get("cooldown_hours", 8)
        all_cd = cooldown_manager.get_all_cooldowns()
        for acc_idx, img_path in enumerate(app.qq_account_images):
            file_name = os.path.basename(img_path)
            # 用两种 key 检查，避免误判
            short_name = file_name.split(":")[-1] if ":" in file_name else file_name
            has_record = file_name in all_cd or short_name in all_cd or img_path in all_cd
            if has_record:
                continue
            cooling, _ = cooldown_manager.is_cooling_down(file_name)
            if not cooling:
                # 用 _get_cooldown_key 的逻辑获取正确的 key
                cd_key = short_name if short_name in all_cd else file_name
                cooldown_manager.record_run(cd_key, cd_hours)
                print(f"📝 首次启用冷却监听，为 {cd_key} 记录冷却时间")

    app._cooldown_watcher_stop = threading.Event()
    app._cooldown_watcher_thread = threading.Thread(target=cooldown_watcher_loop, args=(app,), daemon=True)
    app._cooldown_watcher_thread.start()
    print("👀 冷却到期监听已启动，冷却结束后将自动执行任务")


def stop_cooldown_watcher(app):
    """停止冷却到期监听"""
    if hasattr(app, '_cooldown_watcher_stop') and app._cooldown_watcher_stop:
        app._cooldown_watcher_stop.set()


def restart_cooldown_watcher(app):
    """冷却监听异常退出后的恢复入口"""
    if not hasattr(app, '_cooldown_watcher_stop') or app._cooldown_watcher_stop is None:
        return
    if not app._cooldown_watcher_stop.is_set() and app.settings.get("cooldown_run_immediately", False):
        print("🔄 正在重启冷却监听...")
        app._cooldown_watcher_thread = None
        start_cooldown_watcher(app)


def cooldown_watcher_loop(app):
    """冷却到期监听循环：每30秒检查一次，有账号冷却到期则自动执行"""
    last_trigger_minute = None
    try:
        while not app._cooldown_watcher_stop.is_set():
            try:
                # 用户主动停止后，等待30秒再恢复监听（防止立即重新触发）
                if app._user_stopped_cooldown:
                    for _ in range(6):  # 30秒 = 6 * 5秒
                        if app._cooldown_watcher_stop.is_set():
                            return
                        time.sleep(5)
                    app._user_stopped_cooldown = False
                    print("ℹ️ 用户停止冷却期已过，恢复冷却监听")
                    continue

                # 更新唤醒定时器（基于最早冷却到期时间）
                app._update_cooldown_wake_timer()

                # 自动移除已过期的冷却记录
                expired = cooldown_manager.remove_expired_cooldowns()
                if expired:
                    print(f"🔔 冷却完成，已从冷却列表移除：{', '.join(expired)}")

                if not app.running and app.qq_account_images:
                    now = datetime.datetime.now()
                    current_minute = now.strftime("%Y-%m-%d %H:%M")
                    # 同一分钟内不重复触发
                    if current_minute != last_trigger_minute:
                        has_ready = check_any_account_ready(app)
                        if has_ready:
                            last_trigger_minute = current_minute
                            print("🔔 检测到账号冷却到期，自动执行任务...")

                            # 发送冷却到期邮件提醒
                            ready_list = []
                            cd_data = cooldown_manager._load_data()
                            for img_path in app.qq_account_images:
                                fname = os.path.basename(img_path)
                                cd_name = img_path if img_path in cd_data else fname
                                cooling, _ = cooldown_manager.is_cooling_down(cd_name)
                                if not cooling:
                                    ready_list.append(cd_name)
                            if ready_list:
                                email_notifier.send_cooldown_ready_email(app, ready_list)

                            # 直接设置标志位并安全调用 start()
                            app._ignore_cooldown_this_run = True
                            utils.prevent_sleep()

                            print("🚀 冷却到期，正在启动自动任务...")

                            # 删除定时任务兜底（监听线程已成功触发，不需要定时任务了）
                            try:
                                utils.remove_cooldown_scheduled_task()
                            except Exception:
                                pass

                            # 直接在主线程调度 start()，这是最可靠的方式
                            app.root.after(0, app.start)

                            # 等待并验证任务是否成功启动
                            time.sleep(3)
                            if not app.running:
                                print("⚠️ 首次启动未生效，正在进行二次重试...")
                                app.root.after(0, app.start)
                                time.sleep(3)
                                if not app.running:
                                    print("❌ 自动启动失败，请检查程序状态或手动按 F1")
                                else:
                                    print("✅ 二次重试成功，任务已启动")
                            else:
                                print("✅ 自动任务已成功启动")

            except Exception as inner_e:
                print(f"⚠️ 冷却监听异常（将继续运行）: {inner_e}")
                traceback.print_exc()
            # 等待30秒，但分段检查停止信号以支持快速退出
            for _ in range(6):
                if app._cooldown_watcher_stop.is_set():
                    break
                time.sleep(5)
    except Exception as e:
        print(f"❌ 冷却监听线程异常退出: {e}")
        traceback.print_exc()
        # 异常恢复机制
        if not app._cooldown_watcher_stop.is_set() and app.settings.get("cooldown_run_immediately", False):
            print("🔄 冷却监听线程将在 5 秒后自动重启...")
            app.root.after(5000, lambda: restart_cooldown_watcher(app))


def check_any_account_ready(app):
    """检查是否有账号冷却到期且未在冷却中且未暂停，返回是否有可用账号"""
    if not app.settings.get("cooldown_run_immediately", False):
        return False
    ready_accounts = []
    cd_data = cooldown_manager._load_data()
    for img_path in app.qq_account_images:
        file_name = os.path.basename(img_path)
        short_name = file_name.split(":")[-1] if ":" in file_name else file_name
        # 优先用短名称（暂停状态通常记录在短名称上）
        if short_name in cd_data:
            cd_name = short_name
        elif img_path in cd_data:
            cd_name = img_path
        else:
            cd_name = file_name
        # 跳过暂停的账号
        if cooldown_manager.is_account_paused(cd_name):
            continue
        cooling, next_time = cooldown_manager.is_cooling_down(cd_name)
        if not cooling:
            ready_accounts.append(cd_name)
    # 只在状态变化时打印日志，避免重复输出
    ready_key = tuple(sorted(ready_accounts))
    if ready_accounts:
        if not hasattr(app, '_last_ready_key') or app._last_ready_key != ready_key:
            print(f"🔍 发现 {len(ready_accounts)} 个账号就绪：{', '.join(ready_accounts)}")
            app._last_ready_key = ready_key
        return True
    else:
        if hasattr(app, '_last_ready_key') and app._last_ready_key:
            app._last_ready_key = None
    return False
