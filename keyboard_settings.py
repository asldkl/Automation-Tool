# -*- coding: utf-8 -*-
"""键盘输入设置窗口

从「设置 → 实验功能 → 驱动键盘测试 → 键盘设置」打开。

为什么单独一个窗口
------------------
键盘后端是一组相关配置（后端优先级 + STM32 端口/节奏/超时），塞进设置主窗口会很挤；
而且这里要**自带测试** —— 打字测试需要一个不被打扰、还能读回内容的窗口，
所以直接在本窗口放一个输入框，让硬件把字打进来做回读校验。

测试项（对应「测试 STM32 是否连接成功和正常使用」）
--------------------------------------------------
· 检测连接  —— 只发 PING / INFO，**不按键**；报固件版本 / STATE / USB 就绪
· 打字测试  —— 用 **STM32 后端**（绕过优先级链）把测试串打进本窗口的输入框，再读回比对。
               故意绕过链：否则 Interception 可能被兜住，测不出 STM32 到底行不行。
· 紧急停止 / 恢复 —— 对应板上长按 PB1/PB11 0.8 秒触发的那个状态
"""
import threading
import tkinter as tk
from tkinter import ttk

import config
import driver_keyboard
import stm32_keyboard

TEST_TEXT = "Test123!@#aAzZ-_,.[]"


def _ime_detach(win):
    """临时摘掉窗口的**输入法关联**，返回原句柄以便恢复（失败返回 None）。

    为什么必须做：中文输入法会把硬件键盘打出的字符吃掉/转全角
    （实测 `Test123!@#aAzZ` 被输入法变成 `Test23！@#` —— 字母进了拼音候选不上屏、
    标点被转成全角）。那是输入法层的行为，不是硬件键盘的问题；
    不摘掉它，测试会把「输入法干扰」误报成「STM32 不能用」。
    """
    try:
        import ctypes
        imm32 = ctypes.WinDLL("imm32")
        imm32.ImmAssociateContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        imm32.ImmAssociateContext.restype = ctypes.c_void_p
        user32 = ctypes.WinDLL("user32")
        user32.GetParent.argtypes = [ctypes.c_void_p]
        user32.GetParent.restype = ctypes.c_void_p

        hwnd = ctypes.c_void_p(win.winfo_id())
        old = []
        for h in (hwnd, ctypes.c_void_p(user32.GetParent(hwnd))):
            if h and h.value:
                old.append((h, imm32.ImmAssociateContext(h, None)))
        return old or None
    except Exception:
        return None


def _ime_restore(old):
    """把输入法关联还回去（只影响本窗口）"""
    if not old:
        return
    try:
        import ctypes
        imm32 = ctypes.WinDLL("imm32")
        imm32.ImmAssociateContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        imm32.ImmAssociateContext.restype = ctypes.c_void_p
        for h, ctx in old:
            if ctx:
                imm32.ImmAssociateContext(h, ctx)
    except Exception:
        pass

_BACKEND_OPTIONS = [
    ("auto", "自动（推荐）", "按 STM32 硬件键盘 → Interception 驱动 → SendInput 依次挑第一个可用的。\n"
                        "STM32 排在前面：它同样是硬件级输入，但不会把系统键盘栈搞挂。"),
    ("stm32", "只用 STM32 硬件键盘", "强制走外部硬件键盘；没插板子就输入失败（不回退到别的后端）。"),
    ("interception", "只用 Interception 驱动", "强制走内核驱动级输入；驱动不可用时输入失败。"),
    ("sendinput", "只用 SendInput", "纯软件模拟，不需要任何驱动/硬件，但按键带注入标记，部分游戏不认。"),
]


