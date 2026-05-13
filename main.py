"""
主入口文件
启动 Tkinter 应用程序
"""
import sys
import os
import traceback
import ctypes


def ensure_single_instance():
    """
    确保只运行一个程序实例。
    使用 Windows 命名互斥体检测重复启动，重复时激活已有窗口并退出。
    """
    mutex_name = "Global\\DeltaAutoTool_SingleInstance"
    ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        try:
            import win32gui
            import win32con
            hwnd = win32gui.FindWindow(None, "三角洲行动自动化工具")
            if hwnd:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    ensure_single_instance()

    try:
        from gui_app import main
        main()
    except Exception:
        error_log = os.path.join(os.path.expanduser("~"), ".delta_auto_error.log")
        with open(error_log, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        sys.exit(1)
