"""
图形用户界面模块
包含多账号管理、快捷登录、游戏内操作、停止机制及快捷键
支持账号列表本地持久化、启动联网时间校验、多时间点定时执行、每日循环、静默托盘、开机自启动
"""
import os
import sys
import time
import json
import datetime
import threading
import urllib.request
import re
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import pyautogui
import winreg

import config
import utils
from settings_window import SettingsWindow

# 尝试导入托盘所需库
try:
    import pystray
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# -------------------- 有效期设置 --------------------
EXPIRY_DATE = datetime.date(2026, 6, 1)
# ------------------------------------------------

ACCOUNTS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_accounts.json")


class RedirectText:
    """将标准输出重定向到 Tkinter 文本框，可选同时写入日志文件"""
    def __init__(self, text_widget, log_path=None):
        self.text_widget = text_widget
        self.log_path = log_path
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def write(self, message):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, message)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')
        if self.log_path and message.strip():
            try:
                with open(self.log_path, 'a', encoding='utf-8') as f:
                    f.write(message)
            except Exception:
                pass

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("三角洲行动自动化工具")
        self.root.resizable(False, False)
        self.running = False
        self.account_images = []
        self.qq_account_images = []
        self._stop_event = threading.Event()
        self._qq_running = False
        self._qq_pause_event = threading.Event()
        self._qq_pause_event.set()  # 初始状态：未暂停
        self._auto_timer = None
        self._schedule_thread = None
        self._daily_loop = False
        self._silent = False
        self._schedule_times = []
        self._settings_window = None
        # 提醒相关
        self._reminder_shown = False
        self._reminder_cancelled = False
        self._reminder_target = None
        self._reminder_window = None
        self._next_run_time_str = ""
        # 唤醒定时器
        self._wake_timer_handle = None
        self._wake_attempted = False  # 是否已尝试唤醒显示器
        # 关机标志（每日只触发一次）
        self._shutdown_handled_today = False
        # 窗口图标
        try:
            icon_path = config.resource_path("picture/icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        # 加载设置
        self.settings = config.APP_SETTINGS
        config.WEGAME_PATH = self.settings.get("wegame_path", "")
        config.CONFIDENCE = self.settings["confidence"]

        # 运行统计
        self.run_stats = {"total": 0, "success": 0, "fail": 0, "start_time": None}

        # 日志文件路径
        log_dir = self.settings.get("log_save_path", "")
        if log_dir:
            today = datetime.datetime.now().strftime("%Y%m%d")
            self._log_file_path = os.path.join(log_dir, f"delta_auto_{today}.log")
        else:
            self._log_file_path = None

        # 初始化样式
        self._setup_styles()

        # 快捷键
        root.bind("<F1>", lambda e: self.start())
        root.bind("<F2>", lambda e: self.stop())

        self._build_ui()
        self._redirect_output()
        self.total_steps = 0
        self.current_step = 0
        self.load_accounts()
        self.update_account_count()

        # 托盘
        self.tray_icon = None
        self._setup_tray()

        # 定时任务初始化
        if self.settings.get("auto_start", False):
            self._start_scheduler()

        # QQ 开机自动登录（仅在开机自启动时运行，双击启动不触发）
        if self.settings.get("qq_login_enabled", False) and self.qq_account_images and '--auto-start' in sys.argv:
            self.root.after(2000, self._auto_login_qq)

        # 静默模式
        if self.settings.get("silent_mode", False) and TRAY_AVAILABLE:
            self.root.withdraw()

        # 关闭按钮 → 最小化到托盘（而非退出）
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        """配置现代化 ttk 样式"""
        style = ttk.Style()
        # 使用 clam 主题以获得更好的自定义能力
        available_themes = style.theme_names()
        if 'clam' in available_themes:
            style.theme_use('clam')

        # 配色方案
        PRIMARY = "#2c3e50"
        ACCENT = "#3498db"
        SUCCESS = "#27ae60"
        DANGER = "#e74c3c"
        WARNING = "#f39c12"
        BG_LIGHT = "#f0f2f5"
        CARD_BG = "#ffffff"
        TEXT_DARK = "#2c3e50"
        TEXT_LIGHT = "#ffffff"
        BORDER = "#dcdde1"

        # 根窗口背景
        style.configure('.', background=BG_LIGHT, font=('Microsoft YaHei UI', 9))
        style.configure('TFrame', background=BG_LIGHT)
        style.configure('TLabel', background=BG_LIGHT, foreground=TEXT_DARK)
        style.configure('TButton', background=PRIMARY, foreground=TEXT_LIGHT,
                        borderwidth=0, focusthickness=3, font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('TButton',
                  background=[('active', ACCENT), ('disabled', '#bdc3c7')],
                  foreground=[('disabled', '#95a5a6')])

        # 卡片样式的 LabelFrame
        style.configure('Card.TLabelframe', background=CARD_BG, foreground=TEXT_DARK,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe.Label', background=CARD_BG, foreground=PRIMARY,
                        font=('Microsoft YaHei UI', 9, 'bold'))

        # 带内部 Frame 的卡片
        style.configure('CardInner.TFrame', background=CARD_BG)

        # 标题样式
        style.configure('Header.TFrame', background=PRIMARY)
        style.configure('Header.TLabel', background=PRIMARY, foreground=TEXT_LIGHT,
                        font=('Microsoft YaHei UI', 14, 'bold'))
        style.configure('HeaderSub.TLabel', background=PRIMARY, foreground='#bdc3c7',
                        font=('Microsoft YaHei UI', 8))

        # 信息标签
        style.configure('Info.TLabel', background=CARD_BG, foreground=TEXT_DARK)
        style.configure('Accent.TLabel', background=CARD_BG, foreground=ACCENT, font=('Microsoft YaHei UI', 9, 'bold'))
        style.configure('Success.TLabel', background=CARD_BG, foreground=SUCCESS)
        style.configure('Warning.TLabel', background=CARD_BG, foreground=WARNING)

        # 按钮变体
        style.configure('Success.TButton', background=SUCCESS, foreground=TEXT_LIGHT,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Success.TButton', background=[('active', '#219a52'), ('disabled', '#bdc3c7')])

        style.configure('Danger.TButton', background=DANGER, foreground=TEXT_LIGHT,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Danger.TButton', background=[('active', '#c0392b'), ('disabled', '#bdc3c7')])

        style.configure('Accent.TButton', background=ACCENT, foreground=TEXT_LIGHT,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Accent.TButton', background=[('active', '#2980b9'), ('disabled', '#bdc3c7')])

        # 进度条
        style.configure('Accent.Horizontal.TProgressbar', background=ACCENT, troughcolor=BG_LIGHT,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)

        # 复选框
        style.configure('TCheckbutton', background=BG_LIGHT, foreground=TEXT_DARK, font=('Microsoft YaHei UI', 9))

        # 滚动条
        style.configure('TScrollbar', background='#dfe6e9', bordercolor=BG_LIGHT,
                        arrowcolor=PRIMARY, troughcolor=BG_LIGHT)

        # 下拉框
        style.configure('TCombobox', fieldbackground=CARD_BG, foreground=TEXT_DARK,
                        background=PRIMARY, arrowcolor=TEXT_LIGHT)

        # 输入框
        style.configure('TEntry', fieldbackground=CARD_BG, foreground=TEXT_DARK, borderwidth=1)

    # ---------- 托盘 ----------
    def _setup_tray(self):
        if not TRAY_AVAILABLE:
            return
        try:
            icon_path = config.resource_path("picture/icon.ico")
            image = Image.open(icon_path)
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", self._show_window),
                pystray.MenuItem("退出", self._quit_all),
            )
            self.tray_icon = pystray.Icon("delta_tool", image, "三角洲自动化工具", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"⚠️ 托盘创建失败: {e}")

    def _show_window(self):
        self.root.after(0, self.root.deiconify)
        self.root.after(0, lambda: (self.root.lift(), self.root.focus_force()))
        self.root.after(0, lambda: self.root.attributes('-topmost', True))
        self.root.after(100, lambda: self.root.attributes('-topmost', False))

    def _on_close(self):
        """关闭按钮：最小化到托盘（如果可用），否则退出"""
        if TRAY_AVAILABLE and self.tray_icon:
            self.root.withdraw()
            print("ℹ️ 程序已最小化到托盘，右键托盘图标可退出")
        else:
            self._quit_all()

    def _quit_all(self):
        """真正退出程序"""
        self.stop()
        # 清理唤醒定时器
        if self._wake_timer_handle:
            utils.cancel_wake_timer(self._wake_timer_handle)
            self._wake_timer_handle = None
        # 恢复睡眠设置
        utils.allow_sleep()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ---------- 定时任务调度 ----------
    def _start_scheduler(self):
        """启动定时检查线程"""
        if self._schedule_thread and self._schedule_thread.is_alive():
            return
        self._stop_event.clear()
        self._daily_loop = self.settings.get("run_mode") == "每日循环"
        times_str = self.settings.get("schedule_times", [])
        if not times_str:
            single = self.settings.get("start_time", "08:00")
            times_str = [single]
        self._schedule_times = sorted(times_str)
        self._schedule_thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self._schedule_thread.start()
        print(f"⏰ 已设置定时任务，时间点：{', '.join(self._schedule_times)}，"
              f"模式：{'每日循环' if self._daily_loop else '单次'}")
        # 设置唤醒定时器
        self._set_next_wake_timer()
        # 确保开机唤醒任务存在
        if self.settings.get("auto_startup_enabled", False):
            startup_time = self.settings.get("auto_startup_time", "07:00")
            utils.schedule_startup_task(startup_time)

    def _schedule_loop(self):
        """线程：每分钟检查一次时间，处理提醒、唤醒、触发执行和自动关机"""
        if self._daily_loop:
            self._schedule_loop_daily()
        else:
            self._schedule_loop_single()

    def _schedule_loop_daily(self):
        """每日循环模式：持续检查时间点"""
        while not self._stop_event.is_set():
            now = datetime.datetime.now()
            now_str = now.strftime("%H:%M")

            # 1. 定时执行
            if now_str in self._schedule_times and not self.running:
                if not self._reminder_cancelled:
                    self._execute_scheduled_run(now_str)
                else:
                    print(f"⏹ 用户取消了 {now_str} 的定时运行")
                    self._reminder_shown = False
                    self._reminder_target = None
                    self._reminder_cancelled = False
                time.sleep(60)
                continue

            # 在即将运行的时段阻止系统睡眠（唤醒后防止再次休眠）
            if self._is_within_pre_run_window(now, minutes=10):
                utils.prevent_sleep()
                if not self._wake_attempted:
                    utils.wake_display()
                    self._wake_attempted = True
            else:
                if not self.running:
                    utils.allow_sleep()
                self._wake_attempted = False

            # 2. 运行前提醒
            self._check_reminder_daily(now)

            # 3. 自动关机（每天只触发一次）
            self._check_shutdown(now)

            time.sleep(30)

    def _schedule_loop_single(self):
        """单次模式：等待下一个时间点"""
        now = datetime.datetime.now()
        targets = []
        for t in self._schedule_times:
            h, m = map(int, t.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target < now:
                target += datetime.timedelta(days=1)
            targets.append(target)
        next_target = min(targets)
        print(f"⏰ 单次定时：将在 {next_target.strftime('%Y-%m-%d %H:%M')} 执行")

        while not self._stop_event.is_set():
            now = datetime.datetime.now()

            # 在即将运行的时段阻止系统睡眠
            pre_run_start = next_target - datetime.timedelta(minutes=10)
            if pre_run_start <= now < next_target and not self.running:
                utils.prevent_sleep()
                if not self._wake_attempted:
                    utils.wake_display()
                    self._wake_attempted = True
            elif now >= next_target or now < pre_run_start:
                if not self.running:
                    utils.allow_sleep()
                self._wake_attempted = False

            # 提醒
            if self.settings.get("reminder_enabled", False) and not self._reminder_shown and not self.running:
                reminder_min = self.settings.get("reminder_minutes", 5)
                reminder_time = next_target - datetime.timedelta(minutes=reminder_min)
                if reminder_time <= now < next_target:
                    self._next_run_time_str = next_target.strftime("%H:%M")
                    self._reminder_shown = True
                    self._reminder_target = next_target
                    self.root.after(0, lambda: self._show_reminder(reminder_min))

            # 执行
            if now >= next_target:
                if not self._reminder_cancelled:
                    self._execute_scheduled_run(next_target.strftime("%H:%M"))
                else:
                    print(f"⏹ 用户取消了 {next_target.strftime('%H:%M')} 的定时运行")
                self.settings["auto_start"] = False
                config.save_settings(self.settings)
                self.root.after(0, self._update_ui_after_single)
                break

            time.sleep(10)

    def _check_reminder_daily(self, now):
        """每日循环模式：检查是否需要弹出运行提醒"""
        if not self.settings.get("reminder_enabled", False) or self._reminder_shown or self.running:
            return

        reminder_min = self.settings.get("reminder_minutes", 5)
        reminder_sec_offset = reminder_min * 60

        for t in self._schedule_times:
            h, m = map(int, t.split(":"))
            scheduled_sec = h * 3600 + m * 60
            remind_sec = scheduled_sec - reminder_sec_offset

            # 处理跨天提醒（如 00:10 运行，23:55 提醒）
            current_sec = now.hour * 3600 + now.minute * 60 + now.second
            if remind_sec < 0:
                remind_sec += 86400
                scheduled_sec += 86400

            if remind_sec <= current_sec < scheduled_sec:
                self._next_run_time_str = t
                self._reminder_target = t
                self._reminder_shown = True
                self.root.after(0, lambda m=reminder_min: self._show_reminder(m))
                break

        # 如果目标时间已过，重置提醒标志
        if self._reminder_shown and self._reminder_target:
            h, m = map(int, self._reminder_target.split(":"))
            target_sec = h * 3600 + m * 60
            current_sec = now.hour * 3600 + now.minute * 60 + now.second
            if current_sec >= target_sec:
                self._reminder_shown = False
                self._reminder_target = None
                self._reminder_cancelled = False

    def _check_shutdown(self, now):
        """检查是否需要触发自动关机"""
        if not self.settings.get("auto_shutdown_enabled", False) or self._shutdown_handled_today:
            return

        shutdown_time_str = self.settings.get("auto_shutdown_time", "22:00")
        try:
            h, m = map(int, shutdown_time_str.split(":"))
            shutdown_sec = h * 3600 + m * 60
            current_sec = now.hour * 3600 + now.minute * 60 + now.second

            # 在关机时间后的2分钟内触发
            if shutdown_sec <= current_sec < shutdown_sec + 120:
                if self.running:
                    print("⏳ 任务正在运行，延迟关机...")
                    return
                delay = 90
                utils.schedule_shutdown(delay)
                print(f"🔌 已到达关机时间 {shutdown_time_str}，系统将在 {delay} 秒后关机")
                self._shutdown_handled_today = True

            # 每日重置
            if current_sec < 60 and now.hour == 0:
                self._shutdown_handled_today = False
        except Exception as e:
            print(f"⚠️ 自动关机检查失败: {e}")

    def _is_within_pre_run_window(self, now, minutes=10):
        """检查当前时间是否在某个定时运行点的前N分钟窗口内（用于唤醒保持）"""
        if not self._schedule_times:
            return False
        for t in self._schedule_times:
            h, m = map(int, t.split(":"))
            scheduled_sec = h * 3600 + m * 60
            window_start = scheduled_sec - minutes * 60
            current_sec = now.hour * 3600 + now.minute * 60 + now.second
            # 处理跨天
            if window_start < 0:
                window_start += 86400
                scheduled_sec += 86400
            if window_start <= current_sec < scheduled_sec:
                return True
        return False

    def _execute_scheduled_run(self, time_str):
        """执行定时运行（关闭提醒窗口、确保唤醒状态、启动脚本）"""
        print(f"🚀 定时触发：{time_str}")
        # 关闭提醒窗口
        if self._reminder_window:
            try:
                self._reminder_window.destroy()
            except Exception:
                pass
            self._reminder_window = None
        self._reminder_shown = False
        self._reminder_cancelled = False
        # 防止系统在运行时睡眠
        utils.prevent_sleep()
        # 尝试唤醒显示器（从睡眠/息屏状态恢复）
        utils.wake_display()
        time.sleep(2)
        self.start()

    def _set_next_wake_timer(self):
        """计算下一个运行时间，提前5分钟设置唤醒定时器"""
        if not self.settings.get("wake_enabled", True):
            return
        try:
            # 取消旧定时器
            if self._wake_timer_handle:
                utils.cancel_wake_timer(self._wake_timer_handle)
                self._wake_timer_handle = None

            now = datetime.datetime.now()
            next_run = None
            for t in self._schedule_times:
                h, m = map(int, t.split(":"))
                run_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if run_time <= now:
                    run_time += datetime.timedelta(days=1)
                if next_run is None or run_time < next_run:
                    next_run = run_time

            if next_run:
                wake_time = next_run - datetime.timedelta(minutes=5)
                # 只设置未来的唤醒时间（至少1分钟后）
                min_gap = datetime.timedelta(seconds=60)
                if wake_time > now + min_gap:
                    handle = utils.set_wake_timer(wake_time)
                    if handle:
                        self._wake_timer_handle = handle
                        print(f"🔔 已设置唤醒定时器：{wake_time.strftime('%H:%M')}")
        except Exception as e:
            print(f"⚠️ 设置唤醒定时器失败: {e}")

    def _show_reminder(self, minutes):
        """显示运行前提醒弹窗"""
        if self._reminder_window and self._reminder_window.winfo_exists():
            return

        self._reminder_window = tk.Toplevel(self.root)
        self._reminder_window.title("⏰ 运行提醒")
        self._reminder_window.geometry("380x200")
        self._reminder_window.resizable(False, False)
        self._reminder_window.transient(self.root)
        self._reminder_window.attributes('-topmost', True)

        # 居中
        self._reminder_window.update_idletasks()
        x = (self._reminder_window.winfo_screenwidth() - 380) // 2
        y = (self._reminder_window.winfo_screenheight() - 200) // 2
        self._reminder_window.geometry(f"380x200+{x}+{y}")

        frame = ttk.Frame(self._reminder_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"程序即将在 {minutes} 分钟后运行",
                 font=('Microsoft YaHei UI', 14, 'bold')).pack(pady=(10, 5))
        ttk.Label(frame, text=f"将于 {self._next_run_time_str} 开始执行任务",
                 font=('Microsoft YaHei UI', 9)).pack(pady=(0, 15))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="立即运行", style='Success.TButton',
                  command=self._reminder_run_now, width=12).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="取消本次", style='Danger.TButton',
                  command=self._reminder_cancel, width=12).pack(side=tk.LEFT)

        self._reminder_window.protocol("WM_DELETE_WINDOW", self._reminder_cancel)

    def _reminder_run_now(self):
        """提醒窗口：立即运行"""
        if self._reminder_window:
            try:
                self._reminder_window.destroy()
            except Exception:
                pass
            self._reminder_window = None
        self._reminder_cancelled = False
        self._reminder_shown = False
        if not self.running:
            utils.prevent_sleep()
            self.start()

    def _reminder_cancel(self):
        """提醒窗口：取消本次运行"""
        if self._reminder_window:
            try:
                self._reminder_window.destroy()
            except Exception:
                pass
            self._reminder_window = None
        self._reminder_cancelled = True
        print(f"⏹ 用户取消了 {self._next_run_time_str} 的定时运行")

    def _update_ui_after_single(self):
        self.settings["auto_start"] = False
        config.save_settings(self.settings)

    def _stop_scheduler(self):
        pass

    # ---------- UI 构建 ----------
    def _build_ui(self):
        # ===== 顶部标题栏 =====
        header = ttk.Frame(self.root, style='Header.TFrame')
        header.pack(fill=tk.X, padx=0, pady=0, ipady=8)
        ttk.Label(header, text="三角洲行动自动化工具", style='Header.TLabel').pack(side=tk.LEFT, padx=(15, 5))
        ttk.Label(header, text="v2.0  |  多账号轮换 · 定时执行 · QQ自动登录", style='HeaderSub.TLabel').pack(side=tk.LEFT, padx=5)

        # ===== 主内容区 =====
        main_container = ttk.Frame(self.root, style='TFrame')
        main_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 12))

        # ----- 账号管理 -----
        account_frame = ttk.LabelFrame(main_container, text=" 账号管理（截图顺序即运行顺序） ", style='Card.TLabelframe', padding=12)
        account_frame.pack(fill=tk.X, pady=(0, 8))

        # 按钮行
        btn_frame = ttk.Frame(account_frame, style='CardInner.TFrame')
        btn_frame.pack(fill=tk.X, pady=(0, 6))
        self.add_btn = ttk.Button(btn_frame, text="＋ 添加账号", style='Accent.TButton', command=self.add_account, width=14)
        self.add_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.del_btn = ttk.Button(btn_frame, text="－ 删除选中", style='TButton', command=self.delete_account, width=10)
        self.del_btn.pack(side=tk.LEFT, padx=4)
        self.clear_btn = ttk.Button(btn_frame, text="× 清空列表", style='TButton', command=self.clear_accounts, width=10)
        self.clear_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="↑ 上移", style='TButton', command=self._move_up, width=7).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="↓ 下移", style='TButton', command=self._move_down, width=7).pack(side=tk.LEFT, padx=4)

        # 列表
        list_frame = ttk.Frame(account_frame, style='CardInner.TFrame')
        list_frame.pack(fill=tk.X)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.account_listbox = tk.Listbox(list_frame, height=4,
                                          yscrollcommand=scrollbar.set,
                                          selectmode=tk.SINGLE,
                                          font=('Microsoft YaHei UI', 9),
                                          bg='#fafbfc', fg='#2c3e50',
                                          selectbackground='#3498db',
                                          selectforeground='#ffffff',
                                          relief='flat', highlightthickness=1,
                                          highlightcolor='#dcdde1', borderwidth=0)
        scrollbar.config(command=self.account_listbox.yview)
        self.account_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

        # 账号列表右键菜单
        self.account_menu = tk.Menu(self.root, tearoff=0)
        self.account_menu.add_command(label="测试截图识别", command=self._test_recognition)
        self.account_menu.add_separator()
        self.account_menu.add_command(label="删除选中", command=self.delete_account)
        self.account_listbox.bind("<Button-3>", self._show_account_menu)


        # ----- 状态信息栏 -----
        info_card = ttk.Frame(main_container, style='Card.TLabelframe', padding=10)
        info_card.pack(fill=tk.X, pady=(0, 8))

        info_row = ttk.Frame(info_card, style='CardInner.TFrame')
        info_row.pack(fill=tk.X)
        ttk.Label(info_row, text="进度：", style='Info.TLabel').pack(side=tk.LEFT)
        self.account_label = ttk.Label(info_row, text="未开始", style='Accent.TLabel')
        self.account_label.pack(side=tk.LEFT, padx=(2, 18))
        ttk.Label(info_row, text="当前账号：", style='Info.TLabel').pack(side=tk.LEFT)
        self.current_account_file_label = ttk.Label(info_row, text="无", style='Success.TLabel')
        self.current_account_file_label.pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(info_row, text="操作：", style='Info.TLabel').pack(side=tk.LEFT)
        self.op_label = ttk.Label(info_row, text="就绪", style='Warning.TLabel')
        self.op_label.pack(side=tk.LEFT, padx=(2, 0))

        # 进度条
        self.progress = ttk.Progressbar(main_container, length=500, mode='determinate',
                                         style='Accent.Horizontal.TProgressbar')
        self.progress.pack(pady=(0, 4), fill=tk.X)

        # 运行统计
        self.stats_label = ttk.Label(main_container, text="", style='Info.TLabel')
        self.stats_label.pack(pady=(0, 8))

        # ----- 日志区域 -----
        log_label_frame = ttk.LabelFrame(main_container, text=" 运行日志 ", style='Card.TLabelframe', padding=8)
        log_label_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.log_area = scrolledtext.ScrolledText(log_label_frame,
                                                  state='disabled', wrap=tk.WORD,
                                                  font=('Consolas', 9),
                                                  bg='#1e272e', fg='#00d8d6',
                                                  insertbackground='#00d8d6',
                                                  relief='flat', borderwidth=0,
                                                  padx=8, pady=8,
                                                  highlightthickness=1,
                                                  highlightcolor='#dcdde1')
        self.log_area.pack(expand=True, fill=tk.BOTH)

        # ----- 底部控制按钮 -----
        ctrl_frame = ttk.Frame(main_container, style='TFrame')
        ctrl_frame.pack(fill=tk.X)
        self.start_btn = ttk.Button(ctrl_frame, text="▶ 开始运行 (F1)", style='Success.TButton',
                                    command=self.start, width=18)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn = ttk.Button(ctrl_frame, text="■ 停止 (F2)", style='Danger.TButton',
                                   command=self.stop, state='disabled', width=16)
        self.stop_btn.pack(side=tk.LEFT, padx=8)
        self.help_btn = ttk.Button(ctrl_frame, text="? 使用说明", style='TButton',
                                   command=self.show_help, width=12)
        self.help_btn.pack(side=tk.LEFT, padx=(20, 8))
        self.settings_btn = ttk.Button(ctrl_frame, text="⚙ 设置", style='TButton',
                                       command=self.open_settings, width=10)
        self.settings_btn.pack(side=tk.LEFT, padx=8)
        self.qq_login_btn = ttk.Button(ctrl_frame, text="QQ一键登录", style='TButton',
                                       command=self.trigger_qq_login, width=14)
        self.qq_login_btn.pack(side=tk.LEFT, padx=(8, 0))

    def _redirect_output(self):
        sys.stdout = RedirectText(self.log_area, self._log_file_path)
        sys.stderr = RedirectText(self.log_area, self._log_file_path)

    def apply_auto_settings_from_window(self):
        """从设置窗口保存后应用自动任务设置"""
        if self.settings.get("auto_start", False):
            self._start_scheduler()
        else:
            print("⏰ 已取消定时执行")
            # 取消旧定时器
            if self._wake_timer_handle:
                utils.cancel_wake_timer(self._wake_timer_handle)
                self._wake_timer_handle = None

    def open_settings(self):
        if self._settings_window and self._settings_window.win.winfo_exists():
            self._settings_window.win.lift()
            self._settings_window.win.focus_force()
            return
        self._settings_window = SettingsWindow(self.root, self)
        self._settings_window.win.protocol("WM_DELETE_WINDOW", self._on_settings_close)

    def _on_settings_close(self):
        if self._settings_window:
            self._settings_window.win.destroy()
            self._settings_window = None

    def update_confidence_display(self):
        pass

    # ---------- 原有功能 ----------
    def show_help(self):
        help_text = (
            "【使用说明】\n\n"
            "━━━ 基本操作 ━━━\n"
            "1. WeGame 快捷登录：添加 QQ 号截图 → 点击运行，自动完成快捷登录。\n"
            "2. QQ 自动登录：在设置中配置 QQ 路径和账号，仅在开机自启动时自动登录。\n"
            "3. 点击主界面「QQ一键登录」按钮可随时手动执行 QQ 登录，运行中可暂停/继续。\n"
            "4. 点击「开始运行」或按 F1 键启动脚本，按 F2 键或点击「停止」终止。\n"
            "5. 可在设置中调整图像匹配置信度（0.50-0.95），值越高匹配越严格。\n\n"
            "━━━ 定时执行 ━━━\n"
            "6. 在「设置 → 自动任务设置」中启用定时执行。\n"
            "7. 可设置多个时间点（HH:MM），支持「单次」和「每日循环」两种模式。\n"
            "8. 勾选需要执行的操作（技术中心/工作台/防具台/制药台），可多选。\n"
            "9. 支持静默运行（最小化到系统托盘），右键托盘图标可退出。\n\n"
            "━━━ 运行提醒 ━━━\n"
            "10. 在设置中开启「运行前提醒弹窗」，可选提前1~15分钟。\n"
            "    到达提醒时间后弹出窗口，可「立即运行」或「取消本次」。\n"
            "    【注意】取消本次运行后，不会影响后续时间点的定时任务。\n\n"
            "━━━ 电源管理 ━━━\n"
            "11. 唤醒电脑：定时运行前自动唤醒系统，并尝试点亮显示器。\n"
            "    如果在唤醒后屏幕仍然黑屏，程序会自动发送按键/鼠标信号唤醒显示器。\n"
            "12. 自动关机：设定关机时间，到达后自动关闭电脑。\n"
            "13. 定时开机：设定开机时间，电脑在睡眠/休眠状态时可自动唤醒。\n"
            "    完全关机需主板支持 RTC 唤醒，请在 BIOS 中启用「定时开机」功能。\n\n"
            "━━━ QQ 自动登录 ━━━\n"
            "14. 在设置 → 自动任务设置中配置 QQ 账号截图并勾选「开机时自动登录QQ」。\n"
            "15. QQ 登录仅在程序通过【开机自启动】运行时自动触发，双击启动不会自动登录。\n"
            "    登录过程中可点击「暂停」按钮暂停执行，点击「继续」恢复。\n"
            "16. 也可点击主界面的「QQ一键登录」按钮随时手动触发 QQ 登录。\n\n"
            "━━━ 注意事项 ━━━\n"
            "17. 脚本依赖固定图片识别，请保持屏幕分辨率和缩放比例一致。\n"
            "18. 若某个步骤超时，脚本会跳过当前账号并继续下一个。\n"
            "19. 点击停止后，当前步骤完成后才会退出（或强制结束进程）。\n"
            "20. 所有日志显示在下方区域，如遇问题可截图反馈。\n"
            "21. 定时执行前5分钟程序会尝试唤醒系统和显示器，请确保电脑处于休眠/睡眠状态，\n"
            "    而非完全关机。完全关机需主板支持 RTC 唤醒。"
        )
        messagebox.showinfo("使用说明", help_text)

    # ---------- 账号持久化 ----------
    def save_accounts(self):
        try:
            data = {"wegame": self.account_images, "qq": self.qq_account_images}
            with open(ACCOUNTS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存账号列表失败：{e}")

    def load_accounts(self):
        if not os.path.exists(ACCOUNTS_JSON_PATH):
            return
        try:
            with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧格式（纯列表 → 仅 WeGame）
            if isinstance(data, list):
                self.account_images = [p for p in data if os.path.exists(p)]
                self.qq_account_images = []
            else:
                self.account_images = [p for p in data.get("wegame", []) if os.path.exists(p)]
                self.qq_account_images = [p for p in data.get("qq", []) if os.path.exists(p)]
            # 刷新 WeGame 列表
            self.account_listbox.delete(0, tk.END)
            for p in self.account_images:
                self.account_listbox.insert(tk.END, os.path.basename(p))
            total = len(self.account_images) + len(self.qq_account_images)
            print(f"✅ 已加载 {len(self.account_images)} 个 WeGame 账号、{len(self.qq_account_images)} 个 QQ 账号")
        except Exception as e:
            print(f"⚠️ 加载历史账号失败：{e}")

    def add_account(self):
        file_path = filedialog.askopenfilename(
            title="选择 QQ 号截图",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")]
        )
        if file_path:
            self.account_images.append(file_path)
            self.account_listbox.insert(tk.END, os.path.basename(file_path))
            self.update_account_count()
            self.save_accounts()

    def delete_account(self):
        sel = self.account_listbox.curselection()
        if sel:
            idx = sel[0]
            self.account_listbox.delete(idx)
            del self.account_images[idx]
            self.update_account_count()
            self.save_accounts()

    def clear_accounts(self):
        self.account_listbox.delete(0, tk.END)
        self.account_images.clear()
        self.update_account_count()
        self.save_accounts()

    def update_account_count(self):
        self.total_steps = len(self.account_images) * 4
        self.progress['maximum'] = max(1, self.total_steps)

    # ---------- 账号排序 ----------
    def _move_up(self):
        sel = self.account_listbox.curselection()
        if sel and sel[0] > 0:
            idx = sel[0]
            self.account_images[idx], self.account_images[idx-1] = self.account_images[idx-1], self.account_images[idx]
            self._refresh_account_list()
            self.account_listbox.selection_set(idx-1)

    def _move_down(self):
        sel = self.account_listbox.curselection()
        if sel and sel[0] < len(self.account_images) - 1:
            idx = sel[0]
            self.account_images[idx], self.account_images[idx+1] = self.account_images[idx+1], self.account_images[idx]
            self._refresh_account_list()
            self.account_listbox.selection_set(idx+1)

    def _refresh_account_list(self):
        self.account_listbox.delete(0, tk.END)
        for p in self.account_images:
            self.account_listbox.insert(tk.END, os.path.basename(p))
        self.save_accounts()

    # ---------- 账号右键菜单 ----------
    def _show_account_menu(self, event):
        try:
            sel = self.account_listbox.nearest(event.y)
            self.account_listbox.selection_clear(0, tk.END)
            self.account_listbox.selection_set(sel)
            self.account_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.account_menu.grab_release()

    def _test_recognition(self):
        sel = self.account_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个账号")
            return
        idx = sel[0]
        img_path = self.account_images[idx]
        if not os.path.exists(img_path):
            messagebox.showerror("错误", "截图文件不存在")
            return
        try:
            import cv2
            import numpy as np
            screen = pyautogui.screenshot()
            screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
            template = cv2.imread(img_path, 0)
            if template is None:
                messagebox.showerror("错误", "无法读取截图文件")
                return
            gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            conf = int(max_val * 100)
            threshold = int(config.CONFIDENCE * 100)
            status = "✅ 可识别" if max_val >= config.CONFIDENCE else "❌ 匹配度不足"
            messagebox.showinfo(
                "测试结果",
                f"截图：{os.path.basename(img_path)}\n"
                f"匹配度：{conf}% (阈值：{threshold}%)\n"
                f"最高匹配位置：{max_loc}\n"
                f"结论：{status}"
            )
        except Exception as e:
            messagebox.showerror("测试失败", f"识别过程出错：{e}")

    # ---------- 启停控制 ----------
    def start(self):
        if self.running:
            return
        if self._qq_running:
            messagebox.showwarning("提示", "QQ 登录正在运行，请先暂停或等待完成后，再开始脚本")
            return
        if not self.account_images:
            messagebox.showwarning("未添加账号", "请先添加至少一个 WeGame 账号截图！")
            return
        self.running = True
        self._stop_event.clear()
        self.current_step = 0
        self.progress['value'] = 0
        self.stats_label.config(text="")
        self.run_stats = {"total": 0, "success": 0, "fail": 0, "start_time": time.time()}
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.log_area.configure(state='normal')
        self.log_area.delete('1.0', tk.END)
        self.log_area.configure(state='disabled')
        # 阻止系统睡眠，确保脚本执行不中断
        utils.prevent_sleep()
        self.work_thread = threading.Thread(target=self.run_script_main, daemon=True)
        self.work_thread.start()

    def stop(self):
        if not self.running:
            return
        self._stop_event.set()
        self.running = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        print("\n⏹ 停止信号已发送，将尽快终止...")

    def update_ui(self, step_increment=False, account_text=None, account_file=None):
        if step_increment:
            self.current_step += 1
            self.progress['value'] = self.current_step
        if account_text:
            self.account_label.config(text=account_text)
        if account_file:
            self.current_account_file_label.config(text=account_file)

    def set_operation(self, text):
        """从工作线程安全更新当前操作状态文字"""
        self.root.after(0, lambda: self.op_label.config(text=text))

    # ---------- QQ 自动登录 ----------
    def _auto_login_qq(self):
        """在后台线程中执行 QQ 自动登录"""
        if self.running:
            print("⚠️ 脚本正在运行，跳过 QQ 自动登录")
            return
        if self._qq_running:
            return
        self._qq_running = True
        self._qq_pause_event.set()  # 确保未暂停
        self.root.after(0, lambda: self.qq_login_btn.config(text="暂停"))
        threading.Thread(target=self._run_qq_login_phase, daemon=True).start()

    def trigger_qq_login(self):
        """QQ登录按钮点击处理：根据运行状态执行启动/暂停/继续"""
        if self.running:
            messagebox.showwarning("提示", "脚本正在运行，请先停止后再执行 QQ 登录")
            return
        if self._qq_running:
            self._toggle_qq_pause()
            return
        # 未运行 → 启动
        qq_path = self.settings.get("qq_path", "")
        if not qq_path:
            messagebox.showwarning("提示", "请先在设置中配置 QQ.exe 路径")
            return
        if not self.qq_account_images:
            messagebox.showwarning("提示", "请先在设置中添加 QQ 账号截图")
            return
        self._auto_login_qq()

    def _toggle_qq_pause(self):
        """切换QQ登录暂停/继续"""
        if not self._qq_running:
            return
        if self._qq_pause_event.is_set():
            # 运行中 → 暂停
            self._qq_pause_event.clear()
            print("⏸ QQ 登录已暂停")
            self.qq_login_btn.config(text="继续")
        else:
            # 已暂停 → 继续
            self._qq_pause_event.set()
            print("▶️ QQ 登录已继续")
            self.qq_login_btn.config(text="暂停")

    def _on_qq_login_finish(self):
        """QQ登录完成后的UI恢复"""
        self._qq_running = False
        self.qq_login_btn.config(text="QQ一键登录")

    # ---------- QQ 自动登录阶段 ----------
    def _run_qq_login_phase(self):
        """脚本执行前先完成所有 QQ 账号的自动登录"""
        try:
            qq_path = self.settings.get("qq_path", "")
            if not qq_path or not self.qq_account_images:
                return

            total = len(self.qq_account_images)
            print("\n" + "=" * 40)
            print(f"  QQ 自动登录阶段（共 {total} 个账号）")
            print("=" * 40)

            for i, img_path in enumerate(self.qq_account_images):
                if self._stop_event.is_set():
                    break

                # 暂停检查：暂停时阻塞，直到继续或收到停止信号
                while not self._qq_pause_event.is_set():
                    if self._stop_event.wait(timeout=0.5):
                        break
                if self._stop_event.is_set():
                    print("⏹ QQ 登录已停止")
                    break

                file_name = os.path.basename(img_path)
                print(f"\n--- QQ 登录 {i+1}/{total}：{file_name} ---")

                # 启动 QQ
                self.set_operation(f"启动 QQ ({i+1}/{total})")
                if not utils.start_app(qq_path, "QQ"):
                    print("❌ QQ 启动失败，跳过")
                    continue
                time.sleep(5)

                if self._stop_event.is_set(): break
                self.set_operation("QQ 快捷登录")
                if not utils.qq_quick_login(img_path):
                    print("❌ QQ 快捷登录失败")
                    utils.kill_process(config.QQ_PROCESS)
                    continue

                # 等待登录完成，然后关闭 QQ 窗口（保留后台进程）
                time.sleep(3)
                utils.close_window_by_title("QQ", partial_match=True)
                time.sleep(2)
                time.sleep(2)

            print("✅ QQ 自动登录阶段完成\n")
        finally:
            self.root.after(0, self._on_qq_login_finish)

    # ---------- 主流程 ----------
    def run_script_main(self):
        try:
            total = len(self.account_images)
            print("=" * 55)
            print("  WeGame 快捷登录 + 三角洲行动 多账号轮换脚本")
            print(f"  本轮将处理 {total} 个 WeGame 账号")
            print("=" * 55)

            for i, img_path in enumerate(self.account_images):
                if self._stop_event.is_set():
                    break

                file_name = os.path.basename(img_path)
                acc_text = f"第 {i+1}/{total} 个账号"
                self.root.after(0, self.update_ui, False, acc_text, file_name)
                print(f"\n{'='*40}")
                print(f"    {acc_text}  -  {file_name}")
                print(f"{'='*40}")
                self.run_stats["total"] += 1
                account_failed = False

                if self._stop_event.is_set(): break
                self.set_operation("启动 WeGame")
                print("启动 WeGame...")
                if not config.WEGAME_PATH or not utils.start_app(config.WEGAME_PATH, "WeGame"):
                    print("❌ WeGame 启动失败，跳过此账号")
                    account_failed = True
                if not account_failed:
                    time.sleep(8)

                if not account_failed and self._stop_event.is_set(): break
                if not account_failed:
                    self.set_operation("快捷登录 WeGame")
                    print("开始快捷登录 WeGame ...")
                    if not utils.wegame_quick_login(img_path):
                        print("❌ WeGame 快捷登录失败，跳过此账号")
                        utils.kill_process(config.WEGAME_PROCESS)
                        account_failed = True
                    else:
                        time.sleep(3)

                if not account_failed and self._stop_event.is_set(): break
                if not account_failed:
                    self.set_operation("查找三角洲游戏图标")
                    print("\n--- 启动三角洲行动 ---")
                    utils.activate_window_by_title("WeGame", partial_match=True)
                    time.sleep(2)

                    delta_icon_found = False
                    for retry in range(3):
                        if self._stop_event.is_set(): break
                        if utils.find_and_click(config.DELTA_GAME_ICON, timeout=15):
                            delta_icon_found = True
                            break
                        print(f"⚠️ 未找到三角洲游戏图标，3秒后重试 ({retry+1}/3)...")
                        time.sleep(3)
                    if not delta_icon_found:
                        print("❌ 多次重试后仍未找到三角洲游戏图标，跳过此账号")
                        utils.kill_process(config.WEGAME_PROCESS)
                        account_failed = True

                if not account_failed:
                    time.sleep(2)

                    launch_found = False
                    for retry in range(3):
                        if self._stop_event.is_set(): break
                        if utils.find_and_click(config.DELTA_LAUNCH_BTN, timeout=15):
                            launch_found = True
                            break
                        print(f"⚠️ 未找到启动按钮，3秒后重试 ({retry+1}/3)...")
                        time.sleep(3)
                    if not launch_found:
                        print("❌ 多次重试后仍未找到启动按钮，跳过此账号")
                        utils.kill_process(config.WEGAME_PROCESS)
                        account_failed = True

                if not account_failed:
                    print("✅ 三角洲正在启动，等待游戏加载...")
                    time.sleep(25)

                    self._game_operations()
                    if self._stop_event.is_set(): break

                    self.set_operation("关闭三角洲游戏")
                    print("\n--- 关闭三角洲游戏 ---")
                    delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
                    for title in delta_titles:
                        if self._stop_event.is_set(): break
                        utils.close_window_by_title(title, partial_match=True)
                    time.sleep(2)
                    utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)

                    self.set_operation("关闭 WeGame")
                    print("\n--- 关闭 WeGame ---")
                    utils.close_window_by_title("WeGame", partial_match=True)
                    time.sleep(2)
                    utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
                    time.sleep(3)

                if account_failed:
                    self.run_stats["fail"] += 1
                else:
                    self.run_stats["success"] += 1

            print("\n🎉 所有账号处理完毕！")
        except Exception as e:
            print(f"❌ 运行出错: {e}")
        finally:
            self.root.after(0, self.on_finish)

    def _game_operations(self):
        print("\n--- 进入游戏操作 ---")
        self.set_operation("进入烽火地带")
        print("进入烽火地带...")
        for retry in range(3):
            if self._stop_event.is_set(): return
            if utils.find_and_click(config.Hazard_Operations, timeout=15):
                break
            print(f"⚠️ 未找到烽火地带图标，5秒后重试 ({retry + 1}/3)...")
            time.sleep(5)
        else:
            print("❌ 多次重试后仍未找到烽火地带图标")
            utils.kill_process(config.DELTA_PROCESS, wait_exit=False)
            return

        time.sleep(5)
        self.set_operation("进入大厅 / 特勤处")
        print("进入大厅...")
        pyautogui.press("Space")
        time.sleep(0.5)
        pyautogui.press("Space")
        time.sleep(0.5)
        pyautogui.press("Tab")
        time.sleep(1)

        for retry in range(3):
            if self._stop_event.is_set(): return
            if utils.find_and_click(config.Special_Ops, timeout=15):
                break
            print(f"⚠️ 未找到特勤处图标，5秒后重试 ({retry + 1}/3)...")
            time.sleep(5)
        else:
            print("❌ 多次重试后仍未找到特勤处图标")
            utils.kill_process(config.DELTA_PROCESS, wait_exit=False)
            return
        time.sleep(0.5)

        selected_ops = self.settings.get("selected_operations", [])
        all_facilities = [
            ("tech_center", config.Tech_Center, config.Produce_TechCenter, "技术中心"),
            ("tool_bench", config.Tool_Bench, config.Produce_ToolBench, "工作台"),
            ("armor_station", config.Armor_Station, config.Produce_ArmorStation, "防具台"),
            ("pharmacy_station", config.Pharmacy_Station, config.Produce_PharmacyStation, "制药台"),
        ]
        facilities = [(f[1], f[2], f[3]) for f in all_facilities if f[0] in selected_ops]
        if not facilities:
            print("ℹ️ 未选择任何设施操作，跳过游戏内操作")
            return
        op_names = [f[3] for f in all_facilities if f[0] in selected_ops]
        print(f"🔧 将执行：{'、'.join(op_names)}")
        for fac_img, prod_img, fac_name in facilities:
            if self._stop_event.is_set(): break
            self.set_operation(f"处理 {fac_name}")
            if not self._handle_facility(fac_img, prod_img, fac_name):
                if not self._stop_event.is_set():
                    print(f"❌ 处理{fac_name}失败，终止当前账号")
                    utils.kill_process(config.DELTA_PROCESS, wait_exit=False)
                    utils.kill_process(config.WEGAME_PROCESS)
                break
            pyautogui.press("esc")
            time.sleep(0.5)
        else:
            print("✅ 所有设施处理完成")

    def _handle_facility(self, facility_img, produce_item_img, facility_name):
        if self._stop_event.is_set(): return False
        print(f"🏭 开始处理 {facility_name} ...")
        if not utils.find_and_click(facility_img, timeout=15): return False
        time.sleep(0.5)

        if not utils.find_and_click(config.MAKE, timeout=15): return False
        time.sleep(0.5)

        if not utils.find_and_click(config.Collect, timeout=15): return False
        time.sleep(0.5)

        if not utils.find_and_click(config.Claim_Reward, timeout=15): return False
        time.sleep(0.5)

        if not utils.find_and_click(produce_item_img, timeout=15): return False
        time.sleep(0.5)

        if utils.find_and_click(config.Auto_fill, timeout=8):
            print(f"🔧 一键补齐材料 ({facility_name})")
        else:
            print(f"ℹ️ 材料已足够，无需补齐 ({facility_name})")
        time.sleep(0.5)

        buy_attempts = 0
        while utils.find_and_click(config.COIN_GAME, timeout=5):
            if self._stop_event.is_set(): return False
            print(f"💰 购买材料 ({buy_attempts + 1}/5)")
            time.sleep(0.5)
            buy_attempts += 1
            if buy_attempts >= 5:
                print("⚠️ 购买尝试已达上限，可能价格波动频繁")
                break

        if not utils.find_and_click(config.Produce, timeout=15): return False
        time.sleep(0.5)

        pyautogui.press("esc")
        time.sleep(0.5)
        print(f"✅ {facility_name} 处理完毕")
        self.root.after(0, self.update_ui, True)
        return True

    def on_finish(self):
        self.running = False
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.progress['value'] = self.progress['maximum']

        # 恢复系统睡眠设置
        utils.allow_sleep()

        # 设置下一次唤醒定时器
        self._set_next_wake_timer()

        # 显示运行统计
        stats = self.run_stats
        elapsed = time.time() - stats["start_time"] if stats["start_time"] else 0
        if stats["total"] > 0 and elapsed > 0:
            m, s = divmod(int(elapsed), 60)
            h, m = divmod(m, 60)
            if h > 0:
                time_str = f"{h}时{m}分{s}秒"
            else:
                time_str = f"{m}分{s}秒"
            stats_text = (f"📊 本轮：共 {stats['total']} 个账号  "
                          f"✅ {stats['success']} 成功  "
                          f"❌ {stats['fail']} 失败  "
                          f"⏱ 耗时 {time_str}")
            self.stats_label.config(text=stats_text)
            print(f"\n{'='*40}")
            print(f"   {stats_text}")
            print(f"{'='*40}")


