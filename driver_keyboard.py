"""
驱动级键盘输入模块
统一键盘输入接口：优先使用 Interception 驱动，不可用时降级到 IbInputSimulator（SendInput 模式）
"""
import time

_ib_simulator = None


def _get_ib():
    global _ib_simulator
    if _ib_simulator is None:
        from ib_simulator import IbSimulator
        _ib_simulator = IbSimulator(driver="SendInput")
        _ib_simulator.start()
    return _ib_simulator


def is_available():
    """检查是否有可用的键盘驱动（IbSimulator 始终可用）"""
    try:
        import interception_keyboard
        if interception_keyboard.is_available():
            return True
    except Exception:
        pass
    return True  # IbSimulator SendInput 模式不需要额外驱动


def get_backend():
    """返回当前使用的后端名称"""
    try:
        import interception_keyboard
        if interception_keyboard.is_available():
            return "Interception"
    except Exception:
        pass
    return "IbInputSimulator(SendInput)"


def send_string(text, interval=0.02):
    """发送字符串，优先用 Interception，不可用时降级到 IbSimulator"""
    try:
        import interception_keyboard
        if interception_keyboard.is_available():
            return interception_keyboard.send_string(text, interval=interval)
    except Exception:
        pass

    # 降级：IbSimulator 逐字符发送（带间隔）
    ib = _get_ib()
    for ch in text:
        ib.send_text(ch)
        time.sleep(interval)
    return True


def press_key(name, interval=0.05):
    """按一个按键（如 esc/enter/tab/f5 等），优先 Interception 驱动级发送，不可用时降级 pyautogui"""
    try:
        import interception_keyboard
        if interception_keyboard.is_available():
            if interception_keyboard.press_key(name, interval=interval):
                return True
    except Exception:
        pass

    # 降级：pyautogui 发送
    try:
        import pyautogui
        pyautogui.press(name)
        return True
    except Exception:
        return False
