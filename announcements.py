# -*- coding: utf-8 -*-
"""
赛季公告（每天提醒一次 + 一键配置）

行为：
- 程序启动后若「今天还没弹过」且该公告未被永久关闭 → 弹一次公告窗口
- 「关闭」= 今天不再提醒（明天启动再提醒）
- 「永久不再提示」= 此公告永久不再显示（写入 announcements_forever）
- 「一键配置」= 自动给第9模板（烽火地带入口 Hazard_Operations）写入「点击后插入步骤」：
  按空格 → OCR 找「开启新赛季」并点击（找不到则继续后续流程），随后关闭且今天不再提醒
  （第9模板的图片更新需用户手动重新截图，公告内已提示）

存储：settings.json（announcement_last_date / announcements_forever）
"""
import datetime
import tkinter as tk
from tkinter import ttk, messagebox

import config
import utils
import template_insert_steps

ANNOUNCEMENT_ID = "s11_season_20260902"
ANNOUNCEMENT_TITLE = "S11 赛季更新提示"
# 公告正文（与用户给定内容一致，排版分行便于阅读）
ANNOUNCEMENT_TEXT = (
    "S11 赛季已更新，本工具需要做以下处理：\n"
    "1. 请手动更新配置「第9号模板（烽火地带入口）」——若游戏内图标已变化，\n"
    "   请在 模板上传向导 → 第9模板 → 模板设置 → 截取，重新截图上传；\n"
    "2. 每个账号第9步（进入烽火地带）完成后、首次进入段位结算界面时，\n"
    "   需先按空格，再用 OCR 识别点击「开启新赛季」。\n\n"
    "点击下方「一键配置」即可自动写入该段位结算处理步骤\n"
    "（作为第9模板的点击后插入步骤），随后照常运行即可。\n"
    "该提示每天最多提醒一次；点「关闭」明天再提醒，点「永久不再提示」则不再出现。"
)

# 一键配置写入的插入步骤（第9模板点击后执行）
QUICK_CONFIG_TEMPLATE = "Hazard_Operations"
QUICK_CONFIG_STEPS = [
    {"type": "keyboard", "name": "按空格", "keys": "space", "key_mode": "key", "pause_after": 1.0},
    {"type": "ocr", "name": "点击开启新赛季", "text": "开启新赛季",
     "confidence": 0.6, "timeout": 10, "pause_after": 0.5},
]


def _today():
    return datetime.date.today().isoformat()


def should_show():
    """今天未弹过且未被永久关闭 → True"""
    s = config.load_settings()
    forever = s.get("announcements_forever")
    if isinstance(forever, list) and ANNOUNCEMENT_ID in forever:
        return False
    last = s.get("announcement_last_date", "")
    return last != _today()


def _save(done_forever=False):
    """记录公告已处理：done_forever=True 永久关闭；否则仅今天关闭"""
    s = config.load_settings()
    if done_forever:
        lst = s.get("announcements_forever")
        if not isinstance(lst, list):
            lst = []
        if ANNOUNCEMENT_ID not in lst:
            lst = lst + [ANNOUNCEMENT_ID]
        s["announcements_forever"] = lst
    s["announcement_last_date"] = _today()
    config.save_settings(s)


def maybe_show(root, app=None):
    """程序启动后调用；满足条件才弹公告。app.running 时（正在跑自动化）本次跳过"""
    if not should_show():
        return
    if app is not None and getattr(app, "running", False):
        return
    _show(root)


def _apply_quick_config(root):
    """一键配置：给第9模板写「点击后插入步骤」（空格 + OCR 开启新赛季）"""
    try:
        ok = template_insert_steps.save(QUICK_CONFIG_TEMPLATE, "after", QUICK_CONFIG_STEPS)
    except Exception as e:
        ok = False
        print(f"❌ 一键配置失败：{e}")
    def _tip():
        if ok:
            messagebox.showinfo(
                "已配置",
                "已给「第9模板（烽火地带入口）」写入点击后插入步骤：\n"
                "按空格 → OCR 识别并点击『开启新赛季』（找不到会自动继续后续流程）。\n\n"
                "⚠️ 若游戏内「烽火地带入口」图标已随赛季变化，请到\n"
                "模板上传向导 → 第9模板 → 模板设置 → 截取，重新截图上传新图标。",
                parent=root)
        else:
            messagebox.showerror("配置失败", "写入第9模板插入步骤失败，请重试。", parent=root)
    try:
        root.after(0, _tip)
    except Exception:
        pass


def _show(root):
    """显示公告窗口"""
    win = tk.Toplevel(root)
    win.title(ANNOUNCEMENT_TITLE)
    win.resizable(False, False)
    win.transient(root)
    win.attributes("-topmost", True)
    win.grab_set()
    try:
        utils.set_window_icon(win)
    except Exception:
        pass

    wrap_w = 440
    ttk.Label(win, text=ANNOUNCEMENT_TITLE, font=('Microsoft YaHei UI', 13, 'bold'),
              foreground='#E67E22').pack(anchor='w', padx=14, pady=(12, 6))
    msg = tk.Message(win, text=ANNOUNCEMENT_TEXT, width=wrap_w, justify=tk.LEFT,
                     font=('Microsoft YaHei UI', 10), anchor='w')
    msg.pack(fill=tk.X, padx=14, pady=(0, 6))

    def _do_close(forever=False):
        try:
            win.grab_release()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        _save(done_forever=forever)

    btn = ttk.Frame(win)
    btn.pack(fill=tk.X, padx=14, pady=(4, 12))
    ttk.Button(btn, text="一键配置", style='Accent.TButton', width=12,
               command=lambda: (_apply_quick_config(root), _do_close(forever=False))).pack(
        side=tk.RIGHT, padx=(6, 0))
    ttk.Button(btn, text="永久不再提示", width=12,
               command=lambda: _do_close(forever=True)).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(btn, text="关闭", width=8,
               command=lambda: _do_close(forever=False)).pack(side=tk.RIGHT)

    win.update_idletasks()
    try:
        pw = win.winfo_width()
        ph = win.winfo_height()
        x = (win.winfo_screenwidth() - pw) // 2
        y = (win.winfo_screenheight() - ph) // 3
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass
    try:
        win.focus_force()
    except Exception:
        pass
