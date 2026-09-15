# -*- coding: utf-8 -*-
"""日志遮罩自检：验证遮罩是否已「排除在屏幕捕获之外」。

为什么要这个工具
---------------
遮罩（screen_log_overlay）默认盖在屏幕左下角。而模板匹配是「先截屏、再找图」：
如果遮罩正好盖住目标按钮，截到的像素里就有遮罩的日志文字 → 匹配失败 → 那个按钮就永远点不到。
（历史缺陷：原来的「点击避让」写在匹配成功之后，而遮罩污染的是匹配之前的截图，
  所以遮罩一盖住目标就永远走不到避让。）

现在的做法：给遮罩窗口设 Win32 的 SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)（Win10 2004+）。
遮罩照常显示在屏幕上，但 GDI BitBlt（pyautogui.screenshot / PIL ImageGrab）拍到的是它背后原本的画面。

本脚本做三件事并逐条打印结论：
  1. 构造后 capture_excluded 是否为 True
  2. 遮罩所在区域的截图是否与「遮罩出现之前」完全一致（一致 = 截图看穿了遮罩）
  3. set_click_through()（内部 setWindowFlag + show，会重建原生窗口）之后，标志是否被 showEvent 自动补回

用法：直接运行即可（会短暂出现一个小遮罩窗口，约 2 秒）
    python 日志遮罩自检.py
若第 2 步的「最大通道差」不为 0，说明本机不支持该 API —— 程序会自动降级为
「识别失败时让遮罩让位」的兼容方案（见 gui_app._overlay_avoid_region）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pyautogui
from PyQt6.QtWidgets import QApplication

from screen_log_overlay import ScreenLogOverlay

WIN_W, WIN_H = 320, 220
WIN_X, WIN_Y = 120, 120
PROBE = (WIN_X + 60, WIN_Y + 60, 80, 80)   # 取遮罩内部一小块做比对

app = QApplication.instance() or QApplication([])


def _pump(n=5, delay=0.15):
    for _ in range(n):
        app.processEvents()
        time.sleep(delay)


def probe(tag):
    _pump(3)
    img = pyautogui.screenshot(region=PROBE)
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
    print(f"探测区域 = {PROBE}（屏幕 {pyautogui.size()[0]}x{pyautogui.size()[1]}）")
    base = probe("基线（遮罩出现之前）")

    ov = ScreenLogOverlay(max_lines=50, width=WIN_W, height=WIN_H,
                          translucent_bg=True, exclude_from_capture=True)
    ov.move(WIN_X, WIN_Y)
    ov.set_status_text("自检 - 正在运行 00:00:01")
    ov.info("这是一行用于自检的日志文字 0123456789")
    ov.show()
    _pump()

    print("步骤 1：构造后 capture_excluded =", ov.capture_excluded,
          "→", "✅" if ov.capture_excluded else "❌ 应排除在捕获外")
    d1 = channel_diff(probe("遮罩显示中（已排除捕获）"), base)
    print(f"  与基线最大通道差 = {d1:.1f} → "
          + ("✅ 截图看穿了遮罩" if d1 <= 6 else "❌ 遮罩仍出现在截图里"))

    print("步骤 2：再调一次 set_click_through()（setWindowFlag 会重建原生窗口，WDA 标志会丢）")
    ov.set_click_through()
    _pump()
    print("  重建后 capture_excluded =", ov.capture_excluded,
          "→", "✅ 已自动补回" if ov.capture_excluded else "❌ 标志丢失")
    d2 = channel_diff(probe("重建后（已排除捕获）"), base)
    print(f"  与基线最大通道差 = {d2:.1f} → "
          + ("✅ 截图仍看穿遮罩" if d2 <= 6 else "❌ 遮罩又进截图了"))

    ov.close()

    print()
    print("=== 结论 ===")
    if ov.capture_excluded and d1 <= 6 and d2 <= 6:
        print("✅ 全部通过：遮罩已排除在屏幕捕获之外，原生窗口重建后仍保持。")
        return 0
    print("❌ 有失败项，请看上面的逐条结果（程序会自动降级为『让位』方案）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
