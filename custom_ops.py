"""
自定义操作模块
用户在主流程完成后（游戏回到主界面），自行配置步骤序列，
程序在每个账号的主流程结束后、关闭游戏前自动按顺序执行。

支持的步骤类型（op.type）：
    image      找图点击（默认）
    coordinate 坐标点击
    ocr        OCR文字识别点击
    keyboard   键盘输入（按键/组合键/文本）
    multi_image 多图匹配点击（按顺序试多张图）
    drag       鼠标拖拽（起点→终点）
    scroll     鼠标滚轮
    screenshot 截图保存（存到设置目录/当天日期/账号名_时间.png）
    condition  条件跳转（找图/OCR 探测，满足则跳转到指定步骤）
    jump       无条件跳转到指定步骤（配合 condition 实现循环）
"""
import os
import time
import json
import threading

import config
import utils

CUSTOM_OPS_DIR = os.path.join(config.APP_DATA_DIR, "custom_ops")
CUSTOM_OPS_IMAGES = os.path.join(CUSTOM_OPS_DIR, "images")
CUSTOM_OPS_JSON = os.path.join(CUSTOM_OPS_DIR, "ops.json")
RUNS_JSON = os.path.join(CUSTOM_OPS_DIR, "runs.json")   # 每个账号自定义操作运行记录

_lock = threading.Lock()


def ensure_dirs():
    """确保自定义操作相关目录存在"""
    os.makedirs(CUSTOM_OPS_IMAGES, exist_ok=True)


