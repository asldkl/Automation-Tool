# -*- coding: utf-8 -*-
"""
登录验证码统一调度（OCR 判定 → 分发）

登录第三态（既未见重登按钮也未见三角洲图标）触发后：
1. OCR 识别屏幕文字，按关键词判定验证类型：
   - 命中滑块关键词（拖动/滑动/滑块…）→ 滑块 YOLO 自动拖动（slider_captcha）
   - 命中点击关键词（依次点击/请点击…）→ AI 视觉验证点击（ai_visual_captcha）
   - 未命中任何关键词 → AI 视觉兜底判定（能识别任意形态；未配置 AI 则放行由启动流程兜底）
2. 滑块 YOLO 未检测到滑块元素（OCR 误报）时自动落到 AI 兜底
3. AI 视觉判出滑块类型时也会委托滑块 YOLO（见 ai_visual_captcha 内部）

总开关 captcha_auto_enabled 关闭时整条链路不生效（登录流程保持原行为）。
"""
import utils


def _parse_keywords(value):
    """关键词配置 → 列表（逗号/顿号分隔，去空白去空项）"""
    if not value:
        return []
    items = []
    for part in str(value).replace("，", ",").replace("、", ",").split(","):
        part = part.strip()
        if part:
            items.append(part)
    return items


def gather_screen_text():
    """OCR 全屏识别并合并文本（置信度≥0.5），失败返回空串"""
    try:
        results = utils.ocr_recognize(None)
    except Exception:
        return ""
    parts = []
    for item in (results or []):
        try:
            text = str(item[0]).strip()
            conf = float(item[1]) if len(item) > 1 and item[1] is not None else 1.0
        except Exception:
            continue
        if text and conf >= 0.5:
            parts.append(text)
    return "".join(parts)


def _slider_module_state(settings):
    """(模块可用, 是否启用)"""
    try:
        import slider_captcha
        return slider_captcha, slider_captcha.is_enabled(settings)
    except Exception:
        return None, False


def _ai_module_state(settings):
    try:
        import ai_visual_captcha
        return ai_visual_captcha, ai_visual_captcha.is_configured(settings)
    except Exception:
        return None, False


def route_and_solve(app, stop_event=None, screen_text=None):
    """OCR 判定验证类型并分发处理。

    返回 (ok, detail)：ok=True 表示无验证码或已处理完成（登录可继续）；
    ok=False 表示检测到验证但未解决（调用方按登录失败重试）。
    总开关未启用时返回 (False, "总开关未启用")，调用方不应触发本函数。"""
    settings = getattr(app, "settings", None) or {}
    if not settings.get("captcha_auto_enabled", False):
        return False, "总开关未启用"

    if screen_text is None:
        screen_text = gather_screen_text()
    text = str(screen_text or "")

    slider_kws = _parse_keywords(settings.get("captcha_slider_keywords"))
    click_kws = _parse_keywords(settings.get("captcha_click_keywords"))
    slider_mod, slider_on = _slider_module_state(settings)
    ai_mod, ai_on = _ai_module_state(settings)

    def _try_ai(reason):
        if not ai_on:
            print(f"🛡️ {reason}，但 AI 视觉验证未启用/未配置，无法处理")
            return False, f"{reason}：AI视觉验证未配置"
        ok, detail = ai_mod.solve_captcha(app, stop_event=stop_event)
        return ok, detail

    # 1) 滑块关键词优先（两类词同时命中时按滑块处理，YOLO 未检出会落 AI 兜底）
    if any(k in text for k in slider_kws):
        print(f"🛡️ OCR 判定为滑块验证（命中关键词）")
        if not slider_on:
            return _try_ai("OCR判定滑块但滑块YOLO未启用")
        found, solved, detail = slider_mod.solve_slider_yolo(app, stop_event=stop_event)
        if not found:
            # OCR 误报或 YOLO 未检出：AI 视觉兜底再判一次（能处理任意形态）
            print(f"🧩 滑块YOLO未检测到滑块元素（{detail}），转 AI 视觉兜底")
            if ai_on:
                ok, d2 = _try_ai("滑块未检出")
                return ok, f"滑块未检出→AI兜底：{d2}"
            # 未配置 AI：YOLO 眼中没有滑块元素，大概率不是验证页 → 放行（由启动流程兜底判断）
            return True, f"滑块YOLO未检出元素且未配置AI，放行：{detail}"
        print(f"🧩 滑块验证{'已自动处理' if solved else '未能自动通过'}：{detail}")
        return solved, detail

    # 2) 点击式关键词 → AI 视觉
    if any(k in text for k in click_kws):
        print("🛡️ OCR 判定为点击式验证（命中关键词）")
        return _try_ai("点击式验证")

    # 3) 未命中关键词：AI 兜底判定（无验证码时 AI 返回 none 即成功）
    if ai_on:
        print("🛡️ OCR 未识别到验证码关键词，AI 视觉兜底判定")
        return _try_ai("兜底判定")
    print("ℹ️ 未识别到验证码特征且未配置AI视觉，跳过验证码处理")
    return True, "无验证码特征"


def test_router(app):
    """设置窗口「测试完整流程」按钮：对当前屏幕跑一遍 OCR 判定 + 对应处理"""
    import threading
    import time

    def _run():
        print("🛡️ 验证码完整流程测试开始（3秒后开始，请把测试画面摆在前台）...")
        time.sleep(3)
        ok, detail = route_and_solve(app, stop_event=getattr(app, "_stop_event", None))
        print(f"{'✅' if ok else '❌'} 验证码完整流程测试结束：{detail}")

    threading.Thread(target=_run, daemon=True).start()
