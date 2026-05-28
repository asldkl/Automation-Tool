"""
图形用户界面模块
包含多账号管理、游戏内操作、停止机制及快捷键
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
import html
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox
import pyautogui

import traceback
import config
import utils
import cooldown_manager
import automation
import machine_fingerprint
from settings_window import SettingsWindow

# 尝试导入托盘所需库
try:
    import pystray
    from PIL import Image, ImageTk
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# ==================== 干扰代码（增加分析难度） ====================
def _v1_check():
    """校验许可证完整性"""
    return True

def _v2_check():
    """验证环境配置"""
    if _v1_check():
        return False
    return True

def _v3_check():
    """检查系统兼容性"""
    _ = _v1_check()
    _ = _v2_check()
    return _ and not _

# -------------------- 有效期由服务器端统一校验 --------------------

ACCOUNTS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_accounts.json")


class RedirectText:
    """将标准输出重定向到 Tkinter 文本框，可选同时写入日志文件"""
    def __init__(self, text_widget, log_path=None):
        self.text_widget = text_widget
        self.log_path = log_path
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def write(self, message):
        try:
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, message)
            self.text_widget.see(tk.END)
            self.text_widget.configure(state='disabled')
        except Exception:
            pass
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
        self.qq_account_images = []
        self._stop_event = threading.Event()          # 仅用于停止工作线程
        self._scheduler_stop_event = threading.Event() # 仅用于停止调度器线程
        self._auto_timer = None
        self._schedule_thread = None
        self._daily_loop = False
        self._silent = False
        self._schedule_times = []
        self._settings_window = None
        # 提醒相关
        self._reminder_shown = False
        self._reminder_cancelled_time = None  # 记录被取消的具体时间点（不影响其他时间点）
        self._reminder_target = None
        self._reminder_window = None
        self._next_run_time_str = ""
        # 唤醒定时器
        self._wake_timer_handle = None
        self._last_wake_time = None  # 上次设置的唤醒时间，避免重复日志
        self._wake_attempted = False  # 是否已尝试唤醒显示器
        # 关机标志（每日只触发一次）
        self._shutdown_handled_today = False
        # 定时任务触发时跳过冷却检查
        self._ignore_cooldown_this_run = False
        # 用户主动停止后阻止冷却监听重新触发
        self._user_stopped_cooldown = False
        # 窗口图标
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        # 加载设置
        self.settings = config.APP_SETTINGS
        config.WEGAME_PATH = self.settings.get("wegame_path", "")
        config.CONFIDENCE = self.settings["confidence"]

        # 服务器验证（机器指纹 + 远程有效期）
        self._server_validated = False
        self._server_expiry = None
        try:
            machine_id = machine_fingerprint.get_machine_id()
        except Exception:
            machine_id = "获取失败"

        try:
            allowed, expiry, error = self._validate_with_server()
            if allowed is True:
                self._server_validated = True
                self._server_expiry = expiry
                print(f"✅ 服务器验证通过，有效期至：{expiry}")
            elif allowed is False:
                print(f"❌ 服务器验证失败：{error}")
                messagebox.showerror("验证失败",
                    f"程序无法启动：{error}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"本机机器指纹（请发送给管理员）：\n\n"
                    f"  {machine_id}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━")
                self.root.after(100, self.root.destroy)
                return
            else:
                # 服务器不可达 = 拒绝启动（防止绕过验证）
                print(f"❌ 服务器验证失败：{error}")
                messagebox.showerror("验证失败",
                    f"无法连接到验证服务器，程序无法启动。\n\n"
                    f"错误信息：{error}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"本机机器指纹（请发送给管理员）：\n\n"
                    f"  {machine_id}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"请将此指纹发送给管理员添加白名单。")
                self.root.after(100, self.root.destroy)
                return
        except Exception as e:
            print(f"❌ 服务器验证异常: {e}")
            messagebox.showerror("验证失败",
                f"服务器验证异常，程序无法启动。\n\n"
                f"错误信息：{e}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"本机机器指纹（请发送给管理员）：\n\n"
                f"  {machine_id}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"请将此指纹发送给管理员添加白名单。")
            self.root.after(100, self.root.destroy)
            return

        # 心跳相关
        self._heartbeat_thread = None
        self._heartbeat_stop = None
        self._account_status = {}

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
        # 全局拦截空格键，主界面按下空格不进行任何操作
        root.bind_all("<space>", lambda e: "break")

        self._build_ui()
        self._redirect_output()
        self.total_steps = 0
        self.current_step = 0
        # 提前加载账号列表，确保 QQ 自动登录检查时 qq_account_images 已有数据
        self.load_accounts()
        self.update_account_count()

        # 托盘
        self.tray_icon = None
        self._setup_tray()

        # 单实例前台显示事件
        self._setup_show_event()

        # 互斥校验：auto_start 与 cooldown_run_immediately 不能同时启用
        if self.settings.get("auto_start", False) and self.settings.get("cooldown_run_immediately", False):
            print("⚠️ 检测到「定时执行」与「冷却完立即运行」同时启用，自动关闭「冷却完立即运行」")
            self.settings["cooldown_run_immediately"] = False
            config.save_settings(self.settings)

        # 定时任务初始化
        if self.settings.get("auto_start", False):
            self._start_scheduler()

        # 冷却完立即运行：启动冷却到期监听线程
        if self.settings.get("cooldown_run_immediately", False):
            self._start_cooldown_watcher()

        # 开机自启动检测
        is_auto_start = '--auto-start' in sys.argv
        if is_auto_start:
            print("🔄 检测到开机自启动标志 (--auto-start)")
            # 开机立即运行（仅在开机自启动且开启该选项时触发）
            if self.settings.get("run_on_startup", False) and self.qq_account_images:
                print("🔄 开机立即运行已启用，将在 2 秒后自动执行任务...")
                self.root.after(2000, self.start)
            else:
                print(f"ℹ️ 开机立即运行未启用 (run_on_startup={self.settings.get('run_on_startup', False)}, "
                      f"账号数={len(self.qq_account_images)})")
            # 静默模式（仅开机自启动时生效，双击打开始终显示主界面）
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
            print("⚠️ pystray 或 Pillow 未安装，托盘功能不可用")
            return
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
            if not os.path.exists(icon_path):
                print(f"⚠️ 托盘图标文件不存在: {icon_path}")
                return
            image = Image.open(icon_path)
            # pystray 在 Windows 上要求 RGBA 格式，ICO 文件可能是 P 或 RGB 模式
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            # 调整为系统托盘标准尺寸（Windows 托盘推荐 64x64）
            if image.size != (64, 64):
                image = image.resize((64, 64), Image.LANCZOS)
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", self._show_window, default=True),
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
        """托盘右键菜单「设置」回调——先显示主窗口，再打开设置"""
        def _show_then_settings():
            self._show_window()
            self.open_settings()
        self.root.after(0, _show_then_settings)

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        # 如果设置窗口（模态）处于打开状态，临时释放 grab 使主窗口可获焦
        had_settings = False
        if self._settings_window and self._settings_window.win.winfo_exists():
            try:
                self._settings_window.win.grab_release()
                had_settings = True
            except Exception:
                pass
        self.root.focus_force()
        # 闪烁任务栏图标以吸引注意力
        self.root.attributes('-topmost', True)
        self.root.after(100, lambda: self.root.attributes('-topmost', False))
        # 恢复设置窗口 grab
        if had_settings:
            try:
                self._settings_window.win.grab_set()
                self._settings_window.win.lift()
                self._settings_window.win.focus_force()
            except Exception:
                pass

    def _setup_show_event(self):
        """创建命名事件，用于接收其它实例的前台显示请求"""
        self._show_event = None
        try:
            import win32event
            # 创建全局事件，允许跨进程访问
            self._show_event = win32event.CreateEvent(
                None, False, False,
                "Global\\DeltaAutoTool_ShowApp"
            )
            self._poll_show_event()
        except Exception:
            pass

    def _poll_show_event(self):
        """定期检测是否有其它实例请求显示窗口"""
        try:
            if self._show_event is not None:
                import win32event
                if win32event.WaitForSingleObject(self._show_event, 0) == win32event.WAIT_OBJECT_0:
                    self._show_window()
                    print("ℹ️ 检测到外部打开请求，已显示窗口")
        except Exception:
            pass
        # 保持轮询（在 root 存活期间）
        try:
            if self.root.winfo_exists():
                self.root.after(100, self._poll_show_event)
        except Exception:
            pass

    def _close_show_event(self):
        """关闭显示事件句柄"""
        if self._show_event is not None:
            try:
                import win32event
                win32event.CloseHandle(self._show_event)
            except Exception:
                pass
            self._show_event = None

    # ---------- 服务器验证与心跳 ----------
    def _validate_with_server(self):
        """
        启动时向服务器验证机器指纹和有效期
        返回 (allowed: bool, expiry: str, error: str)
        """
        server_url = self.settings.get("server_url", "").strip()
        client_key = self.settings.get("client_key", "").strip()
        if not server_url or not client_key:
            return None, None, "服务器配置为空，跳过远程验证"

        try:
            machine_id = machine_fingerprint.get_machine_id()
            import urllib.request
            import json as _json

            url = f"{server_url}/api/v1/validate"
            payload = _json.dumps({
                "machine_id": machine_id,
                "current_date": datetime.datetime.now().strftime("%Y-%m-%d")
            }).encode("utf-8")

            req = urllib.request.Request(url, data=payload, method="POST")
            req.add_header("Authorization", client_key)
            req.add_header("Content-Type", "application/json")

            with urllib.request.urlopen(req, timeout=10) as resp:
                result = _json.loads(resp.read().decode("utf-8"))

            if result.get("status") == "granted":
                return True, result.get("expiry", ""), ""
            else:
                reason = result.get("reason", "未知原因")
                return False, None, reason
        except Exception as e:
            return None, None, f"服务器连接失败: {e}"

    def _start_heartbeat(self):
        """启动心跳线程，实时同步账号状态到服务器"""
        if hasattr(self, '_heartbeat_thread') and self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop = threading.Event()
        self._account_status = {}  # {filename: "running|cooling|success|failed|idle"}
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self):
        """停止心跳线程"""
        if hasattr(self, '_heartbeat_stop') and self._heartbeat_stop:
            self._heartbeat_stop.set()

    def _heartbeat_loop(self):
        """心跳循环：每30秒向服务器发送账号状态"""
        server_url = self.settings.get("server_url", "").strip()
        client_key = self.settings.get("client_key", "").strip()
        if not server_url or not client_key:
            return

        try:
            machine_id = machine_fingerprint.get_machine_id()
        except Exception:
            return

        while not self._heartbeat_stop.is_set():
            try:
                self._send_heartbeat(server_url, client_key, machine_id)
            except Exception as e:
                print(f"⚠️ 心跳发送失败: {e}")

            # 等待30秒，分段检查停止信号
            for _ in range(6):
                if self._heartbeat_stop.is_set():
                    break
                time.sleep(5)

    def _send_heartbeat(self, server_url, client_key, machine_id):
        """发送一次心跳到服务器"""
        import urllib.request
        import json as _json

        accounts = []
        for img_path in self.qq_account_images:
            fname = os.path.basename(img_path)
            status = self._account_status.get(fname, "idle")
            accounts.append({"name": fname, "status": status})

        url = f"{server_url}/api/v1/heartbeat"
        payload = _json.dumps({
            "machine_id": machine_id,
            "accounts": accounts,
            "is_running": self.running
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", client_key)
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as resp:
            pass

    def _update_account_status(self, account_name, status):
        """更新单个账号的状态（线程安全）"""
        if hasattr(self, '_account_status'):
            self._account_status[account_name] = status

    def _on_close(self):
        """关闭按钮：最小化到托盘（如果可用），否则退出"""
        if TRAY_AVAILABLE and self.tray_icon:
            self.root.withdraw()
            print("ℹ️ 程序已最小化到系统托盘，双击托盘图标可重新显示，右键可退出")
        else:
            self._quit_all()

    def _quit_all(self):
        """真正退出程序"""
        self.stop()
        self._stop_heartbeat()
        self._scheduler_stop_event.set()
        if self._schedule_thread and self._schedule_thread.is_alive():
            self._schedule_thread.join(timeout=3)
        # 停止冷却监听
        self._stop_cooldown_watcher()
        if hasattr(self, '_cooldown_watcher_thread') and self._cooldown_watcher_thread and self._cooldown_watcher_thread.is_alive():
            self._cooldown_watcher_thread.join(timeout=3)
        # 清理唤醒定时器
        if self._wake_timer_handle:
            utils.cancel_wake_timer(self._wake_timer_handle)
            self._wake_timer_handle = None
            self._last_wake_time = None
        # 恢复睡眠设置
        utils.allow_sleep()
        # 关闭前台显示事件
        self._close_show_event()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ---------- 定时任务调度 ----------
    def _start_scheduler(self):
        """启动定时检查线程，若线程已在运行则先停止再重启（以应用新设置）"""
        if self._schedule_thread and self._schedule_thread.is_alive():
            self._scheduler_stop_event.set()
            self._schedule_thread.join(timeout=5)
        self._scheduler_stop_event.clear()
        self._daily_loop = self.settings.get("run_mode") == "每日循环"
        times_str = self.settings.get("schedule_times", [])
        if not times_str:
            single = self.settings.get("start_time", "08:00")
            times_str = [single]
        # 标准化所有时间格式（补零）
        normalized = []
        for t in times_str:
            try:
                h, m = map(int, t.split(":"))
                normalized.append(f"{h:02d}:{m:02d}")
            except Exception:
                continue
        self._schedule_times = sorted(set(normalized))
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
        try:
            print(f"⏰ 定时调度线程已启动，目标时间点：{self._schedule_times}")
            if self._daily_loop:
                self._schedule_loop_daily()
            else:
                self._schedule_loop_single()
        except Exception as e:
            print(f"❌ 定时调度线程异常退出: {e}")
            traceback.print_exc()
            # 恢复机制：如果调度器意外退出且未被主动停止，5秒后自动重启
            if not self._scheduler_stop_event.is_set() and self.settings.get("auto_start", False):
                print("🔄 调度器将在 5 秒后自动重启...")
                self.root.after(5000, self._restart_scheduler)

    def _restart_scheduler(self):
        """调度器异常退出后的恢复入口（由 root.after 调度到主线程）"""
        if not self._scheduler_stop_event.is_set() and self.settings.get("auto_start", False):
            print("🔄 正在重启调度器...")
            self._start_scheduler()

    def _start_cooldown_watcher(self):
        """启动冷却到期监听线程（cooldown_run_immediately 模式）"""
        if hasattr(self, '_cooldown_watcher_thread') and self._cooldown_watcher_thread and self._cooldown_watcher_thread.is_alive():
            return

        # Bug7: 首次启用时，为所有没有冷却记录的账号记录一次冷却时间
        # 防止所有账号在30秒内全部执行
        if self.settings.get("enable_cooldown", False):
            cd_hours = self.settings.get("cooldown_hours", 8)
            for acc_idx, img_path in enumerate(self.qq_account_images):
                file_name = os.path.basename(img_path)
                cooling, _ = cooldown_manager.is_cooling_down(file_name)
                if not cooling:
                    # 检查是否有历史记录
                    all_cd = cooldown_manager.get_all_cooldowns()
                    if file_name not in all_cd:
                        cooldown_manager.record_run(file_name, cd_hours)
                        print(f"📝 首次启用冷却监听，为 {file_name} 记录冷却时间")

        self._cooldown_watcher_stop = threading.Event()
        self._cooldown_watcher_thread = threading.Thread(target=self._cooldown_watcher_loop, daemon=True)
        self._cooldown_watcher_thread.start()
        print("👀 冷却到期监听已启动，冷却结束后将自动执行任务")

    def _stop_cooldown_watcher(self):
        """停止冷却到期监听"""
        if hasattr(self, '_cooldown_watcher_stop') and self._cooldown_watcher_stop:
            self._cooldown_watcher_stop.set()

    def _restart_cooldown_watcher(self):
        """冷却监听异常退出后的恢复入口"""
        if not self._cooldown_watcher_stop.is_set() and self.settings.get("cooldown_run_immediately", False):
            print("🔄 正在重启冷却监听...")
            self._cooldown_watcher_thread = None
            self._start_cooldown_watcher()

    def _cooldown_watcher_loop(self):
        """冷却到期监听循环：每30秒检查一次，有账号冷却到期则自动执行"""
        last_trigger_minute = None
        try:
            while not self._cooldown_watcher_stop.is_set():
                try:
                    # 用户主动停止后，等待30秒再恢复监听（防止立即重新触发）
                    if self._user_stopped_cooldown:
                        for _ in range(6):  # 30秒 = 6 * 5秒
                            if self._cooldown_watcher_stop.is_set():
                                return
                            time.sleep(5)
                        self._user_stopped_cooldown = False
                        print("ℹ️ 用户停止冷却期已过，恢复冷却监听")
                        continue

                    # 更新唤醒定时器（基于最早冷却到期时间）
                    self._update_cooldown_wake_timer()

                    # 自动移除已过期的冷却记录
                    expired = cooldown_manager.remove_expired_cooldowns()
                    if expired:
                        print(f"🔔 冷却完成，已从冷却列表移除：{', '.join(expired)}")

                    if not self.running and self.qq_account_images:
                        now = datetime.datetime.now()
                        current_minute = now.strftime("%Y-%m-%d %H:%M")
                        # 同一分钟内不重复触发
                        if current_minute != last_trigger_minute:
                            has_ready = self._check_any_account_ready()
                            if has_ready:
                                last_trigger_minute = current_minute
                                print("🔔 检测到账号冷却到期，自动执行任务...")
                                # 发送冷却到期邮件提醒
                                ready_list = []
                                for img_path in self.qq_account_images:
                                    fname = os.path.basename(img_path)
                                    cooling, _ = cooldown_manager.is_cooling_down(fname)
                                    if not cooling:
                                        ready_list.append(fname)
                                if ready_list:
                                    self._send_cooldown_ready_email(ready_list)
                                utils.prevent_sleep()
                                utils.wake_display()
                                time.sleep(2)
                                self.root.after(0, self.start)
                except Exception as inner_e:
                    print(f"⚠️ 冷却监听异常（将继续运行）: {inner_e}")
                    traceback.print_exc()
                # 等待30秒，但分段检查停止信号以支持快速退出
                for _ in range(6):
                    if self._cooldown_watcher_stop.is_set():
                        break
                    time.sleep(5)
        except Exception as e:
            print(f"❌ 冷却监听线程异常退出: {e}")
            traceback.print_exc()
            # Bug 5: 异常恢复机制
            if not self._cooldown_watcher_stop.is_set() and self.settings.get("cooldown_run_immediately", False):
                print("🔄 冷却监听线程将在 5 秒后自动重启...")
                self.root.after(5000, self._restart_cooldown_watcher)

    def _check_any_account_ready(self):
        """检查是否有账号冷却到期且未在冷却中，返回是否有可用账号"""
        if not self.settings.get("cooldown_run_immediately", False):
            return False
        ready_accounts = []
        for img_path in self.qq_account_images:
            file_name = os.path.basename(img_path)
            cooling, next_time = cooldown_manager.is_cooling_down(file_name)
            if not cooling:
                ready_accounts.append(file_name)
        # 只在状态变化时打印日志，避免重复输出
        ready_key = tuple(sorted(ready_accounts))
        if ready_accounts:
            if not hasattr(self, '_last_ready_key') or self._last_ready_key != ready_key:
                print(f"🔍 发现 {len(ready_accounts)} 个账号就绪：{', '.join(ready_accounts)}")
                self._last_ready_key = ready_key
            return True
        else:
            if hasattr(self, '_last_ready_key') and self._last_ready_key:
                self._last_ready_key = None
        return False

    def _schedule_loop_daily(self):
        """每日循环模式：持续检查时间点（含30分钟容差，防止休眠唤醒后错过目标时间）"""
        executed_today = set()  # 记录今天已执行的 (日期, 时间点) 防止重复执行
        try:
            while not self._scheduler_stop_event.is_set():
                try:
                    now = datetime.datetime.now()
                    today_str = now.strftime("%Y-%m-%d")

                    # 清理非当天的执行记录
                    executed_today = {(d, t) for d, t in executed_today if d == today_str}

                    # 1. 定时执行（带30分钟容差，覆盖休眠唤醒场景）
                    matched_time = None
                    for t in self._schedule_times:
                        if (today_str, t) in executed_today:
                            continue
                        h, m = map(int, t.split(":"))
                        scheduled_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                        tolerance = datetime.timedelta(minutes=30)
                        if scheduled_dt <= now <= scheduled_dt + tolerance:
                            matched_time = t
                            break

                    if matched_time is not None and not self.running:
                        if self._reminder_cancelled_time == matched_time:
                            # 用户取消了这个时间点，跳过但不标记为已执行（不影响其他时间点）
                            print(f"⏹ 用户取消了 {matched_time} 的定时运行")
                            executed_today.add((today_str, matched_time))
                            self._reminder_shown = False
                            self._reminder_target = None
                            self._reminder_cancelled_time = None
                        else:
                            executed_today.add((today_str, matched_time))
                            self.root.after(0, lambda mt=matched_time: self._execute_scheduled_run(mt))
                            self._reminder_cancelled_time = None
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
                    self._check_reminder_daily(now, executed_today)

                    # 3. 自动关机（每天只触发一次）
                    self._check_shutdown(now)
                except Exception as inner_e:
                    print(f"⚠️ 调度循环内部异常（将继续运行）: {inner_e}")
                    traceback.print_exc()

                time.sleep(30)
        except Exception as e:
            print(f"❌ 每日循环调度异常: {e}")
            traceback.print_exc()

    def _schedule_loop_single(self):
        """单次模式：等待下一个时间点（含 30 分钟容差，防止休眠唤醒后略过目标时间）"""
        try:
            now = datetime.datetime.now()
            targets = []
            for t in self._schedule_times:
                h, m = map(int, t.split(":"))
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                tolerance = datetime.timedelta(minutes=30)
                if target + tolerance < now:
                    target += datetime.timedelta(days=1)
                targets.append(target)
            next_target = min(targets)
            print(f"⏰ 单次定时：将在 {next_target.strftime('%Y-%m-%d %H:%M')} 执行，当前时间 {now.strftime('%Y-%m-%d %H:%M:%S')}")

            while not self._scheduler_stop_event.is_set():
                try:
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
                            print(f"🔔 触发运行提醒弹窗，将在 {self._next_run_time_str} 执行")
                            self.root.after(0, lambda: self._show_reminder(reminder_min))

                    # 执行
                    if now >= next_target:
                        target_str = next_target.strftime("%H:%M")
                        if self._reminder_cancelled_time == target_str:
                            print(f"⏹ 用户取消了 {target_str} 的定时运行，跳过本次")
                            self._reminder_cancelled_time = None
                            self._reminder_shown = False
                            # 单次模式：取消后跳过今天，自动计算明天的下一个时间点
                            self.root.after(0, lambda: self._reschedule_single(next_target))
                        else:
                            self.root.after(0, lambda ts=target_str: self._execute_scheduled_run(ts))
                            self.settings["auto_start"] = False
                            config.save_settings(self.settings)
                            self.root.after(0, self._update_ui_after_single)
                        break
                except Exception as inner_e:
                    print(f"⚠️ 调度循环内部异常（将继续运行）: {inner_e}")
                    traceback.print_exc()

                time.sleep(10)
        except Exception as e:
            print(f"❌ 单次定时调度异常: {e}")
            traceback.print_exc()

    def _check_reminder_daily(self, now, executed_today=None):
        """每日循环模式：检查是否需要弹出运行提醒"""
        if not self.settings.get("reminder_enabled", False) or self.running:
            return

        reminder_min = self.settings.get("reminder_minutes", 5)
        reminder_sec_offset = reminder_min * 60
        today_str = now.strftime("%Y-%m-%d")

        # 如果已有提醒目标且已过执行时间，重置提醒状态（允许下一个时间点触发提醒）
        if self._reminder_shown and self._reminder_target:
            h, m = map(int, self._reminder_target.split(":"))
            target_sec = h * 3600 + m * 60
            current_sec = now.hour * 3600 + now.minute * 60 + now.second
            if current_sec >= target_sec:
                self._reminder_shown = False
                self._reminder_target = None

        if self._reminder_shown:
            return

        for t in self._schedule_times:
            # 跳过已执行或已取消的时间点，防止提醒重复弹出
            if executed_today and (today_str, t) in executed_today:
                continue
            if self._reminder_cancelled_time == t:
                continue

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
                print(f"🔔 触发运行提醒弹窗，将在 {t} 执行")
                self.root.after(0, lambda m=reminder_min: self._show_reminder(m))
                break

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
        try:
            print(f"🚀 定时触发：{time_str}，当前时间 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            # 关闭提醒窗口
            if self._reminder_window:
                try:
                    self._reminder_window.destroy()
                except Exception:
                    pass
                self._reminder_window = None
            self._reminder_shown = False
            self._reminder_cancelled_time = None
            # 定时任务触发时临时忽略冷却检查，确保所有账号都能执行
            self._ignore_cooldown_this_run = True
            # 防止系统在运行时睡眠
            utils.prevent_sleep()
            # 尝试唤醒显示器（从睡眠/息屏状态恢复）
            utils.wake_display()
            time.sleep(2)
            self.root.after(0, self.start)
        except Exception as e:
            print(f"❌ 定时执行出错: {e}")
            traceback.print_exc()

    def _set_next_wake_timer(self):
        """计算下一个运行时间，提前5分钟设置唤醒定时器（支持定时和冷却两种模式）"""
        if not self.settings.get("wake_enabled", True):
            return
        try:
            # 取消旧定时器
            if self._wake_timer_handle:
                utils.cancel_wake_timer(self._wake_timer_handle)
                self._wake_timer_handle = None

            now = datetime.datetime.now()
            next_run = None

            # 定时执行模式
            for t in self._schedule_times:
                h, m = map(int, t.split(":"))
                run_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if run_time <= now:
                    run_time += datetime.timedelta(days=1)
                if next_run is None or run_time < next_run:
                    next_run = run_time

            # 冷却完立即运行模式：取最早冷却到期时间
            if self.settings.get("cooldown_run_immediately", False) and self.qq_account_images:
                for img_path in self.qq_account_images:
                    fname = os.path.basename(img_path)
                    cooling, next_time_str = cooldown_manager.is_cooling_down(fname)
                    if cooling and next_time_str:
                        try:
                            cd_next = datetime.datetime.strptime(next_time_str, "%Y-%m-%d %H:%M:%S")
                            if next_run is None or cd_next < next_run:
                                next_run = cd_next
                        except Exception:
                            pass

            if next_run:
                wake_time = next_run - datetime.timedelta(minutes=5)
                # 只设置未来的唤醒时间（至少1分钟后）
                min_gap = datetime.timedelta(seconds=60)
                if wake_time > now + min_gap:
                    # 唤醒时间未变化则跳过，避免重复日志
                    if self._last_wake_time == wake_time:
                        return
                    handle = utils.set_wake_timer(wake_time)
                    if handle:
                        self._wake_timer_handle = handle
                        self._last_wake_time = wake_time
                        print(f"🔔 已设置唤醒定时器：{wake_time.strftime('%H:%M')}")
        except Exception as e:
            print(f"⚠️ 设置唤醒定时器失败: {e}")

    def _update_cooldown_wake_timer(self):
        """冷却监听专用：根据最早冷却到期时间更新唤醒定时器"""
        if not self.settings.get("wake_enabled", True):
            return
        if not self.settings.get("cooldown_run_immediately", False):
            return
        try:
            now = datetime.datetime.now()
            earliest_next = None
            if self.qq_account_images:
                for img_path in self.qq_account_images:
                    fname = os.path.basename(img_path)
                    cooling, next_time_str = cooldown_manager.is_cooling_down(fname)
                    if cooling and next_time_str:
                        try:
                            cd_next = datetime.datetime.strptime(next_time_str, "%Y-%m-%d %H:%M:%S")
                            if earliest_next is None or cd_next < earliest_next:
                                earliest_next = cd_next
                        except Exception:
                            pass

            if earliest_next:
                wake_time = earliest_next - datetime.timedelta(minutes=5)
                min_gap = datetime.timedelta(seconds=60)
                if wake_time > now + min_gap:
                    # 唤醒时间未变化则跳过，避免重复日志
                    if self._last_wake_time == wake_time:
                        return
                    # 取消旧定时器后重新设置
                    if self._wake_timer_handle:
                        utils.cancel_wake_timer(self._wake_timer_handle)
                        self._wake_timer_handle = None
                    handle = utils.set_wake_timer(wake_time)
                    if handle:
                        self._wake_timer_handle = handle
                        self._last_wake_time = wake_time
                        print(f"🔔 已设置冷却唤醒定时器：{wake_time.strftime('%H:%M')}")
        except Exception as e:
            print(f"⚠️ 更新冷却唤醒定时器失败: {e}")

    def _show_reminder(self, minutes):
        """显示运行前提醒弹窗"""
        if self._reminder_window and self._reminder_window.winfo_exists():
            return

        self._reminder_window = tk.Toplevel(self.root)
        self._reminder_window.title("⏰ 运行提醒")
        self._reminder_window.geometry("420x200")
        self._reminder_window.resizable(False, False)
        self._reminder_window.transient(self.root)
        self._reminder_window.attributes('-topmost', True)

        # 居中
        self._reminder_window.update_idletasks()
        x = (self._reminder_window.winfo_screenwidth() - 420) // 2
        y = (self._reminder_window.winfo_screenheight() - 200) // 2
        self._reminder_window.geometry(f"420x200+{x}+{y}")

        frame = ttk.Frame(self._reminder_window, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"程序即将在 {minutes} 分钟后运行",
                 font=('Microsoft YaHei UI', 14, 'bold')).pack(pady=(10, 5))
        ttk.Label(frame, text=f"将于 {self._next_run_time_str} 开始执行任务",
                 font=('Microsoft YaHei UI', 9)).pack(pady=(0, 15))

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)

        ttk.Button(btn_frame, text="立即运行", style='Success.TButton',
                  command=self._reminder_run_now, width=10).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="取消本次", style='Danger.TButton',
                  command=self._reminder_cancel, width=10).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="关闭提醒", style='TButton',
                  command=self._reminder_dismiss, width=10).pack(side=tk.LEFT)

        self._reminder_window.protocol("WM_DELETE_WINDOW", self._reminder_dismiss)

    def _reminder_run_now(self):
        """提醒窗口：立即运行"""
        if self._reminder_window:
            try:
                self._reminder_window.destroy()
            except Exception:
                pass
            self._reminder_window = None
        self._reminder_cancelled_time = None
        self._reminder_shown = False
        if not self.running:
            utils.prevent_sleep()
            self.start()

    def _reminder_cancel(self):
        """提醒窗口：取消本次运行（仅取消当前时间点，不影响其他时间点）"""
        if self._reminder_window:
            try:
                self._reminder_window.destroy()
            except Exception:
                pass
            self._reminder_window = None
        self._reminder_cancelled_time = self._next_run_time_str
        print(f"⏹ 用户取消了 {self._next_run_time_str} 的定时运行")

    def _reminder_dismiss(self):
        """提醒窗口：仅关闭弹窗，不影响定时运行"""
        if self._reminder_window:
            try:
                self._reminder_window.destroy()
            except Exception:
                pass
            self._reminder_window = None
        print(f"ℹ️ 已关闭提醒弹窗，定时任务 {self._next_run_time_str} 继续执行")

    def _update_ui_after_single(self):
        self.settings["auto_start"] = False
        config.save_settings(self.settings)

    def _reschedule_single(self, skipped_target):
        """单次模式取消后，自动跳到明天同一时间重新调度"""
        now = datetime.datetime.now()
        tomorrow = skipped_target + datetime.timedelta(days=1)
        h, m = map(int, self._schedule_times[0].split(":"))
        next_target = now.replace(hour=h, minute=m, second=0, microsecond=0) + datetime.timedelta(days=1)
        print(f"ℹ️ 单次定时已跳过，将在明天 {next_target.strftime('%Y-%m-%d %H:%M')} 重新执行")
        # 重新启动调度器
        self._reminder_shown = False
        self._reminder_cancelled_time = None
        self._start_scheduler()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        # ===== 顶部标题栏 =====
        header = ttk.Frame(self.root, style='Header.TFrame')
        header.pack(fill=tk.X, padx=0, pady=0, ipady=8)
        ttk.Label(header, text="三角洲行动自动化工具", style='Header.TLabel').pack(side=tk.LEFT, padx=(15, 5))
        ttk.Label(header, text="v1.0.3  |  多账号轮换 · 定时执行 · 自动化操作", style='HeaderSub.TLabel').pack(side=tk.LEFT, padx=5)

        # ===== 主内容区 =====
        main_container = ttk.Frame(self.root, style='TFrame')
        main_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 12))

        # ----- QQ 账号管理 -----
        account_frame = ttk.LabelFrame(main_container, text=" QQ 账号管理（截图顺序即运行顺序） ", style='Card.TLabelframe', padding=12)
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
                                          bg='#d5d5d5', fg='#1a1a1a',
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
        self.account_menu.add_command(label="裁剪截图（聚焦QQ号区域）", command=self._crop_account_image)
        self.account_menu.add_separator()
        self.account_menu.add_command(label="删除选中", command=self.delete_account)
        self.account_listbox.bind("<Button-3>", self._show_account_menu)
        self.account_listbox.bind("<Double-1>", self._manual_add_cooldown)


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
        ttk.Button(info_row, text="查看冷却", style='TButton',
                   command=self._show_cooldown_window, width=10).pack(side=tk.RIGHT)

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

    def _redirect_output(self):
        sys.stdout = RedirectText(self.log_area, self._log_file_path)
        sys.stderr = RedirectText(self.log_area, self._log_file_path)

    def apply_auto_settings_from_window(self):
        """从设置窗口保存后应用自动任务设置"""
        if self.settings.get("auto_start", False):
            self._start_scheduler()
            # auto_start 启用时停止冷却监听（互斥）
            self._stop_cooldown_watcher()
        else:
            if self._schedule_thread and self._schedule_thread.is_alive():
                self._scheduler_stop_event.set()
                self._schedule_thread.join(timeout=5)
            self._schedule_thread = None
            print("⏰ 已取消定时执行")
            # 取消旧定时器
            if self._wake_timer_handle:
                utils.cancel_wake_timer(self._wake_timer_handle)
                self._wake_timer_handle = None
                self._last_wake_time = None

        # 冷却完立即运行监听
        if self.settings.get("cooldown_run_immediately", False):
            self._start_cooldown_watcher()
        else:
            self._stop_cooldown_watcher()

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
            "【基本操作】\n"
            "F1 / 「开始运行」 → 依次登录 QQ → WeGame → 进游戏执行任务\n"
            "F2 / 「停止」       → 终止当前运行\n\n"
            "【账号管理】\n"
            "• 添加账号：点击「添加账号」选择 QQ 登录截图\n"
            "• 删除账号：右键账号 → 删除选中\n"
            "• 双击账号：手动将该账号加入冷却（需先启用冷却功能）\n"
            "• 右键账号 → 测试截图识别：验证当前截图能否被识别\n\n"
            "【账号冷却】\n"
            "设置 → 其他设置 → 启用账号冷却（默认8小时）\n"
            "• 点击「查看冷却」可查看所有账号冷却状态\n"
            "• 在冷却窗口中可重置单个账号或一键重置所有冷却\n"
            "• 运行失败或手动停止的账号不会记录冷却\n"
            "• 冷却完立即运行：冷却结束后自动执行任务\n\n"
            "【定时执行】\n"
            "设置 → 自动任务设置 → 启用定时，可设多个时间点（HH:MM）\n"
            "支持「单次」和「每日循环」两种模式\n"
            "可勾选需要执行的操作（技术中心/工作台/防具台/制药台）\n\n"
            "【运行提醒】\n"
            "开启后运行前弹窗提醒，可选择提前1~15分钟\n"
            "取消本次不影响后续时间点\n\n"
            "【电源管理】\n"
            "自动唤醒系统显示器、自动关机、定时开机（需主板支持 RTC）\n\n"
            "【开机自启动】\n"
            "设置 → 其他设置 → 可配置开机自启动及开机立即运行\n\n"
            "【注意】\n"
            "• 图像识别依赖固定分辨率/缩放比例\n"
            "• 步骤超时自动跳过当前账号，继续执行下一个\n"
            "• 停止信号发出后，当前步骤完成才退出\n"
            "• 定时执行前5分钟自动唤醒，请确保电脑处于休眠/睡眠状态"
        )
        messagebox.showinfo("使用说明", help_text)

    # ---------- 账号持久化 ----------
    def save_accounts(self):
        try:
            data = {"wegame": [], "qq": self.qq_account_images}
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
            # 兼容旧格式（纯列表 → 丢弃，不再使用 WeGame 账号列表）
            if isinstance(data, list):
                self.qq_account_images = []
            else:
                self.qq_account_images = [p for p in data.get("qq", []) if os.path.exists(p)]
            # 刷新 QQ 账号列表
            self.account_listbox.delete(0, tk.END)
            for p in self.qq_account_images:
                self.account_listbox.insert(tk.END, os.path.basename(p))
            print(f"✅ 已加载 {len(self.qq_account_images)} 个 QQ 账号")
        except Exception as e:
            print(f"⚠️ 加载历史账号失败：{e}")

    def add_account(self):
        file_path = filedialog.askopenfilename(
            title="选择 QQ 号截图",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")]
        )
        if file_path:
            if file_path in self.qq_account_images:
                messagebox.showwarning("提示", "该账号图片已存在，不能重复添加！")
                return
            self.qq_account_images.append(file_path)
            self.account_listbox.insert(tk.END, os.path.basename(file_path))
            self.update_account_count()
            self.save_accounts()

    def delete_account(self):
        sel = self.account_listbox.curselection()
        if sel:
            idx = sel[0]
            self.account_listbox.delete(idx)
            del self.qq_account_images[idx]
            self.update_account_count()
            self.save_accounts()

    def clear_accounts(self):
        self.account_listbox.delete(0, tk.END)
        self.qq_account_images.clear()
        self.update_account_count()
        self.save_accounts()

    def update_account_count(self):
        self.total_steps = len(self.qq_account_images) * 4
        self.progress['maximum'] = max(1, self.total_steps)

    # ---------- 账号排序 ----------
    def _move_up(self):
        sel = self.account_listbox.curselection()
        if sel and sel[0] > 0:
            idx = sel[0]
            self.qq_account_images[idx], self.qq_account_images[idx-1] = self.qq_account_images[idx-1], self.qq_account_images[idx]
            self._refresh_account_list()
            self.account_listbox.selection_set(idx-1)

    def _move_down(self):
        sel = self.account_listbox.curselection()
        if sel and sel[0] < len(self.qq_account_images) - 1:
            idx = sel[0]
            self.qq_account_images[idx], self.qq_account_images[idx+1] = self.qq_account_images[idx+1], self.qq_account_images[idx]
            self._refresh_account_list()
            self.account_listbox.selection_set(idx+1)

    def _refresh_account_list(self):
        self.account_listbox.delete(0, tk.END)
        for p in self.qq_account_images:
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

    def _manual_add_cooldown(self, event):
        """双击账号列表手动为该账号记录冷却时间"""
        sel = self.account_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self.qq_account_images):
            return
        img_path = self.qq_account_images[idx]
        account_name = os.path.basename(img_path)

        if not self.settings.get("enable_cooldown", False):
            messagebox.showinfo("提示",
                "冷却功能未启用，请先在设置中启用「账号冷却」。",
                parent=self.root)
            return

        cooling, next_time = cooldown_manager.is_cooling_down(account_name)
        cd_hours = self.settings.get("cooldown_hours", 8)

        if cooling:
            if not messagebox.askyesno("确认加入冷却",
                    f"「{account_name}」当前仍在冷却中（下次运行：{next_time}）。\n\n"
                    f"是否重新记录冷却时间（{cd_hours}小时）？",
                    parent=self.root):
                return
        else:
            if not messagebox.askyesno("确认加入冷却",
                    f"确定将「{account_name}」加入冷却？\n\n"
                    f"冷却时间：{cd_hours}小时\n"
                    f"加入后该账号在冷却期间不会被自动执行。",
                    parent=self.root):
                return

        cooldown_manager.record_run(account_name, cd_hours)
        _, new_next = cooldown_manager.is_cooling_down(account_name)
        messagebox.showinfo("已记录冷却",
            f"「{account_name}」已记录冷却时间。\n\n"
            f"下次运行时间：{new_next or '未知'}",
            parent=self.root)

    def _test_recognition(self):
        sel = self.account_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个账号")
            return
        idx = sel[0]
        img_path = self.qq_account_images[idx]
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

            # 标准灰度匹配
            res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            # 边缘匹配（对头像轮廓、文字笔画、数字形状更敏感）
            screen_edges = cv2.Canny(gray, 50, 150)
            template_edges = cv2.Canny(template, 50, 150)
            res_edge = cv2.matchTemplate(screen_edges, template_edges, cv2.TM_CCOEFF_NORMED)
            _, edge_val, _, edge_loc = cv2.minMaxLoc(res_edge)

            # 复合多尺度匹配
            matched_ms, max_val_ms, max_loc_ms, best_scale, (ms_h, ms_w) = \
                utils._match_template_multiscale(gray, template, 0.0)

            conf = int(max_val * 100)
            conf_edge = int(edge_val * 100)
            conf_ms = int(max_val_ms * 100)
            threshold = int(config.CONFIDENCE * 100)

            if max_val >= config.CONFIDENCE:
                status = "✅ 灰度匹配成功"
            elif edge_val >= config.CONFIDENCE:
                status = "✅ 边缘匹配成功（头像/文字/数字特征）"
            elif max_val_ms >= config.CONFIDENCE:
                status = f"✅ 复合多尺度匹配成功（缩放 {best_scale:.2f}x）"
            else:
                status = "❌ 匹配度不足，建议裁剪截图保留头像+名称+QQ号区域"

            scale_info = f"（缩放 {best_scale:.2f}x）" if best_scale != 1.0 else "（原始比例）"
            messagebox.showinfo(
                "测试结果",
                f"截图：{os.path.basename(img_path)}\n"
                f"模板尺寸：{template.shape[1]}x{template.shape[0]}\n\n"
                f"灰度匹配度：{conf}% (阈值：{threshold}%)\n"
                f"边缘匹配度：{conf_edge}% （头像轮廓/文字/数字特征）\n"
                f"复合多尺度：{conf_ms}% {scale_info}\n\n"
                f"结论：{status}\n\n"
                f"提示：截图应包含头像+名称+QQ号，这些特征组合可帮助精确区分不同账号。"
            )
        except Exception as e:
            messagebox.showerror("测试失败", f"识别过程出错：{e}")

    def _crop_account_image(self):
        """裁剪QQ账号截图，框选包含头像+名称+QQ号的区域以提高识别精度"""
        sel = self.account_listbox.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个账号", parent=self.root)
            return
        idx = sel[0]
        img_path = self.qq_account_images[idx]
        if not os.path.exists(img_path):
            messagebox.showerror("错误", "截图文件不存在", parent=self.root)
            return

        try:
            from PIL import Image, ImageTk, ImageDraw
            img = Image.open(img_path)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图片：{e}", parent=self.root)
            return

        # 创建裁剪窗口
        crop_win = tk.Toplevel(self.root)
        crop_win.title(f"裁剪截图 - {os.path.basename(img_path)}")
        crop_win.resizable(True, True)
        crop_win.transient(self.root)
        crop_win.grab_set()

        # 设置图标
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                crop_win._icon_photo = ImageTk.PhotoImage(icon_img)
                crop_win.iconphoto(False, crop_win._icon_photo)
        except Exception:
            pass

        # 说明文字
        ttk.Label(crop_win, text="拖动鼠标框选包含头像+名称+QQ号的区域（三个特征组合可精确区分不同账号），然后点击「保存裁剪」",
                  font=('Microsoft YaHei UI', 9), foreground='#555').pack(padx=10, pady=(10, 5), anchor='w')

        # 图片显示区域
        canvas_frame = ttk.Frame(crop_win)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        canvas = tk.Canvas(canvas_frame, bg='#2c3e50', cursor='crosshair')
        canvas.pack(fill=tk.BOTH, expand=True)

        # 显示图片
        orig_w, orig_h = img.size
        canvas.update_idletasks()
        # 初始缩放以适应窗口
        display_img = img.copy()
        max_canvas_w, max_canvas_h = 800, 500
        scale_x = max_canvas_w / orig_w if orig_w > max_canvas_w else 1.0
        scale_y = max_canvas_h / orig_h if orig_h > max_canvas_h else 1.0
        display_scale = min(scale_x, scale_y, 1.0)
        disp_w = int(orig_w * display_scale)
        disp_h = int(orig_h * display_scale)
        if display_scale < 1.0:
            display_img = img.resize((disp_w, disp_h), Image.LANCZOS)
        else:
            display_img = img.copy()

        photo = ImageTk.PhotoImage(display_img)
        canvas.create_image(0, 0, anchor='nw', image=photo)
        canvas.config(scrollregion=canvas.bbox("all"))

        # 裁剪状态
        crop_state = {'start_x': 0, 'start_y': 0, 'rect_id': None, 'crop_rect': None}

        def on_press(event):
            crop_state['start_x'] = event.x
            crop_state['start_y'] = event.y
            if crop_state['rect_id']:
                canvas.delete(crop_state['rect_id'])
            crop_state['rect_id'] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline='#e74c3c', width=2, dash=(4, 4))

        def on_drag(event):
            if crop_state['rect_id']:
                canvas.coords(crop_state['rect_id'],
                              crop_state['start_x'], crop_state['start_y'],
                              event.x, event.y)

        def on_release(event):
            x1 = min(crop_state['start_x'], event.x)
            y1 = min(crop_state['start_y'], event.y)
            x2 = max(crop_state['start_x'], event.x)
            y2 = max(crop_state['start_y'], event.y)
            # 转换回原始图片坐标
            orig_x1 = int(x1 / display_scale)
            orig_y1 = int(y1 / display_scale)
            orig_x2 = int(x2 / display_scale)
            orig_y2 = int(y2 / display_scale)
            # 确保在图片范围内
            orig_x1 = max(0, min(orig_x1, orig_w))
            orig_y1 = max(0, min(orig_y1, orig_h))
            orig_x2 = max(0, min(orig_x2, orig_w))
            orig_y2 = max(0, min(orig_y2, orig_h))
            if orig_x2 - orig_x1 > 5 and orig_y2 - orig_y1 > 5:
                crop_state['crop_rect'] = (orig_x1, orig_y1, orig_x2, orig_y2)
                size_text = f"选区：{orig_x2-orig_x1}x{orig_y2-orig_y1} 像素"
                crop_info_label.config(text=size_text)
            else:
                crop_state['crop_rect'] = None
                crop_info_label.config(text="选区过小，请重新框选")

        canvas.bind('<ButtonPress-1>', on_press)
        canvas.bind('<B1-Motion>', on_drag)
        canvas.bind('<ButtonRelease-1>', on_release)

        # 底部信息和按钮
        bottom_frame = ttk.Frame(crop_win)
        bottom_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        crop_info_label = ttk.Label(bottom_frame, text=f"原始尺寸：{orig_w}x{orig_h}  |  请拖动鼠标框选区域",
                                    font=('Microsoft YaHei UI', 9), foreground='#7f8c8d')
        crop_info_label.pack(side=tk.LEFT)

        def save_crop():
            if not crop_state['crop_rect']:
                messagebox.showwarning("提示", "请先框选要裁剪的区域", parent=crop_win)
                return
            x1, y1, x2, y2 = crop_state['crop_rect']
            cropped = img.crop((x1, y1, x2, y2))
            try:
                cropped.save(img_path)
                self.qq_account_images[idx] = img_path  # 路径不变
                print(f"✅ 截图已裁剪并保存：{img_path} ({x2-x1}x{y2-y1})")
                messagebox.showinfo("完成",
                    f"截图已裁剪并保存！\n\n"
                    f"裁剪区域：{x2-x1}x{y2-y1} 像素\n"
                    f"建议：保留头像+名称+QQ号三个特征区域，组合可精确区分不同账号。\n"
                    f"可在右键菜单中使用「测试截图识别」验证效果。",
                    parent=crop_win)
                crop_win.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"保存失败：{e}", parent=crop_win)

        def cancel_crop():
            crop_win.destroy()

        ttk.Button(bottom_frame, text="保存裁剪", command=save_crop, width=10).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(bottom_frame, text="取消", command=cancel_crop, width=8).pack(side=tk.RIGHT)

        # 居中窗口
        crop_win.update_idletasks()
        w = max(crop_win.winfo_width(), 850)
        h = max(crop_win.winfo_height(), 600)
        x = (crop_win.winfo_screenwidth() - w) // 2
        y = (crop_win.winfo_screenheight() - h) // 2
        crop_win.geometry(f"{w}x{h}+{x}+{y}")

    # ---------- 冷却查看 ----------
    def _show_cooldown_window(self):
        """弹出冷却状态查看窗口"""
        win = tk.Toplevel(self.root)
        win.title("账号冷却状态")
        win.geometry("700x480")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        # 居中
        win.update_idletasks()
        x = (win.winfo_screenwidth() - 700) // 2
        y = (win.winfo_screenheight() - 480) // 2
        win.geometry(f"700x480+{x}+{y}")
        # 图标
        try:
            icon_path = config.resource_path("picture/icon/icon.ico")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                win._icon_photo = ImageTk.PhotoImage(icon_img)
                win.iconphoto(False, win._icon_photo)
        except Exception:
            pass

        # Treeview 区域（独立 Frame，确保与按钮区域垂直排列）
        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        columns = ("account", "last_run", "remaining", "next_run")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10)
        tree.heading("account", text="账号名称")
        tree.heading("last_run", text="上次运行时间")
        tree.heading("remaining", text="冷却剩余")
        tree.heading("next_run", text="下次运行时间")
        tree.column("account", width=150, anchor="center")
        tree.column("last_run", width=150, anchor="center")
        tree.column("remaining", width=120, anchor="center")
        tree.column("next_run", width=150, anchor="center")

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))

        def _format_remaining(seconds):
            if seconds <= 0:
                return "已冷却"
            h = seconds // 3600
            m = (seconds % 3600) // 60
            if h > 0:
                return f"{h}小时{m}分钟"
            return f"{m}分钟"

        def _refresh():
            tree.delete(*tree.get_children())
            all_cd = cooldown_manager.get_all_cooldowns()
            for name, info in sorted(all_cd.items()):
                remaining_str = _format_remaining(info["remaining_seconds"])
                tree.insert("", tk.END, values=(
                    name,
                    info["last_run_time"],
                    remaining_str,
                    info["next_run_time"],
                ))

        _refresh()

        # 按钮区域（固定在底部）
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        def _do_reset(account_name):
            """重置指定账号的冷却"""
            if messagebox.askyesno("确认",
                    f"确定重置「{account_name}」的冷却？\n\n"
                    f"重置后该账号将可以立即运行。",
                    parent=win):
                cooldown_manager.reset_cooldown(account_name)
                _refresh()
                # 重置后更新唤醒定时器
                self._set_next_wake_timer()

        def _reset_selected():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择要重置的账号。", parent=win)
                return
            item = tree.item(sel[0])
            account_name = item["values"][0]
            _do_reset(account_name)

        def _on_double_click(event):
            """双击某行直接重置该账号冷却"""
            sel = tree.identify_row(event.y)
            if not sel:
                return
            tree.selection_set(sel)
            item = tree.item(sel)
            account_name = item["values"][0]
            _do_reset(account_name)

        tree.bind("<Double-1>", _on_double_click)

        ttk.Button(btn_frame, text="重置选中账号冷却", style='TButton',
                   command=_reset_selected, width=16).pack(side=tk.LEFT)

        def _set_custom_time():
            """为选中账号设置自定义冷却结束时间"""
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("提示", "请先选择要设置的账号。", parent=win)
                return
            item = tree.item(sel[0])
            account_name = item["values"][0]

            # 弹出输入对话框
            dialog = tk.Toplevel(win)
            dialog.title("自定义冷却时间")
            dialog.geometry("350x180")
            dialog.resizable(False, False)
            dialog.transient(win)
            dialog.grab_set()
            # 居中
            dialog.update_idletasks()
            dx = (dialog.winfo_screenwidth() - 350) // 2
            dy = (dialog.winfo_screenheight() - 180) // 2
            dialog.geometry(f"350x180+{dx}+{dy}")

            ttk.Label(dialog, text=f"为「{account_name}」设置冷却结束时间",
                      font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=(15, 5))
            ttk.Label(dialog, text="输入格式：HH:MM（当天/明天）或 YYYY-MM-DD HH:MM:SS",
                      font=('Microsoft YaHei UI', 8), foreground='#7f8c8d').pack()

            time_var = tk.StringVar()
            entry = ttk.Entry(dialog, textvariable=time_var, width=25)
            entry.pack(pady=8)
            entry.focus_set()

            def _confirm():
                raw = time_var.get().strip()
                if not raw:
                    messagebox.showwarning("提示", "请输入时间", parent=dialog)
                    return
                if cooldown_manager.set_custom_cooldown(account_name, raw):
                    dialog.destroy()
                    _refresh()
                    self._set_next_wake_timer()
                    messagebox.showinfo("完成", f"「{account_name}」冷却时间已更新。", parent=win)
                else:
                    messagebox.showerror("错误", "时间格式不正确，请使用 HH:MM 或 YYYY-MM-DD HH:MM:SS", parent=dialog)

            btn_f = ttk.Frame(dialog)
            btn_f.pack(pady=5)
            ttk.Button(btn_f, text="确定", command=_confirm, width=8).pack(side=tk.LEFT, padx=5)
            ttk.Button(btn_f, text="取消", command=dialog.destroy, width=8).pack(side=tk.LEFT, padx=5)
            # 回车确认
            dialog.bind("<Return>", lambda e: _confirm())

        ttk.Button(btn_frame, text="自定义冷却时间", style='TButton',
                   command=_set_custom_time, width=14).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(btn_frame, text="刷新", style='TButton',
                   command=_refresh, width=8).pack(side=tk.LEFT, padx=(10, 0))

        def _reset_all():
            all_cd = cooldown_manager.get_all_cooldowns()
            if not all_cd:
                messagebox.showinfo("提示", "当前没有任何冷却记录。", parent=win)
                return
            count = len(all_cd)
            if messagebox.askyesno("确认",
                    f"确定重置所有 {count} 个账号的冷却？\n\n"
                    f"重置后所有账号将可以立即运行。",
                    parent=win):
                cooldown_manager.reset_all_cooldowns()
                _refresh()
                # 重置后更新唤醒定时器
                self._set_next_wake_timer()

        ttk.Button(btn_frame, text="一键重置所有", style='TButton',
                   command=_reset_all, width=12).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(btn_frame, text="关闭", style='TButton',
                   command=win.destroy, width=8).pack(side=tk.RIGHT)

    # ---------- 启停控制 ----------
    def start(self):
        if self.running:
            return
        if not self.qq_account_images:
            messagebox.showwarning("未添加账号", "请先添加至少一个 QQ 账号截图！")
            return
        self.running = True
        self._stop_event.clear()
        self._user_stopped_cooldown = False  # 新运行开始，清除停止标志
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
        # 启动心跳同步
        self._start_heartbeat()
        self.work_thread = threading.Thread(target=self.run_script_main, daemon=True)
        self.work_thread.start()

    def stop(self):
        if not self.running:
            return
        self._stop_event.set()
        self.running = False
        # 标记用户主动停止，阻止冷却监听在短时间内重新触发
        self._user_stopped_cooldown = True
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

    # ---------- 主流程 ----------
    def run_script_main(self):
        try:
            total = len(self.qq_account_images)
            qq_path = self.settings.get("qq_path", "")
            processed_accounts = []  # 记录已处理的QQ号名称

            # 每日首次运行时进行服务器验证
            today_str = datetime.date.today().isoformat()
            if not hasattr(self, '_last_validated_date') or self._last_validated_date != today_str:
                print("🔒 每日验证：正在连接服务器...")
                self.set_operation("服务器验证中")
                allowed, expiry, error = self._validate_with_server()
                if allowed is True:
                    self._last_validated_date = today_str
                    print(f"✅ 每日验证通过，有效期至：{expiry}")
                elif allowed is False:
                    print(f"❌ 验证失败：{error}")
                    self.root.after(0, lambda: messagebox.showerror("验证失败",
                        f"每日验证未通过，程序将退出。\n\n"
                        f"原因：{error}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"本机机器指纹：\n\n"
                        f"  {machine_fingerprint.get_machine_id()}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━"))
                    self.root.after(100, self.root.destroy)
                    return
                else:
                    print(f"❌ 服务器连接失败：{error}")
                    self.root.after(0, lambda: messagebox.showerror("验证失败",
                        f"无法连接验证服务器，程序将退出。\n\n"
                        f"错误：{error}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"本机机器指纹：\n\n"
                        f"  {machine_fingerprint.get_machine_id()}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━"))
                    self.root.after(100, self.root.destroy)
                    return

            # 运行前先退出 QQ 和 WeGame，确保干净状态
            print("🧹 运行前清理：退出 QQ 和 WeGame...")
            self.set_operation("清理进程")
            utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=10)
            utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
            time.sleep(2)

            print("=" * 55)
            print("  QQ 登录 + WeGame 快捷登录 + 三角洲行动 多账号轮换脚本")
            print(f"  本轮将处理 {total} 个 QQ 账号")
            print("=" * 55)

            for i, img_path in enumerate(self.qq_account_images):
                if self._stop_event.is_set():
                    break

                file_name = os.path.basename(img_path)
                current_account_name = file_name

                # 冷却检查（定时任务触发时可跳过冷却检查）
                if self.settings.get("enable_cooldown", False) and not self._ignore_cooldown_this_run:
                    cooling, next_time = cooldown_manager.is_cooling_down(file_name)
                    if cooling:
                        print(f"⏸️ 账号 {file_name} 冷却中，跳过。下次运行时间：{next_time}")
                        processed_accounts.append(f"{file_name} (冷却中)")
                        self._update_account_status(file_name, "cooling")
                        continue

                acc_text = f"第 {i+1}/{total} 个账号"
                self.root.after(0, self.update_ui, False, acc_text, file_name)
                print(f"\n{'='*40}")
                print(f"    {acc_text}  -  {file_name}")
                print(f"{'='*40}")
                self.run_stats["total"] += 1
                account_failed = False
                account_interrupted = False
                self._update_account_status(file_name, "running")

                # 步骤1：启动 QQ 并登录
                if self._stop_event.is_set():
                    account_interrupted = True
                if not account_interrupted:
                    self.set_operation(f"启动 QQ ({i+1}/{total})")
                    print("启动 QQ...")
                    if not qq_path or not utils.start_app(qq_path, "QQ"):
                        print("❌ QQ 启动失败，跳过此账号")
                        account_failed = True

                if not account_failed:
                    # 等待 QQ 窗口出现（含降级方案）
                    qq_ready = False
                    qq_activate_fail_count = 0
                    qq_degrade_triggered = False
                    for _ in range(30):
                        if self._stop_event.is_set(): break
                        if utils.activate_window_by_title("QQ", partial_match=True,
                                                           exclude_titles=["WeGame"]):
                            qq_ready = True
                            qq_activate_fail_count = 0
                            break
                        qq_activate_fail_count += 1
                        # 连续激活失败5次，启动降级方案：直接图像识别点击 QQ_ACCOUNT_SELECT
                        if qq_activate_fail_count >= 5:
                            qq_degrade_triggered = True
                            print("⚠️ QQ 窗口激活连续失败5次，启动降级方案：尝试图像识别点击...")
                            img_found = False
                            for img_retry in range(3):
                                if self._stop_event.is_set(): break
                                if utils.find_and_click_multiscale(config.QQ_ACCOUNT_SELECT, timeout=5):
                                    img_found = True
                                    qq_ready = True
                                    print(f"✅ 降级方案成功：图像识别点击 QQ_ACCOUNT_SELECT（第 {img_retry+1} 次）")
                                    break
                                print(f"⚠️ 降级方案重试 ({img_retry+1}/3)...")
                                time.sleep(1)
                            if img_found:
                                break
                            else:
                                print(f"❌ 降级方案失败：QQ_ACCOUNT_SELECT 图像识别3次均未找到，账号 {current_account_name} 登录失败，跳过")
                                self._send_account_failure_email(current_account_name, "未启用", processed_accounts)
                                account_failed = True
                                break
                        time.sleep(0.5)
                    if not qq_ready and not account_failed:
                        print("⚠️ 未检测到 QQ 窗口，继续尝试登录...")
                    if qq_ready:
                        time.sleep(1)

                if not account_failed and self._stop_event.is_set():
                    account_interrupted = True
                if not account_failed and not account_interrupted:
                    self.set_operation("QQ 快捷登录")
                    print("开始 QQ 快捷登录...")
                    if not utils.qq_quick_login(img_path):
                        print("❌ QQ 快捷登录失败，跳过此账号")
                        utils.kill_process(config.QQ_PROCESS)
                        account_failed = True
                    else:
                        time.sleep(2)
                        # QQ 登录成功后关闭 QQ 窗口（保留后台进程供 WeGame 使用）
                        utils.close_window_by_title("QQ", partial_match=True)
                        time.sleep(1)

                # 步骤2：启动 WeGame 并快捷登录（使用当前 QQ 账号）
                if not account_failed and self._stop_event.is_set():
                    account_interrupted = True
                if not account_failed and not account_interrupted:
                    self.set_operation("启动 WeGame")
                    print("启动 WeGame...")
                    if not config.WEGAME_PATH or not utils.start_app(config.WEGAME_PATH, "WeGame"):
                        print("❌ WeGame 启动失败，跳过此账号")
                        account_failed = True
                    else:
                        time.sleep(3)

                if not account_failed and self._stop_event.is_set():
                    account_interrupted = True
                if not account_failed and not account_interrupted:
                    self.set_operation("快捷登录 WeGame")
                    print("开始快捷登录 WeGame ...")
                    if not utils.wegame_quick_login():
                        print("❌ WeGame 快捷登录失败，跳过此账号")
                        utils.kill_process(config.WEGAME_PROCESS)
                        account_failed = True
                    else:
                        time.sleep(3)

                # 步骤3：启动三角洲行动
                if not account_failed and self._stop_event.is_set():
                    account_interrupted = True
                if not account_failed and not account_interrupted:
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
                    print("✅ 三角洲正在启动，等待游戏窗口出现...")
                    game_loaded = False
                    delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
                    for _ in range(45):
                        if self._stop_event.is_set():
                            break
                        for title in delta_titles:
                            if utils.activate_window_by_title(title, partial_match=True,
                                                               exclude_titles=["WeGame", "腾讯"]):
                                game_loaded = True
                                break
                        if game_loaded:
                            break
                        time.sleep(2)
                    if game_loaded:
                        print("✅ 检测到游戏窗口，等待界面就绪...")
                        time.sleep(8)
                        extra_wait = self.settings.get("game_launch_wait", 0)
                        if extra_wait > 0:
                            print(f"⏳ 游戏已启动，额外等待 {extra_wait} 秒...")
                            time.sleep(extra_wait)
                    else:
                        print("⚠️ 未检测到游戏窗口，继续尝试操作...")

                    if not self._game_operations():
                        if self._stop_event.is_set():
                            account_interrupted = True
                        else:
                            print("❌ 游戏内操作失败，跳过此账号")
                            account_failed = True
                    if self._stop_event.is_set():
                        account_interrupted = True

                # 步骤4 + 清理：仅在未中断时执行
                if not account_interrupted:
                    # 步骤4：关闭游戏和 WeGame，退出 QQ 和 WeGame 进程
                    if not account_failed:
                        self.set_operation("关闭三角洲游戏")
                        print("\n--- 关闭三角洲游戏 ---")
                        delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
                        for title in delta_titles:
                            if self._stop_event.is_set(): break
                            utils.close_window_by_title(title, partial_match=True)
                        time.sleep(2)
                        utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)

                    # 每轮结束后退出 QQ 和 WeGame，不保留后台
                    self.set_operation("清理进程")
                    print("\n--- 退出 QQ 和 WeGame ---")
                    utils.close_window_by_title("WeGame", partial_match=True)
                    time.sleep(1)
                    utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
                    utils.kill_process(config.QQ_PROCESS, wait_exit=True, max_wait=10)
                    time.sleep(2)

                # 获取下次运行时间
                next_run_str = "未启用"
                if self.settings.get("enable_cooldown", False):
                    _, next_run_str = cooldown_manager.is_cooling_down(current_account_name)
                    next_run_str = next_run_str or "已冷却"

                if account_interrupted:
                    # 用户手动停止，不记录冷却，不计入成功/失败
                    print(f"⏹️ 账号 {current_account_name} 被用户中断，跳过冷却记录")
                    processed_accounts.append(f"{current_account_name} (中断)")
                    self._update_account_status(current_account_name, "idle")
                    break
                elif account_failed:
                    self.run_stats["fail"] += 1
                    processed_accounts.append(f"{current_account_name} (失败)")
                    self._update_account_status(current_account_name, "failed")
                    # 立即发送失败邮件通知
                    self._send_account_failure_email(current_account_name, next_run_str, processed_accounts)
                else:
                    # 只有成功运行的账号才记录冷却时间
                    if self.settings.get("enable_cooldown", False):
                        cd_hours = self.settings.get("cooldown_hours", 8)
                        cooldown_manager.record_run(current_account_name, cd_hours)
                    self.run_stats["success"] += 1
                    processed_accounts.append(f"{current_account_name} (成功)")
                    self._update_account_status(current_account_name, "success")

                # 账号间隔等待：非最后一个账号且未被停止时，等待固定间隔再执行下一个
                if i < total - 1 and not self._stop_event.is_set():
                    interval = self.settings.get("cooldown_delay_minutes", 1)
                    if interval > 0:
                        print(f"⏳ 等待 {interval} 分钟后执行下一个账号...")
                        self.set_operation(f"账号间隔等待 ({interval}分钟)")
                        wait_seconds = interval * 60
                        waited = 0
                        while waited < wait_seconds and not self._stop_event.is_set():
                            chunk = min(5, wait_seconds - waited)
                            time.sleep(chunk)
                            waited += chunk
                        if self._stop_event.is_set():
                            break

            print("\n🎉 所有账号处理完毕！")
        except Exception as e:
            print(f"❌ 运行出错: {e}")
            traceback.print_exc()
            self.run_stats["error"] = str(e)
            self._send_failure_email(e, processed_accounts)
        finally:
            self.run_stats["processed_accounts"] = processed_accounts
            self.root.after(0, self.on_finish)

    def _game_operations(self):
        """执行游戏内操作，返回 True=成功，False=失败"""
        result = automation.game_operations(
            self.settings, self._stop_event, self.set_operation,
            update_ui_callback=lambda: self.root.after(0, self.update_ui, True))
        # 处理返回值：game_operations 可能返回 bool 或 (bool, dict)
        if isinstance(result, tuple):
            success, sell_stats = result
            if success:
                self.run_stats["sell_stats"] = sell_stats
            return success
        return result

    def _sell_operations(self):
        """一键出售流程：打开仓库，遍历售卖物品执行出售"""
        return automation.sell_operations(self.settings, self._stop_event, self.set_operation)

    def on_finish(self):
        self.running = False
        self._stop_event.clear()  # 清除工作线程停止信号，不影响调度器
        self._ignore_cooldown_this_run = False  # 重置冷却忽略标志
        # 停止心跳同步
        self._stop_heartbeat()
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.progress['value'] = self.progress['maximum']

        # 用户手动停止时，清理可能残留的进程
        if self._user_stopped_cooldown:
            try:
                utils.kill_process(config.DELTA_PROCESS, wait_exit=False)
                utils.kill_process(config.WEGAME_PROCESS, wait_exit=False)
                utils.kill_process(config.QQ_PROCESS, wait_exit=False)
            except Exception:
                pass

        # 恢复系统睡眠设置
        utils.allow_sleep()

        # 设置下一次唤醒定时器
        self._set_next_wake_timer()

        # 调度器健康检查：如果调度器线程已退出，重新启动
        if self.settings.get("auto_start", False):
            if not self._schedule_thread or not self._schedule_thread.is_alive():
                print("⚠️ 检测到调度器线程已退出，正在重新启动...")
                self._start_scheduler()

        # 冷却监听健康检查：确保冷却到期监听线程正常运行
        if self.settings.get("cooldown_run_immediately", False):
            watcher_alive = (hasattr(self, '_cooldown_watcher_thread')
                            and self._cooldown_watcher_thread
                            and self._cooldown_watcher_thread.is_alive())
            if not watcher_alive:
                print("⚠️ 检测到冷却监听线程已退出，正在重新启动...")
                self._start_cooldown_watcher()

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

        # 发送邮件通知
        processed_accounts = stats.get("processed_accounts", [])
        self._send_email_notification(stats, elapsed, processed_accounts)

        # 运行完成后延迟关机
        shutdown_delay = self.settings.get("post_run_shutdown_delay", 0)
        if shutdown_delay > 0:
            delay_seconds = shutdown_delay * 60
            utils.schedule_shutdown(delay_seconds)
            print(f"🔌 所有账号运行完毕，系统将在 {shutdown_delay} 分钟后关机")
            print(f"   如需取消关机，请在命令行执行: shutdown /a")

    def _get_account_next_run(self, account_name):
        """获取账号的下次运行时间描述"""
        if not self.settings.get("enable_cooldown", False):
            return "未启用"
        _, next_time = cooldown_manager.is_cooling_down(account_name)
        return next_time or "已冷却"

    def _build_accounts_html(self, processed_accounts):
        """构建已处理账号列表的 HTML（含下次运行时间）"""
        if not processed_accounts:
            return ""
        items = []
        for acc in processed_accounts:
            # acc 格式: "xxx.png (成功)" 或 "xxx.png (失败)" 或 "xxx.png (冷却中)"
            next_run = "未启用"
            if self.settings.get("enable_cooldown", False):
                # 提取账号文件名（去掉状态后缀）
                account_name = acc.split(" (")[0] if " (" in acc else acc
                next_run = self._get_account_next_run(account_name)
            items.append(f"<li>{html.escape(acc)}　｜　下次运行：{html.escape(next_run)}</li>")
        accounts_html = "".join(items)
        return f"""
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">已处理账号</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;"><ul style="margin:0;padding-left:20px;">{accounts_html}</ul></td></tr>"""

    def _send_account_failure_email(self, account_name, next_run_str, processed_accounts=None):
        """单个账号失败时立即发送邮件通知"""
        if not self.settings.get("email_enabled", False):
            return
        smtp_code = self.settings.get("smtp_code", "").strip()
        sender = self.settings.get("sender_email", "").strip()
        receiver = self.settings.get("receiver_email", "").strip()
        if not smtp_code or not sender or not receiver:
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats = self.run_stats
        elapsed = time.time() - stats["start_time"] if stats["start_time"] else 0
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        time_str = f"{h}时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"

        accounts_section = self._build_accounts_html(processed_accounts)
        safe_name = html.escape(account_name)
        safe_next = html.escape(next_run_str or "无")

        body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#e74c3c;border-bottom:2px solid #e74c3c;padding-bottom:10px;">三角洲行动自动化工具 - 账号运行失败</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">失败账号信息</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">账号名称</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#e74c3c;font-weight:bold;">{safe_name}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">下次运行</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{safe_next}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">已运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{time_str}</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">累计成功</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{stats['success']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">累计失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#e74c3c;">{stats['fail']} 个</td></tr>
{accounts_section}
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:#e74c3c15;border:1px solid #e74c3c40;">
<span style="font-size:16px;font-weight:bold;color:#e74c3c;">账号 {safe_name} 运行失败，后续账号将继续执行</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

        def _send():
            success, msg = utils.send_email_notification(
                smtp_code, sender, receiver,
                f"三角洲自动化 - 账号失败通知 ({account_name})", body
            )
            if success:
                print(f"📧 账号 {account_name} 失败通知邮件已发送")
            else:
                print(f"📧 失败通知邮件发送失败：{msg}")

        threading.Thread(target=_send, daemon=True).start()

    def _send_cooldown_ready_email(self, ready_accounts):
        """冷却到期时发送邮件提醒"""
        if not self.settings.get("cooldown_email_enabled", False):
            return
        if not self.settings.get("email_enabled", False):
            return
        smtp_code = self.settings.get("smtp_code", "").strip()
        sender = self.settings.get("sender_email", "").strip()
        receiver = self.settings.get("receiver_email", "").strip()
        if not smtp_code or not sender or not receiver:
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        account_items = "".join(f"<li style='padding:3px 0;'>{html.escape(name)}</li>" for name in ready_accounts)
        count = len(ready_accounts)

        body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#27ae60;border-bottom:2px solid #27ae60;padding-bottom:10px;">三角洲行动自动化工具 - 冷却到期提醒</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">提醒时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">到期账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;font-weight:bold;">{count} 个</td></tr>
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">到期账号列表</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;"><ul style="margin:0;padding-left:20px;">{account_items}</ul></td></tr>
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:#27ae6015;border:1px solid #27ae6040;">
<span style="font-size:16px;font-weight:bold;color:#27ae60;">以上账号冷却已到期，即将自动执行任务</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

        def _send():
            success, msg = utils.send_email_notification(
                smtp_code, sender, receiver,
                f"三角洲自动化 - 冷却到期提醒 ({count}个账号)", body
            )
            if success:
                print(f"📧 冷却到期提醒邮件已发送（{count}个账号）")
            else:
                print(f"📧 冷却到期提醒邮件发送失败：{msg}")

        threading.Thread(target=_send, daemon=True).start()

    def _send_email_notification(self, stats, elapsed, processed_accounts=None):
        """在后台线程中发送邮件通知"""
        if not self.settings.get("email_enabled", False):
            return
        smtp_code = self.settings.get("smtp_code", "").strip()
        sender = self.settings.get("sender_email", "").strip()
        receiver = self.settings.get("receiver_email", "").strip()
        if not smtp_code or not sender or not receiver:
            return

        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        time_str = f"{h}时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_color = "#27ae60" if stats["fail"] == 0 else "#e74c3c"
        status_text = "全部成功" if stats["fail"] == 0 else f"有 {stats['fail']} 个失败"

        # 已选操作
        op_names = {"tech_center": "技术中心", "tool_bench": "工作台",
                    "armor_station": "防具台", "pharmacy_station": "制药台"}
        selected = self.settings.get("selected_operations", [])
        ops_text = "、".join(op_names.get(op, op) for op in selected) if selected else "无"

        # 运行模式
        run_mode = self.settings.get("run_mode", "单次")
        schedule_times = self.settings.get("schedule_times", [])
        mode_text = f"每日循环（{', '.join(schedule_times)}）" if run_mode == "每日循环" and schedule_times else "单次执行"

        # 一键出售统计
        sell_section = ""
        sell_stats = stats.get("sell_stats")
        if sell_stats:
            sell_section = f"""
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">一键出售</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">物品总数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{sell_stats['total']} 件</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功上架</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{sell_stats['sold']} 件</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">未找到</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e67e22' if sell_stats['not_found']>0 else '#2c3e50'};">{sell_stats['not_found']} 件</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e74c3c' if sell_stats['failed']>0 else '#2c3e50'};">{sell_stats['failed']} 件</td></tr>"""

        # QQ号名称列表（含下次运行时间）
        accounts_section = self._build_accounts_html(processed_accounts)

        body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px;">三角洲行动自动化工具 - 运行报告</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">基本信息</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">运行模式</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{mode_text}</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">执行操作</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{ops_text}</td></tr>
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">账号统计</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">处理账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{stats['total']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{stats['success']} 个</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e74c3c' if stats['fail']>0 else '#2c3e50'};">{stats['fail']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">耗时</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{time_str}</td></tr>
{sell_section}
{accounts_section}
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:{status_color}15;border:1px solid {status_color}40;">
<span style="font-size:16px;font-weight:bold;color:{status_color};">运行状态：{status_text}</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

        def _send():
            success, msg = utils.send_email_notification(
                smtp_code, sender, receiver,
                f"三角洲自动化 - 运行报告 ({status_text})", body
            )
            if success:
                print("📧 邮件通知已发送")
            else:
                print(f"📧 邮件通知发送失败：{msg}")

        threading.Thread(target=_send, daemon=True).start()

    def _send_failure_email(self, error, processed_accounts=None):
        """程序异常退出时发送失败邮件通知"""
        if not self.settings.get("email_enabled", False):
            return
        smtp_code = self.settings.get("smtp_code", "").strip()
        sender = self.settings.get("sender_email", "").strip()
        receiver = self.settings.get("receiver_email", "").strip()
        if not smtp_code or not sender or not receiver:
            return

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats = self.run_stats
        elapsed = time.time() - stats["start_time"] if stats["start_time"] else 0
        m, s = divmod(int(elapsed), 60)
        h, m = divmod(m, 60)
        time_str = f"{h}时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"

        # 已选操作
        op_names = {"tech_center": "技术中心", "tool_bench": "工作台",
                    "armor_station": "防具台", "pharmacy_station": "制药台"}
        selected = self.settings.get("selected_operations", [])
        ops_text = "、".join(op_names.get(op, op) for op in selected) if selected else "无"

        # 运行模式
        run_mode = self.settings.get("run_mode", "单次")
        schedule_times = self.settings.get("schedule_times", [])
        mode_text = f"每日循环（{', '.join(schedule_times)}）" if run_mode == "每日循环" and schedule_times else "单次执行"

        # QQ号名称列表（含下次运行时间）
        accounts_section = self._build_accounts_html(processed_accounts)

        body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#e74c3c;border-bottom:2px solid #e74c3c;padding-bottom:10px;">三角洲行动自动化工具 - 运行失败通知</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">基本信息</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">运行模式</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{mode_text}</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">执行操作</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{ops_text}</td></tr>
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">运行统计</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">处理账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{stats['total']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{stats['success']} 个</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#e74c3c;">{stats['fail']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">已运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{time_str}</td></tr>
{accounts_section}
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#e74c3c;">错误信息</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;background:#fff5f5;color:#e74c3c;">{html.escape(str(error))}</td></tr>
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:#e74c3c15;border:1px solid #e74c3c40;">
<span style="font-size:16px;font-weight:bold;color:#e74c3c;">运行状态：程序异常退出</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

        def _send():
            success, msg = utils.send_email_notification(
                smtp_code, sender, receiver,
                "三角洲自动化 - 运行失败通知", body
            )
            if success:
                print("📧 失败通知邮件已发送")
            else:
                print(f"📧 失败通知邮件发送失败：{msg}")

        threading.Thread(target=_send, daemon=True).start()


def main():
    config.APP_SETTINGS = config.init_settings()
    config.WEGAME_PATH = config.APP_SETTINGS.get("wegame_path", "")
    config.CONFIDENCE = config.APP_SETTINGS["confidence"]

    root = tk.Tk()
    root.title("三角洲行动自动化工具")
    root.resizable(False, False)

    # 显示加载界面，避免用户看到空白窗口
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

    # 窗口居中显示
    root.update_idletasks()
    w, h = 400, 200
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    def _init_app():
        """服务器验证通过后初始化应用"""
        progress.stop()
        loading_frame.destroy()
        root.geometry("")
        _check_resolution_on_startup(root)
        App(root)
        root.after(50, lambda: (root.lift(), root.focus_force()))
        root.after(50, lambda: root.attributes('-topmost', True))
        root.after(200, lambda: root.attributes('-topmost', False))

    # 直接初始化（服务器验证在 App.__init__ 中执行，失败会自动退出）
    root.after(300, _init_app)

    root.mainloop()


def _check_resolution_on_startup(root):
    """启动时检测分辨率，若与模板不匹配则提示用户重新截图"""
    current_res = config.get_resolution_key()
    stored_res = config.load_template_resolution()

    if not stored_res:
        # 首次运行，保存当前分辨率
        config.save_template_resolution(current_res)
        return

    if current_res == stored_res:
        return  # 分辨率一致，正常启动

    # 分辨率不匹配，弹窗提示
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
        # 打开模板截图向导
        from template_capture import TemplateCaptureWizard
        TemplateCaptureWizard(root, current_res)
    elif result is False:
        # 继续运行，更新存储的分辨率
        config.save_template_resolution(current_res)
    else:
        # 取消 → 退出程序
        sys.exit(0)


if __name__ == "__main__":
    main()
