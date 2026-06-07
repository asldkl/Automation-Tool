"""
自动化运行模块
处理任务启停、主流程执行、游戏操作、邮件通知和账号管理
"""
import os
import time
import datetime
import threading
import traceback
import html
import tkinter as tk
from tkinter import messagebox
import pyautogui

import config
import utils
import automation
import cooldown_manager
import machine_fingerprint
import email_notifier
import cooldown_watcher
import server_client
import scheduler
import asset_db

# 缓存 OCR 引擎实例（首次约2-3秒，后续毫秒级）
_ocr_engine = None


def _recognize_asset(app, asset_region):
    """使用 RapidOCR 识别屏幕指定区域的资产文本"""
    global _ocr_engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("⚠️ RapidOCR 未安装，跳过资产识别")
        return None

    x, y, w, h = asset_region
    if w <= 0 or h <= 0:
        return None

    try:
        import numpy as np
        import re
        screenshot = pyautogui.screenshot(region=(x, y, w, h))
        img_array = np.array(screenshot)

        if _ocr_engine is None:
            _ocr_engine = RapidOCR()
        result, _ = _ocr_engine(img_array)

        if not result:
            return None

        all_text = "".join(item[1] for item in result)
        match = re.search(r'(\d+\.?\d*)\s*([KMBkmb])', all_text)
        if match:
            number = match.group(1)
            suffix = match.group(2).upper()
            return f"{number}{suffix}"
        return all_text.strip() or None
    except Exception as e:
        print(f"⚠️ 资产识别失败: {e}")
        return None


def start_run(app):
    """启动自动化任务"""
    print(f"🔵 start() 被调用，self.running={app.running}，账号数={len(app.qq_account_images)}，boot_startup={app._is_boot_startup}")
    if app.running:
        return
    if not app.qq_account_images:
        messagebox.showwarning("未添加账号", "请先添加至少一个 QQ 账号截图！")
        return
    app.running = True
    app._stop_event.clear()
    app._user_stopped_cooldown = False  # 新运行开始，清除停止标志
    app._ignore_cooldown_this_run = False  # 手动启动时重置冷却跳过标志，确保冷却检查生效
    app._is_boot_startup = False  # 手动启动时重置开机标志
    app.current_step = 0
    app.progress['value'] = 0
    app.stats_label.config(text="")
    app.run_stats = {"total": 0, "success": 0, "fail": 0, "start_time": time.time()}
    app.start_btn.config(state='disabled')
    app.stop_btn.config(state='normal')
    app.log_area.configure(state='normal')
    app.log_area.delete('1.0', tk.END)
    app.log_area.configure(state='disabled')
    # 阻止系统睡眠，确保脚本执行不中断
    utils.prevent_sleep()
    # 启动心跳同步
    server_client.start_heartbeat(app)
    app.work_thread = threading.Thread(target=run_script_main, args=(app,), daemon=True)
    app.work_thread.start()


def stop_run(app):
    """停止自动化任务"""
    if not app.running:
        return
    app._stop_event.set()
    app.running = False
    # 标记用户主动停止，阻止冷却监听在短时间内重新触发
    app._user_stopped_cooldown = True
    app.start_btn.config(state='normal')
    app.stop_btn.config(state='disabled')
    print("\n⏹ 停止信号已发送，将尽快终止...")


def update_ui(app, step_increment=False, account_text=None, account_file=None):
    """更新界面显示"""
    if step_increment:
        app.current_step += 1
        app.progress['value'] = app.current_step
    if account_text:
        app.account_label.config(text=account_text)
    if account_file:
        app.current_account_file_label.config(text=account_file)


def set_operation(app, text):
    """从工作线程安全更新当前操作状态文字"""
    app.root.after(0, lambda: app.op_label.config(text=text))


