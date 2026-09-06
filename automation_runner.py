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
import account_manager
import cooldown_watcher
import server_client
import scheduler
import asset_db
import driver_keyboard
import custom_ops

# 三角洲行动窗口标题关键词
DELTA_TITLES = ["三角洲行动", "DeltaForce", "Delta Force", "三角洲", "Delta"]

# 统一使用 cooldown_manager.normalize_key
_get_cooldown_key = cooldown_manager.normalize_key


def _ensure_wegame_focused():
    """确保 WeGame 窗口在前台，失去焦点时自动重新激活。返回 True=已聚焦"""
    import win32gui
    hwnd = utils.find_window_by_title("WeGame", partial_match=True)
    if not hwnd:
        return False
    try:
        if win32gui.IsIconic(hwnd):
            import win32con
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.3)
        foreground = win32gui.GetForegroundWindow()
        if foreground != hwnd:
            utils.activate_window_by_title("WeGame", partial_match=True)
            time.sleep(0.3)
        return True
    except Exception:
        return utils.activate_window_by_title("WeGame", partial_match=True)


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
        screenshot.close()

        if _ocr_engine is None:
            _ocr_engine = RapidOCR()
        result, _ = _ocr_engine(img_array)

        if not result:
            return None

        all_text = "".join(item[1] for item in result)
        # 提取数字 + 单位(KMB)
        match = re.search(r'([\d,.]+)\s*([KMBkmb])', all_text)
        if match:
            raw_number = match.group(1)
            suffix = match.group(2).upper()
            # OCR 可能把逗号识别成小数点（如 66.271K 实际是 66,271K）
            # K 单位不应有小数点，M/B 单位可以
            if suffix == "K":
                raw_number = raw_number.replace(".", "").replace(",", "")
            else:
                raw_number = raw_number.replace(",", "")
            return _format_asset_display(raw_number, suffix)
        # 降级：清理非数字/KMB字符后重试
        cleaned = re.sub(r'[^0-9.,KMBkmb]', '', all_text)
        match2 = re.search(r'([\d,.]+)\s*([KMBkmb])', cleaned)
        if match2:
            raw_number = match2.group(1)
            suffix = match2.group(2).upper()
            if suffix == "K":
                raw_number = raw_number.replace(".", "").replace(",", "")
            else:
                raw_number = raw_number.replace(",", "")
            return _format_asset_display(raw_number, suffix)
        return None
    except Exception as e:
        print(f"⚠️ 资产识别失败: {e}")
        return None


def _format_asset_display(raw_number, suffix):
    """格式化资产显示：K 用逗号分隔，M 用整数（无小数点）"""
    try:
        value = float(raw_number)
        if suffix == "K":
            # K 单位：用逗号分隔显示，如 78,394K
            return f"{int(value):,}K"
        elif suffix == "M":
            # M 单位：整数显示，如 78M、2100M
            return f"{int(value)}M"
        else:
            return f"{raw_number}{suffix}"
    except ValueError:
        return f"{raw_number}{suffix}"


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
    # 不重置 _ignore_cooldown_this_run，由调用方（冷却监听/信号触发）设置
    app._is_boot_startup = False  # 手动启动时重置开机标志
    # 取消待执行的关机计划（防止冷却触发新运行时意外关机）
    utils.cancel_shutdown()
    # 运行自动化时隐藏主窗口到托盘，防止遮挡游戏画面
    app._hide_to_tray()
    app.current_step = 0
    app.progress['value'] = 0
    app.stats_label.config(text="")
    app.run_stats = {"total": 0, "success": 0, "fail": 0, "start_time": time.time()}
    app._last_account_error = ""
    # 连续失败计数不随本轮重置（跨轮累计，成功或手动恢复才清零）
    app._cooldown_wait_done = False  # 重置冷却等待标志
    app.start_btn.config(state='disabled')
    app.stop_btn.config(state='normal')
    app.log_area.configure(state='normal')
    app.log_area.delete('1.0', tk.END)
    app.log_area.configure(state='disabled')
    # 创建新的日志文件（按日期文件夹+运行时间命名）
    app._set_run_log_file()
    # 阻止系统睡眠，确保脚本执行不中断
    utils.prevent_sleep()
    # 启动心跳同步
    server_client.start_heartbeat(app)
    app.work_thread = threading.Thread(target=run_script_main, args=(app,), daemon=True)
    app.work_thread.start()
    # 启动日志遮罩顶行运行时长刷新
    try:
        app._start_overlay_ticker()
    except Exception:
        pass


def stop_run(app):
    """停止自动化任务（不阻塞 UI，工作线程自行退出）"""
    if not app.running:
        return
    app._stop_event.set()
    # 标记用户主动停止，阻止冷却监听在短时间内重新触发
    app._user_stopped_cooldown = True
    app.start_btn.config(state='normal')
    app.stop_btn.config(state='disabled')
    print("\n⏹ 停止信号已发送，将尽快终止...")


def start_single_account_run(app, img_path):
    """单独运行一个账号（右键菜单触发），运行完进入冷却，暂停账号保持暂停
    不受冷却和暂停限制，用于快速登录进入游戏大厅手动操作"""
    if app.running:
        return
    file_name = _get_cooldown_key(img_path)
    # 记录暂停状态（运行完后恢复），但不阻止运行
    was_paused = cooldown_manager.is_account_paused(file_name)
    app._single_account_mode = True
    app._single_account_was_paused = was_paused
    app._single_account_img_path = img_path
    # 启动运行（只跑这一个账号）
    app.running = True
    app._stop_event.clear()
    app._user_stopped_cooldown = False
    app._ignore_cooldown_this_run = False
    app._is_boot_startup = False
    app._cooldown_wait_done = False  # 重置冷却等待标志：单账号结束后只跑已到期账号、不进入等待
    app.current_step = 0
    app.progress['value'] = 0
    app.stats_label.config(text="")
    app.run_stats = {"total": 0, "success": 0, "fail": 0, "start_time": time.time()}
    app._last_account_error = ""
    # 连续失败计数不随本轮重置（跨轮累计，成功或手动恢复才清零）
    # 运行自动化时隐藏主窗口到托盘，防止遮挡游戏画面
    app._hide_to_tray()
    app.start_btn.config(state='disabled')
    app.stop_btn.config(state='normal')
    app.log_area.configure(state='normal')
    app.log_area.delete('1.0', tk.END)
    app.log_area.configure(state='disabled')
    # 创建新的日志文件（按日期文件夹+运行时间命名）
    app._set_run_log_file()
    utils.prevent_sleep()
    server_client.start_heartbeat(app)
    app.work_thread = threading.Thread(target=_run_single_account_main, args=(app, img_path), daemon=True)
    app.work_thread.start()
    # 启动日志遮罩顶行运行时长刷新
    try:
        app._start_overlay_ticker()
    except Exception:
        pass


