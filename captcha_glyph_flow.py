# -*- coding: utf-8 -*-
"""本地字形匹配验证码处理器（离线、零 API）。

策略（「有把握就点、没把握就换一组」）：
  1. 按「验证码识别区域」截图，复用 captcha_router 的区域 OCR 读出题面里的目标字；
  2. 检出面里的图块，用字形模板匹配给每块打分（黑帽 + ±3σ + TM_CCOEFF_NORMED）；
  3. ``conf = 选中块最低分 − 未选中块最高分``：
     - ``conf > 门限`` → 按顺序点击这些块，再点「确认/提交」，返回成功；
     - ``conf <= 门限`` → **一律不点任何图**（避免误触），返回失败。
       外层 ``captcha_router.route_and_solve`` 的「刷新重试」会据此点「换一组」换批图重来，
       这正是「没把握就刷新下一张」——不需要自己再写一套刷新循环。

与 AI 路径共用同一套配置：``captcha_confirm_point`` / ``captcha_refresh_point`` / ``captcha_refresh_max``。

开关：``captcha_glyph_enabled``（默认关）。关闭时本模块完全不参与，链路行为与从前一致。

可调四项（见 ``read_profile``）：``captcha_glyph_threshold`` / ``_gate`` / ``_prep`` / ``_kernel``。
当前生产档位 = clahe + 核 35 + 阈值 0.40 + 门限 0.09（25 张上门控口径选出，见 config.py 注释）。
"""
import random
import re
import threading
import time

import config  # noqa: F401  (与其它子模块保持一致：设置从 app.settings 取，这里仅备用)

# 「包含文字：X」题面 → 目标字。与 captcha_router 的判型特征词同源，放宽到三种写法。
_TARGET_RE = re.compile(
    r"(?:包含文字|含有文字|含文字)[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")

_matchers: dict = {}          # (黑帽核, 图像处理模式) -> GlyphMatcher
_matcher_lock = threading.Lock()


def is_enabled(settings):
    """本地字形匹配总开关（默认关）"""
    return bool((settings or {}).get("captcha_glyph_enabled", False))


def _num(settings, key, default, lo=None, hi=None):
    """读一个数值设置，非法值/越界一律回落到默认（配置来自用户手填，不能信）"""
    try:
        v = float((settings or {}).get(key, default))
    except (TypeError, ValueError):
        return default
    if lo is not None and v < lo:
        return default
    if hi is not None and v > hi:
        return default
    return v


def read_profile(settings):
    """读「字形匹配」的可调四项并做校验，非法值一律回落默认。

    阈值 / 门限 / 图像处理 / 黑帽核都允许用户在 settings.json 里改（手填的值不能信）。
    返回 {"mode", "kernel", "threshold", "gate"}。
    """
    import captcha_glyph_match as cgm
    raw = str((settings or {}).get("captcha_glyph_prep", "") or "").strip().lower()
    mode = raw if raw in cgm.PREP_MODES else cgm.PREP_DEFAULT
    kernel = int(_num(settings, "captcha_glyph_kernel", cgm.BH_KERNEL, lo=3, hi=99))
    if kernel % 2 == 0:
        kernel += 1                      # 形态学核必须是奇数
    return {"mode": mode, "kernel": kernel,
            "threshold": _num(settings, "captcha_glyph_threshold",
                              cgm.DEFAULT_THRESHOLD, lo=0.0, hi=1.0),
            "gate": _num(settings, "captcha_glyph_gate",
                         cgm.GATE_DEFAULT, lo=0.0, hi=1.0)}


def _get_matcher(profile):
    """按 (黑帽核, 图像处理模式) 复用 GlyphMatcher（模板族按字缓存，避免每轮重新渲染）"""
    key = (int(profile.get("kernel", 25)), str(profile.get("mode", "bh")))
    m = _matchers.get(key)
    if m is None:
        with _matcher_lock:
            m = _matchers.get(key)
            if m is None:
                import captcha_glyph_match as cgm
                m = cgm.GlyphMatcher(kernel=key[0], mode=key[1])
                _matchers[key] = m
    return m


def extract_target_char(text):
    """从 OCR 到的题面文字里取目标字；取不到返回空串"""
    m = _TARGET_RE.search(str(text or ""))
    return m.group(1) if m else ""