# ==================== 联网时间校验 ====================
def get_network_time():
    urls = [
        "http://quan.suning.com/getSysTime.do",
        "http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp",
    ]
    for attempt in range(3):
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=8) as resp:
                    data = resp.read().decode('utf-8')
                    if "sysTime2" in data:
                        obj = json.loads(data)
                        dt_str = obj["sysTime2"]
                        date_part = dt_str.split(" ")[0]
                        return datetime.date(*map(int, date_part.split("-")))
                    if "mtopjsonp" in data:
                        match = re.search(r'"t"\s*:\s*"(\d+)"', data)
                        if match:
                            timestamp = int(match.group(1)) / 1000.0
                            dt = datetime.datetime.fromtimestamp(timestamp)
                            return dt.date()
            except Exception:
                continue
        time.sleep(0.5)
    return None


def main():
    config.APP_SETTINGS = config.init_settings()
    config.WEGAME_PATH = config.APP_SETTINGS.get("wegame_path", "")
    config.CONFIDENCE = config.APP_SETTINGS["confidence"]

    net_date = get_network_time()
    if net_date is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("网络错误", "无法连接时间服务器，请检查网络后重试。")
        sys.exit(1)
    if net_date > EXPIRY_DATE:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("软件已过期", f"该版本已于 {EXPIRY_DATE} 到期。\n当前网络日期：{net_date}")
        sys.exit(1)

    root = tk.Tk()
    App(root)
    # 窗口显示到前台
    root.after(50, lambda: (root.lift(), root.focus_force()))
    root.after(50, lambda: root.attributes('-topmost', True))
    root.after(200, lambda: root.attributes('-topmost', False))
    root.mainloop()


if __name__ == "__main__":
    main()
