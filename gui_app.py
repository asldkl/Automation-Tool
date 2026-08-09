"""
图形用户界面模块
包含多账号管理、游戏内操作、停止机制及快捷键
支持账号列表本地持久化、启动联网时间校验、冷却执行、开机自启动
"""
import os
import sys
import time
import json
import datetime
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

import config
import utils
import cooldown_manager
import machine_fingerprint
from settings_window import SettingsWindow

# 拆分模块
import email_notifier
import account_manager
import scheduler as sched
import cooldown_watcher
import server_client
import automation_runner

# 尝试导入托盘所需库
try:
    import pystray
    from PIL import Image, ImageTk
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# -------------------- 有效期由服务器端统一校验 --------------------

ACCOUNTS_JSON_PATH = os.path.join(config.APP_DATA_DIR, "accounts.json")


# ==================== PyQt6 遮罩日志组件（可选叠加层） ====================
# 默认开启、延迟加载：仅在开启时初始化 PyQt6，关闭时销毁释放内存
_qt_overlay = None           # ScreenLogOverlay 实例
_qt_app = None               # QApplication 实例（防止被 GC）
_qt_pump_scheduled = False   # Qt 事件泵送是否已排队（合并重复请求）
_qt_manual_hide = False      # 用户主动隐藏遮罩（屏幕取点/框选截图时临时隐藏，看门狗不恢复）


def _classify_log_level(message):
    """根据日志内容推断级别：3=ERROR, 2=WARN, 1=INFO（供遮罩日志着色）"""
    if any(k in message for k in ("❌", "失败", "Error", "error", "异常", "跳过", "无法", "错误")):
        return 3  # ERROR（红）
    if any(k in message for k in ("⚠️", "警告", "WARN", "未找到", "未能", "可能")):
        return 2  # WARN（黄）
    return 1  # INFO（浅蓝）


def _schedule_qt_pump(root):
    """排队一次 Qt 事件泵送（合并重复请求）
    仅在日志到达或遮罩开启时触发，空闲时不泵送，
    避免遮罩 UpdateLayeredWindow 重绘干扰 Tk 窗口拖拽导致回弹"""
    global _qt_pump_scheduled
    if _qt_pump_scheduled:
        return
    _qt_pump_scheduled = True
    try:
        root.after(20, lambda: _pump_qt_once(root))
    except Exception:
        _qt_pump_scheduled = False


def _pump_qt_once(root):
    """泵送一次 Qt 事件：交付队列中的日志并重绘遮罩（非连续）"""
    global _qt_pump_scheduled
    _qt_pump_scheduled = False
    if _qt_overlay is None or _qt_app is None:
        return
    try:
        _qt_app.processEvents()
    except Exception:
        pass
    # 交互模式（可拖动遮罩）需要连续泵送处理鼠标事件；穿透模式（默认）空闲即停
    try:
        if not _qt_overlay._transparent_input:
            _schedule_qt_pump(root)
    except Exception:
        pass


# ==================== 遮罩可见性看门狗 ====================
_qt_watchdog_running = False


def _start_qt_watchdog(root):
    """启动遮罩可见性看门狗（每 1 秒检查一次）
    解决：游戏独占全屏时 Windows 会隐藏遮罩窗口，事件驱动泵送在无日志时不处理
    重新显示消息，导致遮罩在账号切换时看起来"被关闭"。看门狗检测到遮罩不可见时重新 show。
    仅在遮罩不可见时动作，拖拽时遮罩可见 → 不干扰，不影响拖拽修复。
    """
    global _qt_watchdog_running
    if _qt_watchdog_running:
        return
    _qt_watchdog_running = True
    root.after(1000, lambda: _qt_watchdog_tick(root))


def _qt_watchdog_tick(root):
    global _qt_watchdog_running, _qt_overlay
    try:
        if _qt_overlay is not None:
            try:
                visible = _qt_overlay.isVisible()
            except RuntimeError:
                # 遮罩被意外销毁（如 Qt 窗口被外部关闭）→ 重新创建
                print("🔄 日志遮罩被销毁，正在重新创建...")
                _qt_overlay = None
                enable_log_overlay(root)
                root.after(1000, lambda: _qt_watchdog_tick(root))
                return
            if not visible and not _qt_manual_hide:
                # 遮罩被 Windows 隐藏（如游戏独占全屏）→ 重新显示；手动隐藏时跳过
                try:
                    _qt_overlay.show()
                    print("📊 日志遮罩重新显示（被全屏游戏隐藏后恢复）")
                except Exception:
                    pass
                try:
                    _qt_app.processEvents()
                except Exception:
                    pass
        root.after(1000, lambda: _qt_watchdog_tick(root))
    except Exception:
        try:
            root.after(1000, lambda: _qt_watchdog_tick(root))
        except Exception:
            _qt_watchdog_running = False


def enable_log_overlay(root):
    """开启日志遮罩（延迟加载 PyQt6；失败不影响主程序）"""
    global _qt_overlay, _qt_app
    if _qt_overlay is not None:
        return
    try:
        from PyQt6.QtWidgets import QApplication
        from screen_log_overlay import ScreenLogOverlay

        _qt_app = QApplication.instance()
        if _qt_app is None:
            _qt_app = QApplication([])
        _qt_overlay = ScreenLogOverlay(max_lines=500, translucent_bg=False)
        _qt_overlay.show()
        # 开启提示：告知如何关闭（遮罩鼠标穿透，需通过托盘菜单或实验功能窗口关闭）
        _qt_overlay.info("💡 日志遮罩：关闭请在 托盘菜单「日志遮罩」或「实验功能」窗口操作")
        _schedule_qt_pump(root)
        _start_qt_watchdog(root)
        print("📊 日志遮罩已开启（左下角透明日志层；关闭：托盘菜单「日志遮罩」或「实验功能」窗口）")
    except Exception as e:
        _qt_overlay = None
        print(f"⚠️ 日志遮罩开启失败（不影响主程序）：{e}")


def disable_log_overlay():
    """关闭日志遮罩（销毁组件释放 PyQt6 内存）"""
    global _qt_overlay
    if _qt_overlay is not None:
        try:
            _qt_overlay._allow_close = True  # 程序主动关闭，放行 closeEvent
            _qt_overlay.close()
            _qt_overlay.deleteLater()
        except Exception:
            pass
        _qt_overlay = None
    print("📊 日志遮罩已关闭")


