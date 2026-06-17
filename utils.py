"""
工具函数模块
包含启动应用程序、窗口激活、图像识别点击、WeGame 快捷登录、进程强制结束等
"""
import time
import threading
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
                    IMAGE_LOGIN_BTN)
import relative_mouse_move


def smooth_move_to(x, y, duration=0.2, use_bezier=True):
    """使用贝塞尔曲线/Smoothstep算法平滑移动鼠标到目标位置"""
    try:
        cur_x, cur_y = pyautogui.position()
        offset_x = x - cur_x
        offset_y = y - cur_y
        if offset_x == 0 and offset_y == 0:
            return
        def move_step(dx, dy):
            pyautogui.moveRel(dx, dy, _pause=False)
            return True
        relative_mouse_move.perform_timed_relative_move(
            offset_x, offset_y, duration, move_step, use_bezier=use_bezier
        )
    except Exception:
        pyautogui.moveTo(x, y, duration=duration)

def start_app(exe_path, app_name, wait_time=5):
    """启动外部程序，等待指定秒数后返回是否成功"""
    if not exe_path or not os.path.exists(exe_path):
        print(f"❌ 找不到 {app_name} 程序文件：{exe_path}")
        return False
    try:
        work_dir = os.path.dirname(exe_path)
        subprocess.Popen(exe_path, cwd=work_dir)
        print(f"✅ 已启动：{app_name}")
        time.sleep(wait_time)
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

def find_window_by_title(title_contains, partial_match=True, exclude_titles=None):
    """按标题查找窗口，返回窗口句柄(hwnd)，未找到返回 None"""
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
        return None
    return windows[0][0]

def wait_for_window(title_contains, timeout=30, partial_match=True, exclude_titles=None):
    """循环等待直到窗口出现（不依赖激活，仅检查窗口是否存在）"""
    cond = "包含" if partial_match else "完全等于"
    print(f"⏳ 等待窗口标题 {cond} '{title_contains}'...")
    start = time.time()
    while time.time() - start < timeout:
        hwnd = find_window_by_title(title_contains, partial_match, exclude_titles)
        if hwnd:
            print(f"✅ 找到窗口: {title_contains}")
            return True
        time.sleep(1)
    print(f"❌ 超时未找到窗口 '{title_contains}'")
    return False

# 模板图片缓存，避免每次匹配都从磁盘读取
_template_cache = {}