def load_ops():
    """加载自定义操作步骤列表，返回 [{...}, ...]"""
    if not os.path.exists(CUSTOM_OPS_JSON):
        return []
    try:
        with open(CUSTOM_OPS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def save_ops(steps):
    """保存自定义操作步骤列表（原子写入）"""
    ensure_dirs()
    tmp = CUSTOM_OPS_JSON + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(steps, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CUSTOM_OPS_JSON)
        return True
    except Exception as e:
        print(f"⚠️ 保存自定义操作失败：{e}")
        return False


def image_path(filename):
    """获取步骤图片的完整路径"""
    return os.path.join(CUSTOM_OPS_IMAGES, filename)


def save_captured_image(pil_image, filename):
    """保存截图到 images 目录，返回完整路径"""
    ensure_dirs()
    path = image_path(filename)
    try:
        pil_image.save(path)
        return path
    except Exception as e:
        print(f"⚠️ 保存自定义操作截图失败：{e}")
        return None


def next_image_name():
    """生成下一个步骤图片文件名 step_1.png / step_2.png ..."""
    ensure_dirs()
    existing = {f for f in os.listdir(CUSTOM_OPS_IMAGES) if f.lower().endswith(".png")}
    n = 1
    while f"step_{n}.png" in existing:
        n += 1
    return f"step_{n}.png"


def _load_runs():
    """加载每个账号的自定义操作运行记录 {account: [时间戳, ...]}"""
    if not os.path.exists(RUNS_JSON):
        return {}
    try:
        with open(RUNS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_runs(data):
    """保存运行记录（原子写入）"""
    try:
        ensure_dirs()
        tmp = RUNS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RUNS_JSON)
    except Exception:
        pass


def should_skip_by_frequency(account_name, max_runs, days):
    """检查账号是否达到自定义操作频率上限（每 days 天最多 max_runs 次）。
    max_runs<=0 表示不限。返回 True=应跳过"""
    if max_runs <= 0 or days <= 0:
        return False
    data = _load_runs()
    runs = data.get(account_name, []) or []
    now = time.time()
    cutoff = now - days * 86400
    recent = [t for t in runs if t >= cutoff]
    return len(recent) >= max_runs


def record_account_run(account_name):
    """记录一次自定义操作运行（当前时间戳）"""
    data = _load_runs()
    runs = data.get(account_name, []) or []
    runs.append(time.time())
    # 只保留最近 90 天记录，避免无限增长
    cutoff = time.time() - 90 * 86400
    data[account_name] = [t for t in runs if t >= cutoff]
    _save_runs(data)


def _apply_jitter(x, y, max_px):
    """坐标点击的拟人抖动：圆内随机偏移 ≤max_px"""
    import math
    import random
    if max_px <= 0:
        return x, y
    angle = random.uniform(0, 2 * math.pi)
    dist = random.uniform(0, max_px)
    return int(x + dist * math.cos(angle)), int(y + dist * math.sin(angle))


def _probe_image(img_path, confidence=0.7, timeout=3, stop_event=None):
    """只探测图片是否存在（不点击），返回 True/False"""
    resolved = config.resolve_template_path(img_path)
    template = utils._imread_unicode(resolved)
    if template is None:
        return False
    start = time.time()
    while time.time() - start < timeout:
        if stop_event and stop_event.is_set():
            return False
        gray = utils._screenshot_gray()
        if gray is None:
            time.sleep(0.3)
            continue
        matched, _val, _loc, (_h, _w) = utils._match_template_multiscale(gray, template, confidence)
        if matched:
            return True
        time.sleep(0.3)
    return False


def _probe_ocr(text, confidence=0.6, timeout=3, stop_event=None):
    """只探测指定文字是否出现（不点击），返回 True/False"""
    start = time.time()
    while time.time() - start < timeout:
        if stop_event and stop_event.is_set():
            return False
        results = utils.ocr_recognize(region=None)
        for t, conf, _box in (results or []):
            if text in str(t) and conf >= confidence:
                return True
        time.sleep(0.3)
    return False


def run_custom_ops(app, account_name, stop_event=None):
    """执行自定义操作序列（主流程完成后、关闭游戏前调用）
    支持步骤类型：image找图 / coordinate坐标 / ocr文字 / keyboard键盘 /
    multi_image多图 / drag拖拽 / scroll滚轮 / condition条件跳转 / jump跳转
    返回 True=全部完成，False=中途中止
    """
    if stop_event is None:
        stop_event = app._stop_event
    ops = load_ops()
    if not ops:
        return True

    # 拟人抖动：自定义操作窗口「点击受随机偏移影响」开关（复用全局 click_jitter_max）
    settings = getattr(app, 'settings', None) or {}
    jitter_enabled = bool(settings.get("custom_ops_jitter", False))
    if jitter_enabled:
        jitter_max = int(settings.get("click_jitter_max", 5))
        utils.set_click_jitter(True, jitter_max)

    total = len(ops)
    print(f"🎯 账号 {account_name} 开始执行自定义操作（共 {total} 步）...")
    idx = 1
    visited = 0   # 跳转死循环保护
    try:
        while idx <= total:
            if stop_event.is_set():
                print("⏹ 自定义操作被用户停止")
                return False
            visited += 1
            if visited > 10000:
                print("⚠️ 检测到可能死循环（跳转次数过多），已中止")
                return False

            op = ops[idx - 1]
            name = op.get("name", f"步骤{idx}")
            pause = float(op.get("pause_after", 0.5))
            op_type = op.get("type", "image")

            if op_type == "jump":
                target = max(1, min(int(op.get("jump_to", idx + 1)), total))
                print(f"  [{idx}/{total}] 跳转到步骤 {target}")
                idx = target
                continue

            if op_type == "condition":
                # 条件跳转：找图/OCR 探测，满足则跳转到目标步骤
                jump_to = max(1, min(int(op.get("jump_to", idx + 1)), total))
                satisfied = _eval_condition(op, stop_event)
                if satisfied:
                    print(f"  [{idx}/{total}] 条件「{name}」满足，跳转到步骤 {jump_to}")
                    idx = jump_to
                else:
                    print(f"  [{idx}/{total}] 条件「{name}」不满足，继续下一步")
                    idx += 1
                continue

            # ----- 普通步骤 -----
            if op_type == "coordinate":
                x = int(op.get("x", 0))
                y = int(op.get("y", 0))
                if jitter_enabled:
                    x, y = _apply_jitter(x, y, jitter_max)
                print(f"  [{idx}/{total}] 坐标点击 ({x}, {y})...")
                utils.smooth_move_to(x, y)
                time.sleep(0.05)
                import pyautogui
                pyautogui.click()
                print(f"    ✅ 已点击坐标 ({x}, {y})")
            elif op_type == "ocr":
                text = op.get("text", "")
                if not text:
                    print(f"  [{idx}/{total}] ⚠️ 步骤「{name}」未配置要识别的文字，中止该账号自定义操作")
                    return False
                ocr_conf = float(op.get("confidence", 0.6))
                ocr_timeout = float(op.get("timeout", 5))
                region = op.get("region") or None
                print(f"  [{idx}/{total}] OCR查找「{text}」...")
                found = utils.ocr_find_and_click(text, region=region,
                                                 timeout=ocr_timeout, confidence=ocr_conf)
                if not found:
                    print(f"    ❌ 未找到文字「{text}」，中止该账号自定义操作，跳到下一个账号")
                    return False
                print(f"    ✅ 已点击「{text}」")
            elif op_type == "keyboard":
                keys = op.get("keys", "")
                mode = op.get("key_mode", "key")
                if not keys:
                    print(f"  [{idx}/{total}] ⚠️ 步骤「{name}」未配置按键内容，中止该账号自定义操作")
                    return False
                print(f"  [{idx}/{total}] 键盘输入「{keys}」...")
                if mode == "text":
                    import driver_keyboard
                    driver_keyboard.send_string(keys)
                else:
                    import pyautogui
                    keys_lower = keys.strip().lower()
                    if "+" in keys_lower:
                        pyautogui.hotkey(*[p.strip() for p in keys_lower.split("+") if p.strip()])
                    else:
                        pyautogui.press(keys_lower)
                print(f"    ✅ 已输入「{keys}」")
            elif op_type == "multi_image":
                images = op.get("images", []) or []
                if not images:
                    print(f"  [{idx}/{total}] ⚠️ 步骤「{name}」未配置图片，中止该账号自定义操作")
                    return False
                confidence = float(op.get("confidence", 0.7))
                timeout = float(op.get("timeout", 2))
                found = False
                for img_name in images:
                    img = image_path(img_name)
                    if not os.path.exists(img):
                        print(f"    ⚠️ 图片不存在: {img_name}")
                        continue
                    print(f"  [{idx}/{total}] 尝试「{img_name}」...")
                    if utils.find_and_click(img, timeout=timeout, confidence=confidence):
                        print(f"    ✅ 已点击「{img_name}」")
                        found = True
                        break
                if not found:
                    print(f"    ❌ 所有图片都未找到，中止该账号自定义操作")
                    return False
            elif op_type == "drag":
                x1, y1 = int(op.get("x1", 0)), int(op.get("y1", 0))
                x2, y2 = int(op.get("x2", 0)), int(op.get("y2", 0))
                duration = float(op.get("duration", 0.5))
                import pyautogui
                print(f"  [{idx}/{total}] 拖拽 ({x1},{y1}) → ({x2},{y2})...")
                utils.smooth_move_to(x1, y1)
                time.sleep(0.05)
                pyautogui.mouseDown()
                time.sleep(0.05)
                utils.smooth_move_to(x2, y2, duration=duration)
                pyautogui.mouseUp()
                print(f"    ✅ 拖拽完成")
            elif op_type == "scroll":
                amount = int(op.get("scroll_amount", 3))
                import pyautogui
                print(f"  [{idx}/{total}] 滚轮 {amount} 格...")
                pyautogui.scroll(amount)
                print(f"    ✅ 滚轮完成")
            elif op_type == "screenshot":
                # 截图保存：保存到 <全局目录>/<当天日期>/<账号名>_<时间>.png
                base_dir = (settings.get("custom_ops_screenshot_dir", "") or "").strip()
                if not base_dir:
                    print(f"  [{idx}/{total}] ⚠️ 未设置截图保存目录（在自定义操作设置中配置），跳过")
                else:
                    try:
                        import pyautogui
                        date_dir = time.strftime("%Y-%m-%d")
                        save_dir = os.path.join(base_dir, date_dir)
                        os.makedirs(save_dir, exist_ok=True)
                        shot = pyautogui.screenshot()
                        safe_name = "".join(c for c in account_name if c not in '\\/:*?"<>|').strip() or "账号"
                        fname = f"{safe_name}_{time.strftime('%H%M%S')}.png"
                        path = os.path.join(save_dir, fname)
                        shot.save(path)
                        print(f"  [{idx}/{total}] 已截图保存: {path}")
                    except Exception as e:
                        print(f"    ⚠️ 截图保存失败: {e}")
            else:
                # 找图点击（默认）
                img = image_path(op.get("image", ""))
                confidence = float(op.get("confidence", 0.7))
                timeout = float(op.get("timeout", 5))
                if not os.path.exists(img):
                    print(f"  [{idx}/{total}] ⚠️ 步骤「{name}」图片不存在，中止该账号自定义操作")
                    return False
                print(f"  [{idx}/{total}] 查找「{name}」...")
                found = utils.find_and_click(img, timeout=timeout, confidence=confidence)
                if not found:
                    print(f"    ❌ 未找到「{name}」，中止该账号自定义操作，跳到下一个账号")
                    return False
                print(f"    ✅ 已点击「{name}」")

            if pause > 0:
                time.sleep(pause)
            idx += 1
    finally:
        if jitter_enabled:
            utils.set_click_jitter(False)

    print(f"🎉 账号 {account_name} 自定义操作执行完毕")
    return True


def _eval_condition(op, stop_event):
    """评估条件步骤：找图或 OCR 探测目标是否存在，返回 True/False"""
    cond_type = op.get("cond_type", "image")
    timeout = float(op.get("timeout", 3))
    if cond_type == "ocr":
        text = op.get("text", "")
        if not text:
            return False
        confidence = float(op.get("confidence", 0.6))
        print(f"    🔍 探测文字「{text}」...")
        return _probe_ocr(text, confidence, timeout, stop_event)
    # 找图探测
    img = image_path(op.get("image", ""))
    confidence = float(op.get("confidence", 0.7))
    if not os.path.exists(img):
        print(f"    ⚠️ 条件图片不存在: {img}")
        return False
    print(f"    🔍 探测图片...")
    return _probe_image(img, confidence, timeout, stop_event)


def run_custom_ops_for_test(app, stop_event):
    """实验功能窗口内的测试运行：使用与自动执行相同的逻辑，仅打印日志"""
    return run_custom_ops(app, "测试", stop_event=stop_event)