def solve_glyph_captcha(app, stop_event=None, force=False):
    """本地字形匹配一条龙。返回 (ok, detail)。

    ok=True  = 已按门控提交（点完目标块并点了确认）
    ok=False = 没把握/读不到题面/没检出图块 —— **没有点击任何图**，交由上层换一组或转 AI

    force=True 跳过开关校验（设置窗口的测试按钮用）。
    """
    settings = getattr(app, "settings", None) or {}
    if not force and not is_enabled(settings):
        return False, "本地字形匹配未启用"

    import ai_visual_captcha as avc
    import captcha_glyph_match as cgm
    import captcha_router as router

    region = avc.get_capture_region(settings)
    offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
    confirm_point = avc.get_confirm_point(settings)
    prof = read_profile(settings)
    threshold, gate = prof["threshold"], prof["gate"]
    if region:
        print(f"🔤 本地字形匹配：使用识别区域 {region}（坐标已换算全屏）")
    if not confirm_point:
        print("⚠️ 本地字形匹配：未配置「确认/提交」坐标，选完图不会点确认，可能不会生效")

    # 遮罩避让：与 AI 路径同法，防止日志遮罩入镜污染截图
    overlay_hidden = avc._hide_overlay()
    try:
        if stop_event is not None and stop_event.is_set():
            return False, "已停止"
        # 目标字：复用 router 的区域 OCR 合并文本（它已处理遮罩/区域）
        text = router.gather_region_text(settings)
        ch = extract_target_char(text)
        if not ch:
            return False, f"题面没读出目标字（OCR：{str(text or '')[:40]}）"
        bgr = avc._grab_bgr(region)
        if bgr is None:
            return False, "截图失败"
        coords = avc.detect_image_tiles(bgr)
        if not coords:
            return False, "没检出图块"
        tiles = [bgr[y:y + h, x:x + w] for (x, y, w, h) in coords]
        scores = _get_matcher(prof).score_tiles(tiles, ch)
        print("🔤 本地字形匹配：目标「{}」逐块分数 {}".format(
            ch, " ".join(f"{i}:{v:+.3f}" for i, v in enumerate(scores, 1))))
        decision = cgm.decide(scores, threshold=threshold, gate=gate)
        if decision["action"] != "submit":
            return False, (f"没把握不点击（{decision['reason']}；"
                           f"选中={decision['picked']}，模式={decision['mode']}）")
        picked = decision["picked"]
        print(f"🎯 本地字形匹配：{decision['reason']}，提交选中 {picked}（模式 {decision['mode']}）")
        for idx in picked:
            if stop_event is not None and stop_event.is_set():
                return False, "已停止"
            x, y, w, h = coords[idx - 1]
            cx, cy = x + w // 2 + offset_x, y + h // 2 + offset_y
            print(f"🔤 点击第 {idx} 块（{cx},{cy}）")
            try:
                avc._click_screen_point(cx, cy)
            except Exception as e:
                return False, f"点击第 {idx} 块失败：{e}"
            time.sleep(random.uniform(0.6, 1.2))
        if confirm_point:
            time.sleep(0.8)
            if stop_event is not None and stop_event.is_set():
                return False, "已停止"
            print(f"🔤 点击「确认」（{confirm_point[0]},{confirm_point[1]}）")
            try:
                avc._click_screen_point(confirm_point[0], confirm_point[1])
            except Exception as e:
                return False, f"点击确认失败：{e}"
        return True, (f"已提交 {picked} 块（conf={decision['conf']:+.3f}，"
                      f"模式={decision['mode']}"
                      f"{'' if confirm_point else '，未配确认坐标'}）")
    finally:
        avc._show_overlay(overlay_hidden)


def test_glyph_captcha(app):
    """设置窗口测试按钮：对当前屏幕跑一次本地字形匹配（没把握时不会点击任何东西）"""
    def _run():
        print("🔤 本地字形匹配测试开始（3 秒后开始，请把验证码画面摆在前台）...")
        time.sleep(3)
        ok, detail = solve_glyph_captcha(
            app, stop_event=getattr(app, "_stop_event", None), force=True)
        print(f"{'✅' if ok else '❌'} 本地字形匹配测试结束：{detail}")

    threading.Thread(target=_run, daemon=True).start()