def _run_single_account_main(app, img_path):
    """单账号运行主函数：登录 → 进入游戏 → 按 Tab → 结束（不退出游戏）"""
    processed_accounts = []
    try:
        file_name = _get_cooldown_key(img_path)
        app._current_account_name = file_name
        app._asset_hub_value = None  # 单账号无大厅候选识别
        total = len(app.qq_account_images)
        try:
            app._set_overlay_status(1, file_name)  # 更新日志遮罩顶行
        except Exception:
            pass
        print(f"🟢 单账号运行：{file_name}")
        utils.cancel_shutdown()  # 取消待执行的关机计划

        if not _validate_daily(app):
            return

        _cleanup_processes(app)
        run_insert = _make_run_insert(app)   # 模板插入步骤执行回调

        account_failed = False
        account_interrupted = False

        # 步骤1：登录 WeGame
        if not _login_account(app, file_name, 0, total, processed_accounts):
            account_failed = True

        # 步骤2：找到三角洲图标并启动游戏
        if not account_failed and not app._stop_event.is_set():
            print("🔍 查找三角洲游戏图标...")
            if not automation._hook(run_insert, "DELTA_GAME_ICON", "before"):
                print("❌ 三角洲游戏图标 插入步骤(点击前)失败")
                account_failed = True
            elif not utils.find_and_click_smart(config.DELTA_GAME_ICON, timeout=10):
                print("❌ 未找到三角洲游戏图标")
                account_failed = True
            elif not automation._hook(run_insert, "DELTA_GAME_ICON", "after"):
                print("❌ 三角洲游戏图标 插入步骤(点击后)失败")
                account_failed = True
            else:
                time.sleep(2)
                # 点击启动按钮
                if not automation._hook(run_insert, "DELTA_LAUNCH_BTN", "before"):
                    print("❌ 启动按钮 插入步骤(点击前)失败")
                    account_failed = True
                elif not utils.find_and_click_smart(config.DELTA_LAUNCH_BTN, timeout=10):
                    print("❌ 未找到启动按钮")
                    account_failed = True
                elif not automation._hook(run_insert, "DELTA_LAUNCH_BTN", "after"):
                    print("❌ 启动按钮 插入步骤(点击后)失败")
                    account_failed = True
                else:
                    print("✅ 游戏启动中，等待进入大厅...")
                    time.sleep(1)
                    # 查找并点击「确定」按钮（可选）
                    if automation._hook(run_insert, "ENSURE", "before"):
                        if utils.find_and_click_smart(config.ENSURE, timeout=5):
                            print("✅ 已点击确认按钮")
                            automation._hook(run_insert, "ENSURE", "after")
                        else:
                            print("ℹ️ 无需确认，继续等待游戏窗口")
                    else:
                        print("ℹ️ 确定按钮 插入步骤(点击前)失败，跳过")
                    # 等待游戏窗口出现
                    game_loaded = False
                    for _ in range(30):
                        if app._stop_event.is_set():
                            break
                        for title in DELTA_TITLES:
                            if utils.activate_window_by_title(title, partial_match=True,
                                                               exclude_titles=["WeGame", "腾讯"]):
                                game_loaded = True
                                break
                        if game_loaded:
                            break
                        time.sleep(2)

                    if game_loaded:
                        time.sleep(5)  # 等待游戏界面加载
                        automation._ensure_game_focused()

                        # 观察账号：进入烽火地带前识别观察状态入口（可选模板，最多3次重试，失败间隔4秒；仍失败则跳过）
                        if _is_observe_account(app, file_name) and os.path.exists(config.resolve_template_path(config.Observe)):
                            print("🔍 观察账号：识别观察状态入口...")
                            observe_found = False
                            observe_interrupted = False
                            if not automation._hook(run_insert, "Observe", "before"):
                                print("⚠️ 观察状态入口 插入步骤(点击前)失败，跳过")
                            else:
                                for retry in range(5):
                                    if app._stop_event.is_set():
                                        observe_interrupted = True
                                        break
                                    if utils.find_and_click_smart(config.Observe, timeout=8):
                                        observe_found = True
                                        break
                                    print(f"⚠️ 未找到观察状态入口，4秒后重试 ({retry + 1}/5)...")
                                    time.sleep(4)
                            if observe_interrupted:
                                account_interrupted = True
                            elif observe_found:
                                if automation._hook(run_insert, "Observe", "after"):
                                    print("✅ 已进入观察状态入口")
                                else:
                                    print("⚠️ 观察状态入口 插入步骤(点击后)失败，继续主流程")
                            else:
                                print("ℹ️ 5次重试后仍未找到观察状态入口，跳过（不影响后续流程）")
                            if not observe_interrupted:
                                utils.human_pause()

                        # 进入烽火地带（单账号运行：最多重试 3 次）
                        print("进入烽火地带...")
                        hazard_found = False
                        if not automation._hook(run_insert, "Hazard_Operations", "before"):
                            print("❌ 烽火地带入口 插入步骤(点击前)失败")
                        else:
                            for retry in range(3):
                                if app._stop_event.is_set():
                                    account_interrupted = True
                                    break
                                if utils.find_and_click_smart(config.Hazard_Operations, timeout=15):
                                    hazard_found = True
                                    break
                                print(f"⚠️ 未找到烽火地带图标，5秒后重试 ({retry + 1}/3)...")
                                automation._ensure_game_focused()
                                time.sleep(5)
                        if account_interrupted:
                            pass  # 用户中断，交给后面统一处理
                        elif not hazard_found:
                            print("❌ 3次重试后仍未找到烽火地带入口（或插入步骤失败）")
                            account_failed = True
                        elif not automation._hook(run_insert, "Hazard_Operations", "after"):
                            print("❌ 烽火地带入口 插入步骤(点击后)失败")
                            account_failed = True
                        else:
                            time.sleep(5)

                            # 按 Space、Space、Tab 进入特勤处（与主流程一致）
                            print("进入大厅...")
                            pyautogui.press("Space")
                            time.sleep(0.5)
                            pyautogui.press("Space")
                            time.sleep(0.8)
                            pyautogui.press("Tab")
                            time.sleep(1)

                            # 等待1秒后进行资产识别
                            _recognize_and_store_asset(app, stage="单账号")

                            print("✅ 已进入游戏大厅，用户可自行操作。程序不会退出游戏。")
                            processed_accounts.append(f"{file_name} (已登录)")
                    else:
                        print("❌ 未检测到游戏窗口")
                        account_failed = True

        if app._stop_event.is_set():
            account_interrupted = True

        if account_failed:
            processed_accounts.append(f"{file_name} (登录失败)")
        elif not account_interrupted:
            # 单账号运行成功：如果在冷却中则保留剩余时间，不重置冷却
            if app.settings.get("enable_cooldown", False):
                is_cooling, remaining = cooldown_manager.is_cooling_down(file_name)
                if not is_cooling:
                    cd_hours = app.settings.get("cooldown_hours", 8)
                    cooldown_manager.record_run(file_name, cd_hours)
                    print(f"✅ 账号 {file_name} 单账号运行完成，记录冷却 {cd_hours} 小时")
                else:
                    print(f"ℹ️ 账号 {file_name} 原有冷却剩余 {remaining}，保持不变")
            processed_accounts.append(f"{file_name} (成功)")

    except Exception as e:
        print(f"❌ 运行出错: {e}")
        traceback.print_exc()
    finally:
        app.run_stats["processed_accounts"] = processed_accounts
        app.root.after(0, lambda: _on_single_account_finish(app))


def _on_single_account_finish(app):
    """单账号运行完成"""
    if hasattr(app, '_single_account_img_path') and app._single_account_img_path:
        file_name = _get_cooldown_key(app._single_account_img_path)
        # 如果是暂停账号，保持暂停状态
        if getattr(app, '_single_account_was_paused', False):
            cooldown_manager.set_account_paused(file_name, True)
            print(f"⏸️ 账号 {file_name} 原为暂停状态，已恢复暂停")
    # 检查是否有其他冷却完成的账号，优先运行（在后台线程执行，避免冻结 UI）。
    # 检查期间保持 app.running=True（结束后才 on_finish），防止用户手动「开始」或
    # 冷却监听线程与本检查线程同时驱动键鼠（双流程竞态）
    if app.settings.get("enable_cooldown", False) and not app._stop_event.is_set():
        app.running = True

        def _check_and_run():
            try:
                processed = []
                _wait_and_run_nearby_cooldowns(app, processed)
            finally:
                try:
                    app.root.after(0, lambda: _finish_after_cooldown_check(app))
                except Exception:
                    _finish_after_cooldown_check(app)

        threading.Thread(target=_check_and_run, daemon=True).start()
    else:
        # 先调用 on_finish（内部会检查 _single_account_mode 跳过邮件和关机），再清除标志
        on_finish(app)
        app._single_account_mode = False


def _finish_after_cooldown_check(app):
    """单账号结束后的后台冷却检查收尾（主线程执行）"""
    # 先调用 on_finish（内部会检查 _single_account_mode 跳过邮件和关机），再清除标志
    on_finish(app)
    app._single_account_mode = False


def set_operation(app, text):
    """从工作线程安全更新当前操作状态文字"""
    app.root.after(0, lambda: app.op_label.config(text=text))


def _make_run_insert(app):
    """构建模板「插入步骤」执行回调 ri(var_name, timing)，供登录/启动/游戏内流程注入。
    回调内部以真实 app 上下文执行；某模板未配置或时序不符时返回 True（不执行）。
    异常时返回 False（与 run_for_account 内部「异常=失败」语义一致，调用方按该模板失败处理）"""
    import template_insert_steps as _tis
    def run_insert(var_name, timing):
        account = getattr(app, "_current_account_name", "") or ""
        try:
            return bool(_tis.run_for_account(app.settings, app._stop_event, account,
                                             var_name, timing))
        except Exception as e:
            print(f"❌ 模板[{var_name}]插入步骤回调异常：{e}")
            return False
    return run_insert


def _validate_daily(app):
    """每日首次运行时进行服务器验证，返回 True=通过，False=应退出"""
    today_str = datetime.date.today().isoformat()
    if hasattr(app, '_last_validated_date') and app._last_validated_date == today_str:
        return True
    print("🔒 每日验证：正在连接服务器...")
    set_operation(app, "服务器验证中")
    allowed, expiry, error = server_client.validate_with_server(app)
    if allowed is True:
        app._last_validated_date = today_str
        print(f"✅ 每日验证通过，有效期至：{expiry}")
        return True
    fingerprint = machine_fingerprint.get_machine_id()
    if allowed is False:
        print(f"❌ 验证失败：{error}")
        app.root.after(0, lambda: messagebox.showerror("验证失败",
            f"每日验证未通过，程序将退出。\n\n原因：{error}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n本机机器指纹：\n\n  {fingerprint}\n\n━━━━━━━━━━━━━━━━━━━━"))
    else:
        print(f"❌ 服务器连接失败：{error}")
        app.root.after(0, lambda: messagebox.showerror("验证失败",
            f"无法连接验证服务器，程序将退出。\n\n错误：{error}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n本机机器指纹：\n\n  {fingerprint}\n\n━━━━━━━━━━━━━━━━━━━━"))
    app.root.after(100, app.root.destroy)
    return False


