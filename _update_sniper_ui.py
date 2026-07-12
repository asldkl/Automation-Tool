#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "settings_window.py")

with open(PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the sniper UI section
old_ui = '''        # ----- 皮肤抢购测试 -----
        frame_sniper = ttk.LabelFrame(parent, text="  皮肤抢购测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_sniper.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_sniper, text="OCR监控倒计时，到达阈值时自动点击购买+确认",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        sniper_row1 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_row1.pack(fill=tk.X, padx=5, pady=2)

        self._sniper_status = ttk.Label(sniper_row1, text="未启动", style='SettingsSmall.TLabel')
        self._sniper_status.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(sniper_row1, text="启动抢购", style='TButton',
                   command=self._sniper_start, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(sniper_row1, text="停止抢购", style='TButton',
                   command=self._sniper_stop, width=12).pack(side=tk.LEFT, padx=2)
        ttk.Button(sniper_row1, text="测试倒计时识别", style='TButton',
                   command=self._sniper_test_ocr, width=14).pack(side=tk.LEFT, padx=2)
        ttk.Button(sniper_row1, text="测试余额识别", style='TButton',
                   command=self._sniper_test_balance, width=14).pack(side=tk.LEFT, padx=2)

        # 行2: 倒计时区域
        sniper_row2 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_row2.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(sniper_row2, text="倒计时区域:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_region_var = tk.StringVar(value="100,100,200,50")
        ttk.Entry(sniper_row2, textvariable=self._sniper_region_var, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sniper_row2, text="设置区域", command=lambda: self._sniper_set_region("countdown"), width=8).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(sniper_row2, text="触发(秒):", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 2))
        self._sniper_threshold_var = tk.StringVar(value="5")
        ttk.Entry(sniper_row2, textvariable=self._sniper_threshold_var, width=4).pack(side=tk.LEFT)

        # 行3: 余额区域
        sniper_row3 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_row3.pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(sniper_row3, text="余额区域:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_balance_var = tk.StringVar(value="")
        ttk.Entry(sniper_row3, textvariable=self._sniper_balance_var, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sniper_row3, text="设置区域", command=lambda: self._sniper_set_region("balance"), width=8).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(sniper_row3, text="变化阈值:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 2))
        self._sniper_balance_threshold_var = tk.StringVar(value="0")
        ttk.Entry(sniper_row3, textvariable=self._sniper_balance_threshold_var, width=5).pack(side=tk.LEFT)

        # 行4: 超时设置
        sniper_row4 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_row4.pack(fill=tk.X, padx=5, pady=(2, 5))

        ttk.Label(sniper_row4, text="超时(分钟,0=不限制):", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_timeout_var = tk.StringVar(value="30")
        ttk.Entry(sniper_row4, textvariable=self._sniper_timeout_var, width=6).pack(side=tk.LEFT)'''

new_ui = '''        # ----- 皮肤抢购测试 -----
        frame_sniper = ttk.LabelFrame(parent, text="  皮肤抢购测试  ", style='SettingsCard.TLabelframe', padding=12)
        frame_sniper.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(frame_sniper, text="OCR监控倒计时 + 余额检测 + 超时自动停止",
                 style='SettingsSmall.TLabel').pack(anchor=tk.W, padx=5, pady=(0, 8))

        # 行1: 控制按钮
        sniper_r1 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_r1.pack(fill=tk.X, padx=5, pady=2)
        self._sniper_status = ttk.Label(sniper_r1, text="未启动", style='SettingsSmall.TLabel')
        self._sniper_status.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(sniper_r1, text="启动抢购", command=self._sniper_start, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(sniper_r1, text="停止", command=self._sniper_stop, width=8).pack(side=tk.LEFT, padx=2)
        ttk.Button(sniper_r1, text="测试倒计时", command=self._sniper_test_ocr, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(sniper_r1, text="测试余额", command=self._sniper_test_balance, width=10).pack(side=tk.LEFT, padx=2)

        # 行2: 倒计时区域 + 触发阈值
        sniper_r2 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_r2.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(sniper_r2, text="倒计时区域:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_region_var = tk.StringVar(value="100,100,200,50")
        ttk.Entry(sniper_r2, textvariable=self._sniper_region_var, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sniper_r2, text="设置", command=lambda: self._sniper_set_region("countdown"), width=5).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(sniper_r2, text="触发(秒):", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 2))
        self._sniper_threshold_var = tk.StringVar(value="5")
        ttk.Entry(sniper_r2, textvariable=self._sniper_threshold_var, width=4).pack(side=tk.LEFT)

        # 行3: 余额区域 + 变化阈值
        sniper_r3 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_r3.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(sniper_r3, text="余额区域:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_balance_var = tk.StringVar(value="")
        ttk.Entry(sniper_r3, textvariable=self._sniper_balance_var, width=14).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sniper_r3, text="设置", command=lambda: self._sniper_set_region("balance"), width=5).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(sniper_r3, text="变化阈值:", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 2))
        self._sniper_balance_threshold_var = tk.StringVar(value="0")
        ttk.Entry(sniper_r3, textvariable=self._sniper_balance_threshold_var, width=5).pack(side=tk.LEFT)

        # 行4: 超时设置
        sniper_r4 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_r4.pack(fill=tk.X, padx=5, pady=(2, 5))
        ttk.Label(sniper_r4, text="超时(分钟,0=不限制):", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_timeout_var = tk.StringVar(value="30")
        ttk.Entry(sniper_r4, textvariable=self._sniper_timeout_var, width=6).pack(side=tk.LEFT)'''

assert old_ui in content, "old UI not found!"
content = content.replace(old_ui, new_ui)

# Replace the start method
old_start = '''    def _sniper_start(self):
        """启动皮肤抢购"""
        if not hasattr(self, '_sniper') or self._sniper is None:
            from skin_sniper import SkinSniper
            self._sniper = SkinSniper()
        try:
            region = eval(self._sniper_region_var.get().strip())
            if isinstance(region, (list, tuple)) and len(region) == 4:
                self._sniper.countdown_region = tuple(region)
        except Exception:
            pass
        try:
            region = eval(self._sniper_balance_var.get().strip())
            if isinstance(region, (list, tuple)) and len(region) == 4:
                self._sniper.balance_region = tuple(region)
        except Exception:
            pass
        try:
            self._sniper.buy_threshold = int(self._sniper_threshold_var.get().strip())
        except Exception:
            pass
        try:
            self._sniper.balance_change_threshold = int(self._sniper_balance_threshold_var.get().strip())
        except Exception:
            pass
        try:
            self._sniper.timeout_minutes = int(self._sniper_timeout_var.get().strip())
        except Exception:
            pass
        self._sniper.set_callbacks(
            status_cb=lambda s: self.win.after(0, lambda: self._sniper_status.config(text=s)),
        )
        self._sniper.start()
        self._sniper_status.config(text="启动中...", foreground="#3498db")'''

new_start = '''    def _sniper_start(self):
        """启动皮肤抢购"""
        if not hasattr(self, '_sniper') or self._sniper is None:
            from skin_sniper import SkinSniper
            self._sniper = SkinSniper()
        try:
            region = eval(self._sniper_region_var.get().strip())
            if isinstance(region, (list, tuple)) and len(region) == 4:
                self._sniper.countdown_region = tuple(region)
        except Exception:
            pass
        try:
            region = eval(self._sniper_balance_var.get().strip())
            if isinstance(region, (list, tuple)) and len(region) == 4:
                self._sniper.balance_region = tuple(region)
        except Exception:
            pass
        try:
            self._sniper.buy_threshold = int(self._sniper_threshold_var.get().strip())
        except Exception:
            pass
        try:
            self._sniper.balance_change_threshold = int(self._sniper_balance_threshold_var.get().strip())
        except Exception:
            pass
        try:
            self._sniper.timeout_minutes = int(self._sniper_timeout_var.get().strip())
        except Exception:
            pass
        self._sniper.set_callbacks(
            status_cb=lambda s: self.win.after(0, lambda: self._sniper_status.config(text=s)),
        )
        self._sniper.start()
        self._sniper_status.config(text="启动中...", foreground="#3498db")'''

assert old_start in content, "old start not found!"
content = content.replace(old_start, new_start)

# Add _sniper_set_region and _sniper_test_balance methods
old_methods = '''    def _sniper_stop(self):
        """停止皮肤抢购"""
        if hasattr(self, '_sniper') and self._sniper:
            self._sniper.stop()
        self._sniper_status.config(text="已停止", foreground="#e74c3c")

    def _sniper_test_balance(self):'''

new_methods = '''    def _sniper_set_region(self, target):
        """全屏拖拽选择区域"""
        import pyautogui as pg
        import tkinter as tk_overlay
        self.win.withdraw()
        self.win.after(300, lambda: self._show_sniper_overlay(target))

    def _show_sniper_overlay(self, target):
        import tkinter as tk_overlay
        overlay = tk_overlay.Toplevel(self.win)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-alpha', 0.3)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='black')
        overlay.config(cursor="crosshair")
        canvas = tk_overlay.Canvas(overlay, highlightthickness=0, bg='black')
        canvas.pack(fill=tk.BOTH, expand=True)
        tk_overlay.Label(overlay, text="请拖动鼠标框选识别区域，按 Esc 取消",
                         font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black').place(relx=0.5, rely=0.05, anchor='center')
        rect_id = None
        sx = sy = 0
        res = [None]
        def on_press(e):
            nonlocal sx, sy, rect_id
            sx, sy = e.x, e.y
            if rect_id: canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(sx, sy, sx, sy, outline='red', width=2)
        def on_drag(e):
            if rect_id: canvas.coords(rect_id, sx, sy, e.x, e.y)
        def on_release(e):
            x1, y1 = min(sx, e.x), min(sy, e.y)
            x2, y2 = max(sx, e.x), max(sy, e.y)
            if x2-x1 > 10 and y2-y1 > 10:
                res[0] = [x1, y1, x2-x1, y2-y1]
            overlay.destroy()
        def on_esc(e): overlay.destroy()
        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_esc)
        self.win.wait_window(overlay)
        self.win.deiconify()
        if res[0]:
            if target == "countdown":
                self._sniper_region_var.set(str(res[0]))
            elif target == "balance":
                self._sniper_balance_var.set(str(res[0]))

    def _sniper_stop(self):
        """停止皮肤抢购"""
        if hasattr(self, '_sniper') and self._sniper:
            self._sniper.stop()
        self._sniper_status.config(text="已停止", foreground="#e74c3c")

    def _sniper_test_balance(self):'''

assert old_methods in content, "old methods not found!"
content = content.replace(old_methods, new_methods)

with open(PATH, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK")
