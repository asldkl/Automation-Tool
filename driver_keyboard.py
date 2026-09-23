# -*- coding: utf-8 -*-
"""驱动级键盘输入模块 —— 统一键盘输入接口，按优先级自动选择后端。

后端与优先级（配置键 `keyboard_backend`）
----------------------------------------
    auto（默认）  STM32 外部硬件键盘 → Interception 驱动 → SendInput
    stm32        只用 STM32 外部硬件键盘（未接则失败，不回退）
    interception 只用 Interception 驱动
    sendinput    只用 Win32 SendInput（纯软件模拟，游戏/反作弊可能不认）

**为什么 auto 把 STM32 排在 Interception 前面**：两者都是硬件级输入（游戏/反作弊认），
但 Interception 是**内核键盘类上层筛选器** —— 一旦挂死会让整机键盘失效、只能重启（有实例）；
STM32 是独立的 USB HID 设备，坏了也只是它自己不按键。两者都能用时，没有理由优先用有副作用的那个。

⚠️ **不做「输入中途换后端」**：密码类输入若在中途换后端，同一个字符串会被打两遍 → 必然错误。
所以策略是「先挑一个可用后端，然后只用它」；只有当前后端**整体不可用**（比如设备被拔了）
时才会重新挑，而不是在一次输入失败后切换。

对外只返回 True/False，绝不抛异常。
"""
import ctypes
import time

_settings = {}          # 由 set_settings() 注入（默认空 = 全部用默认值）
_CHOSEN = None          # 已选定的后端；仅当它不再可用时才重新挑

BACKENDS = ("stm32", "interception", "sendinput")
_LABEL = {
    "stm32": "STM32 外部硬件键盘",
    "interception": "Interception 驱动",
    "sendinput": "SendInput（软件模拟）",
}


def set_settings(settings):
    """注入应用设置（不调用也能跑：全部走默认值，STM32 仍会按 VID/PID 自动查找）"""
    global _settings, _CHOSEN
    _settings = dict(settings or {})
    _CHOSEN = None       # 配置变了，重新挑


# --------------------------------------------------------------------------- #
# 各后端的可用性判定
# --------------------------------------------------------------------------- #

def _available(name):
    try:
        if name == "stm32":
            import stm32_keyboard
            return stm32_keyboard.is_available(_settings)
        if name == "interception":
            import interception_keyboard
            return bool(interception_keyboard.is_available())
        if name == "sendinput":
            return True          # 纯用户态 API，始终可用
    except Exception:
        return False
    return False


def _order():
    """按配置决定尝试顺序"""
    want = str((_settings or {}).get("keyboard_backend", "auto") or "auto").strip().lower()
    if want in BACKENDS:
        return (want,)
    return BACKENDS          # auto / 非法值 → 默认顺序


def _pick(force=False):
    """挑一个可用后端并缓存；force=True 时强制重挑"""
    global _CHOSEN
    if not force and _CHOSEN and _available(_CHOSEN):
        return _CHOSEN
    for name in _order():
        if _available(name):
            _CHOSEN = name
            return name
    _CHOSEN = None
    return None


# --------------------------------------------------------------------------- #
# 后端实现
# --------------------------------------------------------------------------- #

def _send_stm32(text, interval):
    import stm32_keyboard
    return stm32_keyboard.send_string(text, interval=interval, settings=_settings)


def _send_interception(text, interval):
    import interception_keyboard
    return interception_keyboard.send_string(text, interval=interval)


# --- SendInput（最后一档兜底，纯用户态模拟）------------------------------- #
_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

_VK_RETURN = 0x0D
_VK_TAB = 0x09


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", _ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):
    """只为把 union 撑到正确大小：x64 下 INPUT 必须是 40 字节，否则 SendInput 报参数错误"""
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", _ULONG_PTR)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUT_UNION)]


_user32 = None


def _get_user32():
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
        u.SendInput.restype = ctypes.c_uint
        _user32 = u
    return _user32


