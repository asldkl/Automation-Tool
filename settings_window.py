"""
设置窗口模块
提供 WeGame 路径、三角洲路径、置信度、日志保存路径、开机自启动的配置界面
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import winreg
import config

class SettingsWindow:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.settings = config.APP_SETTINGS.copy()
        self.win = tk.Toplevel(parent)
        self.win.title("全局设置")
        self.win.geometry("560x420")
        self.win.resizable(False, False)
        self._build_ui()

    def _build_ui(self):
        main_frame = ttk.Frame(self.win, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # WeGame 路径
        ttk.Label(main_frame, text="WeGame 路径：").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.wegame_var = tk.StringVar(value=self.settings.get("wegame_path", ""))
        ttk.Entry(main_frame, textvariable=self.wegame_var, width=45).grid(row=0, column=1, padx=5)
        ttk.Button(main_frame, text="浏览...", command=self._browse_wegame).grid(row=0, column=2)

        # 三角洲游戏路径
        ttk.Label(main_frame, text="三角洲路径（可选）：").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.delta_var = tk.StringVar(value=self.settings.get("delta_path", ""))
        ttk.Entry(main_frame, textvariable=self.delta_var, width=45).grid(row=1, column=1, padx=5)
        ttk.Button(main_frame, text="浏览...", command=self._browse_delta).grid(row=1, column=2)

        # 置信度
        ttk.Label(main_frame, text="图像识别置信度：").grid(row=2, column=0, sticky=tk.W, pady=10)
        self.confidence_var = tk.DoubleVar(value=float(self.settings.get("confidence", 0.7)))
        scale = ttk.Scale(main_frame, from_=0.5, to=0.95, variable=self.confidence_var, length=200, orient=tk.HORIZONTAL)
        scale.grid(row=2, column=1, sticky=tk.W, padx=5)
        lbl_val = ttk.Label(main_frame, textvariable=self.confidence_var)
        lbl_val.grid(row=2, column=2, sticky=tk.W)

        # 日志保存路径
        ttk.Label(main_frame, text="日志保存目录：").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.log_var = tk.StringVar(value=self.settings.get("log_save_path", ""))
        ttk.Entry(main_frame, textvariable=self.log_var, width=45).grid(row=3, column=1, padx=5)
        ttk.Button(main_frame, text="浏览...", command=self._browse_log).grid(row=3, column=2)

        # 开机自启动
        self.autostart_var = tk.BooleanVar(value=self._get_autostart_state())
        ttk.Checkbutton(main_frame, text="开机自启动", variable=self.autostart_var).grid(row=4, column=0, columnspan=3, sticky=tk.W, padx=5, pady=5)

        # 按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=20)
        ttk.Button(btn_frame, text="保存", command=self._save).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", command=self.win.destroy).pack(side=tk.LEFT)

    def _browse_wegame(self):
        path = filedialog.askopenfilename(title="选择 WeGame.exe", filetypes=[("可执行文件", "*.exe")])
        if path:
            self.wegame_var.set(path)

    def _browse_delta(self):
        path = filedialog.askopenfilename(title="选择三角洲行动启动程序", filetypes=[("可执行文件", "*.exe")])
        if path:
            self.delta_var.set(path)

    def _browse_log(self):
        path = filedialog.askdirectory(title="选择日志保存目录")
        if path:
            self.log_var.set(path)

    def _get_autostart_state(self):
        """检查注册表是否已有开机自启动项"""
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "DeltaAutoTool")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            return False

    def _set_autostart(self, enable):
        """设置或取消开机自启动"""
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            # 获取当前 EXE 或脚本路径
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
            else:
                exe_path = sys.argv[0]
            winreg.SetValueEx(key, "DeltaAutoTool", 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, "DeltaAutoTool")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)

    def _save(self):
        self.settings["wegame_path"] = self.wegame_var.get()
        self.settings["delta_path"] = self.delta_var.get()
        self.settings["confidence"] = round(self.confidence_var.get(), 2)
        self.settings["log_save_path"] = self.log_var.get()
        # 保存开机自启动
        self._set_autostart(self.autostart_var.get())
        # 写回全局配置
        config.APP_SETTINGS.update(self.settings)
        config.save_settings(config.APP_SETTINGS)
        # 更新主界面使用的全局变量
        config.WEGAME_PATH = config.APP_SETTINGS.get("wegame_path", "")
        config.CONFIDENCE = config.APP_SETTINGS["confidence"]
        self.app.update_confidence_display()
        messagebox.showinfo("提示", "设置已保存，部分设置将在下次启动时生效。")
        self.win.destroy()