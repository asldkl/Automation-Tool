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
import os
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
# 429/5xx 重试退避基数（秒）：第 n 次重试等待 n×该值；免费模型高峰期限流常见
RETRY_BACKOFF_SECONDS = 5.0
# JPEG 压缩：从 90 起逐级降到 55（超过 4MB 降一档，与 LCA 同思路）
JPEG_QUALITIES = (90, 85, 80, 75, 70, 65, 60, 55)
MAX_IMAGE_BYTES = 4 * 1024 * 1024

# 供应商预设：切换时自动回填 base_url / model；CUSTOM 只用用户手填的值
CUSTOM_PROVIDER = "自定义"
PROVIDER_PRESETS = [
    {"name": "智谱GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4.6v-flash", "note": "glm-4.6v-flash 免费"},
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

# 已下线的旧模型 → 当前替代（旧配置调用时自动升级，避免静默失败）
RETIRED_MODELS = {
    "glm-4v-flash": "glm-4.6v-flash",  # 初代 glm-4v-flash 已下线
}


def normalize_model(model):
    """旧模型名自动映射到当前替代（其余原样返回）"""
    m = str(model or "").strip()
    return RETIRED_MODELS.get(m.lower(), m)


def get_preset(provider_name):
    """按预设名返回 {"base_url","model"}；自定义/未知返回空值"""
    for p in PROVIDER_PRESETS:
        if p["name"] == provider_name:
            return {"base_url": p["base_url"], "model": p["model"]}
    return {"base_url": "", "model": ""}


def is_configured(settings, require_enabled=True):
    """是否配置齐全；require_enabled=False 时只校验供应商配置（供测试按钮绕过启用开关）"""
    if require_enabled and not settings.get("ai_visual_captcha_enabled", False):
        return False
    return all(str(settings.get(k, "") or "").strip()
               for k in ("ai_visual_captcha_base_url",
                         "ai_visual_captcha_api_key",
                         "ai_visual_captcha_model"))


def get_capture_region(settings):
    """读取验证码识别区域配置（滑块YOLO与AI视觉共用）。
    启用且区域有效返回 (x, y, w, h)；否则返回 None（全屏）"""
    if not settings.get("captcha_region_enabled", False):
        return None
    region = settings.get("captcha_region", [0, 0, 0, 0])
    try:
        x, y, w, h = [int(v) for v in region]
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def _build_prompt(width, height):
    return (
        "你是登录验证码识别助手。这是电脑屏幕截图，"
        f"分辨率 {width}x{height} 像素。判断图中是否出现验证码（点选/图片验证）。\n"
        '只输出严格JSON，不要输出任何其他文字：\n'
        '{"captcha": true/false, "type": "click"/"slider"/"none", '
        '"targets": [{"text": "要点击的目标文字或描述", "bbox": [x1,y1,x2,y2], "point": [x,y]}]}\n'
        "规则：\n"
        "- 点选类验证码：type=click，按题目要求的点击顺序排列 targets，每个 target 必须给 point（目标中心坐标）；可另给 bbox 作参考，但程序以 point 为准\n"
        "- 坐标必须是【像素】，且【相对本张图片的左上角】（左上角为 0,0）；不要给归一化(0-1/0-1000)坐标\n"
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
    """从 target 提取坐标（单位：像素，相对"发送给模型的这张图"的左上角）。
    直接取原始数值，不做任何归一化/缩放换算；调用方再统一加上识别区域左上角偏移。
    优先 point（模型自报的目标点），无 point 才用 bbox 中心。返回 (x, y) 或 None"""
    if not isinstance(target, dict):
        return None

    def _px(v):
        try:
            return int(round(float(str(v).strip())))
        except (TypeError, ValueError):
            return None

    point = target.get("point")
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        x, y = _px(point[0]), _px(point[1])
        if x is not None and y is not None:
            return (x, y)
    bbox = target.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        x1, y1, x2, y2 = _px(bbox[0]), _px(bbox[1]), _px(bbox[2]), _px(bbox[3])
        if None not in (x1, y1, x2, y2) and x2 >= x1 and y2 >= y1:
            return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    # 兜底：x1/y1/x2/y2 平铺字段
    xs = [_px(target.get(k)) for k in ("x1", "x2")]
    ys = [_px(target.get(k)) for k in ("y1", "y2")]
    if all(v is not None for v in xs + ys):
        return (int((xs[0] + xs[1]) / 2), int((ys[0] + ys[1]) / 2))
    xy = (_px(target.get("x")), _px(target.get("y")))
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


def _capture_screen_jpeg(region=None):
    """截图 → JPEG base64（超 4MB 逐级降质）。
    region 为 (x, y, w, h) 时只截该区域（验证码识别区域），返回 (b64, mime, w, h)"""
    import pyautogui
    if region:
        region = tuple(int(v) for v in region)
        shot = pyautogui.screenshot(region=region)
    else:
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


def _ask_model(base_url, api_key, model, image_b64, prompt, timeout=REQUEST_TIMEOUT_SECONDS,
               retries=3, backoff_seconds=None):
    """调用 OpenAI 兼容 /chat/completions（图像走 base64 data URL），返回文本内容。
    429 限流 / 5xx 服务器错误自动重试 retries 次（免费模型高峰期常见 429），退避等待"""
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
    wait_base = backoff_seconds if backoff_seconds is not None else RETRY_BACKOFF_SECONDS
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {str(api_key).strip()}",
        },
        method="POST",
    )
    last_exc = None
    for attempt in range(retries + 1):
        try:
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
        except urllib.error.HTTPError as e:
            # 429 限流 / 5xx：退避后重试；其他错误（401 密钥无效、400 参数错误等）直接抛出
            if e.code == 429 or 500 <= e.code < 600:
                last_exc = e
                if attempt < retries:
                    time.sleep(wait_base * (attempt + 1))
                    continue
            raise
    raise last_exc


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


