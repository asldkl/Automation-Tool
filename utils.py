"""
工具函数模块
包含启动应用程序、窗口激活、图像识别点击、WeGame 快捷登录、进程强制结束等
"""
import time
import cv2
import numpy as np
import pyautogui
import subprocess
import os
import psutil
import win32gui
import win32con
import config
from config import (CONFIDENCE, WAIT_TIME, WEGAME_PROCESS, DELTA_PROCESS,
                    IMAGE_LOGIN_BTN,
                    QQ_ACCOUNT_SELECT, QQ_LOGIN_BTN)

def start_app(exe_path, app_name):
    """启动外部程序，5秒后返回是否成功"""
    if not exe_path or not os.path.exists(exe_path):
        print(f"❌ 找不到 {app_name} 程序文件：{exe_path}")
        return False
    try:
        work_dir = os.path.dirname(exe_path)
        subprocess.Popen(exe_path, cwd=work_dir)
        print(f"✅ 已启动：{app_name}")
        time.sleep(5)
        return True
    except Exception as e:
        print(f"❌ 启动 {app_name} 失败：{e}")
        return False

def activate_window_by_title(title_contains, partial_match=True, exclude_titles=None):
    """
    按标题激活窗口（支持部分匹配、排除关键词）
    返回是否成功激活
    """
    if exclude_titles is None:
        exclude_titles = []

    def enum_callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd):
            window_title = win32gui.GetWindowText(hwnd)
            if partial_match and title_contains.lower() in window_title.lower():
                for ex in exclude_titles:
                    if ex.lower() in window_title.lower():
                        return True
                windows.append((hwnd, window_title))
            elif not partial_match and window_title == title_contains:
                for ex in exclude_titles:
                    if ex.lower() in window_title.lower():
                        return True
                windows.append((hwnd, window_title))
        return True

    windows = []
    win32gui.EnumWindows(enum_callback, windows)
    if not windows:
        print(f"❌ 未找到包含 '{title_contains}' 的窗口")
        return False

    hwnd, title = windows[0]
    print(f"🔍 找到窗口: {title}")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    try:
        win32gui.SetForegroundWindow(hwnd)
        print(f"✅ 已激活窗口: {title}")
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"❌ 激活失败: {e}")
        return False

def wait_for_window(title_contains, timeout=30, partial_match=True, exclude_titles=None):
    """循环等待直到窗口出现并激活成功"""
    cond = "包含" if partial_match else "完全等于"
    print(f"⏳ 等待窗口标题 {cond} '{title_contains}'...")
    start = time.time()
    while time.time() - start < timeout:
        if activate_window_by_title(title_contains, partial_match, exclude_titles):
            return True
        time.sleep(1)
    print(f"❌ 超时未找到窗口 '{title_contains}'")
    return False

# 模板图片缓存，避免每次匹配都从磁盘读取
_template_cache = {}

def clear_template_cache():
    """清除模板缓存（用于重新截图后刷新）"""
    global _template_cache
    _template_cache.clear()

def find_and_click(img_path, timeout=20, region=None):
    """
    在当前屏幕中查找图片并点击中心点
    返回是否成功找到并点击
    """
    # 从缓存加载模板，首次调用时读取磁盘
    template = _template_cache.get(img_path)
    if template is None:
        template = cv2.imread(img_path, 0)
        if template is None:
            print(f"❌ 图片文件不存在：{img_path}")
            return False
        _template_cache[img_path] = template

    start = time.time()
    while time.time() - start < timeout:
        try:
            screen = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        except Exception:
            time.sleep(0.5)
            continue
        screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= CONFIDENCE:
            h, w = template.shape
            x = max_loc[0] + w // 2 + (region[0] if region else 0)
            y = max_loc[1] + h // 2 + (region[1] if region else 0)

            # 忽略屏幕边缘可疑坐标
            screen_w, screen_h = pyautogui.size()
            margin = 10
            if x < margin or y < margin or x > screen_w - margin or y > screen_h - margin:
                print(f"⚠️ 忽略可疑坐标 ({x}, {y})，继续寻找...")
                time.sleep(0.3)
                continue

            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()
            time.sleep(WAIT_TIME)
            return True
        time.sleep(0.3)
    print(f"⏳ 超时未找到：{img_path}")
    return False

