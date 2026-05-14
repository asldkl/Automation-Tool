"""
设置窗口模块
提供 WeGame 路径、三角洲路径、置信度、开机自启动等全局设置，
以及定时执行、运行模式等自动任务设置
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import re
import winreg
import config


class SettingsWindow:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("设置")
        self.win.geometry("660x720")
        self.win.resizable(False, False)
        # 窗口居中
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - 660) // 2
        y = (self.win.winfo_screenheight() - 720) // 2
        self.win.geometry(f"660x720+{x}+{y}")
        self.win.transient(parent)
        self.win.grab_set()
        # 设置窗口图标
        try:
            icon_path = config.resource_path("picture/icon.ico")
            if os.path.exists(icon_path):
                self.win.iconbitmap(icon_path)
        except Exception:
            pass

        # 全局设置变量
        self.wegame_var = tk.StringVar(value=app.settings.get("wegame_path", ""))
        self.delta_var = tk.StringVar(value=app.settings.get("delta_path", ""))
        self.confidence_var = tk.DoubleVar(value=float(app.settings.get("confidence", 0.7)))
        self.log_var = tk.StringVar(value=app.settings.get("log_save_path", ""))
        self.autostart_var = tk.BooleanVar(value=self._get_autostart_state())

        # 自动任务设置变量
        self.auto_enable_var = tk.BooleanVar(value=app.settings.get("auto_start", False))
        self.run_mode_var = tk.StringVar(value=app.settings.get("run_mode", "单次"))
        self.silent_var = tk.BooleanVar(value=app.settings.get("silent_mode", False))

        # 操作选择变量
        selected = app.settings.get("selected_operations", [])
        self.op_tech = tk.BooleanVar(value="tech_center" in selected)
        self.op_bench = tk.BooleanVar(value="tool_bench" in selected)
        self.op_armor = tk.BooleanVar(value="armor_station" in selected)
        self.op_pharmacy = tk.BooleanVar(value="pharmacy_station" in selected)

        # 运行提醒变量
        self.reminder_enable_var = tk.BooleanVar(value=app.settings.get("reminder_enabled", False))
        self.reminder_minutes_var = tk.IntVar(value=app.settings.get("reminder_minutes", 5))

        # QQ 路径 + 登录开关
        self.qq_path_var = tk.StringVar(value=app.settings.get("qq_path", ""))
        self.qq_login_var = tk.BooleanVar(value=app.settings.get("qq_login_enabled", False))

        # 电源管理变量
        self.wake_var = tk.BooleanVar(value=app.settings.get("wake_enabled", True))
        self.shutdown_enable_var = tk.BooleanVar(value=app.settings.get("auto_shutdown_enabled", False))
        self.shutdown_time_var = tk.StringVar(value=app.settings.get("auto_shutdown_time", "22:00"))
        self.startup_enable_var = tk.BooleanVar(value=app.settings.get("auto_startup_enabled", False))
        self.startup_time_var = tk.StringVar(value=app.settings.get("auto_startup_time", "07:00"))

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self):
        style = ttk.Style()
        style.configure('Settings.TFrame', background='#f0f2f5')
        style.configure('SettingsCard.TLabelframe', background='#ffffff', foreground='#2c3e50',
                        bordercolor='#dcdde1', lightcolor='#dcdde1', darkcolor='#dcdde1',
                        relief='solid', borderwidth=1)
        style.configure('SettingsCard.TLabelframe.Label', background='#ffffff', foreground='#2c3e50',
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.configure('SettingsInner.TFrame', background='#ffffff')
        style.configure('Settings.TLabel', background='#ffffff', foreground='#2c3e50',
                        font=('Microsoft YaHei UI', 9))
        style.configure('SettingsSmall.TLabel', background='#ffffff', foreground='#7f8c8d',
                        font=('Microsoft YaHei UI', 8))

    def _build_ui(self):
        # 主容器
        main_frame = ttk.Frame(self.win, style='Settings.TFrame', padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 选项卡
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        # ----- Tab 1: 全局设置 -----
        global_tab = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(global_tab, text="  全局设置  ")
        self._build_global_tab(global_tab)

        # ----- Tab 2: 自动任务设置 -----
        auto_tab = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(auto_tab, text="  自动任务设置  ")
        self._build_auto_tab(auto_tab)

        # ----- Tab 3: 电源管理 -----
        power_tab = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(power_tab, text="  电源管理  ")
        self._build_power_tab(power_tab)

        # ----- 底部操作按钮 -----
        btn_frame = ttk.Frame(main_frame, style='Settings.TFrame')
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="✓ 保存设置", style='Success.TButton',
                   command=self._save, width=14).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="✕ 取消", style='TButton',
                   command=self.win.destroy, width=10).pack(side=tk.LEFT)

    def _build_global_tab(self, parent):
        """全局设置选项卡内容"""
        # ----- WeGame 路径 -----
        frame1 = ttk.LabelFrame(parent, text="  WeGame 路径  ", style='SettingsCard.TLabelframe', padding=8)
        frame1.pack(fill=tk.X, pady=(0, 8))

        f1 = ttk.Frame(frame1, style='SettingsInner.TFrame')
        f1.pack(fill=tk.X)
        ttk.Label(f1, text="WeGame.exe：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        wegame_entry = ttk.Entry(f1, textvariable=self.wegame_var, width=45)
        wegame_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        ttk.Button(f1, text="浏览", command=self._browse_wegame, width=24).pack(side=tk.LEFT)

        # ----- 三角洲路径 -----
        frame2 = ttk.LabelFrame(parent, text="  三角洲路径（可选）  ", style='SettingsCard.TLabelframe', padding=8)
        frame2.pack(fill=tk.X, pady=(0, 8))

        f2 = ttk.Frame(frame2, style='SettingsInner.TFrame')
        f2.pack(fill=tk.X)
        ttk.Label(f2, text="启动程序：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        delta_entry = ttk.Entry(f2, textvariable=self.delta_var, width=45)
        delta_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        ttk.Button(f2, text="浏览", command=self._browse_delta, width=24).pack(side=tk.LEFT)

        # ----- QQ 路径 -----
        frame_qq = ttk.LabelFrame(parent, text="  QQ 路径（自动登录用）  ", style='SettingsCard.TLabelframe', padding=8)
        frame_qq.pack(fill=tk.X, pady=(0, 8))

        f_qq = ttk.Frame(frame_qq, style='SettingsInner.TFrame')
        f_qq.pack(fill=tk.X)
        ttk.Label(f_qq, text="QQ.exe：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        qq_entry = ttk.Entry(f_qq, textvariable=self.qq_path_var, width=45)
        qq_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        ttk.Button(f_qq, text="浏览", command=self._browse_qq, width=24).pack(side=tk.LEFT)

        # ----- 图像识别置信度 -----
        frame3 = ttk.LabelFrame(parent, text="  图像识别设置  ", style='SettingsCard.TLabelframe', padding=12)
        frame3.pack(fill=tk.X, pady=(0, 8))

        f3 = ttk.Frame(frame3, style='SettingsInner.TFrame')
        f3.pack(fill=tk.X)
        ttk.Label(f3, text="匹配置信度：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))

        scale = ttk.Scale(f3, from_=0.5, to=0.95, variable=self.confidence_var,
                          length=200, orient=tk.HORIZONTAL)
        scale.pack(side=tk.LEFT, padx=(0, 8))

        # 置信度数值显示（带百分号）
        self.conf_label = ttk.Label(f3, textvariable=self.confidence_var, style='SettingsSmall.TLabel', width=4)
        self.conf_label.pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(f3, text="(0.50 - 0.95)", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 8))

        # 显示实时值
        self.conf_value_label = ttk.Label(f3, style='Settings.TLabel', width=16)
        self.conf_value_label.pack(side=tk.LEFT)
        self._update_conf_display()

        def on_scale_change(*args):
            self._update_conf_display()
        self.confidence_var.trace_add('write', on_scale_change)

        # ----- 日志保存目录 -----
        frame4 = ttk.LabelFrame(parent, text="  日志保存目录  ", style='SettingsCard.TLabelframe', padding=8)
        frame4.pack(fill=tk.X, pady=(0, 8))

        f4 = ttk.Frame(frame4, style='SettingsInner.TFrame')
        f4.pack(fill=tk.X)
        ttk.Label(f4, text="保存路径：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        log_entry = ttk.Entry(f4, textvariable=self.log_var, width=45)
        log_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        ttk.Button(f4, text="浏览", command=self._browse_log, width=24).pack(side=tk.LEFT)

        # ----- 开机自启动 -----
        frame5 = ttk.LabelFrame(parent, text="  其他设置  ", style='SettingsCard.TLabelframe', padding=12)
        frame5.pack(fill=tk.X, pady=(0, 0))

        f5 = ttk.Frame(frame5, style='SettingsInner.TFrame')
        f5.pack(fill=tk.X)
        ttk.Checkbutton(f5, text="开机自启动（登录 Windows 时自动运行）",
                       variable=self.autostart_var).pack(side=tk.LEFT, padx=5, pady=5)

    def _build_auto_tab(self, parent):
        """自动任务设置选项卡内容"""
        # 第1行：启用 + 模式 + 静默
        row1 = ttk.Frame(parent, style='SettingsInner.TFrame')
        row1.pack(fill=tk.X, pady=(0, 12))

        ttk.Checkbutton(row1, text="启用定时执行",
                        variable=self.auto_enable_var).pack(side=tk.LEFT, padx=(0, 18))

        ttk.Label(row1, text="运行模式：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        mode_combo = ttk.Combobox(row1, textvariable=self.run_mode_var,
                                  values=["每日循环", "单次"],
                                  state="readonly", width=10)
        mode_combo.pack(side=tk.LEFT, padx=(0, 18))

        ttk.Checkbutton(row1, text="静默运行（托盘）",
                       variable=self.silent_var).pack(side=tk.LEFT)

        # 第2行：时间点管理
        row2 = ttk.Frame(parent, style='SettingsInner.TFrame')
        row2.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(row2, text="执行时间点（HH:MM）：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        self.time_var = tk.StringVar()
        time_entry = ttk.Entry(row2, textvariable=self.time_var, width=8)
        time_entry.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row2, text="添加", style='TButton', command=self._add_time, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="删除选中", style='TButton', command=self._delete_time, width=8).pack(side=tk.LEFT, padx=4)

        # 时间列表
        time_list_frame = ttk.Frame(parent, style='SettingsInner.TFrame')
        time_list_frame.pack(fill=tk.X, pady=(0, 12))
        scrollbar = ttk.Scrollbar(time_list_frame, orient=tk.VERTICAL)
        self.time_listbox = tk.Listbox(time_list_frame, height=4,
                                       yscrollcommand=scrollbar.set,
                                       selectmode=tk.SINGLE,
                                       font=('Microsoft YaHei UI', 9),
                                       bg='#fafbfc', fg='#2c3e50',
                                       selectbackground='#3498db',
                                       selectforeground='#ffffff',
                                       relief='flat', highlightthickness=1,
                                       highlightcolor='#dcdde1', borderwidth=0)
        scrollbar.config(command=self.time_listbox.yview)
        self.time_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

        # 填充已有时间
        times = self.app.settings.get("schedule_times", [])
        if not times and self.app.settings.get("start_time"):
            times = [self.app.settings["start_time"]]
        for t in times:
            self.time_listbox.insert(tk.END, t)

        # ----- 执行操作选择 -----
        ops_frame = ttk.LabelFrame(parent, text="  执行操作（可多选）  ", style='SettingsCard.TLabelframe', padding=10)
        ops_frame.pack(fill=tk.X, pady=(0, 0))

        ops_inner = ttk.Frame(ops_frame, style='SettingsInner.TFrame')
        ops_inner.pack(fill=tk.X)
        ttk.Checkbutton(ops_inner, text="技术中心", variable=self.op_tech).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(ops_inner, text="工作台", variable=self.op_bench).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(ops_inner, text="防具台", variable=self.op_armor).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(ops_inner, text="制药台", variable=self.op_pharmacy).pack(side=tk.LEFT)

        # ----- 运行提醒 -----
        reminder_frame = ttk.LabelFrame(parent, text="  运行提醒  ", style='SettingsCard.TLabelframe', padding=10)
        reminder_frame.pack(fill=tk.X, pady=(8, 0))

        reminder_inner = ttk.Frame(reminder_frame, style='SettingsInner.TFrame')
        reminder_inner.pack(fill=tk.X)
        ttk.Checkbutton(reminder_inner, text="启用运行前提醒弹窗",
                       variable=self.reminder_enable_var).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(reminder_inner, text="提前", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        reminder_combo = ttk.Combobox(reminder_inner, textvariable=self.reminder_minutes_var,
                                      values=[1, 2, 3, 5, 10, 15],
                                      state="readonly", width=5)
        reminder_combo.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(reminder_inner, text="分钟弹出提示", style='Settings.TLabel').pack(side=tk.LEFT)

        # ----- QQ 自动登录（账号管理） -----
        qq_frame = ttk.LabelFrame(parent, text="  QQ 自动登录  ", style='SettingsCard.TLabelframe', padding=12)
        qq_frame.pack(fill=tk.X, pady=(8, 0))

        qq_inner1 = ttk.Frame(qq_frame, style='SettingsInner.TFrame')
        qq_inner1.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(qq_inner1, text="开机时自动登录QQ（程序启动后自动登录所有已添加账号）",
                       variable=self.qq_login_var).pack(anchor=tk.W, padx=5, pady=2)

        # QQ 账号管理
        qq_btn_frame = ttk.Frame(qq_frame, style='SettingsInner.TFrame')
        qq_btn_frame.pack(fill=tk.X, pady=(4, 6))
        ttk.Button(qq_btn_frame, text="＋ 添加QQ账号",
                  command=self._add_qq_account, width=16).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(qq_btn_frame, text="－ 删除选中",
                  command=self._delete_qq_account, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(qq_btn_frame, text="× 清空列表",
                  command=self._clear_qq_accounts, width=10).pack(side=tk.LEFT, padx=4)

        # QQ 列表
        qq_list_frame = ttk.Frame(qq_frame, style='SettingsInner.TFrame')
        qq_list_frame.pack(fill=tk.X)
        qq_scrollbar = ttk.Scrollbar(qq_list_frame, orient=tk.VERTICAL)
        self.qq_listbox = tk.Listbox(qq_list_frame, height=3,
                                     yscrollcommand=qq_scrollbar.set,
                                     selectmode=tk.SINGLE,
                                     font=('Microsoft YaHei UI', 9),
                                     bg='#fafbfc', fg='#2c3e50',
                                     selectbackground='#3498db',
                                     selectforeground='#ffffff',
                                     relief='flat', highlightthickness=1,
                                     highlightcolor='#dcdde1', borderwidth=0)
        qq_scrollbar.config(command=self.qq_listbox.yview)
        self.qq_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        qq_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

        # 填充已有 QQ 账号
        for p in self.app.qq_account_images:
            self.qq_listbox.insert(tk.END, os.path.basename(p))

    def _build_power_tab(self, parent):
        """电源管理选项卡"""
        # ----- 唤醒设置 -----
        frame1 = ttk.LabelFrame(parent, text="  唤醒设置  ", style='SettingsCard.TLabelframe', padding=12)
        frame1.pack(fill=tk.X, pady=(0, 8))

        f1 = ttk.Frame(frame1, style='SettingsInner.TFrame')
        f1.pack(fill=tk.X)
        ttk.Checkbutton(f1, text="运行前5分钟唤醒电脑（防止休眠 / 睡眠状态）",
                       variable=self.wake_var).pack(side=tk.LEFT, padx=5, pady=5)
        note1 = ttk.Frame(frame1, style='SettingsInner.TFrame')
        note1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(note1, text="电脑挂机休眠时可自动唤醒，确保定时任务正常执行",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5)

        # ----- 自动关机 -----
        frame2 = ttk.LabelFrame(parent, text="  自动关机  ", style='SettingsCard.TLabelframe', padding=12)
        frame2.pack(fill=tk.X, pady=(0, 8))

        f2 = ttk.Frame(frame2, style='SettingsInner.TFrame')
        f2.pack(fill=tk.X)
        ttk.Checkbutton(f2, text="启用自动关机",
                       variable=self.shutdown_enable_var).pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(f2, text="关机时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        shutdown_entry = ttk.Entry(f2, textvariable=self.shutdown_time_var, width=8)
        shutdown_entry.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f2, text="(HH:MM)", style='SettingsSmall.TLabel').pack(side=tk.LEFT)
        # 说明文字另起一行
        note2 = ttk.Frame(frame2, style='SettingsInner.TFrame')
        note2.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(note2, text="到达设定时间后系统将自动关机（任务运行中会等待完成后执行）",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5)

        # ----- 自动开机（唤醒） -----
        frame3 = ttk.LabelFrame(parent, text="  定时开机（从睡眠/休眠唤醒）  ", style='SettingsCard.TLabelframe', padding=12)
        frame3.pack(fill=tk.X, pady=(0, 8))

        f3 = ttk.Frame(frame3, style='SettingsInner.TFrame')
        f3.pack(fill=tk.X)
        ttk.Checkbutton(f3, text="启用定时开机唤醒",
                       variable=self.startup_enable_var).pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(f3, text="开机时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        startup_entry = ttk.Entry(f3, textvariable=self.startup_time_var, width=8)
        startup_entry.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f3, text="(HH:MM)", style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        note_frame = ttk.Frame(parent, style='SettingsInner.TFrame')
        note_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(note_frame,
                 text="💡 定时开机功能可在电脑处于睡眠/休眠状态时将其唤醒。\n    若电脑为完全关机状态，需主板支持 RTC 唤醒并在 BIOS 中启用【定时开机】或「RTC Alarm」功能。",
                 style='SettingsSmall.TLabel', wraplength=580, justify=tk.LEFT).pack(padx=5, pady=5)

    def _add_time(self):
        raw = self.time_var.get().strip()
        if re.match(r'^\d{1,2}:\d{2}$', raw):
            h, m = map(int, raw.split(":"))
            if h < 0 or h > 23 or m < 0 or m > 59:
                messagebox.showwarning("格式错误", "时间超出范围，请输入 00:00 ~ 23:59")
                return
            normalized = f"{h:02d}:{m:02d}"
            self.time_listbox.insert(tk.END, normalized)
            self.time_var.set("")
        else:
            messagebox.showwarning("格式错误", "请输入 HH:MM 格式的时间，例如 08:30")

    def _delete_time(self):
        sel = self.time_listbox.curselection()
        if sel:
            self.time_listbox.delete(sel[0])

    def _update_conf_display(self):
        val = self.confidence_var.get()
        percent = int(val * 100)
        self.conf_value_label.config(text=f"当前值：{percent}%")

    def _browse_wegame(self):
        path = filedialog.askopenfilename(title="选择 WeGame.exe", filetypes=[("可执行文件", "*.exe")])
        if path:
            self.wegame_var.set(path)

    def _browse_delta(self):
        path = filedialog.askopenfilename(title="选择三角洲行动启动程序", filetypes=[("可执行文件", "*.exe")])
        if path:
            self.delta_var.set(path)

    def _browse_qq(self):
        path = filedialog.askopenfilename(title="选择 QQ.exe", filetypes=[("可执行文件", "*.exe")])
        if path:
            self.qq_path_var.set(path)

    def _browse_log(self):
        path = filedialog.askdirectory(title="选择日志保存目录")
        if path:
            self.log_var.set(path)

    # ---------- QQ 账号管理 ----------
    def _add_qq_account(self):
        file_path = filedialog.askopenfilename(
            title="选择 QQ 号截图",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")]
        )
        if file_path:
            self.app.qq_account_images.append(file_path)
            self.qq_listbox.insert(tk.END, os.path.basename(file_path))
            self.app.save_accounts()

    def _delete_qq_account(self):
        sel = self.qq_listbox.curselection()
        if sel:
            idx = sel[0]
            self.qq_listbox.delete(idx)
            del self.app.qq_account_images[idx]
            self.app.save_accounts()

    def _clear_qq_accounts(self):
        self.qq_listbox.delete(0, tk.END)
        self.app.qq_account_images.clear()
        self.app.save_accounts()

    def _get_autostart_state(self):
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
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, 'frozen', False):
                exe_path = sys.executable
                # 添加 --auto-start 参数以区分开机自启动与双击启动
                winreg.SetValueEx(key, "DeltaAutoTool", 0, winreg.REG_SZ, f'"{exe_path}" --auto-start')
            else:
                python_exe = sys.executable
                script_path = os.path.abspath(sys.argv[0])
                winreg.SetValueEx(key, "DeltaAutoTool", 0, winreg.REG_SZ,
                                  f'"{python_exe}" "{script_path}" --auto-start')
        else:
            try:
                winreg.DeleteValue(key, "DeltaAutoTool")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)

    def _save(self):
        # 全局设置
        self.app.settings["wegame_path"] = self.wegame_var.get()
        self.app.settings["delta_path"] = self.delta_var.get()
        self.app.settings["confidence"] = round(self.confidence_var.get(), 2)
        self.app.settings["log_save_path"] = self.log_var.get()
        self._set_autostart(self.autostart_var.get())

        # 自动任务设置
        self.app.settings["auto_start"] = self.auto_enable_var.get()
        self.app.settings["run_mode"] = self.run_mode_var.get()
        self.app.settings["silent_mode"] = self.silent_var.get()
        times = [self.time_listbox.get(i) for i in range(self.time_listbox.size())]
        # 标准化时间格式（补零）
        normalized_times = []
        for t in times:
            try:
                h, m = map(int, t.split(":"))
                normalized_times.append(f"{h:02d}:{m:02d}")
            except Exception:
                continue
        self.app.settings["schedule_times"] = normalized_times
        if normalized_times:
            self.app.settings["start_time"] = normalized_times[0]

        # 执行操作
        ops = []
        if self.op_tech.get(): ops.append("tech_center")
        if self.op_bench.get(): ops.append("tool_bench")
        if self.op_armor.get(): ops.append("armor_station")
        if self.op_pharmacy.get(): ops.append("pharmacy_station")
        self.app.settings["selected_operations"] = ops

        # 运行提醒
        self.app.settings["reminder_enabled"] = self.reminder_enable_var.get()
        self.app.settings["reminder_minutes"] = self.reminder_minutes_var.get()

        # 电源管理
        self.app.settings["wake_enabled"] = self.wake_var.get()
        self.app.settings["auto_shutdown_enabled"] = self.shutdown_enable_var.get()
        self.app.settings["auto_shutdown_time"] = self.shutdown_time_var.get()
        self.app.settings["auto_startup_enabled"] = self.startup_enable_var.get()
        self.app.settings["auto_startup_time"] = self.startup_time_var.get()

        # QQ 设置
        self.app.settings["qq_path"] = self.qq_path_var.get()
        self.app.settings["qq_login_enabled"] = self.qq_login_var.get()

        config.APP_SETTINGS.update(self.app.settings)
        config.save_settings(config.APP_SETTINGS)
        config.WEGAME_PATH = config.APP_SETTINGS.get("wegame_path", "")
        config.CONFIDENCE = config.APP_SETTINGS["confidence"]
        self.app.update_confidence_display()

        # 应用定时设置
        self.app.apply_auto_settings_from_window()

        # 更新定时开机任务
        if self.startup_enable_var.get():
            import utils
            utils.schedule_startup_task(self.startup_time_var.get())
        else:
            import utils
            utils.remove_startup_task()

        messagebox.showinfo("提示", "设置已保存。")
        self.win.destroy()