def run_script_main(app):
    """主工作线程：遍历账号执行登录和游戏操作"""
    try:
        print(f"🟢 run_script_main() 已启动，ignore_cooldown={app._ignore_cooldown_this_run}")
        total = len(app.qq_account_images)
        qq_path = app.settings.get("qq_path", "")
        processed_accounts = []  # 记录已处理的QQ号名称

        # 每日首次运行时进行服务器验证
        today_str = datetime.date.today().isoformat()
        if not hasattr(app, '_last_validated_date') or app._last_validated_date != today_str:
            print("🔒 每日验证：正在连接服务器...")
            set_operation(app, "服务器验证中")
            allowed, expiry, error = server_client.validate_with_server(app)
            if allowed is True:
                app._last_validated_date = today_str
                print(f"✅ 每日验证通过，有效期至：{expiry}")
            elif allowed is False:
                print(f"❌ 验证失败：{error}")
                app.root.after(0, lambda: messagebox.showerror("验证失败",
                    f"每日验证未通过，程序将退出。\n\n"
                    f"原因：{error}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"本机机器指纹：\n\n"
                    f"  {machine_fingerprint.get_machine_id()}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━"))
                app.root.after(100, app.root.destroy)
                return
            else:
                print(f"❌ 服务器连接失败：{error}")
                app.root.after(0, lambda: messagebox.showerror("验证失败",
                    f"无法连接验证服务器，程序将退出。\n\n"
                    f"错误：{error}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"本机机器指纹：\n\n"
                    f"  {machine_fingerprint.get_machine_id()}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━"))
                app.root.after(100, app.root.destroy)
                return

        # 运行前先退出 QQ、WeGame 和三角洲行动，确保干净状态
        print("🧹 运行前清理：退出 QQ、WeGame 和三角洲行动...")
        set_operation(app, "清理进程")
        utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)
        utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=10)
        utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
        time.sleep(2)

        print("=" * 55)
        print("  QQ 登录 + WeGame 快捷登录 + 三角洲行动 多账号轮换脚本")
        print(f"  本轮将处理 {total} 个 QQ 账号")
        print("=" * 55)

        for i, img_path in enumerate(app.qq_account_images):
            if app._stop_event.is_set():
                break

            file_name = os.path.basename(img_path)
            current_account_name = file_name
            app._current_account_name = file_name

            # 冷却检查（定时任务/冷却到期触发时可跳过冷却检查，但开机启动时强制检查）
            if app._ignore_cooldown_this_run and not app._is_boot_startup:
                print(f"ℹ️ 冷却检查已跳过（冷却到期/定时任务触发）: {file_name}")
            if app.settings.get("enable_cooldown", False) and (not app._ignore_cooldown_this_run or app._is_boot_startup):
                cooling, next_time = cooldown_manager.is_cooling_down(file_name)
                if cooling:
                    print(f"⏸️ 账号 {file_name} 冷却中，跳过。下次运行时间：{next_time}")
                    processed_accounts.append(f"{file_name} (冷却中)")
                    server_client.update_account_status(app, file_name, "cooling")
                    continue

            acc_text = f"第 {i+1}/{total} 个账号"
            app.root.after(0, update_ui, app, False, acc_text, file_name)
            print(f"\n{'='*40}")
            print(f"    {acc_text}  -  {file_name}")
            print(f"{'='*40}")
            app.run_stats["total"] += 1
            account_failed = False
            account_interrupted = False
            server_client.update_account_status(app, file_name, "running")

            # 步骤1：启动 QQ 并登录
            if app._stop_event.is_set():
                account_interrupted = True
            if not account_interrupted:
                set_operation(app, f"启动 QQ ({i+1}/{total})")
                print("启动 QQ...")
                if not qq_path or not utils.start_app(qq_path, "QQ"):
                    print("❌ QQ 启动失败，跳过此账号")
                    account_failed = True

            if not account_failed:
                # 等待 QQ 窗口出现（含降级方案）
                qq_ready = False
                qq_activate_fail_count = 0
                qq_degrade_triggered = False
                for _ in range(30):
                    if app._stop_event.is_set(): break
                    if utils.activate_window_by_title("QQ", partial_match=True,
                                                       exclude_titles=["WeGame"]):
                        qq_ready = True
                        qq_activate_fail_count = 0
                        break
                    qq_activate_fail_count += 1
                    # 连续激活失败5次，启动降级方案：直接图像识别点击 QQ_ACCOUNT_SELECT
                    if qq_activate_fail_count >= 5:
                        qq_degrade_triggered = True
                        print("⚠️ QQ 窗口激活连续失败5次，启动降级方案：尝试图像识别...")
                        img_found = False
                        for img_retry in range(3):
                            if app._stop_event.is_set(): break
                            if utils.find_multiscale(config.QQ_ACCOUNT_SELECT, timeout=5):
                                img_found = True
                                qq_ready = True
                                print(f"✅ 降级方案成功：检测到 QQ_ACCOUNT_SELECT（第 {img_retry+1} 次），等待后续登录流程处理")
                                break
                            print(f"⚠️ 降级方案重试 ({img_retry+1}/3)...")
                            time.sleep(1)
                        if img_found:
                            break
                        else:
                            print(f"❌ 降级方案失败：QQ_ACCOUNT_SELECT 图像识别3次均未找到，账号 {current_account_name} 登录失败，跳过")
                            email_notifier.send_account_failure_email(app, current_account_name, "未启用", processed_accounts)
                            account_failed = True
                            break
                    time.sleep(0.5)
                if not qq_ready and not account_failed:
                    print("⚠️ 未检测到 QQ 窗口，继续尝试登录...")
                if qq_ready:
                    time.sleep(1)

            if not account_failed and app._stop_event.is_set():
                account_interrupted = True
            if not account_failed and not account_interrupted:
                set_operation(app, "QQ 快捷登录")
                print("开始 QQ 快捷登录...")
                if not utils.qq_quick_login(img_path):
                    print("❌ QQ 快捷登录失败，跳过此账号")
                    utils.kill_process(config.QQ_PROCESS)
                    account_failed = True
                else:
                    time.sleep(2)
                    # QQ 登录成功后关闭 QQ 窗口（保留后台进程供 WeGame 使用）
                    utils.close_window_by_title("QQ", partial_match=True)
                    time.sleep(1)

            # 步骤2：启动 WeGame 并快捷登录（使用当前 QQ 账号）
            if not account_failed and app._stop_event.is_set():
                account_interrupted = True
            if not account_failed and not account_interrupted:
                set_operation(app, "启动 WeGame")
                print("启动 WeGame...")
                if not config.WEGAME_PATH or not utils.start_app(config.WEGAME_PATH, "WeGame"):
                    print("❌ WeGame 启动失败，跳过此账号")
                    account_failed = True
                else:
                    time.sleep(3)

            if not account_failed and app._stop_event.is_set():
                account_interrupted = True
            if not account_failed and not account_interrupted:
                set_operation(app, "快捷登录 WeGame")
                print("开始快捷登录 WeGame ...")
                if not utils.wegame_quick_login():
                    print("❌ WeGame 快捷登录失败，跳过此账号")
                    utils.kill_process(config.WEGAME_PROCESS)
                    account_failed = True
                else:
                    time.sleep(3)

            # 步骤3：启动三角洲行动
            if not account_failed and app._stop_event.is_set():
                account_interrupted = True
            if not account_failed and not account_interrupted:
                set_operation(app, "查找三角洲游戏图标")
                print("\n--- 启动三角洲行动 ---")
                utils.activate_window_by_title("WeGame", partial_match=True)
                time.sleep(2)

                delta_icon_found = False
                for retry in range(3):
                    if app._stop_event.is_set(): break
                    if utils.find_and_click(config.DELTA_GAME_ICON, timeout=15):
                        delta_icon_found = True
                        break
                    print(f"⚠️ 未找到三角洲游戏图标，3秒后重试 ({retry+1}/3)...")
                    time.sleep(3)
                if not delta_icon_found:
                    print("❌ 多次重试后仍未找到三角洲游戏图标，跳过此账号")
                    utils.kill_process(config.WEGAME_PROCESS)
                    account_failed = True

            # 资产识别（三角洲图标后、启动按钮前）
            if not account_failed and not account_interrupted:
                settings = config.load_settings()
                if settings.get("enable_asset_recognition", False):
                    set_operation(app, "识别资产")
                    asset_region = settings.get("asset_region", [0, 0, 0, 0])
                    if asset_region and asset_region[2] > 0 and asset_region[3] > 0:
                        print(f"🔍 正在识别资产区域：{asset_region}")
                        import re
                        time.sleep(4)
                        asset_value = _recognize_asset(app, asset_region)
                        if asset_value:
                            print(f"💰 识别到资产：{asset_value}")
                            if app._current_account_name:
                                app._account_assets[app._current_account_name] = asset_value
                                # 记录资产历史
                                if app._current_account_name not in app._asset_history:
                                    app._asset_history[app._current_account_name] = []
                                app._asset_history[app._current_account_name].append({
                                    "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                    "value": asset_value
                                })
                                # 写入 SQLite 持久化记录
                                asset_db.record_asset(app._current_account_name, asset_value)
                                app.root.after(0, app._refresh_account_tree)
                        else:
                            print("ℹ️ 未识别到资产数值")
            time.sleep(2)# 资产识别缓冲

            if not account_failed:
                time.sleep(2)

                launch_found = False
                for retry in range(3):
                    if app._stop_event.is_set(): break
                    if utils.find_and_click(config.DELTA_LAUNCH_BTN, timeout=15):
                        launch_found = True
                        break
                    print(f"⚠️ 未找到启动按钮，3秒后重试 ({retry+1}/3)...")
                    time.sleep(3)
                if not launch_found:
                    print("❌ 多次重试后仍未找到启动按钮，跳过此账号")
                    utils.kill_process(config.WEGAME_PROCESS)
                    account_failed = True

            if not account_failed:
                print("✅ 三角洲正在启动，等待游戏窗口出现...")
                game_loaded = False
                delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
                for _ in range(45):
                    if app._stop_event.is_set():
                        break
                    for title in delta_titles:
                        if utils.activate_window_by_title(title, partial_match=True,
                                                           exclude_titles=["WeGame", "腾讯"]):
                            game_loaded = True
                            break
                    if game_loaded:
                        break
                    time.sleep(2)
                if game_loaded:
                    print("✅ 检测到游戏窗口，等待界面就绪...")
                    time.sleep(8)
                    extra_wait = app.settings.get("game_launch_wait", 0)
                    if extra_wait > 0:
                        print(f"⏳ 游戏已启动，额外等待 {extra_wait} 秒...")
                        time.sleep(extra_wait)
                else:
                    print("⚠️ 未检测到游戏窗口，继续尝试操作...")

                if not game_operations_wrapper(app):
                    if app._stop_event.is_set():
                        account_interrupted = True
                    else:
                        print("❌ 游戏内操作失败，跳过此账号")
                        account_failed = True
                if app._stop_event.is_set():
                    account_interrupted = True

            # 步骤4 + 清理：仅在未中断时执行
            if not account_interrupted:
                # 步骤4：关闭游戏和 WeGame，退出 QQ 和 WeGame 进程
                if not account_failed:
                    set_operation(app, "关闭三角洲游戏")
                    print("\n--- 关闭三角洲游戏 ---")
                    # 多次按 Alt+F4 确保游戏窗口关闭（处理确认弹窗等）
                    for _ in range(3):
                        pyautogui.hotkey('alt', 'f4')
                        time.sleep(0.5)
                    time.sleep(1)
                    delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
                    for title in delta_titles:
                        if app._stop_event.is_set(): break
                        utils.close_window_by_title(title, partial_match=True)
                    time.sleep(2)
                    utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)

                # 每轮结束后退出三角洲、QQ 和 WeGame，不保留后台
                set_operation(app, "清理进程")
                print("\n--- 退出三角洲行动、QQ 和 WeGame ---")
                utils.close_window_by_title("WeGame", partial_match=True)
                time.sleep(1)
                utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)
                utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
                utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=10)
                time.sleep(2)

            # 获取下次运行时间
            next_run_str = "未启用"
            if app.settings.get("enable_cooldown", False):
                _, next_run_str = cooldown_manager.is_cooling_down(current_account_name)
                next_run_str = next_run_str or "已冷却"

            if account_interrupted:
                # 用户手动停止，不记录冷却，不计入成功/失败
                print(f"⏹️ 账号 {current_account_name} 被用户中断，跳过冷却记录")
                processed_accounts.append(f"{current_account_name} (中断)")
                server_client.update_account_status(app, current_account_name, "idle")
                break
            elif account_failed:
                app.run_stats["fail"] += 1
                processed_accounts.append(f"{current_account_name} (失败)")
                server_client.update_account_status(app, current_account_name, "failed")
                # 立即发送失败邮件通知
                email_notifier.send_account_failure_email(app, current_account_name, next_run_str, processed_accounts)
            else:
                # 只有成功运行的账号才记录冷却时间
                if app.settings.get("enable_cooldown", False):
                    cd_hours = app.settings.get("cooldown_hours", 8)
                    cooldown_manager.record_run(current_account_name, cd_hours)
                app.run_stats["success"] += 1
                processed_accounts.append(f"{current_account_name} (成功)")
                server_client.update_account_status(app, current_account_name, "success")

            # 账号间隔等待：非最后一个账号且未被停止时，等待固定间隔再执行下一个
            if i < total - 1 and not app._stop_event.is_set():
                interval = app.settings.get("cooldown_delay_minutes", 1)
                if interval > 0:
                    print(f"⏳ 等待 {interval} 分钟后执行下一个账号...")
                    set_operation(app, f"账号间隔等待 ({interval}分钟)")
                    wait_seconds = interval * 60
                    waited = 0
                    while waited < wait_seconds and not app._stop_event.is_set():
                        chunk = min(5, wait_seconds - waited)
                        time.sleep(chunk)
                        waited += chunk
                    if app._stop_event.is_set():
                        break

        print("\n🎉 所有账号处理完毕！")
    except Exception as e:
        print(f"❌ 运行出错: {e}")
        traceback.print_exc()
        app.run_stats["error"] = str(e)
        email_notifier.send_failure_email(app, e, processed_accounts)
    finally:
        app.run_stats["processed_accounts"] = processed_accounts
        app.root.after(0, lambda: on_finish(app))


