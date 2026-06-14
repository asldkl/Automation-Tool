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
import interception_keyboard


def _account_key(path):
    """从账号路径提取账号标识（去掉 account: 前缀和 .png 后缀）"""
    name = os.path.basename(path)
    if name.startswith("account:"):
        return name[len("account:"):]
    return os.path.splitext(name)[0]


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
        # 提取数字+小数点+单位(KMB)，过滤"现有资产"等无效文字
        match = re.search(r'(\d+\.?\d*)\s*([KMBkmb])', all_text)
        if match:
            number = match.group(1)
            suffix = match.group(2).upper()
            return f"{number}{suffix}"
        # 降级：清理非数字/KMB字符后重试
        cleaned = re.sub(r'[^0-9.KMBkmb]', '', all_text)
        match2 = re.search(r'(\d+\.?\d*)\s*([KMBkmb])', cleaned)
        if match2:
            number = match2.group(1)
            suffix = match2.group(2).upper()
            return f"{number}{suffix}"
        return None
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
    """运行前清理 QQ、WeGame 和三角洲行动进程"""
    print("🧹 运行前清理：退出 QQ、WeGame 和三角洲行动...")
    set_operation(app, "清理进程")
    utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)
    utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=10)
    utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
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
    set_operation(app, f"WeGame 登录 ({i+1}/{total})")

    # 获取备注中的账号和密码
    note_data = app._account_notes.get(account_name, {})
    if isinstance(note_data, dict):
        login_account = note_data.get("account", "").strip()
        login_password = note_data.get("password", "").strip()
    else:
        login_account = ""
        login_password = ""

    if not login_account:
        print(f"❌ 账号 {account_name} 未设置游戏账号，跳过")
        return False
    if not login_password:
        print(f"❌ 账号 {account_name} 未设置游戏密码，跳过")
        return False

    kb_backend = interception_keyboard.get_backend()
    print(f"⌨️ 键盘后端: {kb_backend}")

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
            print("❌ WeGame 启动失败，请检查 WeGame 路径设置")
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
        if not utils.find_and_click(config.ACCOUNT_SELECT, clicks=2, timeout=10, x_offset=-15):
            print(f"⚠️ 未找到账号选择框，重试 ({attempt+1}/{max_retries})...")
            continue
        print("✅ 已双击账号选择框")
        time.sleep(0.3)

        if app._stop_event.is_set():
            return False

        # 删除旧账号文本（Ctrl+A 全选 + Backspace）
        import pyautogui
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyautogui.press('backspace')
        time.sleep(0.2)

        # 步骤4：Interception 输入账号
        set_operation(app, "输入账号")
        print(f"⌨️ 输入账号: {login_account}")
        if not interception_keyboard.send_string(login_account, interval=0.02):
            print(f"⚠️ 账号输入失败，重试 ({attempt+1}/{max_retries})...")
            continue
        time.sleep(0.3)

        if app._stop_event.is_set():
            return False

        # 步骤5：图像识别点击 Input（密码输入框）
        set_operation(app, "点击密码输入框")
        print("🔍 识别密码输入框...")
        if not utils.find_and_click(config.IMAGE_INPUT_FIELD, timeout=10):
            print(f"⚠️ 未找到密码输入框，重试 ({attempt+1}/{max_retries})...")
            continue
        print("✅ 已点击密码输入框")
        time.sleep(0.2)

        if app._stop_event.is_set():
            return False

        # Interception 输入密码
        print("⌨️ 输入密码: ****")
        if not interception_keyboard.send_string(login_password, interval=0.02):
            print(f"⚠️ 密码输入失败，重试 ({attempt+1}/{max_retries})...")
            continue
        time.sleep(0.3)

        if app._stop_event.is_set():
            return False

        # 步骤6：图像识别点击 Sign-in（登录确认按钮）
        set_operation(app, "点击登录")
        print("🔍 识别登录确认按钮...")
        if not utils.find_and_click(config.SIGN_IN, timeout=10):
            print(f"⚠️ 未找到登录确认按钮，重试 ({attempt+1}/{max_retries})...")
            continue
        print("✅ 已点击登录确认按钮")
        time.sleep(3)

        # 检查登录是否成功（WeGame 窗口仍存在且不再显示登录界面）
        print(f"✅ 账号 {account_name} WeGame 登录成功")
        return True

    print(f"❌ 账号 {account_name} 登录失败，已重试 {max_retries} 次")
    return False