def find_and_click_pos(img_path, timeout=20, region=None):
    """
    在当前屏幕中查找图片并点击中心点
    返回 (是否成功, 坐标元组(x,y)) 或 (False, None)
    """
    template = _template_cache.get(img_path)
    if template is None:
        template = cv2.imread(img_path, 0)
        if template is None:
            print(f"❌ 图片文件不存在：{img_path}")
            return False, None
        _template_cache[img_path] = template

    start = time.time()
    while time.time() - start < timeout:
        try:
            screen = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        except Exception:
            time.sleep(0.5)
            continue
        screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= CONFIDENCE:
            h, w = template.shape
            x = max_loc[0] + w // 2 + (region[0] if region else 0)
            y = max_loc[1] + h // 2 + (region[1] if region else 0)

            screen_w, screen_h = pyautogui.size()
            margin = 10
            if x < margin or y < margin or x > screen_w - margin or y > screen_h - margin:
                print(f"⚠️ 忽略可疑坐标 ({x}, {y})，继续寻找...")
                time.sleep(0.3)
                continue

            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()
            time.sleep(WAIT_TIME)
            return True, (x, y)
        time.sleep(0.3)
    print(f"⏳ 超时未找到：{img_path}")
    return False, None

def wegame_quick_login():
    """
    使用图像识别完成 WeGame 快捷登录：
    直接点击登录按钮（使用当前已登录的 QQ 账号）
    每轮运行前会先退出 QQ 和 WeGame，确保打开 WeGame 时快捷登录显示的就是当前 QQ 账号
    """
    print("🔍 点击登录按钮...")
    if not find_and_click(IMAGE_LOGIN_BTN, timeout=15):
        print("❌ 未找到登录按钮")
        return False
    print("✅ 快捷登录完成")
    return True

def kill_process(process_name, wait_exit=True, max_wait=30):
    """强制结束指定进程，可选等待退出"""
    killed = False
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
            try:
                proc.kill()
                print(f"✅ 已结束进程: {proc.info['name']}")
                killed = True
            except Exception:
                pass

    if not killed:
        print(f"⚠️ 未找到进程 {process_name}，可能已退出")
        return True

    if wait_exit:
        print(f"⏳ 等待进程 {process_name} 完全退出...")
        start = time.time()
        while time.time() - start < max_wait:
            exists = any(
                p.info['name'] and p.info['name'].lower() == process_name.lower()
                for p in psutil.process_iter(['name'])
            )
            if not exists:
                print("✅ 进程已完全退出")
                return True
            time.sleep(1)
        print(f"❌ 超时：进程 {process_name} 仍在运行")
        return False
    return True
# 在原有 utils.py 末尾添加：
def close_window_by_title(title_contains, partial_match=True):
    """通过窗口标题查找窗口并发送 WM_CLOSE 消息"""
    hwnd_target = None
    def enum_callback(hwnd, _):
        nonlocal hwnd_target
        if win32gui.IsWindowVisible(hwnd):
            wt = win32gui.GetWindowText(hwnd)
            if partial_match and title_contains.lower() in wt.lower():
                hwnd_target = hwnd
                return False
            elif not partial_match and wt == title_contains:
                hwnd_target = hwnd
                return False
        return True
    win32gui.EnumWindows(enum_callback, None)
    if hwnd_target:
        win32gui.PostMessage(hwnd_target, win32con.WM_CLOSE, 0, 0)
        return True
    return False


# ==================== 电源管理 ====================
import ctypes
import datetime as _dt

_kernel32 = ctypes.windll.kernel32

# SetThreadExecutionState flags
ES_CONTINUOUS      = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040
ES_DISPLAY_REQUIRED = 0x00000002

_prev_sleep_state = None
_sleep_prevent_count = 0


def prevent_sleep():
    """阻止系统进入睡眠/休眠状态，并保持显示器开启（运行关键操作时调用）"""
    global _sleep_prevent_count, _prev_sleep_state
    _sleep_prevent_count += 1
    if _sleep_prevent_count == 1:
        _kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED | ES_DISPLAY_REQUIRED
        )


