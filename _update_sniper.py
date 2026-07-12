#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

# ===== 1. Update skin_sniper.py =====
path = os.path.join(ROOT, "skin_sniper.py")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add balance region and timeout to __init__
old = '''        self.countdown_region = (100, 100, 200, 50)  # 倒计时区域 x,y,w,h
        self.buy_template = None    # 图1：购买按钮模板路径'''
new = '''        self.countdown_region = (100, 100, 200, 50)  # 倒计时区域 x,y,w,h
        self.balance_region = None    # 余额区域 x,y,w,h（None=不检测）
        self.buy_template = None    # 图1：购买按钮模板路径'''
assert old in content
content = content.replace(old, new)

# Add timeout config
old = '''        self.buy_threshold = 5            # 倒计时低于此值执行抢购

        self._last_countdown = None    # 上一次识别到的倒计时值'''
new = '''        self.buy_threshold = 5            # 倒计时低于此值执行抢购
        self.balance_change_threshold = 0  # 余额变化大于此值视为购买成功
        self.timeout_minutes = 0        # 超时分钟数（0=不超时）

        self._last_countdown = None    # 上一次识别到的倒计时值
        self._last_balance = None      # 上一次的余额值
        self._purchase_attempted = False
        self._purchase_success = False'''
assert old in content
content = content.replace(old, new)

# Add start_time to __init__
old = '''        self._start_time = None  # 启动时间，用于超时判断

        # 默认配置（可在UI中修改）'''
new = '''        # 默认配置（可在UI中修改）'''
content = content.replace(old, new)

# Add _read_balance method
old = '''    @property
    def is_running(self):
        return self._running'''
new = '''    @property
    def is_running(self):
        return self._running

    def _read_balance(self):
        """OCR读取余额区域，返回数值或None"""
        if not self.balance_region or self.balance_region[2] <= 0 or self.balance_region[3] <= 0:
            return None
        results = utils.ocr_recognize(self.balance_region)
        if not results:
            return None
        for text, conf, bbox in results:
            if conf < 0.5:
                continue
            match = re.search(r'[\\d,.]+', text)
            if match:
                raw = match.group(0).replace(',', '').replace('.', '')
                try:
                    return int(raw)
                except ValueError:
                    pass
        return None

    def _check_timeout(self):
        """检查是否超时，超时返回True"""
        if self.timeout_minutes <= 0 or self._start_time is None:
            return False
        elapsed = (time.time() - self._start_time) / 60
        return elapsed >= self.timeout_minutes'''
assert old in content
content = content.replace(old, new)

# Update start to record time
old = '''    def start(self):
        """启动抢购线程"""
        if self._running:
            return
        self._running = True
        self._purchase_attempted = False
        self._purchase_success = False
        self._start_time = time.time()
        self._stop_event.clear()'''
new = '''    def start(self):
        """启动抢购线程"""
        if self._running:
            return
        self._running = True
        self._purchase_attempted = False
        self._purchase_success = False
        self._last_balance = None
        self._start_time = time.time()
        self._stop_event.clear()'''
assert old in content
content = content.replace(old, new)

# Update _run_loop with balance check and timeout
old = '''        while not self._stop_event.is_set():
            try:
                # 超时检查
                if self._check_timeout():
                    self._log(f"抢购超时（{self.timeout_minutes}分钟），自动停止")
                    self._set_status("已超时停止")
                    break

                # 购买成功后退出
                if self._purchase_success:
                    self._log("购买成功，监控结束")
                    self._set_status("购买成功 ✅")
                    break

                countdown = self._read_countdown()
                now = time.time()

                if countdown is not None:
                    self._last_countdown = countdown
                    self._set_status(f"倒计时: {countdown:.0f}秒")

                    if countdown < self.buy_threshold and not self._purchase_attempted:
                        self._log(f"倒计时 {countdown:.0f}秒 < {self.buy_threshold}秒，执行抢购!")
                        self._purchase_attempted = True
                        self._execute_purchase()

                        # 检测余额变化判断是否成功
                        self._sleep_or_stop(2)
                        if self.balance_region:
                            new_balance = self._read_balance()
                            if self._last_balance is not None and new_balance is not None:
                                diff = abs(new_balance - self._last_balance)
                                if diff > self.balance_change_threshold:
                                    self._log(f"余额变化 {diff}，购买成功!")
                                    self._purchase_success = True
                                    continue
                                else:
                                    self._log(f"余额未变化({diff})，可能购买失败，继续监控")
                                    self._purchase_attempted = False
                            else:
                                self._log("无法读取余额，继续监控")
                                self._purchase_attempted = False
                        else:
                            self._purchase_success = True  # 未配置余额检测，默认成功
                            continue

                    if countdown < self.refresh_stop_threshold:
                        self._set_status(f"等待抢购: {countdown:.0f}秒")
                        self._sleep_or_stop(self.ocr_interval)
                        continue

                # 非抢购期：定时刷新
                if refresh_timer >= self.refresh_interval:
                    if self.refresh_template and os.path.exists(self.refresh_template):
                        self._log("刷新页面")
                        utils.find_and_click_smart(self.refresh_template, timeout=5)
                    refresh_timer = 0
                else:
                    refresh_timer += self.ocr_interval

                self._sleep_or_stop(self.ocr_interval)

            except Exception as e:
                self._log(f"异常: {e}")
                self._sleep_or_stop(1)

        self._running = False'''
