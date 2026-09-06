# -*- coding: utf-8 -*-
"""
AI 视觉验证码处理（WeGame 登录点击式图片验证）

精简自 LCA 的「视觉 Agent」思路：截图 → 多模态模型定位 → 本地点击 → 复核。
- 仅处理「点击式」验证（请依次点击/点选文字图标）；检测到滑块时提示手动处理
- 默认关闭：需在设置中启用并配置 AI 供应商后才生效（enable_ai_visual_captcha）
- 供应商统一走 OpenAI 兼容 /chat/completions，图片用 base64 data URL
  （智谱 / 阿里百炼 / 月之暗面 / 豆包方舟 / 硅基流动 等国内接口格式一致）
"""
import base64
import json
import random
import re
import time
import urllib.request
import urllib.error

import cv2
import numpy as np

import utils

# 单次请求超时（秒）
REQUEST_TIMEOUT_SECONDS = 60.0
# 复核轮次间等待（点击后给页面反应时间）
RECHECK_WAIT_SECONDS = 2.5
# JPEG 压缩：从 90 起逐级降到 55（超过 4MB 降一档，与 LCA 同思路）
JPEG_QUALITIES = (90, 85, 80, 75, 70, 65, 60, 55)
MAX_IMAGE_BYTES = 4 * 1024 * 1024

