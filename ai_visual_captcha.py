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

# 模型返回坐标的空间：
#   normalized = 0-1000 归一化（国内视觉接口通行约定，glm-4.6v / doubao / qwen-vl 等均如此，
#                提示词里写「像素」也无效，实测返回的仍是 0-1000）
#   pixel      = 相对本图左上角的像素
#   auto       = 按返回值的量级自动判定（见 _detect_coord_space）
COORD_SPACE_AUTO = "auto"
COORD_SPACE_NORMALIZED = "normalized"
COORD_SPACE_PIXEL = "pixel"
COORD_SPACE_LABELS = {
    COORD_SPACE_AUTO: "自动判定（推荐）",
    COORD_SPACE_NORMALIZED: "归一化 0-1000",
    COORD_SPACE_PIXEL: "像素",
}
COORD_SPACE_BY_LABEL = {v: k for k, v in COORD_SPACE_LABELS.items()}

# 单轮最多允许点击多少个目标：正常验证码远小于此值
#（文字点选一般 2~6 个字，图片选择一般 1~4 张图）。
# 超过说明模型判错了题型——典型是把「选出所有符合描述的图片」当成「把图里的字逐个点一遍」，
# 一口气给出十几个坐标。这种情况下乱点会把整页文字都点一遍，宁可判失败也不点。
MAX_CLICK_TARGETS = 10