def _imread_unicode(path, flags=cv2.IMREAD_GRAYSCALE):
    """cv2.imread 不支持非 ASCII 路径（如中文），用 np.fromfile + cv2.imdecode 替代"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, flags)
    except Exception:
        return None

def clear_template_cache():
    """清除模板缓存（用于重新截图后刷新）"""
    global _template_cache
    _template_cache.clear()

def _match_template(gray_screen, template, threshold):
    """标准灰度模板匹配，返回 (matched, max_val, max_loc, (h, w))"""
    res = cv2.matchTemplate(gray_screen, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    h, w = template.shape
    return max_val >= threshold, max_val, max_loc, (h, w)


def _screenshot_gray(region=None):
    """截屏并直接转灰度（跳过 RGB→BGR 中间步骤）"""
    try:
        screen = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
    except Exception:
        return None
    arr = np.array(screen)
    screen.close()
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def _find_and_click_core(img_path, timeout=20, region=None, confidence=None,
                         clicks=1, x_offset=0, y_offset=0,
                         multiscale=False, return_pos=False):
    """
    统一的图像识别+点击函数。
    multiscale: True 使用多尺度边缘+灰度匹配，False 使用标准灰度匹配
    return_pos: True 返回 (success, (x,y)), False 返回 success
    """
    threshold = confidence if confidence is not None else CONFIDENCE
    resolved = config.resolve_template_path(img_path)
    template = _template_cache.get(resolved)
    if template is None:
        template = _imread_unicode(resolved)
        if template is None:
            print(f"❌ 图片文件不存在或无法读取：{resolved}")
            return (False, None) if return_pos else False
        _template_cache[resolved] = template

    start = time.time()
    while time.time() - start < timeout:
        gray = _screenshot_gray(region)
        if gray is None:
            time.sleep(0.5)
            continue

        if multiscale:
            matched, max_val, max_loc, (h, w) = _match_template_multiscale(
                gray, template, threshold)
        else:
            matched, max_val, max_loc, (h, w) = _match_template(
                gray, template, threshold)

        if matched:
            x = max_loc[0] + w // 2 + (region[0] if region else 0) + x_offset
            y = max_loc[1] + h // 2 + (region[1] if region else 0) + y_offset

            screen_w, screen_h = pyautogui.size()
            margin = 10
            if x < margin or y < margin or x > screen_w - margin or y > screen_h - margin:
                print(f"⚠️ 忽略可疑坐标 ({x}, {y})，继续寻找...")
                time.sleep(0.3)
                continue

            if multiscale and max_val >= threshold:
                print(f"🔍 复合匹配成功：置信度 {max_val:.3f}")
            try:
                smooth_move_to(x, y, duration=0.2)
                pyautogui.click(clicks=clicks)
            except pyautogui.FailSafeException:
                print(f"⚠️ 鼠标触碰屏幕角落，安全机制触发，跳过点击")
                time.sleep(0.5)
                continue
            time.sleep(WAIT_TIME)
            return (True, (x, y)) if return_pos else True
        time.sleep(0.3)
    print(f"⏳ 超时未找到：{img_path}")
    return (False, None) if return_pos else False


def find_and_click(img_path, timeout=20, region=None, confidence=None, clicks=1, x_offset=0, y_offset=0):
    """在当前屏幕中查找图片并点击中心点，返回是否成功"""
    return _find_and_click_core(img_path, timeout, region, confidence,
                                clicks, x_offset, y_offset, multiscale=False, return_pos=False)


def find_and_click_pos(img_path, timeout=20, region=None, confidence=None):
    """在当前屏幕中查找图片并点击中心点，返回 (是否成功, (x,y))"""
    return _find_and_click_core(img_path, timeout, region, confidence,
                                multiscale=False, return_pos=True)

def _match_template_multiscale(gray_screen, template, threshold, scales=None):
    """
    多尺度复合模板匹配：结合灰度匹配和边缘匹配，充分利用头像轮廓、名称文字、
    QQ号码等结构特征。在多个缩放比例下尝试，返回最佳结果。
    - 灰度匹配：对整体布局和明暗敏感
    - 边缘匹配：对头像轮廓、文字笔画、数字形状等结构特征更敏感，抗光照变化
    两种方法取最高分，确保各类特征都能被利用。
    返回 (matched, max_val, max_loc, best_scale, (tH, tW))
    """
    if scales is None:
        scales = [1.0, 0.9, 1.1, 0.8, 1.2, 0.7, 1.3]

    best_val = -1
    best_loc = None
    best_scale = 1.0
    best_h, best_w = template.shape

    # 预计算屏幕边缘图（Canny 边缘检测，捕捉头像轮廓和文字笔画）
    screen_edges = cv2.Canny(gray_screen, 50, 150)

    for scale in scales:
        if scale == 1.0:
            scaled = template
        else:
            new_w = max(1, int(template.shape[1] * scale))
            new_h = max(1, int(template.shape[0] * scale))
            if new_w < 2 or new_h < 2:
                continue
            scaled = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)

        sh, sw = scaled.shape
        if sh > gray_screen.shape[0] or sw > gray_screen.shape[1]:
            continue

        # 方法1：灰度模板匹配（整体像素模式）
        res_gray = cv2.matchTemplate(gray_screen, scaled, cv2.TM_CCOEFF_NORMED)
        _, gray_val, _, gray_loc = cv2.minMaxLoc(res_gray)

        # 方法2：边缘模板匹配（结构特征：头像轮廓、文字边缘、数字形状）
        template_edges = cv2.Canny(scaled, 50, 150)
        if template_edges is not None and template_edges.shape[0] <= screen_edges.shape[0] and template_edges.shape[1] <= screen_edges.shape[1]:
            res_edge = cv2.matchTemplate(screen_edges, template_edges, cv2.TM_CCOEFF_NORMED)
            _, edge_val, _, edge_loc = cv2.minMaxLoc(res_edge)
        else:
            edge_val = -1
            edge_loc = gray_loc

        # 取两种方法的平均分，融合灰度和边缘特征
        if edge_val >= 0:
            val = (gray_val + edge_val) / 2.0
        else:
            val = gray_val
        # 位置用得分更高的那个（更准确）
        loc = edge_loc if edge_val > gray_val else gray_loc

        if val > best_val:
            best_val = val
            best_loc = loc
            best_scale = scale
            best_h, best_w = sh, sw

    matched = best_val >= threshold
    return matched, best_val, best_loc, best_scale, (best_h, best_w)


def find_and_click_multiscale(img_path, timeout=20, region=None, confidence=None):
    """多尺度复合图像识别 + 点击，返回是否成功"""
    return _find_and_click_core(img_path, timeout, region, confidence,
                                multiscale=True, return_pos=False)


def find_multiscale(img_path, timeout=20, region=None, confidence=None):
    """多尺度复合图像识别，仅检测不点击，返回 True/False"""
    threshold = confidence if confidence is not None else CONFIDENCE
    resolved = config.resolve_template_path(img_path)
    template = _template_cache.get(resolved)
    if template is None:
        template = _imread_unicode(resolved)
        if template is None:
            print(f"❌ 图片文件不存在或无法读取：{resolved}")
            return False
        _template_cache[resolved] = template

    start = time.time()
    while time.time() - start < timeout:
        gray = _screenshot_gray(region)
        if gray is None:
            time.sleep(0.5)
            continue
        matched, max_val, _, scale, _ = _match_template_multiscale(
            gray, template, threshold)
        if matched:
            if scale != 1.0:
                print(f"🔍 复合匹配成功（仅检测）：缩放 {scale:.2f}x，置信度 {max_val:.3f}")
            return True
        time.sleep(0.3)
    return False


def find_and_click_pos_multiscale(img_path, timeout=20, region=None, confidence=None):
    """多尺度复合图像识别 + 点击，返回 (是否成功, (x,y))"""
    return _find_and_click_core(img_path, timeout, region, confidence,
                                multiscale=True, return_pos=True)


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

_kernel32 = ctypes.windll.kernel32

# SetThreadExecutionState flags
ES_CONTINUOUS      = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040
ES_DISPLAY_REQUIRED = 0x00000002

_prev_sleep_state = None
_sleep_prevent_count = 0
_sleep_lock = threading.Lock()


def prevent_sleep():
    """阻止系统进入睡眠/休眠状态，并保持显示器开启（运行关键操作时调用）"""
    global _sleep_prevent_count, _prev_sleep_state
    with _sleep_lock:
        _sleep_prevent_count += 1
        if _sleep_prevent_count == 1:
            _kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED | ES_DISPLAY_REQUIRED
            )


def allow_sleep():
    """恢复系统自动睡眠（与 prevent_sleep 配对调用）"""
    global _sleep_prevent_count
    with _sleep_lock:
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
        smooth_move_to(screen_w // 2, screen_h // 2, duration=0.5)
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
    使用 QQ 邮箱 SMTP 发送邮件通知（含重试）。
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

    msg = MIMEMultipart('alternative')
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html', 'utf-8'))

    max_retries = 3
    last_error = ""
    for attempt in range(max_retries):
        try:
            with smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=60) as server:
                server.login(sender_email, smtp_code)
                server.sendmail(sender_email, receiver_email, msg.as_string())
            return True, "邮件发送成功"
        except smtplib.SMTPAuthenticationError:
            return False, "SMTP 认证失败，请检查授权码是否正确"
        except smtplib.SMTPConnectError:
            last_error = "无法连接到 SMTP 服务器，请检查网络"
        except smtplib.SMTPServerDisconnected:
            last_error = "SMTP 服务器意外断开连接"
        except smtplib.SMTPException as e:
            last_error = f"SMTP 错误：{e}"
        except Exception as e:
            last_error = f"发送失败：{e}"
        if attempt < max_retries - 1:
            import time
            time.sleep(3)
    return False, last_error


# ==================== OCR 识别功能 ====================
_ocr_engine = None
_ocr_failed = False         # True = OCR 引擎不可用，全部降级为图像识别
_ocr_timeout_count = 0      # 连续 OCR 超时计数

def init_ocr_engine():
    """预初始化 RapidOCR 引擎。程序启动时调用，失败则标记 _ocr_failed"""
    global _ocr_engine, _ocr_failed, _ocr_timeout_count
    _ocr_timeout_count = 0
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
        _ocr_failed = False
        print("✅ RapidOCR 引擎初始化成功")
        return True
    except ImportError:
        print("⚠️ rapidocr-onnxruntime 未安装，OCR 功能不可用，全部使用图像识别")
        _ocr_failed = True
        return False
    except Exception as e:
        print(f"⚠️ RapidOCR 初始化失败：{e}，全部使用图像识别")
        _ocr_failed = True
        return False

def _get_ocr_engine():
    """获取 OCR 引擎（单例）。初始化失败返回 None"""
    global _ocr_engine
    if _ocr_failed:
        return None
    if _ocr_engine is None:
        init_ocr_engine()
    return _ocr_engine if not _ocr_failed else None


def ocr_recognize(region=None):
    """
    对屏幕指定区域进行 OCR 识别。
    region: (x, y, w, h) 或 None（全屏）
    返回: [(text, confidence, (x1,y1,x2,y2)), ...] 或 []
    """
    engine = _get_ocr_engine()
    if engine is None:
        return []

    try:
        if region:
            x, y, w, h = region
            screenshot = pyautogui.screenshot(region=(x, y, w, h))
        else:
            screenshot = pyautogui.screenshot()

        img_np = np.array(screenshot)
        screenshot.close()

        result, _ = engine(img_np)
        if result is None:
            return []

        # result 格式: [[box, text, confidence], ...]
        parsed = []
        for item in result:
            box, text, conf = item
            # box 是四个角点坐标 [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            if region:
                # 转换为屏幕绝对坐标
                bbox = (bbox[0] + region[0], bbox[1] + region[1],
                        bbox[2] + region[0], bbox[3] + region[1])
            parsed.append((text, float(conf) if conf is not None else 0.0, bbox))
        return parsed
    except Exception as e:
        print(f"⚠️ OCR 识别出错：{e}")
        return []


def ocr_find(text, region=None, timeout=20, confidence=0.8):
    """
    在屏幕指定区域查找包含指定文本的内容（仅检测，不点击）。
    返回: True/False
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        results = ocr_recognize(region)
        for recognized_text, conf, bbox in results:
            if conf >= confidence and text in recognized_text:
                return True
        time.sleep(1)
    return False