class KeyboardSettingsWindow:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self._busy = False
        self._ime_old = None       # 打字测试期间临时摘掉的输入法句柄

        self.win = tk.Toplevel(parent)
        self.win.title("键盘输入设置")
        self.win.transient(parent)
        try:
            geom = str((app.settings or {}).get("keyboard_settings_geometry", "") or "")
        except Exception:
            geom = ""
        self.win.geometry(geom or "620x660")
        self.win.minsize(560, 560)
        try:
            self.win.iconbitmap(config.resource_path("picture/icon/icon.ico"))
        except Exception:
            pass

        self._backend_var = tk.StringVar(value=str(
            self.app.settings.get("keyboard_backend", "auto") or "auto"))
        self._port_var = tk.StringVar(value=str(
            self.app.settings.get("stm32_port", "auto") or "auto"))
        self._interval_var = tk.StringVar(value=str(
            self.app.settings.get("stm32_interval_ms", 25) or 25))
        self._timeout_var = tk.StringVar(value=str(
            self.app.settings.get("stm32_timeout", 3.0) or 3.0))

        self._build()
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_status()
        self.win.lift()
        self.win.focus_force()

    # ------------------------------------------------------------------ UI --

    def _build(self):
        outer = ttk.Frame(self.win, style='Settings.TFrame', padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="键盘输入后端", style='Header.TLabel').pack(anchor=tk.W)
        ttk.Label(outer,
                  text="登录时输入账号密码走哪个后端。默认「自动」即可 —— 插上 STM32 就自动用它。",
                  style='SettingsSmall.TLabel').pack(anchor=tk.W, pady=(2, 10))

        # ----- 1. 后端优先级 -----
        card1 = ttk.LabelFrame(outer, text="  后端优先级  ", style='SettingsCard.TLabelframe', padding=10)
        card1.pack(fill=tk.X, pady=(0, 8))
        for value, label, hint in _BACKEND_OPTIONS:
            row = ttk.Frame(card1, style='SettingsInner.TFrame')
            row.pack(fill=tk.X, pady=(0, 6))
            ttk.Radiobutton(row, text=label, value=value, variable=self._backend_var,
                            command=self._refresh_status).pack(anchor=tk.W)
            ttk.Label(row, text=hint, style='SettingsSmall.TLabel',
                      justify=tk.LEFT).pack(anchor=tk.W, padx=(22, 0))

        # ----- 2. STM32 参数 -----
        card2 = ttk.LabelFrame(outer, text="  STM32 硬件键盘  ", style='SettingsCard.TLabelframe', padding=10)
        card2.pack(fill=tk.X, pady=(0, 8))

        r1 = ttk.Frame(card2, style='SettingsInner.TFrame')
        r1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r1, text="串口", style='SettingsSmall.TLabel').pack(side=tk.LEFT)
        self._port_combo = ttk.Combobox(r1, textvariable=self._port_var, width=26)
        self._port_combo.pack(side=tk.LEFT, padx=(8, 6))
        ttk.Button(r1, text="刷新端口", command=self._refresh_ports).pack(side=tk.LEFT)

        r2 = ttk.Frame(card2, style='SettingsInner.TFrame')
        r2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r2, text="打字间隔(ms)", style='SettingsSmall.TLabel').pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=5, to=500, increment=5, width=6,
                    textvariable=self._interval_var).pack(side=tk.LEFT, padx=(8, 16))
        ttk.Label(r2, text="回执超时(秒)", style='SettingsSmall.TLabel').pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=0.5, to=30, increment=0.5, width=6,
                    textvariable=self._timeout_var).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(card2, text="间隔由固件侧控制（5~500ms），越大越像人手动打字；"
                              "端口填 auto 即按 VID:PID 0483:57A0 自动查找。",
                  style='SettingsSmall.TLabel', justify=tk.LEFT).pack(anchor=tk.W, padx=2, pady=(2, 0))
        self._refresh_ports()

        # ----- 3. 测试 -----
        card3 = ttk.LabelFrame(outer, text="  测试  ", style='SettingsCard.TLabelframe', padding=10)
        card3.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        b = ttk.Frame(card3, style='SettingsInner.TFrame')
        b.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(b, text="检测连接", style='TButton', width=10,
                   command=self._test_connect).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(b, text="打字测试", style='Accent.TButton', width=10,
                   command=self._test_type).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(b, text="紧急停止", style='Danger.TButton', width=10,
                   command=self._emergency_stop).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(b, text="恢复", style='TButton', width=8,
                   command=self._resume).pack(side=tk.LEFT)

        ttk.Label(card3, text="打字测试会以 STM32 后端把下面这串打进输入框（不走优先级链，确保测的是 STM32 本人）。\n"
                              "测试时请**不要点到别的窗口** —— 硬件键盘是往当前焦点窗口打字的。",
                  style='SettingsSmall.TLabel', justify=tk.LEFT).pack(anchor=tk.W)

        self._test_entry = ttk.Entry(card3, font=("Consolas", 11))
        self._test_entry.pack(fill=tk.X, pady=(6, 6))

        self._status_label = ttk.Label(card3, text="", style='SettingsSmall.TLabel',
                                       justify=tk.LEFT, wraplength=560)
        self._status_label.pack(anchor=tk.W, pady=(2, 6))

        self._backend_status = ttk.Label(card3, text="", style='SettingsSmall.TLabel',
                                         justify=tk.LEFT, wraplength=560)
        self._backend_status.pack(anchor=tk.W)

        # ----- 底部 -----
        bottom = ttk.Frame(outer, style='SettingsInner.TFrame')
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="保存并关闭", style='Success.TButton',
                   command=lambda: self._on_close(save=True)).pack(side=tk.RIGHT)

    # --------------------------------------------------------------- 小工具 --

    def _cfg(self):
        """用界面上的值临时拼一份 settings（测试时立即生效，不必先保存）"""
        s = dict(self.app.settings)
        s["keyboard_backend"] = self._backend_var.get()
        s["stm32_port"] = (self._port_var.get() or "auto").strip()
        try:
            s["stm32_interval_ms"] = int(float(self._interval_var.get()))
        except Exception:
            s["stm32_interval_ms"] = 25
        try:
            s["stm32_timeout"] = float(self._timeout_var.get())
        except Exception:
            s["stm32_timeout"] = 3.0
        return s

    def _set_status(self, text, level="info"):
        style = {"ok": 'Success.TLabel', "err": 'Warning.TLabel',
                 "info": 'SettingsSmall.TLabel'}.get(level, 'SettingsSmall.TLabel')
        colour = {"ok": "#27ae60", "err": "#e74c3c", "info": "#888888"}.get(level)
        try:
            self._status_label.config(text=text, foreground=colour)
        except Exception:
            pass

    def _refresh_ports(self):
        values = ["auto"]
        try:
            for dev, desc in stm32_keyboard.available_ports():
                values.append(dev if not desc else "%s (%s)" % (dev, desc))
        except Exception:
            pass
        cur = (self._port_var.get() or "auto").strip()
        if cur and cur not in values:
            values.append(cur)
        try:
            self._port_combo.config(values=values)
        except Exception:
            pass

    def _refresh_status(self):
        """刷新三个后端的可用性 + 当前会选中谁"""
        try:
            driver_keyboard.set_settings(self._cfg())
            lines, chosen = driver_keyboard.backend_report()
            txt = "\n".join("%s %s —— %s" % (m, n, d) for m, n, d in lines)
            txt += "\n当前会使用：%s" % (driver_keyboard.get_backend() if chosen else "无可用后端")
            self._backend_status.config(text=txt)
        except Exception as e:
            self._backend_status.config(text="状态检测异常：%s" % e)

    # ----------------------------------------------------------- 测试动作 --

    def _test_connect(self):
        self._set_status("正在检测 STM32 连接（只发 PING/INFO，不按键）...", "info")

        def _run():
            try:
                ok, detail = stm32_keyboard.probe(self._cfg())
            except Exception as e:
                ok, detail = False, "异常：%s" % e
            self.win.after(0, lambda: self._set_status(
                ("✓ 连接成功\n%s" % detail) if ok else ("✗ 连接失败：%s" % detail),
                "ok" if ok else "err"))
            self.win.after(0, self._refresh_status)

        threading.Thread(target=_run, daemon=True).start()

    def _test_type(self):
        """打字测试：清空输入框 → 把焦点交给它 → 让 STM32 打进来 → 读回比对"""
        if self._busy:
            return
        self._busy = True
        expected = TEST_TEXT
        try:
            self._test_entry.delete(0, tk.END)
        except Exception:
            pass
        # 焦点必须在本窗口的输入框上：硬件键盘是往当前焦点窗口打字
        try:
            self.win.lift()
            self.win.focus_force()
            self._test_entry.focus_set()
            self.win.update()
        except Exception:
            pass
        # ⚠️ 必须临时摘掉输入法关联：中文输入法会把硬件键盘的字符吃掉/转全角，
        #    导致「测出来像 STM32 坏了」，其实只是输入法在中间作怪
        self._ime_old = _ime_detach(self.win)
        self._set_status("3 秒后开始打字，请不要点到别的窗口...", "info")
        cfg = self._cfg()

        def _run():
            import time
            time.sleep(3)
            ok, detail = False, ""
            try:
                ok = stm32_keyboard.send_string(expected, interval=0.03, settings=cfg)
            except Exception as e:
                detail = "异常：%s" % e
            if not ok and not detail:
                detail = stm32_keyboard.last_error() or "发送失败"
            self.win.after(0, lambda: self._finish_type(ok, detail, expected))

        threading.Thread(target=_run, daemon=True).start()

    def _finish_type(self, ok, detail, expected):
        self._busy = False
        try:
            got = self._test_entry.get()
        except Exception:
            got = ""
        _ime_restore(self._ime_old)          # 输入法关联还回去
        self._ime_old = None
        if ok and got == expected:
            self._set_status("✓ STM32 打字测试通过：硬件键盘把 %d 个字符完整打进了输入框。"
                             % len(expected), "ok")
        elif ok and got != expected:
            self._set_status("△ 指令已成功发送，但输入框内容对不上。\n"
                             "  期望：%r\n  实际：%r\n"
                             "  · 若实际为空/不全 → 测试期间焦点被切走了（点到了别的窗口）\n"
                             "  · 若字符有缺失 → 可把「打字间隔」调大一点再试"
                             % (expected, got), "err")
        else:
            self._set_status("✗ STM32 打字测试失败：%s" % (detail or "未知原因"), "err")
        self._refresh_status()

    def _emergency_stop(self):
        def _run():
            ok, detail = stm32_keyboard.stop(self._cfg())
            self.win.after(0, lambda: self._set_status(
                ("✓ 已发送紧急停止：全部按键已松开，之后需点「恢复」才能继续\n%s" % detail) if ok
                else "✗ 紧急停止失败：%s" % detail, "ok" if ok else "err"))
        threading.Thread(target=_run, daemon=True).start()

    def _resume(self):
        def _run():
            ok, detail = stm32_keyboard.resume(self._cfg())
            self.win.after(0, lambda: self._set_status(
                ("✓ 已恢复工作\n%s" % detail) if ok else "✗ 恢复失败：%s" % detail,
                "ok" if ok else "err"))
        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------- 保存/关闭 --

    def _on_close(self, save=False):
        _ime_restore(self._ime_old)      # 万一在打字测试中途关窗，别把输入法关联留在摘掉状态
        self._ime_old = None
        # ⚠️ 先存窗口几何，再存本窗口的配置。
        # utils.save_window_geometry() 内部是「load_settings → 改 → save_settings」，
        # 会把后写的人盖掉；放在前面才不会被它覆盖。
        try:
            import utils
            utils.save_window_geometry(self.win, "keyboard_settings_geometry")
        except Exception:
            pass
        if save:
            try:
                target = dict(config.load_settings())
                target["keyboard_backend"] = self._backend_var.get()
                target["stm32_port"] = (self._port_var.get() or "auto").strip()
                try:
                    target["stm32_interval_ms"] = max(5, min(500, int(float(self._interval_var.get()))))
                except Exception:
                    target["stm32_interval_ms"] = 25
                try:
                    target["stm32_timeout"] = max(0.5, min(30.0, float(self._timeout_var.get())))
                except Exception:
                    target["stm32_timeout"] = 3.0
                config.save_settings(target)
                self.app.settings.update(target)
                # 立即生效：让正在运行的程序按新后端走（不必重启）
                driver_keyboard.set_settings(self.app.settings)
                print("⌨️ 键盘设置已保存：后端=%s，STM32 端口=%s"
                      % (target["keyboard_backend"], target["stm32_port"]))
            except Exception as e:
                print("⚠️ 键盘设置保存失败：%s" % e)
        try:
            self.win.destroy()
        except Exception:
            pass
