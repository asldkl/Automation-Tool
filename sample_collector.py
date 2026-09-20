# -*- coding: utf-8 -*-
"""样本采集小工具 —— 点击指定位置 → 等待若干秒 → 截取指定区域 → 循环 N 次

独立脚本：只依赖标准库 + Pillow（截图）；鼠标点击走 Win32 API，不需要 pyautogui。
典型用途：批量采集验证码样本，用来扩充测试集。

用法：
    python sample_collector.py              # 打开图形界面
    python sample_collector.py --selftest   # 只做「DPI / 坐标 / 截图链路」自检后退出

坐标约定：程序启动时先开启 DPI 感知，因此界面坐标、框选得到的坐标、
          ImageGrab 截图的物理像素三者一致（本机 2880x1800 @200% 也成立）。
"""
import argparse
import ctypes
import datetime
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "样本采集工具"
CN_FONT = "Microsoft YaHei UI"
HINT_FG = "#7f8c8d"
ACCENT = "#2d7ff9"
DEFAULT_PREFIX = "sample"
IMG_EXT = ".png"
UI_POLL_MS = 40          # 主线程轮询后台命令队列的间隔


# --------------------------------------------------------------------------- #
# Win32 基础
# --------------------------------------------------------------------------- #
def enable_dpi_awareness() -> bool:
    """必须在创建 tk.Tk() 之前调用，否则界面坐标与截图物理像素会差一个缩放比。"""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
        return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
        return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def virtual_screen_rect():
    """虚拟桌面范围（多屏时含负坐标），返回 (x, y, w, h)。"""
    u = ctypes.windll.user32
    try:
        x, y = u.GetSystemMetrics(76), u.GetSystemMetrics(77)    # SM_X/YVIRTUALSCREEN
        w, h = u.GetSystemMetrics(78), u.GetSystemMetrics(79)
        if w > 0 and h > 0:
            return x, y, w, h
    except Exception:
        pass
    return 0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1)


def click_screen(x: int, y: int) -> None:
    """把鼠标移到 (x, y) 并单击左键。"""
    u = ctypes.windll.user32
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    u.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.05)
    u.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP


def app_dir() -> str:
    """程序所在目录。

    打包成 onefile exe 后 __file__ 指向临时解包目录（退出即删），
    必须改用 exe 自身所在目录，否则默认输出目录会写到一个会被删掉的地方。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def grab_region(x: int, y: int, w: int, h: int):
    """截取屏幕区域，返回 PIL.Image（RGB）。"""
    from PIL import ImageGrab
    x, y, w, h = int(x), int(y), int(w), int(h)
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return img.convert("RGB") if img.mode != "RGB" else img


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class SampleCollector:
    def __init__(self, root, on_close=None, styles=None):
        """root：Tk 根窗口；嵌入主工具时传 Toplevel（见 open_in）。

        on_close：可选无参回调。给了就由宿主负责销毁窗口（主工具用它走导航栈恢复父窗口）；
                  不给则自己 destroy（独立运行时的行为）。
        styles：可选 ttk 样式名映射 {"card":..., "button":..., "accent":...}，
                用来跟宿主界面统一；不传就用 ttk 默认样式。
        """
        self.root = root
        self.on_close = on_close
        self.styles = dict(styles) if styles else {}
        self._saved_grab = None         # 隐藏窗口前暂存的模态 grab，恢复窗口时归还
        self._drain_id = None           # 轮询 UI 队列的 after id，销毁时要撤销
        self.stop_event = threading.Event()
        self.worker = None
        self._q = queue.Queue()
        self._preview_ref = None        # 保持 PhotoImage 引用，否则预览会空白

        # ---- 变量 ----
        self.region = [tk.StringVar(value="0"), tk.StringVar(value="0"),
                       tk.StringVar(value="600"), tk.StringVar(value="400")]
        self.out_dir = tk.StringVar(value=os.path.join(app_dir(), "captured_samples"))
        self.prefix = tk.StringVar(value=DEFAULT_PREFIX)
        self.click_enabled = tk.BooleanVar(value=True)
        self.click_xy = [tk.StringVar(value="0"), tk.StringVar(value="0")]
        self.wait_sec = tk.StringVar(value="1.0")
        self.interval_sec = tk.StringVar(value="0.3")
        self.start_delay = tk.StringVar(value="3")
        self.count = tk.StringVar(value="10")
        self.minimize = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="就绪。先「框选区域」，需要点刷新就「屏幕取点」，然后开始采集。")
        self.counter = tk.StringVar(value="0 / 0")

        self._build_ui()
        # 最小尺寸由控件自然尺寸反推（已含字体放大后的真实需要，天然 DPI 无关）
        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 窗口可能被宿主直接 destroy（导航栈），那时不会有 WM_DELETE_WINDOW 回调
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        self._drain_id = self.root.after(UI_POLL_MS, self._drain)

    def _kw(self, kind):
        """按宿主传入的样式名生成 ttk 关键字参数（没给就返回空 dict，用默认样式）。"""
        s = self.styles.get(kind)
        return {"style": s} if s else {}

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        self.root.title(APP_TITLE)

        wrap = ttk.Frame(self.root, padding=12)
        wrap.pack(fill=tk.BOTH, expand=True)

        # ---------- 截图区域 ----------
        box1 = ttk.LabelFrame(wrap, text="  截图区域（框住要保存的画面）  ", padding=10,
                             **self._kw("card"))
        box1.pack(fill=tk.X)
        row = ttk.Frame(box1)
        row.pack(fill=tk.X)
        for label, var, tail in (("X", self.region[0], 12), ("Y", self.region[1], 12),
                                 ("宽", self.region[2], 12), ("高", self.region[3], 12)):
            ttk.Label(row, text=label).pack(side=tk.LEFT)
            ttk.Entry(row, textvariable=var, width=7).pack(side=tk.LEFT, padx=(4, tail))
        ttk.Button(row, text="框选区域", width=10, command=self._pick_region).pack(side=tk.LEFT)
        ttk.Button(row, text="试拍一张", width=10, command=self._test_capture).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(box1, text="点「框选区域」后屏幕变暗，按住左键拖出矩形即可；Esc 取消。",
                  font=(CN_FONT, 8), foreground=HINT_FG).pack(anchor="w", pady=(6, 0))

        # ---------- 点击设置 ----------
        box2 = ttk.LabelFrame(wrap, text="  点击设置（每次截图前先点一下，比如验证码的「刷新」）  ",
                             padding=10, **self._kw("card"))
        box2.pack(fill=tk.X, pady=(10, 0))
        row2 = ttk.Frame(box2)
        row2.pack(fill=tk.X)
        ttk.Checkbutton(row2, text="采集前先点击", variable=self.click_enabled).pack(side=tk.LEFT)
        ttk.Label(row2, text="X").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Entry(row2, textvariable=self.click_xy[0], width=7).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(row2, text="Y").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.click_xy[1], width=7).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Button(row2, text="屏幕取点", width=10, command=self._pick_click_point).pack(side=tk.LEFT)

        row2b = ttk.Frame(box2)
        row2b.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(row2b, text="点击后等待(秒)").pack(side=tk.LEFT)
        ttk.Entry(row2b, textvariable=self.wait_sec, width=6).pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(row2b, text="两次采集间隔(秒)").pack(side=tk.LEFT)
        ttk.Entry(row2b, textvariable=self.interval_sec, width=6).pack(side=tk.LEFT, padx=(4, 14))
        ttk.Label(row2b, text="开始前倒计时(秒)").pack(side=tk.LEFT)
        ttk.Entry(row2b, textvariable=self.start_delay, width=6).pack(side=tk.LEFT, padx=(4, 0))

        # ---------- 保存与次数 ----------
        box3 = ttk.LabelFrame(wrap, text="  保存与次数  ", padding=10, **self._kw("card"))
        box3.pack(fill=tk.X, pady=(10, 0))
        row3 = ttk.Frame(box3)
        row3.pack(fill=tk.X)
        ttk.Label(row3, text="输出目录").pack(side=tk.LEFT)
        ttk.Entry(row3, textvariable=self.out_dir).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 6))
        ttk.Button(row3, text="浏览", width=8, command=self._browse_dir).pack(side=tk.LEFT)
        ttk.Button(row3, text="打开", width=8, command=self._open_dir).pack(side=tk.LEFT, padx=(6, 0))

        row4 = ttk.Frame(box3)
        row4.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(row4, text="文件名前缀").pack(side=tk.LEFT)
        ttk.Entry(row4, textvariable=self.prefix, width=16).pack(side=tk.LEFT, padx=(6, 18))
        ttk.Label(row4, text="采集次数").pack(side=tk.LEFT)
        ttk.Entry(row4, textvariable=self.count, width=8).pack(side=tk.LEFT, padx=(6, 18))
        ttk.Checkbutton(row4, text="采集时最小化本窗口", variable=self.minimize).pack(side=tk.LEFT)
        ttk.Label(box3, text="文件名格式：前缀_序号_时间戳.png（例 sample_001_20260920-231502.png）",
                  font=(CN_FONT, 8), foreground=HINT_FG).pack(anchor="w", pady=(6, 0))

        # ---------- 执行 ----------
        box4 = ttk.Frame(wrap)
        box4.pack(fill=tk.X, pady=(12, 0))
        _accent = self.styles.get("accent")
        if _accent:
            # 宿主给了强调按钮样式 → 用 ttk，跟主工具其它按钮长得一样
            self.btn_start = ttk.Button(box4, text="开始采集", width=14,
                                        style=_accent, command=self._start)
        else:
            self.btn_start = tk.Button(box4, text="开始采集", width=14, command=self._start,
                                       bg=ACCENT, fg="white", activebackground="#1f66cc",
                                       activeforeground="white", relief="flat",
                                       font=(CN_FONT, 10, "bold"))
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stop = ttk.Button(box4, text="停止", width=10, command=self._stop,
                                   state=tk.DISABLED, **self._kw("button"))
        self.btn_stop.pack(side=tk.LEFT, padx=(8, 18))
        ttk.Label(box4, textvariable=self.counter, font=(CN_FONT, 11, "bold")).pack(side=tk.LEFT)

        # ---------- 状态 / 预览 / 日志 ----------
        ttk.Label(wrap, textvariable=self.status, font=(CN_FONT, 9), foreground="#333333",
                  wraplength=1140, justify="left").pack(anchor="w", pady=(10, 0))

        body = ttk.Frame(wrap)
        body.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        prev_box = ttk.LabelFrame(body, text="  预览  ", padding=6, **self._kw("card"))
        prev_box.pack(side=tk.LEFT, fill=tk.Y)
        self.preview = tk.Label(prev_box, text="（试拍一张后在此预览）", width=30, height=9,
                                bg="#f5f6f8", fg=HINT_FG, font=(CN_FONT, 9))
        self.preview.pack()

        log_box = ttk.LabelFrame(body, text="  日志  ", padding=6, **self._kw("card"))
        log_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        self.log = tk.Text(log_box, height=9, wrap="none", font=("Consolas", 9),
                           relief="flat", bg="#fbfbfb")
        self.log.pack(fill=tk.BOTH, expand=True)
        self.log.configure(state=tk.DISABLED)

    # ------------------------------------------------------- 线程安全 UI 通道 --
    def _ui(self, fn, *a):
        """工作线程调用，把操作排进队列，由主线程执行。"""
        self._q.put((fn, a))

    def _drain(self):
        while True:
            try:
                fn, a = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*a)
            except Exception as e:      # noqa: BLE001
                print(f"UI 回调异常: {e}", file=sys.stderr)
        self._drain_id = self.root.after(UI_POLL_MS, self._drain)

    def _on_destroy(self, event=None):
        """窗口被销毁时收尾。

        ⚠️ 不撤销 after 轮询的话，销毁后回调仍会触发，Tcl 会报
        「invalid command name "..._drain"」（窗口化 exe 里看不到，但会写进错误流）。
        ⚠️ 另外要停掉采集线程：窗口都没了还在点鼠标是最坏的情况。
        """
        if event is not None and event.widget is not self.root:
            return                      # <Destroy> 会因子控件销毁而触发，只认窗口本身
        self.stop_event.set()
        if self._drain_id is not None:
            try:
                self.root.after_cancel(self._drain_id)
            except Exception:
                pass
            self._drain_id = None

    # ------------------------------------------------------------- 小工具 --
    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{ts}] {msg}\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _say(self, msg: str):
        self.status.set(msg)

    def _read_int(self, var, name, minimum=None):
        try:
            v = int(float(str(var.get()).strip()))
        except (TypeError, ValueError):
            raise ValueError(f"「{name}」必须是数字")
        if minimum is not None and v < minimum:
            raise ValueError(f"「{name}」不能小于 {minimum}")
        return v

    def _read_float(self, var, name, minimum=None):
        try:
            v = float(str(var.get()).strip())
        except (TypeError, ValueError):
            raise ValueError(f"「{name}」必须是数字")
        if minimum is not None and v < minimum:
            raise ValueError(f"「{name}」不能小于 {minimum}")
        return v

    def _region(self):
        return (self._read_int(self.region[0], "区域 X"),
                self._read_int(self.region[1], "区域 Y"),
                self._read_int(self.region[2], "区域宽度", 1),
                self._read_int(self.region[3], "区域高度", 1))

    def _ensure_dir(self):
        d = self.out_dir.get().strip()
        if not d:
            raise ValueError("请先设置输出目录")
        os.makedirs(d, exist_ok=True)
        return d

    # --------------------------------------------------- 全屏遮罩：框选 / 取点 --
    def _overlay(self, mode: str):
        """全屏半透明遮罩。mode='region' 拖拽框选；mode='point' 单击取点。

        返回 [x, y, w, h]（region）或 [x, y]（point）；Esc 或未操作返回 None。
        """
        self._hide_window()
        self.root.update_idletasks()
        time.sleep(0.25)            # 等 withdraw 真正生效，否则遮罩会被挡

        result = {"v": None}
        ov = tk.Toplevel(self.root)
        try:
            ov.attributes("-fullscreen", True)
            ov.attributes("-alpha", 0.3)
            ov.attributes("-topmost", True)
        except Exception:
            pass
        ov.configure(bg="black")
        ov.config(cursor="crosshair")

        cv = tk.Canvas(ov, highlightthickness=0, bg="black", cursor="crosshair")
        cv.pack(fill=tk.BOTH, expand=True)
        tip = ("拖动鼠标框选要截取的区域，Esc 取消" if mode == "region"
               else "单击要点击的位置，Esc 取消")
        tk.Label(ov, text=tip, font=(CN_FONT, 14, "bold"), fg="white", bg="black"
                 ).place(relx=0.5, rely=0.05, anchor="center")
        live = tk.Label(ov, text="", font=(CN_FONT, 11), fg="#ffd75e", bg="black")
        live.place(relx=0.5, rely=0.10, anchor="center")

        st = {"rx": 0, "ry": 0, "id": None}

        def to_screen(e):
            # 用画布相对屏幕的偏移换算；遮罩不在 (0,0) 时也不会整体偏移
            return int(cv.winfo_rootx()) + int(e.x), int(cv.winfo_rooty()) + int(e.y)

        def on_press(e):
            st["rx"], st["ry"] = e.x, e.y
            if st["id"]:
                cv.delete(st["id"])
            st["id"] = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff3b30", width=3)

        def on_drag(e):
            if st["id"]:
                cv.coords(st["id"], st["rx"], st["ry"], e.x, e.y)
            sx, sy = to_screen(e)
            live.config(text=f"当前 {sx},{sy}")

        def on_release(e):
            x1, y1 = min(st["rx"], e.x), min(st["ry"], e.y)
            x2, y2 = max(st["rx"], e.x), max(st["ry"], e.y)
            if x2 - x1 > 10 and y2 - y1 > 10:
                ox, oy = int(cv.winfo_rootx()), int(cv.winfo_rooty())
                result["v"] = [ox + x1, oy + y1, x2 - x1, y2 - y1]
            ov.destroy()

        def on_click(e):
            sx, sy = to_screen(e)
            result["v"] = [sx, sy]
            ov.destroy()

        if mode == "region":
            cv.bind("<ButtonPress-1>", on_press)
            cv.bind("<B1-Motion>", on_drag)
            cv.bind("<ButtonRelease-1>", on_release)
        else:
            cv.bind("<Motion>", on_drag)
            cv.bind("<Button-1>", on_click)
        ov.bind("<Escape>", lambda _e: ov.destroy())

        try:
            ov.grab_set()
            ov.lift()
            ov.focus_force()
        except Exception:
            pass
        try:
            ov.wait_window()        # 阻塞到遮罩销毁（mainloop 仍在跑）
        finally:
            try:
                ov.grab_release()
            except Exception:
                pass
            self._restore_window()
        return result["v"]

    def _pick_region(self):
        v = self._overlay("region")
        if not v:
            self._say("已取消框选。")
            return
        for var, val in zip(self.region, v):
            var.set(str(val))
        self._say(f"截图区域已设为 {v[0]},{v[1]}  {v[2]}x{v[3]}")
        self._log(f"截图区域 = {v}")

    def _pick_click_point(self):
        v = self._overlay("point")
        if not v:
            self._say("已取消取点。")
            return
        self.click_xy[0].set(str(v[0]))
        self.click_xy[1].set(str(v[1]))
        self.click_enabled.set(True)
        self._say(f"点击坐标已设为 {v[0]},{v[1]}")
        self._log(f"点击坐标 = ({v[0]}, {v[1]})")

    # ------------------------------------------------------------ 目录 / 预览 --
    def _browse_dir(self):
        d = filedialog.askdirectory(title="选择样本保存目录", initialdir=self.out_dir.get() or None)
        if d:
            self.out_dir.set(d)

    def _open_dir(self):
        d = self.out_dir.get().strip()
        if not d:
            return
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)          # noqa: S606  (Windows 专用)
        except Exception as e:
            messagebox.showerror(APP_TITLE, f"打开目录失败：{e}")

    def _save(self, img, out_dir, prefix):
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = os.path.join(out_dir, f"{prefix}_{ts}{IMG_EXT}")
        i = 1
        while os.path.exists(path):          # 同秒重复时自动加序号，避免覆盖
            path = os.path.join(out_dir, f"{prefix}_{ts}_{i}{IMG_EXT}")
            i += 1
        img.save(path)
        return path

    def _show_preview(self, path):
        try:
            from PIL import Image, ImageTk
            im = Image.open(path)
            im.thumbnail((280, 190))
            self._preview_ref = ImageTk.PhotoImage(im)
            self.preview.config(image=self._preview_ref, text="", width=0, height=0)
        except Exception as e:      # noqa: BLE001
            self._log(f"预览失败：{e}")

    def _restore_window(self):
        try:
            self.root.deiconify()
            self.root.lift()
        except Exception:
            pass
        g = self._saved_grab
        if g is not None:
            self._saved_grab = None
            try:
                g.grab_set()
            except Exception:
                pass

    def _hide_window(self):
        """截图/取点期间把本窗口收起来，别挡住采集区域。

        ⚠️ 窗口持着模态 grab 时直接 withdraw，会让整个应用的鼠标键盘都落到一个
        不可见的窗口上（表现为「假死」）→ 先把 grab 借出来，恢复窗口时再还回去。
        独立运行没有 grab，这两步都是空操作。
        """
        try:
            g = self.root.grab_current()
        except Exception:
            g = None
        if g is not None:
            self._saved_grab = g
            try:
                g.grab_release()
            except Exception:
                pass
        try:
            self.root.withdraw()
        except Exception:
            pass

    def _test_capture(self):
        """试拍一张：只截图不点击，用于确认区域选对了。"""
        try:
            x, y, w, h = self._region()
            out_dir = self._ensure_dir()
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return

        if self.minimize.get():
            self._hide_window()
            time.sleep(0.35)
        try:
            img = grab_region(x, y, w, h)
            path = self._save(img, out_dir, "preview")
        except Exception as e:      # noqa: BLE001
            self._restore_window()
            messagebox.showerror(APP_TITLE, f"截图失败：{e}")
            return
        self._restore_window()
        self._show_preview(path)
        self._say(f"试拍完成：{os.path.basename(path)}  ({img.width}x{img.height})")
        self._log(f"试拍 → {path}")

    # ----------------------------------------------------------- 采集主流程 --
    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            x, y, w, h = self._region()
            total = self._read_int(self.count, "采集次数", 1)
            wait_sec = self._read_float(self.wait_sec, "点击后等待", 0)
            interval = self._read_float(self.interval_sec, "两次采集间隔", 0)
            delay = self._read_float(self.start_delay, "开始前倒计时", 0)
            click_on = bool(self.click_enabled.get())
            cx = cy = 0
            if click_on:
                cx = self._read_int(self.click_xy[0], "点击 X")
                cy = self._read_int(self.click_xy[1], "点击 Y")
            out_dir = self._ensure_dir()
            prefix = self.prefix.get().strip() or DEFAULT_PREFIX
            minimize = bool(self.minimize.get())
        except ValueError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return

        self.stop_event.clear()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.counter.set(f"0 / {total}")
        self._log(f"开始采集：区域 {x},{y} {w}x{h}，次数 {total}，"
                  f"{'点击 %d,%d 后 ' % (cx, cy) if click_on else ''}等待 {wait_sec:g}s")

        self.worker = threading.Thread(target=self._loop, daemon=True, args=(
            (x, y, w, h), total, wait_sec, interval, delay, click_on, cx, cy,
            out_dir, prefix, minimize))
        self.worker.start()

    def _stop(self):
        self.stop_event.set()
        self._say("正在停止…")
        self.btn_stop.config(state=tk.DISABLED)

    def _wait(self, secs, tick=None):
        """可被「停止」打断的等待；tick(剩余整秒) 只在秒数变化时回调一次。"""
        end = time.time() + max(0.0, secs)
        last = None
        while True:
            if self.stop_event.is_set():
                return False
            left = end - time.time()
            if left <= 0:
                return True
            if tick:
                cur = int(left) + 1
                if cur != last:
                    last = cur
                    tick(cur)
            time.sleep(min(0.1, max(0.0, left)))

    def _loop(self, region, total, wait_sec, interval, delay, click_on, cx, cy,
              out_dir, prefix, minimize):
        x, y, w, h = region
        done = 0
        try:
            if minimize:
                self._ui(self._hide_window)
                time.sleep(0.35)

            if delay > 0:
                self._wait(delay, tick=lambda n: self._ui(
                    self._say, f"{n} 秒后开始，请切换到目标窗口…"))
                if self.stop_event.is_set():
                    return

            for i in range(1, total + 1):
                if self.stop_event.is_set():
                    break
                self._ui(self._say, f"第 {i}/{total} 次："
                                    + ("点击 → " if click_on else "")
                                    + f"等待 {wait_sec:g}s → 截图")
                if click_on:
                    click_screen(cx, cy)
                if not self._wait(wait_sec, tick=lambda n, i=i: self._ui(
                        self._say, f"第 {i}/{total} 次：等待截图… {n}s")):
                    break

                img = grab_region(x, y, w, h)
                path = self._save(img, out_dir, f"{prefix}_{i:03d}")
                done = i
                self._ui(self.counter.set, f"{i} / {total}")
                self._ui(self._log, f"[{i}/{total}] {os.path.basename(path)}  "
                                    f"({img.width}x{img.height})")
                self._ui(self._show_preview, path)

                if i < total and not self._wait(interval):
                    break

            tail = "已停止" if self.stop_event.is_set() else "完成"
            self._ui(self._say, f"{tail}，共保存 {done}/{total} 张 → {out_dir}")
            self._ui(self._log, f"—— {tail}：{done}/{total} ——")
        except Exception as e:      # noqa: BLE001
            self._ui(self._log, f"出错：{e}")
            self._ui(self._say, f"出错：{e}")
            self._ui(messagebox.showerror, APP_TITLE, f"采集出错：{e}")
        finally:
            self._ui(self._restore_window)
            self._ui(self._finish_buttons)

    def _finish_buttons(self):
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)

    # --------------------------------------------------------------- 关闭 --
    def confirm_close(self) -> bool:
        """关窗前确认（正在采集时弹确认框）。返回 False = 用户放弃关闭。"""
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_TITLE, "正在采集，确定要退出吗？"):
                return False
            self.stop_event.set()
        return True

    def _on_close(self):
        if not self.confirm_close():
            return
        if callable(self.on_close):
            # 宿主接管关闭（例如走导航栈恢复父窗口），由宿主负责销毁本窗口
            try:
                self.on_close()
            except Exception as e:      # noqa: BLE001
                print(f"on_close 回调异常：{e}", file=sys.stderr)
                try:
                    self.root.destroy()
                except Exception:
                    pass
            return
        self.root.destroy()


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
def selftest(dpi_ok: bool) -> int:
    print(f"DPI 感知：{'成功' if dpi_ok else '失败（坐标可能不准）'}", flush=True)
    try:
        import PIL
        print(f"Pillow：{PIL.__version__}", flush=True)
    except Exception as e:      # noqa: BLE001
        print(f"Pillow 导入失败：{e}", flush=True)
        return 1

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    print(f"Tk 屏幕尺寸：{root.winfo_screenwidth()} x {root.winfo_screenheight()}", flush=True)
    vx, vy, vw, vh = virtual_screen_rect()
    print(f"虚拟桌面：原点 ({vx},{vy})  尺寸 {vw} x {vh}", flush=True)

    tmp = os.path.join(os.environ.get("TEMP", "."), "_sample_collector_selftest.png")
    try:
        img = grab_region(0, 0, 400, 300)
        img.save(tmp)
    except Exception as e:      # noqa: BLE001
        print(f"截图失败：{e}", flush=True)
        root.destroy()
        return 1
    root.destroy()

    print(f"截取 (0,0,400,300) 实际得到：{img.width} x {img.height}", flush=True)
    print(f"测试图：{tmp}", flush=True)
    ok = (img.width, img.height) == (400, 300)
    print(f"尺寸一致性：{'OK' if ok else '不一致！'}", flush=True)
    return 0 if ok else 1


def open_in(parent, on_close=None, styles=None):
    """把采集器作为一个子窗口嵌进已有的 Tk 应用里（主工具「实验功能」按钮用）。

    与 main() 的区别：
      - 不新建 Tk 根、不进入 mainloop（由宿主 mainloop 驱动）；
      - 不改 ttk 主题（宿主已经设好了，改主题会把主工具界面一起带歪）。
    ⚠️ DPI 感知必须由宿主在**创建 Tk 之前**设好（主工具 main.py 启动时已经设了）。

    返回 SampleCollector 实例，窗口取 sc.root。
    """
    win = tk.Toplevel(parent)
    win.title(APP_TITLE)
    win.resizable(True, True)
    return SampleCollector(win, on_close=on_close, styles=styles)


def main():
    ap = argparse.ArgumentParser(description="样本采集小工具")
    ap.add_argument("--selftest", action="store_true", help="只做链路自检后退出")
    args = ap.parse_args()

    dpi_ok = enable_dpi_awareness()     # 必须在 tk.Tk() 之前
    if args.selftest:
        sys.exit(selftest(dpi_ok))

    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except Exception:
        pass
    SampleCollector(root)
    root.mainloop()


if __name__ == "__main__":
    main()