def ocr_find_and_click(text, region=None, timeout=20, confidence=0.8):
    """
    在屏幕指定区域查找包含指定文本的内容并点击其中心。
    返回: True（找到并点击）/ False（超时未找到）
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        results = ocr_recognize(region)
        for recognized_text, conf, bbox in results:
            if conf >= confidence and text in recognized_text:
                cx = int((bbox[0] + bbox[2]) / 2)
                cy = int((bbox[1] + bbox[3]) / 2)
                try:
                    smooth_move_to(cx, cy, duration=0.2)
                    pyautogui.click()
                except pyautogui.FailSafeException:
                    print("⚠️ 鼠标触碰屏幕角落，安全机制触发，跳过点击")
                    time.sleep(0.5)
                    continue
                return True
        time.sleep(1)
    return False


def ocr_find_and_click_offset(text, region=None, timeout=20, confidence=0.8, x_offset=0, y_offset=0):
    """
    在屏幕指定区域查找包含指定文本的内容并点击（支持偏移）。
    返回: True（找到并点击）/ False（超时未找到）
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        results = ocr_recognize(region)
        for recognized_text, conf, bbox in results:
            if conf >= confidence and text in recognized_text:
                cx = int((bbox[0] + bbox[2]) / 2) + x_offset
                cy = int((bbox[1] + bbox[3]) / 2) + y_offset
                try:
                    smooth_move_to(cx, cy, duration=0.2)
                    pyautogui.click()
                except pyautogui.FailSafeException:
                    print("⚠️ 鼠标触碰屏幕角落，安全机制触发，跳过点击")
                    time.sleep(0.5)
                    continue
                return True
        time.sleep(1)
    return False