# 供应商预设：切换时自动回填 base_url / model；CUSTOM 只用用户手填的值
CUSTOM_PROVIDER = "自定义"
PROVIDER_PRESETS = [
    {"name": "智谱GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4v-flash", "note": "glm-4v-flash 免费"},
    {"name": "阿里百炼", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": "qwen-vl-plus", "note": "qwen-vl-plus 价格低"},
    {"name": "月之暗面Kimi", "base_url": "https://api.moonshot.cn/v1",
     "model": "moonshot-v1-8k-vision-preview", "note": "视觉模型按量计费"},
    {"name": "豆包（火山方舟）", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "model": "doubao-1.5-vision-lite", "note": "模型名或接入点ID"},
    {"name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1",
     "model": "Qwen/Qwen2.5-VL-7B-Instruct", "note": "多款开源视觉模型"},
    {"name": CUSTOM_PROVIDER, "base_url": "", "model": "", "note": "手填地址与模型"},
]
PROVIDER_NAMES = [p["name"] for p in PROVIDER_PRESETS]


def get_preset(provider_name):
    """按预设名返回 {"base_url","model"}；自定义/未知返回空值"""
    for p in PROVIDER_PRESETS:
        if p["name"] == provider_name:
            return {"base_url": p["base_url"], "model": p["model"]}
    return {"base_url": "", "model": ""}


def is_configured(settings):
    """是否已启用且配置齐全（未齐全时登录流程不会触发）"""
    if not settings.get("ai_visual_captcha_enabled", False):
        return False
    return all(str(settings.get(k, "") or "").strip()
               for k in ("ai_visual_captcha_base_url",
                         "ai_visual_captcha_api_key",
                         "ai_visual_captcha_model"))


def _build_prompt(width, height):
    return (
        "你是登录验证码识别助手。这是电脑屏幕截图，"
        f"分辨率 {width}x{height} 像素。判断图中是否出现验证码（点选/图片验证）。\n"
        '只输出严格JSON，不要输出任何其他文字：\n'
        '{"captcha": true/false, "type": "click"/"slider"/"none", '
        '"targets": [{"text": "要点击的目标文字或描述", "bbox": [x1,y1,x2,y2], "point": [x,y]}]}\n'
        "规则：\n"
        "- 点选类验证码：type=click，按题目要求的点击顺序排列 targets，每个 target 优先给 bbox，给不准再给 point\n"
        "- 坐标用像素；若你只能给归一化坐标（0-1000 / 0-1024 / 0-1），在该 target 里加 \"scale\": 1000 / 1024 / 1\n"
        "- 滑块拼图验证：输出 {\"captcha\": true, \"type\": \"slider\", \"targets\": []}\n"
        "- 没有验证码：输出 {\"captcha\": false, \"type\": \"none\", \"targets\": []}\n"
        "- 找不准目标就不要给坐标，宁可输出找不到"
    )


def _extract_json(text):
    """从模型回复中提取第一个 JSON 对象（容忍 ```json 包裹、前后缀文字）"""
    if not text:
        return None
    cleaned = re.sub(r"```(?:json)?", "", str(text)).strip()
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(cleaned[start:i + 1])
                except Exception:
                    return None
    return None


def _to_number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _scale_factor(scale_value):
    """归一化坐标系数：1000 / 1024 / 1（0-1 浮点）；像素坐标返回 0"""
    if scale_value is None:
        return 0
    s = _to_number(scale_value)
    if s is None:
        text = str(scale_value).strip().lower()
        if text in ("pixel", "px", "像素"):
            return 0
        return 0
    if s in (1000, 1024, 1):
        return s
    return 0


def _to_pixel_coord(value, max_size, scale):
    """单个坐标转像素：scale=1000/1024 按比例放大，scale=1（0-1 浮点）乘边长，0=原样像素"""
    v = _to_number(value)
    if v is None:
        return None
    if scale == 1000:
        return int(round(v / 1000.0 * max_size))
    if scale == 1024:
        return int(round(v / 1024.0 * max_size))
    if scale == 1:
        # 0-1 浮点：>1 视为已是像素
        return int(round(v * max_size)) if 0 <= v <= 1 else int(round(v))
    return int(round(v))


def _target_center(target, screen_w, screen_h):
    """从 target 提取像素中心点：bbox 中心优先，point 兜底；返回 (x, y) 或 None"""
    if not isinstance(target, dict):
        return None
    scale = _scale_factor(target.get("scale"))
    bbox = target.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        x1 = _to_pixel_coord(bbox[0], screen_w, scale)
        y1 = _to_pixel_coord(bbox[1], screen_h, scale)
        x2 = _to_pixel_coord(bbox[2], screen_w, scale)
        y2 = _to_pixel_coord(bbox[3], screen_h, scale)
        if None not in (x1, y1, x2, y2) and x2 >= x1 and y2 >= y1:
            return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    point = target.get("point")
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        x = _to_pixel_coord(point[0], screen_w, scale)
        y = _to_pixel_coord(point[1], screen_h, scale)
        if None not in (x, y):
            return (x, y)
    # 兜底：x1/y1/x2/y2 平铺字段
    xs = [_to_pixel_coord(target.get(k), screen_w, scale) for k in ("x1", "x2")]
    ys = [_to_pixel_coord(target.get(k), screen_h, scale) for k in ("y1", "y2")]
    if all(v is not None for v in xs + ys):
        return (int((xs[0] + xs[1]) / 2), int((ys[0] + ys[1]) / 2))
    xy = (_to_pixel_coord(target.get("x"), screen_w, scale),
          _to_pixel_coord(target.get("y"), screen_h, scale))
    if None not in xy:
        return xy
    return None


def parse_model_response(text, screen_w, screen_h):
    """解析模型回复 → {"status": "click"/"slider"/"none"/"invalid", "points": [(x,y),...], "labels": [...]}"""
    data = _extract_json(text)
    if not isinstance(data, dict):
        return {"status": "invalid", "points": [], "labels": []}
    captcha = bool(data.get("captcha"))
    ctype = str(data.get("type") or "").strip().lower()
    targets = data.get("targets")
    if not isinstance(targets, list):
        targets = []
    if not captcha or ctype in ("none", "no", "false"):
        return {"status": "none", "points": [], "labels": []}
    if ctype in ("slider", "slide", "drag", "puzzle"):
        return {"status": "slider", "points": [], "labels": []}
    points = []
    labels = []
    for t in targets:
        center = _target_center(t, screen_w, screen_h)
        if center is None:
            continue
        points.append(center)
        label = ""
        if isinstance(t, dict):
            label = str(t.get("text") or "").strip()
        labels.append(label)
    if not points:
        return {"status": "invalid", "points": [], "labels": []}
    return {"status": "click", "points": points, "labels": labels}


def _capture_screen_jpeg():
    """彩色全屏截图 → JPEG base64（超 4MB 逐级降质），返回 (b64, "image/jpeg", w, h) 或 (None, None, 0, 0)"""
    import pyautogui
    shot = pyautogui.screenshot()
    try:
        arr = np.array(shot)
    finally:
        try:
            shot.close()
        except Exception:
            pass
    h, w = arr.shape[:2]
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    for quality in JPEG_QUALITIES:
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            continue
        payload = buf.tobytes()
        if len(payload) <= MAX_IMAGE_BYTES:
            return base64.b64encode(payload).decode("ascii"), "image/jpeg", w, h
    return None, None, 0, 0


def _ask_model(base_url, api_key, model, image_b64, prompt, timeout=REQUEST_TIMEOUT_SECONDS):
    """调用 OpenAI 兼容 /chat/completions（图像走 base64 data URL），返回文本内容"""
    url = str(base_url).strip().rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{image_b64}",
                                   "detail": "high"}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {str(api_key).strip()}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"模型返回无内容：{str(data)[:200]}")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and str(item.get("type") or "") in ("text", "output_text"):
                parts.append(str(item.get("text") or ""))
        content = "\n".join(p for p in parts if p)
    return str(content or "").strip()


