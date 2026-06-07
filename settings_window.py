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
import utils
from PIL import Image, ImageTk


class SettingsWindow:
    def __init__(self, parent, app):
        self.parent = parent
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("设置")
        self.win.geometry("550x700")
        self.win.resizable(True, True)
        self.win.minsize(550, 500)
        # 窗口居中
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - 550) // 2
        y = (self.win.winfo_screenheight() - 700) // 2
        self.win.geometry(f"550x700+{x}+{y}")
        self.win.transient(parent)
        self.win.grab_set()
        # 设置窗口图标
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
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
        self.cooldown_run_immediately_var = tk.BooleanVar(value=app.settings.get("cooldown_run_immediately", False))
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
        self.cooldown_email_enabled_var = tk.BooleanVar(value=app.settings.get("cooldown_email_enabled", False))

        # 账号列表滚动查找变量
        self.qq_mouse_move_distance_var = tk.IntVar(value=app.settings.get("qq_mouse_move_distance", 100))
        self.scroll_amount_var = tk.IntVar(value=app.settings.get("scroll_amount", 100))
        self.game_launch_wait_var = tk.IntVar(value=app.settings.get("game_launch_wait", 0))

        # 一键出售变量
        self.enable_sell_var = tk.BooleanVar(value=app.settings.get("enable_sell_after_run", False))
        self.sell_confidence_var = tk.DoubleVar(value=float(app.settings.get("sell_confidence", 0.55)))

        # 售卖时间区间变量
        self.sell_time_enabled_var = tk.BooleanVar(value=app.settings.get("sell_time_enabled", False))
        self.sell_time_start_var = tk.StringVar(value=app.settings.get("sell_time_start", "08:00"))
        self.sell_time_end_var = tk.StringVar(value=app.settings.get("sell_time_end", "22:00"))

        # 邮箱货币变量
        self.email_currency_var = tk.BooleanVar(value=app.settings.get("enable_email_currency", False))

        # 冷却管理变量
        self.cooldown_enable_var = tk.BooleanVar(value=app.settings.get("enable_cooldown", False))
        self.cooldown_delay_var = tk.IntVar(value=app.settings.get("cooldown_delay_minutes", 1))

        # 电源管理变量
        self.wake_var = tk.BooleanVar(value=app.settings.get("wake_enabled", True))
        self.shutdown_enable_var = tk.BooleanVar(value=app.settings.get("auto_shutdown_enabled", False))
        self.shutdown_time_var = tk.StringVar(value=app.settings.get("auto_shutdown_time", "22:00"))
        self.startup_enable_var = tk.BooleanVar(value=app.settings.get("auto_startup_enabled", False))
        self.startup_time_var = tk.StringVar(value=app.settings.get("auto_startup_time", "07:00"))
        self.post_run_shutdown_delay_var = tk.IntVar(value=app.settings.get("post_run_shutdown_delay", 0))

        self._active_canvas = None
        self._setup_styles()
        self._build_ui()
        self.win.bind_all("<MouseWheel>", self._on_mousewheel)

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

    def _on_mousewheel(self, event):
        """全局滚轮事件处理，仅滚动当前激活的 canvas"""
        if self._active_canvas:
            try:
                self._active_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass

    def _create_scrollable_tab(self, parent):
        """为 Tab 内容创建 Canvas+Scrollbar 滚动容器，返回内部 Frame"""
        canvas = tk.Canvas(parent, highlightthickness=0, bg='#ffffff')
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        inner_frame = ttk.Frame(canvas, style='Settings.TFrame')

        inner_frame_id = canvas.create_window((0, 0), window=inner_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(inner_frame_id, width=event.width)

        def _on_enter(event):
            self._active_canvas = canvas

        def _on_leave(event):
            if self._active_canvas is canvas:
                self._active_canvas = None

        inner_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)
        inner_frame.bind("<Enter>", _on_enter)
        inner_frame.bind("<Leave>", _on_leave)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        return inner_frame

    def _build_ui(self):
        # 主容器
        main_frame = ttk.Frame(self.win, style='Settings.TFrame', padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ----- 底部操作按钮（先 pack 到底部，确保始终可见） -----
        btn_frame = ttk.Frame(main_frame, style='Settings.TFrame')
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        ttk.Button(btn_frame, text="✓ 保存设置", style='Success.TButton',
                   command=self._save, width=14).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="✕ 取消", style='TButton',
                   command=self.win.destroy, width=10).pack(side=tk.LEFT)

        # 选项卡
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # ----- Tab 1: 全局设置 -----
        global_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(global_tab_outer, text="  全局设置  ")
        global_tab = self._create_scrollable_tab(global_tab_outer)
        self._build_global_tab(global_tab)

        # ----- Tab 2: 售卖物品 -----
        sell_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(sell_tab_outer, text="  售卖物品  ")
        sell_tab = self._create_scrollable_tab(sell_tab_outer)
        self._build_sell_tab(sell_tab)

        # ----- Tab 3: 自动任务设置 -----
        auto_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(auto_tab_outer, text="  自动任务  ")
        auto_tab = self._create_scrollable_tab(auto_tab_outer)
        self._build_auto_tab(auto_tab)

        # ----- Tab 4: 电源管理 -----
        power_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(power_tab_outer, text="  电源管理  ")
        power_tab = self._create_scrollable_tab(power_tab_outer)
        self._build_power_tab(power_tab)

        # ----- Tab 5: 邮件通知 -----
        email_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(email_tab_outer, text="  邮件通知  ")
        email_tab = self._create_scrollable_tab(email_tab_outer)
        self._build_email_tab(email_tab)

        # ----- Tab 6: 其他设置 -----
        other_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(other_tab_outer, text="  其他设置  ")
        other_tab = self._create_scrollable_tab(other_tab_outer)
        self._build_other_tab(other_tab)

    def _build_global_tab(self, parent):
        """全局设置选项卡内容"""
        # ----- WeGame 路径 -----
        frame1 = ttk.LabelFrame(parent, text="  WeGame 路径  ", style='SettingsCard.TLabelframe', padding=8)
        frame1.pack(fill=tk.X, pady=(0, 8))

        f1 = ttk.Frame(frame1, style='SettingsInner.TFrame')
        f1.pack(fill=tk.X)
        ttk.Label(f1, text="WeGame.exe：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        wegame_entry = ttk.Entry(f1, textvariable=self.wegame_var, width=45)
        wegame_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ----- 三角洲路径 -----
        frame2 = ttk.LabelFrame(parent, text="  三角洲路径（可选）  ", style='SettingsCard.TLabelframe', padding=8)
        frame2.pack(fill=tk.X, pady=(0, 8))

        f2 = ttk.Frame(frame2, style='SettingsInner.TFrame')
        f2.pack(fill=tk.X)
        ttk.Label(f2, text="启动程序：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        delta_entry = ttk.Entry(f2, textvariable=self.delta_var, width=45)
        delta_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ----- QQ 路径 -----
        frame_qq = ttk.LabelFrame(parent, text="  QQ 路径  ", style='SettingsCard.TLabelframe', padding=8)
        frame_qq.pack(fill=tk.X, pady=(0, 8))

        f_qq = ttk.Frame(frame_qq, style='SettingsInner.TFrame')
        f_qq.pack(fill=tk.X)
        ttk.Label(f_qq, text="QQ.exe：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        qq_entry = ttk.Entry(f_qq, textvariable=self.qq_path_var, width=45)
        qq_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ----- 日志保存目录 -----
        frame4 = ttk.LabelFrame(parent, text="  日志保存目录  ", style='SettingsCard.TLabelframe', padding=8)
        frame4.pack(fill=tk.X, pady=(0, 8))

        f4 = ttk.Frame(frame4, style='SettingsInner.TFrame')
        f4.pack(fill=tk.X)
        ttk.Label(f4, text="保存路径：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        log_entry = ttk.Entry(f4, textvariable=self.log_var, width=45)
        log_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

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

        # ----- 资产识别设置 -----
        asset_frame = ttk.LabelFrame(parent, text="  资产识别  ", style='SettingsCard.TLabelframe', padding=12)
        asset_frame.pack(fill=tk.X, pady=(0, 8))

        self.enable_asset_var = tk.BooleanVar(value=self.app.settings.get("enable_asset_recognition", False))
        ttk.Checkbutton(asset_frame, text="启用资产识别（游戏内自动识别资产数值）",
                        variable=self.enable_asset_var,
                        style='Settings.TCheckbutton').pack(anchor='w', pady=(0, 5))

        asset_region_frame = ttk.Frame(asset_frame, style='SettingsInner.TFrame')
        asset_region_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(asset_region_frame, text="识别区域 (x, y, w, h)：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        asset_region = self.app.settings.get("asset_region", [0, 0, 0, 0])
        self.asset_region_var = tk.StringVar(value=str(asset_region))
        ttk.Entry(asset_region_frame, textvariable=self.asset_region_var, width=20).pack(side=tk.LEFT, padx=(0, 8))

        asset_btn_frame = ttk.Frame(asset_frame, style='SettingsInner.TFrame')
        asset_btn_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(asset_btn_frame, text="设置区域", command=self._set_asset_region, width=10).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(asset_btn_frame, text="测试识别", command=self._test_asset_recognition, width=10).pack(side=tk.LEFT)

        # ----- 使用说明 -----
        guide_frame = ttk.LabelFrame(parent, text="  使用说明  ", style='SettingsCard.TLabelframe', padding=12)
        guide_frame.pack(fill=tk.X, pady=(0, 8))

        import account_manager
        ttk.Button(guide_frame, text="查看使用说明", style='Accent.TButton',
                   command=lambda: account_manager.show_help(self.app), width=14).pack(anchor='w', padx=5, pady=5)

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

        # 第1.5行：冷却完立即运行（与启用定时执行互斥）
        row1b = ttk.Frame(parent, style='SettingsInner.TFrame')
        row1b.pack(fill=tk.X, pady=(0, 12))

        self._cooldown_run_immed_cb = ttk.Checkbutton(
            row1b, text="冷却完立即运行（冷却结束后自动执行，与定时执行互斥）",
            variable=self.cooldown_run_immediately_var)
        self._cooldown_run_immed_cb.pack(side=tk.LEFT, padx=(0, 18))

        # 获取"启用定时执行"Checkbutton 引用（row1 的第一个子控件）
        self._auto_enable_cb = row1.winfo_children()[0]

        # 互斥逻辑：勾选一个时取消另一个并禁用，取消时恢复另一个
        def _on_auto_enable_changed(*args):
            if self.auto_enable_var.get():
                self.cooldown_run_immediately_var.set(False)
                self._cooldown_run_immed_cb.state(['disabled'])
            else:
                self._cooldown_run_immed_cb.state(['!disabled'])

        def _on_cooldown_run_immed_changed(*args):
            if self.cooldown_run_immediately_var.get():
                self.auto_enable_var.set(False)
                self._auto_enable_cb.state(['disabled'])
            else:
                self._auto_enable_cb.state(['!disabled'])

        self.auto_enable_var.trace_add('write', _on_auto_enable_changed)
        self.cooldown_run_immediately_var.trace_add('write', _on_cooldown_run_immed_changed)

        # 初始化互斥状态
        if self.auto_enable_var.get():
            self._cooldown_run_immed_cb.state(['disabled'])
        if self.cooldown_run_immediately_var.get():
            self._auto_enable_cb.state(['disabled'])

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

        # ----- 运行完成后延迟关机 -----
        frame2b = ttk.LabelFrame(parent, text="  运行完成后关机  ", style='SettingsCard.TLabelframe', padding=12)
        frame2b.pack(fill=tk.X, pady=(0, 8))

        f2b = ttk.Frame(frame2b, style='SettingsInner.TFrame')
        f2b.pack(fill=tk.X)
        ttk.Label(f2b, text="所有账号运行完成后延迟关机：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f2b, from_=0, to=5, increment=1,
                    textvariable=self.post_run_shutdown_delay_var, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f2b, text="分钟", style='Settings.TLabel').pack(side=tk.LEFT)
        note2b = ttk.Frame(frame2b, style='SettingsInner.TFrame')
        note2b.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(note2b, text="所有账号处理完毕后，按设定延迟时间自动关机（0表示不关机）",
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

        note_frame = ttk.Frame(frame3, style='SettingsInner.TFrame')
        note_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(note_frame,
                 text="💡 定时开机功能可在电脑处于睡眠/休眠状态时将其唤醒。\n    若电脑为完全关机状态，需主板支持 RTC 唤醒并在 BIOS 中启用【定时开机】或「RTC Alarm」功能。",
                 style='SettingsSmall.TLabel', wraplength=480, justify=tk.LEFT).pack(anchor='w', padx=5, pady=5)

    def _build_email_tab(self, parent):
        """邮件通知选项卡内容"""
        # ----- 启用开关 -----
        enable_frame = ttk.LabelFrame(parent, text="  通知设置  ", style='SettingsCard.TLabelframe', padding=12)
        enable_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Checkbutton(enable_frame, text="启用邮件通知（工作流执行完成后自动发送运行结果）",
                       variable=self.email_enable_var).pack(anchor=tk.W, padx=5, pady=5)
        ttk.Checkbutton(enable_frame, text="冷却结束后发送邮件提醒（账号冷却到期时自动发送通知）",
                       variable=self.cooldown_email_enabled_var).pack(anchor=tk.W, padx=5, pady=(0, 5))

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
            "5. 工作流执行完成后将自动发送包含运行结果的邮件通知\n"
            "6. 冷却到期提醒需先启用「启用邮件通知」，再单独勾选冷却提醒"
        )
        ttk.Label(tips_frame, text=tips_text, style='SettingsSmall.TLabel',
                 wraplength=500, justify=tk.LEFT).pack(anchor='w', padx=5, pady=5)

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
        # ----- 机器指纹 -----
        frame_fp = ttk.LabelFrame(parent, text="  机器指纹（本机唯一标识）  ", style='SettingsCard.TLabelframe', padding=12)
        frame_fp.pack(fill=tk.X, pady=(0, 8))

        fp_row = ttk.Frame(frame_fp, style='SettingsInner.TFrame')
        fp_row.pack(fill=tk.X, pady=(0, 4))
        self._fingerprint_var = tk.StringVar(value="加载中...")
        ttk.Entry(fp_row, textvariable=self._fingerprint_var, width=36,
                  state='readonly', font=('Consolas', 9)).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(frame_fp, text="此指纹用于服务器绑定验证，需告知管理员添加到白名单后方可使用",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(4, 0))
        # 自动加载指纹
        try:
            import machine_fingerprint
            info = machine_fingerprint.get_machine_info()
            self._fingerprint_var.set(info["machine_id"])
        except Exception:
            self._fingerprint_var.set("获取失败")

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

        # ----- 冷却管理 -----
        frame_cooldown = ttk.LabelFrame(parent, text="  冷却管理  ", style='SettingsCard.TLabelframe', padding=12)
        frame_cooldown.pack(fill=tk.X, pady=(0, 8))

        cd_row1 = ttk.Frame(frame_cooldown, style='SettingsInner.TFrame')
        cd_row1.pack(fill=tk.X, pady=(0, 4))
        self._cooldown_enable_cb = ttk.Checkbutton(cd_row1, text="启用账号冷却（每次运行完成后进入冷却期）",
                       variable=self.cooldown_enable_var)
        self._cooldown_enable_cb.pack(side=tk.LEFT, padx=5, pady=5)

        # 冷却完立即运行与启用账号冷却的联动
        def _on_cooldown_enable_changed(*args):
            if not self.cooldown_enable_var.get():
                # 取消启用账号冷却时，自动取消冷却完立即运行
                self.cooldown_run_immediately_var.set(False)

        def _on_cooldown_run_immed_changed_for_enable(*args):
            if self.cooldown_run_immediately_var.get():
                # 启用冷却完立即运行时，自动勾选启用账号冷却
                self.cooldown_enable_var.set(True)

        self.cooldown_enable_var.trace_add('write', _on_cooldown_enable_changed)
        self.cooldown_run_immediately_var.trace_add('write', _on_cooldown_run_immed_changed_for_enable)

        cd_row2 = ttk.Frame(frame_cooldown, style='SettingsInner.TFrame')
        cd_row2.pack(fill=tk.X)
        ttk.Label(cd_row2, text="账号间隔时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(5, 4))
        ttk.Spinbox(cd_row2, from_=0, to=5, increment=1,
                    textvariable=self.cooldown_delay_var, width=6).pack(side=tk.RIGHT, padx=(0, 4))

        # ----- 账号列表鼠标下移距离设置 -----
        frame2 = ttk.LabelFrame(parent, text="  账号列表鼠标下移距离  ", style='SettingsCard.TLabelframe', padding=12)
        frame2.pack(fill=tk.X, pady=(0, 8))

        f2a = ttk.Frame(frame2, style='SettingsInner.TFrame')
        f2a.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(f2a, text="QQ 账号列表鼠标下移距离：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f2a, from_=30, to=300, increment=10,
                    textvariable=self.qq_mouse_move_distance_var, width=6).pack(side=tk.RIGHT, padx=(0, 4))

        # ----- 滚动幅度设置 -----
        frame3 = ttk.LabelFrame(parent, text="  滚动幅度设置  ", style='SettingsCard.TLabelframe', padding=12)
        frame3.pack(fill=tk.X, pady=(0, 8))

        f3 = ttk.Frame(frame3, style='SettingsInner.TFrame')
        f3.pack(fill=tk.X)
        ttk.Label(f3, text="滚动幅度：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f3, from_=50, to=150, increment=10,
                    textvariable=self.scroll_amount_var, width=6).pack(side=tk.RIGHT, padx=(0, 4))

        # ----- 游戏启动等待时间 -----
        frame4 = ttk.LabelFrame(parent, text="  游戏启动等待时间  ", style='SettingsCard.TLabelframe', padding=12)
        frame4.pack(fill=tk.X, pady=(0, 8))

        f4 = ttk.Frame(frame4, style='SettingsInner.TFrame')
        f4.pack(fill=tk.X)
        ttk.Label(f4, text="额外等待时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(f4, from_=0, to=120, increment=5,
                    textvariable=self.game_launch_wait_var, width=6).pack(side=tk.RIGHT, padx=(0, 4))

        # ----- 设置说明 -----
        tips_frame = ttk.Frame(parent, style='SettingsInner.TFrame')
        tips_frame.pack(fill=tk.X, pady=(0, 0))
        tips_lines = (
            "• 账号间隔时间：0-5分钟，相邻账号执行间隔，0=连续执行\n"
            "• 鼠标下移距离：30-300像素，账号超过3个被遮挡时使用\n"
            "• 滚动幅度：50-150，值越大滚动越多，默认100\n"
            "• 额外等待时间：0-120秒，机器配置较低时可增加等待，默认0"
        )
        ttk.Label(tips_frame, text=tips_lines, style='SettingsSmall.TLabel',
                  justify=tk.LEFT).pack(anchor='w', padx=5, pady=5)

    def _build_sell_tab(self, parent):
        """售卖物品选项卡内容"""
        # ----- 物品列表 -----
        list_frame = ttk.LabelFrame(parent, text="  售卖物品列表  ", style='SettingsCard.TLabelframe', padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        # Treeview
        columns = ("name", "discount_times", "quantity", "filename")
        self.sell_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=4)
        self.sell_tree.heading("name", text="名称")
        self.sell_tree.heading("discount_times", text="降价次数")
        self.sell_tree.heading("quantity", text="出售数量")
        self.sell_tree.heading("filename", text="图片文件")
        self.sell_tree.column("name", width=100)
        self.sell_tree.column("discount_times", width=80, anchor="center")
        self.sell_tree.column("quantity", width=80, anchor="center")
        self.sell_tree.column("filename", width=90)

        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.sell_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.configure(command=self.sell_tree.yview)
        self.sell_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 双击编辑
        self.sell_tree.bind("<Double-1>", self._on_sell_treeview_edit)

        # 加载物品元数据
        self._sell_items_meta = config.load_sell_items_meta()
        self._refresh_sell_treeview()

        # ----- 物品操作按钮 -----
        btn_frame = ttk.LabelFrame(parent, text="  物品操作  ", style='SettingsCard.TLabelframe', padding=10)
        btn_frame.pack(fill=tk.X, pady=(0, 8))

        btn_row = ttk.Frame(btn_frame, style='SettingsInner.TFrame')
        btn_row.pack(fill=tk.X)
        ttk.Button(btn_row, text="添加物品", width=10,
                   command=self._add_sell_item).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="删除选中", width=10,
                   command=self._delete_sell_item).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="上移", width=8,
                   command=lambda: self._move_sell_item(-1)).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="下移", width=8,
                   command=lambda: self._move_sell_item(1)).pack(side=tk.LEFT)

        # ----- 邮箱货币领取 -----
        frame_email = ttk.LabelFrame(parent, text="  邮箱货币领取  ", style='SettingsCard.TLabelframe', padding=12)
        frame_email.pack(fill=tk.X, pady=(0, 8))
        ttk.Checkbutton(frame_email, text="启用自动领取邮箱货币",
                       variable=self.email_currency_var).pack(side=tk.LEFT, padx=5, pady=5)

        # ----- 售卖时间区间 -----
        time_frame = ttk.LabelFrame(parent, text="  售卖时间区间  ", style='SettingsCard.TLabelframe', padding=10)
        time_frame.pack(fill=tk.X, pady=(0, 8))

        time_row1 = ttk.Frame(time_frame, style='SettingsInner.TFrame')
        time_row1.pack(fill=tk.X)
        ttk.Checkbutton(time_row1, text="启用时间区间限制",
                        variable=self.sell_time_enabled_var).pack(side=tk.LEFT, padx=(0, 15))

        time_row2 = ttk.Frame(time_frame, style='SettingsInner.TFrame')
        time_row2.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(time_row2, text="开始时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(time_row2, textvariable=self.sell_time_start_var, width=8).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(time_row2, text="结束时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(time_row2, textvariable=self.sell_time_end_var, width=8).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Label(time_row2, text="格式 HH:MM，仅在此时间段内执行售卖",
                  style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        # ----- 出售设置 -----
        sell_frame = ttk.LabelFrame(parent, text="  出售设置  ", style='SettingsCard.TLabelframe', padding=10)
        sell_frame.pack(fill=tk.X, pady=(0, 8))

        sell_row1 = ttk.Frame(sell_frame, style='SettingsInner.TFrame')
        sell_row1.pack(fill=tk.X)
        ttk.Checkbutton(sell_row1, text="主流程完成后执行一键售卖",
                        variable=self.enable_sell_var).pack(side=tk.LEFT, padx=(0, 15))

        sell_row2 = ttk.Frame(sell_frame, style='SettingsInner.TFrame')
        sell_row2.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(sell_row2, text="物品匹配置信度：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        sell_scale = ttk.Scale(sell_row2, from_=0.40, to=0.80, variable=self.sell_confidence_var,
                               length=180, orient=tk.HORIZONTAL)
        sell_scale.pack(side=tk.LEFT, padx=(0, 8))
        self.sell_conf_label = ttk.Label(sell_row2, text="", style='SettingsSmall.TLabel', width=4)
        self.sell_conf_label.pack(side=tk.LEFT, padx=(0, 2))
        ttk.Label(sell_row2, text="(0.40 - 0.80)", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        self._update_sell_conf_display()

        def on_sell_conf_change(*args):
            self._update_sell_conf_display()
        self.sell_confidence_var.trace_add('write', on_sell_conf_change)

        sell_row3 = ttk.Frame(sell_frame, style='SettingsInner.TFrame')
        sell_row3.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(sell_row3, text="出售测试", width=10,
                   command=self._sell_test_from_tab).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(sell_row3, text="说明：测试前请先回到游戏仓库界面",
                  style='SettingsSmall.TLabel').pack(side=tk.LEFT)

    def _refresh_sell_treeview(self):
        """刷新售卖物品 Treeview"""
        for item in self.sell_tree.get_children():
            self.sell_tree.delete(item)
        for item in self._sell_items_meta.get("items", []):
            self.sell_tree.insert("", tk.END, values=(
                item.get("name", ""),
                item.get("discount_times", 0),
                item.get("quantity", 1),
                item.get("filename", "")
            ))

    def _add_sell_item(self):
        """添加售卖物品图片"""
        filetypes = [("图片文件", "*.png;*.jpg;*.jpeg;*.bmp"), ("所有文件", "*.*")]
        src = filedialog.askopenfilename(title="选择售卖物品图片", filetypes=filetypes)
        if not src:
            return
        try:
            os.makedirs(config.SELL_ITEMS_DIR, exist_ok=True)
            basename = os.path.basename(src)
            name, ext = os.path.splitext(basename)
            save_path = os.path.join(config.SELL_ITEMS_DIR, basename)
            counter = 1
            while os.path.exists(save_path):
                save_path = os.path.join(config.SELL_ITEMS_DIR, f"{name}_{counter}{ext}")
                counter += 1
            with open(src, "rb") as f_in, open(save_path, "wb") as f_out:
                f_out.write(f_in.read())
            saved_name = os.path.basename(save_path)
            self._sell_items_meta.setdefault("items", []).append({
                "filename": saved_name,
                "name": os.path.splitext(saved_name)[0],
                "discount_times": 0,
                "quantity": 1
            })
            self._refresh_sell_treeview()
        except Exception as e:
            messagebox.showerror("错误", f"添加失败：{e}")

    def _delete_sell_item(self):
        """删除选中的售卖物品"""
        sel = self.sell_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要删除的物品。")
            return
        item_vals = self.sell_tree.item(sel[0], "values")
        item_name = item_vals[0]
        filename = item_vals[3]
        if not messagebox.askyesno("确认", f"确定删除售卖物品「{item_name}」？"):
            return
        try:
            os.remove(os.path.join(config.SELL_ITEMS_DIR, filename))
        except Exception:
            pass
        self._sell_items_meta["items"] = [
            i for i in self._sell_items_meta["items"] if i["filename"] != filename
        ]
        self._refresh_sell_treeview()

    def _move_sell_item(self, direction):
        """上移/下移物品 (-1=上移, 1=下移)"""
        sel = self.sell_tree.selection()
        if not sel:
            return
        items = self._sell_items_meta.get("items", [])
        idx = self.sell_tree.index(sel[0])
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(items):
            return
        items[idx], items[new_idx] = items[new_idx], items[idx]
        self._refresh_sell_treeview()
        # 重新选中移动后的项
        children = self.sell_tree.get_children()
        if new_idx < len(children):
            self.sell_tree.selection_set(children[new_idx])

    def _on_sell_treeview_edit(self, event):
        """双击编辑 Treeview 单元格"""
        region = self.sell_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.sell_tree.identify_column(event.x)
        row_id = self.sell_tree.identify_row(event.y)
        if not row_id:
            return

        col_idx = int(column.replace("#", "")) - 1  # 0-based
        # 只允许编辑 name(0), discount_times(1), quantity(2)
        if col_idx > 2:
            return

        item_idx = self.sell_tree.index(row_id)
        items = self._sell_items_meta.get("items", [])
        if item_idx >= len(items):
            return

        bbox = self.sell_tree.bbox(row_id, column)
        if not bbox:
            return
        x, y, w, h = bbox

        current_val = self.sell_tree.item(row_id, "values")[col_idx]

        if col_idx == 0:
            # 名称 - Entry
            entry = ttk.Entry(self.sell_tree, width=15)
            entry.insert(0, current_val)
            entry.select_range(0, tk.END)
            entry.place(x=x, y=y, width=w, height=h)
            entry.focus_set()

            def _confirm_name(e=None):
                items[item_idx]["name"] = entry.get()
                entry.destroy()
                self._refresh_sell_treeview()

            entry.bind("<Return>", _confirm_name)
            entry.bind("<FocusOut>", _confirm_name)
        else:
            # 降价次数/出售数量 - Spinbox
            from_ = 0 if col_idx == 1 else 1
            to_ = 5 if col_idx == 1 else 99
            spin = ttk.Spinbox(self.sell_tree, from_=from_, to=to_, width=5)
            spin.delete(0, tk.END)
            spin.insert(0, current_val)
            spin.place(x=x, y=y, width=w, height=h)
            spin.focus_set()

            field = "discount_times" if col_idx == 1 else "quantity"

            def _confirm_spin(e=None):
                try:
                    val = int(spin.get())
                    items[item_idx][field] = val
                except ValueError:
                    pass
                spin.destroy()
                self._refresh_sell_treeview()

            spin.bind("<Return>", _confirm_spin)
            spin.bind("<FocusOut>", _confirm_spin)

    def _save_sell_items_meta(self):
        """保存物品元数据到文件"""
        config.save_sell_items_meta(self._sell_items_meta)

    def _sell_test_from_tab(self):
        """从售卖物品Tab触发出售测试"""
        if not self.app:
            messagebox.showwarning("提示", "无法访问主程序。")
            return
        if self.app.running:
            messagebox.showwarning("提示", "任务运行中，请等待完成后再测试。")
            return
        items = self._sell_items_meta.get("items", [])
        if not items:
            messagebox.showwarning("提示", "未配置任何售卖物品，请先添加物品。")
            return
        import threading

        def _run():
            import pyautogui
            start_time = __import__('time').time()
            pyautogui.press("Tab")
            __import__('time').sleep(1)
            success, sell_stats = self.app._sell_operations()
            elapsed = __import__('time').time() - start_time
            stats_text = (f"测试耗时：{elapsed:.1f} 秒\n"
                          f"共 {sell_stats['total']} 件物品\n"
                          f"成功上架：{sell_stats['sold']} 件\n"
                          f"未找到：{sell_stats['not_found']} 件\n"
                          f"失败：{sell_stats['failed']} 件")
            self.win.after(0, lambda: messagebox.showinfo("出售测试完成", stats_text))

        threading.Thread(target=_run, daemon=True).start()

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

    def _set_asset_region(self):
        """让用户在屏幕上拖动框选资产识别区域"""
        self.win.withdraw()
        import time
        time.sleep(0.3)

        import tkinter as tk_overlay

        overlay = tk_overlay.Toplevel(self.win)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-alpha', 0.3)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='black')
        overlay.config(cursor="crosshair")

        canvas = tk_overlay.Canvas(overlay, highlightthickness=0, bg='black')
        canvas.pack(fill=tk.BOTH, expand=True)

        hint = tk_overlay.Label(overlay, text="请拖动鼠标框选资产识别区域，按 Esc 取消",
                                font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
        hint.place(relx=0.5, rely=0.05, anchor='center')

        rect_id = None
        start_x = start_y = 0
        result = None

        def on_press(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y,
                                              outline='red', width=2)

        def on_drag(event):
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)

        def on_release(event):
            nonlocal result
            x1, y1 = min(start_x, event.x), min(start_y, event.y)
            x2, y2 = max(start_x, event.x), max(start_y, event.y)
            if x2 - x1 > 10 and y2 - y1 > 10:
                result = [x1, y1, x2 - x1, y2 - y1]
            overlay.destroy()

        def on_escape(event):
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)

        self.win.wait_window(overlay)
        self.win.deiconify()

        if result:
            self.asset_region_var.set(str(result))

    def _test_asset_recognition(self):
        """测试资产识别：对设定区域执行 OCR 并显示结果"""
        try:
            import re
            region_str = self.asset_region_var.get().strip()
            if not region_str:
                messagebox.showwarning("提示", "请先设置识别区域", parent=self.win)
                return
            region = eval(region_str)
            if not isinstance(region, list) or len(region) != 4 or region[2] <= 0 or region[3] <= 0:
                messagebox.showwarning("提示", "识别区域格式不正确，应为 [x, y, w, h]", parent=self.win)
                return

            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError:
                messagebox.showerror("错误",
                    "RapidOCR 未安装，请先安装：pip install rapidocr-onnxruntime",
                    parent=self.win)
                return

            # 最小化设置窗口
            self.win.withdraw()
            import time
            time.sleep(0.5)

            import pyautogui
            import numpy as np
            x, y, w, h = region
            screenshot = pyautogui.screenshot(region=(x, y, w, h))
            img_array = np.array(screenshot)

            ocr = RapidOCR()
            result, _ = ocr(img_array)

            self.win.deiconify()

            if not result:
                messagebox.showinfo("测试结果",
                    f"识别区域：({x}, {y}) - {w}x{h}\n\n"
                    "识别结果：未检测到文字",
                    parent=self.win)
                return

            # 拼接所有识别到的文本
            all_text = "".join(item[1] for item in result)

            # 匹配资产格式：数字+K/M/B
            match = re.search(r'(\d+\.?\d*)\s*([KMBkmb])', all_text)
            if match:
                asset_str = f"{match.group(1)}{match.group(2).upper()}"
            else:
                asset_str = "未匹配到资产格式"

            detail_lines = [f"  {item[1]}  (置信度：{float(item[2]):.2f})" for item in result]
            detail_text = "\n".join(detail_lines)

            messagebox.showinfo("测试结果",
                f"识别区域：({x}, {y}) - {w}x{h}\n\n"
                f"识别到的文字：\n{detail_text}\n\n"
                f"解析结果：{asset_str}",
                parent=self.win)

        except SyntaxError:
            messagebox.showerror("错误", "区域格式不正确，应为 [x, y, w, h]", parent=self.win)
        except Exception as e:
            self.win.deiconify()
            messagebox.showerror("测试失败", f"识别出错：{e}", parent=self.win)

    def _open_capture_wizard(self):
        """打开模板截图向导"""
        from template_capture import TemplateCaptureWizard
        current_res = config.get_resolution_key()
        TemplateCaptureWizard(self.win, current_res, app=self.app)

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
        self.app.settings["cooldown_run_immediately"] = self.cooldown_run_immediately_var.get()
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
        self.app.settings["post_run_shutdown_delay"] = self.post_run_shutdown_delay_var.get()

        # QQ 设置
        self.app.settings["qq_path"] = self.qq_path_var.get()

        # 邮件通知设置
        self.app.settings["email_enabled"] = self.email_enable_var.get()
        self.app.settings["smtp_code"] = self.smtp_code_var.get()
        self.app.settings["sender_email"] = self.sender_email_var.get()
        self.app.settings["receiver_email"] = self.receiver_email_var.get()
        self.app.settings["cooldown_email_enabled"] = self.cooldown_email_enabled_var.get()

        # 账号列表滚动查找设置
        self.app.settings["qq_mouse_move_distance"] = self.qq_mouse_move_distance_var.get()
        self.app.settings["scroll_amount"] = self.scroll_amount_var.get()
        self.app.settings["game_launch_wait"] = self.game_launch_wait_var.get()

        # 一键出售设置
        self.app.settings["enable_sell_after_run"] = self.enable_sell_var.get()
        self.app.settings["sell_confidence"] = round(self.sell_confidence_var.get(), 2)

        # 售卖时间区间
        self.app.settings["sell_time_enabled"] = self.sell_time_enabled_var.get()
        self.app.settings["sell_time_start"] = self.sell_time_start_var.get().strip()
        self.app.settings["sell_time_end"] = self.sell_time_end_var.get().strip()

        # 保存物品元数据
        self._save_sell_items_meta()

        # 邮箱货币设置
        self.app.settings["enable_email_currency"] = self.email_currency_var.get()

        # 资产识别设置
        self.app.settings["enable_asset_recognition"] = self.enable_asset_var.get()
        try:
            region_str = self.asset_region_var.get().strip()
            if region_str:
                region = eval(region_str)
                if isinstance(region, list) and len(region) == 4:
                    self.app.settings["asset_region"] = region
        except Exception:
            pass

        # 冷却管理设置
        self.app.settings["enable_cooldown"] = self.cooldown_enable_var.get()
        self.app.settings["cooldown_delay_minutes"] = self.cooldown_delay_var.get()

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