def ocr_find_by_config(var_name, timeout=20):
    """
    根据 OCR 配置查找并点击。如果 var_name 没有 OCR 配置，返回 None（表示应使用图像匹配）。
    OCR 在配置了 ocr_configs 的模板上自动启用，无需手动开关。
    返回: True（OCR 找到并点击）/ False（OCR 超时未找到）/ None（无 OCR 配置）
    """
    settings = config.load_settings()
    ocr_configs = settings.get("ocr_configs", {})
    if var_name not in ocr_configs:
        return None

    ocr_cfg = ocr_configs[var_name]
    region = tuple(ocr_cfg["region"]) if ocr_cfg.get("region") else None
    # 无区域时尝试全局 OCR 区域（全局 OCR 或全局文本配置启用时均可使用）
    if not region:
        global_region = settings.get("global_ocr_region", [0, 0, 0, 0])
        if global_region[2] > 0 and global_region[3] > 0:
            region = tuple(global_region)
    text = ocr_cfg.get("text", "")
    conf = ocr_cfg.get("confidence") or settings.get("global_ocr_confidence", 0.8)

    if not text:
        return None

    return ocr_find_and_click(text, region=region, timeout=timeout, confidence=conf)


# config 图片路径 → var_name 映射（用于 OCR 智能调度）
_IMAGE_TO_VAR = None

