"""
驱动级键盘输入模块
使用 Interception 驱动实现驱动级模拟键盘输入
程序必须基于 Interception 运行
"""


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
