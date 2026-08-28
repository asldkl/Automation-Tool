"""
滑块验证模块（WeGame 登录后可能出现的滑块验证码处理）
支持：
- OCR 关键词检测滑块验证是否出现
- 目标位置计算：配置了拼图块/切片区域用模板匹配；否则用边缘密度列分析找可见目标（缺口/竖条/标记）
- 拟人化拖动滑块（先快后慢 + 随机停顿 + 微调）
在 login 流程中自动调用；实验功能中有「测试滑块验证」按钮可手动验证
"""
import time
import random

import cv2
import numpy as np
import pyautogui

import config
import utils


def _screenshot_color(region):
    """截取屏幕区域并转为 BGR 彩色数组"""
    try:
        screen = pyautogui.screenshot(region=tuple(int(v) for v in region))
        arr = np.array(screen)
        screen.close()
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def _crop_whitespace(img):
    """裁掉图片的透明/白边，返回 (裁剪图, 左裁剪偏移, 上裁剪偏移)（向量化，比逐像素循环快）"""
    if img is None or img.size == 0:
        return img, 0, 0
    rgb = img[:, :, :3]
    # 非白像素掩码：任一通道明显低于白色
    non_white = np.any(rgb < 245, axis=2)
    if not non_white.any():
        return img, 0, 0
    rows = np.any(non_white, axis=1)
    cols = np.any(non_white, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    return img[rmin:rmax + 1, cmin:cmax + 1], int(cmin), int(rmin)


def find_target_by_template(bg_img, tile_img, bg_region=None, slice_region=None):
    """ddddocr slide_match 成熟算法：裁剪透明边 → 灰度 → Canny(50,150) → 模板匹配
    屏蔽拼图块当前位置（避免把拼图块本身误识别成缺口），再找缺口
    返回 (缺口左边缘x, 置信度, 切片左裁剪偏移, 拼图块宽 tile_w)
    缺口左边缘x 为拼图块在背景图中的左边缘（对齐时拼图块左边缘应到达此位置）"""
    try:
        tile = tile_img
        crop_x = 0
        if tile.ndim == 3 and tile.shape[2] == 4:
            # RGBA：用 alpha 通道去掉透明边
            alpha = tile[:, :, 3]
            mask = alpha > 0
            if mask.any():
                x, y, w, h = cv2.boundingRect(mask.astype(np.uint8))
                tile = tile[y:y + h, x:x + w, :3]
                crop_x = int(x)
        else:
            # BGR 截图：去掉白边
            tile_cropped, crop_x, _ = _crop_whitespace(tile)
            tile = tile_cropped
        if tile is None or tile.size == 0:
            return None
        # ddddocr：RGB→灰度 + Canny(50,150)，不做置信度过滤，始终返回最佳匹配
        bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
        tile_gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
        bg_edge = cv2.Canny(bg_gray, 50, 150)
        tile_edge = cv2.Canny(tile_gray, 50, 150)
        if tile_edge.shape[0] >= bg_edge.shape[0] or tile_edge.shape[1] >= bg_edge.shape[1]:
            return None
        res = cv2.matchTemplate(bg_edge, tile_edge, cv2.TM_CCOEFF_NORMED)
        # 屏蔽拼图块当前位置（若它落在背景区域内），避免把拼图块误识别成缺口
        if bg_region is not None and slice_region is not None:
            bg_w = bg_img.shape[1]
            piece_x0_in_bg = slice_region[0] - bg_region[0]
            piece_x1_in_bg = piece_x0_in_bg + slice_region[2]
            if piece_x1_in_bg > 0 and piece_x0_in_bg < bg_w:
                mask_x0 = max(0, piece_x0_in_bg - 15)
                mask_x1 = min(res.shape[1], piece_x1_in_bg + 15)
                if mask_x0 < mask_x1:
                    res[:, mask_x0:mask_x1] = -1
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        return int(max_loc[0]), float(max_val), int(crop_x), int(tile_edge.shape[1])
    except Exception:
        return None


def find_knob_x(track_img):
    """在滑块轨道图中定位滑块把手（起点）位置：找左半部分最左侧的强边缘簇
    返回相对轨道的 x，找不到返回 0"""
    try:
        gray = cv2.cvtColor(track_img, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 60, 150)
        col_edges = edges.sum(axis=0).astype(float)
        if col_edges.size == 0:
            return 0
        threshold = max(col_edges.max() * 0.5, 1)
        high = np.where(col_edges >= threshold)[0]
        if high.size == 0:
            return 0
        # 把手通常在轨道左半部分
        half = track_img.shape[1] // 2
        left_high = high[high < half]
        if left_high.size == 0:
            left_high = high
        return int(left_high[0])
    except Exception:
        return 0


def find_target_by_gap(bg_img):
    """边缘密度列分析：定位背景图中的竖向目标（缺口/竖条/标记）中心
    找目标左右两条边界峰，取其中点（比取整段跨度中心更精确）"""
    try:
        gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        col_edges = edges.sum(axis=0).astype(float)
        if col_edges.size == 0:
            return 0
        # 滑动平均平滑，减少噪声
        k = 5
        kernel = np.ones(k) / k
        smoothed = np.convolve(col_edges, kernel, mode='same')
        max_val = smoothed.max()
        if max_val < 1:
            return gray.shape[1] // 2
        threshold = max_val * 0.5
        # 找局部峰值（间隔≥8 列）
        peaks = []
        n = len(smoothed)
        for i in range(1, n - 1):
            if smoothed[i] >= smoothed[i - 1] and smoothed[i] > smoothed[i + 1] and smoothed[i] >= threshold:
                if peaks and (i - peaks[-1]) < 8:
                    if smoothed[i] > smoothed[peaks[-1]]:
                        peaks[-1] = i
                else:
                    peaks.append(i)
        if not peaks:
            return gray.shape[1] // 2
        # 相邻峰对（间隔 8-120px）视为目标左右边界，取其中点（跨度最大者）
        best_mid, best_span = None, -1
        for i in range(len(peaks) - 1):
            span = peaks[i + 1] - peaks[i]
            if 8 <= span <= 120 and span > best_span:
                best_span = span
                best_mid = (peaks[i] + peaks[i + 1]) // 2
        if best_mid is not None:
            return best_mid
        # 只有单峰：返回峰本身
        return peaks[0]
    except Exception:
        return 0


def find_target_by_contour(bg_img):
    """成熟方案（GitHub 常见做法）：高斯模糊 → Canny → 膨胀 → 轮廓筛选找缺口
    返回缺口中心 x，找不到返回 None"""
    try:
        gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 100, 200)
        # 膨胀连接断裂边缘，让缺口轮廓闭合
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.dilate(edges, kernel, iterations=2)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = gray.shape
        candidates = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if cw <= 0 or ch <= 0:
                continue
            rect_area = cw * ch
            area = cv2.contourArea(cnt)
            fill_ratio = area / rect_area
            # 缺口特征：有一定尺寸（相对图片）、填充率适中、非贴右缘
            if (cw >= w * 0.03 and ch >= h * 0.10
                    and 0.20 <= fill_ratio <= 0.98
                    and x + cw < w * 0.98):
                candidates.append((rect_area, x + cw // 2))
        if not candidates:
            return None
        # 取面积最大的缺口候选，返回其中心 x
        candidates.sort(key=lambda c: c[0], reverse=True)
        return candidates[0][1]
    except Exception:
        return None


def detect_slider(app, keyword=None):
    """OCR 检测滑块验证是否出现在屏幕上
    返回 True=检测到"""
    try:
        settings = app.settings if hasattr(app, 'settings') else {}
        kw = (keyword or settings.get("slider_detect_keyword", "") or "拖动").strip()
        if not kw:
            return False
        region = settings.get("slider_detect_region", [0, 0, 0, 0])
        if not region or len(region) != 4 or region[2] <= 0:
            region = None
        results = utils.ocr_recognize(region)
        for text, conf, bbox in results:
            if kw in text:
                print(f"🔍 检测到滑块验证（OCR：{text.strip()}）")
                return True
        return False
    except Exception:
        return False


def _human_drag(x1, y1, x2, y2):
    """拟人化拖动滑块：先快后慢 + 随机停顿 + 到达微调，降低机器特征"""
    try:
        pyautogui.moveTo(x1, y1, duration=random.uniform(0.15, 0.3), _pause=False)
        time.sleep(random.uniform(0.05, 0.15))
        pyautogui.mouseDown()
        time.sleep(random.uniform(0.03, 0.08))
        steps = random.randint(30, 45)
        for i in range(1, steps + 1):
            t = i / steps
            eased = t * t * (3 - 2 * t)  # smoothstep：先快后慢
            cx = int(x1 + (x2 - x1) * eased)
            cy = int(y1 + (y2 - y1) * eased)
            pyautogui.moveTo(cx, cy, duration=random.uniform(0.005, 0.02), _pause=False)
            time.sleep(random.uniform(0.001, 0.008))
        # 到达目标后随机微调
        for _ in range(random.randint(1, 3)):
            pyautogui.moveRel(random.randint(-3, 3), random.randint(-1, 1),
                              duration=random.uniform(0.01, 0.03), _pause=False)
            time.sleep(random.uniform(0.02, 0.06))
        time.sleep(random.uniform(0.05, 0.15))
        pyautogui.mouseUp()
        return True
    except Exception as e:
        print(f"⚠️ 拖动滑块异常：{e}")
        try:
            pyautogui.mouseUp()
        except Exception:
            pass
        return False


def _get_region(settings, key):
    """读取区域配置，非法返回 None"""
    region = settings.get(key, [0, 0, 0, 0])
    if not region or len(region) != 4 or region[2] <= 0 or region[3] <= 0:
        return None
    return region


def solve_slider(app):
    """完整解滑块流程：检测 → 截图 → 求目标位置 → 拟人拖动
    返回 (found, solved, detail)"""
    if not detect_slider(app):
        return False, False, "未检测到滑块验证"

    settings = app.settings
    bg_region = _get_region(settings, "slider_bg_region")
    track_region = _get_region(settings, "slider_track_region")
    if bg_region is None:
        return True, False, "未配置背景区域（设置 → 全局设置 → 滑块验证 → 设置背景区域）"
    if track_region is None:
        return True, False, "未配置滑块轨道区域（设置 → 全局设置 → 滑块验证 → 设置滑块轨道区域）"

    bg_img = _screenshot_color(bg_region)
    if bg_img is None:
        return True, False, "背景区域截图失败"

    # 目标位置计算：拼图块模板匹配（拼图式）→ 轮廓筛选 → 边缘列兜底
    method = "轮廓筛选"
    target_x = None
    slice_crop_x = 0
    tile_w = 0  # 拼图块宽（模板匹配定位到缺口后，用于画缺口矩形）
    slice_region = _get_region(settings, "slider_slice_region")
    if slice_region is not None:
        slice_img = _screenshot_color(slice_region)
        if slice_img is not None:
            res = find_target_by_template(bg_img, slice_img, bg_region=bg_region, slice_region=slice_region)
            if res is not None:
                target_x, conf, slice_crop_x, tile_w = res
                method = f"模板匹配(置信度{conf:.2f})"
    if target_x is None:
        target_x = find_target_by_contour(bg_img)
    if target_x is None:
        target_x = find_target_by_gap(bg_img)
        method = "边缘缺口检测"

    # 保存调试图：背景 + 检测到的缺口矩形（红框=缺口左边缘到左边缘+拼图块宽），便于核对
    try:
        debug_path = settings.get("slider_debug_path", "")
        if debug_path:
            import os
            debug_dir = os.path.dirname(debug_path)
            if debug_dir:
                os.makedirs(debug_dir, exist_ok=True)
            debug_img = bg_img.copy()
            hh, ww = debug_img.shape[:2]
            box_w = max(int(tile_w), 40) if tile_w > 0 else 40
            cv2.rectangle(debug_img, (max(0, int(target_x) - 5), 0),
                          (min(ww, int(target_x) + box_w + 5), hh), (0, 0, 255), 2)
            cv2.putText(debug_img, f"x={target_x} w={box_w}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            # cv2.imwrite 不支持中文路径，改用 imencode + 二进制写文件
            ok, encoded = cv2.imencode('.png', debug_img)
            if ok:
                with open(debug_path, 'wb') as f:
                    f.write(encoded.tobytes())
                print(f"📷 调试图已保存：{debug_path}")
    except Exception:
        pass

    # 拖动参数
    knob_offset = int(settings.get("slider_knob_offset", 20))
    drag_offset = int(settings.get("slider_drag_offset", 0))
    track_y = track_region[1] + track_region[3] // 2
    # 鼠标起点：检测轨道内把手位置（比固定偏移准确），失败则用轨道左端 + 偏移
    start_x = None
    track_img = _screenshot_color(track_region)
    if track_img is not None:
        knob_x = find_knob_x(track_img)
        if knob_x > 0:
            start_x = track_region[0] + knob_x
    if start_x is None:
        start_x = track_region[0] + knob_offset
    # 拖动距离：拼图模式用拼图块当前位置（左边缘+去白边偏移）算，非拼图用把手起点算
    target_abs_x = bg_region[0] + int(target_x)
    if slice_region is not None:
        piece_left = slice_region[0] + slice_crop_x
        drag_dist = (target_abs_x - piece_left) + drag_offset
        base_desc = f"拼图块左={piece_left}"
    else:
        drag_dist = (target_abs_x - start_x) + drag_offset
        base_desc = f"起点={start_x}"
    drag_dist = max(0, drag_dist)

    print(f"🖱️ 滑块计算：背景区域={bg_region}，轨道区域={track_region}，"
          f"目标x={target_x}(相对背景，绝对{target_abs_x})，{method}，"
          f"{base_desc}，轨道Y={track_y}，拖动距离={drag_dist}px")
    ok = _human_drag(start_x, track_y, start_x + drag_dist, track_y)
    if ok:
        return True, True, f"{method}→目标x={target_x}，拖动{drag_dist}px"
    return True, False, "拖动执行失败"


def test_slider(app):
    """实验功能测试入口：检测并尝试解滑块，返回可读结果"""
    found, solved, detail = solve_slider(app)
    if not found:
        return ("未检测到滑块验证。\n\n"
                "请确认滑块验证码已出现在屏幕上，且「检测关键词」设置正确。")
    if solved:
        return f"✅ 滑块已拖动完成：{detail}\n\n请观察验证码是否通过。"
    return f"❌ 滑块处理失败：{detail}"
