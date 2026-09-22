# -*- coding: utf-8 -*-
"""日志遮罩自检：验证遮罩是否真的「排除在屏幕捕获之外」。

为什么要这个工具
---------------
遮罩（screen_log_overlay）默认盖在屏幕一角。而模板匹配是「先截屏、再找图」：
如果遮罩正好盖住目标按钮，截到的像素里就有遮罩的日志文字 → 匹配失败 → 那个按钮永远点不到。
（历史缺陷：原来的「点击避让」写在 `if matched:` 里面，而遮罩污染的是匹配**之前**的截图，
  所以遮罩一盖住目标就永远匹配不上、也就永远走不到避让。2026-09-22 已改成「截图前让位」。）

现在的做法：给遮罩窗口设 Win32 的 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)（Win10 2004+）。
遮罩照常显示，但 GDI BitBlt（pyautogui.screenshot / PIL ImageGrab）拍到的是它背后原本的画面。

本脚本做四步，逐条打印结论：
  1. 构造后**读回**显示亲和性（不再只看 SetWindowDisplayAffinity 的返回值 —— 它会「谎报成功」）
  2. 遮罩所在区域的截图是否与「遮罩出现之前」一致（一致 = 截图看穿了遮罩）
  3. set_click_through()（内部 setWindowFlag + show，会重建原生窗口）后标志是否被自动补回
  4. **品红探针对照实验**：不打标志必须拍得到、打上标志必须拍不到 —— 唯一的端到端证据

第 4 步是决定性的；前三步用于定位是哪一环出的问题。
若结论是「不支持」，程序会自动降级为「截图前让位 + 匹配失败换角落」的兜底方案
（见 gui_app._overlay_avoid_region / _overlay_nudge 与 utils._find_and_click_core）。

用法：直接运行即可（会短暂出现一个遮罩窗口和一个品红小方块，共约 4 秒）
    python 日志遮罩自检.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pyautogui
from PyQt6.QtWidgets import QApplication

from screen_log_overlay import (ScreenLogOverlay, is_excluded_from_capture,
                                probe_exclude_from_capture)

WIN_W, WIN_H = 320, 220          # 遮罩尺寸（Qt **逻辑**像素）
WIN_X, WIN_Y = 120, 120          # 遮罩位置（Qt **逻辑**像素）
# 遮罩内部一小块（Qt 逻辑坐标）。⚠️ 截图比对前必须换算成物理像素，见 _physical()
PROBE_LOGICAL = (WIN_X + 60, WIN_Y + 60, 80, 80)
# 与基线比对的最大通道差上限：0 最理想；留一点余量容忍背景自身的变化
DIFF_TOLERANCE = 6.0

app = QApplication.instance() or QApplication([])


def _dpr():
    """Qt 逻辑像素 → 物理像素的比例（本机 2880×1800 @200% 缩放时为 2.0）

    ⚠️ Qt 按**逻辑**像素摆放窗口，pyautogui.screenshot 按**物理**像素取区域。
    不换算就会「按坐标取错地方」—— 比对的其实是桌面和桌面，看着全绿其实什么都没测。
    """
    try:
        return float(QApplication.primaryScreen().devicePixelRatio())
    except Exception:
        return 1.0


def _physical(box):
    """逻辑坐标矩形 → 物理坐标矩形"""
    r = _dpr()
    return tuple(int(round(v * r)) for v in box)


def _pump(n=5, delay=0.15):
    for _ in range(n):
        app.processEvents()
        time.sleep(delay)


def probe(tag):
    _pump(3)
    img = pyautogui.screenshot(region=_physical(PROBE_LOGICAL))
    arr = np.array(img)
    img.close()
    mean = arr.reshape(-1, 3).mean(axis=0).round(1)
    print(f"  {tag:<34} 平均RGB={mean}")
    return mean


def channel_diff(a, b):
    if a is None or b is None:
        return -1.0
    return float(np.abs(np.array(a) - np.array(b)).max())


def main():
    ok = []
    sw, sh = pyautogui.size()
    print(f"屏幕物理尺寸 = {sw}x{sh}；Qt 逻辑尺寸 = "
          f"{QApplication.primaryScreen().size().width()}x"
          f"{QApplication.primaryScreen().size().height()}；"
          f"缩放比 = {_dpr():.2f}")
    print(f"比对区域：逻辑 {PROBE_LOGICAL} → 物理 {_physical(PROBE_LOGICAL)}")
    print("提示：本脚本用「屏幕静止的背景」做比对，运行期间请不要切换窗口/播放视频。\n")
    base = probe("基线（遮罩出现之前）")

    ov = ScreenLogOverlay(max_lines=50, width=WIN_W, height=WIN_H,
                          translucent_bg=True, exclude_from_capture=True)
    ov.move(WIN_X, WIN_Y)
    ov.set_status_text("自检 - 正在运行 00:00:01")
    ov.info("这是一行用于自检的日志文字 0123456789")
    ov.show()
    _pump()

    # ---------- 步骤 1：读回标志 ----------
    hwnd = int(ov.winId())
    flag_ok = is_excluded_from_capture(hwnd)
    print(f"步骤 1：读回显示亲和性 → {'✅ 标志已设上' if flag_ok else '❌ 标志没设上'}"
          f"（capture_excluded={ov.capture_excluded}）")
    ok.append(flag_ok)

    d1 = channel_diff(probe("遮罩显示中（应看穿遮罩）"), base)
    shot_ok = d1 <= DIFF_TOLERANCE
    print(f"  与基线最大通道差 = {d1:.1f} → "
          + ("✅ 截图看穿了遮罩" if shot_ok else "❌ 遮罩仍出现在截图里"))
    ok.append(shot_ok)

    # ---------- 步骤 2：原生窗口重建后标志是否还在 ----------
    print("\n步骤 2：再调一次 set_click_through()（setWindowFlag 会重建原生窗口，WDA 标志会丢）")
    ov.set_click_through()
    _pump()
    rebuilt_ok = ov.ensure_capture_exclusion()
    print("  重建后 ensure_capture_exclusion() =", rebuilt_ok,
          "→", "✅ 已自动补回" if rebuilt_ok else "❌ 标志丢失")
    d2 = channel_diff(probe("重建后（应看穿遮罩）"), base)
    shot2_ok = d2 <= DIFF_TOLERANCE
    print(f"  与基线最大通道差 = {d2:.1f} → "
          + ("✅ 截图仍看穿遮罩" if shot2_ok else "❌ 遮罩又进截图了"))
    ok.append(rebuilt_ok and shot2_ok)

    ov.close()
    _pump(2)

    # ---------- 步骤 3：品红探针对照实验（决定性） ----------
    print("\n步骤 3：品红探针对照实验（本机到底支不支持，就看这一步）")
    probe_ok = probe_exclude_from_capture(log=lambda m: print("  " + m))
    ok.append(probe_ok)

    print("\n=== 结论 ===")
    if all(ok):
        print("✅ 全部通过：遮罩已排除在屏幕捕获之外，原生窗口重建后仍保持。")
        print("   → 可以放心一直开着日志遮罩跑游戏，遮罩不会污染模板匹配的截图。")
        return 0
    print("❌ 有失败项，逐条结果见上。")
    print("   程序会自动降级为「截图前让位 + 匹配失败换角落」的兜底方案：")
    print("   · 已知识别区域（验证码/资产）：截图前把遮罩移到不遮挡的角落，截完复原")
    print("   · 全屏找图：匹配失败且疑似被遮住时，把遮罩换到下一个角落重试（限量 2 次）")
    print("   启动时日志里会打印实测结论（📊 / ⚠️ 开头），据此判断当前用的是哪条路。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