def _get_image_to_var():
    global _IMAGE_TO_VAR
    if _IMAGE_TO_VAR is None:
        _IMAGE_TO_VAR = {
            config.IMAGE_LOGIN_BTN: "IMAGE_LOGIN_BTN",
            config.DELTA_LAUNCH_BTN: "DELTA_LAUNCH_BTN",
            config.Hazard_Operations: "Hazard_Operations",
            config.Special_Ops: "Special_Ops",
            config.Tech_Center: "Tech_Center",
            config.Tool_Bench: "Tool_Bench",
            config.Armor_Station: "Armor_Station",
            config.Pharmacy_Station: "Pharmacy_Station",
            config.MAKE: "MAKE",
            config.Produce: "Produce",
            config.Collect: "Collect",
            config.Auto_fill: "Auto_fill",
            config.Claim_Reward: "Claim_Reward",
            config.COIN_GAME: "COIN_GAME",
            config.Warehouse: "Warehouse",
            config.Sell: "Sell",
            config.List_Item: "List_Item",
            config.Discount: "Discount",
            config.Confirm_Listing: "Confirm_Listing",
            config.EMAIL_MAIL: "EMAIL_MAIL",
            config.EMAIL_TRADE_HOUSE: "EMAIL_TRADE_HOUSE",
            config.EMAIL_CLAIM_ALL: "EMAIL_CLAIM_ALL",
            config.EMAIL_RECEIVE_COMPLETED: "EMAIL_RECEIVE_COMPLETED",
            config.Produce_TechCenter: "Produce_TechCenter",
            config.Produce_ToolBench: "Produce_ToolBench",
            config.Produce_ArmorStation: "Produce_ArmorStation",
            config.Produce_PharmacyStation: "Produce_PharmacyStation",
        }
    return _IMAGE_TO_VAR


def find_and_click_smart(img_path, timeout=20, region=None, confidence=None):
    """
    智能识别点击：优先使用 OCR（如果配置了），否则使用图像匹配。
    自动根据 img_path 查找对应的 var_name OCR 配置。
    连续 OCR 超时 2 次后自动禁用 OCR，全部降级为图像识别。
    """
    global _ocr_timeout_count, _ocr_failed
    var_map = _get_image_to_var()
    var_name = var_map.get(img_path)

    if var_name and not _ocr_failed:
        ocr_result = ocr_find_by_config(var_name, timeout=timeout)
        if ocr_result is True:
            _ocr_timeout_count = 0  # 成功则重置计数
            return True
        if ocr_result is False:
            _ocr_timeout_count += 1
            print(f"⚠️ OCR 超时，回退到图像匹配：{var_name}（连续超时 {_ocr_timeout_count}/2）")
            if _ocr_timeout_count >= 2:
                _ocr_failed = True
                print("⚠️ OCR 连续超时 2 次，已自动禁用 OCR，后续全部使用图像识别")

    return find_and_click(img_path, timeout=timeout, region=region, confidence=confidence)


# ==================== 窗口图标设置 ====================
def set_window_icon(win):
    """为 Tkinter 窗口统一设置应用图标"""
    try:
        icon_path = config.resource_path("picture/icon/icon.ico")
        if os.path.exists(icon_path):
            from PIL import Image, ImageTk
            win._icon_photo = ImageTk.PhotoImage(Image.open(icon_path))
            win.iconphoto(False, win._icon_photo)
    except Exception:
        pass


# ==================== 资产数值解析/格式化 ====================
def parse_asset_value(val_str):
    """将资产字符串转为数值，如 '1.2M' → 1200000"""
    if not val_str or val_str == "0":
        return 0
    val_str = val_str.strip().upper()
    multipliers = {"K": 1000, "M": 1_000_000, "B": 1_000_000_000}
    for suffix, mult in multipliers.items():
        if val_str.endswith(suffix):
            try:
                return float(val_str[:-1]) * mult
            except ValueError:
                return 0
    try:
        return float(val_str)
    except ValueError:
        return 0


def format_asset_num(val):
    """将数值格式化为资产字符串，如 1200000 → '1.20M'"""
    abs_val = abs(val)
    if abs_val >= 1_000_000_000:
        return f"{val / 1_000_000_000:.2f}B"
    elif abs_val >= 1_000_000:
        return f"{val / 1_000_000:.2f}M"
    elif abs_val >= 1_000:
        return f"{val / 1_000:.1f}K"
    else:
        return f"{val:.0f}"