def _sendinput_events(*events):
    """events: (wVk, wScan, dwFlags) 序列；返回是否全部投递成功"""
    arr = (_INPUT * len(events))()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = _INPUT_KEYBOARD
        arr[i].ki.wVk = vk
        arr[i].ki.wScan = scan
        arr[i].ki.dwFlags = flags
        arr[i].ki.time = 0
        arr[i].ki.dwExtraInfo = 0
    sent = _get_user32().SendInput(len(events), arr, ctypes.sizeof(_INPUT))
    return sent == len(events)


def _send_sendinput(text, interval):
    """用 KEYEVENTF_UNICODE 逐字符投递（不需要扫描码表，字母数字符号都覆盖）

    ⚠️ 这是软件模拟：按键带 LLKHF_INJECTED 标记，部分游戏/启动器会忽略 ——
    所以它只作为最后一档兜底。
    """
    if not text:
        return True
    _get_user32()        # 预热 + 校验签名
    delay = max(0.0, float(interval))
    for ch in text:
        if ch == "\n":
            ok = _sendinput_events((_VK_RETURN, 0, 0), (_VK_RETURN, 0, _KEYEVENTF_KEYUP))
        elif ch == "\t":
            ok = _sendinput_events((_VK_TAB, 0, 0), (_VK_TAB, 0, _KEYEVENTF_KEYUP))
        else:
            code = ord(ch)
            if code > 0xFFFF:                 # 超出 BMP 的字符拆成代理对
                hi = 0xD800 + ((code - 0x10000) >> 10)
                lo = 0xDC00 + ((code - 0x10000) & 0x3FF)
                ok = _sendinput_events(
                    (0, hi, _KEYEVENTF_UNICODE), (0, hi, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP),
                    (0, lo, _KEYEVENTF_UNICODE), (0, lo, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
            else:
                ok = _sendinput_events((0, code, _KEYEVENTF_UNICODE),
                                       (0, code, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP))
        if not ok:
            print("⚠️ SendInput 投递失败（GetLastError=%d）" % ctypes.get_last_error())
            return False
        if delay:
            time.sleep(delay)
    return True


_SENDERS = {
    "stm32": _send_stm32,
    "interception": _send_interception,
    "sendinput": _send_sendinput,
}


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #

def is_available():
    """是否有任何可用的键盘后端"""
    return _pick() is not None


def get_backend():
    """返回当前生效的后端名（含细节），给日志与设置界面用"""
    name = _pick()
    if name is None:
        return "无可用后端"
    if name == "stm32":
        try:
            import stm32_keyboard
            return stm32_keyboard.get_backend(_settings)
        except Exception:
            pass
    if name == "interception":
        try:
            import interception_keyboard
            return interception_keyboard.get_backend()
        except Exception:
            pass
    return _LABEL.get(name, name)


def send_string(text, interval=0.02):
    """发送字符串。**只用挑定的那一个后端**（避免中途换后端把同一串打两遍）

    返回 True/False；失败时打印明确原因，绝不抛异常。
    """
    if not text:
        return True

    name = _pick()
    if name is None:
        print("⚠️ 键盘输入失败：没有任何可用后端（STM32 未接 / Interception 驱动不可用 / SendInput 异常）")
        return False

    try:
        return bool(_SENDERS[name](text, interval))
    except Exception as e:
        print("⚠️ 键盘输入失败（后端 %s 异常）：%s" % (_LABEL.get(name, name), e))
        return False


def send_key(char, interval=0.02):
    return send_string(char, interval=interval)


def backend_report():
    """各后端可用性一览（给设置界面的状态显示用）；返回 (列表, 当前选中后端)"""
    lines = []
    for name in BACKENDS:
        ok = _available(name)
        if name == "stm32":
            try:
                import stm32_keyboard
                detail = stm32_keyboard.get_backend(_settings)
                if not ok:
                    detail += " / " + (stm32_keyboard.last_error() or "不可用")
            except Exception as e:
                detail = "模块异常：%s" % e
        elif name == "interception":
            detail = "驱动可用" if ok else "驱动不可用（未安装或未启动）"
        else:
            detail = "始终可用（软件模拟，游戏可能不认）"
        lines.append(("✓" if ok else "✗", _LABEL.get(name, name), detail))
    return lines, _pick()
