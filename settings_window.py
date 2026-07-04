"""
设置窗口模块
提供 WeGame 路径、三角洲路径、置信度、开机自启动等全局设置，
以及冷却执行、操作选择等自动任务设置
"""
import os
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ast
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
        self.win.resizable(True, True)
        self.win.minsize(550, 500)
        self.win.transient(parent)
        self.win.grab_set()
        # 设置窗口图标
        utils.set_window_icon(self.win)

        # 全局设置变量
        self.wegame_var = tk.StringVar(value=app.settings.get("wegame_path", ""))
        self.delta_var = tk.StringVar(value=app.settings.get("delta_path", ""))
        self.confidence_var = tk.DoubleVar(value=float(app.settings.get("confidence", 0.7)))
        self.log_var = tk.StringVar(value=app.settings.get("log_save_path", ""))
        self.autostart_var = tk.BooleanVar(value=self._get_autostart_state())
        self.run_on_startup_var = tk.BooleanVar(value=app.settings.get("run_on_startup", False))

        # 自动任务设置变量
        self.cooldown_run_immediately_var = tk.BooleanVar(value=app.settings.get("cooldown_run_immediately", False))
        self.cooldown_scheduled_task_var = tk.BooleanVar(value=app.settings.get("cooldown_scheduled_task_enabled", True))
        self.restart_on_interception_fail_var = tk.BooleanVar(value=app.settings.get("restart_on_interception_fail", False))

        # 操作选择变量
        selected = app.settings.get("selected_operations", [])
        self.op_tech = tk.BooleanVar(value="tech_center" in selected)
        self.op_bench = tk.BooleanVar(value="tool_bench" in selected)
        self.op_armor = tk.BooleanVar(value="armor_station" in selected)
        self.op_pharmacy = tk.BooleanVar(value="pharmacy_station" in selected)


        # 邮件通知变量
        self.email_enable_var = tk.BooleanVar(value=app.settings.get("email_enabled", False))
        self.smtp_code_var = tk.StringVar(value=app.settings.get("smtp_code", ""))
        self.sender_email_var = tk.StringVar(value=app.settings.get("sender_email", ""))
        self.receiver_email_var = tk.StringVar(value=app.settings.get("receiver_email", ""))
        self.cooldown_email_enabled_var = tk.BooleanVar(value=app.settings.get("cooldown_email_enabled", False))

        # 账号列表滚动查找变量
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
        self.cooldown_hours_var = tk.IntVar(value=app.settings.get("cooldown_hours", 8))
        self.cooldown_delay_var = tk.IntVar(value=app.settings.get("cooldown_delay_minutes", 1))

        # 自动关机变量
        self.shutdown_enable_var = tk.BooleanVar(value=app.settings.get("auto_shutdown_enabled", False))
        self.shutdown_time_var = tk.StringVar(value=app.settings.get("auto_shutdown_time", "22:00"))
        self.post_run_shutdown_delay_var = tk.IntVar(value=app.settings.get("post_run_shutdown_delay", 0))

        self._active_canvas = None
        self._trace_ids = []  # 存储 trace 回调 ID，关闭时移除
        self._setup_styles()
        self._build_ui()
        self.win.bind_all("<MouseWheel>", self._on_mousewheel)
        # 恢复窗口大小
        utils.restore_window_geometry(self.win, "settings_window_geometry", "550x700", (550, 500))
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """窗口关闭时清理资源，防止内存泄漏"""
        # 保存窗口大小和位置
        utils.save_window_geometry(self.win, "settings_window_geometry")
        # 保存售卖物品元数据（防止未点保存按钮就关闭窗口）
        if hasattr(self, '_sell_items_meta'):
            self._save_sell_items_meta()
        # 移除全局滚轮绑定
        self.win.unbind_all("<MouseWheel>")
        # 移除所有 trace 回调
        for var, trace_id in self._trace_ids:
            try:
                var.trace_remove('write', trace_id)
            except Exception:
                pass
        self._trace_ids.clear()
        self.win.destroy()

    def _setup_styles(self):
        style = ttk.Style()
        # 浅色主题（参考 themes/light.qss）
        style.configure('Settings.TFrame', background='#ffffff')
        style.configure('SettingsCard.TLabelframe', background='#ffffff', foreground='#333333',
                        bordercolor='#e0e0e0', lightcolor='#e0e0e0', darkcolor='#e0e0e0',
                        relief='solid', borderwidth=1)
        style.configure('SettingsCard.TLabelframe.Label', background='#ffffff', foreground='#2c3e50',
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.configure('SettingsInner.TFrame', background='#ffffff')
        style.configure('Settings.TLabel', background='#ffffff', foreground='#333333',
                        font=('Microsoft YaHei UI', 9))
        style.configure('SettingsSmall.TLabel', background='#ffffff', foreground='#666666',
                        font=('Microsoft YaHei UI', 8))
        # 滑块样式（确保可拖动，增大滑块区域）
        style.configure('TScale', background='#ffffff', troughcolor='#f5f5f5',
                        bordercolor='#e0e0e0', lightcolor='#0078d4', darkcolor='#0078d4',
                        sliderlength=20, sliderrelief='raised')

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

        def _on_canvas_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)
        inner_frame.bind("<Enter>", _on_enter)
        inner_frame.bind("<Leave>", _on_leave)
        canvas.bind("<MouseWheel>", _on_canvas_mousewheel)
        inner_frame.bind("<MouseWheel>", _on_canvas_mousewheel)

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
                   command=self._on_close, width=10).pack(side=tk.LEFT)

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

        # ----- Tab 4: 邮件通知 -----
        email_tab_outer = ttk.Frame(notebook, style='Settings.TFrame')
        notebook.add(email_tab_outer, text="  邮件通知  ")
        email_tab = self._create_scrollable_tab(email_tab_outer)
        self._build_email_tab(email_tab)

        # ----- Tab 5: 其他设置 -----
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
        self._trace_ids.append((self.confidence_var, self.confidence_var.trace_add('write', on_scale_change)))

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
        btn_row = ttk.Frame(guide_frame, style='SettingsInner.TFrame')
        btn_row.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_row, text="查看使用说明", style='Accent.TButton',
                   command=lambda: account_manager.show_help(self.app), width=14).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="开发者测试", style='TButton',
                   command=self._open_dev_test_window, width=12).pack(side=tk.LEFT)

    def _build_auto_tab(self, parent):
        """自动任务设置选项卡内容（冷却执行模式）"""
        # ----- 冷却执行 -----
        cooldown_frame = ttk.LabelFrame(parent, text="  冷却执行  ", style='SettingsCard.TLabelframe', padding=10)
        cooldown_frame.pack(fill=tk.X, pady=(0, 8))

        cd_row1 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(cd_row1, text="启用账号冷却（每次运行完成后进入冷却期）",
                       variable=self.cooldown_enable_var).pack(side=tk.LEFT, padx=5, pady=5)

        cd_row2 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row2.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(cd_row2, text="冷却小时数：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(5, 4))
        ttk.Spinbox(cd_row2, from_=1, to=24, increment=1,
                    textvariable=self.cooldown_hours_var, width=6).pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(cd_row2, text="账号间隔时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(cd_row2, from_=0, to=5, increment=1,
                    textvariable=self.cooldown_delay_var, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(cd_row2, text="分钟", style='Settings.TLabel').pack(side=tk.LEFT)

        cd_row3 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row3.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(cd_row3, text="冷却完立即运行（冷却结束后自动执行任务）",
                       variable=self.cooldown_run_immediately_var).pack(side=tk.LEFT, padx=5, pady=5)

        cd_row4 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row4.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(cd_row4, text="定时任务兜底（冷却到期时自动启动程序）",
                       variable=self.cooldown_scheduled_task_var).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Label(cooldown_frame, text="开启后即使程序未运行，冷却到期也会通过系统定时任务自动启动程序执行",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 2))

        cd_row5 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row5.pack(fill=tk.X, pady=(4, 4))
        ttk.Checkbutton(cd_row5, text="Interception 驱动失败时自动重启电脑",
                       variable=self.restart_on_interception_fail_var).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Label(cooldown_frame, text="开启后运行时如果检测到 Interception 驱动不可用，将自动重启电脑重新加载驱动",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 2))

        # ----- 开机自启动 -----
        autostart_frame = ttk.LabelFrame(parent, text="  开机自启动  ", style='SettingsCard.TLabelframe', padding=10)
        autostart_frame.pack(fill=tk.X, pady=(8, 8))

        as_row1 = ttk.Frame(autostart_frame, style='SettingsInner.TFrame')
        as_row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(as_row1, text="开机自启动（登录 Windows 时自动运行）",
                       variable=self.autostart_var).pack(side=tk.LEFT, padx=5, pady=5)
        as_row2 = ttk.Frame(autostart_frame, style='SettingsInner.TFrame')
        as_row2.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(as_row2, text="开机后立即运行一次任务（需先开启开机自启动）",
                       variable=self.run_on_startup_var).pack(side=tk.LEFT, padx=5, pady=(0, 5))
        ttk.Label(autostart_frame, text="开启后程序随系统启动时将自动执行一次任务，无需手动操作",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 2))

        # ----- 执行操作选择 -----
        ops_frame = ttk.LabelFrame(parent, text="  执行操作（可多选）  ", style='SettingsCard.TLabelframe', padding=10)
        ops_frame.pack(fill=tk.X, pady=(0, 0))

        ops_inner = ttk.Frame(ops_frame, style='SettingsInner.TFrame')
        ops_inner.pack(fill=tk.X)
        ttk.Checkbutton(ops_inner, text="技术中心", variable=self.op_tech).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(ops_inner, text="工作台", variable=self.op_bench).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(ops_inner, text="防具台", variable=self.op_armor).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(ops_inner, text="制药台", variable=self.op_pharmacy).pack(side=tk.LEFT)


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
        """发送测试邮件（异步，不阻塞 UI 线程）"""
        sender = self.sender_email_var.get().strip()
        code = self.smtp_code_var.get().strip()
        receiver = self.receiver_email_var.get().strip()

        if not sender or not code or not receiver:
            messagebox.showwarning("提示", "请先填写完整的邮箱配置信息")
            return

        self.email_test_label.config(text="正在发送...", foreground="#f39c12")

        def _send():
            import utils
            success, msg = utils.send_email_notification(
                code, sender, receiver,
                "三角洲自动化工具 - 测试邮件",
                "<h3>测试邮件</h3><p>如果您收到此邮件，说明邮件通知功能配置成功！</p>"
            )
            self.win.after(0, lambda: self._on_test_email_result(success, msg))

        import threading
        threading.Thread(target=_send, daemon=True).start()

    def _on_test_email_result(self, success, msg):
        """测试邮件发送结果回调（UI 线程）"""
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
        # 异步加载指纹（避免阻塞 UI）
        def _load_fingerprint():
            try:
                import machine_fingerprint
                info = machine_fingerprint.get_machine_info()
                self.win.after(0, self._fingerprint_var.set, info["machine_id"])
            except Exception:
                self.win.after(0, self._fingerprint_var.set, "获取失败")
        import threading
        threading.Thread(target=_load_fingerprint, daemon=True).start()

        # ----- 自动关机 -----
        frame_shutdown = ttk.LabelFrame(parent, text="  自动关机  ", style='SettingsCard.TLabelframe', padding=12)
        frame_shutdown.pack(fill=tk.X, pady=(0, 8))

        fs1 = ttk.Frame(frame_shutdown, style='SettingsInner.TFrame')
        fs1.pack(fill=tk.X)
        ttk.Checkbutton(fs1, text="启用自动关机",
                       variable=self.shutdown_enable_var).pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(fs1, text="关机时间：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(fs1, textvariable=self.shutdown_time_var, width=8).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(fs1, text="(HH:MM)", style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        ttk.Label(frame_shutdown, text="到达设定时间后系统将自动关机（任务运行中会等待完成后执行）",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(4, 0))

        # ----- 运行完成后延迟关机 -----
        frame_post = ttk.LabelFrame(parent, text="  运行完成后关机  ", style='SettingsCard.TLabelframe', padding=12)
        frame_post.pack(fill=tk.X, pady=(0, 8))

        fp1 = ttk.Frame(frame_post, style='SettingsInner.TFrame')
        fp1.pack(fill=tk.X)
        ttk.Label(fp1, text="所有账号运行完成后延迟关机：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        ttk.Spinbox(fp1, from_=0, to=5, increment=1,
                    textvariable=self.post_run_shutdown_delay_var, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(fp1, text="分钟", style='Settings.TLabel').pack(side=tk.LEFT)

        ttk.Label(frame_post, text="所有账号处理完毕后，按设定延迟时间自动关机（0表示不关机）",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(4, 0))

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

    def _open_dev_test_window(self):
        """打开开发者测试独立窗口"""
        win = tk.Toplevel(self.win)
        win.title("开发者测试")
        win.resizable(True, True)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)

        # 恢复窗口大小 + 关闭时自动保存
        utils.bind_window_geometry(win, "dev_test_geometry", "500x600")

        # 滚动容器
        canvas = tk.Canvas(win, highlightthickness=0, bg='#ffffff')
        scrollbar = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        inner_frame = ttk.Frame(canvas)
        inner_frame_id = canvas.create_window((0, 0), window=inner_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(event):
            canvas.itemconfig(inner_frame_id, width=event.width)
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.bind("<MouseWheel>", _on_mousewheel)
        inner_frame.bind("<MouseWheel>", _on_mousewheel)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 保存当前状态标签引用
        self._dev_win = win
        self._build_dev_test_tab(inner_frame)

    def _build_dev_test_tab(self, parent):
        """开发者测试内容"""
        # ----- 账号登录测试 -----
        frame_login = ttk.LabelFrame(parent, text="  账号登录测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_login.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_login, text="测试 WeGame 直接登录流程（输入游戏账号名称）",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        login_btn_frame = ttk.Frame(frame_login, style='SettingsInner.TFrame')
        login_btn_frame.pack(fill=tk.X)

        self._dev_login_account_var = tk.StringVar()
        ttk.Label(login_btn_frame, text="游戏账号：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(login_btn_frame, textvariable=self._dev_login_account_var, width=20).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(login_btn_frame, text="测试登录", style='TButton',
                   command=self._test_account_login, width=10).pack(side=tk.LEFT)

        self._dev_login_status = ttk.Label(frame_login, text="", style='SettingsSmall.TLabel')
        self._dev_login_status.pack(anchor=tk.W, padx=5, pady=(4, 0))

        # ----- 驱动键盘测试 -----
        frame_kb = ttk.LabelFrame(parent, text="  驱动键盘测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_kb.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_kb, text="测试 Interception 驱动级键盘",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        kb_btn_frame = ttk.Frame(frame_kb, style='SettingsInner.TFrame')
        kb_btn_frame.pack(fill=tk.X)

        ttk.Button(kb_btn_frame, text="检测键盘状态", style='TButton',
                   command=self._test_ola_status, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(kb_btn_frame, text="测试 Interception", style='TButton',
                   command=self._test_interception_input, width=16).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(kb_btn_frame, text="测试输入", style='TButton',
                   command=self._test_keyboard_input, width=10).pack(side=tk.LEFT)

        self._dev_kb_status = ttk.Label(frame_kb, text="", style='SettingsSmall.TLabel')
        self._dev_kb_status.pack(anchor=tk.W, padx=5, pady=(4, 0))

        # ----- 进程清理测试 -----
        frame_proc = ttk.LabelFrame(parent, text="  进程清理测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_proc.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_proc, text="测试进程清理功能",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        proc_btn_frame = ttk.Frame(frame_proc, style='SettingsInner.TFrame')
        proc_btn_frame.pack(fill=tk.X)

        ttk.Button(proc_btn_frame, text="清理 WeGame", style='TButton',
                   command=lambda: self._test_kill_process("WeGame"), width=12).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(proc_btn_frame, text="清理三角洲", style='TButton',
                   command=lambda: self._test_kill_process("DeltaForce"), width=12).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(proc_btn_frame, text="清理全部", style='TButton',
                   command=self._test_kill_all, width=10).pack(side=tk.LEFT)

        self._dev_proc_status = ttk.Label(frame_proc, text="", style='SettingsSmall.TLabel')
        self._dev_proc_status.pack(anchor=tk.W, padx=5, pady=(4, 0))

        # ----- 窗口查找测试 -----
        frame_win = ttk.LabelFrame(parent, text="  窗口查找测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_win.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_win, text="测试窗口查找功能",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        win_btn_frame = ttk.Frame(frame_win, style='SettingsInner.TFrame')
        win_btn_frame.pack(fill=tk.X)

        ttk.Button(win_btn_frame, text="查找 WeGame 窗口", style='TButton',
                   command=lambda: self._test_find_window("WeGame"), width=16).pack(side=tk.LEFT, padx=(0, 4))

        self._dev_win_status = ttk.Label(frame_win, text="", style='SettingsSmall.TLabel')
        self._dev_win_status.pack(anchor=tk.W, padx=5, pady=(4, 0))

        # ----- 文本识别测试 -----
        frame_ocr = ttk.LabelFrame(parent, text="  文本识别测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_ocr.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_ocr, text="测试 OCR 能否识别屏幕上的目标文字（需先启用全局文本配置）",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        ocr_btn_frame = ttk.Frame(frame_ocr, style='SettingsInner.TFrame')
        ocr_btn_frame.pack(fill=tk.X)

        ttk.Button(ocr_btn_frame, text="打开文本识别测试", style='TButton',
                   command=self._open_ocr_test_window, width=18).pack(side=tk.LEFT)

        self._dev_ocr_status = ttk.Label(frame_ocr, text="", style='SettingsSmall.TLabel')
        self._dev_ocr_status.pack(anchor=tk.W, padx=5, pady=(4, 0))

        # ----- 图片识别置信度测试 -----
        frame_conf = ttk.LabelFrame(parent, text="  图片识别置信度测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_conf.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_conf, text="点击模板名称，在屏幕上识别并返回置信度（匹配当前设置的置信度）",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        ttk.Button(frame_conf, text="打开置信度测试窗口", style='TButton',
                   command=self._open_confidence_test_window, width=20).pack(anchor=tk.W, padx=5)

    def _open_confidence_test_window(self):
        """打开图片识别置信度测试窗口"""
        import config as cfg
        win = tk.Toplevel(self.win)
        win.title("图片识别置信度测试")
        win.resizable(True, True)
        win.minsize(400, 300)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)
        utils.restore_window_geometry(win, "confidence_test_geometry", "500x600", (400, 300))

        # 标题
        ttk.Label(win, text="点击模板名称，识别屏幕并返回置信度",
                  font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=(10, 5))
        ttk.Label(win, text=f"当前匹配置信度：{self.confidence_var.get():.2f}",
                  font=('Microsoft YaHei UI', 9), foreground='#666').pack(pady=(0, 5))

        # 结果显示
        result_var = tk.StringVar(value="等待测试...")
        result_label = ttk.Label(win, textvariable=result_var,
                                font=('Consolas', 10), foreground='#333')
        result_label.pack(pady=(0, 10))

        # 滚动区域
        canvas = tk.Canvas(win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 分组
        section_headers = {
            "Produce_TechCenter": "产出项",
            "DELTA_GAME_ICON": "WeGame 登录",
            "Hazard_Operations": "游戏内导航",
            "Tech_Center": "设施操作",
            "MAKE": "制造操作",
            "Warehouse": "一键出售",
            "EMAIL_MAIL": "邮箱货币",
        }

        def _test_template(var_name, rel_path, name, btn):
            """测试单个模板的识别置信度"""
            import cv2
            import numpy as np
            btn.config(state='disabled')
            result_var.set(f"正在识别: {name}...")
            win.update_idletasks()

            try:
                # 截取全屏
                screen = utils._screenshot_gray()
                if screen is None:
                    result_var.set("截图失败")
                    btn.config(state='normal')
                    return

                # 加载模板
                template = utils._imread_unicode(config.resolve_template_path(rel_path))
                if template is None:
                    result_var.set(f"模板加载失败: {rel_path}")
                    btn.config(state='normal')
                    return

                # 转灰度
                if len(template.shape) == 3:
                    template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

                # 匹配
                confidence = float(self.confidence_var.get())
                result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

                h, w = template.shape[:2]
                if max_val >= confidence:
                    result_var.set(f"✅ {name}: 置信度 {max_val:.4f} (阈值 {confidence:.2f}) 坐标({max_loc[0]},{max_loc[1]})")
                    result_label.config(foreground='#27ae60')
                else:
                    result_var.set(f"❌ {name}: 置信度 {max_val:.4f} (阈值 {confidence:.2f}) 未达标")
                    result_label.config(foreground='#e74c3c')
            except Exception as e:
                result_var.set(f"错误: {e}")
                result_label.config(foreground='#e74c3c')
            finally:
                btn.config(state='normal')

        seq_num = 0
        for var_name, rel_path, name, hint in cfg.TEMPLATE_CAPTURE_LIST:
            if var_name in section_headers:
                hdr = ttk.Frame(inner)
                hdr.pack(fill=tk.X, pady=(8, 2), padx=5)
                ttk.Label(hdr, text=section_headers[var_name],
                         font=('Microsoft YaHei UI', 9, 'bold'), foreground='#2c3e50').pack(side=tk.LEFT)
                ttk.Separator(inner, orient='horizontal').pack(fill=tk.X, padx=5, pady=(0, 2))

            seq_num += 1
            row = ttk.Frame(inner)
            row.pack(fill=tk.X, padx=5, pady=1)

            ttk.Label(row, text=f"{seq_num}.", width=3, foreground='#999').pack(side=tk.LEFT)
            btn = ttk.Button(row, text=name, width=25,
                           command=lambda v=var_name, r=rel_path, n=name, b=None: _test_template(v, r, n, b))
            # 需要在创建后绑定自身引用
            btn.configure(command=lambda v=var_name, r=rel_path, n=name, b=btn: _test_template(v, r, n, b))
            btn.pack(side=tk.LEFT, padx=(0, 5))
            ttk.Label(row, text=hint, font=('Microsoft YaHei UI', 8), foreground='#999').pack(side=tk.LEFT)

        # 关闭时清理
        def _on_close():
            utils.save_window_geometry(win, "confidence_test_geometry")
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_close)

    def _test_account_login(self):
        """测试账号登录流程（WeGame 直接登录）"""
        game_account = self._dev_login_account_var.get().strip()
        if not game_account:
            self._dev_login_status.config(text="请输入游戏账号名称", foreground="#e74c3c")
            return

        # 检查备注中是否有该账号
        note_data = self.app._account_notes.get(game_account, {})
        if isinstance(note_data, dict):
            login_account = note_data.get("account", "").strip()
        else:
            login_account = ""

        if not login_account:
            self._dev_login_status.config(text=f"游戏账号 {game_account} 未找到或未设置", foreground="#e74c3c")
            return

        self._dev_login_status.config(text=f"正在测试 WeGame 登录 {game_account}...", foreground="#3498db")
        self.win.update()

        # 在新线程中执行测试
        import threading
        def _run_test():
            try:
                import automation_runner
                result = automation_runner._login_account(self.app, game_account, 0, 1, [])
                if result:
                    self.win.after(0, lambda: self._dev_login_status.config(
                        text=f"✓ WeGame 登录测试成功！", foreground="#27ae60"))
                else:
                    self.win.after(0, lambda: self._dev_login_status.config(
                        text=f"✗ WeGame 登录测试失败", foreground="#e74c3c"))
            except Exception as e:
                self.win.after(0, lambda: self._dev_login_status.config(
                    text=f"✗ 测试异常: {e}", foreground="#e74c3c"))

        threading.Thread(target=_run_test, daemon=True).start()

    def _test_ola_status(self):
        """测试 Interception 驱动键盘状态"""
        try:
            import interception_keyboard
            inter_ok = interception_keyboard.is_available()
            if inter_ok:
                self._dev_kb_status.config(
                    text="Interception ✓ | 驱动可用",
                    foreground="#27ae60")
            else:
                self._dev_kb_status.config(
                    text="Interception ✗ | 驱动不可用",
                    foreground="#e74c3c")
        except Exception as e:
            self._dev_kb_status.config(text=f"✗ 检测异常: {e}", foreground="#e74c3c")

    def _test_keyboard_input(self):
        """测试键盘输入"""
        self._dev_kb_status.config(text="正在测试键盘输入...", foreground="#3498db")
        self.win.update()

        import threading
        def _run_test():
            try:
                import driver_keyboard
                import pyautogui
                # 提示用户将焦点放到目标窗口
                self.win.after(0, lambda: self._dev_kb_status.config(
                    text="3秒后开始输入测试，请将焦点放到目标窗口...", foreground="#3498db"))
                time.sleep(3)
                pyautogui.typewrite("test123", interval=0.05)
                self.win.after(0, lambda: self._dev_kb_status.config(
                    text="✓ 键盘输入测试完成", foreground="#27ae60"))
            except Exception as e:
                self.win.after(0, lambda: self._dev_kb_status.config(
                    text=f"✗ 测试异常: {e}", foreground="#e74c3c"))

        threading.Thread(target=_run_test, daemon=True).start()

    def _test_interception_input(self):
        """测试 Interception 驱动级键盘输入"""
        import interception_keyboard
        if not interception_keyboard.is_available():
            self._dev_kb_status.config(
                text="✗ Interception 不可用，请安装 Interception 驱动并确保驱动正常运行",
                foreground="#e74c3c")
            return

        self._dev_kb_status.config(text="请在3秒内将焦点放到目标窗口（如记事本）...", foreground="#3498db")

        def _do_test():
            try:
                self._dev_kb_status.config(text="正在发送 Interception 按键...", foreground="#3498db")
                self.win.update()

                test_text = "test123abc"
                result = interception_keyboard.send_string(test_text, interval=0.03)
                if result:
                    self._dev_kb_status.config(
                        text=f"✓ Interception 输入完成: '{test_text}'", foreground="#27ae60")
                else:
                    self._dev_kb_status.config(
                        text="✗ Interception 输入失败", foreground="#e74c3c")
            except Exception as e:
                self._dev_kb_status.config(
                    text=f"✗ 测试异常: {e}", foreground="#e74c3c")

        # 3秒后执行测试（在主线程上，避免 threading + after 的兼容性问题）
        self.win.after(3000, _do_test)

    def _test_kill_process(self, process_name):
        """测试清理指定进程"""
        process_map = {
            "WeGame": config.WEGAME_PROCESS,
            "DeltaForce": config.DELTA_PROCESS,
        }

        proc = process_map.get(process_name)
        if not proc:
            self._dev_proc_status.config(text=f"未知进程: {process_name}", foreground="#e74c3c")
            return

        self._dev_proc_status.config(text=f"正在清理 {process_name}...", foreground="#3498db")

        import threading
        def _run():
            try:
                utils.kill_process(proc, wait_exit=True, max_wait=5)
                self.win.after(0, lambda: self._dev_proc_status.config(
                    text=f"✓ {process_name} 已清理", foreground="#27ae60"))
            except Exception as e:
                self.win.after(0, lambda: self._dev_proc_status.config(
                    text=f"✗ 清理失败: {e}", foreground="#e74c3c"))

        threading.Thread(target=_run, daemon=True).start()

    def _test_kill_all(self):
        """测试清理所有进程"""
        self._dev_proc_status.config(text="正在清理所有进程...", foreground="#3498db")

        import threading
        def _run():
            try:
                utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=5)
                utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=5)
                utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=5)
                self.win.after(0, lambda: self._dev_proc_status.config(
                    text="✓ 所有进程已清理", foreground="#27ae60"))
            except Exception as e:
                self.win.after(0, lambda: self._dev_proc_status.config(
                    text=f"✗ 清理失败: {e}", foreground="#e74c3c"))

        threading.Thread(target=_run, daemon=True).start()

    def _test_find_window(self, window_name):
        """测试窗口查找"""
        import utils

        self._dev_win_status.config(text=f"正在查找 {window_name} 窗口...", foreground="#3498db")
        self.win.update()

        try:
            hwnd = utils.find_window_by_title(window_name)
            if hwnd:
                self._dev_win_status.config(
                    text=f"✓ 找到 {window_name} 窗口 (hwnd={hwnd})", foreground="#27ae60")
            else:
                self._dev_win_status.config(
                    text=f"✗ 未找到 {window_name} 窗口", foreground="#e74c3c")
        except Exception as e:
            self._dev_win_status.config(text=f"✗ 查找异常: {e}", foreground="#e74c3c")

    def _open_ocr_test_window(self):
        """打开文本识别测试窗口：显示所有可识别文字，点击测试 OCR"""
        import threading
        import config as cfg
        from template_capture import GLOBAL_TEXT_DEFAULTS

        # 收集可识别的文字项（default_text 不为 None）
        items = []
        for var_name, (display_name, default_text) in GLOBAL_TEXT_DEFAULTS.items():
            if default_text is not None:
                items.append((var_name, display_name, default_text))

        win = tk.Toplevel(self.win)
        win.title("文本识别测试")
        win.resizable(True, True)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)

        # 恢复窗口大小 + 关闭时自动保存
        utils.bind_window_geometry(win, "ocr_test_geometry", "700x500")

        # 标题说明
        ttk.Label(win, text="点击按钮 → OCR 识别屏幕上的文字 → 鼠标移动并点击 → 按钮变绿色",
                  font=('Microsoft YaHei UI', 10)).pack(padx=15, pady=(12, 5), anchor='w')
        ttk.Label(win, text="识别成功变绿色（显示坐标），失败变红色。鼠标会实际移动到文字位置并点击。",
                  font=('Microsoft YaHei UI', 9), foreground='#888').pack(padx=15, pady=(0, 8), anchor='w')

        # 滚动区域
        container = ttk.Frame(win)
        container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 按钮样式
        style = ttk.Style()
        style.configure('OCR_Default.TButton', font=('Microsoft YaHei UI', 10))
        style.configure('OCR_Green.TButton', font=('Microsoft YaHei UI', 10), background='#4caf50')
        style.configure('OCR_Red.TButton', font=('Microsoft YaHei UI', 10), background='#f44336')

        # 使用 tk.Button 以支持 bg 颜色变化
        buttons = {}
        cols = 3
        for i, (var_name, display_name, default_text) in enumerate(items):
            row, col = divmod(i, cols)
            btn_text = f"{display_name}\n({default_text})"
            btn = tk.Button(scroll_frame, text=btn_text, font=('Microsoft YaHei UI', 10),
                           width=20, height=2, relief='raised', bd=1)
            btn.grid(row=row, column=col, padx=4, pady=4, sticky='nsew')
            buttons[var_name] = btn

        # 配置列权重
        for c in range(cols):
            scroll_frame.columnconfigure(c, weight=1)

        # 底部状态栏
        status_var = tk.StringVar(value="点击按钮测试文字识别")
        status_label = ttk.Label(win, textvariable=status_var, font=('Microsoft YaHei UI', 9))
        status_label.pack(padx=15, pady=(0, 8), anchor='w')

        # 已测试计数
        tested_count = [0]
        total_count = len(items)

        # 测试状态控制：同一时间只运行一个测试
        _test_running = [False]
        _test_done_event = threading.Event()

        def _do_ocr_test(var_name, display_name, default_text):
            """执行一次 OCR 测试（在调用线程中运行，完成后设置事件）"""
            btn = buttons[var_name]
            try:
                time.sleep(0.1)
                # 只扫描测试窗口区域（降低 CPU 占用）
                wx = win.winfo_rootx()
                wy = win.winfo_rooty()
                ww = win.winfo_width()
                wh = win.winfo_height()
                results = utils.ocr_recognize(region=(wx, wy, ww, wh))
                click_x, click_y = None, None
                for recognized_text, recognized_conf, bbox in results:
                    if default_text in recognized_text:
                        click_x = int((bbox[0] + bbox[2]) / 2)
                        click_y = int((bbox[1] + bbox[3]) / 2)
                        break

                if click_x is not None:
                    import pyautogui
                    utils.smooth_move_to(click_x, click_y, duration=0.2)
                    pyautogui.click()
                    tested_count[0] += 1
                    win.after(0, lambda: btn.config(bg='#4caf50', fg='white'))
                    win.after(0, lambda: status_var.set(
                        f"[{tested_count[0]}/{total_count}] ✓ {display_name} 识别并点击成功 ({click_x},{click_y})"))
                else:
                    tested_count[0] += 1
                    win.after(0, lambda: btn.config(bg='#f44336', fg='white'))
                    win.after(0, lambda: status_var.set(
                        f"[{tested_count[0]}/{total_count}] ✗ {display_name} 未识别到"))
            except Exception as e:
                tested_count[0] += 1
                win.after(0, lambda: btn.config(bg='#ff9800', fg='white'))
                win.after(0, lambda: status_var.set(f"✗ {display_name} 测试异常: {e}"))
            finally:
                _test_running[0] = False
                _test_done_event.set()

        def _test_one(var_name, display_name, default_text):
            """点击单个按钮测试"""
            if _test_running[0]:
                return
            _test_running[0] = True
            _test_done_event.clear()
            status_var.set(f"正在识别: {display_name} ({default_text})...")
            win.update()
            threading.Thread(target=_do_ocr_test, args=(var_name, display_name, default_text), daemon=True).start()

        # 绑定点击事件
        for var_name, display_name, default_text in items:
            buttons[var_name].config(
                command=lambda vn=var_name, dn=display_name, dt=default_text: _test_one(vn, dn, dt))

        # 底部按钮栏
        btn_bar = ttk.Frame(win)
        btn_bar.pack(fill=tk.X, padx=15, pady=(0, 10))

        def _test_all():
            """先重置，再依次识别并点击每个文字（串行，一个完成后再启动下一个）"""
            if _test_running[0]:
                return
            for btn in buttons.values():
                btn.config(bg='SystemButtonFace', fg='black')
            tested_count[0] = 0
            status_var.set("开始全部测试...")

            def _run():
                for var_name, display_name, default_text in items:
                    _test_running[0] = True
                    _test_done_event.clear()
                    win.after(0, lambda dn=display_name, dt=default_text: status_var.set(f"正在识别: {dn} ({dt})..."))
                    _do_ocr_test(var_name, display_name, default_text)
                    # _do_ocr_test 完成后会设置 _test_done_event
                    time.sleep(0.2)  # 测试间隔

            threading.Thread(target=_run, daemon=True).start()

        def _reset_all():
            """重置所有按钮颜色"""
            tested_count[0] = 0
            for btn in buttons.values():
                btn.config(bg='SystemButtonFace', fg='black')
            status_var.set("已重置")

        ttk.Button(btn_bar, text="全部测试", command=_test_all, width=10).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_bar, text="重置", command=_reset_all, width=8).pack(side=tk.LEFT)

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
        self._trace_ids.append((self.sell_confidence_var, self.sell_confidence_var.trace_add('write', on_sell_conf_change)))

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
        """添加售卖物品图片（支持多选，自动跳过重复）"""
        filetypes = [("图片文件", "*.png;*.jpg;*.jpeg;*.bmp"), ("所有文件", "*.*")]
        sources = filedialog.askopenfilenames(title="选择售卖物品图片（可多选）", filetypes=filetypes)
        if not sources:
            return
        os.makedirs(config.SELL_ITEMS_DIR, exist_ok=True)
        existing_filenames = {i["filename"] for i in self._sell_items_meta.get("items", [])}
        added = 0
        skipped = 0
        for src in sources:
            try:
                basename = os.path.basename(src)
                name, ext = os.path.splitext(basename)
                save_path = os.path.join(config.SELL_ITEMS_DIR, basename)
                counter = 1
                while os.path.exists(save_path):
                    save_path = os.path.join(config.SELL_ITEMS_DIR, f"{name}_{counter}{ext}")
                    counter += 1
                saved_name = os.path.basename(save_path)
                if saved_name in existing_filenames:
                    skipped += 1
                    continue
                with open(src, "rb") as f_in, open(save_path, "wb") as f_out:
                    f_out.write(f_in.read())
                self._sell_items_meta.setdefault("items", []).append({
                    "filename": saved_name,
                    "name": os.path.splitext(saved_name)[0],
                    "discount_times": 0,
                    "quantity": 1
                })
                existing_filenames.add(saved_name)
                added += 1
            except Exception:
                pass
        self._refresh_sell_treeview()
        if added > 0:
            self._save_sell_items_meta()
        msg = f"成功添加 {added} 个物品。"
        if skipped:
            msg += f"\n跳过 {skipped} 个重复物品。"
        if added == 0 and skipped == 0:
            msg = "未添加任何物品。"
        messagebox.showinfo("添加结果", msg)

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
        self._save_sell_items_meta()

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
        self._save_sell_items_meta()
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
                self._save_sell_items_meta()

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
                self._save_sell_items_meta()

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
        self.win.after(300, self._show_asset_overlay)

    def _show_asset_overlay(self):
        """显示资产区域选择覆盖层（在 withdraw 后异步调用）"""
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
            region = ast.literal_eval(region_str)
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

            # 最小化设置窗口，异步执行截图和 OCR
            self.win.withdraw()
            self.win.after(500, lambda: self._do_asset_ocr(region))

        except SyntaxError:
            messagebox.showerror("错误", "区域格式不正确，应为 [x, y, w, h]", parent=self.win)
        except Exception as e:
            self.win.deiconify()
            messagebox.showerror("测试失败", f"识别出错：{e}", parent=self.win)

    def _do_asset_ocr(self, region):
        """执行资产 OCR 识别（在 withdraw 后异步调用）"""
        try:
            import pyautogui
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR

            x, y, w, h = region
            screenshot = pyautogui.screenshot(region=(x, y, w, h))
            img_array = np.array(screenshot)
            screenshot.close()

            if not hasattr(self, '_ocr_instance'):
                self._ocr_instance = RapidOCR()
            result, _ = self._ocr_instance(img_array)

            self.win.deiconify()

            if not result:
                messagebox.showinfo("测试结果",
                    f"识别区域：({x}, {y}) - {w}x{h}\n\n"
                    "识别结果：未检测到文字",
                    parent=self.win)
                return

            # 拼接所有识别到的文本
            all_text = "".join(item[1] for item in result)

            # 匹配资产格式：数字（含逗号分隔）+K/M/B（过滤"现有资产"等无效文字）
            match = re.search(r'([\d,]+\.?\d*)\s*([KMBkmb])', all_text)
            if match:
                asset_str = f"{match.group(1)}{match.group(2).upper()}"
            else:
                # 降级：清理非数字/KMB字符后重试
                cleaned = re.sub(r'[^0-9,KMBkmb]', '', all_text)
                match2 = re.search(r'([\d,]+\.?\d*)\s*([KMBkmb])', cleaned)
                if match2:
                    asset_str = f"{match2.group(1)}{match2.group(2).upper()}"
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
            self.win.deiconify()
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
        # 从磁盘加载最新设置，避免覆盖其他模块（如模板向导）保存的 OCR 配置
        fresh = config.load_settings()

        # 全局设置
        fresh["wegame_path"] = self.wegame_var.get()
        fresh["delta_path"] = self.delta_var.get()
        fresh["confidence"] = round(self.confidence_var.get(), 2)
        fresh["log_save_path"] = self.log_var.get()
        self._set_autostart(self.autostart_var.get(), self.run_on_startup_var.get())
        fresh["run_on_startup"] = self.run_on_startup_var.get()

        # 冷却执行设置
        fresh["cooldown_run_immediately"] = self.cooldown_run_immediately_var.get()
        fresh["cooldown_scheduled_task_enabled"] = self.cooldown_scheduled_task_var.get()
        fresh["restart_on_interception_fail"] = self.restart_on_interception_fail_var.get()

        # 如果关闭了定时任务兜底，删除已有的定时任务
        if not self.cooldown_scheduled_task_var.get():
            try:
                utils.remove_cooldown_scheduled_task()
            except Exception:
                pass

        # 执行操作
        ops = []
        if self.op_tech.get(): ops.append("tech_center")
        if self.op_bench.get(): ops.append("tool_bench")
        if self.op_armor.get(): ops.append("armor_station")
        if self.op_pharmacy.get(): ops.append("pharmacy_station")
        fresh["selected_operations"] = ops

        # 自动关机
        fresh["auto_shutdown_enabled"] = self.shutdown_enable_var.get()
        fresh["auto_shutdown_time"] = self.shutdown_time_var.get()
        fresh["post_run_shutdown_delay"] = self.post_run_shutdown_delay_var.get()

        # 邮件通知设置
        fresh["email_enabled"] = self.email_enable_var.get()
        fresh["smtp_code"] = self.smtp_code_var.get()
        fresh["sender_email"] = self.sender_email_var.get()
        fresh["receiver_email"] = self.receiver_email_var.get()
        fresh["cooldown_email_enabled"] = self.cooldown_email_enabled_var.get()

        # 游戏启动等待
        fresh["game_launch_wait"] = self.game_launch_wait_var.get()

        # 一键出售设置
        fresh["enable_sell_after_run"] = self.enable_sell_var.get()
        fresh["sell_confidence"] = round(self.sell_confidence_var.get(), 2)

        # 售卖时间区间
        fresh["sell_time_enabled"] = self.sell_time_enabled_var.get()
        fresh["sell_time_start"] = self.sell_time_start_var.get().strip()
        fresh["sell_time_end"] = self.sell_time_end_var.get().strip()

        # 保存物品元数据
        self._save_sell_items_meta()

        # 邮箱货币设置
        fresh["enable_email_currency"] = self.email_currency_var.get()

        # 资产识别设置
        fresh["enable_asset_recognition"] = self.enable_asset_var.get()
        try:
            region_str = self.asset_region_var.get().strip()
            if region_str:
                region = ast.literal_eval(region_str)
                if isinstance(region, list) and len(region) == 4:
                    fresh["asset_region"] = region
        except Exception:
            pass

        # 冷却管理设置
        fresh["enable_cooldown"] = self.cooldown_enable_var.get()
        fresh["cooldown_hours"] = self.cooldown_hours_var.get()
        fresh["cooldown_delay_minutes"] = self.cooldown_delay_var.get()

        # 滚动量
        fresh["scroll_amount"] = self.scroll_amount_var.get()

        # 保存并同步内存中的设置引用
        config.save_settings(fresh)
        config.APP_SETTINGS.update(fresh)
        config.WEGAME_PATH = fresh.get("wegame_path", "")
        config.CONFIDENCE = fresh["confidence"]
        self.app.update_confidence_display()

        # 应用定时设置
        self.app.apply_auto_settings_from_window()

        messagebox.showinfo("提示", "设置已保存。")
        utils.save_window_geometry(self.win, "settings_window_geometry")
        self.win.destroy()
