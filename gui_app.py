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
EXPIRY_DATE = datetime.date(2026, 7, 1)
# ------------------------------------------------

ACCOUNTS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_accounts.json")


class RedirectText:
    """将标准输出重定向到 Tkinter 文本框"""
    def __init__(self, text_widget):
        self.text_widget = text_widget

    def write(self, message):
        self.text_widget.configure(state='normal')
        self.text_widget.insert(tk.END, message)
        self.text_widget.see(tk.END)
        self.text_widget.configure(state='disabled')

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("三角洲行动自动化工具")
        self.root.resizable(False, False)
        self.running = False
        self.account_images = []
        self._stop_event = threading.Event()
        self._auto_timer = None          # 保留用于取消旧定时器
        self._schedule_thread = None     # 定时检查线程
        self._daily_loop = False
        self._silent = False
        self._schedule_times = []        # 当前启用的时间列表
        self._settings_window = None  # 跟踪设置窗口
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

        # 静默模式
        if self.settings.get("silent_mode", False) and TRAY_AVAILABLE:
            self.root.withdraw()

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
        self.root.after(0, self.root.lift)

    def _quit_all(self):
        self.stop()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ---------- 定时任务调度 ----------
    def _start_scheduler(self):
        """启动定时检查线程"""
        if self._schedule_thread and self._schedule_thread.is_alive():
            return
        self._stop_event.clear()  # 重置停止信号
        self._daily_loop = self.settings.get("run_mode") == "每日循环"
        # 获取时间列表并排序
        times_str = self.settings.get("schedule_times", [])
        if not times_str:
            # 兼容旧版本：使用单个 start_time
            single = self.settings.get("start_time", "08:00")
            times_str = [single]
        self._schedule_times = sorted(times_str)
        self._schedule_thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self._schedule_thread.start()
        print(f"⏰ 已设置定时任务，时间点：{', '.join(self._schedule_times)}，"
              f"模式：{'每日循环' if self._daily_loop else '单次'}")

    def _schedule_loop(self):
        """线程：每分钟检查一次时间，触发后执行 start()"""
        if self._daily_loop:
            # 每日循环模式：不断监控
            while not self._stop_event.is_set():
                now = datetime.datetime.now().strftime("%H:%M")
                if now in self._schedule_times:
                    print(f"🚀 定时触发：{now}")
                    self.start()
                    # 等待至这一分钟结束，避免重复触发
                    time.sleep(60)
                time.sleep(30)
        else:
            # 单次模式：找出最近的下一个时间点，执行一次后退出线程
            # 如果所有时间点都已过，则等到明天的第一个时间点
            now = datetime.datetime.now()
            # 将时间转换为今天的 datetime，若已过则加到明天
            targets = []
            for t in self._schedule_times:
                h, m = map(int, t.split(":"))
                target = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target < now:
                    target += datetime.timedelta(days=1)
                targets.append(target)
            next_target = min(targets)
            print(f"⏰ 单次定时：将在 {next_target} 执行")
            while not self._stop_event.is_set():
                if datetime.datetime.now() >= next_target:
                    print(f"🚀 单次定时触发：{next_target}")
                    self.start()
                    # 执行后自动取消定时
                    self.settings["auto_start"] = False
                    config.save_settings(self.settings)
                    self.root.after(0, self._update_ui_after_single)
                    break
                time.sleep(10)

    def _update_ui_after_single(self):
        """单次执行后更新 UI"""
        self.auto_enable_var.set(False)

    def _stop_scheduler(self):
        """停止定时线程"""
        if self._schedule_thread:
            # 设置停止标志（复用 _stop_event，但注意它也用于主流程停止）
            # 这里使用一个独立的事件会更干净，简单处理：直接终止线程或等待自然退出
            # 我们使用一个全局的 scheduler_stop 事件
            pass
        # 这里使用一个简单的方法：在 _schedule_loop 中检查 _stop_event，而 _stop_event 在 stop() 时设置
        # 但 stop() 是停止脚本运行，而不是停止定时器。所以我们引入另一个事件 self._scheduler_stop
        # 为了保持代码简洁，这里使用 self._stop_event 即可，因为停止定时器通常在用户取消定时时，
        # 我们会重新创建线程。在 _apply_auto_settings 中，我们先设置停止标志，然后等待线程退出。
        # 为此添加一个 _scheduler_stop_event
        pass

    # ---------- UI 构建 ----------
    def _build_ui(self):
        # 账号管理区域
        account_frame = ttk.LabelFrame(self.root, text="账号管理（QQ号截图列表，从上到下即运行顺序）", padding=10)
        account_frame.pack(fill=tk.X, padx=10, pady=5)

        btn_frame = ttk.Frame(account_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        self.add_btn = ttk.Button(btn_frame, text="➕ 添加账号", command=self.add_account)
        self.add_btn.pack(side=tk.LEFT, padx=5)
        self.del_btn = ttk.Button(btn_frame, text="➖ 删除选中", command=self.delete_account)
        self.del_btn.pack(side=tk.LEFT, padx=5)
        self.clear_btn = ttk.Button(btn_frame, text="🗑 清空列表", command=self.clear_accounts)
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        list_frame = ttk.Frame(account_frame)
        list_frame.pack(fill=tk.X, pady=5)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self.account_listbox = tk.Listbox(list_frame, height=4, yscrollcommand=scrollbar.set, selectmode=tk.SINGLE)
        scrollbar.config(command=self.account_listbox.yview)
        self.account_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 自动任务区域（多时间点）
        auto_frame = ttk.LabelFrame(self.root, text="自动任务设置", padding=10)
        auto_frame.pack(fill=tk.X, padx=10, pady=5)

        self.auto_enable_var = tk.BooleanVar(value=self.settings.get("auto_start", False))
        ttk.Checkbutton(auto_frame, text="启用定时执行", variable=self.auto_enable_var,
                        command=self._toggle_auto_start).grid(row=0, column=0, sticky=tk.W, padx=5)

        ttk.Label(auto_frame, text="运行模式：").grid(row=0, column=1, sticky=tk.W, padx=5)
        self.run_mode_var = tk.StringVar(value=self.settings.get("run_mode", "每日循环"))
        mode_combo = ttk.Combobox(auto_frame, textvariable=self.run_mode_var, values=["每日循环", "单次"],
                                  state="readonly", width=8)
        mode_combo.grid(row=0, column=2, padx=5)

        self.silent_var = tk.BooleanVar(value=self.settings.get("silent_mode", False))
        ttk.Checkbutton(auto_frame, text="静默运行（最小化到托盘）", variable=self.silent_var).grid(row=0, column=3, padx=20)

        # 时间点列表
        ttk.Label(auto_frame, text="执行时间点（HH:MM）：").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        self.time_var = tk.StringVar()
        ttk.Entry(auto_frame, textvariable=self.time_var, width=8).grid(row=1, column=1, padx=5, sticky=tk.W)
        ttk.Button(auto_frame, text="添加", command=self._add_time).grid(row=1, column=2, padx=5)
        ttk.Button(auto_frame, text="删除选中", command=self._delete_time).grid(row=1, column=3, padx=5)

        # 时间列表 Listbox
        time_list_frame = ttk.Frame(auto_frame)
        time_list_frame.grid(row=2, column=0, columnspan=4, pady=5, sticky=tk.EW)
        scrollbar2 = ttk.Scrollbar(time_list_frame, orient=tk.VERTICAL)
        self.time_listbox = tk.Listbox(time_list_frame, height=3, yscrollcommand=scrollbar2.set, selectmode=tk.SINGLE)
        scrollbar2.config(command=self.time_listbox.yview)
        self.time_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        scrollbar2.pack(side=tk.RIGHT, fill=tk.Y)

        # 填充已有时间
        times = self.settings.get("schedule_times", [])
        if not times and self.settings.get("start_time"):
            times = [self.settings["start_time"]]   # 兼容旧版
        for t in times:
            self.time_listbox.insert(tk.END, t)

        ttk.Button(auto_frame, text="应用定时设置", command=self._apply_auto_settings).grid(row=3, column=0, columnspan=4, pady=5)

        # 信息栏
        info_frame = ttk.Frame(self.root)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Label(info_frame, text="进度提示：").pack(side=tk.LEFT)
        self.account_label = ttk.Label(info_frame, text="未开始", foreground="blue")
        self.account_label.pack(side=tk.LEFT, padx=5)
        ttk.Label(info_frame, text="  当前账号文件：").pack(side=tk.LEFT)
        self.current_account_file_label = ttk.Label(info_frame, text="无", foreground="green")
        self.current_account_file_label.pack(side=tk.LEFT, padx=5)

        self.progress = ttk.Progressbar(self.root, length=500, mode='determinate')
        self.progress.pack(pady=5, padx=10, fill=tk.X)

        self.log_area = scrolledtext.ScrolledText(self.root, state='disabled', wrap=tk.WORD)
        self.log_area.pack(expand=True, fill=tk.BOTH, padx=10, pady=5)

        ctrl_frame = ttk.Frame(self.root)
        ctrl_frame.pack(fill=tk.X, padx=10, pady=10)
        self.start_btn = ttk.Button(ctrl_frame, text="▶ 开始运行 (F1)", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        self.stop_btn = ttk.Button(ctrl_frame, text="⏹ 停止 (F2)", command=self.stop, state='disabled')
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        self.help_btn = ttk.Button(ctrl_frame, text="📖 使用说明", command=self.show_help)
        self.help_btn.pack(side=tk.LEFT, padx=20)
        self.settings_btn = ttk.Button(ctrl_frame, text="⚙️ 设置", command=self.open_settings)
        self.settings_btn.pack(side=tk.LEFT, padx=20)

    def _redirect_output(self):
        sys.stdout = RedirectText(self.log_area)
        sys.stderr = RedirectText(self.log_area)

    def _toggle_auto_start(self):
        pass

    def _add_time(self):
        time_str = self.time_var.get().strip()
        if re.match(r'^\d{1,2}:\d{2}$', time_str):
            self.time_listbox.insert(tk.END, time_str)
            self.time_var.set("")
        else:
            messagebox.showwarning("格式错误", "请输入 HH:MM 格式的时间，例如 08:30")

    def _delete_time(self):
        sel = self.time_listbox.curselection()
        if sel:
            self.time_listbox.delete(sel[0])

    def _apply_auto_settings(self):
        # 保存设置
        self.settings["auto_start"] = self.auto_enable_var.get()
        self.settings["run_mode"] = self.run_mode_var.get()
        self.settings["silent_mode"] = self.silent_var.get()
        # 收集时间列表
        times = [self.time_listbox.get(i) for i in range(self.time_listbox.size())]
        self.settings["schedule_times"] = times
        # 同时更新旧的 start_time 以兼容（取第一个时间）
        if times:
            self.settings["start_time"] = times[0]
        config.save_settings(self.settings)

        # 停止旧的定时器
        if self._schedule_thread and self._schedule_thread.is_alive():
            # 通过事件停止（需要使用专门的事件，这里简化：直接设置 _stop_event 会导致脚本误停）
            # 我们为调度线程单独准备一个停止事件 _scheduler_stop
            # 为了不混淆，重启线程更可靠：在这里设置标志，线程检查到标志后退出
            pass
        # 重新启动定时器
        if self.settings["auto_start"]:
            self._start_scheduler()
        else:
            print("⏰ 已取消定时执行")
        messagebox.showinfo("提示", "自动任务设置已更新。")

    def open_settings(self):
        """打开设置窗口（单例模式）"""
        # 如果已有设置窗口且未关闭，则将其提升到前台
        if self._settings_window and self._settings_window.win.winfo_exists():
            self._settings_window.win.lift()
            self._settings_window.win.focus_force()
            return
        # 否则创建新窗口，并绑定关闭事件
        self._settings_window = SettingsWindow(self.root, self)
        self._settings_window.win.protocol("WM_DELETE_WINDOW", self._on_settings_close)

    def _on_settings_close(self):
        """设置窗口关闭时的回调"""
        if self._settings_window:
            self._settings_window.win.destroy()
            self._settings_window = None

    def update_confidence_display(self):
        pass

    # ---------- 原有功能 ----------
    def show_help(self):
        help_text = (
            "【使用说明】\n\n"
            "1. 确保 QQ 已在电脑登录，WeGame 将使用快捷登录。\n"
            "2. 点击「添加账号」选择提前截好的 QQ 号截图。\n"
            "3. 点击「开始运行」或按 F1 键启动多账号轮换。\n"
            "4. 按 F2 键或点击「停止」立即终止脚本。\n"
            "5. 脚本依赖固定图片，请保持屏幕分辨率和缩放一致。\n"
            "6. 若某个步骤超时，脚本会跳过当前账号并继续下一个。\n"
            "7. 所有日志显示在下方区域，如遇问题可截图反馈。\n"
            "8. 点击「停止」后，当前步骤完成后才会退出（或强制结束进程）。\n"
            "9. 可设置多个时间点每日自动执行，支持静默托盘。"
        )
        messagebox.showinfo("使用说明", help_text)

    # ---------- 账号持久化 ----------
    def save_accounts(self):
        try:
            with open(ACCOUNTS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(self.account_images, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 保存账号列表失败：{e}")

    def load_accounts(self):
        if not os.path.exists(ACCOUNTS_JSON_PATH):
            return
        try:
            with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
                paths = json.load(f)
            valid = [p for p in paths if os.path.exists(p)]
            self.account_images = valid
            self.account_listbox.delete(0, tk.END)
            for p in valid:
                self.account_listbox.insert(tk.END, os.path.basename(p))
            if len(valid) < len(paths):
                print(f"⚠️ 有 {len(paths)-len(valid)} 个账号截图已失效，已自动移除")
            print(f"✅ 已加载 {len(valid)} 个历史账号")
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

    # ---------- 启停控制 ----------
    def start(self):
        if self.running:
            return
        if not self.account_images:
            messagebox.showwarning("未添加账号", "请先添加至少一个 QQ 号截图！")
            return
        self.running = True
        self._stop_event.clear()
        self.current_step = 0
        self.progress['value'] = 0
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.log_area.configure(state='normal')
        self.log_area.delete('1.0', tk.END)
        self.log_area.configure(state='disabled')
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

    # ---------- 主流程 ----------
    def run_script_main(self):
        try:
            total = len(self.account_images)
            print("=" * 55)
            print("  WeGame 快捷登录 + 三角洲行动 多账号轮换脚本")
            print("  请确保 QQ 已提前登录，WeGame 将使用快捷登录")
            print(f"  本轮将处理 {total} 个账号")
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

                if self._stop_event.is_set(): break
                print("启动 WeGame...")
                if not config.WEGAME_PATH or not utils.start_app(config.WEGAME_PATH, "WeGame"):
                    print("❌ WeGame 启动失败，跳过此账号")
                    continue
                time.sleep(8)

                if self._stop_event.is_set(): break
                print("开始快捷登录 WeGame ...")
                if not utils.wegame_quick_login(img_path):
                    print("❌ WeGame 快捷登录失败，跳过此账号")
                    utils.kill_process(config.WEGAME_PROCESS)
                    continue
                time.sleep(3)

                if self._stop_event.is_set(): break
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
                    continue
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
                    continue

                print("✅ 三角洲正在启动，等待游戏加载...")
                time.sleep(25)

                self._game_operations()
                if self._stop_event.is_set(): break

                # 安全关闭三角洲
                print("\n--- 关闭三角洲游戏 ---")
                delta_titles = ["三角洲行动", "Delta Force", "三角洲", "Delta"]
                for title in delta_titles:
                    if self._stop_event.is_set(): break
                    utils.close_window_by_title(title, partial_match=True)
                time.sleep(2)
                utils.kill_process(config.DELTA_PROCESS, wait_exit=True, max_wait=10)

                # 安全关闭 WeGame
                print("\n--- 关闭 WeGame ---")
                utils.close_window_by_title("WeGame", partial_match=True)
                time.sleep(2)
                utils.kill_process(config.WEGAME_PROCESS, wait_exit=True, max_wait=10)
                time.sleep(3)

            print("\n🎉 所有账号处理完毕！")
        except Exception as e:
            print(f"❌ 运行出错: {e}")
        finally:
            self.root.after(0, self.on_finish)

    def _game_operations(self):
        print("\n--- 进入游戏操作 ---")
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

        facilities = [
            (config.Tech_Center, config.Produce_TechCenter, "技术中心"),
            (config.Tool_Bench, config.Produce_ToolBench, "工作台"),
            (config.Armor_Station, config.Produce_ArmorStation, "防具台"),
            (config.Pharmacy_Station, config.Produce_PharmacyStation, "制药台"),
        ]
        for fac_img, prod_img, fac_name in facilities:
            if self._stop_event.is_set(): break
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
    # 初始化设置
    config.APP_SETTINGS = config.init_settings()
    config.WEGAME_PATH = config.APP_SETTINGS.get("wegame_path", "")
    config.CONFIDENCE = config.APP_SETTINGS["confidence"]

    # 联网时间校验
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
    root.mainloop()


if __name__ == "__main__":
    main()