def save_debug_annotation(region, points_screen, labels=None, raw_content="", settings=None):
    """把本次 AI 识别结果标注到当前屏幕截图上并保存到「日志目录/日期/图片/」（并尝试打开）。
    points_screen: 已换算到全屏的点击坐标 [(x,y),...]；region: 识别区域或 None。
    用于人工判断：是 AI 定位错，还是坐标换算错。返回保存路径或 None"""
    try:
        import datetime
        import pyautogui
        labels = labels or []
        shot = pyautogui.screenshot()
        try:
            arr = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        finally:
            try:
                shot.close()
            except Exception:
                pass
        # 取模型原始 targets（用于标注「AI 在框内识别到的位置」）
        raw_targets = []
        try:
            _data = _extract_json(raw_content) if raw_content else None
            if isinstance(_data, dict) and isinstance(_data.get("targets"), list):
                raw_targets = [t for t in _data["targets"] if isinstance(t, dict)]
        except Exception:
            raw_targets = []

        # 识别区域框（橙）
        if region:
            try:
                rx, ry, rw, rh = [int(v) for v in region]
                cv2.rectangle(arr, (rx, ry), (rx + rw, ry + rh), (0, 165, 255), 2)
                cv2.putText(arr, f"region [{rx},{ry},{rw},{rh}]", (rx, max(20, ry - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
            except Exception:
                pass

        # ① AI 在【标注框内】的原始位置（绿）：AI 坐标是相对"区域裁剪图"的，
        #    加上标注框左上角 (region.x, region.y) 才是它在全屏上的位置
        #    —— 绿圈若正好落在目标上 → AI 定位对（那红圈偏就是换算错）；绿圈偏 → AI 定位错
        _ox, _oy = (int(region[0]), int(region[1])) if region else (0, 0)
        for i, t in enumerate(raw_targets):
            _scale = _scale_factor(t.get("scale"))
            pt = t.get("point")
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    raw_x, raw_y = int(float(pt[0])), int(float(pt[1]))
                    gx, gy = raw_x + _ox, raw_y + _oy
                    cv2.circle(arr, (gx, gy), 16, (0, 200, 0), 3)
                    _tag = f"AI框内({raw_x},{raw_y})" + ("" if not _scale else f"[scale{_scale}]")
                    cv2.putText(arr, _tag, (gx + 20, gy + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
                except Exception:
                    pass
            bb = t.get("bbox")
            if isinstance(bb, (list, tuple)) and len(bb) >= 4:
                try:
                    cv2.rectangle(arr,
                                  (int(float(bb[0])) + _ox, int(float(bb[1])) + _oy),
                                  (int(float(bb[2])) + _ox, int(float(bb[3])) + _oy),
                                  (0, 200, 0), 1)
                except Exception:
                    pass

        # ② 换算后点击位置（红圈 + 十字）
        for i, pt in enumerate(points_screen or []):
            try:
                px, py = int(pt[0]), int(pt[1])
            except Exception:
                continue
            cv2.circle(arr, (px, py), 24, (0, 0, 255), 3)
            cv2.line(arr, (px - 34, py), (px + 34, py), (0, 0, 255), 2)
            cv2.line(arr, (px, py - 34), (px, py + 34), (0, 0, 255), 2)
            text = f"{labels[i] if i < len(labels) else ''}({px},{py})"
            cv2.putText(arr, text, (px + 28, py - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)

        # ③ 右上角"框内视图"：区域裁剪 + 框内原始(绿)/换算(红)位置，直接看 AI 在框内认到哪
        if region:
            try:
                rx, ry, rw, rh = [int(v) for v in region]
                crop = arr[ry:ry + rh, rx:rx + rw].copy()
                disp_w = min(420, max(200, rw))
                ratio = disp_w / max(1, rw)
                disp = cv2.resize(crop, (disp_w, max(1, int(rh * ratio))))
                hh, ww = disp.shape[:2]
                cv2.rectangle(disp, (0, 0), (ww - 1, hh - 1), (0, 165, 255), 2)
                cv2.putText(disp, "crop: green=AI raw(in box), red=converted", (6, 16),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
                for pt in (points_screen or []):
                    try:
                        cv2.circle(disp, (int((int(pt[0]) - rx) * ratio),
                                          int((int(pt[1]) - ry) * ratio)), 9, (0, 0, 255), 2)
                    except Exception:
                        pass
                for t in raw_targets:
                    _pt = t.get("point")
                    if isinstance(_pt, (list, tuple)) and len(_pt) >= 2:
                        try:
                            cv2.circle(disp, (int(float(_pt[0]) * ratio),
                                              int(float(_pt[1]) * ratio)), 7, (0, 200, 0), 2)
                        except Exception:
                            pass
                x0 = max(0, arr.shape[1] - ww - 10)
                arr[10:10 + hh, x0:x0 + ww] = disp
            except Exception:
                pass
        # 保存到「日志/截图保存目录/日期/图片/」（与日志同日期，图片独立子文件夹）
        base_dir = ""
        try:
            if settings:
                base_dir = (settings.get("log_save_path", "") or "").strip()
            if not base_dir:
                import config as _cfg
                base_dir = _cfg.APP_DATA_DIR
        except Exception:
            base_dir = ""
        try:
            out_dir = os.path.join(base_dir, utils.date_folder_name(), "图片")
        except Exception:
            out_dir = base_dir or "."
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            pass
        path = os.path.join(out_dir, "AI验证_" + datetime.datetime.now().strftime("%H%M%S") + ".png")
        cv2.imencode(".png", arr)[1].tofile(path)
        print(f"🖼️ 已保存 AI 位置标注图：{path}")
        if raw_content:
            print(f"🖼️ 模型原始回复：{str(raw_content)[:200]}")
        try:
            _rox, _roy = (int(region[0]), int(region[1])) if region else (0, 0)
            for i, t in enumerate(raw_targets):
                _p = t.get("point")
                _s = t.get("scale")
                _cv = points_screen[i] if (points_screen and i < len(points_screen)) else None
                _box = None
                try:
                    _box = (int(float(_p[0])) + _rox, int(float(_p[1])) + _roy)
                except Exception:
                    _box = None
                print(f"🖼️ 目标{i + 1}: AI原始 point={_p} scale={_s} → 框内屏幕={_box}(绿) → 换算点击={_cv}(红)")
        except Exception:
            pass
        try:
            os.startfile(path)   # 自动打开图片便于查看
        except Exception:
            pass
        return path
    except Exception as e:
        print(f"⚠️ 保存 AI 标注图失败：{e}")
        return None


def solve_captcha(app, stop_event=None, max_rounds=None, force=False, save_debug=False):
    """检测并处理屏幕上的点击式验证码（供登录流程/测试调用）。

    force=True 时跳过启用开关校验（设置窗口「仅测试AI」用，只需供应商配置完整）。

    返回 (ok, detail)：
      ok=True  = 屏幕无验证码（或已按顺序点击完成且复核通过）
      ok=False = 滑块（需手动）/ AI 不确定 / 轮次用尽仍在 / 调用异常
    """
    settings = getattr(app, "settings", None) or {}
    if not is_configured(settings, require_enabled=not force):
        return False, "AI视觉验证未启用或配置不完整"
    base_url = str(settings.get("ai_visual_captcha_base_url") or "").strip()
    api_key = str(settings.get("ai_visual_captcha_api_key") or "").strip()
    model = normalize_model(settings.get("ai_visual_captcha_model"))
    try:
        rounds = int(max_rounds or settings.get("ai_visual_captcha_max_rounds", 5) or 5)
    except (TypeError, ValueError):
        rounds = 5
    rounds = max(1, min(rounds, 10))
    # 识别区域（与滑块共用）：只截图该区域发给模型，识别到的坐标换算回全屏再点击
    region = get_capture_region(settings)
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
    if region:
        print(f"🤖 AI视觉验证：使用识别区域 {region}（坐标已自动换算全屏）")

    overlay_hidden = _hide_overlay()
    try:
        for round_index in range(1, rounds + 1):
            if stop_event is not None and stop_event.is_set():
                return False, "已停止"
            image_b64, mime, w, h = _capture_screen_jpeg(region)
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
            # 诊断日志：核对换算（模型原始回复 / 图像尺寸 / 区域偏移 / 解析出的坐标）
            try:
                print(f"🤖 AI原始回复：{str(content)[:300]}")
                print(f"🤖 图像 {w}x{h}，区域偏移 ({offset_x},{offset_y})，解析坐标：{parsed.get('points')}")
            except Exception:
                pass
            status = parsed["status"]
            if status == "none":
                print("🤖 AI视觉验证：未检测到验证码")
                if save_debug:
                    save_debug_annotation(region, [], [], content, settings=settings)
                return True, f"第{round_index}轮未检测到验证码"
            if status == "slider":
                if save_debug:
                    save_debug_annotation(region, [], [], content, settings=settings)
                # 滑块验证：委托本地 YOLO 模块处理（未启用且非 force 则提示手动）
                slider_module = None
                try:
                    import slider_captcha as slider_module
                except Exception:
                    pass
                if slider_module is not None and (slider_module.is_enabled(settings) or force):
                    print("🤖 AI视觉验证：检测到滑块验证，转交滑块YOLO模块处理...")
                    found, solved, slider_detail = slider_module.solve_slider_yolo(
                        app, stop_event=stop_event, manage_overlay=False, force=force)
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
                if save_debug:
                    save_debug_annotation(region, [], [], content, settings=settings)
                return False, "模型未返回有效坐标"
            # click：按顺序拟人点击（截图带区域时坐标需加区域偏移换算回全屏）
            labels = parsed["labels"]
            if save_debug:
                save_debug_annotation(
                    region,
                    [(int(px) + offset_x, int(py) + offset_y) for (px, py) in parsed["points"]],
                    labels, content, settings=settings)
            for i, (x, y) in enumerate(parsed["points"]):
                if stop_event is not None and stop_event.is_set():
                    return False, "已停止"
                screen_x = x + offset_x
                screen_y = y + offset_y
                label = labels[i] if i < len(labels) and labels[i] else f"目标{i + 1}"
                print(f"🤖 AI视觉验证：点击「{label}」（{screen_x},{screen_y}）")
                try:
                    utils.smooth_move_to(screen_x, screen_y)
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
    """设置窗口「仅测试AI」按钮：对当前屏幕跑一次完整检测处理（无验证码时不会点击任何东西）。
    不要求启用开关，只需供应商配置完整"""
    import threading
    stop_event = getattr(app, "_stop_event", None)

    def _run():
        print("🤖 AI视觉验证测试开始（3秒后截图，请把测试画面摆在前台）...")
        time.sleep(3)
        ok, detail = solve_captcha(app, stop_event=stop_event, force=True, save_debug=True)
        print(f"{'✅' if ok else '❌'} AI视觉验证测试结束：{detail}")
        print("🖼️ 本次已在 %APPDATA%\\DeltaAutoTool\\captcha_debug\\ 生成带标注的截图（红圈=AI定位点）")

    threading.Thread(target=_run, daemon=True).start()
