"""
驱动级键盘输入模块
使用 Interception 驱动实现驱动级模拟键盘输入
程序必须基于 Interception 运行，不支持 PyDirectInput 回退
"""
import time

# Windows 虚拟键码
VK_DELETE = 0x2E
VK_RETURN = 0x0D
VK_BACK = 0x08
VK_TAB = 0x09
VK_SPACE = 0x20
VK_ESCAPE = 0x1B


def is_available():
    """检查 Interception 驱动是否可用"""
    import interception_keyboard
    return interception_keyboard.is_available()


def get_backend():
    """当前使用的后端名称"""
    return "Interception"


def send_string(hwnd, text):
    """发送字符串到指定窗口（通过 Interception 扫描码方式）"""
    import interception_keyboard
    return interception_keyboard.send_string(text, interval=0.02)


def key_press(vk_code):
    """按下并释放一个键"""
    import interception_keyboard
    char = _vk_to_char(vk_code)
    if char:
        return interception_keyboard.send_key(char)
    return False


def key_down(vk_code):
    """按住一个键"""
    import interception_keyboard
    char = _vk_to_char(vk_code)
    if char:
        return interception_keyboard.send_key(char, interval=0)
    return False


def key_up(vk_code):
    """释放一个键"""
    # Interception 的 send_key 已经包含 key_down + key_up
    return True


def hold_key(vk_code, duration=2.0):
    """长按一个键指定秒数"""
    import interception_keyboard
    char = _vk_to_char(vk_code)
    if char:
        return interception_keyboard.send_key(char, interval=duration)
    return False


def _vk_to_char(vk_code):
    """将 VK 码转换为字符"""
    mapping = {
        0x2E: '\x7f',   # delete
        0x0D: '\n',     # enter
        0x08: '\x08',   # backspace
        0x09: '\t',     # tab
        0x20: ' ',      # space
        0x1B: '\x1b',   # escape
    }
    return mapping.get(vk_code)
