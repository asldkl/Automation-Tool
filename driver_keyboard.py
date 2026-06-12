"""
驱动级键盘输入模块
使用 PyDirectInput 实现驱动级模拟键盘输入
当 PyDirectInput 不可用时回退到 pyautogui
"""
import time

_pydirectinput = None
_pydirectinput_available = None

# Windows 虚拟键码
VK_DELETE = 0x2E
VK_RETURN = 0x0D
VK_BACK = 0x08
VK_TAB = 0x09
VK_SPACE = 0x20
VK_ESCAPE = 0x1B


def _init():
    """初始化 PyDirectInput，返回是否可用"""
    global _pydirectinput, _pydirectinput_available
    if _pydirectinput_available is not None:
        return _pydirectinput_available
    try:
        import pydirectinput
        pydirectinput.FAILSAFE = False
        _pydirectinput = pydirectinput
        _pydirectinput_available = True
        print("[OK] PyDirectInput 驱动级键盘已加载")
        return True
    except Exception as e:
        _pydirectinput_available = False
        print(f"[WARN] PyDirectInput 加载失败: {e}，回退到 pyautogui")
        return False


def is_available():
    """检查驱动级键盘是否可用"""
    return _init()


def get_backend():
    """当前使用的后端名称"""
    if _init():
        return "PyDirectInput"
    return "pyautogui"


def send_string(hwnd, text):
    """发送字符串到指定窗口（通过剪贴板粘贴）"""
    try:
        import pyperclip
        pyperclip.copy(text)
        if _init():
            _pydirectinput.keyDown('ctrl')
            _pydirectinput.press('v')
            _pydirectinput.keyUp('ctrl')
        else:
            import pyautogui
            pyautogui.hotkey('ctrl', 'v')
        return True
    except Exception as e:
        print(f"[WARN] 发送字符串失败: {e}")
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.02)
            return True
        except Exception:
            return False


def key_press(vk_code):
    """按下并释放一个键"""
    if _init():
        try:
            _pydirectinput.press(_vk_to_name(vk_code))
            return True
        except Exception:
            return False
    else:
        import pyautogui
        pyautogui.press(_vk_to_name(vk_code))
        return True


def key_down(vk_code):
    """按住一个键"""
    if _init():
        try:
            _pydirectinput.keyDown(_vk_to_name(vk_code))
            return True
        except Exception:
            return False
    else:
        import pyautogui
        pyautogui.keyDown(_vk_to_name(vk_code))
        return True


def key_up(vk_code):
    """释放一个键"""
    if _init():
        try:
            _pydirectinput.keyUp(_vk_to_name(vk_code))
            return True
        except Exception:
            return False
    else:
        import pyautogui
        pyautogui.keyUp(_vk_to_name(vk_code))
        return True


def hold_key(vk_code, duration=2.0):
    """长按一个键指定秒数"""
    key_down(vk_code)
    time.sleep(duration)
    key_up(vk_code)


def _vk_to_name(vk_code):
    """将 VK 码转换为按键名称"""
    mapping = {
        0x2E: 'delete',
        0x0D: 'enter',
        0x08: 'backspace',
        0x09: 'tab',
        0x20: 'space',
        0x1B: 'escape',
    }
    return mapping.get(vk_code, str(vk_code))