def allow_sleep():
    """恢复系统自动睡眠（与 prevent_sleep 配对调用）"""
    global _sleep_prevent_count
    if _sleep_prevent_count > 0:
        _sleep_prevent_count -= 1
    if _sleep_prevent_count == 0:
        _kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def _local_to_filetime(local_dt):
    """
    将本地 datetime 转换为 Windows FILETIME 格式
    （自 1601-01-01 00:00 UTC 以来的 100 纳秒间隔数）
    """
    import calendar, time
    timestamp = time.mktime(local_dt.timetuple())  # local → seconds since epoch
    ft_offset = 11644473600  # seconds from 1601-01-01 to 1970-01-01
    ft_seconds = timestamp + ft_offset
    return int(ft_seconds * 10000000)


def set_wake_timer(wake_local_dt):
    """
    设置系统唤醒定时器，使电脑在指定时间从睡眠/休眠中唤醒。
    wake_local_dt: datetime 对象（本地时间）
    返回 timer handle，需保持引用直至定时器触发或取消。
    """
    hundred_ns = _local_to_filetime(wake_local_dt)
    timer_handle = _kernel32.CreateWaitableTimerW(None, True, None)
    if not timer_handle:
        return None
    due_time = ctypes.c_longlong(hundred_ns)
    result = _kernel32.SetWaitableTimer(
        timer_handle,
        ctypes.byref(due_time),
        0,       # 单次触发
        None,    # 无完成回调
        None,    # 无参数
        True     # fResume = True → 唤醒系统
    )
    if not result:
        _kernel32.CloseHandle(timer_handle)
        return None
    return timer_handle


def cancel_wake_timer(timer_handle):
    """取消之前设置的唤醒定时器，并释放句柄"""
    if timer_handle:
        _kernel32.CancelWaitableTimer(timer_handle)
        _kernel32.CloseHandle(timer_handle)


def schedule_shutdown(delay_seconds=120):
    """
    安排系统在指定秒数后关机。
    返回 True 表示成功。
    """
    import subprocess
    try:
        subprocess.run(
            ["shutdown", "/s", "/t", str(int(delay_seconds))],
            check=True, capture_output=True, timeout=5
        )
        return True
    except Exception as e:
        print(f"❌ 设置自动关机失败: {e}")
        return False


def cancel_shutdown():
    """取消待执行的关机计划。返回 True 表示成功"""
    import subprocess
    try:
        subprocess.run(
            ["shutdown", "/a"],
            check=True, capture_output=True, timeout=5
        )
        return True
    except Exception:
        return False


def wake_display():
    """
    唤醒显示器（从黑屏/息屏状态恢复显示）。
    组合多种方法确保显示器正常点亮。
    """
    # 方法1: 模拟鼠标移动和点击（常用于唤醒休眠中的显示器）
    try:
        screen_w, screen_h = pyautogui.size()
        pyautogui.moveTo(screen_w // 2, screen_h // 2, duration=0.5)
        pyautogui.click()
        pyautogui.moveRel(1, 0, duration=0.1)
    except Exception:
        pass
    time.sleep(0.3)

    # 方法2: 模拟键盘按键 (Ctrl 键)
    ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)  # Ctrl up
    time.sleep(0.3)

    # 方法3: 使用 SC_MONITORPOWER 发送显示器唤醒信号
    HWND_BROADCAST = 0xFFFF
    WM_SYSCOMMAND = 0x0112
    SC_MONITORPOWER = 0xF170
    ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, -1)
    time.sleep(0.5)

    # 再次请求保持显示器开启
    _kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    )
    time.sleep(0.5)

    # 解除 Windows 锁屏：屏幕唤醒后可能处于锁屏界面，
    # 需要按 Space 键进入 Windows 桌面。
    # 第1次 Space：响应屏幕点亮/唤起床；第2次 Space：进入桌面。
    try:
        pyautogui.press("Space")
        time.sleep(1)
        pyautogui.press("Space")
    except Exception:
        pass

    print("🖥️ 已尝试唤醒显示器")