def toggle_log_overlay(root):
    """切换日志遮罩开/关，返回开启状态"""
    if _qt_overlay is not None:
        disable_log_overlay()
    else:
        enable_log_overlay(root)
    return _qt_overlay is not None


def hide_log_overlay():
    """临时隐藏日志遮罩（不销毁，保留日志内容）
    用于屏幕取点/框选截图：置顶遮罩会挡住点击，取点前隐藏、取完恢复"""
    global _qt_manual_hide
    _qt_manual_hide = True
    if _qt_overlay is not None:
        try:
            _qt_overlay.hide()
        except Exception:
            pass


def show_log_overlay():
    """恢复显示日志遮罩（与 hide_log_overlay 成对使用）"""
    global _qt_manual_hide
    _qt_manual_hide = False
    if _qt_overlay is not None:
        try:
            _qt_overlay.show()
        except Exception:
            pass


class RedirectText:
    """将标准输出重定向到 Tkinter 文本框，可选同时写入日志文件（线程安全，缓冲写入）"""
    def __init__(self, text_widget, root, log_path=None):
        self.text_widget = text_widget
        self.root = root
        self.log_path = log_path
        self._log_buffer = []
        self._log_file = None
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            try:
                self._log_file = open(log_path, 'a', encoding='utf-8')
            except Exception:
                pass

    def write(self, message):
        try:
            # 从后台线程安全地更新 UI
            self.root.after(0, self._insert_text, message)
        except Exception:
            pass
        # 转发到 PyQt6 遮罩日志（线程安全：内部走 Qt 信号槽）
        if _qt_overlay is not None and message.strip():
            try:
                _qt_overlay.add_log(_classify_log_level(message), message.strip())
                # 事件驱动泵送：有日志才处理 Qt 事件，空闲不泵送（避免干扰 Tk 拖拽）
                _schedule_qt_pump(self.root)
            except Exception:
                pass
        if self._log_file and message.strip():
            try:
                self._log_file.write(message)
                self._log_file.flush()
            except Exception:
                pass

    def set_log_path(self, log_path):
        """切换日志文件（关闭旧文件，打开新文件）"""
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None
        self.log_path = log_path
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            try:
                self._log_file = open(log_path, 'a', encoding='utf-8')
            except Exception:
                pass

    def close(self):
        """关闭日志文件"""
        if self._log_file:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

    def _insert_text(self, message):
        """在主线程中插入文本到文本框"""
        try:
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, message)
            self.text_widget.see(tk.END)
            self.text_widget.configure(state='disabled')
        except Exception:
            pass

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("三角洲行动自动化工具")
        self.root.resizable(True, True)
        self.root.minsize(500, 600)
        self.running_event = threading.Event()
        self._shutdown = False
        self._consecutive_failures = {}  # 账号名 -> 连续失败次数
        self.qq_account_images = []
        self._account_assets = {}
        self._asset_history = {}
        self._account_notes = {}
        self._current_account_name = None
        self._stop_event = threading.Event()
        self._scheduler_stop_event = threading.Event()
        self._schedule_thread = None
        self._settings_window = None
        self._wake_timer_handle = None
        self._last_wake_time = None
        self._ignore_cooldown_this_run = False
        self._is_boot_startup = False
        self._user_stopped_cooldown = False
        # 窗口图标（失败时重试一次）
        self._icon_photo = None
        if not self._set_window_icon():
            self.root.after(500, self._set_window_icon)

        # 加载设置
        self.settings = config.APP_SETTINGS
        config.WEGAME_PATH = self.settings.get("wegame_path", "")
        config.CONFIDENCE = self.settings["confidence"]

        # 服务器验证（异步，不阻塞 UI 线程）
        self._server_validated = False
        self._server_expiry = None
        self._machine_id = ""  # 由后台验证线程填充（WMI 查询不阻塞 UI）

        # 显示加载提示，后台执行验证
        self._loading_label = ttk.Label(self.root, text="正在验证许可证...",
                                        font=('Microsoft YaHei UI', 11), foreground="#666")
        self._loading_label.pack(expand=True)
        self._validate_thread = threading.Thread(target=self._async_validate, daemon=True)
        self._validate_thread.start()
        self.root.after(200, self._check_validate_result)
        return

    def _async_validate(self):
        """后台线程执行服务器验证"""
        try:
            # 后台线程获取机器指纹（WMI 查询慢时不阻塞 UI，且已有缓存不重复耗时）
            try:
                self._machine_id = machine_fingerprint.get_machine_id()
            except Exception:
                self._machine_id = "获取失败"
            self._validate_result = server_client.validate_with_server(self)
        except Exception as e:
            self._validate_result = (None, None, f"服务器验证异常: {e}")

    def _check_validate_result(self):
        """轮询验证结果，完成后继续初始化或退出"""
        if self._validate_thread.is_alive():
            self.root.after(200, self._check_validate_result)
            return
        # 验证完成，处理结果
        allowed, expiry, error = self._validate_result
        if allowed is True:
            self._server_validated = True
            self._server_expiry = expiry
            print(f"✅ 服务器验证通过，有效期至：{expiry}")
            self._loading_label.destroy()
            self._continue_init()
        elif allowed is False:
            print(f"❌ 服务器验证失败：{error}")
            messagebox.showerror("验证失败",
                f"程序无法启动：{error}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"本机机器指纹（请发送给管理员）：\n\n"
                f"  {self._machine_id}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━")
            self.root.destroy()
        else:
            print(f"❌ 服务器验证失败：{error}")
            messagebox.showerror("验证失败",
                f"无法连接到验证服务器，程序无法启动。\n\n"
                f"错误信息：{error}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"本机机器指纹（请发送给管理员）：\n\n"
                f"  {self._machine_id}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"请将此指纹发送给管理员添加白名单。")
            self.root.destroy()

    def _continue_init(self):
        """服务器验证通过后继续初始化"""
        root = self.root
        # 心跳相关
        self._heartbeat_thread = None
        self._heartbeat_stop = None
        self._account_status = {}

        # 运行统计
        self.run_stats = {"total": 0, "success": 0, "fail": 0, "start_time": None}

        # 日志文件路径（初始 startup.log，每次运行时自动切换）
        log_dir = self.settings.get("log_save_path", "")
        if log_dir:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            date_dir = os.path.join(log_dir, today)
            os.makedirs(date_dir, exist_ok=True)
            self._log_file_path = os.path.join(date_dir, "startup.log")
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
        self._start_periodic_tree_refresh()

        # 托盘
        self.tray_icon = None
        self._setup_tray()

        # 单实例前台显示事件
        self._setup_show_event()

        # 冷却完立即运行
        if self.settings.get("cooldown_run_immediately", False):
            self._start_cooldown_watcher()

        # 开机自启动检测
        is_auto_start = '--auto-start' in sys.argv
        if is_auto_start:
            print("🔄 检测到开机自启动标志 (--auto-start)")
            if self.settings.get("run_on_startup", False) and self.qq_account_images:
                print("🔄 开机立即运行已启用，将在 2 秒后自动执行任务...")
                self._is_boot_startup = True
                self.root.after(2000, self.start)
            else:
                print(f"ℹ️ 开机立即运行未启用 (run_on_startup={self.settings.get('run_on_startup', False)}, "
                      f"账号数={len(self.qq_account_images)})")

        # 冷却到期信号文件检查（定时任务兜底机制）
        # 启动时立即检查一次（不等 30 秒），之后每 30 秒检查
        self.root.after(2000, self._check_cooldown_signal)

        # 关闭按钮 → 最小化到托盘
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================== 线程安全属性 ====================
    @property
    def running(self):
        return self.running_event.is_set()

    def _set_window_icon(self):
        """设置窗口图标，返回 True=成功"""
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
            if os.path.exists(icon_path):
                from PIL import Image, ImageTk
                self._icon_photo = ImageTk.PhotoImage(Image.open(icon_path))
                self.root.iconphoto(False, self._icon_photo)
                return True
        except Exception:
            pass
        return False

    @running.setter
    def running(self, value):
        if value:
            self.running_event.set()
        else:
            self.running_event.clear()

    # ==================== 样式 ====================
    def _setup_styles(self):
        """配置浅色主题 ttk 样式（参考 themes/light.qss 色板）"""
        style = ttk.Style()
        available_themes = style.theme_names()
        if 'clam' in available_themes:
            style.theme_use('clam')

        # 浅色主题色板（来自 light.qss）
        PRIMARY = "#2c3e50"       # 页头/默认按钮
        ACCENT = "#0078d4"        # 主强调色（Windows 蓝）
        ACCENT_HOVER = "#1084d8"
        ACCENT_PRESSED = "#006cbe"
        SUCCESS = "#4CAF50"       # 成功/开始按钮（绿色）
        SUCCESS_HOVER = "#45a049"
        DANGER = "#f44336"        # 危险/停止按钮（红色）
        DANGER_HOVER = "#d32f2f"
        WARNING = "#ff8c00"       # 警告（橙色）
        BG = "#ffffff"            # 主背景
        BG_SURFACE = "#f5f5f5"    # 按钮/表面背景
        CARD_BG = "#ffffff"       # 卡片背景
        TEXT_DARK = "#333333"     # 主文字
        TEXT_SEC = "#666666"      # 次要文字
        TEXT_LIGHT = "#ffffff"    # 按钮文字
        BORDER = "#e0e0e0"        # 边框
        BORDER_LIGHT = "#d0d0d0"  # 悬停边框

        # 全局默认
        style.configure('.', background=BG, foreground=TEXT_DARK,
                        font=('Microsoft YaHei UI', 9))
        # 框架
        style.configure('TFrame', background=BG)
        style.configure('CardInner.TFrame', background=CARD_BG)
        # 标签
        style.configure('TLabel', background=BG, foreground=TEXT_DARK)
        # 按钮 - 浅色表面风格（参考 light.qss QPushButton）
        style.configure('TButton', background=BG_SURFACE, foreground=TEXT_DARK,
                        bordercolor=BORDER, borderwidth=1, focusthickness=3,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('TButton',
                  background=[('active', '#e8e8e8'), ('disabled', '#fafafa'),
                              ('pressed', '#d8d8d8')],
                  foreground=[('disabled', '#999999')],
                  bordercolor=[('active', BORDER_LIGHT), ('disabled', '#e8e8e8')])
        # 成功按钮 - 绿色（参考 light.qss #assignAllButton / #saveButton）
        style.configure('Success.TButton', background=SUCCESS, foreground=TEXT_LIGHT,
                        bordercolor=SUCCESS, borderwidth=1,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Success.TButton',
                  background=[('active', SUCCESS_HOVER), ('disabled', '#fafafa'),
                              ('pressed', '#3d8b40')],
                  foreground=[('disabled', '#999999')],
                  bordercolor=[('active', SUCCESS_HOVER)])
        # 危险按钮 - 红色（参考 light.qss #stopAllButton / #cancelButton）
        style.configure('Danger.TButton', background=DANGER, foreground=TEXT_LIGHT,
                        bordercolor=DANGER, borderwidth=1,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Danger.TButton',
                  background=[('active', DANGER_HOVER), ('disabled', '#fafafa'),
                              ('pressed', '#b71c1c')],
                  foreground=[('disabled', '#999999')],
                  bordercolor=[('active', DANGER_HOVER)])
        # 强调按钮 - 蓝色（参考 light.qss #okButton / primary）
        style.configure('Accent.TButton', background=ACCENT, foreground=TEXT_LIGHT,
                        bordercolor=ACCENT, borderwidth=1,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Accent.TButton',
                  background=[('active', ACCENT_HOVER), ('disabled', '#fafafa'),
                              ('pressed', ACCENT_PRESSED)],
                  foreground=[('disabled', '#999999')],
                  bordercolor=[('active', ACCENT_HOVER)])
        # 卡片标签框
        style.configure('Card.TLabelframe', background=CARD_BG, foreground=TEXT_DARK,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        relief='solid', borderwidth=1)
        style.configure('Card.TLabelframe.Label', background=CARD_BG, foreground=PRIMARY,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        # 页头
        style.configure('Header.TFrame', background=PRIMARY)
        style.configure('Header.TLabel', background=PRIMARY, foreground=TEXT_LIGHT,
                        font=('Microsoft YaHei UI', 14, 'bold'))
        style.configure('HeaderSub.TLabel', background=PRIMARY, foreground='#bdc3c7',
                        font=('Microsoft YaHei UI', 8))
        # 信息标签
        style.configure('Info.TLabel', background=CARD_BG, foreground=TEXT_DARK)
        style.configure('Accent.TLabel', background=CARD_BG, foreground=ACCENT,
                        font=('Microsoft YaHei UI', 9, 'bold'))
        style.configure('Success.TLabel', background=CARD_BG, foreground=SUCCESS)
        style.configure('Warning.TLabel', background=CARD_BG, foreground=WARNING)
        # 进度条
        style.configure('Accent.Horizontal.TProgressbar', background=ACCENT,
                        troughcolor=BG_SURFACE, bordercolor=BORDER,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        # 滑块（确保可拖动）
        style.configure('TScale', background=BG, troughcolor=BG_SURFACE,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT)
        # 复选框
        style.configure('TCheckbutton', background=BG, foreground=TEXT_DARK,
                        font=('Microsoft YaHei UI', 9))
        # 滚动条
        style.configure('TScrollbar', background='#dfe6e9', bordercolor=BG,
                        arrowcolor=PRIMARY, troughcolor=BG)
        # 下拉框
        style.configure('TCombobox', fieldbackground=CARD_BG, foreground=TEXT_DARK,
                        background=PRIMARY, bordercolor=BORDER,
                        arrowcolor=TEXT_LIGHT, selectbackground=ACCENT,
                        selectforeground=TEXT_LIGHT)
        # 输入框
        style.configure('TEntry', fieldbackground=CARD_BG, foreground=TEXT_DARK,
                        bordercolor=BORDER, borderwidth=1,
                        insertcolor=TEXT_DARK)
        style.map('TEntry',
                  bordercolor=[('focus', ACCENT)])
        # Treeview
        style.configure('Treeview', background=CARD_BG, foreground=TEXT_DARK,
                        fieldbackground=CARD_BG, bordercolor=BORDER,
                        font=('Microsoft YaHei UI', 9), rowheight=28)
        style.configure('Treeview.Heading', background=BG_SURFACE, foreground=TEXT_DARK,
                        bordercolor=BORDER, font=('Microsoft YaHei UI', 9, 'bold'))
        style.map('Treeview',
                  background=[('selected', ACCENT)],
                  foreground=[('selected', TEXT_LIGHT)])
        style.map('Treeview.Heading',
                  background=[('active', '#e8e8e8')])
        # Notebook（标签页）
        style.configure('TNotebook', background=BG, bordercolor=BORDER)
        style.configure('TNotebook.Tab', background=BG_SURFACE, foreground=TEXT_DARK,
                        bordercolor=BORDER, padding=[10, 4])
        style.map('TNotebook.Tab',
                  background=[('selected', BG)],
                  foreground=[('selected', ACCENT)])

    # ==================== 托盘 ====================
    def _setup_tray(self):
        if not TRAY_AVAILABLE:
            print("⚠️ pystray 或 Pillow 未安装，托盘功能不可用")
            return
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
            if not os.path.exists(icon_path):
                print(f"⚠️ 托盘图标文件不存在: {icon_path}")
                return
            image = Image.open(icon_path)
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            if image.size != (64, 64):
                image = image.resize((64, 64), Image.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", lambda: self.root.after(0, self._show_window), default=True),
                # 日志遮罩开关：文本随当前状态动态切换（text callable 需接收 item 参数）
                pystray.MenuItem(
                    lambda item: "关闭日志遮罩" if _qt_overlay is not None else "开启日志遮罩",
                    lambda: self.root.after(0, self._toggle_log_overlay)),
                pystray.MenuItem("设置", self._on_tray_settings),
                pystray.MenuItem("退出", self._quit_all),
            )
            self.tray_icon = pystray.Icon("delta_tool", image, "三角洲自动化工具", menu)
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
            print("✅ 系统托盘图标已创建")
        except Exception as e:
            print(f"⚠️ 托盘创建失败: {e}")
            self.tray_icon = None

    def _on_tray_settings(self):
        def _show_then_settings():
            self._show_window()
            self.open_settings()
        self.root.after(0, _show_then_settings)

    def _toggle_log_overlay(self):
        """切换日志遮罩开/关，并保存状态到设置"""
        enabled = toggle_log_overlay(self.root)
        self.settings["enable_log_overlay"] = enabled
        config.save_settings(self.settings)
        # 刷新托盘菜单文本
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def _hide_to_tray(self):
        """隐藏主窗口到系统托盘（运行自动化时防止遮挡游戏画面）"""
        try:
            # 仅当托盘可用时隐藏，否则窗口消失后无法恢复
            if TRAY_AVAILABLE and self.tray_icon:
                self.root.withdraw()
                if self._log_win and self._log_win.winfo_exists():
                    self._log_win.withdraw()
        except Exception:
            pass

    def _show_window(self):
        try:
            try:
                self.root.withdraw()
            except Exception:
                pass
            self.root.after(50, self._do_show_window)
        except Exception:
            try:
                self.root.deiconify()
                self.root.lift()
            except Exception:
                pass

    def _do_show_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
            had_settings = False
            if self._settings_window and self._settings_window.win.winfo_exists():
                try:
                    self._settings_window.win.grab_release()
                    had_settings = True
                except Exception:
                    pass
            self.root.focus_force()
            self.root.attributes('-topmost', True)
            self.root.after(100, lambda: self.root.attributes('-topmost', False))
            if had_settings:
                try:
                    self._settings_window.win.grab_set()
                    self._settings_window.win.lift()
                    self._settings_window.win.focus_force()
                except Exception:
                    pass
            # 恢复日志窗口
            if self._log_win and self._log_win.winfo_exists():
                self._log_win.deiconify()
                self._log_win.lift()
        except Exception as e:
            print(f"⚠️ 恢复窗口失败: {e}")
            try:
                self.root.state('normal')
                self.root.deiconify()
                self.root.lift()
            except Exception:
                pass

    def _setup_show_event(self):
        self._show_event = None
        try:
            import win32event
            self._show_event = win32event.CreateEvent(None, False, False, "Global\\DeltaAutoTool_ShowApp")
            self._poll_show_event()
        except Exception:
            pass

    def _poll_show_event(self):
        try:
            if self._show_event is not None:
                import win32event
                if win32event.WaitForSingleObject(self._show_event, 0) == win32event.WAIT_OBJECT_0:
                    # 运行期间忽略外部打开请求，避免主界面遮挡游戏窗口
                    if not self.running:
                        self._show_window()
                        print("ℹ️ 检测到外部打开请求，已显示窗口")
        except Exception:
            pass
        try:
            if self.root.winfo_exists():
                self.root.after(100, self._poll_show_event)
        except Exception:
            pass

    def _close_show_event(self):
        if self._show_event is not None:
            try:
                import win32event
                win32event.CloseHandle(self._show_event)
            except Exception:
                pass
            self._show_event = None

    # ==================== 关闭/退出 ====================
    def _on_close(self):
        if TRAY_AVAILABLE and self.tray_icon:
            try:
                self.root.attributes('-topmost', False)
                self.root.withdraw()
                # 隐藏日志窗口
                if self._log_win and self._log_win.winfo_exists():
                    self._log_win.withdraw()
                print("ℹ️ 程序已最小化到系统托盘，双击托盘图标可重新显示，右键可退出")
            except Exception as e:
                print(f"⚠️ 最小化到托盘失败: {e}")
                self._quit_all()
        else:
            self._quit_all()

    def _quit_all(self):
        self._shutdown = True
        # 保存窗口大小和位置（最小化/托盘状态时先恢复再保存）
        try:
            if self.root.state() == 'iconic' or self.root.state() == 'withdrawn':
                self.root.deiconify()
                self.root.update_idletasks()
            geo = self.root.geometry()
            # 只记住窗口大小（位置始终屏幕居中），过滤掉退化的 1x1 尺寸
            if geo and "x" in geo:
                try:
                    w_part = geo.split("x", 1)[0]
                    h_part = geo.split("x", 1)[1].split("+")[0].split("-")[0]
                    w = int(w_part)
                    h = int(h_part)
                    if w > 100 and h > 50:
                        settings = config.load_settings()
                        settings["window_geometry"] = f"{w}x{h}"
                        config.save_settings(settings)
                except Exception:
                    pass
        except Exception:
            pass
        self._close_log_window()
        self.stop()
        server_client.stop_heartbeat(self)
        self._scheduler_stop_event.set()
        if self._schedule_thread and self._schedule_thread.is_alive():
            self._schedule_thread.join(timeout=3)
        cooldown_watcher.stop_cooldown_watcher(self)
        if hasattr(self, '_cooldown_watcher_thread') and self._cooldown_watcher_thread and self._cooldown_watcher_thread.is_alive():
            self._cooldown_watcher_thread.join(timeout=3)
        if self._wake_timer_handle:
            utils.cancel_wake_timer(self._wake_timer_handle)
            self._wake_timer_handle = None
            self._last_wake_time = None
        utils.allow_sleep()
        self._close_show_event()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ==================== 设置 ====================
    def open_settings(self):
        if self._settings_window and self._settings_window.win.winfo_exists():
            self._settings_window.win.lift()
            self._settings_window.win.focus_force()
            return
        def _open():
            self._settings_window = SettingsWindow(self.root, self)
            self._settings_window.win.protocol("WM_DELETE_WINDOW", self._on_settings_close)
        utils.nav_push(self.root, _open)

    def _on_settings_close(self):
        win = self._settings_window.win if self._settings_window else None
        if self._settings_window:
            try:
                self._settings_window.win.unbind_all("<MouseWheel>")
            except Exception:
                pass
            self._settings_window = None
        if win:
            utils.nav_pop(win)

    def apply_auto_settings_from_window(self):
        sched.apply_auto_settings(self)

    def update_confidence_display(self):
        pass

    # ==================== 代理方法（委托给拆分模块） ====================
    # --- 服务器验证 ---
    def _validate_with_server(self):
        return server_client.validate_with_server(self)

    def _start_heartbeat(self):
        server_client.start_heartbeat(self)

    def _stop_heartbeat(self):
        server_client.stop_heartbeat(self)

    def _heartbeat_loop(self):
        server_client.heartbeat_loop(self)

    def _send_heartbeat(self, server_url, client_key, machine_id):
        server_client.send_heartbeat(self, server_url, client_key, machine_id)

    def _update_account_status(self, account_name, status):
        server_client.update_account_status(self, account_name, status)

    # --- 账号管理 ---
    def save_accounts(self):
        account_manager.save_accounts(self)

    def load_accounts(self):
        account_manager.load_accounts(self)

    def add_account(self):
        account_manager.add_account(self)

    def delete_account(self):
        account_manager.delete_account(self)

    def extend_all_cooldowns(self):
        """全体延时+：给所有冷却中的账号延长 30 分钟冷却（不影响暂停账号）"""
        extended = cooldown_manager.extend_all_cooldowns(hours=0.5)
        if extended:
            print(f"⏳ 已为 {len(extended)} 个冷却中的账号延长 30 分钟冷却：{', '.join(extended)}")
        else:
            print("ℹ️ 当前没有正在冷却中的账号，无需延长")
        account_manager.refresh_account_tree(self)

    def _reduce_all_cooldowns(self):
        """冷却缩减-：给所有冷却中的账号缩减 30 分钟冷却（不影响暂停账号）
        缩减后到期的账号直接变为可运行"""
        reduced, removed = cooldown_manager.reduce_all_cooldowns(minutes=30)
        parts = []
        if reduced:
            parts.append(f"缩减 {len(reduced)} 个账号：{', '.join(reduced)}")
        if removed:
            parts.append(f"到期 {len(removed)} 个账号：{', '.join(removed)}")
        if parts:
            print("⏳ " + "；".join(parts))
        else:
            print("ℹ️ 当前没有正在冷却中的账号，无需缩减")
        account_manager.refresh_account_tree(self)

    def update_account_count(self):
        account_manager.update_account_count(self)

    def _move_up(self):
        account_manager.move_up(self)

    def _move_down(self):
        account_manager.move_down(self)

    def _refresh_account_tree(self):
        account_manager.refresh_account_tree(self)

    def _show_account_menu(self, event):
        account_manager.show_account_menu(self, event)

    def _manual_add_cooldown(self, event):
        account_manager.manual_add_cooldown(self, event)

    def _reset_selected_cooldown(self):
        account_manager.reset_selected_cooldown(self)

    def _custom_cooldown_time(self):
        account_manager.custom_cooldown_time(self)

    def _start_periodic_tree_refresh(self):
        account_manager.start_periodic_tree_refresh(self)

    def _show_asset_history(self):
        account_manager.show_asset_history(self)

    def _show_cooldown_window(self):
        account_manager.show_cooldown_window(self)

    def _show_usage_guide(self):
        account_manager.show_help(self)

    def _show_asset_monitor(self):
        account_manager.show_asset_monitor(self)

    def _show_account_note(self):
        account_manager.show_account_note(self)

    def _toggle_cooldown_pause(self):
        account_manager.toggle_account_pause(self)

    def _on_tree_click(self, event):
        """点击 Treeview 时，如果点击的是分隔行则阻止选中"""
        item = self.account_tree.identify_row(event.y)
        if item and "separator" in self.account_tree.item(item, "tags"):
            return "break"


    # --- 调度器 ---
    def _set_next_wake_timer(self):
        sched.set_next_wake_timer(self)

    def _update_cooldown_wake_timer(self):
        sched.update_cooldown_wake_timer(self)

    # --- 冷却监听 ---
    def _start_cooldown_watcher(self):
        cooldown_watcher.start_cooldown_watcher(self)

    def _stop_cooldown_watcher(self):
        cooldown_watcher.stop_cooldown_watcher(self)

    def _restart_cooldown_watcher(self):
        cooldown_watcher.restart_cooldown_watcher(self)

    def _cooldown_watcher_loop(self):
        cooldown_watcher.cooldown_watcher_loop(self)

    def _run_single_account(self):
        """右键菜单：单独运行选中的账号"""
        import automation_runner
        sel = self.account_tree.selection()
        if not sel:
            return
        if "separator" in self.account_tree.item(sel[0], "tags"):
            return
        idx = account_manager._tree_idx_to_account_idx(self, sel[0])
        if idx >= len(self.qq_account_images):
            return
        if self.running:
            messagebox.showwarning("提示", "已有任务在运行中，请等待完成后再试。", parent=self.root)
            return
        img_path = self.qq_account_images[idx]
        automation_runner.start_single_account_run(self, img_path)

    def _check_any_account_ready(self):
        return cooldown_watcher.check_any_account_ready(self)

    def _check_cooldown_signal(self):
        """每 30 秒检查冷却触发信号文件（定时任务兜底机制）"""
        try:
            if utils.check_cooldown_signal():
                if not self.running and self.qq_account_images:
                    # 检查是否有非暂停的账号就绪
                    has_ready = cooldown_watcher.check_any_account_ready(self)
                    if has_ready:
                        print("📡 检测到冷却触发信号，自动执行任务...")
                        self.start()
                    else:
                        print("📡 检测到冷却触发信号，但所有账号都暂停或冷却中，忽略")
                else:
                    if not hasattr(self, '_last_signal_skip') or not self._last_signal_skip:
                        self._last_signal_skip = True
                        print("📡 检测到冷却触发信号，但程序正在运行或无账号，忽略")
        except Exception as e:
            print(f"⚠️ 检查冷却信号文件异常: {e}")
        # 关闭时不重新调度
        if not self._shutdown:
            self.root.after(30000, self._check_cooldown_signal)

    # --- 运行控制 ---
    def start(self):
        automation_runner.start_run(self)

    def stop(self):
        automation_runner.stop_run(self)

    def update_ui(self, step_increment=False, account_text=None, account_file=None):
        if step_increment:
            self.current_step += 1
            self.progress['value'] = self.current_step
        if account_text:
            self.account_label.config(text=account_text)
        if account_file:
            self.current_account_file_label.config(text=account_file)

    def set_operation(self, text):
        automation_runner.set_operation(self, text)

    def run_script_main(self):
        automation_runner.run_script_main(self)

    def _game_operations(self):
        return automation_runner.game_operations_wrapper(self)

    def _sell_operations(self):
        return automation_runner.sell_operations_wrapper(self)

    def on_finish(self):
        automation_runner.on_finish(self)

    def _get_account_next_run(self, account_name):
        return automation_runner.get_account_next_run(self, account_name)

    def _build_accounts_html(self, processed_accounts):
        return automation_runner.build_accounts_html(self, processed_accounts)

    # --- 邮件通知 ---
    def _send_email_notification(self, stats, elapsed, processed_accounts=None):
        email_notifier.send_run_report_email(self, stats, elapsed, processed_accounts)

    def _send_failure_email(self, error, processed_accounts=None):
        email_notifier.send_failure_email(self, error, processed_accounts)

    def _send_account_failure_email(self, account_name, next_run_str, processed_accounts=None):
        email_notifier.send_account_failure_email(self, account_name, next_run_str, processed_accounts)

    def _send_cooldown_ready_email(self, ready_accounts):
        email_notifier.send_cooldown_ready_email(self, ready_accounts)

    # ==================== UI 构建 ====================
    def _build_ui(self):
        # 设置根窗口浅色背景
        self.root.configure(bg='#ffffff')
        # ===== 顶部标题栏 =====
        header = ttk.Frame(self.root, style='Header.TFrame')
        header.pack(fill=tk.X, padx=0, pady=0, ipady=8)
        ttk.Label(header, text="三角洲行动自动化工具", style='Header.TLabel').pack(side=tk.LEFT, padx=(15, 5))
        ttk.Label(header, text="v1.3.6  |  多账号轮换 · 冷却执行 · 自动化操作", style='HeaderSub.TLabel').pack(side=tk.LEFT, padx=5)

        # ===== 主内容区 =====
        main_container = ttk.Frame(self.root, style='TFrame')
        main_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 12))

        # ----- QQ 账号管理 -----
        account_frame = ttk.LabelFrame(main_container, text=" QQ 账号管理（添加顺序即运行顺序） ", style='Card.TLabelframe', padding=12)
        account_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        btn_frame = ttk.Frame(account_frame, style='CardInner.TFrame')
        btn_frame.pack(fill=tk.X, pady=(0, 6))
        self.add_btn = ttk.Button(btn_frame, text="＋ 添加账号", style='Accent.TButton', command=self.add_account, width=14)
        self.add_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.clear_btn = ttk.Button(btn_frame, text="全体延时+", style='TButton', command=self.extend_all_cooldowns, width=10)
        self.clear_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="冷却缩减-", style='TButton',
                   command=self._reduce_all_cooldowns, width=10).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="资产监测", style='Accent.TButton',
                   command=self._show_asset_monitor, width=10).pack(side=tk.LEFT, padx=4)

        list_frame = ttk.Frame(account_frame, style='CardInner.TFrame')
        list_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("name", "asset", "next_run", "note")
        self.account_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=8)
        self.account_tree.heading("name", text="QQ账号")
        self.account_tree.heading("asset", text="现有资产")
        self.account_tree.heading("next_run", text="下次运行时间")
        self.account_tree.heading("note", text="名称/备注")
        self.account_tree.column("name", width=100, minwidth=60, anchor=tk.W)
        self.account_tree.column("asset", width=60, minwidth=40, anchor=tk.CENTER)
        self.account_tree.column("next_run", width=100, minwidth=70, anchor=tk.CENTER)
        self.account_tree.column("note", width=120, minwidth=80, anchor=tk.CENTER)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.account_tree.yview)
        self.account_tree.configure(yscrollcommand=scrollbar.set)
        self.account_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        # 账号状态颜色标签
        self.account_tree.tag_configure("cooling", foreground="#0078d4")   # 蓝色 - 冷却中
        self.account_tree.tag_configure("runnable", foreground="#4CAF50")  # 绿色 - 可运行
        self.account_tree.tag_configure("paused", foreground="#f44336")    # 红色 - 已暂停
        self.account_tree.tag_configure("game_failed", foreground="#ff8c00")  # 黄色 - 游戏失败
        self.account_tree.tag_configure("separator", background="#e0e0e0")  # 分隔线

        btn_frame2 = ttk.Frame(account_frame, style='CardInner.TFrame')
        btn_frame2.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(btn_frame2, text="右键账号可进行上移、下移、删除、重置冷却等操作",
                  style='Info.TLabel', font=('Microsoft YaHei UI', 8), foreground='#888').pack(side=tk.LEFT)

        self.account_menu = tk.Menu(self.root, tearoff=0)
        self.account_menu.add_command(label="运行此账号", command=self._run_single_account)
        self.account_menu.add_command(label="查看资产记录", command=self._show_asset_history)
        self.account_menu.add_command(label="账号信息设置", command=self._show_account_note)
        self.account_menu.add_separator()
        self.account_menu.add_command(label="上移", command=self._move_up)
        self.account_menu.add_command(label="下移", command=self._move_down)
        self.account_menu.add_separator()
        self.account_menu.add_command(label="重置选中冷却", command=self._reset_selected_cooldown)
        self.account_menu.add_command(label="自定义冷却时间", command=self._custom_cooldown_time)
        self.account_menu.add_command(label="暂停账号", command=self._toggle_cooldown_pause)
        self.account_menu.add_separator()
        self.account_menu.add_command(label="删除选中", command=self.delete_account)
        self.account_tree.bind("<Button-3>", self._show_account_menu)
        self.account_tree.bind("<Double-1>", self._manual_add_cooldown)
        self.account_tree.bind("<Button-1>", self._on_tree_click)

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

        self.progress = ttk.Progressbar(main_container, length=500, mode='determinate',
                                         style='Accent.Horizontal.TProgressbar')
        self.progress.pack(pady=(0, 4), fill=tk.X)

        self.stats_label = ttk.Label(main_container, text="", style='Info.TLabel')
        self.stats_label.pack(pady=(0, 8))

        # ----- 底部控制按钮 -----
        ctrl_frame = ttk.Frame(main_container, style='TFrame')
        ctrl_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.start_btn = ttk.Button(ctrl_frame, text="▶ 开始运行 (F1)", style='Success.TButton',
                                    command=self.start, width=14)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn = ttk.Button(ctrl_frame, text="■ 停止 (F2)", style='Danger.TButton',
                                   command=self.stop, state='disabled', width=12)
        self.stop_btn.pack(side=tk.LEFT, padx=8)
        self.settings_btn = ttk.Button(ctrl_frame, text="⚙ 设置", style='TButton',
                                       command=self.open_settings, width=10)
        self.settings_btn.pack(side=tk.RIGHT, padx=8)
        self.log_toggle_btn = ttk.Button(ctrl_frame, text="日志", style='Accent.TButton',
                                         command=self._toggle_log_panel, width=10)
        self.log_toggle_btn.pack(side=tk.RIGHT, padx=8)

        # ===== 日志窗口（初始隐藏） =====
        self._log_win = None
        self._log_area_widget = None
        # 主窗口隐藏的日志缓冲区（日志窗口关闭时接收输出）
        self.log_area = scrolledtext.ScrolledText(self.root, state='disabled')

    def _toggle_log_panel(self):
        """展开/收起日志独立窗口"""
        if self._log_win and self._log_win.winfo_exists():
            self._close_log_window()
        else:
            self._open_log_window()

    def _open_log_window(self):
        """打开日志窗口，固定在主窗口右侧"""
        if self._log_win and self._log_win.winfo_exists():
            return

        LOG_WIDTH = 400
        win = tk.Toplevel(self.root)
        win.title("运行日志")
        win.configure(bg='#1e272e')
        win.resizable(True, True)
        win.minsize(300, 200)
        win.transient(self.root)
        self._log_win = win

        # 图标
        utils.set_window_icon(win)

        # 定位到主窗口右侧
        self.root.update_idletasks()
        main_x = self.root.winfo_x()
        main_y = self.root.winfo_y()
        main_h = self.root.winfo_height()
        win.geometry(f"{LOG_WIDTH}x{main_h}+{main_x + self.root.winfo_width()}+{main_y}")

        # 日志文本区
        log_area = scrolledtext.ScrolledText(win,
                                             state='disabled', wrap=tk.WORD,
                                             font=('Consolas', 9),
                                             bg='#1e272e', fg='#00d8d6',
                                             insertbackground='#00d8d6',
                                             relief='flat', borderwidth=0,
                                             padx=8, pady=8,
                                             highlightthickness=1,
                                             highlightcolor='#dcdde1')
        log_area.pack(expand=True, fill=tk.BOTH, padx=6, pady=6)
        self._log_area_widget = log_area

        # 将已有日志内容复制过来
        try:
            self.log_area.configure(state='normal')
            content = self.log_area.get('1.0', tk.END)
            self.log_area.configure(state='disabled')
            log_area.configure(state='normal')
            log_area.insert('1.0', content)
            log_area.see(tk.END)
            log_area.configure(state='disabled')
        except Exception:
            pass

        # 重定向输出到新窗口
        sys.stdout = RedirectText(log_area, self.root, self._log_file_path)
        sys.stderr = RedirectText(log_area, self.root, self._log_file_path)

        # 主窗口移动时，日志窗口跟随
        def _sync_win_state():
            if self._log_win and self._log_win.winfo_exists():
                if self.root.state() == 'iconic':
                    self._log_win.withdraw()
                else:
                    self._log_win.deiconify()
                    self._log_win.lift()

        def _follow_main(event=None):
            try:
                if self._log_win and self._log_win.winfo_exists():
                    mx = self.root.winfo_x()
                    my = self.root.winfo_y()
                    mh = self.root.winfo_height()
                    mw = self.root.winfo_width()
                    self._log_win.geometry(f"+{mx + mw}+{my}")
                    # 高度跟随
                    cur_w = self._log_win.winfo_width()
                    self._log_win.geometry(f"{cur_w}x{mh}")
            except Exception:
                pass

        self.root.bind("<Configure>", _follow_main)
        self.root.bind("<FocusIn>", lambda e: _sync_win_state())
        win._follow_binding = _follow_main

        # 关闭时清理
        def _on_log_close():
            self._close_log_window()

        win.protocol("WM_DELETE_WINDOW", _on_log_close)

    def _close_log_window(self):
        """关闭日志窗口，恢复输出到主窗口隐藏的 log_area"""
        if self._log_win and self._log_win.winfo_exists():
            try:
                # 解除跟随绑定
                follow = getattr(self._log_win, '_follow_binding', None)
                if follow:
                    self.root.unbind("<Configure>", follow)
            except Exception:
                pass
            try:
                self._log_win.destroy()
            except Exception:
                pass
        self._log_win = None
        self._log_area_widget = None
        # 恢复输出到主窗口的隐藏 log_area
        sys.stdout = RedirectText(self.log_area, self.root, self._log_file_path)
        sys.stderr = RedirectText(self.log_area, self.root, self._log_file_path)

    def _redirect_output(self):
        sys.stdout = RedirectText(self.log_area, self.root, self._log_file_path)
        sys.stderr = RedirectText(self.log_area, self.root, self._log_file_path)

    def _set_run_log_file(self, run_start_time=None):
        """切换日志到以运行时间命名的文件，按日期分文件夹存放

        每次运行开始时调用：
        - 日志保存路径 / YYYY-MM-DD / HH-MM-SS.log
        """
        if run_start_time is None:
            run_start_time = datetime.datetime.now()
        log_dir = self.settings.get("log_save_path", "")
        if not log_dir:
            self._log_file_path = None
            return
        # 创建日期文件夹：YYYY-MM-DD
        date_str = run_start_time.strftime("%Y-%m-%d")
        time_str = run_start_time.strftime("%H-%M-%S")
        date_dir = os.path.join(log_dir, date_str)
        os.makedirs(date_dir, exist_ok=True)
        new_log_path = os.path.join(date_dir, f"{time_str}.log")
        self._log_file_path = new_log_path
        # 更新两个 RedirectText 实例的日志文件
        if hasattr(sys.stdout, 'set_log_path'):
            sys.stdout.set_log_path(new_log_path)
        if hasattr(sys.stderr, 'set_log_path'):
            sys.stderr.set_log_path(new_log_path)
        print(f"📝 日志文件: {new_log_path}")


