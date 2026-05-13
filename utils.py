"""
工具函数模块
包含启动应用程序、窗口激活、图像识别点击、WeGame 快捷登录、进程强制结束等
"""
import time
import cv2
import numpy as np
import pyautogui
import subprocess
import os
import psutil
import win32gui
import win32con
from config import (CONFIDENCE, WAIT_TIME, WEGAME_PROCESS, DELTA_PROCESS,
                    IMAGE_ACCOUNT_SELECT, IMAGE_LOGIN_BTN)

def start_app(exe_path, app_name):
    """启动外部程序，5秒后返回是否成功"""
    if not exe_path or not os.path.exists(exe_path):
        print(f"❌ 找不到 {app_name} 程序文件：{exe_path}")
        return False
    try:
        work_dir = os.path.dirname(exe_path)
        subprocess.Popen(exe_path, cwd=work_dir)
        print(f"✅ 已启动：{app_name}")
        time.sleep(5)
        return True
    except Exception as e:
        print(f"❌ 启动 {app_name} 失败：{e}")
        return False

def activate_window_by_title(title_contains, partial_match=True, exclude_titles=None):
    """
    按标题激活窗口（支持部分匹配、排除关键词）
    返回是否成功激活
    """
    if exclude_titles is None:
        exclude_titles = []

    def enum_callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd):
            window_title = win32gui.GetWindowText(hwnd)
            if partial_match and title_contains.lower() in window_title.lower():
                for ex in exclude_titles:
                    if ex.lower() in window_title.lower():
                        return True
                windows.append((hwnd, window_title))
            elif not partial_match and window_title == title_contains:
                for ex in exclude_titles:
                    if ex.lower() in window_title.lower():
                        return True
                windows.append((hwnd, window_title))
        return True

    windows = []
    win32gui.EnumWindows(enum_callback, windows)
    if not windows:
        print(f"❌ 未找到包含 '{title_contains}' 的窗口")
        return False

    hwnd, title = windows[0]
    print(f"🔍 找到窗口: {title}")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.3)
    try:
        win32gui.SetForegroundWindow(hwnd)
        print(f"✅ 已激活窗口: {title}")
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"❌ 激活失败: {e}")
        return False

def wait_for_window(title_contains, timeout=30, partial_match=True, exclude_titles=None):
    """循环等待直到窗口出现并激活成功"""
    cond = "包含" if partial_match else "完全等于"
    print(f"⏳ 等待窗口标题 {cond} '{title_contains}'...")
    start = time.time()
    while time.time() - start < timeout:
        if activate_window_by_title(title_contains, partial_match, exclude_titles):
            return True
        time.sleep(1)
    print(f"❌ 超时未找到窗口 '{title_contains}'")
    return False

def find_and_click(img_path, timeout=20, region=None):
    """
    在当前屏幕中查找图片并点击中心点
    返回是否成功找到并点击
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            screen = pyautogui.screenshot(region=region) if region else pyautogui.screenshot()
        except Exception:
            time.sleep(0.5)
            continue
        screen_cv = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
        template = cv2.imread(img_path, 0)
        if template is None:
            print(f"❌ 图片文件不存在：{img_path}")
            return False

        gray = cv2.cvtColor(screen_cv, cv2.COLOR_BGR2GRAY)
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val >= CONFIDENCE:
            h, w = template.shape
            x = max_loc[0] + w // 2 + (region[0] if region else 0)
            y = max_loc[1] + h // 2 + (region[1] if region else 0)

            # 忽略屏幕边缘可疑坐标
            screen_w, screen_h = pyautogui.size()
            margin = 10
            if x < margin or y < margin or x > screen_w - margin or y > screen_h - margin:
                print(f"⚠️ 忽略可疑坐标 ({x}, {y})，继续寻找...")
                time.sleep(0.3)
                continue

            pyautogui.moveTo(x, y, duration=0.2)
            pyautogui.click()
            time.sleep(WAIT_TIME)
            return True
        time.sleep(0.3)
    print(f"⏳ 超时未找到：{img_path}")
    return False

def wegame_quick_login(qq_number_img):
    """
    使用图像识别完成 WeGame 快捷登录：
    点击账号选择按钮 → 点击目标 QQ 号 → 点击登录按钮
    """
    print("🔍 点击账号选择按钮...")
    if not find_and_click(IMAGE_ACCOUNT_SELECT, timeout=15):
        print("❌ 未找到账号选择按钮")
        return False
    time.sleep(1)  # 等待列表弹出

    print("🔍 选择 QQ 号...")
    if not find_and_click(qq_number_img, timeout=10):
        print("❌ 未找到目标 QQ 号")
        return False
    time.sleep(0.5)

    print("🔍 点击登录按钮...")
    if not find_and_click(IMAGE_LOGIN_BTN, timeout=10):
        print("❌ 未找到登录按钮")
        return False
    print("✅ 快捷登录完成")
    return True

def kill_process(process_name, wait_exit=True, max_wait=30):
    """强制结束指定进程，可选等待退出"""
    killed = False
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and proc.info['name'].lower() == process_name.lower():
            try:
                proc.kill()
                print(f"✅ 已结束进程: {proc.info['name']}")
                killed = True
            except Exception:
                pass

    if not killed:
        print(f"⚠️ 未找到进程 {process_name}，可能已退出")
        return True

    if wait_exit:
        print(f"⏳ 等待进程 {process_name} 完全退出...")
        start = time.time()
        while time.time() - start < max_wait:
            exists = any(
                p.info['name'] and p.info['name'].lower() == process_name.lower()
                for p in psutil.process_iter(['name'])
            )
            if not exists:
                print("✅ 进程已完全退出")
                return True
            time.sleep(1)
        print(f"❌ 超时：进程 {process_name} 仍在运行")
        return False
    return True
# 在原有 utils.py 末尾添加：
def close_window_by_title(title_contains, partial_match=True):
    """通过窗口标题查找窗口并发送 WM_CLOSE 消息"""
    hwnd_target = None
    def enum_callback(hwnd, _):
        nonlocal hwnd_target
        if win32gui.IsWindowVisible(hwnd):
            wt = win32gui.GetWindowText(hwnd)
            if partial_match and title_contains.lower() in wt.lower():
                hwnd_target = hwnd
                return False
            elif not partial_match and wt == title_contains:
                hwnd_target = hwnd
                return False
        return True
    win32gui.EnumWindows(enum_callback, None)
    if hwnd_target:
        win32gui.PostMessage(hwnd_target, win32con.WM_CLOSE, 0, 0)
        return True
    return False