def _cleanup_processes(app):
    """运行前清理 QQ、WeGame 和三角洲行动进程（并行杀进程，减少等待）"""
    print("🧹 运行前清理：退出 QQ、WeGame 和三角洲行动...")
    set_operation(app, "清理进程")
    import threading
    threads = []
    for proc_name in [config.DELTA_PROCESS, config.QQ_PROCESS, config.WEGAME_PROCESS]:
        t = threading.Thread(target=utils.kill_process, args=(proc_name,), kwargs={"wait_exit": True, "max_wait": 10}, daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join(timeout=12)
    time.sleep(2)


def _login_account(app, account_name, i, total, processed_accounts):
    """WeGame 直接登录流程（使用 Interception 驱动级键盘输入）：
    1. 杀掉 QQ/WeGame/三角洲进程
    2. 打开 WeGame → 等待窗口出现
    3. 图像识别双击 account_select（左偏 15px）→ 删除旧账号
    4. Interception 输入账号
    5. 图像识别点击 Input → Interception 输入密码
    6. 图像识别点击 Sign-in 完成登录
    返回 True=成功"""
    run_insert = _make_run_insert(app)   # 模板插入步骤执行回调（含 WeGame 登录模板）
    set_operation(app, f"WeGame 登录 ({i+1}/{total})")
    # 登录验证码自动处理总开关（OCR 判定→滑块YOLO/AI视觉分发，详见 captcha_router）
    _captcha_auto_enabled = bool(app.settings.get("captcha_auto_enabled", False))

    note_data = app._account_notes.get(account_name, {})
    if isinstance(note_data, dict):
        login_account = note_data.get("account", "").strip()
        login_password = note_data.get("password", "").strip()
    else:
        login_account = ""
        login_password = ""

    if not login_account:
        msg = "未设置游戏账号"
        print(f"❌ 账号 {account_name} {msg}，跳过")
        app._last_account_error = msg
        return False
    if not login_password:
        msg = "未设置游戏密码"
        print(f"❌ 账号 {account_name} {msg}，跳过")
        app._last_account_error = msg
        return False

    kb_backend = driver_keyboard.get_backend()
    print(f"⌨️ 键盘后端: {kb_backend}")

    # 检查 Interception 驱动是否可用，不可用时根据设置决定是否重启
    if not driver_keyboard.is_available():
        if app.settings.get("restart_on_interception_fail", False):
            print("❌ Interception 驱动不可用，尝试重新加载驱动服务...")
            import subprocess
            driver_restored = False
            # 先尝试重启驱动服务（不重启电脑），通常可恢复
            try:
                subprocess.run(["sc", "stop", "interception"], capture_output=True, timeout=5,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(1)
                result = subprocess.run(["sc", "start", "interception"], capture_output=True, timeout=5, text=True,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                time.sleep(1)
                if driver_keyboard.is_available():
                    print("✅ Interception 驱动服务已重新加载，继续执行")
                    driver_restored = True
                else:
                    print(f"⚠️ sc start 输出: {result.stdout.strip()}{result.stderr.strip()}")
            except Exception as e:
                print(f"⚠️ 驱动服务重启失败 ({e})", end="")
            if not driver_restored:
                print("，即将重启电脑...")
                subprocess.run(["shutdown", "/r", "/t", "10", "/c", "Interception 驱动不可用，自动重启以重新加载驱动"], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
                app.root.after(0, lambda: messagebox.showinfo("提示", "Interception 驱动不可用，已尝试重启驱动服务未成功，系统将在 10 秒后自动重启电脑以重新加载驱动。"))
                app._stop_event.set()  # 阻止后续账号执行（避免 cancel_shutdown 中断重启计划）
                return False
            # driver_restored=True 时继续走正常登录流程
        else:
            print("❌ Interception 驱动不可用，请安装驱动或在设置中开启「Interception 失败时自动重启电脑」")
            app._last_account_error = "Interception 驱动不可用"
            return False

    max_retries = 3
    for attempt in range(max_retries):
        if app._stop_event.is_set():
            return False

        # 步骤1：杀掉所有相关进程
        print(f"🧹 清理进程 (尝试 {attempt+1}/{max_retries})...")
        utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=5)
        utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=5)
        utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=5)
        time.sleep(1)

        if app._stop_event.is_set():
            return False

        # 步骤2：打开 WeGame
        set_operation(app, "启动 WeGame")
        print("🚀 启动 WeGame...")
        if not config.WEGAME_PATH or not utils.start_app(config.WEGAME_PATH, "WeGame"):
            msg = "WeGame 启动失败，请检查路径设置"
            print(f"❌ {msg}")
            app._last_account_error = msg
            return False
        time.sleep(1)

        # 等待 WeGame 窗口出现
        if not utils.wait_for_window("WeGame", timeout=10):
            print(f"⚠️ WeGame 窗口未出现，重试 ({attempt+1}/{max_retries})...")
            continue

        if app._stop_event.is_set():
            return False

        # 确保 WeGame 窗口可见（最小化时恢复）
        hwnd_wegame = utils.find_window_by_title("WeGame", partial_match=True)
        if hwnd_wegame:
            try:
                import win32gui, win32con
                if win32gui.IsIconic(hwnd_wegame):
                    win32gui.ShowWindow(hwnd_wegame, win32con.SW_RESTORE)
                    time.sleep(0.3)
            except Exception:
                pass

        # 步骤3：图像识别双击 account_select（左偏 15px，选中旧账号文本）
        set_operation(app, "选择账号输入框")
        print("🔍 查找账号选择框...")
        if not automation._hook(run_insert, "ACCOUNT_SELECT", "before"):
            print(f"⚠️ 账号选择框 插入步骤(点击前)失败，重试 ({attempt+1}/{max_retries})...")
            continue
        if not utils.find_and_click_smart(config.ACCOUNT_SELECT, clicks=2, timeout=10, x_offset=-15):
            print(f"⚠️ 未找到账号选择框，重试 ({attempt+1}/{max_retries})...")
            continue
        if not automation._hook(run_insert, "ACCOUNT_SELECT", "after"):
            print(f"⚠️ 账号选择框 插入步骤(点击后)失败，重试 ({attempt+1}/{max_retries})...")
            continue
        print("✅ 已双击账号选择框")
        time.sleep(0.3)

        if app._stop_event.is_set():
            return False

        # 删除旧账号文本（Ctrl+A 全选 + Backspace）
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyautogui.press('backspace')
        time.sleep(0.2)

        # 步骤4：Interception 输入账号（确保 WeGame 窗口聚焦）
        set_operation(app, "输入账号")
        print(f"⌨️ 输入账号: {login_account}")
        if not _ensure_wegame_focused():
            print(f"⚠️ WeGame 窗口失去焦点，重试 ({attempt+1}/{max_retries})...")
            continue
        if not driver_keyboard.send_string(login_account, interval=0.02):
            print(f"⚠️ 账号输入失败，重试 ({attempt+1}/{max_retries})...")
            continue
        time.sleep(0.3)

        if app._stop_event.is_set():
            return False

        # 步骤5：图像识别点击 Input（密码输入框）
        set_operation(app, "点击密码输入框")
        print("🔍 识别密码输入框...")
        if not automation._hook(run_insert, "IMAGE_INPUT_FIELD", "before"):
            print(f"⚠️ 密码输入框 插入步骤(点击前)失败，重试 ({attempt+1}/{max_retries})...")
            continue
        if not utils.find_and_click_smart(config.IMAGE_INPUT_FIELD, timeout=10):
            print(f"⚠️ 未找到密码输入框，重试 ({attempt+1}/{max_retries})...")
            continue
        if not automation._hook(run_insert, "IMAGE_INPUT_FIELD", "after"):
            print(f"⚠️ 密码输入框 插入步骤(点击后)失败，重试 ({attempt+1}/{max_retries})...")
            continue
        print("✅ 已点击密码输入框")
        time.sleep(0.2)

        if app._stop_event.is_set():
            return False

        # Interception 输入密码（确保 WeGame 窗口聚焦）
        print("⌨️ 输入密码: ****")
        if not _ensure_wegame_focused():
            print(f"⚠️ WeGame 窗口失去焦点，重试 ({attempt+1}/{max_retries})...")
            continue
        if not driver_keyboard.send_string(login_password, interval=0.02):
            print(f"⚠️ 密码输入失败，重试 ({attempt+1}/{max_retries})...")
            continue
        time.sleep(0.3)

        if app._stop_event.is_set():
            return False

        # 步骤6：图像识别点击 Sign-in（登录确认按钮）
        set_operation(app, "点击登录")
        print("🔍 识别登录确认按钮...")
        if not automation._hook(run_insert, "SIGN_IN", "before"):
            print(f"⚠️ 登录确认按钮 插入步骤(点击前)失败，重试 ({attempt+1}/{max_retries})...")
            continue
        if not utils.find_and_click_smart(config.SIGN_IN, timeout=10):
            print(f"⚠️ 未找到登录确认按钮，重试 ({attempt+1}/{max_retries})...")
            continue
        if not automation._hook(run_insert, "SIGN_IN", "after"):
            print(f"⚠️ 登录确认按钮 插入步骤(点击后)失败，重试 ({attempt+1}/{max_retries})...")
            continue
        print("✅ 已点击登录确认按钮")

        # 轮询检查登录结果（每轮 2 秒间隔 + 两次纯探测各最多 2 秒，4 轮最长约 24 秒）
        # 注意：这里只是「探测是否出现」，必须用只识别不点击的判断，
        # 否则会把三角洲图标当按钮提前点击一次，之后 _launch_game 又会点一次（造成点 2 次）
        login_ok = False
        for _ in range(4):
            time.sleep(2)
            if app._stop_event.is_set():
                return False
            if utils.find_image_on_screen(config.LOGIN_AGAIN, timeout=2,
                                          stop_event=app._stop_event):
                print(f"⚠️ 检测到重新登录按钮，登录失败，重试...")
                break
            if utils.find_image_on_screen(config.DELTA_GAME_ICON, timeout=2,
                                          stop_event=app._stop_event):
                login_ok = True
                break
        else:
            # 4 次检查既没看到重新登录按钮也没看到三角洲图标（可能停在验证码/公告页等
            # 第三态界面）：先输出屏幕文字诊断便于失败归因
            print("⚠️ 登录后既未检测到重新登录按钮也未检测到三角洲图标，可能停在验证/公告等界面")
            screen_text = ""
            try:
                screen_text = _ocr_capture_screen_text()
                if screen_text:
                    print(f"📋 屏幕文字: {screen_text}")
            except Exception:
                pass
            handled = False
            if _captcha_auto_enabled:
                # 登录验证码自动处理：OCR 判定类型 → 滑块YOLO / AI视觉 分发（captcha_router）
                try:
                    import captcha_router
                    captcha_ok, captcha_detail = captcha_router.route_and_solve(
                        app, stop_event=app._stop_event, screen_text=screen_text)
                except Exception as e:
                    print(f"⚠️ 登录验证码处理异常：{e}")
                    captcha_ok, captcha_detail = False, f"调度异常：{e}"
                print(f"🛡️ 登录验证码处理{'通过' if captcha_ok else '未通过'}：{captcha_detail}")
                login_ok = captcha_ok
                handled = True
            if not handled:
                # 总开关关闭：按原逻辑假设登录成功（真实状态由 _launch_game 兜底判断）
                login_ok = True

        if not login_ok:
            continue
        print(f"✅ 账号 {account_name} WeGame 登录成功")
        return True

    app._last_account_error = f"登录失败，已重试 {max_retries} 次"
    print(f"❌ 账号 {account_name} {app._last_account_error}")
    return False


def _launch_game(app):
    """查找三角洲图标、资产识别、启动游戏、等待窗口。返回 True=成功"""
    app._asset_hub_value = None  # 重置大厅候选资产（防跨账号残留）
    run_insert = _make_run_insert(app)   # 模板插入步骤执行回调
    set_operation(app, "查找三角洲游戏图标")
    print("\n--- 启动三角洲行动 ---")
    if not utils.activate_window_by_title("WeGame", partial_match=True):
        print("⚠️ 激活 WeGame 窗口失败，尝试直接识别...")
    time.sleep(1)

    if not automation._hook(run_insert, "DELTA_GAME_ICON", "before"):
        print("❌ 三角洲游戏图标 插入步骤(点击前)失败，跳过此账号")
        app._last_account_error = "三角洲游戏图标 插入步骤失败"
        utils.kill_process(config.WEGAME_PROCESS)
        return False
    delta_icon_found = False
    for retry in range(3):
        if app._stop_event.is_set():
            return False
        if utils.find_and_click_smart(config.DELTA_GAME_ICON, timeout=10):
            delta_icon_found = True
            break
        # 每次未找到游戏图标时，立即检测是否登录失败（login_again）
        print(f"🔍 未找到游戏图标，检测是否存在重新登录按钮... ({retry+1}/3)")
        if utils.find_and_click_smart(config.LOGIN_AGAIN, timeout=3):
            print("⚠️ 检测到重新登录按钮（可能是输入时窗口失焦导致登录失败），立即重新登录...")
            return "relogin"
        print(f"⚠️ 未找到三角洲游戏图标，重试 ({retry+1}/3)...")
    if not delta_icon_found:
        msg = "未找到三角洲游戏图标"
        print(f"❌ 多次重试后仍{msg}，跳过此账号")
        app._last_account_error = msg
        utils.kill_process(config.WEGAME_PROCESS)
        return False
    if not automation._hook(run_insert, "DELTA_GAME_ICON", "after"):
        print("❌ 三角洲游戏图标 插入步骤(点击后)失败，跳过此账号")
        app._last_account_error = "三角洲游戏图标 插入步骤失败"
        utils.kill_process(config.WEGAME_PROCESS)
        return False

    if not automation._hook(run_insert, "DELTA_LAUNCH_BTN", "before"):
        print("❌ 启动游戏按钮 插入步骤(点击前)失败，跳过此账号")
        app._last_account_error = "启动游戏按钮 插入步骤失败"
        utils.kill_process(config.WEGAME_PROCESS)
        return False
    launch_found = False
    for retry in range(3):
        if app._stop_event.is_set():
            return False
        if utils.find_and_click_smart(config.DELTA_LAUNCH_BTN, timeout=15):
            launch_found = True
            break
        print(f"⚠️ 未找到启动按钮，3秒后重试 ({retry+1}/3)...")
        time.sleep(3)
    if not launch_found:
        msg = "未找到游戏启动按钮"
        print(f"❌ 多次重试后仍{msg}，跳过此账号")
        app._last_account_error = msg
        utils.kill_process(config.WEGAME_PROCESS)
        return False
    if not automation._hook(run_insert, "DELTA_LAUNCH_BTN", "after"):
        print("❌ 启动游戏按钮 插入步骤(点击后)失败，跳过此账号")
        app._last_account_error = "启动游戏按钮 插入步骤失败"
        utils.kill_process(config.WEGAME_PROCESS)
        return False

    time.sleep(1)  # 等待游戏加载
    # 查找并点击「确定」按钮（部分用户会出现的确认步骤；可选，插入失败不中止）
    if automation._hook(run_insert, "ENSURE", "before"):
        if utils.find_and_click_smart(config.ENSURE, timeout=5):
            print("✅ 已点击确认按钮")
            automation._hook(run_insert, "ENSURE", "after")
        else:
            print("ℹ️ 无需确认，继续等待游戏窗口")
    else:
        print("ℹ️ 确定按钮 插入步骤(点击前)失败，跳过")

    print("✅ 三角洲正在启动，等待游戏窗口出现...")
    game_loaded = False
    for _ in range(45):
        if app._stop_event.is_set():
            break
        for title in DELTA_TITLES:
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
        msg = "未检测到游戏窗口"
        print(f"❌ {msg}，跳过此账号")
        app._last_account_error = msg
        return False

    ops_result = game_operations_wrapper(app)
    if ops_result == "game_failed":
        msg = "游戏内操作失败（识别问题）"
        print(f"❌ {msg}，跳过此账号")
        app._last_account_error = msg
        return "game_failed"
    if not ops_result:
        if app._stop_event.is_set():
            return "interrupted"
        msg = "游戏内操作失败"
        print(f"❌ {msg}，跳过此账号")
        app._last_account_error = msg
        return False

    # 资产识别（游戏内操作完成后，识别资产数值）
    _recognize_and_store_asset(app, stage="识别")
    return True


def _hub_asset_check(app):
    """进入特勤处前（大厅）识别一次资产，作为候选 A（与操作完成后的识别 B 对比校验）"""
    settings = app.settings
    if not settings.get("enable_asset_recognition", False):
        return
    region = settings.get("asset_region", [0, 0, 0, 0])
    if not region or region[2] <= 0 or region[3] <= 0:
        app._asset_hub_value = None
        return
    print("🔍 进入特勤处前识别资产（候选A）...")
    time.sleep(4)  # 给一点时间用于资产识别
    value = _recognize_asset(app, region)
    if value:
        app._asset_hub_value = value
        print(f"💰 大厅识别到资产（候选A）：{value}")
    else:
        app._asset_hub_value = None
        print("⚠️ 大厅资产识别失败（候选A为空）")


def _validate_asset_pair(candidate_a, candidate_b, last_record_value):
    """校验两次资产识别，返回最终有效值或 None
    规则：
      - 两者都成功：差≤3m，且与最近记录≤50m（无记录则无50m限制）→ 取后一次（B）
      - 只成功一个：与最近记录≤50m（无记录则直接有效）"""
    a = utils.parse_asset_value(candidate_a) if candidate_a else None
    b = utils.parse_asset_value(candidate_b) if candidate_b else None
    last = utils.parse_asset_value(last_record_value) if last_record_value else None
    if a is None and b is None:
        return None
    if a is not None and b is not None:
        if abs(a - b) <= 3_000_000:
            if last is None or abs(b - last) <= 50_000_000:
                return candidate_b   # 取后一次（操作完成后那次）
        return None
    # 只成功一个
    raw = candidate_a if a is not None else candidate_b
    val = a if a is not None else b
    if last is None or abs(val - last) <= 50_000_000:
        return raw
    return None


def _recognize_and_store_asset(app, stage=""):
    """执行资产识别并存储结果（与大厅候选A对比校验，防误识别）
    stage: 识别阶段标识，用于日志区分"""
    settings = app.settings
    if not settings.get("enable_asset_recognition", False):
        return
    label = f"（{stage}）" if stage else ""
    set_operation(app, f"识别资产{label}")
    asset_region = settings.get("asset_region", [0, 0, 0, 0])
    if not asset_region or asset_region[2] <= 0 or asset_region[3] <= 0:
        return
    print(f"🔍 正在识别资产区域{label}：{asset_region}")
    time.sleep(4)
    asset_value = _recognize_asset(app, asset_region)   # 这是 B（后一次）
    # 取最近一次记录（本次存储前）
    last_record = None
    if app._current_account_name:
        history = app._asset_history.get(app._current_account_name, [])
        if history:
            last_record = history[-1].get("value")
    # 与大厅候选 A 对比校验
    hub_value = getattr(app, '_asset_hub_value', None)
    if hub_value:
        valid = _validate_asset_pair(hub_value, asset_value, last_record)
    else:
        # 无大厅候选（单账号/大厅识别失败）：仅对本次识别做 50m 校验
        valid = None
        if asset_value:
            v = utils.parse_asset_value(asset_value)
            lv = utils.parse_asset_value(last_record) if last_record else None
            if lv is None or (v is not None and abs(v - lv) <= 50_000_000):
                valid = asset_value
    if not valid:
        print(f"⚠️ {stage}资产识别校验未通过，不存储" if stage else "⚠️ 资产识别校验未通过，不存储")
        return
    print(f"💰 {stage}识别到资产：{valid}")
    if app._current_account_name:
        app._account_assets[app._current_account_name] = valid
        if app._current_account_name not in app._asset_history:
            app._asset_history[app._current_account_name] = []
        app._asset_history[app._current_account_name].append({
            "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "value": valid
        })
        asset_db.record_asset(app._current_account_name, valid)
        import account_manager
        account_manager.save_accounts(app)
        app.root.after(0, app._refresh_account_tree)


def _game_process_running():
    """检查三角洲游戏进程是否仍在运行"""
    import psutil
    return any(
        p.info['name'] and p.info['name'].lower() == config.DELTA_PROCESS.lower()
        for p in psutil.process_iter(['name'])
    )


def _wait_game_process_exit(max_wait):
    """等待三角洲游戏进程退出，最多 max_wait 秒，返回是否已退出"""
    start = time.time()
    while time.time() - start < max_wait:
        if not _game_process_running():
            return True
        time.sleep(0.5)
    return not _game_process_running()


def _activate_delta_window():
    """查找并前台激活三角洲游戏窗口，返回是否成功"""
    for title in DELTA_TITLES:
        hwnd = utils.find_window_by_title(title, partial_match=True)
        if hwnd:
            try:
                import win32gui
                if win32gui.IsIconic(hwnd):
                    import win32con
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.3)
            except Exception:
                pass
            return True
    return False