def main():
    config.APP_SETTINGS = config.init_settings()
    config.WEGAME_PATH = config.APP_SETTINGS.get("wegame_path", "")
    config.CONFIDENCE = config.APP_SETTINGS["confidence"]

    # 预加载 OCR 引擎（后台线程，不阻塞启动）
    import utils
    threading.Thread(target=utils.init_ocr_engine, daemon=True).start()

    root = tk.Tk()
    root.title("三角洲行动自动化工具")
    root.resizable(True, True)
    root.minsize(500, 600)

    # 日志遮罩：默认关闭，仅当设置开启时才延迟加载（PyQt6 可选，失败不影响主程序）
    if config.APP_SETTINGS.get("enable_log_overlay", False):
        enable_log_overlay(root)

    # 显示加载界面
    loading_frame = ttk.Frame(root, padding=40)
    loading_frame.pack(fill=tk.BOTH, expand=True)
    ttk.Label(loading_frame, text="三角洲行动自动化工具",
              font=('Microsoft YaHei UI', 16, 'bold')).pack(pady=(20, 10))
    status_label = ttk.Label(loading_frame, text="正在连接服务器验证...",
                             font=('Microsoft YaHei UI', 10))
    status_label.pack(pady=10)
    progress = ttk.Progressbar(loading_frame, mode='indeterminate', length=250)
    progress.pack(pady=10)
    progress.start(15)

    root.update_idletasks()
    w, h = 400, 200
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    def _init_app():
        progress.stop()
        loading_frame.destroy()
        # 恢复上次窗口大小（位置始终屏幕居中）
        saved_geo = config.APP_SETTINGS.get("window_geometry", "")
        saved_w, saved_h = 550, 800
        if saved_geo and "x" in saved_geo:
            try:
                w_part = saved_geo.split("x", 1)[0]
                h_part = saved_geo.split("x", 1)[1].split("+")[0].split("-")[0]
                saved_w = int(w_part)
                saved_h = int(h_part)
            except Exception:
                saved_w, saved_h = 550, 800
        root.geometry(f"{saved_w}x{saved_h}")
        _center_window(root, saved_w, saved_h)
        _check_resolution_on_startup(root)
        App(root)
        root.after(50, lambda: (root.lift(), root.focus_force()))
        root.after(50, lambda: root.attributes('-topmost', True))
        root.after(200, lambda: root.attributes('-topmost', False))

    root.after(300, _init_app)
    root.mainloop()


def _center_window(win, w, h):
    """将窗口居中显示"""
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")


def _check_resolution_on_startup(root):
    """启动时检测分辨率，若与模板不匹配则提示用户重新截图"""
    current_res = config.get_resolution_key()
    stored_res = config.load_template_resolution()

    if not stored_res:
        config.save_template_resolution(current_res)
        return

    if current_res == stored_res:
        return

    msg = (
        f"检测到屏幕分辨率发生变化！\n\n"
        f"  模板截图时分辨率：{stored_res}\n"
        f"  当前屏幕分辨率：{current_res}\n\n"
        f"分辨率不同会导致图像识别失败。\n"
        f"建议重新截取模板图片。"
    )
    result = messagebox.askyesnocancel(
        "分辨率不匹配",
        msg + "\n\n点击「是」打开模板截图向导\n点击「否」继续运行（可能识别失败）",
        icon='warning'
    )
    if result is True:
        from template_capture import TemplateCaptureWizard
        TemplateCaptureWizard(root, current_res)
    elif result is False:
        config.save_template_resolution(current_res)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
