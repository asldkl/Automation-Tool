"""
Interception 驱动级键盘输入模块
通过 ctypes 调用 interception.dll 实现驱动级键盘模拟
必须安装 Interception 驱动且 DLL 可用，否则无法工作
"""
import os
import sys
import ctypes
import ctypes.wintypes
import time

# DLL 句柄和函数引用
_dll = None
_dll_loaded = False
_create_context = None
_destroy_context = None
_set_filter = None
_send = None
_is_keyboard = None

# predicate 回调类型：int (*)(InterceptionDevice)
_INTERCEPTION_PREDICATE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int)

def _accept_all_keyboard(device):
    """predicate：接受所有键盘设备（device <= INTERCEPTION_MAX_KEYBOARD=10）"""
    return 1 if device >= 1 and device <= 10 else 0

# 保持回调引用防止被垃圾回收
_predicate_callback = _INTERCEPTION_PREDICATE(_accept_all_keyboard)


class InterceptionKeyStroke(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("state", ctypes.c_ushort),
        ("information", ctypes.c_uint),
    ]


# InterceptionKeyState
KEY_DOWN = 0x00
KEY_UP = 0x01
KEY_E0 = 0x02

# 字符 → (扫描码, 是否需要 Shift)
_CHAR_TO_SCANCODE = {
    # 数字
    '1': (0x02, False), '2': (0x03, False), '3': (0x04, False),
    '4': (0x05, False), '5': (0x06, False), '6': (0x07, False),
    '7': (0x08, False), '8': (0x09, False), '9': (0x0A, False),
    '0': (0x0B, False),
    # Shift + 数字 = 符号
    '!': (0x02, True), '@': (0x03, True), '#': (0x04, True),
    '$': (0x05, True), '%': (0x06, True), '^': (0x07, True),
    '&': (0x08, True), '*': (0x09, True), '(': (0x0A, True),
    ')': (0x0B, True),
    # 字母（小写）
    'q': (0x10, False), 'w': (0x11, False), 'e': (0x12, False),
    'r': (0x13, False), 't': (0x14, False), 'y': (0x15, False),
    'u': (0x16, False), 'i': (0x17, False), 'o': (0x18, False),
    'p': (0x19, False), 'a': (0x1E, False), 's': (0x1F, False),
    'd': (0x20, False), 'f': (0x21, False), 'g': (0x22, False),
    'h': (0x23, False), 'j': (0x24, False), 'k': (0x25, False),
    'l': (0x26, False), 'z': (0x2C, False), 'x': (0x2D, False),
    'c': (0x2E, False), 'v': (0x2F, False), 'b': (0x30, False),
    'n': (0x31, False), 'm': (0x32, False),
    # 字母（大写）
    'Q': (0x10, True), 'W': (0x11, True), 'E': (0x12, True),
    'R': (0x13, True), 'T': (0x14, True), 'Y': (0x15, True),
    'U': (0x16, True), 'I': (0x17, True), 'O': (0x18, True),
    'P': (0x19, True), 'A': (0x1E, True), 'S': (0x1F, True),
    'D': (0x20, True), 'F': (0x21, True), 'G': (0x22, True),
    'H': (0x23, True), 'J': (0x24, True), 'K': (0x25, True),
    'L': (0x26, True), 'Z': (0x2C, True), 'X': (0x2D, True),
    'C': (0x2E, True), 'V': (0x2F, True), 'B': (0x30, True),
    'N': (0x31, True), 'M': (0x32, True),
    # 常用符号
    '-': (0x0C, False), '_': (0x0C, True),
    '=': (0x0D, False), '+': (0x0D, True),
    '[': (0x1A, False), '{': (0x1A, True),
    ']': (0x1B, False), '}': (0x1B, True),
    '\\': (0x2B, False), '|': (0x2B, True),
    ';': (0x27, False), ':': (0x27, True),
    "'": (0x28, False), '"': (0x28, True),
    '`': (0x29, False), '~': (0x29, True),
    ',': (0x33, False), '<': (0x33, True),
    '.': (0x34, False), '>': (0x34, True),
    '/': (0x35, False), '?': (0x35, True),
    ' ': (0x39, False),
    # 特殊键
    '\n': (0x1C, False),
    '\t': (0x0F, False),
}


def _load_dll():
    """加载 interception.dll"""
    global _dll, _dll_loaded, _create_context, _destroy_context
    global _set_filter, _send, _is_keyboard

    if _dll_loaded:
        return _dll is not None

    _dll_loaded = True

    # DLL 搜索路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    meipass = getattr(sys, '_MEIPASS', None)

    search_paths = [
        os.path.join(script_dir, "interception.dll"),
        os.path.join(script_dir, "Interception-master", "library", "interception.dll"),
        os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "interception.dll"),
    ]
    if meipass:
        search_paths.insert(0, os.path.join(meipass, "interception.dll"))

    for dll_path in search_paths:
        if os.path.exists(dll_path):
            try:
                _dll = ctypes.CDLL(dll_path)
                _setup_functions()
                print(f"[OK] Interception DLL 已加载: {dll_path}")
                return True
            except Exception as e:
                print(f"[WARN] 加载 {dll_path} 失败: {e}")
                _dll = None

    # 尝试系统 PATH
    try:
        _dll = ctypes.CDLL("interception.dll")
        _setup_functions()
        print("[OK] Interception DLL 已从系统路径加载")
        return True
    except Exception:
        _dll = None
        print("[ERROR] Interception DLL 未找到！请安装 Interception 驱动并确保 interception.dll 在项目目录中")
        return False