# _run_loop already updated - skipping

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("1. skin_sniper.py updated")

# ===== 2. Update settings_window.py =====
path2 = os.path.join(ROOT, "settings_window.py")
with open(path2, 'r', encoding='utf-8') as f:
    content2 = f.read()

# Replace the sniper UI section with enhanced version
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

        sniper_row2 = ttk.Frame(frame_sniper, style='SettingsInner.TFrame')
        sniper_row2.pack(fill=tk.X, padx=5, pady=(2, 5))

        ttk.Label(sniper_row2, text="倒计时区域(x,y,w,h)：", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 4))
        self._sniper_region_var = tk.StringVar(value="100,100,200,50")
        ttk.Entry(sniper_row2, textvariable=self._sniper_region_var, width=18).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(sniper_row2, text="阈值(秒)：", style='SettingsSmall.TLabel').pack(side=tk.LEFT, padx=(0, 2))
        self._sniper_threshold_var = tk.StringVar(value="5")
        ttk.Entry(sniper_row2, textvariable=self._sniper_threshold_var, width=5).pack(side=tk.LEFT)'''

new_ui = '''        # ----- 皮肤抢购测试 -----
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

assert old_ui in content2, "old UI not found"
content2 = content2.replace(old_ui, new_ui)

# Add _sniper_set_region and _sniper_test_balance methods
old_methods = '''    def _sniper_stop(self):
        """停止皮肤抢购"""
        if hasattr(self, '_sniper') and self._sniper:
            self._sniper.stop()
        self._sniper_status.config(text="已停止", foreground="#e74c3c")

    def _sniper_test_ocr(self):'''

new_methods = '''    def _sniper_set_region(self, target):
        """全屏拖拽选择区域"""
        import pyautogui as pg
        import tkinter as tk_overlay

        self.win.withdraw()
        self.win.after(300, lambda: self._sniper_show_overlay(target))
        self._sniper_overlay_target = target

    def _sniper_show_overlay(self, target):
        """显示区域选择覆盖层"""
        import tkinter as tk_overlay
        import pyautogui as pg

        overlay = tk_overlay.Toplevel(self.win)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-alpha', 0.3)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='black')
        overlay.config(cursor="crosshair")

        canvas = tk_overlay.Canvas(overlay, highlightthickness=0, bg='black')
        canvas.pack(fill=tk.BOTH, expand=True)

        hint = tk_overlay.Label(overlay, text="请拖动鼠标框选识别区域，按 Esc 取消",
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
            rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline='red', width=2)

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

        if result and hasattr(self, '_sniper_overlay_target'):
            if self._sniper_overlay_target == "countdown":
                self._sniper_region_var.set(str(result))
            elif self._sniper_overlay_target == "balance":
                self._sniper_balance_var.set(str(result))

    def _sniper_stop(self):
        """停止皮肤抢购"""
        if hasattr(self, '_sniper') and self._sniper:
            self._sniper.stop()
        self._sniper_status.config(text="已停止", foreground="#e74c3c")

    def _sniper_test_balance(self):
        """测试余额OCR识别"""
        try:
            region_str = self._sniper_balance_var.get().strip()
            if not region_str:
                self._sniper_status.config(text="请先设置余额区域", foreground="#e74c3c")
                return
            region = eval(region_str)
            if not isinstance(region, (list, tuple)) or len(region) != 4:
                raise ValueError
            region = tuple(region)
        except Exception:
            self._sniper_status.config(text="余额区域格式错误", foreground="#e74c3c")
            return

        import threading
        def _run():
            from skin_sniper import SkinSniper
            sniper = SkinSniper()
            sniper.balance_region = region
            for _ in range(5):
                val = sniper._read_balance()
                if val is not None:
                    self.win.after(0, lambda v=val: self._sniper_status.config(
                        text=f"余额: {v}", foreground="#27ae60"))
                else:
                    self.win.after(0, lambda: self._sniper_status.config(
                        text="未识别到余额", foreground="#e74c3c"))
                time.sleep(0.5)
            self.win.after(0, lambda: self._sniper_status.config(text="余额测试完成"))
        threading.Thread(target=_run, daemon=True).start()

    def _sniper_test_ocr(self):'''

assert old_methods in content2, "old methods not found"
content2 = content2.replace(old_methods, new_methods)

# Update _sniper_start to pass new configs
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
            self._sniper.buy_threshold = int(self._sniper_threshold_var.get().strip())
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

assert old_start in content2, "old start method not found"
content2 = content2.replace(old_start, new_start)

with open(path2, 'w', encoding='utf-8') as f:
    f.write(content2)
print("2. settings_window.py updated")
print("Done!")