def _launch_game(app):
    """查找三角洲图标、资产识别、启动游戏、等待窗口。返回 True=成功"""
    set_operation(app, "查找三角洲游戏图标")
    print("\n--- 启动三角洲行动 ---")
    if not utils.activate_window_by_title("WeGame", partial_match=True):
        print("⚠️ 激活 WeGame 窗口失败，尝试直接识别...")
    time.sleep(1)

    delta_icon_found = False
    for retry in range(3):
        if app._stop_event.is_set():
            return False
        if utils.find_and_click(config.DELTA_GAME_ICON, timeout=15):
            delta_icon_found = True
            break
        print(f"⚠️ 未找到三角洲游戏图标，3秒后重试 ({retry+1}/3)...")
        time.sleep(3)
    if not delta_icon_found:
        print("❌ 多次重试后仍未找到三角洲游戏图标，跳过此账号")
        utils.kill_process(config.WEGAME_PROCESS)
        return False

    # 资产识别
    _recognize_and_store_asset(app)
    time.sleep(2)  # 资产识别缓冲
    time.sleep(2)

    launch_found = False
    for retry in range(3):
        if app._stop_event.is_set():
            return False
        if utils.find_and_click(config.DELTA_LAUNCH_BTN, timeout=15):
            launch_found = True
            break
        print(f"⚠️ 未找到启动按钮，3秒后重试 ({retry+1}/3)...")
        time.sleep(3)
    if not launch_found:
        print("❌ 多次重试后仍未找到启动按钮，跳过此账号")
        utils.kill_process(config.WEGAME_PROCESS)
        return False

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
            return False
        print("❌ 游戏内操作失败，跳过此账号")
        return False
    return not app._stop_event.is_set()


def _recognize_and_store_asset(app):
    """执行资产识别并存储结果"""
    settings = config.load_settings()
    if not settings.get("enable_asset_recognition", False):
        return
    set_operation(app, "识别资产")
    asset_region = settings.get("asset_region", [0, 0, 0, 0])
    if not asset_region or asset_region[2] <= 0 or asset_region[3] <= 0:
        return
    print(f"🔍 正在识别资产区域：{asset_region}")
    time.sleep(4)
    asset_value = _recognize_asset(app, asset_region)
    if asset_value:
        print(f"💰 识别到资产：{asset_value}")
        if app._current_account_name:
            app._account_assets[app._current_account_name] = asset_value
            if app._current_account_name not in app._asset_history:
                app._asset_history[app._current_account_name] = []
            app._asset_history[app._current_account_name].append({
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "value": asset_value
            })
            asset_db.record_asset(app._current_account_name, asset_value)
            app.root.after(0, app._refresh_account_tree)
    else:
        print("ℹ️ 未识别到资产数值")


def _close_game(app):
    """关闭三角洲游戏窗口"""
    set_operation(app, "关闭三角洲游戏")
    print("\n--- 关闭三角洲游戏 ---")
    for _ in range(3):
        pyautogui.hotkey('alt', 'f4')
        time.sleep(0.5)
    time.sleep(1)
    delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
    for title in delta_titles:
        if app._stop_event.is_set():
            break
        utils.close_window_by_title(title, partial_match=True)
    time.sleep(2)
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
        if not app._user_stopped_cooldown:
            email_notifier.send_account_failure_email(app, account_name, next_run_str, processed_accounts)
    else:
        if app.settings.get("enable_cooldown", False):
            cd_hours = app.settings.get("cooldown_hours", 8)
            cooldown_manager.record_run(account_name, cd_hours)
        app.run_stats["success"] += 1
        processed_accounts.append(f"{account_name} (成功)")
        server_client.update_account_status(app, account_name, "success")


def _wait_and_run_nearby_cooldowns(app, processed_accounts):
    """检查冷却列表，如果有 5 分钟内到期的账号则等待并运行"""
    while not app._stop_event.is_set():
        all_cooldowns = cooldown_manager.get_all_cooldowns()
        now = datetime.datetime.now()
        nearby = []  # (剩余秒数, 账号名)
        for name, entry in all_cooldowns.items():
            if entry.get("account_paused") or entry.get("paused"):
                continue
            next_run_str = entry.get("next_run_time", "")
            if not next_run_str:
                continue
            try:
                next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
                remaining = (next_run - now).total_seconds()
                if 0 < remaining <= 300:  # 5 分钟内
                    nearby.append((remaining, name))
            except Exception:
                continue

        if not nearby:
            break

        nearby.sort(key=lambda x: x[0])
        wait_seconds = int(nearby[0][0])
        names = [n for _, n in nearby]
        print(f"⏳ 检测到 {len(names)} 个账号将在 5 分钟内冷却结束：{', '.join(names)}")
        print(f"⏳ 等待 {wait_seconds} 秒后执行...")
        set_operation(app, f"等待冷却结束 ({wait_seconds}秒)")

        waited = 0
        while waited < wait_seconds and not app._stop_event.is_set():
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
                if _account_key(p) == name:
                    img_path = p
                    break
            if not img_path:
                continue
            print(f"\n🔔 账号 {name} 冷却到期，开始执行...")
            _run_single_account(app, img_path, len(app.qq_account_images), processed_accounts)


def _run_single_account(app, img_path, total, processed_accounts):
    """运行单个账号（从冷却等待中调用）"""
    file_name = _account_key(img_path)
    app._current_account_name = file_name
    server_client.update_account_status(app, file_name, "running")
    app.run_stats["total"] += 1
    account_failed = False
    account_interrupted = False

    if app._stop_event.is_set():
        account_interrupted = True
    if not account_interrupted:
        if not _login_account(app, file_name, 0, total, processed_accounts):
            account_failed = True
    if not account_failed and app._stop_event.is_set():
        account_interrupted = True
    if not account_failed and not account_interrupted:
        if not _launch_game(app):
            if app._stop_event.is_set():
                account_interrupted = True
            else:
                account_failed = True
        # else: _launch_game 内部已调用 _recognize_and_store_asset、game_operations_wrapper（含一键出售）

    if not account_interrupted:
        if not account_failed:
            _close_game(app)
        _cleanup_account_processes(app)

    _process_account_result(app, file_name, account_failed, account_interrupted, processed_accounts)