def _close_game(app):
    """关闭三角洲游戏窗口

    优先优雅关闭：先发送 WM_CLOSE 并等待进程退出；
    仅当 WM_CLOSE 无效时再兜底 Alt+F4 + 强制结束。
    避免对全屏游戏直接注入 Alt+F4 强制退出（该路径会硬拆输入栈，
    与拦截驱动/反作弊收尾冲突，曾导致 0x139/0xBE 蓝屏）。"""
    set_operation(app, "关闭三角洲游戏")
    print("\n--- 关闭三角洲游戏 ---")
    # 先激活游戏窗口，避免关闭其他窗口
    _activate_delta_window()

    # 优雅关闭：发送 WM_CLOSE，等待进程退出（最多约 8 秒）
    for title in DELTA_TITLES:
        if app._stop_event.is_set():
            break
        utils.close_window_by_title(title, partial_match=True)
    if not app._stop_event.is_set():
        _wait_game_process_exit(8)

    # 仍未退出 → 兜底 Alt+F4（SendInput，不含驱动注入）
    # Alt+F4 作用于当前焦点窗口，等待期间焦点可能已漂移，必须重新激活游戏窗口再发
    if not app._stop_event.is_set() and _game_process_running():
        print("⚠️ WM_CLOSE 未生效，尝试 Alt+F4 关闭...")
        _activate_delta_window()
        for _ in range(3):
            pyautogui.hotkey('alt', 'f4')
            time.sleep(0.5)
        time.sleep(1)
        for title in DELTA_TITLES:
            if app._stop_event.is_set():
                break
            utils.close_window_by_title(title, partial_match=True)
        _wait_game_process_exit(6)

    time.sleep(1)
    utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)


