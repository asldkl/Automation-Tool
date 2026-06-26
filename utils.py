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
from config import (CONFIDENCE, WAIT_TIME, WEGAME_PROCESS, DELTA_PROCESS)
import relative_mouse_move
import ctypes


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

# 模板图片缓存，LRU 淘汰避免内存无限增长
_MAX_CACHE_SIZE = 50
_template_cache = {}
_template_cache_lock = threading.Lock()

def _imread_unicode(path, flags=cv2.IMREAD_GRAYSCALE):
    """cv2.imread 不支持非 ASCII 路径（如中文），用 np.fromfile + cv2.imdecode 替代"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, flags)
    except Exception:
        return None

def _cache_get(key):
    """LRU 缓存读取：命中时移至末尾（最近使用）"""
    with _template_cache_lock:
        template = _template_cache.pop(key, None)
        if template is not None:
            _template_cache[key] = template
        return template

def _cache_put(key, value):
    """LRU 缓存写入：超限时淘汰最早条目"""
    with _template_cache_lock:
        if len(_template_cache) >= _MAX_CACHE_SIZE:
            oldest = next(iter(_template_cache))
            del _template_cache[oldest]
        _template_cache[key] = value

def clear_template_cache():
    """清除模板缓存（用于重新截图后刷新）"""
    with _template_cache_lock:
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
        arr = np.array(screen)
    except Exception:
        return None
    finally:
        try:
            screen.close()
        except Exception:
            pass
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
    template = _cache_get(resolved)
    if template is None:
        template = _imread_unicode(resolved)
        if template is None:
            print(f"❌ 图片文件不存在或无法读取：{resolved}")
            return (False, None) if return_pos else False
        _cache_put(resolved, template)

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
    template = _cache_get(resolved)
    if template is None:
        template = _imread_unicode(resolved)
        if template is None:
            print(f"❌ 图片文件不存在或无法读取：{resolved}")
            return False
        _cache_put(resolved, template)

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
_ocr_failed = False                          # True = OCR 引擎初始化失败，全局不可用
_ocr_failures = {}                           # var_name → [failure_timestamps]，连续失败后临时禁用
_ocr_failures_lock = threading.Lock()        # 线程安全锁
_OCR_MAX_FAILURES = 3                        # 连续失败次数阈值
_OCR_DISABLE_SECONDS = 300                   # 临时禁用时长（5分钟），超时自动恢复

def _ocr_is_disabled(var_name):
    """检查指定 var_name 是否因连续失败被临时禁用（5分钟后自动恢复）"""
    with _ocr_failures_lock:
        timestamps = _ocr_failures.get(var_name, [])
        now = time.time()
        cutoff = now - _OCR_DISABLE_SECONDS
        recent = [t for t in timestamps if t > cutoff]
        _ocr_failures[var_name] = recent
        return len(recent) >= _OCR_MAX_FAILURES

def _ocr_record_failure(var_name):
    """记录一次 OCR 失败"""
    with _ocr_failures_lock:
        _ocr_failures.setdefault(var_name, []).append(time.time())

def _ocr_record_success(var_name):
    """OCR 成功后清除该 var_name 的失败记录"""
    with _ocr_failures_lock:
        _ocr_failures.pop(var_name, None)

def init_ocr_engine():
    """预初始化 RapidOCR 引擎。程序启动时调用，失败则标记 _ocr_failed"""
    global _ocr_engine, _ocr_failed
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


def _click_pos_valid(cx, cy):
    """检查点击坐标是否在屏幕有效范围内（边缘 10px 留白）"""
    screen_w, screen_h = pyautogui.size()
    margin = 10
    if cx < margin or cy < margin or cx > screen_w - margin or cy > screen_h - margin:
        print(f"⚠️ 忽略可疑坐标 ({cx}, {cy})")
        return False
    return True


def ocr_find_and_click(text, region=None, timeout=20, confidence=0.8):
    """
    在屏幕指定区域查找包含指定文本的内容并点击其中心。
    返回: True（找到并点击）/ False（超时未找到）
    """
    start_time = time.time()
    first_scan = True
    while time.time() - start_time < timeout:
        results = ocr_recognize(region)
        for recognized_text, conf, bbox in results:
            if conf >= confidence and text in recognized_text:
                cx = int((bbox[0] + bbox[2]) / 2)
                cy = int((bbox[1] + bbox[3]) / 2)
                if not _click_pos_valid(cx, cy):
                    continue
                try:
                    smooth_move_to(cx, cy, duration=0.2)
                    pyautogui.click()
                except pyautogui.FailSafeException:
                    print("⚠️ 鼠标触碰屏幕角落，安全机制触发，跳过点击")
                    time.sleep(0.5)
                    continue
                return True
        # 首次扫描未命中时，打印实际识别到的文字供调试
        if first_scan and results:
            matches = [f"'{r[0]}'(conf={r[1]:.2f})" for r in results if text in r[0]]
            others = [f"'{r[0]}'(conf={r[1]:.2f})" for r in results if text not in r[0]]
            if matches:
                print(f"  ℹ️ 找到文字但置信度不足：{', '.join(matches[:5])}")
            if others:
                print(f"  ℹ️ 区域内识别到：{', '.join(others[:5])}")
            first_scan = False
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
                if not _click_pos_valid(cx, cy):
                    continue
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
    ocr_cfg = ocr_configs.get(var_name, {})

    # 从 ocr_configs 获取文本，没有则回退到 global_ocr_texts
    text = ocr_cfg.get("text", "")
    if not text:
        global_texts = settings.get("global_ocr_texts", {})
        text = global_texts.get(var_name, "")
    if not text:
        return None

    region = None
    cfg_region = ocr_cfg.get("region")
    if cfg_region and len(cfg_region) == 4 and cfg_region[2] > 0 and cfg_region[3] > 0:
        region = tuple(cfg_region)
    # 无有效区域时尝试全局 OCR 区域
    if not region:
        global_region = settings.get("global_ocr_region", [0, 0, 0, 0])
        if global_region[2] > 0 and global_region[3] > 0:
            region = tuple(global_region)
    conf = ocr_cfg.get("confidence") or settings.get("global_ocr_confidence", 0.8)

    return ocr_find_and_click(text, region=region, timeout=timeout, confidence=conf)


# config 图片路径 → var_name 映射（用于 OCR 智能调度）
# 自动从 TEMPLATE_CAPTURE_LIST 生成，无需手动维护
_IMAGE_TO_VAR = None

def _get_image_to_var():
    global _IMAGE_TO_VAR
    if _IMAGE_TO_VAR is None:
        _IMAGE_TO_VAR = {}
        for entry in config.TEMPLATE_CAPTURE_LIST:
            var_name = entry[0]
            resolved = getattr(config, var_name, None)
            if resolved:
                _IMAGE_TO_VAR[resolved] = var_name
    return _IMAGE_TO_VAR


def find_and_click_smart(img_path, timeout=20, region=None, confidence=None,
                         clicks=1, x_offset=0, y_offset=0):
    """
    智能识别点击：优先使用 OCR（如果配置了），否则使用图像匹配。
    自动根据 img_path 查找对应的 var_name OCR 配置。
    单 var_name 连续 OCR 失败 3 次后临时禁用（5分钟自动恢复），仅影响该 var_name。
    可通过全局 OCR 设置中的"OCR 降级"关闭降级，OCR 失败后直接返回 False。
    """
    var_map = _get_image_to_var()
    var_name = var_map.get(img_path)

    if var_name and not _ocr_failed and not _ocr_is_disabled(var_name):
        ocr_result = ocr_find_by_config(var_name, timeout=timeout)
        if ocr_result is True:
            _ocr_record_success(var_name)
            print(f"✅ OCR 识别成功：{var_name}")
            return True
        if ocr_result is False:
            settings = config.load_settings()
            downgrade_enabled = settings.get("ocr_downgrade_enabled", True)
            if not downgrade_enabled:
                print(f"❌ OCR 未识别到：{var_name}（降级已关闭，不使用图片匹配）")
                return False
            _ocr_record_failure(var_name)
            if _ocr_is_disabled(var_name):
                print(f"⚠️ {var_name} OCR 连续失败 {_OCR_MAX_FAILURES} 次，已临时禁用（5分钟后自动恢复）")
            else:
                print(f"⚠️ OCR 超时，回退到图像匹配：{var_name}")

    if var_name:
        print(f"🔍 使用图片识别：{var_name}")
    else:
        print(f"🔍 使用图片识别：{os.path.basename(img_path)}")

    return find_and_click(img_path, timeout=timeout, region=region, confidence=confidence,
                          clicks=clicks, x_offset=x_offset, y_offset=y_offset)


# ==================== 窗口图标设置 ====================
def set_window_icon(win):
    """为 Tkinter 窗口统一设置应用图标，最小化恢复后自动重新设置"""
    try:
        icon_path = config.resource_path("picture/icon/icon.ico")
        if os.path.exists(icon_path):
            from PIL import Image, ImageTk
            win._icon_photo = ImageTk.PhotoImage(Image.open(icon_path))
            win.iconphoto(False, win._icon_photo)
            # 绑定窗口恢复事件，防止最小化后图标消失
            def _reapply_icon(event=None):
                try:
                    win.iconphoto(False, win._icon_photo)
                except Exception:
                    pass
            win.bind('<Map>', _reapply_icon)
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


# ==================== 冷却到期定时任务兜底 ====================
COOLDOWN_SIGNAL_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_cooldown_signal")
COOLDOWN_TASK_NAME = "DeltaAutoTool_Cooldown"


def write_cooldown_signal():
    """写入冷却触发信号文件（定时任务触发时调用，通知已有实例）"""
    try:
        import datetime
        with open(COOLDOWN_SIGNAL_PATH, "w", encoding="utf-8") as f:
            f.write(datetime.datetime.now().isoformat())
        print(f"[OK] 已写入冷却触发信号文件")
    except Exception as e:
        print(f"[WARN] 写入冷却信号文件失败: {e}")


def check_cooldown_signal():
    """检查并消费信号文件，返回 True 表示有信号"""
    try:
        os.remove(COOLDOWN_SIGNAL_PATH)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def create_cooldown_scheduled_task(trigger_time):
    """创建一次性定时任务，到期时写信号文件并启动程序
    trigger_time: datetime 对象
    """
    import subprocess, tempfile, sys
    import datetime

    trigger_str = trigger_time.strftime("%Y-%m-%dT%H:%M:%S")

    # 创建辅助脚本：写信号文件 + 启动程序（无窗口）
    # 放到 ProgramData 目录避免中文路径问题
    # 用 GBK 编码写入 cmd 脚本，用 VBScript 隐藏窗口运行
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    helper_dir = os.path.join(programdata, "DeltaAutoTool")
    os.makedirs(helper_dir, exist_ok=True)
    cmd_path = os.path.join(helper_dir, "cooldown_trigger.cmd")
    vbs_path = os.path.join(helper_dir, "cooldown_trigger.vbs")

    if getattr(sys, 'frozen', False):
        exe_path = sys.executable
        with open(cmd_path, 'w', encoding='gbk') as f:
            f.write(f'@echo signal > "{COOLDOWN_SIGNAL_PATH}"\n')
            f.write(f'start "" "{exe_path}"\n')
    else:
        python_exe = sys.executable
        script_path = os.path.abspath(sys.argv[0]) if sys.argv[0] else os.path.abspath(__file__)
        with open(cmd_path, 'w', encoding='gbk') as f:
            f.write(f'@echo signal > "{COOLDOWN_SIGNAL_PATH}"\n')
            f.write(f'"{python_exe}" "{script_path}" --auto-start\n')

    # VBScript 包装器：隐藏 cmd 窗口运行
    with open(vbs_path, 'w', encoding='gbk') as f:
        f.write(f'Set objShell = CreateObject("WScript.Shell")\n')
        f.write(f'objShell.Run "cmd /c ""{cmd_path}""", 0, False\n')

    # 用 vbs 作为实际执行入口
    helper_path = vbs_path

    # 使用 schtasks 创建定时任务
    trigger_date = trigger_time.strftime("%Y/%m/%d")
    trigger_time_str = trigger_time.strftime("%H:%M")

    try:
        # 先删除旧任务（静默，失败无所谓）
        subprocess.run(
            ["schtasks", "/delete", "/tn", COOLDOWN_TASK_NAME, "/f"],
            capture_output=True, timeout=10
        )

        # 创建新任务（用 wscript.exe 运行 VBScript，完全无窗口）
        result = subprocess.run(
            ["schtasks", "/create",
             "/tn", COOLDOWN_TASK_NAME,
             "/tr", f'wscript.exe "{vbs_path}"',
             "/sc", "once",
             "/st", trigger_time_str,
             "/sd", trigger_date,
             "/f"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            print(f"[OK] 已创建冷却定时任务：{trigger_time.strftime('%Y-%m-%d %H:%M')}")
            return True
        else:
            print(f"[WARN] 创建冷却定时任务失败: {result.stderr}")
            return False
    except Exception as e:
        print(f"[WARN] 创建冷却定时任务失败: {e}")
        return False


def remove_cooldown_scheduled_task():
    """删除冷却到期定时任务"""
    import subprocess
    try:
        subprocess.run(
            ["schtasks", "/delete", "/tn", COOLDOWN_TASK_NAME, "/f"],
            capture_output=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        print(f"[OK] 已删除冷却定时任务")
        return True
    except Exception:
        return False


# ==================== 窗口大小记忆 ====================
def restore_window_geometry(win, settings_key, default_size="550x700", min_size=None):
    """恢复窗口大小和位置，返回 True=已恢复，False=使用默认"""
    import config
    settings = config.load_settings()
    saved = settings.get(settings_key, "")
    if saved and "x" in saved:
        try:
            win.geometry(saved)
            return True
        except Exception:
            pass
    # 使用默认大小并居中
    w, h = map(int, default_size.split("x"))
    if min_size:
        win.minsize(*min_size)
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")
    return False


def save_window_geometry(win, settings_key):
    """保存窗口大小和位置到设置文件"""
    import config
    try:
        win.update_idletasks()
        geo = win.geometry()
        if not geo or "x" not in geo:
            return
        settings = config.load_settings()
        settings[settings_key] = geo
        config.save_settings(settings)
    except Exception:
        pass


def bind_window_geometry(win, settings_key, default_size=None, min_size=None):
    """一行代码给窗口加上大小记忆：恢复上次大小 + 关闭时自动保存"""
    if default_size:
        restore_window_geometry(win, settings_key, default_size, min_size)
    def _on_close():
        save_window_geometry(win, settings_key)
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", _on_close)