def _wait_account_interval(app, i, total):
    """账号间隔等待，返回 True=被中断应退出循环"""
    if i >= total - 1 or app._stop_event.is_set():
        return app._stop_event.is_set()
    interval = app.settings.get("cooldown_delay_minutes", 1)
    if interval <= 0:
        return False
    print(f"⏳ 等待 {interval} 分钟后执行下一个账号...")
    set_operation(app, f"账号间隔等待 ({interval}分钟)")
    wait_seconds = interval * 60
    waited = 0
    while waited < wait_seconds and not app._stop_event.is_set():
        chunk = min(5, wait_seconds - waited)
        time.sleep(chunk)
        waited += chunk
    return app._stop_event.is_set()


def run_script_main(app):
    """主工作线程：遍历账号执行登录和游戏操作"""
    processed_accounts = []
    try:
        print(f"🟢 run_script_main() 已启动，ignore_cooldown={app._ignore_cooldown_this_run}")
        total = len(app.qq_account_images)
        qq_path = app.settings.get("qq_path", "")

        if not _validate_daily(app):
            return

        _cleanup_processes(app)

        print("=" * 55)
        print("  QQ 登录 + WeGame 快捷登录 + 三角洲行动 多账号轮换脚本")
        print(f"  本轮将处理 {total} 个 QQ 账号")
        print("=" * 55)

        for i, img_path in enumerate(app.qq_account_images):
            if app._stop_event.is_set():
                break

            file_name = _account_key(img_path)
            app._current_account_name = file_name

            if cooldown_manager.is_account_paused(file_name):
                print(f"⏸️ 账号 {file_name} 已暂停，跳过。")
                processed_accounts.append(f"{file_name} (已暂停)")
                server_client.update_account_status(app, file_name, "cooling")
                continue

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
                if not _launch_game(app):
                    if app._stop_event.is_set():
                        account_interrupted = True
                    else:
                        account_failed = True

            # 步骤3：清理进程
            if not account_interrupted:
                if not account_failed:
                    _close_game(app)
                _cleanup_account_processes(app)

            # 记录结果
            _process_account_result(app, file_name, account_failed, account_interrupted,
                                    processed_accounts)

            if account_interrupted:
                break

            if _wait_account_interval(app, i, total):
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
    # 清空进度条和状态信息
    app.progress['value'] = 0
    app.account_label.config(text="未开始")
    app.current_account_file_label.config(text="无")
    app.op_label.config(text="就绪")

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

    # 发送邮件通知（手动终止时不发送）
    if not app._user_stopped_cooldown:
        processed_accounts = stats.get("processed_accounts", [])
        email_notifier.send_run_report_email(app, stats, elapsed, processed_accounts)
    else:
        print("⏹ 用户手动终止，跳过邮件通知")

    # 运行完成后延迟关机（手动终止时不执行）
    if not app._user_stopped_cooldown:
        shutdown_delay = app.settings.get("post_run_shutdown_delay", 0)
        if shutdown_delay > 0:
            delay_seconds = shutdown_delay * 60
            utils.schedule_shutdown(delay_seconds)
            print(f"🔌 所有账号运行完毕，系统将在 {shutdown_delay} 分钟后关机")
            print(f"   如需取消关机，请在命令行执行: shutdown /a")

    # 刷新账号列表（更新冷却状态和颜色）
    account_manager.refresh_account_tree(app)


def get_account_next_run(app, account_name):
    """获取账号的下次运行时间描述"""
    if not app.settings.get("enable_cooldown", False):
        return "未启用"
    if cooldown_manager.is_account_paused(account_name):
        return "待定"
    _, next_time = cooldown_manager.is_cooling_down(account_name)
    return next_time or "已冷却"


def build_accounts_html(app, processed_accounts):
    """构建已处理账号列表的 HTML（含资产和下次运行时间）"""
    if not processed_accounts:
        return ""
    items = []
    for acc in processed_accounts:
        # acc 格式: "xxx.png (成功)" 或 "xxx.png (失败)" 或 "xxx.png (冷却中)"
        account_name = acc.split(" (")[0] if " (" in acc else acc
        asset = app._account_assets.get(account_name, "")
        asset_text = f"　｜　资产：{html.escape(asset)}" if asset else ""
        next_run = "未启用"
        if app.settings.get("enable_cooldown", False):
            next_run = get_account_next_run(app, account_name)
        items.append(f"<li>{html.escape(acc)}{asset_text}　｜　下次运行：{html.escape(next_run)}</li>")
    accounts_html = "".join(items)
    return f"""
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">已处理账号</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;"><ul style="margin:0;padding-left:20px;">{accounts_html}</ul></td></tr>"""