def _cleanup_account_processes(app):
    """清理当前账号的所有相关进程"""
    set_operation(app, "清理进程")
    print("\n--- 退出三角洲行动、QQ 和 WeGame ---")
    utils.close_window_by_title("WeGame", partial_match=True)
    time.sleep(1)
    utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)
    utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
    utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=10)
    time.sleep(2)


def _ocr_capture_screen_text():
    """OCR 识别当前屏幕文字并返回格式化文本（账号出错时调用，用于错误诊断）"""
    try:
        import utils as _u
        import re
        results = _u.ocr_recognize(region=None)
        if not results:
            return ""
        # 合并、去重、过滤低置信度
        seen = set()
        lines = []
        for text, conf, *_ in results:
            if conf is not None and conf < 0.6:
                continue
            text = text.strip()
            if text and text not in seen and len(text) > 1:
                seen.add(text)
                lines.append(text)
        return " | ".join(lines) if lines else ""
    except Exception as e:
        return f"[OCR 识别失败: {e}]"


def _process_account_result(app, account_name, account_failed, account_interrupted,
                            processed_accounts):
    """处理单个账号的执行结果：记录状态、冷却、邮件通知"""
    next_run_str = "未启用"
    if app.settings.get("enable_cooldown", False):
        _, next_run_str = cooldown_manager.is_cooling_down(account_name)
        next_run_str = next_run_str or "已冷却"

    if account_interrupted:
        print(f"⏹️ 账号 {account_name} 被用户中断，跳过冷却记录")
        processed_accounts.append(f"{account_name} (中断)")
        server_client.update_account_status(app, account_name, "idle")
    elif account_failed:
        app.run_stats["fail"] += 1
        processed_accounts.append(f"{account_name} (失败)")
        server_client.update_account_status(app, account_name, "failed")
        # OCR 识别屏幕文本，输出到日志用于后续错误关键词分析
        try:
            screen_text = _ocr_capture_screen_text()
            if screen_text:
                print(f"📋 屏幕文字: {screen_text}")
        except Exception:
            pass
        if not app._user_stopped_cooldown:
            error_msg = getattr(app, '_last_account_error', '未知错误')
            email_notifier.send_account_failure_email(app, account_name, next_run_str, processed_accounts, error_msg)
        # 连续失败计数（跨轮累计）：达到 2 次自动暂停该账号（标黄，不弹窗）
        app._consecutive_failures[account_name] = app._consecutive_failures.get(account_name, 0) + 1
        if app._consecutive_failures[account_name] >= 2:
            print(f"⏸️ 账号 {account_name} 连续失败 {app._consecutive_failures[account_name]} 次，自动暂停")
            processed_accounts[-1] = f"{account_name} (失败-自动暂停)"
            try:
                cooldown_manager.set_account_paused(account_name, True)
                cooldown_manager.set_auto_paused(account_name, True)
            except Exception as e:
                print(f"⚠️ 自动暂停账号失败: {e}")
    else:
        if app.settings.get("enable_cooldown", False):
            cd_hours = app.settings.get("cooldown_hours", 8)
            cooldown_manager.record_run(account_name, cd_hours)
        app.run_stats["success"] += 1
        processed_accounts.append(f"{account_name} (成功)")
        server_client.update_account_status(app, account_name, "success")
        # 成功则重置连续失败计数
        app._consecutive_failures.pop(account_name, None)