def _hide_overlay():
    """隐藏日志遮罩（防入镜）；返回是否需要恢复"""
    try:
        import gui_app
        if getattr(gui_app, "_qt_overlay", None) is not None:
            gui_app.hide_log_overlay()
            return True
    except Exception:
        pass
    return False


def _show_overlay(need_restore):
    if need_restore:
        try:
            import gui_app
            gui_app.show_log_overlay()
        except Exception:
            pass


def solve_captcha(app, stop_event=None, max_rounds=None):
    """检测并处理屏幕上的点击式验证码（供登录流程/测试调用）。

    返回 (ok, detail)：
      ok=True  = 屏幕无验证码（或已按顺序点击完成且复核通过）
      ok=False = 滑块（需手动）/ AI 不确定 / 轮次用尽仍在 / 调用异常
    """
    settings = getattr(app, "settings", None) or {}
    if not is_configured(settings):
        return False, "AI视觉验证未启用或配置不完整"
    base_url = str(settings.get("ai_visual_captcha_base_url") or "").strip()
    api_key = str(settings.get("ai_visual_captcha_api_key") or "").strip()
    model = str(settings.get("ai_visual_captcha_model") or "").strip()
    try:
        rounds = int(max_rounds or settings.get("ai_visual_captcha_max_rounds", 5) or 5)
    except (TypeError, ValueError):
        rounds = 5
    rounds = max(1, min(rounds, 10))

    overlay_hidden = _hide_overlay()
    try:
        for round_index in range(1, rounds + 1):
            if stop_event is not None and stop_event.is_set():
                return False, "已停止"
            image_b64, mime, w, h = _capture_screen_jpeg()
            if not image_b64:
                return False, "截图失败"
            print(f"🤖 AI视觉验证 第{round_index}/{rounds}轮：请求 {model} 识别验证码...")
            try:
                content = _ask_model(base_url, api_key, model, image_b64, _build_prompt(w, h))
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    pass
                return False, f"AI接口HTTP错误 {e.code}：{body or e.reason}"
            except Exception as e:
                return False, f"AI接口调用失败：{e}"
            parsed = parse_model_response(content, w, h)
            status = parsed["status"]
            if status == "none":
                print("🤖 AI视觉验证：未检测到验证码")
                return True, f"第{round_index}轮未检测到验证码"
            if status == "slider":
                # 滑块验证：委托本地 YOLO 模块处理（未启用则提示手动）
                slider_module = None
                try:
                    import slider_captcha as slider_module
                except Exception:
                    pass
                if slider_module is not None and slider_module.is_enabled(settings):
                    print("🤖 AI视觉验证：检测到滑块验证，转交滑块YOLO模块处理...")
                    found, solved, slider_detail = slider_module.solve_slider_yolo(
                        app, stop_event=stop_event, manage_overlay=False)
                    if found and solved:
                        # 继续下一轮 AI 复核（此时验证码应已消失）
                        if round_index < rounds:
                            time.sleep(RECHECK_WAIT_SECONDS)
                        continue
                    return False, f"滑块YOLO处理未通过：{slider_detail}"
                print("🤖 AI视觉验证：检测到滑块拼图验证，请在游戏内手动完成（滑块YOLO未启用）")
                return False, "检测到滑块验证，需手动处理"
            if status == "invalid":
                print(f"⚠️ AI视觉验证：模型未返回有效坐标（回复：{content[:120]}）")
                return False, "模型未返回有效坐标"
            # click：按顺序拟人点击
            labels = parsed["labels"]
            for i, (x, y) in enumerate(parsed["points"]):
                if stop_event is not None and stop_event.is_set():
                    return False, "已停止"
                label = labels[i] if i < len(labels) and labels[i] else f"目标{i + 1}"
                print(f"🤖 AI视觉验证：点击「{label}」（{x},{y}）")
                try:
                    utils.smooth_move_to(x, y)
                    utils.human_click_delay()
                    import pyautogui
                    pyautogui.click()
                except Exception as e:
                    return False, f"点击失败：{e}"
                time.sleep(random.uniform(0.6, 1.2))
            if round_index < rounds:
                time.sleep(RECHECK_WAIT_SECONDS)
        return False, f"{rounds}轮处理后仍未确认验证码消失"
    finally:
        _show_overlay(overlay_hidden)


def test_captcha(app):
    """设置窗口「测试」按钮：对当前屏幕跑一次完整检测处理（无验证码时不会点击任何东西）"""
    import threading
    stop_event = getattr(app, "_stop_event", None)

    def _run():
        print("🤖 AI视觉验证测试开始（3秒后截图，请把测试画面摆在前台）...")
        time.sleep(3)
        ok, detail = solve_captcha(app, stop_event=stop_event)
        print(f"{'✅' if ok else '❌'} AI视觉验证测试结束：{detail}")

    threading.Thread(target=_run, daemon=True).start()