# 供应商预设：切换时自动回填 base_url / model；CUSTOM 只用用户手填的值
CUSTOM_PROVIDER = "自定义"
PROVIDER_PRESETS = [
    {"name": "智谱GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "model": "glm-4.6v-flash", "note": "glm-4.6v-flash 免费"},
    {"name": "DeepSeek", "base_url": "https://api.deepseek.com",
     "model": "deepseek-flash", "note": "V4.1 Flash 原生多模态（若报模型不存在改填 deepseek-v4-flash）"},
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


def _provider_store_path():
    import config as _cfg
    return os.path.join(_cfg.APP_DATA_DIR, "ai_provider_config.json")


def load_provider_configs():
    """读取「每个供应商各自记住的配置」{供应商名: {api_key, base_url, model}}。
    存独立文件（不放 settings.json）：settings 会被启动快照整体覆盖，独立文件更稳。损坏返回空"""
    try:
        with open(_provider_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_provider_config(provider):
    """取某供应商上次用过的配置（没存过返回 {}）"""
    item = load_provider_configs().get(str(provider or "").strip())
    return item if isinstance(item, dict) else {}


def save_provider_config(provider, api_key="", base_url="", model=""):
    """记住某供应商的地址/模型/Key，切换预设时自动回填"""
    name = str(provider or "").strip()
    if not name:
        return False
    path = _provider_store_path()
    try:
        data = load_provider_configs()
        data[name] = {
            "api_key": str(api_key or ""),
            "base_url": str(base_url or ""),
            "model": str(model or ""),
        }
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"⚠️ 保存供应商配置失败：{e}")
        return False


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


def get_confirm_point(settings):
    """选图类验证码的「确认/提交」按钮坐标。
    启用且坐标有效返回 (x, y)；未启用/坐标为 0 返回 None（不点）"""
    if not (settings or {}).get("captcha_confirm_enabled", False):
        return None
    point = (settings or {}).get("captcha_confirm_point", [0, 0]) or [0, 0]
    try:
        x, y = int(point[0]), int(point[1])
    except (TypeError, ValueError, IndexError):
        return None
    if x <= 0 or y <= 0:
        return None
    return (x, y)


def _click_screen_point(x, y):
    """拟人移动到坐标并单击（移动失败则退回直接点击）"""
    try:
        utils.smooth_move_to(x, y)
        utils.human_click_delay()
    except Exception:
        pass
    import pyautogui
    pyautogui.click()


def get_coord_space(settings):
    """读取「坐标空间」设置：auto / normalized / pixel（非法值按 auto）"""
    value = str((settings or {}).get("ai_visual_captcha_coord_space", "") or "").strip()
    if value in (COORD_SPACE_AUTO, COORD_SPACE_NORMALIZED, COORD_SPACE_PIXEL):
        return value
    return COORD_SPACE_AUTO


def _build_prompt(width, height):
    return (
        "你是登录验证码识别助手。这是电脑屏幕截图（可能只截取了验证码所在区域），"
        f"分辨率 {width}x{height} 像素。判断图中是否出现验证码（点选/图片验证）。\n"
        '只输出严格JSON，不要输出任何其他文字：\n'
        '{"captcha": true/false, "type": "click"/"slider"/"none", "mode": "text"/"image", '
        '"targets": [{"text": "要点击的目标描述", "bbox": [x1,y1,x2,y2], "point": [x,y]}]}\n'
        "【第一步：读懂题目文字，判断题型】（mode 必须填对，两种题型完全不同）\n"
        "- mode=text（文字点选）：题目直接给出要点选的字/词，"
        "如「请依次点击：桦 离」「请点击文字：XXX」→ 每个要点选的字/词各给一个 target，"
        "point 是该字中心的坐标，targets 按题目要求的点击顺序排列\n"
        "- mode=image（图片选择）：题目要求选出【内容符合某个描述】的图片，"
        "如「请选择所有包含红绿灯的图片」「选出所有有狗的图片」→ 每张符合描述的图片各给一个 target，"
        "point 必须是【那张图片的中心】，不要指向图片内部的某个文字或局部\n"
        "【第二步：严格遵守】\n"
        "- mode=image 时，绝对不要逐个输出图片里的文字，也不要把图中所有文字都当成目标；"
        "target 数量 = 符合描述的图片张数（通常 1~4 个）。"
        "如果你输出了十几个 target，说明你把题型判断错了，请重新判断\n"
        "- 题目里带文字要求时（如「包含文字：\"川\"」），要看的是图片内容里是否真的出现了该文字"
        "（可能是藏在景物里的字形、半透明水印等，不要因为不显眼就忽略）\n"
        "- mode=image 时 bbox 要紧贴该图片的四条边（不要跨到相邻图片），point 取该图片矩形的中心\n"
        "- text 字段用简短描述即可，不要包含英文引号（\"），以免 JSON 出错\n"
        "- 按题目顺序排列 targets（图片选择题无顺序要求时按从左到右、从上到下排）\n"
        "- 坐标一律用【0-1000 归一化整数】：本图左上角=(0,0)，右下角=(1000,1000)；不要给像素坐标\n"
        "- 只选清晰、颜色鲜明、显示完整的目标；默认忽略半透明水印、背景底纹、被遮挡或残缺的内容"
        "（例外：题目明确要求找「包含文字X」的图片时，图里的文字即使不显眼也要算）\n"
        "- 滑块拼图验证：输出 {\"captcha\": true, \"type\": \"slider\", \"mode\": \"\", \"targets\": []}\n"
        "- 没有验证码：输出 {\"captcha\": false, \"type\": \"none\", \"mode\": \"\", \"targets\": []}\n"
        "- 找不准目标就不要给坐标，宁可输出找不到"
    )


def _repair_unescaped_quotes(text):
    """修复模型返回 JSON 里【字符串内部的未转义引号】。

    实测 glm-4.6v 会把画面上的题目原样写进 text 字段，于是出现
    "text": "包含文字"川"的图片" —— JSON 非法，json.loads 直接失败、坐标全丢。
    规则：字符串内碰到 " 时，看它后面第一个非空白字符——
    是 , } ] : 或结尾 → 视为字符串结束；否则判为字符串内部的引号，转义为 \\" """
    out = []
    in_str = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == "\\":
            out.append(text[i:i + 2])
            i += 2
            continue
        if ch == '"':
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            nxt = text[j] if j < n else ""
            if nxt in (",", "}", "]", ":", ""):
                out.append('"')
                in_str = False
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_json(text):
    """从模型回复中提取第一个 JSON 对象（容忍 ```json 包裹、前后缀文字、
    字符串内未转义的引号）"""
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
                raw = cleaned[start:i + 1]
                try:
                    return json.loads(raw)
                except Exception:
                    pass
                # 常见失败原因：text 里带了未转义的引号（模型照抄画面上的
                # 「包含文字"川"的图片」这类题目）→ 修一次再试
                try:
                    return json.loads(_repair_unescaped_quotes(raw))
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


def _raw_target_values(target):
    """收集 target 里所有坐标原始数值（point/bbox/x1..y2），供坐标空间判定"""
    values = []
    if not isinstance(target, dict):
        return values
    for key in ("point", "bbox"):
        seq = target.get(key)
        if isinstance(seq, (list, tuple)):
            for v in seq:
                n = _to_number(v)
                if n is not None:
                    values.append(abs(n))
    for key in ("x", "y", "x1", "y1", "x2", "y2"):
        n = _to_number(target.get(key))
        if n is not None:
            values.append(abs(n))
    return values


def _detect_coord_space(raw_targets, setting=COORD_SPACE_AUTO):
    """判定模型返回坐标的空间。

    auto：出现 >1000 的坐标说明模型给的是像素（归一化不可能超过 1000），否则按
          0-1000 归一化处理 —— 国内视觉接口（智谱/豆包/百炼等）默认就是归一化，
          提示词里要求「像素」也不会改变，实测 glm-4.6v 返回的正是 0-1000。
    若供应商确实返回像素坐标（例如图中目标在左上角、数值刚好都不超过 1000 时无法自动区分），
    可在设置里把「坐标空间」改成「像素」强制指定。"""
    if setting in (COORD_SPACE_NORMALIZED, COORD_SPACE_PIXEL):
        return setting
    values = []
    for t in raw_targets or []:
        values.extend(_raw_target_values(t))
    if values and max(values) > 1000:
        return COORD_SPACE_PIXEL
    return COORD_SPACE_NORMALIZED


def _to_px(v, dim, scale):
    """单个坐标 → 像素：scale=1000/1024 按比例放大，scale=1（0-1 浮点）乘边长，0=原样像素"""
    n = _to_number(v)
    if n is None:
        return None
    if scale in (1000, 1024):
        return int(round(n / float(scale) * dim))
    if scale == 1:
        return int(round(n * dim)) if 0 <= n <= 1 else int(round(n))
    return int(round(n))


def _target_scale(target, space):
    """该 target 的换算系数：模型显式给了 scale 就以其为准，否则用判定出的全局空间"""
    explicit = _scale_factor((target or {}).get("scale"))
    if explicit:
        return explicit
    return 1000 if space == COORD_SPACE_NORMALIZED else 0


def _target_center(target, screen_w, screen_h, space=COORD_SPACE_NORMALIZED):
    """从 target 提取坐标（像素，相对"发送给模型的这张图"的左上角）。
    按 space（像素/归一化）换算后返回；调用方再统一加上识别区域左上角偏移。
    优先 point（模型自报的目标点），无 point 才用 bbox 中心。返回 (x, y) 或 None"""
    if not isinstance(target, dict):
        return None
    scale = _target_scale(target, space)

    def _px(v, dim):
        return _to_px(v, dim, scale)

    point = target.get("point")
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        x, y = _px(point[0], screen_w), _px(point[1], screen_h)
        if x is not None and y is not None:
            return (x, y)
    bbox = target.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        x1, y1 = _px(bbox[0], screen_w), _px(bbox[1], screen_h)
        x2, y2 = _px(bbox[2], screen_w), _px(bbox[3], screen_h)
        if None not in (x1, y1, x2, y2) and x2 >= x1 and y2 >= y1:
            return (int((x1 + x2) / 2), int((y1 + y2) / 2))
    # 兜底：x1/y1/x2/y2 平铺字段
    xs = [_px(target.get(k), screen_w) for k in ("x1", "x2")]
    ys = [_px(target.get(k), screen_h) for k in ("y1", "y2")]
    if all(v is not None for v in xs + ys):
        return (int((xs[0] + xs[1]) / 2), int((ys[0] + ys[1]) / 2))
    xy = (_px(target.get("x"), screen_w), _px(target.get("y"), screen_h))
    if None not in xy:
        return xy
    return None


def parse_model_response(text, screen_w, screen_h, coord_space=COORD_SPACE_AUTO):
    """解析模型回复 → {"status": "click"/"slider"/"none"/"invalid",
                      "points": [(x,y),...], "labels": [...], "space": "normalized"/"pixel"}
    points 为相对「发送给模型的这张图」左上角的像素坐标（已按坐标空间换算）。"""
    data = _extract_json(text)
    if not isinstance(data, dict):
        return {"status": "invalid", "points": [], "labels": [], "space": coord_space,
                "mode": ""}
    captcha = bool(data.get("captcha"))
    ctype = str(data.get("type") or "").strip().lower()
    mode = str(data.get("mode") or "").strip().lower()
    if mode not in ("text", "image"):
        mode = ""
    targets = data.get("targets")
    if not isinstance(targets, list):
        targets = []
    space = _detect_coord_space(targets, coord_space)
    if not captcha or ctype in ("none", "no", "false"):
        return {"status": "none", "points": [], "labels": [], "space": space, "mode": mode}
    if ctype in ("slider", "slide", "drag", "puzzle"):
        return {"status": "slider", "points": [], "labels": [], "space": space, "mode": mode}
    points = []
    labels = []
    for t in targets:
        center = _target_center(t, screen_w, screen_h, space)
        if center is None:
            continue
        points.append(center)
        label = ""
        if isinstance(t, dict):
            label = str(t.get("text") or "").strip()
        labels.append(label)
    if not points:
        return {"status": "invalid", "points": [], "labels": [], "space": space, "mode": mode}
    return {"status": "click", "points": points, "labels": labels, "space": space, "mode": mode}


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


def save_debug_annotation(region, points_screen, labels=None, raw_content="",
                          settings=None, space=None, crop_size=None):
    """把本次 AI 识别结果标注到当前屏幕截图上并保存到「日志目录/图片/」（并尝试打开）。
    points_screen: 已换算到全屏的点击坐标 [(x,y),...]；region: 识别区域或 None；
    space: 本次判定的坐标空间（normalized/pixel）；crop_size: 发给模型的图尺寸 (w,h)。
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

        # ① AI 在【标注框内】的原始位置
        #    绿圈 = 把模型返回的数值当像素直读（旧算法会点这里）
        #    蓝圈 = 按本次判定的坐标空间换算（0-1000 归一化 → 像素）后的位置
        #    —— 蓝圈落在目标上 → 换算正确；蓝圈也偏 → 模型本身定位错
        _ox, _oy = (int(region[0]), int(region[1])) if region else (0, 0)
        _space = space or _detect_coord_space(raw_targets)
        _cw, _ch = crop_size if crop_size else (arr.shape[1], arr.shape[0])
        for i, t in enumerate(raw_targets):
            _scale = _target_scale(t, _space)
            pt = t.get("point")
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    raw_x, raw_y = int(float(pt[0])), int(float(pt[1]))
                    gx, gy = raw_x + _ox, raw_y + _oy
                    cv2.circle(arr, (gx, gy), 16, (0, 200, 0), 3)
                    cv2.putText(arr, f"AI原始({raw_x},{raw_y})", (gx + 20, gy + 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 2)
                except Exception:
                    pass
                try:
                    cx = _to_px(pt[0], _cw, _scale) + _ox
                    cy = _to_px(pt[1], _ch, _scale) + _oy
                    if None not in (cx, cy):
                        cv2.circle(arr, (cx, cy), 10, (255, 120, 0), 3)
                        cv2.putText(arr, f"换算[{_space}]({cx - _ox},{cy - _oy})",
                                    (cx + 14, cy - 12),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 120, 0), 2)
                except Exception:
                    pass
            bb = t.get("bbox")
            if isinstance(bb, (list, tuple)) and len(bb) >= 4:
                try:
                    _b = [_to_px(v, _cw if k % 2 == 0 else _ch, _scale)
                          for k, v in enumerate(bb[:4])]
                    if None not in _b:
                        cv2.rectangle(arr, (_b[0] + _ox, _b[1] + _oy),
                                      (_b[2] + _ox, _b[3] + _oy), (255, 120, 0), 1)
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
                cv2.putText(disp, f"crop: green=raw as pixel, blue=converted[{_space}], red=click",
                            (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
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
                        try:
                            _s2 = _target_scale(t, _space)
                            _bx = _to_px(_pt[0], _cw, _s2)
                            _by = _to_px(_pt[1], _ch, _s2)
                            if None not in (_bx, _by):
                                cv2.circle(disp, (int(_bx * ratio), int(_by * ratio)),
                                           5, (255, 120, 0), 2)
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
                _conv = None
                try:
                    _s2 = _target_scale(t, _space)
                    _conv = (_to_px(_p[0], _cw, _s2), _to_px(_p[1], _ch, _s2))
                except Exception:
                    _conv = None
                print(f"🖼️ 目标{i + 1}: AI原始 point={_p}（scale={_s}，坐标空间={_space}）"
                      f" → 框内原始直读={_box}(绿) → 换算后框内={_conv}(蓝) → 实际点击={_cv}(红)")
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
    coord_space = get_coord_space(settings)
    confirm_point = get_confirm_point(settings)
    if region:
        print(f"🤖 AI视觉验证：使用识别区域 {region}（坐标已自动换算全屏）")
    if confirm_point:
        print(f"🤖 AI视觉验证：已启用「选图后点确认」，点完目标图后点击 {confirm_point}")
    try:
        import pyautogui as _pag
        screen_size = tuple(_pag.size())
    except Exception:
        screen_size = None

    overlay_hidden = _hide_overlay()
    # 轮次安排：前 rounds 轮「识别+点击」，最后再补 1 轮「只识别不点击」的复核。
    # 复核必须单独占一轮：否则 max_rounds=1 时点完目标就直接返回失败，
    # 即使点对了也判不过（只能靠后面的人工验证等待兜底）。
    total_rounds = rounds + 1
    try:
        for round_index in range(1, total_rounds + 1):
            verify_only = round_index > rounds
            if stop_event is not None and stop_event.is_set():
                return False, "已停止"
            image_b64, mime, w, h = _capture_screen_jpeg(region)
            if not image_b64:
                return False, "截图失败"
            if verify_only:
                print(f"🔍 AI视觉验证：复核验证码是否已消失（第{round_index - 1}次点击后）...")
            else:
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
            parsed = parse_model_response(content, w, h, coord_space)
            # 诊断日志：核对换算（模型原始回复 / 图像尺寸 / 坐标空间 / 区域偏移 / 解析出的坐标）
            try:
                print(f"🤖 AI原始回复：{str(content)[:300]}")
                _sp = parsed.get("space")
                if status == "invalid" and not parsed.get("points"):
                    # 解析失败（模型给了验证码但坐标没解出来）——多半是 JSON 格式问题
                    print(f"⚠️ 未能解析出坐标（图像 {w}x{h}，题型={parsed.get('mode') or '未给'}）"
                          f"，原始回复见上一行")
                else:
                    _sp_desc = {COORD_SPACE_NORMALIZED: "（已按 0-1000 归一化换算成像素）",
                                COORD_SPACE_PIXEL: "（按像素直读）"}.get(_sp, "（自动判定）")
                    print(f"🤖 图像 {w}x{h}，题型={parsed.get('mode') or '未给'}，坐标空间={_sp}{_sp_desc}，"
                          f"区域偏移 ({offset_x},{offset_y})，框内像素坐标：{parsed.get('points')}")
            except Exception:
                pass
            status = parsed["status"]
            if status == "none":
                print("🤖 AI视觉验证：未检测到验证码")
                if save_debug:
                    save_debug_annotation(region, [], [], content, settings=settings,
                                        space=parsed.get("space"), crop_size=(w, h))
                if verify_only:
                    return True, "验证通过（复核确认验证码已消失）"
                return True, f"第{round_index}轮未检测到验证码"
            if status == "slider":
                if save_debug:
                    save_debug_annotation(region, [], [], content, settings=settings,
                                        space=parsed.get("space"), crop_size=(w, h))
                if verify_only:
                    return False, "复核时仍检测到滑块验证"
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
                        time.sleep(RECHECK_WAIT_SECONDS)
                        continue
                    return False, f"滑块YOLO处理未通过：{slider_detail}"
                print("🤖 AI视觉验证：检测到滑块拼图验证，请在游戏内手动完成（滑块YOLO未启用）")
                return False, "检测到滑块验证，需手动处理"
            if status == "invalid":
                if _extract_json(content) is None:
                    print("⚠️ AI视觉验证：模型回复的 JSON 解析失败（格式损坏，常见于字符串里带"
                          "未转义的引号）；原始回复见上方日志")
                else:
                    print("⚠️ AI视觉验证：模型答复里没有可用坐标"
                          "（可能只读出了题目文字、没给出目标位置）")
                if save_debug:
                    save_debug_annotation(region, [], [], content, settings=settings,
                                        space=parsed.get("space"), crop_size=(w, h))
                return False, "模型未返回有效坐标"
            # click：按顺序拟人点击（截图带区域时坐标需加区域偏移换算回全屏）
            if len(parsed["points"]) > MAX_CLICK_TARGETS:
                # 题型判错的典型症状（图片选择题被当成逐字点选），点下去会误触一大片
                if save_debug:
                    save_debug_annotation(
                        region,
                        [(int(px) + offset_x, int(py) + offset_y) for (px, py) in parsed["points"]],
                        parsed["labels"], content, settings=settings,
                        space=parsed.get("space"), crop_size=(w, h))
                print(f"⚠️ AI视觉验证：模型给出 {len(parsed['points'])} 个目标，超过单轮上限 "
                      f"{MAX_CLICK_TARGETS}，疑似题型判断错误（如把图片选择题当成逐字点选），"
                      f"本轮不点击、按未通过处理（题型={parsed.get('mode') or '未给'}）")
                return False, f"目标数异常（{len(parsed['points'])} 个 > {MAX_CLICK_TARGETS}）"
            if verify_only:
                # 复核轮只判不点：还识别得到目标说明上一轮没点成功
                if save_debug:
                    save_debug_annotation(
                        region,
                        [(int(px) + offset_x, int(py) + offset_y) for (px, py) in parsed["points"]],
                        parsed["labels"], content, settings=settings,
                        space=parsed.get("space"), crop_size=(w, h))
                print(f"❌ 复核仍有 {len(parsed['points'])} 个目标未被点击成功，本次验证未通过")
                return False, f"复核时验证码仍在（仍有 {len(parsed['points'])} 个目标）"
            labels = parsed["labels"]
            if save_debug:
                save_debug_annotation(
                    region,
                    [(int(px) + offset_x, int(py) + offset_y) for (px, py) in parsed["points"]],
                    labels, content, settings=settings,
                    space=parsed.get("space"), crop_size=(w, h))
            for i, (x, y) in enumerate(parsed["points"]):
                if stop_event is not None and stop_event.is_set():
                    return False, "已停止"
                screen_x = x + offset_x
                screen_y = y + offset_y
                label = labels[i] if i < len(labels) and labels[i] else f"目标{i + 1}"
                if screen_size and not (0 <= screen_x < screen_size[0]
                                        and 0 <= screen_y < screen_size[1]):
                    # 换算后落到屏幕外：坐标空间判错或模型给的是无效值，点下去只会误触
                    print(f"⚠️ AI视觉验证：目标「{label}」换算后坐标 ("
                          f"{screen_x},{screen_y}) 超出屏幕 {screen_size[0]}x{screen_size[1]}，跳过本次点击")
                    return False, f"坐标超出屏幕：{label}({screen_x},{screen_y})"
                print(f"🤖 AI视觉验证：点击「{label}」（{screen_x},{screen_y}）")
                try:
                    _click_screen_point(screen_x, screen_y)
                except Exception as e:
                    return False, f"点击失败：{e}"
                time.sleep(random.uniform(0.6, 1.2))
            # 选图类验证码：选完图还要点一次「确认/提交」才生效
            if confirm_point:
                time.sleep(0.8)
                if stop_event is not None and stop_event.is_set():
                    return False, "已停止"
                print(f"🤖 AI视觉验证：点击「确认」（{confirm_point[0]},{confirm_point[1]}）")
                try:
                    _click_screen_point(confirm_point[0], confirm_point[1])
                except Exception as e:
                    return False, f"点击确认失败：{e}"
            time.sleep(RECHECK_WAIT_SECONDS)
        return False, f"{rounds}轮点击后复核仍未确认验证码消失"
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
        print("🖼️ 本次已在「日志目录/日期/图片/」生成带标注的截图并自动打开"
              "（绿=AI原始值直读，蓝=按坐标空间换算，红=实际点击）")

    threading.Thread(target=_run, daemon=True).start()