def _wait_and_run_nearby_cooldowns(app, processed_accounts):
    """检查冷却列表：先运行已到期账号，再等待 N 分钟内到期的账号
    等待窗口 = cooldown_wait_minutes（默认10分钟）；开启分组运行且<10 时自动 15 分钟（避免漏跑即将到期的账号）"""
    # 第一步：检查是否有已到期的账号，直接运行
    all_cooldowns = cooldown_manager.get_all_cooldowns()
    now = datetime.datetime.now()
    expired = []
    for name, entry in all_cooldowns.items():
        # 检查暂停状态（兼容多种 key 格式）
        if entry.get("account_paused") or entry.get("paused"):
            continue
        # 用短名称再检查一次暂停状态（防止多 key 导致漏检）
        short_name = name.split(":")[-1] if ":" in name else name
        if short_name != name and cooldown_manager.is_account_paused(short_name):
            continue
        next_run_str = entry.get("next_run_time", "")
        if not next_run_str:
            continue
        try:
            next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
            remaining = (next_run - now).total_seconds()
            if remaining <= 0:
                expired.append(name)
        except Exception:
            continue

    if expired:
        print(f"🔔 检测到 {len(expired)} 个已到期账号，立即执行：{', '.join(expired)}")
        for name in expired:
            if app._stop_event.is_set():
                break
            img_path = None
            for p in app.qq_account_images:
                cd_key = _get_cooldown_key(p)
                if cd_key == name:
                    img_path = p
                    break
            if img_path:
                print(f"\n🔔 账号 {name} 冷却已到期，开始执行...")
                _run_single_account(app, img_path, len(app.qq_account_images), processed_accounts)

    # 第二步：检查 N 分钟内到期的账号，等待执行（N = cooldown_wait_minutes，开启分组运行且<10 时自动 15）
    # _cooldown_wait_done 控制是否执行等待：
    #   False = 首次调用（主循环前），只运行已到期账号，不等待
    #   True  = 第二次调用（主循环后），执行等待
    #   "done" = 已经等待过了，不再重复
    if not hasattr(app, '_cooldown_wait_done'):
        app._cooldown_wait_done = False
    if app._cooldown_wait_done == "done":
        return
    if not app._cooldown_wait_done:
        app._cooldown_wait_done = True
        return  # 首次调用，只运行已到期账号，不等待
    app._cooldown_wait_done = "done"
    # 冷却检测等待窗口（分钟）：用户可配置，默认10；开启分组运行且<10 时自动 15（避免漏跑即将到期的账号导致提前关机）
    wait_window_minutes = int(app.settings.get("cooldown_wait_minutes", 10))
    if app.settings.get("smart_schedule_enabled", False) and wait_window_minutes < 10:
        wait_window_minutes = 15
    wait_window_seconds = wait_window_minutes * 60
    while not app._stop_event.is_set():
        all_cooldowns = cooldown_manager.get_all_cooldowns()
        now = datetime.datetime.now()
        nearby = []  # (剩余秒数, 账号名)
        for name, entry in all_cooldowns.items():
            if entry.get("account_paused") or entry.get("paused"):
                continue
            # 用短名称再检查一次暂停状态
            short_name = name.split(":")[-1] if ":" in name else name
            if short_name != name and cooldown_manager.is_account_paused(short_name):
                continue
            next_run_str = entry.get("next_run_time", "")
            if not next_run_str:
                continue
            try:
                next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
                remaining = (next_run - now).total_seconds()
                # 包含已冷却完成的账号（remaining<=0）：它们应立刻执行，而不是等待冷却中的账号
                if remaining <= wait_window_seconds:
                    nearby.append((remaining, name))
            except Exception:
                continue

        if not nearby:
            break

        nearby.sort(key=lambda x: x[0])
        names = [n for _, n in nearby]
        # 已冷却完成的账号立即执行；其余等待最早到期的
        runnable_now = [n for r, n in nearby if r <= 0]
        wait_seconds = max(0, int(nearby[0][0]))
        if wait_seconds > 0:
            print(f"⏳ 检测到 {len(names)} 个账号将在 {wait_window_minutes} 分钟内冷却结束：{', '.join(names)}")
            print(f"⏳ 等待 {wait_seconds} 秒后执行...")
            set_operation(app, f"等待冷却结束 ({wait_seconds}秒)")
        else:
            print(f"🔔 检测到 {len(runnable_now)} 个账号已冷却完成，立即执行：{', '.join(runnable_now)}")
            set_operation(app, "执行已冷却账号")

        waited = 0
        while wait_seconds > 0 and waited < wait_seconds and not app._stop_event.is_set():
            chunk = min(5, wait_seconds - waited)
            time.sleep(chunk)
            waited += chunk

        if app._stop_event.is_set():
            break

        # 冷却到期，逐个运行到期账号
        for _, name in nearby:
            if app._stop_event.is_set():
                break
            cooling, _ = cooldown_manager.is_cooling_down(name)
            if cooling:
                continue
            # 找到对应图片路径
            img_path = None
            for p in app.qq_account_images:
                cd_key = _get_cooldown_key(p)
                if cd_key == name:
                    img_path = p
                    break
            if not img_path:
                continue
            print(f"\n🔔 账号 {name} 冷却到期，开始执行...")
            _run_single_account(app, img_path, len(app.qq_account_images), processed_accounts)


def _run_single_account(app, img_path, total, processed_accounts):
    """运行单个账号（从冷却等待中调用）"""
    file_name = _get_cooldown_key(img_path)
    app._current_account_name = file_name
    app._cooldown_single_run = True  # 标记为单账号运行（烽火地带识别 3 次）
    # 计算实际账号序号
    try:
        idx = app.qq_account_images.index(img_path) + 1
    except ValueError:
        idx = total
    server_client.update_account_status(app, file_name, "running")
    app.run_stats["total"] += 1
    account_failed = False
    account_interrupted = False

    if app._stop_event.is_set():
        account_interrupted = True
    if not account_interrupted:
        if not _login_account(app, file_name, idx - 1, total, processed_accounts):
            account_failed = True
    if not account_failed and app._stop_event.is_set():
        account_interrupted = True
    if not account_failed and not account_interrupted:
        launch_result = _launch_game(app)
        if launch_result == "relogin":
            # 登录失败（账号密码错误），重新输入账号密码再试一次
            print("🔄 重新登录...")
            if not _login_account(app, file_name, 0, total, processed_accounts):
                account_failed = True
                launch_result = None  # 登录失败已处理，跳过下方启动结果判断
            elif app._stop_event.is_set():
                account_interrupted = True
                launch_result = None
            else:
                launch_result = _launch_game(app)
                if launch_result == "relogin":
                    # 二次启动仍要求重新登录：按启动失败处理
                    launch_result = False
        if launch_result == "game_failed":
            # 游戏内操作失败（识别问题），设置1天冷却，用户自行处理
            # （重新登录后二次启动同样适用，不能漏判成成功）
            print(f"⚠️ 游戏内操作失败，设置 1 天冷却等待用户处理")
            app.run_stats["fail"] += 1
            cooldown_manager.record_run(file_name, 24)  # 24小时冷却
            cooldown_manager.mark_game_failed(file_name)
            processed_accounts.append(f"{file_name} (游戏失败-1天冷却)")
            server_client.update_account_status(app, file_name, "failed")
            _close_game(app)
            _cleanup_account_processes(app)
            app._cooldown_single_run = False
            return  # 单账号模式直接返回
        elif launch_result is False or launch_result == "interrupted":
            if account_failed or account_interrupted:
                pass  # 重新登录路径已处理，不重复记账
            elif app._stop_event.is_set() or launch_result == "interrupted":
                account_interrupted = True
            else:
                account_failed = True
        # else: _launch_game 内部已调用 _recognize_and_store_asset、game_operations_wrapper（含一键出售）

    # 自定义操作（主流程完成、游戏在主界面，关闭游戏前执行）
    # 只要配置了自定义操作（有工作流含步骤）就执行；频率限制在 run_custom_ops 内部按工作流判断
    if (not account_failed and not account_interrupted
            and not app._stop_event.is_set()
            and custom_ops.has_configured()):
        try:
            custom_ops.run_custom_ops(app, file_name)
        except Exception as e:
            print(f"⚠️ 自定义操作执行异常：{e}")
            traceback.print_exc()

    if not account_interrupted:
        _close_game(app)
        _cleanup_account_processes(app)

    _process_account_result(app, file_name, account_failed, account_interrupted, processed_accounts)
    app._cooldown_single_run = False