def _setup_functions():
    """配置 DLL 函数签名"""
    global _create_context, _destroy_context, _set_filter, _send, _is_keyboard

    _create_context = _dll.interception_create_context
    _create_context.restype = ctypes.c_void_p
    _create_context.argtypes = []

    _destroy_context = _dll.interception_destroy_context
    _destroy_context.restype = None
    _destroy_context.argtypes = [ctypes.c_void_p]

    _set_filter = _dll.interception_set_filter
    _set_filter.restype = None
    _set_filter.argtypes = [ctypes.c_void_p, _INTERCEPTION_PREDICATE, ctypes.c_ushort]

    _send = _dll.interception_send
    _send.restype = ctypes.c_int
    _send.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(InterceptionKeyStroke), ctypes.c_uint]

    _is_keyboard = _dll.interception_is_keyboard
    _is_keyboard.restype = ctypes.c_int
    _is_keyboard.argtypes = [ctypes.c_int]


def _check_driver():
    """验证 Interception 驱动是否真正可用"""
    if not _load_dll():
        return False
    try:
        ctx = _create_context()
        if not ctx:
            return False
        # 发送左 Shift 释放事件作为测试（无害操作，不会产生实际按键效果）
        stroke = InterceptionKeyStroke(0x2A, KEY_UP, 0)
        result = _send(ctx, 1, stroke, 1)
        _destroy_context(ctx)
        return result > 0
    except Exception:
        return False


def is_available():
    """检查 Interception 驱动和 DLL 是否可用"""
    return _check_driver()


def get_backend():
    """返回当前使用的键盘后端名称"""
    if is_available():
        return "Interception"
    return "不可用"


def send_string(text, interval=0.02):
    """逐字符发送按键（扫描码方式）

    Args:
        text: 要输入的文本
        interval: 每个字符间隔秒数

    Returns:
        True=成功，False=失败
    """
    if not text:
        return True

    if not _load_dll():
        print("[ERROR] Interception 不可用，无法输入")
        return False

    ctx = None
    try:
        # FILTER_KEY_ALL = 0xFFFF
        ctx = _create_context()
        if not ctx:
            print("[ERROR] interception_create_context 失败")
            return False

        _set_filter(ctx, _predicate_callback, 0xFFFF)

        # 第一个设备是键盘 1
        keyboard_device = 1  # INTERCEPTION_KEYBOARD(0)

        for ch in text:
            if ch not in _CHAR_TO_SCANCODE:
                continue

            scan_code, need_shift = _CHAR_TO_SCANCODE[ch]

            if need_shift:
                shift_down = InterceptionKeyStroke(0x2A, KEY_DOWN, 0)
                if _send(ctx, keyboard_device, shift_down, 1) <= 0:
                    return False

            key_down = InterceptionKeyStroke(scan_code, KEY_DOWN, 0)
            if _send(ctx, keyboard_device, key_down, 1) <= 0:
                return False

            key_up = InterceptionKeyStroke(scan_code, KEY_UP, 0)
            if _send(ctx, keyboard_device, key_up, 1) <= 0:
                return False

            if need_shift:
                shift_up = InterceptionKeyStroke(0x2A, KEY_UP, 0)
                if _send(ctx, keyboard_device, shift_up, 1) <= 0:
                    return False

            time.sleep(interval)

        return True
    except Exception as e:
        print(f"[ERROR] Interception send_string 失败: {e}")
        return False
    finally:
        if ctx:
            _destroy_context(ctx)


def send_key(char, interval=0.02):
    """发送单个按键事件

    Args:
        char: 单个字符
        interval: 按键后等待秒数

    Returns:
        True=成功，False=失败
    """
    if not char:
        return True

    if not _load_dll():
        print("[ERROR] Interception 不可用，无法输入")
        return False

    ctx = None
    try:
        ctx = _create_context()
        if not ctx:
            return False

        _set_filter(ctx, _predicate_callback, 0xFFFF)
        keyboard_device = 1

        if char in _CHAR_TO_SCANCODE:
            scan_code, need_shift = _CHAR_TO_SCANCODE[char]

            if need_shift:
                shift_down = InterceptionKeyStroke(0x2A, KEY_DOWN, 0)
                if _send(ctx, keyboard_device, shift_down, 1) <= 0:
                    return False

            key_down = InterceptionKeyStroke(scan_code, KEY_DOWN, 0)
            if _send(ctx, keyboard_device, key_down, 1) <= 0:
                return False

            key_up = InterceptionKeyStroke(scan_code, KEY_UP, 0)
            if _send(ctx, keyboard_device, key_up, 1) <= 0:
                return False

            if need_shift:
                shift_up = InterceptionKeyStroke(0x2A, KEY_UP, 0)
                if _send(ctx, keyboard_device, shift_up, 1) <= 0:
                    return False

            time.sleep(interval)

        return True
    except Exception as e:
        print(f"[ERROR] Interception send_key 失败: {e}")
        return False
    finally:
        if ctx:
            _destroy_context(ctx)