def qq_quick_login(qq_number_img):
    """
    使用图像识别完成 QQ 自动登录：
    点击账号选择 → 点击目标 QQ 号 → 点击登录按钮
    支持滚动查找被遮挡的账号（超过3个账号时）
    """
    print("🔍 点击 QQ 账号选择按钮...")
    success, btn_pos = find_and_click_pos(QQ_ACCOUNT_SELECT, timeout=15)
    if not success:
        print("❌ 未找到 QQ 账号选择按钮")
        return False
    time.sleep(1)

    print("🔍 选择 QQ 号...")
    if not find_and_click(qq_number_img, timeout=5):
        # 未找到目标账号，尝试滚动下拉列表查找
        if btn_pos:
            print("🔍 目标 QQ 号可能被遮挡，尝试滚动查找...")
            scroll_x, scroll_y = btn_pos
            scroll_distance = config.APP_SETTINGS.get("qq_mouse_move_distance", 100)
            scroll_amount = config.APP_SETTINGS.get("scroll_amount", 100)
            for scroll_attempt in range(3):
                pyautogui.moveTo(scroll_x, scroll_y + scroll_distance, duration=0.1)
                time.sleep(0.2)
                pyautogui.scroll(-scroll_amount)
                time.sleep(0.8)
                if find_and_click(qq_number_img, timeout=5):
                    break
            else:
                print("❌ 滚动查找后仍未找到目标 QQ 号")
                return False
        else:
            print("❌ 未找到目标 QQ 号")
            return False
    time.sleep(0.5)

    print("🔍 点击 QQ 登录按钮...")
    if not find_and_click(QQ_LOGIN_BTN, timeout=10):
        print("❌ 未找到 QQ 登录按钮")
        return False
    print("✅ QQ 自动登录完成")
    return True

def schedule_startup_task(time_str):
    """
    使用 Windows Task Scheduler 创建每日定时任务。
    在睡眠/休眠状态下可唤醒电脑并启动本程序。
    time_str: "HH:MM" 格式
    """
    import subprocess, sys, tempfile

    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        ps_script = f"""$a = New-ScheduledTaskAction -Execute '"{exe_path}"' -Argument '--auto-start'
"""
    else:
        python_exe = sys.executable
        script_path = os.path.abspath(sys.argv[0]) if sys.argv[0] else os.path.abspath(__file__)
        ps_script = f"""$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c "{python_exe}" "{script_path}" --auto-start')
"""

    ps_script += f"""$t = New-ScheduledTaskTrigger -Daily -At '{time_str}'
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun -StartWhenAvailable
$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'DeltaAutoTool_Wake' -Action $a -Trigger $t -Settings $s -Principal $p -Force
"""
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix='.ps1', prefix='delta_task_')
        with os.fdopen(fd, 'w', encoding='utf-8-sig') as f:
            f.write(ps_script)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_path],
            check=True, capture_output=True, text=True, timeout=15
        )
        print(f"✅ 已创建定时开机任务：每天 {time_str}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️ 设置定时开机任务失败: {e.stderr if e.stderr else e}")
        return False
    except Exception as e:
        print(f"⚠️ 设置定时开机任务失败: {e}")
        return False
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def remove_startup_task():
    """删除之前创建的定时开机唤醒任务"""
    import subprocess
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Unregister-ScheduledTask -TaskName 'DeltaAutoTool_Wake' -Confirm:$false"],
            check=True, capture_output=True, timeout=15
        )
        return True
    except Exception:
        return False


# ==================== 邮件通知 ====================
def send_email_notification(smtp_code, sender_email, receiver_email, subject, body):
    """
    使用 QQ 邮箱 SMTP 发送邮件通知。
    smtp_code: SMTP 授权码
    sender_email: 发送者邮箱
    receiver_email: 接收者邮箱
    subject: 邮件主题
    body: 邮件正文（HTML 格式）
    返回 (success: bool, message: str)
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        with smtplib.SMTP_SSL('smtp.qq.com', 465, timeout=30) as server:
            server.login(sender_email, smtp_code)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        return True, "邮件发送成功"
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP 认证失败，请检查授权码是否正确"
    except smtplib.SMTPConnectError:
        return False, "无法连接到 SMTP 服务器，请检查网络"
    except smtplib.SMTPException as e:
        return False, f"SMTP 错误：{e}"
    except Exception as e:
        return False, f"发送失败：{e}"