def run_script_main(app):
    """主工作线程：遍历账号执行登录和游戏操作"""
    processed_accounts = []
    try:
        print(f"🟢 run_script_main() 已启动，ignore_cooldown={app._ignore_cooldown_this_run}")
        total = len(app.qq_account_images)

        if not _validate_daily(app):
            return

        _cleanup_processes(app)

        print("=" * 55)
        print("  WeGame 直接登录 + 三角洲行动 多账号轮换脚本")
        print(f"  本轮将处理 {total} 个账号")
        print("=" * 55)

        # 开始前检查是否有即将到期的账号（10分钟内），等待并运行
        if app.settings.get("enable_cooldown", False):
            _wait_and_run_nearby_cooldowns(app, processed_accounts)

        # 账号运行分组：每 N 个账号一组，组间等待，避免频繁切换账号触发滑块验证
        smart_enabled = app.settings.get("smart_schedule_enabled", False)
        smart_group_size = max(1, int(app.settings.get("smart_group_size", 3)))
        smart_interval = max(0, int(app.settings.get("smart_group_interval", 5)))
        group_processed = 0

        def _group_wait():
            """每跑完 N 个账号，若后续还有就绪账号则等待组间隔分钟
            动态统计当前位置之后的就绪账号（含本次运行中新就绪的），避免用开跑前快照导致组间等待漏触发"""
            nonlocal group_processed
            group_processed += 1
            remaining_runnable = 0
            for j in range(i + 1, total):
                nm = _get_cooldown_key(app.qq_account_images[j])
                if cooldown_manager.is_account_paused(nm):
                    continue
                if app.settings.get("enable_cooldown", False) and cooldown_manager.is_cooling_down(nm)[0]:
                    continue
                remaining_runnable += 1
            if (smart_enabled and smart_interval > 0
                    and group_processed >= smart_group_size
                    and remaining_runnable >= 1
                    and not app._stop_event.is_set()):
                group_processed = 0
                set_operation(app, f"组间等待 {smart_interval} 分钟")
                try:
                    app._overlay_override_text = f"组间等待 {smart_interval} 分钟"
                except Exception:
                    pass
                print(f"⏳ 分组运行：已完成一组 {smart_group_size} 个账号，后续还有 {remaining_runnable} 个就绪，等待 {smart_interval} 分钟后再跑下一组（避免频繁切换账号触发滑块验证）")
                wait_sec = smart_interval * 60
                waited = 0
                while waited < wait_sec and not app._stop_event.is_set():
                    chunk = min(5, wait_sec - waited)
                    time.sleep(chunk)
                    waited += chunk
                    # 主页操作栏 + 日志遮罩顶行显示组间等待倒计时
                    remaining_sec = wait_sec - waited
                    if remaining_sec > 0 and not app._stop_event.is_set():
                        set_operation(app, f"组间等待 {remaining_sec // 60}分{remaining_sec % 60:02d}秒")
                        try:
                            app._overlay_override_text = f"组间等待 {remaining_sec // 60}分{remaining_sec % 60:02d}秒"
                        except Exception:
                            pass
                # 组间等待结束（含被中断），恢复遮罩顶行账号状态
                try:
                    app._overlay_override_text = None
                except Exception:
                    pass

        for i, img_path in enumerate(app.qq_account_images):
            if app._stop_event.is_set():
                break

            file_name = _get_cooldown_key(img_path)
            app._current_account_name = file_name
            app._last_account_error = ""  # 每个账号开始前清除上一个账号的错误
            utils.cancel_shutdown()  # 取消待执行的关机计划，防止账号运行中关机

            if cooldown_manager.is_account_paused(file_name):
                print(f"⏸️ 账号 {file_name} 已暂停，跳过。")
                processed_accounts.append(f"{file_name} (已暂停)")
                server_client.update_account_status(app, file_name, "idle")
                continue

            # 冷却检查：无论是否由冷却触发，都要检查每个账号的冷却状态
            if app.settings.get("enable_cooldown", False):
                cooling, next_time = cooldown_manager.is_cooling_down(file_name)
                if cooling:
                    print(f"⏸️ 账号 {file_name} 冷却中，跳过。下次运行时间：{next_time}")
                    processed_accounts.append(f"{file_name} (冷却中)")
                    server_client.update_account_status(app, file_name, "cooling")
                    continue

            acc_text = f"第 {i+1}/{total} 个账号"
            app.root.after(0, app.update_ui, False, acc_text, file_name)
            try:
                app._set_overlay_status(i + 1, file_name)  # 更新日志遮罩顶行
            except Exception:
                pass
            print(f"\n{'='*40}")
            print(f"    {acc_text}  -  {file_name}")
            print(f"{'='*40}")
            app.run_stats["total"] += 1
            account_failed = False
            account_interrupted = False
            server_client.update_account_status(app, file_name, "running")

            # 步骤1：WeGame QQ 账号登录（新模式）
            if app._stop_event.is_set():
                account_interrupted = True
            if not account_interrupted:
                if not _login_account(app, file_name, i, total, processed_accounts):
                    account_failed = True

            # 步骤2：启动游戏并执行操作
            if not account_failed and app._stop_event.is_set():
                account_interrupted = True
            if not account_failed and not account_interrupted:
                launch_result = _launch_game(app)
                if launch_result == "relogin":
                    # 登录失败（账号密码错误），重新输入账号密码再试一次
                    print("🔄 重新登录...")
                    if not _login_account(app, file_name, i, total, processed_accounts):
                        account_failed = True
                        launch_result = None  # 登录失败已处理，跳过下方启动结果判断
                    elif app._stop_event.is_set():
                        account_interrupted = True
                        launch_result = None
                    else:
                        launch_result = _launch_game(app)
                        if launch_result == "relogin":
                            # 二次启动仍要求重新登录：按启动失败处理
                            launch_result = False
                if launch_result == "game_failed":
                    # 游戏内操作失败，设置1天冷却（重新登录后二次启动同样适用，不能漏判成成功）
                    print(f"⚠️ 游戏内操作失败，设置 1 天冷却等待用户处理")
                    app.run_stats["fail"] += 1
                    cooldown_manager.record_run(file_name, 24)
                    cooldown_manager.mark_game_failed(file_name)
                    processed_accounts.append(f"{file_name} (游戏失败-1天冷却)")
                    server_client.update_account_status(app, file_name, "failed")
                    _close_game(app)
                    _cleanup_account_processes(app)
                    _group_wait()  # 分组运行：计入本组并可能触发组间等待
                    continue  # 继续下一个账号
                elif launch_result is False or launch_result == "interrupted":
                    if account_failed or account_interrupted:
                        pass  # 重新登录路径已处理，不重复记账
                    elif app._stop_event.is_set() or launch_result == "interrupted":
                        account_interrupted = True
                    else:
                        account_failed = True

            # 步骤2.5：自定义操作（主流程完成、游戏在主界面，关闭游戏前执行）
            # 只要配置了自定义操作（有工作流含步骤）就执行；频率限制在 run_custom_ops 内部按工作流判断
            if (not account_failed and not account_interrupted
                    and not app._stop_event.is_set()
                    and custom_ops.has_configured()):
                try:
                    custom_ops.run_custom_ops(app, file_name)
                except Exception as e:
                    print(f"⚠️ 自定义操作执行异常：{e}")
                    traceback.print_exc()

            # 步骤3：清理进程
            if not account_interrupted:
                _close_game(app)
                _cleanup_account_processes(app)

            # 记录结果
            _process_account_result(app, file_name, account_failed, account_interrupted,
                                    processed_accounts)
            _group_wait()  # 分组运行：计入本组并可能触发组间等待

            if account_interrupted:
                break

        print("\n🎉 所有账号处理完毕！")

        # 检查是否有 5 分钟内冷却结束的账号，等待并运行
        if not app._stop_event.is_set() and app.settings.get("enable_cooldown", False):
            _wait_and_run_nearby_cooldowns(app, processed_accounts)

    except Exception as e:
        print(f"❌ 运行出错: {e}")
        traceback.print_exc()
        app.run_stats["error"] = str(e)
        if not app._user_stopped_cooldown:
            email_notifier.send_failure_email(app, e, processed_accounts)
    finally:
        app.run_stats["processed_accounts"] = processed_accounts
        app.root.after(0, lambda: on_finish(app))


