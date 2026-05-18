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
from PIL import Image, ImageTk


class SettingsWindow:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("设置")
        self.win.geometry("660x780")
        self.win.resizable(False, False)
        # 窗口居中
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - 660) // 2
        y = (self.win.winfo_screenheight() - 780) // 2
        self.win.geometry(f"660x780+{x}+{y}")
        self.win.transient(parent)
        self.win.grab_set()
        # 设置窗口图标
        try:
            icon_path = config.resource_path("picture/icon.ico")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self.win.iconphoto(False, self._icon_photo)
        except Exception:
            pass

        # 全局设置变量
        self.wegame_var = tk.StringVar(value=app.settings.get("wegame_path", ""))
        self.delta_var = tk.StringVar(value=app.settings.get("delta_path", ""))
        self.confidence_var = tk.DoubleVar(value=float(app.settings.get("confidence", 0.7)))
        self.log_var = tk.StringVar(value=app.settings.get("log_save_path", ""))
        self.autostart_var = tk.BooleanVar(value=self._get_autostart_state())
        self.run_on_startup_var = tk.BooleanVar(value=app.settings.get("run_on_startup", False))

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

        # QQ 路径
        self.qq_path_var = tk.StringVar(value=app.settings.get("qq_path", ""))

        # 邮件通知变量
        self.email_enable_var = tk.BooleanVar(value=app.settings.get("email_enabled", False))
        self.smtp_code_var = tk.StringVar(value=app.settings.get("smtp_code", ""))
        self.sender_email_var = tk.StringVar(value=app.settings.get("sender_email", ""))
        self.receiver_email_var = tk.StringVar(value=app.settings.get("receiver_email", ""))

        # 账号列表滚动查找变量
        self.qq_mouse_move_distance_var = tk.IntVar(value=app.settings.get("qq_mouse_move_distance", 100))
        self.scroll_amount_var = tk.IntVar(value=app.settings.get("scroll_amount", 100))
        self.game_launch_wait_var = tk.IntVar(value=app.settings.get("game_launch_wait", 0))

        # 一键出售变量
        self.enable_sell_var = tk.BooleanVar(value=app.settings.get("enable_sell_after_run", False))
        self.sell_discount_var = tk.IntVar(value=app.settings.get("sell_discount_times", 0))
        self.sell_confidence_var = tk.DoubleVar(value=float(app.settings.get("sell_confidence", 0.55)))

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

        # ----- Tab 4: 邮件通知 -----
        email_tab = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(email_tab, text="  邮件通知  ")
        self._build_email_tab(email_tab)

        # ----- Tab 5: 其他设置 -----
        other_tab = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(other_tab, text="  其他设置  ")
        self._build_other_tab(other_tab)

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
        frame_qq = ttk.LabelFrame(parent, text="  QQ 路径  ", style='SettingsCard.TLabelframe', padding=8)
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

        # 分辨率信息
        res_frame = ttk.Frame(frame3, style='SettingsInner.TFrame')
        res_frame.pack(fill=tk.X, pady=(8, 0))
        current_res = config.get_resolution_key()
        stored_res = config.load_template_resolution()
        res_text = f"当前分辨率：{current_res}"
        if stored_res and stored_res != current_res:
            res_text += f"  ⚠️ 模板分辨率：{stored_res}（不匹配）"
        elif stored_res:
            res_text += "  ✅ 与模板一致"
        ttk.Label(res_frame, text=res_text, style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(res_frame, text="上传模板图片", style='Accent.TButton',
                   command=self._open_capture_wizard, width=14).pack(side=tk.RIGHT)

        # ----- 日志保存目录 -----
        frame4 = ttk.LabelFrame(parent, text="  日志保存目录  ", style='SettingsCard.TLabelframe', padding=8)
        frame4.pack(fill=tk.X, pady=(0, 8))

        f4 = ttk.Frame(frame4, style='SettingsInner.TFrame')
        f4.pack(fill=tk.X)
        ttk.Label(f4, text="保存路径：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        log_entry = ttk.Entry(f4, textvariable=self.log_var, width=45)
        log_entry.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        ttk.Button(f4, text="浏览", command=self._browse_log, width=24).pack(side=tk.LEFT)

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

        # ----- 一键出售设置 -----
        sell_frame = ttk.LabelFrame(parent, text="  一键出售  ", style='SettingsCard.TLabelframe', padding=10)
        sell_frame.pack(fill=tk.X, pady=(8, 0))

        sell_inner = ttk.Frame(sell_frame, style='SettingsInner.TFrame')
        sell_inner.pack(fill=tk.X)
        ttk.Checkbutton(sell_inner, text="主流程完成后执行一键售卖",
                        variable=self.enable_sell_var).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(sell_inner, text="降价次数：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(sell_inner, from_=0, to=5, increment=1,
                    textvariable=self.sell_discount_var, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(sell_inner, text="次（0-5，0=不降价）", style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        # 出售置信度滑块
        sell_conf_row = ttk.Frame(sell_frame, style='SettingsInner.TFrame')
        sell_conf_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(sell_conf_row, text="物品匹配置信度：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        sell_scale = ttk.Scale(sell_conf_row, from_=0.40, to=0.80, variable=self.sell_confidence_var,
                               length=180, orient=tk.HORIZONTAL)
        sell_scale.pack(side=tk.LEFT, padx=(0, 8))
        self.sell_conf_label = ttk.Label(sell_conf_row, text="", style='SettingsSmall.TLabel', width=4)
        self.sell_conf_label.pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(sell_conf_row, text="(0.40 - 0.80)", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        self._update_sell_conf_display()

        def on_sell_conf_change(*args):
            self._update_sell_conf_display()
        self.sell_confidence_var.trace_add('write', on_sell_conf_change)


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

    def _build_email_tab(self, parent):
        """邮件通知选项卡内容"""
        # ----- 启用开关 -----
        enable_frame = ttk.LabelFrame(parent, text="  通知设置  ", style='SettingsCard.TLabelframe', padding=12)
        enable_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Checkbutton(enable_frame, text="启用邮件通知（工作流执行完成后自动发送运行结果）",
                       variable=self.email_enable_var).pack(anchor=tk.W, padx=5, pady=5)

        # ----- 邮箱配置 -----
        config_frame = ttk.LabelFrame(parent, text="  邮箱配置  ", style='SettingsCard.TLabelframe', padding=12)
        config_frame.pack(fill=tk.X, pady=(0, 8))

        # 发送者邮箱
        row1 = ttk.Frame(config_frame, style='SettingsInner.TFrame')
        row1.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row1, text="发送者邮箱：", style='Settings.TLabel', width=14).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(row1, textvariable=self.sender_email_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # SMTP 授权码
        row2 = ttk.Frame(config_frame, style='SettingsInner.TFrame')
        row2.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row2, text="SMTP 授权码：", style='Settings.TLabel', width=14).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(row2, textvariable=self.smtp_code_var, width=40, show="*").pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 接收者邮箱
        row3 = ttk.Frame(config_frame, style='SettingsInner.TFrame')
        row3.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row3, text="接收者邮箱：", style='Settings.TLabel', width=14).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Entry(row3, textvariable=self.receiver_email_var, width=40).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 测试发送按钮
        row4 = ttk.Frame(config_frame, style='SettingsInner.TFrame')
        row4.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(row4, text="发送测试邮件", style='Accent.TButton',
                  command=self._test_send_email, width=16).pack(side=tk.LEFT, padx=(0, 10))
        self.email_test_label = ttk.Label(row4, text="", style='Settings.TLabel')
        self.email_test_label.pack(side=tk.LEFT)

        # ----- 使用提示 -----
        tips_frame = ttk.LabelFrame(parent, text="  使用提示  ", style='SettingsCard.TLabelframe', padding=12)
        tips_frame.pack(fill=tk.X, pady=(0, 0))

        tips_text = (
            "1. 登录 QQ 邮箱网页版 → 设置 → 账户 → 开启 SMTP 服务 → 生成授权码\n"
            "2. 将生成的授权码填入上方「SMTP 授权码」栏\n"
            "3. 发送者邮箱和接收者邮箱可以相同（自己发给自己）\n"
            "4. 点击「发送测试邮件」验证配置是否正确\n"
            "5. 工作流执行完成后将自动发送包含运行结果的邮件通知"
        )
        ttk.Label(tips_frame, text=tips_text, style='SettingsSmall.TLabel',
                 wraplength=580, justify=tk.LEFT).pack(padx=5, pady=5)

        server_info = ttk.Frame(tips_frame, style='SettingsInner.TFrame')
        server_info.pack(fill=tk.X, padx=5, pady=(0, 5))
        ttk.Label(server_info, text="SMTP 服务器：smtp.qq.com    SSL 端口：465",
                 style='SettingsSmall.TLabel', font=('Microsoft YaHei UI', 8, 'bold')).pack(anchor=tk.W)

    def _test_send_email(self):
        """发送测试邮件"""
        sender = self.sender_email_var.get().strip()
        code = self.smtp_code_var.get().strip()
        receiver = self.receiver_email_var.get().strip()

        if not sender or not code or not receiver:
            messagebox.showwarning("提示", "请先填写完整的邮箱配置信息")
            return

        self.email_test_label.config(text="正在发送...", foreground="#f39c12")
        self.win.update_idletasks()

        import utils
        success, msg = utils.send_email_notification(
            code, sender, receiver,
            "三角洲自动化工具 - 测试邮件",
            "<h3>测试邮件</h3><p>如果您收到此邮件，说明邮件通知功能配置成功！</p>"
        )
        if success:
            self.email_test_label.config(text="✓ 发送成功！", foreground="#27ae60")
        else:
            self.email_test_label.config(text=f"✗ {msg}", foreground="#e74c3c")

    def _build_other_tab(self, parent):
        """其他设置选项卡内容"""
        # ----- 开机自启动 -----
        frame1 = ttk.LabelFrame(parent, text="  开机自启动  ", style='SettingsCard.TLabelframe', padding=12)
        frame1.pack(fill=tk.X, pady=(0, 8))

        f1 = ttk.Frame(frame1, style='SettingsInner.TFrame')
        f1.pack(fill=tk.X)
        ttk.Checkbutton(f1, text="开机自启动（登录 Windows 时自动运行）",
                       variable=self.autostart_var).pack(side=tk.LEFT, padx=5, pady=5)
        f1b = ttk.Frame(frame1, style='SettingsInner.TFrame')
        f1b.pack(fill=tk.X)
        ttk.Checkbutton(f1b, text="开机后立即运行一次任务（需先开启开机自启动）",
                       variable=self.run_on_startup_var).pack(side=tk.LEFT, padx=5, pady=(0, 5))
        ttk.Label(frame1, text="开启后程序随系统启动时将自动执行一次任务，无需手动操作",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 2))

        # ----- 账号列表鼠标下移距离设置 -----
        frame2 = ttk.LabelFrame(parent, text="  账号列表鼠标下移距离  ", style='SettingsCard.TLabelframe', padding=12)
        frame2.pack(fill=tk.X, pady=(0, 8))

        f2a = ttk.Frame(frame2, style='SettingsInner.TFrame')
        f2a.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(f2a, text="QQ 账号列表鼠标下移距离：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f2a, from_=30, to=300, increment=10,
                    textvariable=self.qq_mouse_move_distance_var, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f2a, text="像素（账号超过3个被遮挡时使用）", style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        # ----- 滚动幅度设置 -----
        frame3 = ttk.LabelFrame(parent, text="  滚动幅度设置  ", style='SettingsCard.TLabelframe', padding=12)
        frame3.pack(fill=tk.X, pady=(0, 8))

        f3 = ttk.Frame(frame3, style='SettingsInner.TFrame')
        f3.pack(fill=tk.X)
        ttk.Label(f3, text="滚动幅度：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f3, from_=50, to=150, increment=10,
                    textvariable=self.scroll_amount_var, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f3, text="（50-150，值越大滚动越多，默认 100）", style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        # ----- 游戏启动等待时间 -----
        frame4 = ttk.LabelFrame(parent, text="  游戏启动等待时间  ", style='SettingsCard.TLabelframe', padding=12)
        frame4.pack(fill=tk.X, pady=(0, 0))

        f4 = ttk.Frame(frame4, style='SettingsInner.TFrame')
        f4.pack(fill=tk.X)
        ttk.Label(f4, text="额外等待时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f4, from_=0, to=120, increment=5,
                    textvariable=self.game_launch_wait_var, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f4, text="秒（0-120，机器配置较低时可增加等待，默认 0）", style='SettingsSmall.TLabel').pack(side=tk.LEFT)

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

    def _update_sell_conf_display(self):
        val = self.sell_confidence_var.get()
        percent = int(val * 100)
        self.sell_conf_label.config(text=f"{percent}%")

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

    def _open_capture_wizard(self):
        """打开模板截图向导"""
        from template_capture import TemplateCaptureWizard
        current_res = config.get_resolution_key()
        TemplateCaptureWizard(self.win, current_res)

    def _get_autostart_state(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_READ)
            try:
                value, _ = winreg.QueryValueEx(key, "DeltaAutoTool")
                # 验证值非空且包含程序路径
                return bool(value and value.strip())
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except (FileNotFoundError, PermissionError, OSError):
            return False

    def _set_autostart(self, enable, run_on_startup=False):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE | winreg.KEY_READ)
        except (FileNotFoundError, PermissionError):
            return
        try:
            if enable:
                flags = "--auto-start"
                if run_on_startup:
                    flags += " --run-on-startup"
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                    # 确保路径用双引号包裹，正确处理中文路径和空格
                    reg_value = f'"{exe_path}" {flags}'
                else:
                    python_exe = sys.executable
                    script_path = os.path.abspath(sys.argv[0])
                    reg_value = f'"{python_exe}" "{script_path}" {flags}'
                winreg.SetValueEx(key, "DeltaAutoTool", 0, winreg.REG_SZ, reg_value)
            else:
                try:
                    winreg.DeleteValue(key, "DeltaAutoTool")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)

    def _save(self):
        # 全局设置
        self.app.settings["wegame_path"] = self.wegame_var.get()
        self.app.settings["delta_path"] = self.delta_var.get()
        self.app.settings["confidence"] = round(self.confidence_var.get(), 2)
        self.app.settings["log_save_path"] = self.log_var.get()
        self._set_autostart(self.autostart_var.get(), self.run_on_startup_var.get())
        self.app.settings["run_on_startup"] = self.run_on_startup_var.get()

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

        # 邮件通知设置
        self.app.settings["email_enabled"] = self.email_enable_var.get()
        self.app.settings["smtp_code"] = self.smtp_code_var.get()
        self.app.settings["sender_email"] = self.sender_email_var.get()
        self.app.settings["receiver_email"] = self.receiver_email_var.get()

        # 账号列表滚动查找设置
        self.app.settings["qq_mouse_move_distance"] = self.qq_mouse_move_distance_var.get()
        self.app.settings["scroll_amount"] = self.scroll_amount_var.get()
        self.app.settings["game_launch_wait"] = self.game_launch_wait_var.get()

        # 一键出售设置
        self.app.settings["enable_sell_after_run"] = self.enable_sell_var.get()
        self.app.settings["sell_discount_times"] = self.sell_discount_var.get()
        self.app.settings["sell_confidence"] = round(self.sell_confidence_var.get(), 2)

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