def game_operations_wrapper(app):
    """执行游戏内操作，返回 True=成功，False=失败"""
    result = automation.game_operations(
        app.settings, app._stop_event, lambda text: set_operation(app, text),
        update_ui_callback=lambda: app.root.after(0, update_ui, app, True))
    # 处理返回值：game_operations 可能返回 bool 或 (bool, dict)
    if isinstance(result, tuple):
        success, extra = result
        if success:
            if "sell_stats" in extra:
                app.run_stats["sell_stats"] = extra["sell_stats"]
            if "asset" in extra and app._current_account_name:
                app._account_assets[app._current_account_name] = extra["asset"]
                # 写入 SQLite 持久化记录
                asset_db.record_asset(app._current_account_name, extra["asset"])
                app.root.after(0, app._refresh_account_tree)
        return success
    return result


def sell_operations_wrapper(app):
    """一键出售流程：打开仓库，遍历售卖物品执行出售"""
    return automation.sell_operations(app.settings, app._stop_event, lambda text: set_operation(app, text))


def on_finish(app):
    """任务完成后处理：清理状态、恢复UI、发送通知"""
    app.running = False
    app._stop_event.clear()  # 清除工作线程停止信号，不影响调度器
    app._ignore_cooldown_this_run = False  # 重置冷却忽略标志
    app._is_boot_startup = False  # 重置开机启动标志
    # 停止心跳同步
    server_client.stop_heartbeat(app)
    app.start_btn.config(state='normal')
    app.stop_btn.config(state='disabled')
    app.progress['value'] = app.progress['maximum']

    # 用户手动停止时，清理可能残留的进程
    if app._user_stopped_cooldown:
        try:
            # 多次按 Alt+F4 确保三角洲游戏窗口关闭
            for _ in range(3):
                pyautogui.hotkey('alt', 'f4')
                time.sleep(0.5)
            time.sleep(1)
            utils.kill_process(config.DELTA_PROCESS, wait_exit=False)
            utils.kill_process(config.WEGAME_PROCESS, wait_exit=False)
            utils.kill_process(config.QQ_PROCESS, wait_exit=False)
        except Exception:
            pass

    # 恢复系统睡眠设置
    utils.allow_sleep()

    # 设置下一次唤醒定时器
    app._set_next_wake_timer()

    # 调度器健康检查：如果调度器线程已退出，重新启动
    if app.settings.get("auto_start", False):
        if not app._schedule_thread or not app._schedule_thread.is_alive():
            print("⚠️ 检测到调度器线程已退出，正在重新启动...")
            scheduler.start_scheduler(app)

    # 冷却监听健康检查：确保冷却到期监听线程正常运行
    if app.settings.get("cooldown_run_immediately", False):
        watcher_alive = (hasattr(app, '_cooldown_watcher_thread')
                        and app._cooldown_watcher_thread
                        and app._cooldown_watcher_thread.is_alive())
        if not watcher_alive:
            print("⚠️ 检测到冷却监听线程已退出，正在重新启动...")
            cooldown_watcher.start_cooldown_watcher(app)

    # 显示运行统计
    stats = app.run_stats
    elapsed = time.time() - stats["start_time"] if stats["start_time"] else 0
    if stats["total"] > 0 and elapsed > 0:
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        if h > 0:
            time_str = f"{h}时{m}分{s}秒"
        else:
            time_str = f"{m}分{s}秒"
        stats_text = (f"📊 本轮：共 {stats['total']} 个账号  "
                      f"✅ {stats['success']} 成功  "
                      f"❌ {stats['fail']} 失败  "
                      f"⏱ 耗时 {time_str}")
        app.stats_label.config(text=stats_text)
        print(f"\n{'='*40}")
        print(f"   {stats_text}")
        print(f"{'='*40}")

    # 发送邮件通知
    processed_accounts = stats.get("processed_accounts", [])
    email_notifier.send_run_report_email(app, stats, elapsed, processed_accounts)

    # 运行完成后延迟关机
    shutdown_delay = app.settings.get("post_run_shutdown_delay", 0)
    if shutdown_delay > 0:
        delay_seconds = shutdown_delay * 60
        utils.schedule_shutdown(delay_seconds)
        print(f"🔌 所有账号运行完毕，系统将在 {shutdown_delay} 分钟后关机")
        print(f"   如需取消关机，请在命令行执行: shutdown /a")


def get_account_next_run(app, account_name):
    """获取账号的下次运行时间描述"""
    if not app.settings.get("enable_cooldown", False):
        return "未启用"
    _, next_time = cooldown_manager.is_cooling_down(account_name)
    return next_time or "已冷却"


def build_accounts_html(app, processed_accounts):
    """构建已处理账号列表的 HTML（含下次运行时间）"""
    if not processed_accounts:
        return ""
    items = []
    for acc in processed_accounts:
        # acc 格式: "xxx.png (成功)" 或 "xxx.png (失败)" 或 "xxx.png (冷却中)"
        next_run = "未启用"
        if app.settings.get("enable_cooldown", False):
            # 提取账号文件名（去掉状态后缀）
            account_name = acc.split(" (")[0] if " (" in acc else acc
            next_run = get_account_next_run(app, account_name)
        items.append(f"<li>{html.escape(acc)}　｜　下次运行：{html.escape(next_run)}</li>")
    accounts_html = "".join(items)
    return f"""
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">已处理账号</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;"><ul style="margin:0;padding-left:20px;">{accounts_html}</ul></td></tr>"""