def _is_observe_account(app, account_name):
    """判断账号是否处于观察状态（观察账号在主流程/单账号运行中多执行观察步骤）"""
    try:
        note_data = app._account_notes.get(account_name, {})
        if isinstance(note_data, dict):
            return bool(note_data.get("observe", False))
    except Exception:
        pass
    return False


def game_operations_wrapper(app):
    """执行游戏内操作，返回 True=成功，False=失败（游戏内点击启用拟人随机偏移）"""
    # 根据设置启用点击随机偏移，结束后恢复
    utils.set_click_jitter(app.settings.get("enable_click_jitter", False),
                           app.settings.get("click_jitter_max", 5))
    try:
        account_name = getattr(app, "_current_account_name", "")
        observe_mode = _is_observe_account(app, account_name)
        # 单账号运行（手动单账号 / 冷却到期单账号）烽火地带识别 3 次，主流程 5 次
        single_account = (getattr(app, '_single_account_mode', False)
                          or getattr(app, '_cooldown_single_run', False))
        hazard_retry = 3 if single_account else 5
        result = automation.game_operations(
            app.settings, app._stop_event, lambda text: set_operation(app, text),
            update_ui_callback=lambda: app.root.after(0, app.update_ui, True),
            on_hub_entered=lambda: _hub_asset_check(app),
            observe_mode=observe_mode,
            hazard_retry=hazard_retry,
            run_insert=_make_run_insert(app))
    finally:
        utils.set_click_jitter(False)
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
                import account_manager
                account_manager.save_accounts(app)
                app.root.after(0, app._refresh_account_tree)
        return success
    return result


def sell_operations_wrapper(app):
    """一键出售流程：打开仓库，遍历售卖物品执行出售（游戏内点击启用拟人随机偏移）"""
    utils.set_click_jitter(app.settings.get("enable_click_jitter", False),
                           app.settings.get("click_jitter_max", 5))
    try:
        return automation.sell_operations(app.settings, app._stop_event,
                                          lambda text: set_operation(app, text),
                                          run_insert=_make_run_insert(app))
    finally:
        utils.set_click_jitter(False)


def on_finish(app):
    """任务完成后处理：清理状态、恢复UI、发送通知"""
    app.running = False
    app._stop_event.clear()  # 清除工作线程停止信号，不影响调度器
    app._ignore_cooldown_this_run = False  # 重置冷却忽略标志
    app._is_boot_startup = False  # 重置开机启动标志
    # 停止日志遮罩顶行运行时长刷新并复位为「未运行」
    try:
        app._stop_overlay_ticker()
    except Exception:
        pass
    # 停止心跳同步
    server_client.stop_heartbeat(app)
    app.start_btn.config(state='normal')
    app.stop_btn.config(state='disabled')
    # 清空进度条和状态信息
    app.progress['value'] = 0
    app.account_label.config(text="未开始")
    app.current_account_file_label.config(text="无")
    app.op_label.config(text="就绪")

    # 用户手动停止时，不清理进程（保留游戏和 WeGame 窗口）

    # 恢复系统睡眠设置
    utils.allow_sleep()

    # 设置下一次唤醒定时器
    app._set_next_wake_timer()

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

    # 发送邮件通知（手动终止或单账号模式时不发送）
    if not app._user_stopped_cooldown and not getattr(app, '_single_account_mode', False):
        processed_accounts = stats.get("processed_accounts", [])
        email_notifier.send_run_report_email(app, stats, elapsed, processed_accounts)
    else:
        if getattr(app, '_single_account_mode', False):
            print("ℹ️ 单账号模式，跳过邮件通知")
        else:
            print("⏹ 用户手动终止，跳过邮件通知")

    # 运行完成后延迟关机（手动终止或单账号模式时不执行）
    if not app._user_stopped_cooldown and not getattr(app, '_single_account_mode', False):
        shutdown_delay = app.settings.get("post_run_shutdown_delay", 0)
        if shutdown_delay > 0:
            delay_seconds = shutdown_delay * 60
            utils.schedule_shutdown(delay_seconds)
            print(f"🔌 所有账号运行完毕，系统将在 {shutdown_delay} 分钟后关机")
            print(f"   支持 shutdown /a 命令取消关机，或开始新任务自动取消")
    elif getattr(app, '_single_account_mode', False):
        print("ℹ️ 单账号模式，跳过延时关机")

    # 刷新账号列表（更新冷却状态和颜色）
    account_manager.refresh_account_tree(app)

    # 崩溃保险：任务结束时强制把冷却数据写盘并同步备份，防止异常退出丢数据
    try:
        cooldown_manager.flush()
    except Exception as e:
        print(f"⚠️ 冷却数据兜底保存失败: {e}")

    # 账号数据自动备份（达到间隔天数则备份，防崩溃/蓝屏导致账号数据丢失）
    try:
        account_manager.auto_backup_account_data(app)
    except Exception as e:
        print(f"⚠️ 账号数据自动备份失败: {e}")

    # 清理过期日志/截图/账号备份（按保留天数，默认3天，0=不清理）
    try:
        account_manager.cleanup_old_data(app)
    except Exception as e:
        print(f"⚠️ 清理过期日志/备份失败: {e}")

    # 运行完成：保持主窗口隐藏（托盘），需要时手动点托盘图标恢复
    # 移除原来的 _show_window()，避免运行完自动弹出窗口


def get_account_next_run(app, account_name):
    """获取账号的下次运行时间描述"""
    if not app.settings.get("enable_cooldown", False):
        return "未启用"
    if cooldown_manager.is_account_paused(account_name):
        return "待定"
    _, next_time = cooldown_manager.is_cooling_down(account_name)
    return next_time or "已冷却"


def _email_next_run_display(next_run):
    """邮件「下次运行」列：完整时间戳去掉年份和秒，显示 08-31 15:00；其他文本原样显示"""
    if not next_run:
        return "已冷却"
    # 仅对时间戳格式（YYYY-MM-DD HH:MM:SS 或 YYYY-MM-DD HH:MM）去年份
    if len(next_run) >= 10 and next_run[4] == "-" and next_run[7] == "-":
        try:
            dt = datetime.datetime.fromisoformat(next_run)
            return dt.strftime("%m-%d %H:%M")
        except Exception:
            pass
    return next_run


def build_accounts_html(app, processed_accounts):
    """构建已处理账号列表的 HTML 表格（账号前加备注 + 状态 + 资产 + 下次运行）"""
    if not processed_accounts:
        return ""
    items = []
    for idx, acc in enumerate(processed_accounts):
        # acc 格式: "xxx (成功)" 或 "xxx (失败)" 或 "xxx (冷却中)"
        # 用 rsplit 从右边分割，避免账号名中包含 ( 的情况
        account_name = acc.rsplit(" (", 1)[0] if " (" in acc else acc
        status = acc.rsplit(" (", 1)[1][:-1] if " (" in acc else ""
        # 账号前加备注（账号信息设置中的「备注」字段）用于分辨账号
        note = ""
        note_data = app._account_notes.get(account_name, {})
        if isinstance(note_data, dict) and note_data.get("game_name"):
            note = note_data["game_name"]
        if note:
            account_display = f"{html.escape(note)}　{html.escape(account_name)}"
        else:
            account_display = html.escape(account_name)
        # 资产列（与主页列表一致：统一 M 格式，如 78.39M；无资产显示 0）
        asset = app._account_assets.get(account_name, "0")
        if asset and asset != "0":
            try:
                asset_num = utils.parse_asset_value(asset)
                if asset_num > 0:
                    asset = utils.format_asset_num(asset_num)
            except Exception:
                pass
        asset_display = html.escape(str(asset))
        # 下次运行列（去掉年份，如 08-31 15:00）
        next_run = "未启用"
        if app.settings.get("enable_cooldown", False):
            next_run = get_account_next_run(app, account_name)
        next_run_display = html.escape(_email_next_run_display(next_run))
        bg = "background:#f0f2f5;" if idx % 2 == 0 else ""
        items.append(
            f'<tr style="{bg}">'
            f'<td style="padding:8px 10px;border:1px solid #dcdde1;">{account_display}</td>'
            f'<td style="padding:8px 10px;border:1px solid #dcdde1;">{html.escape(status)}</td>'
            f'<td style="padding:8px 10px;border:1px solid #dcdde1;">{asset_display}</td>'
            f'<td style="padding:8px 10px;border:1px solid #dcdde1;">{next_run_display}</td>'
            f'</tr>')
    accounts_html = "".join(items)
    return f"""
<tr><td colspan="4" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">已处理账号</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">账号</td><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">状态</td><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">资产</td><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">下次运行</td></tr>
{accounts_html}"""
