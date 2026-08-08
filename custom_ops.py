"""
自定义操作模块
用户在主流程完成后（游戏回到主界面），自行配置"找图→单击"步骤序列，
程序在每个账号的主流程结束后、关闭游戏前自动按顺序执行。

数据结构（每个步骤）：
    {
        "name": "打开仓库",          # 步骤名称（显示用）
        "image": "step_1.png",       # 图片文件名（存放在 images 目录）
        "confidence": 0.7,           # 找图置信度
        "timeout": 5,                # 找图超时（秒）
        "pause_after": 0.5,          # 点击后停顿（秒）
    }
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


def run_custom_ops(app, account_name, stop_event=None):
    """执行自定义操作序列（主流程完成后、关闭游戏前调用）
    逐步骤：找图→单击→停顿；某步找不到图则中止当前账号的自定义操作
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

    print(f"🎯 账号 {account_name} 开始执行自定义操作（共 {len(ops)} 步）...")
    try:
        for idx, op in enumerate(ops, 1):
            if stop_event.is_set():
                print("⏹ 自定义操作被用户停止")
                return False
            img = image_path(op.get("image", ""))
            name = op.get("name", f"步骤{idx}")
            confidence = float(op.get("confidence", 0.7))
            timeout = float(op.get("timeout", 5))
            pause = float(op.get("pause_after", 0.5))

            if not os.path.exists(img):
                print(f"  [{idx}/{len(ops)}] ⚠️ 步骤「{name}」图片不存在，中止该账号自定义操作")
                return False

            print(f"  [{idx}/{len(ops)}] 查找「{name}」...")
            found = utils.find_and_click(img, timeout=timeout, confidence=confidence)
            if not found:
                print(f"    ❌ 未找到「{name}」，中止该账号自定义操作，跳到下一个账号")
                return False
            print(f"    ✅ 已点击「{name}」")
            if pause > 0:
                time.sleep(pause)
    finally:
        if jitter_enabled:
            utils.set_click_jitter(False)

    print(f"🎉 账号 {account_name} 自定义操作执行完毕")
    return True


def run_custom_ops_for_test(app, stop_event):
    """实验功能窗口内的测试运行：使用与自动执行相同的逻辑，仅打印日志"""
    return run_custom_ops(app, "测试", stop_event=stop_event)
