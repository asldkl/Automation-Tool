# -*- coding: utf-8 -*-
"""
赛季公告（每天提醒一次 + 永久关闭）

行为：
- 程序启动后若「今天还没弹过」且该公告未被永久关闭 → 弹一次公告窗口
- 「关闭」= 今天不再提醒（明天启动再提醒）；点窗口标题栏 X 同样按「关闭」记录
- 「永久不再提示」= 此公告永久不再显示（写入 forever 列表）
- 正在跑自动化（app.running）时不弹，改为每隔一段时间重试，直到空闲或超次数放弃
  （避免开机自启场景自动化先于本检测启动，公告被永久跳过）

存储：
    独立文件 %APPDATA%\\DeltaAutoTool\\announcements.json
    {"last_date": "YYYY-MM-DD", "forever": ["公告id", ...]}
    —— 特意不用 settings.json：运行过程中多处会用"启动时的 settings 快照"整份覆盖写回，
      会把公告的每日一次/永久关闭状态回滚掉；独立文件可避免被覆盖。
    旧版写在 settings.json（announcement_last_date / announcements_forever）的
    状态在首次读取时自动迁移到本文件。
"""
import datetime
import os
import json
import time
import tkinter as tk
from tkinter import ttk

import config
import utils

ANNOUNCEMENT_ID = "s11_season_20260902"
ANNOUNCEMENT_TITLE = "S11 赛季更新提示"
# 公告正文（纯提示，不提供自动写入；排版分行便于阅读）
ANNOUNCEMENT_TEXT = (
    "S11 赛季已更新，请进行以下检查：\n"
    "1. 若游戏内「烽火地带入口」（第9模板）图标已变化，\n"
    "   请在 模板上传向导 → 第9模板 → 模板设置 → 截取，重新截图上传；\n"
    "2. 每个账号第9步（进入烽火地带）完成后、点击第10步（特勤处入口）之前，\n"
    "   首次进入的段位结算界面需先按空格，再用 OCR 识别点击「开启新赛季」。\n"
    "   如需自动处理，可在 模板上传向导 → 第10模板 → 模板设置 → 插入步骤 中\n"
    "   自行配置（按空格 → OCR 找「开启新赛季」并点击，该步勾选「可选」）。\n\n"
    "该提示每天最多提醒一次；点「关闭」明天再提醒，点「永久不再提示」则不再出现。"
)

ANNOUNCEMENTS_JSON = os.path.join(config.APP_DATA_DIR, "announcements.json")
# 运行中跳过时的重试参数：每 2 分钟重试一次，最多 60 次（约 2 小时）
_RETRY_INTERVAL_MS = 120_000
_MAX_RUNNING_RETRIES = 60


def _today():
    return datetime.date.today().isoformat()


def _migrate_from_settings():
    """旧版状态在 settings.json（announcement_last_date / announcements_forever），搬到独立文件"""
    try:
        s = config.load_settings()
        last = s.get("announcement_last_date", "")
        forever = s.get("announcements_forever")
        if last or isinstance(forever, list):
            return {"last_date": last if isinstance(last, str) else "",
                    "forever": [x for x in forever if isinstance(x, str)]}
    except Exception:
        pass
    return None


def _read_state():
    """读取状态文件；文件不存在时尝试从 settings.json 迁移；损坏时备份原文件后当空处理"""
    try:
        with open(ANNOUNCEMENTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        migrated = _migrate_from_settings()
        if migrated is not None:
            _write_state(migrated)
            return migrated
        return {}
    except Exception:
        # 文件损坏：把原文件改名保留（供手动找回），当空状态处理，避免之后保存时静默丢状态
        try:
            backup = f"{ANNOUNCEMENTS_JSON}.corrupt.{time.strftime('%Y%m%d_%H%M%S')}"
            os.replace(ANNOUNCEMENTS_JSON, backup)
            print(f"⚠️ 公告状态文件损坏，已备份为 {os.path.basename(backup)} 并按空状态继续")
        except Exception:
            pass
    return {}


def _write_state(data):
    """原子写状态文件（.tmp + os.replace），返回是否成功"""
    try:
        config.ensure_app_data_dir()
        tmp = ANNOUNCEMENTS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ANNOUNCEMENTS_JSON)
        return True
    except Exception as e:
        print(f"⚠️ 公告状态保存失败：{e}")
        return False


def should_show():
    """今天未弹过且未被永久关闭 → True"""
    state = _read_state()
    forever = state.get("forever")
    if isinstance(forever, list) and ANNOUNCEMENT_ID in forever:
        return False
    return state.get("last_date") != _today()


def _save(done_forever=False):
    """记录公告已处理：done_forever=True 永久关闭；否则仅今天关闭"""
    state = _read_state()
    if done_forever:
        lst = state.get("forever")
        if not isinstance(lst, list):
            lst = []
        if ANNOUNCEMENT_ID not in lst:
            lst = lst + [ANNOUNCEMENT_ID]
        state["forever"] = lst
    state["last_date"] = _today()
    return _write_state(state)


def maybe_show(root, app=None, _attempts=0):
    """程序启动后调用；满足条件才弹公告。
    app.running 时（正在跑自动化，含开机自启立即运行）不弹，延迟重试直到空闲或超次数"""
    if not should_show():
        return
    if app is not None and getattr(app, "running", False):
        if _attempts >= _MAX_RUNNING_RETRIES:
            print("ℹ️ 公告提醒：自动化长时间运行，本次启动不再弹出（明天会再提醒）")
            return
        try:
            root.after(_RETRY_INTERVAL_MS,
                       lambda: maybe_show(root, app, _attempts + 1))
        except Exception:
            pass
        return
    _show(root)


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

    # 点标题栏 X / Alt+F4 也按「关闭」记录，保证「每天最多提醒一次」不被绕过
    win.protocol("WM_DELETE_WINDOW", lambda: _do_close(forever=False))

    btn = ttk.Frame(win)
    btn.pack(fill=tk.X, padx=14, pady=(4, 12))
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
