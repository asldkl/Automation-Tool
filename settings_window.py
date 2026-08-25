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
        self.cooldown_hours_var = tk.IntVar(value=app.settings.get("cooldown_hours", 8))

        # 自动关机变量
        self.shutdown_enable_var = tk.BooleanVar(value=app.settings.get("auto_shutdown_enabled", False))
        self.shutdown_time_var = tk.StringVar(value=app.settings.get("auto_shutdown_time", "22:00"))
        self.post_run_shutdown_delay_var = tk.IntVar(value=app.settings.get("post_run_shutdown_delay", 0))

        # 账号数据自动备份间隔（天，0=关闭）
        self.account_backup_days_var = tk.IntVar(value=app.settings.get("account_backup_days", 0))

        # 日志/备份保留天数（0=不清理，默认3）
        self.log_retention_days_var = tk.IntVar(value=app.settings.get("log_retention_days", 3))

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
        # 导航返回上一窗口
        utils.nav_pop(self.win)
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

        # ----- 目录及数据（日志/截图/账号备份共用根目录，按日期分「日志」「图片」子文件夹） -----
        frame4 = ttk.LabelFrame(parent, text="  目录及数据  ", style='SettingsCard.TLabelframe', padding=8)
        frame4.pack(fill=tk.X, pady=(0, 8))

        f4 = ttk.Frame(frame4, style='SettingsInner.TFrame')
        f4.pack(fill=tk.X)
        ttk.Label(f4, text="保存路径：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 8))
        log_entry = ttk.Entry(f4, textvariable=self.log_var, width=45)
        log_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 日志/备份保留天数（自动清理）
        ret_row = ttk.Frame(frame4, style='SettingsInner.TFrame')
        ret_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(ret_row, text="日志/备份保留：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(ret_row, from_=0, to=90, increment=1,
                    textvariable=self.log_retention_days_var, width=4).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(ret_row, text="天（0=不清理，自动清理过期数据）",
                  style='SettingsSmall.TLabel').pack(side=tk.LEFT)

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
        ttk.Button(res_frame, text="上传模板图片", style='Accent.TButton',
                   command=self._open_capture_wizard_nav, width=14).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(res_frame, text=res_text, style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 10))

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

        # ----- 点击随机偏移（游戏内操作拟人抖动） -----
        frame_jitter = ttk.LabelFrame(parent, text="  点击随机偏移  ", style='SettingsCard.TLabelframe', padding=12)
        frame_jitter.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_jitter, text="游戏内操作点击位置随机偏移（拟人抖动），减少机械化痕迹",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        jitter_row = ttk.Frame(frame_jitter, style='SettingsInner.TFrame')
        jitter_row.pack(fill=tk.X)

        self._jitter_enabled_var = tk.BooleanVar(value=self.app.settings.get("enable_click_jitter", False))
        ttk.Checkbutton(jitter_row, text="启用随机偏移",
                        variable=self._jitter_enabled_var,
                        command=self._save_jitter_settings).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Label(jitter_row, text="最大偏移(px)：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._jitter_max_var = tk.StringVar(value=str(self.app.settings.get("click_jitter_max", 5)))
        ttk.Entry(jitter_row, textvariable=self._jitter_max_var, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(jitter_row, text="保存", style='TButton',
                   command=self._save_jitter_settings, width=6).pack(side=tk.LEFT)

        # ----- 实用工具 -----
        guide_frame = ttk.LabelFrame(parent, text="  实用工具  ", style='SettingsCard.TLabelframe', padding=12)
        guide_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(guide_frame, text="实验功能：驱动键盘测试、日志遮罩、皮肤抢购",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))
        btn_row = ttk.Frame(guide_frame, style='SettingsInner.TFrame')
        btn_row.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_row, text="实验功能", style='TButton',
                   command=self._open_dev_test_window, width=12).pack(side=tk.LEFT)

    def _build_auto_tab(self, parent):
        """自动任务设置选项卡内容（冷却执行模式）"""
        # ----- 冷却执行 -----
        cooldown_frame = ttk.LabelFrame(parent, text="  冷却执行  ", style='SettingsCard.TLabelframe', padding=10)
        cooldown_frame.pack(fill=tk.X, pady=(0, 8))

        cd_row2 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row2.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(cd_row2, text="冷却小时数：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(5, 4))
        ttk.Spinbox(cd_row2, from_=1, to=24, increment=1,
                    textvariable=self.cooldown_hours_var, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(cd_row2, text="小时", style='Settings.TLabel').pack(side=tk.LEFT)

        cd_row3 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row3.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(cd_row3, text="冷却完立即运行（冷却结束后自动执行任务）",
                       variable=self.cooldown_run_immediately_var).pack(side=tk.LEFT, padx=5, pady=5)

        cd_row4 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row4.pack(fill=tk.X, pady=(0, 4))
        ttk.Checkbutton(cd_row4, text="定时任务兜底（冷却到期时自动启动程序）",
                       variable=self.cooldown_scheduled_task_var).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Label(cooldown_frame, text="开启后程序未运行也会自动启动执行",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 2))

        cd_row5 = ttk.Frame(cooldown_frame, style='SettingsInner.TFrame')
        cd_row5.pack(fill=tk.X, pady=(4, 4))
        ttk.Checkbutton(cd_row5, text="Interception 驱动失败时自动重启电脑",
                       variable=self.restart_on_interception_fail_var).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Label(cooldown_frame, text="驱动不可用时自动重启电脑重新加载",
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

        # ----- 自定义操作 -----
        frame_custom = ttk.LabelFrame(parent, text="  自定义操作  ", style='SettingsCard.TLabelframe', padding=10)
        frame_custom.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(frame_custom,
                  text="主流程完成后自动执行「找图→单击」步骤",
                  style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        ttk.Button(frame_custom, text="配置自定义操作", style='Accent.TButton',
                   command=self._open_custom_ops_window, width=16).pack(anchor=tk.W, padx=5)


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
        tips_label = ttk.Label(tips_frame, text=tips_text, style='SettingsSmall.TLabel',
                 wraplength=500, justify=tk.LEFT)
        tips_label.pack(anchor='w', padx=5, pady=5)

        # 说明文本跟随窗口宽度自动换行
        def _on_tips_resize(event):
            try:
                tips_label.configure(wraplength=max(200, event.width - 10))
            except tk.TclError:
                pass
        tips_frame.bind("<Configure>", _on_tips_resize)

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
                    textvariable=self.game_launch_wait_var, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(f4, text="秒", style='Settings.TLabel').pack(side=tk.LEFT)

        # ----- 账号数据导入导出 -----
        frame_acct = ttk.LabelFrame(parent, text="  账号数据导入导出  ", style='SettingsCard.TLabelframe', padding=12)
        frame_acct.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_acct, text="导入/导出账号列表、密码备注、资产及历史记录",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        acct_btn_frame = ttk.Frame(frame_acct, style='SettingsInner.TFrame')
        acct_btn_frame.pack(fill=tk.X)

        ttk.Button(acct_btn_frame, text="导出账号数据", style='TButton',
                   command=self._export_accounts, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(acct_btn_frame, text="导入账号数据", style='TButton',
                   command=self._import_accounts, width=14).pack(side=tk.LEFT)

        # 自动备份间隔（防崩溃/蓝屏导致账号数据丢失）
        backup_row = ttk.Frame(frame_acct, style='SettingsInner.TFrame')
        backup_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(backup_row, text="自动备份间隔：", style='Settings.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Spinbox(backup_row, from_=0, to=3, increment=1,
                    textvariable=self.account_backup_days_var, width=4).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(backup_row, text="天（0=关闭，每 N 天自动备份数据）",
                  style='SettingsSmall.TLabel').pack(side=tk.LEFT)

        # ----- 设置说明 -----
        tips_frame = ttk.Frame(parent, style='SettingsInner.TFrame')
        tips_frame.pack(fill=tk.X, pady=(0, 0))
        tips_lines = (
            "• 额外等待时间：0-120秒，可增加游戏启动等待，默认0\n"
            "• 账号数据导入导出：导出 JSON 备份；导入会覆盖当前账号数据（导入前自动备份）"
        )
        tips_label = ttk.Label(tips_frame, text=tips_lines, style='SettingsSmall.TLabel', justify=tk.LEFT)
        tips_label.pack(anchor='w', padx=5, pady=5)
        # 说明文本跟随窗口宽度自动换行
        def _on_tips_resize(event):
            try:
                tips_label.configure(wraplength=max(200, event.width - 10))
            except tk.TclError:
                pass
        tips_frame.bind("<Configure>", _on_tips_resize)

    def _open_dev_test_window(self):
        """打开实验功能独立窗口"""
        def _open():
            win = tk.Toplevel(self.win)
            win.title("实验功能")
            win.resizable(True, True)
            win.transient(self.win)
            win.grab_set()
            utils.set_window_icon(win)
            utils.restore_window_geometry(win, "dev_test_geometry", "500x600")
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
            self._dev_win = win

            def _on_dev_test_close():
                utils.save_window_geometry(win, "dev_test_geometry")
                utils.nav_pop(win)

            win.protocol("WM_DELETE_WINDOW", _on_dev_test_close)
            self._build_dev_test_tab(inner_frame)
        utils.nav_push(self.win, _open)

    def _build_dev_test_tab(self, parent):
        """实验功能内容"""
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

        # ----- 日志遮罩开关 -----
        frame_overlay = ttk.LabelFrame(parent, text="  日志遮罩  ", style='SettingsCard.TLabelframe', padding=12)
        frame_overlay.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_overlay, text="PyQt6 透明日志叠加层（鼠标穿透不影响游戏），顶行显示当前运行账号与时长",
                  style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        self._overlay_var = tk.BooleanVar(value=self.app.settings.get("enable_log_overlay", False))
        overlay_row = ttk.Frame(frame_overlay, style='SettingsInner.TFrame')
        overlay_row.pack(fill=tk.X, padx=5, pady=5)
        ttk.Checkbutton(overlay_row, text="启用日志遮罩（默认开启）",
                        variable=self._overlay_var,
                        command=self._toggle_overlay).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(overlay_row, text="更换角落", style='TButton',
                   command=self._cycle_overlay_corner, width=10).pack(side=tk.LEFT)

        # ----- 皮肤抢购 -----
        frame_sniper = ttk.LabelFrame(parent, text="  皮肤抢购  ", style='SettingsCard.TLabelframe', padding=12)
        frame_sniper.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_sniper, text="图片识别查找购买按钮 + 余额检测 + 超时自动停止",
                  style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))
        sniper_btn_frame = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(sniper_btn_frame, text="打开皮肤抢购", style='Accent.TButton',
                   command=lambda: self._open_sniper_window(getattr(self, '_dev_win', None)), width=14).pack(side=tk.LEFT)

        # ----- 测试关闭游戏 -----
        frame_close = ttk.LabelFrame(parent, text="  测试关闭游戏  ", style='SettingsCard.TLabelframe', padding=12)
        frame_close.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_close, text="优雅关闭《三角洲行动》（WM_CLOSE 优先，无效才 Alt+F4）；请先打开游戏再测试",
                  style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))
        close_btn_frame = ttk.Frame(frame_close, style='SettingsInner.TFrame')
        close_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(close_btn_frame, text="关闭三角洲游戏", style='Accent.TButton',
                   command=self._test_close_game, width=16).pack(side=tk.LEFT)

    def _test_close_game(self):
        """测试优雅关闭三角洲游戏（WM_CLOSE 优先，验证蓝屏修复是否生效）"""
        if not messagebox.askyesno("测试关闭游戏",
                "将尝试优雅关闭正在运行的《三角洲行动》（WM_CLOSE 优先，无效才 Alt+F4）。\n\n"
                "请确认游戏已打开、当前无需保存的游戏进度。是否继续？",
                parent=self.win):
            return
        import threading
        threading.Thread(target=self._run_close_game_test, daemon=True).start()
        messagebox.showinfo("已执行", "关闭流程已在后台触发，请观察游戏窗口是否正常关闭、是否蓝屏。",
                            parent=self.win)

    def _run_close_game_test(self):
        """后台执行关闭游戏测试"""
        try:
            import automation_runner
            automation_runner._close_game(self.app)
            print("✅ 测试关闭游戏流程执行完成")
        except Exception as e:
            print(f"⚠️ 测试关闭游戏异常：{e}")

    def _open_custom_ops_window(self):
        """打开自定义操作配置窗口（隐藏设置窗口，返回时恢复）"""
        def _open():
            try:
                from custom_ops_window import CustomOpsWindow
                CustomOpsWindow(self.win, self.app)
            except Exception as e:
                try:
                    self.win.deiconify()
                except Exception:
                    pass
                messagebox.showerror("自定义操作", f"打开窗口失败：{e}", parent=self.win)
        utils.nav_push(self.win, _open)

    def _toggle_overlay(self):
        """切换日志遮罩开关（委托给 App，状态持久化）"""
        try:
            self.app._toggle_log_overlay()
        except Exception as e:
            messagebox.showerror("日志遮罩", f"切换失败：{e}", parent=self.win)
        # 同步复选框状态（若 PyQt6 不可用会失败，恢复原状态）
        self._overlay_var.set(self.app.settings.get("enable_log_overlay", False))

    def _cycle_overlay_corner(self):
        """日志遮罩角落逆时针旋转一次（左下→右下→右上→左上→左下），位置持久化"""
        try:
            idx = self.app._cycle_overlay_corner()
            if idx is not None:
                corners = {0: "左下角", 1: "右下角", 2: "右上角", 3: "左上角"}
                messagebox.showinfo("日志遮罩", f"已切换到 {corners.get(idx, '')}", parent=self.win)
        except Exception as e:
            messagebox.showerror("日志遮罩", f"切换角落失败：{e}", parent=self.win)

    def _save_jitter_settings(self):
        """保存点击随机偏移设置到 settings.json"""
        try:
            max_px = max(0, min(int(self._jitter_max_var.get()), 20))
        except ValueError:
            max_px = 5
        self.app.settings["enable_click_jitter"] = self._jitter_enabled_var.get()
        self.app.settings["click_jitter_max"] = max_px
        config.save_settings(self.app.settings)
        messagebox.showinfo("已保存",
                            f"点击随机偏移：{'开启' if self._jitter_enabled_var.get() else '关闭'}，最大偏移 {max_px}px",
                            parent=self.win)

    def _export_accounts(self):
        """导出账号数据到用户选择的文件"""
        import shutil
        import account_manager
        src = account_manager.ACCOUNTS_JSON_PATH
        if not os.path.exists(src):
            messagebox.showwarning("提示", "当前没有账号数据文件", parent=self.win)
            return
        dest = filedialog.asksaveasfilename(
            parent=self.win, title="导出账号数据",
            defaultextension=".json",
            initialfile=f"accounts_{time.strftime('%Y%m%d_%H%M%S')}.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if not dest:
            return
        try:
            shutil.copy2(src, dest)
            messagebox.showinfo("导出成功", f"账号数据已导出到：\n{dest}", parent=self.win)
        except Exception as e:
            messagebox.showerror("导出失败", f"导出异常：{e}", parent=self.win)

    def _import_accounts(self):
        """从用户选择的文件导入账号数据（覆盖当前数据）"""
        import json
        import account_manager
        src = filedialog.askopenfilename(
            parent=self.win, title="导入账号数据",
            filetypes=[("账号数据文件", "*.json *.bak"), ("JSON 文件", "*.json"), ("所有文件", "*.*")])
        if not src:
            return
        if not messagebox.askyesno(
                "确认导入",
                "导入将覆盖当前所有账号数据，是否继续？",
                parent=self.win):
            return
        try:
            with open(src, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 校验格式
            if not isinstance(data, dict) or "qq" not in data:
                messagebox.showerror("导入失败",
                    "文件格式不正确，不是有效的账号数据文件。\n"
                    "自动备份请选择 accounts.json 开头的文件（如 accounts.json.20260812_0217.bak）；\n"
                    "cooldown.json / settings.json 的备份不能用于导入账号。",
                    parent=self.win)
                return
            # 先备份当前数据
            if os.path.exists(account_manager.ACCOUNTS_JSON_PATH):
                import shutil
                try:
                    shutil.copy2(account_manager.ACCOUNTS_JSON_PATH,
                                 account_manager.ACCOUNTS_JSON_PATH + ".pre_import.bak")
                except Exception:
                    pass
            # 写入新数据
            with open(account_manager.ACCOUNTS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 重新加载到界面
            account_manager.load_accounts(self.app)
            messagebox.showinfo("导入成功",
                                f"已导入 {len(data.get('qq', []))} 个账号",
                                parent=self.win)
        except Exception as e:
            messagebox.showerror("导入失败", f"导入异常：{e}", parent=self.win)

    def _open_sniper_window(self, parent=None):
        """打开皮肤抢购独立窗口（parent 缺省时为设置窗口）"""
        parent = parent or self.win
        win = tk.Toplevel(parent)
        win.title("皮肤抢购")
        win.resizable(True, True)
        win.minsize(480, 350)
        win.transient(parent)
        utils.set_window_icon(win)
        utils.bind_window_geometry(win, "sniper_geometry", "500x400")

        main = ttk.Frame(win, style='Settings.TFrame', padding=15)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="图片识别查找购买按钮 + 余额检测 + 超时自动停止",
                  style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        # 变量区
        s = self.app.settings
        def _sv(key, default):
            return str(s.get(key, default))
        region_var = tk.StringVar(value=_sv("sniper_search_region", "100,100,200,50"))
        balance_var = tk.StringVar(value=_sv("sniper_balance_region", ""))
        balance_threshold_var = tk.StringVar(value=_sv("sniper_balance_threshold", "0"))
        timeout_var = tk.StringVar(value=_sv("sniper_timeout", "30"))

        def _save_sniper_settings():
            self.app.settings["sniper_search_region"] = region_var.get().strip()
            self.app.settings["sniper_balance_region"] = balance_var.get().strip()
            self.app.settings["sniper_balance_threshold"] = balance_threshold_var.get().strip()
            self.app.settings["sniper_timeout"] = timeout_var.get().strip()
            config.save_settings(self.app.settings)

        # 状态标签
        status_label = ttk.Label(main, text="未启动", style='SettingsSmall.TLabel')
        status_label.pack(anchor=tk.W, padx=5, pady=(0, 4))

        # 按钮行
        r1 = ttk.Frame(main, style='SettingsInner.TFrame')
        r1.pack(fill=tk.X, padx=5, pady=2)

        # 引用容器（方便在闭包中修改）
        sniper_ref = [None]

        def sniper_start():
            if sniper_ref[0] is None:
                from skin_sniper import SkinSniper
                sniper_ref[0] = SkinSniper()
            s = sniper_ref[0]
            try:
                region = eval(region_var.get().strip())
                if isinstance(region, (list, tuple)) and len(region) == 4:
                    s.search_region = tuple(region)
            except Exception:
                pass
            s.set_callbacks(
                status_cb=lambda st: win.after(0, lambda: status_label.config(text=st)),
            )
            s.start()
            status_label.config(text="启动中...", foreground="#3498db")

        def sniper_stop():
            if sniper_ref[0]:
                sniper_ref[0].stop()
            status_label.config(text="已停止", foreground="#e74c3c")

        def set_region(target):
            overlay = tk.Toplevel(win)
            overlay.attributes('-fullscreen', True)
            overlay.attributes('-alpha', 0.3)
            overlay.attributes('-topmost', True)
            overlay.configure(bg='black')
            overlay.config(cursor="crosshair")
            cv = tk.Canvas(overlay, highlightthickness=0, bg='black')
            cv.pack(fill=tk.BOTH, expand=True)
            hint = tk.Label(overlay, text="请拖动鼠标框选识别区域，按 Esc 取消",
                            font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
            hint.place(relx=0.5, rely=0.05, anchor='center')
            rect_id = [None]; start_x = [0]; start_y = [0]; result = [None]

            def on_press(e):
                start_x[0], start_y[0] = e.x, e.y
                if rect_id[0]: cv.delete(rect_id[0])
                rect_id[0] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline='red', width=2)
            def on_drag(e):
                if rect_id[0]:
                    cv.coords(rect_id[0], start_x[0], start_y[0], e.x, e.y)
            def on_release(e):
                x1, y1, x2, y2 = start_x[0], start_y[0], e.x, e.y
                x, y = min(x1, x2), min(y1, y2)
                w, h = abs(x2 - x1), abs(y2 - y1)
                if w > 5 and h > 5:
                    result[0] = (x, y, w, h)
                overlay.destroy()
            def on_key(e):
                if e.keysym == 'Escape':
                    overlay.destroy()
            cv.bind("<ButtonPress-1>", on_press)
            cv.bind("<B1-Motion>", on_drag)
            cv.bind("<ButtonRelease-1>", on_release)
            overlay.bind("<KeyPress-Escape>", on_key)
            overlay.focus_set()
            win.wait_window(overlay)
            if result[0]:
                val = f"{result[0][0]},{result[0][1]},{result[0][2]},{result[0][3]}"
                if target == "search":
                    region_var.set(val)
                else:
                    balance_var.set(val)

        def test_search():
            """测试在搜索区域中查找购买按钮"""
            region_str = region_var.get().strip()
            try:
                region = eval(f"[{region_str}]")
                if not isinstance(region, (list, tuple)) or len(region) != 4:
                    status_label.config(text="区域格式错误，应为 x,y,w,h", foreground="#e74c3c")
                    return
            except Exception:
                status_label.config(text="区域格式错误，应为 x,y,w,h", foreground="#e74c3c")
                return
            status_label.config(text="正在查找购买按钮...", foreground="#f39c12")
            import threading
            def _run():
                try:
                    from skin_sniper import SkinSniper
                    s = SkinSniper()
                    s.search_region = tuple(region)
                    # 使用用户设置的 buy_template 路径
                    buy_path = self.app.settings.get("sniper_buy_template", "")
                    if buy_path and os.path.exists(buy_path):
                        s.buy_template = buy_path
                    for _ in range(20):
                        pos = s._find_buy_pos()
                        if pos:
                            win.after(0, lambda p=pos: status_label.config(
                                text=f"找到按钮！位置 ({p[0]}, {p[1]})", foreground="#27ae60"))
                            return
                        time.sleep(0.3)
                    win.after(0, lambda: status_label.config(text="未找到购买按钮", foreground="#e74c3c"))
                except Exception as e:
                    win.after(0, lambda e=e: status_label.config(text=f"测试异常: {e}", foreground="#e74c3c"))
            threading.Thread(target=_run, daemon=True).start()

        def test_balance():
            region_str = balance_var.get().strip()
            if not region_str:
                status_label.config(text="请先设置余额区域", foreground="#e74c3c")
                return
            try:
                region = eval(f"[{region_str}]")
                if not isinstance(region, (list, tuple)) or len(region) != 4:
                    status_label.config(text="余额区域格式错误", foreground="#e74c3c")
                    return
            except Exception:
                status_label.config(text="余额区域格式错误", foreground="#e74c3c")
                return
            status_label.config(text="正在测试余额...", foreground="#f39c12")
            import threading
            def _run():
                try:
                    from skin_sniper import SkinSniper
                    s = SkinSniper()
                    s.balance_region = tuple(region)
                    val = s._read_balance()
                    win.after(0, lambda v=val: status_label.config(
                        text=f"余额: {v}" if v else "未识别到余额", foreground="#27ae60" if v else "#e74c3c"))
                except Exception as e:
                    win.after(0, lambda e=e: status_label.config(text=f"测试异常: {e}", foreground="#e74c3c"))
            threading.Thread(target=_run, daemon=True).start()

        # ---- 按钮 ----
        ttk.Button(r1, text="启动抢购", command=sniper_start, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(r1, text="停止", command=sniper_stop, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(r1, text="测试搜索", command=test_search, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(r1, text="测试余额", command=test_balance, width=10).pack(side=tk.LEFT, padx=2)

        # 搜索区域
        r2 = ttk.Frame(main, style='SettingsInner.TFrame')
        r2.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(r2, text="搜索区域:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(r2, textvariable=region_var, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(r2, text="设置", command=lambda: set_region("search"), width=5).pack(side=tk.LEFT, padx=(0, 8))

        # 购买按钮图片路径
        buy_path_var = tk.StringVar(value=_sv("sniper_buy_template", ""))
        r2b = ttk.Frame(main, style='SettingsInner.TFrame')
        r2b.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(r2b, text="购买按钮图:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(r2b, textvariable=buy_path_var, width=20).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(r2b, text="浏览", width=4,
                   command=lambda: buy_path_var.set(
                       filedialog.askopenfilename(title="选择购买按钮图片",
                           filetypes=[("PNG", "*.png"), ("所有图片", "*.png *.jpg *.bmp")])
                   )).pack(side=tk.LEFT)

        # 刷新按钮图片路径
        refresh_path_var = tk.StringVar(value=_sv("sniper_refresh_template", ""))
        r2c = ttk.Frame(main, style='SettingsInner.TFrame')
        r2c.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(r2c, text="刷新按钮图:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(r2c, textvariable=refresh_path_var, width=20).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(r2c, text="浏览", width=4,
                   command=lambda: refresh_path_var.set(
                       filedialog.askopenfilename(title="选择刷新按钮图片",
                           filetypes=[("PNG", "*.png"), ("所有图片", "*.png *.jpg *.bmp")])
                   )).pack(side=tk.LEFT)

        # 余额区域
        r3 = ttk.Frame(main, style='SettingsInner.TFrame')
        r3.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(r3, text="余额区域:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(r3, textvariable=balance_var, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(r3, text="设置", command=lambda: set_region("balance"), width=5).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(r3, text="变化阈值:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 2))
        ttk.Entry(r3, textvariable=balance_threshold_var, width=5).pack(side=tk.LEFT)

        # 超时设置
        r4 = ttk.Frame(main, style='SettingsInner.TFrame')
        r4.pack(fill=tk.X, padx=5, pady=(2, 5))
        ttk.Label(r4, text="超时(分钟,0=不限制):", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        ttk.Entry(r4, textvariable=timeout_var, width=6).pack(side=tk.LEFT)

        # 在启动/停止时同步图片路径
        _orig_start = sniper_start
        def _start_with_paths():
            if sniper_ref[0] is None:
                from skin_sniper import SkinSniper
                sniper_ref[0] = SkinSniper()
            s = sniper_ref[0]
            # 同步图片路径
            bp = buy_path_var.get().strip()
            if bp:
                s.buy_template = bp
            rp = refresh_path_var.get().strip()
            if rp:
                s.refresh_template = rp
            # 保存设置
            self.app.settings["sniper_buy_template"] = bp
            self.app.settings["sniper_refresh_template"] = rp
            _orig_start()
        sniper_start = _start_with_paths

        win.protocol("WM_DELETE_WINDOW", lambda: (
            _save_sniper_settings(),
            sniper_stop(),
            utils.save_window_geometry(win, "sniper_geometry"),
            win.destroy()
        ))

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
                import interception_keyboard
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
        ttk.Label(time_row2, text="格式 HH:MM，仅在该时段执行",
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

    def _open_capture_wizard_nav(self):
        """打开模板上传向导（带导航栈）"""
        def _open():
            self._open_capture_wizard()
        utils.nav_push(self.win, _open)

    def _open_capture_wizard(self):
        """打开模板截图向导"""
        from template_capture import TemplateCaptureWizard
        current_res = config.get_resolution_key()
        wizard = TemplateCaptureWizard(self.win, current_res, app=self.app)
        wizard.win.protocol("WM_DELETE_WINDOW", lambda: utils.nav_pop(wizard.win))

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

        # 账号数据自动备份间隔（天，0=关闭）
        fresh["account_backup_days"] = self.account_backup_days_var.get()

        # 日志/备份保留天数（0=不清理）
        fresh["log_retention_days"] = self.log_retention_days_var.get()

        # 邮件通知设置
        fresh["email_enabled"] = self.email_enable_var.get()
        fresh["smtp_code"] = self.smtp_code_var.get()
        fresh["sender_email"] = self.sender_email_var.get()
        fresh["receiver_email"] = self.receiver_email_var.get()

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
        fresh["cooldown_hours"] = self.cooldown_hours_var.get()

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
        utils.nav_pop(self.win)
