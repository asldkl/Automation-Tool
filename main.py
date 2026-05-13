"""
主入口文件
启动 Tkinter 应用程序
"""
import sys
import os
import traceback

try:
    from gui_app import main
    main()
except Exception:
    error_log = os.path.join(os.path.expanduser("~"), ".delta_auto_error.log")
    with open(error_log, "w", encoding="utf-8") as f:
        traceback.print_exc(file=f)
    sys.exit(1)
