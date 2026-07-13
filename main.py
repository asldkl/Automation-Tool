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
            # 1. 优先使用命名事件通知已有实例显示窗口（避免 ShowWindow 损坏 tkinter 窗口几何）
            try:
                import win32event
                event = win32event.OpenEvent(win32event.EVENT_MODIFY_STATE, False,
                                             "Global\\DeltaAutoTool_ShowApp")
                if event:
                    win32event.SetEvent(event)
                    win32event.CloseHandle(event)
            except Exception:
                pass
            # 2. 查找已有窗口
            hwnd = win32gui.FindWindow(None, "三角洲行动自动化工具")
            if hwnd:
                # 最小化状态 → 通过 WM_SYSCOMMAND/SC_RESTORE 恢复（tkinter 自身处理，安全）将修改上传到git
                if win32gui.IsIconic(hwnd):
                    win32gui.SendMessage(hwnd, win32con.WM_SYSCOMMAND, win32con.SC_RESTORE, 0)
                # 隐藏状态（托盘 withdraw）→ 不调用 ShowWindow，靠事件通知实例自行 deiconify
                # 可见但非前台 → 直接置前
                if win32gui.IsWindowVisible(hwnd):
                    win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    ensure_single_instance()

    try:
        # 初始化数据目录并迁移旧数据
        import config
        config.ensure_app_data_dir()
        config.migrate_old_data()

        from gui_app import main
        main()
    except Exception:
        error_log = os.path.join(config.APP_DATA_DIR, "error.log")
        with open(error_log, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        sys.exit(1)
