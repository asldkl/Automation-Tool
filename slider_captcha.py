# -*- coding: utf-8 -*-
"""
滑块验证自动处理（YOLO 缺口定位版）

用用户自训练的 YOLOv8 ONNX 模型（best.onnx，类别: gap=缺口 / slider=滑块 / puzzle=拼图块）
在整屏截图中定位缺口与拼图块，计算拖动距离后拟人拖动。
- 与旧版（自动滑块验证/集成代码）的区别：缺口定位由 YOLO 完成，**无需框选背景/拼图/轨道区域**
- 拖动距离 = 缺口中心x − 拼图块中心x（puzzle 缺失时退用 slider 类），可加微调偏移
- 推理用 onnxruntime（随 rapidocr 打包），不需要 torch/ultralytics
- 默认关闭：设置→全局设置→「滑块验证（YOLO）」启用后生效
"""
import json
import os
import random
import time

import cv2
import numpy as np

import config

MODEL_FILENAME = "best.onnx"
INPUT_SIZE = 640
CLASS_NAMES_FALLBACK = {0: "gap", 1: "slider", 2: "puzzle"}
CLASS_GAP, CLASS_SLIDER, CLASS_PUZZLE = "gap", "slider", "puzzle"
# 拖动后等待复核时间
DRAG_RECHECK_WAIT_SECONDS = 2.5

_session = None
_session_model_path = ""
_session_names = None


def is_enabled(settings):
    """滑块 YOLO 处理是否启用（权重文件存在性在 solve 时再查，避免每次登录读盘）"""
    return bool(settings.get("slider_yolo_enabled", False))


def resolve_model_path():
    """定位 best.onnx：resource_path（兼容打包）→ exe/项目目录 → 当前目录"""
    candidates = [
        config.resource_path(MODEL_FILENAME),
        os.path.join(os.path.dirname(os.path.abspath(config.__file__)), MODEL_FILENAME),
        os.path.join(os.getcwd(), MODEL_FILENAME),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""


def _parse_names_from_metadata(meta_map):
    """从 ONNX 元数据解析类别名（Ultralytics 导出为 JSON dict 字符串）；失败返回 None"""
    raw = meta_map.get("names") if meta_map else None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {int(k): str(v) for k, v in parsed.items()}
    except Exception:
        pass
    return None


def _get_session(model_path):
    """懒加载 onnxruntime 会话（进程内缓存），返回 (session, class_names dict)"""
    global _session, _session_model_path, _session_names
    if _session is not None and _session_model_path == model_path:
        return _session, _session_names
    import onnxruntime as ort
    sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    try:
        names = _parse_names_from_metadata(sess.get_modelmeta().custom_metadata_map)
    except Exception:
        names = None
    if not names:
        names = dict(CLASS_NAMES_FALLBACK)
    _session = sess
    _session_model_path = model_path
    _session_names = names
    print(f"🧩 滑块YOLO模型已加载：{os.path.basename(model_path)}（类别: {names}）")
    return _session, _session_names


def letterbox(image_bgr, size=INPUT_SIZE):
    """等比例缩放并填充到 size×size，返回 (input_tensor [1,3,640,640] float, scale, dw, dh)
    dw/dh 为内容放置的整数偏移（左右/上下各一半留白取整），回映射用同值"""
    h, w = image_bgr.shape[:2]
    scale = min(size / w, size / h)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(image_bgr, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    dw, dh = (size - new_w) // 2, (size - new_h) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[dh:dh + new_h, dw:dw + new_w] = resized
    tensor = canvas.astype(np.float32) / 255.0
    tensor = tensor.transpose(2, 0, 1)[np.newaxis, ...]  # HWC → 1CHW
    return tensor, scale, dw, dh


def _nms(boxes, scores, iou_threshold=0.45):
    """简单 numpy NMS，返回保留索引（按分数降序）"""
    if len(boxes) == 0:
        return []
    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / np.maximum(1e-9, areas[i] + areas[rest] - inter)
        order = rest[iou <= iou_threshold]
    return keep


def _scale_boxes_back(boxes_xyxy, scale, dw, dh, img_w, img_h):
    """letterbox 坐标映射回原始截图坐标"""
    boxes = boxes_xyxy.copy()
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - dw) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - dh) / scale
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, img_w - 1)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, img_h - 1)
    return boxes


def detect_targets(image_bgr, confidence=0.35, model_path=None):
    """整屏截图跑 YOLO，返回按置信度降序的检测列表：
    [{"class": "gap"/"slider"/"puzzle", "conf": 0.xx, "box": [x1,y1,x2,y2], "center": (cx,cy)}]"""
    path = model_path or resolve_model_path()
    if not path:
        raise RuntimeError("未找到模型权重文件 best.onnx（请放到程序目录）")
    sess, names = _get_session(path)
    img_h, img_w = image_bgr.shape[:2]
    tensor, scale, dw, dh = letterbox(image_bgr)
    outputs = sess.run(None, {sess.get_inputs()[0].name: tensor})
    out = outputs[0]  # [1, 4+nc, 8400]
    out = np.squeeze(out, axis=0)  # [4+nc, 8400]
    num_classes = out.shape[0] - 4
    boxes_cxcywh = out[:4].T          # [8400, 4]
    class_scores = out[4:].T          # [8400, nc]
    class_ids = class_scores.argmax(axis=1)
    confidences = class_scores.max(axis=1)

    keep_mask = confidences >= float(confidence)
    if not keep_mask.any():
        return []
    boxes_cxcywh = boxes_cxcywh[keep_mask]
    confidences = confidences[keep_mask]
    class_ids = class_ids[keep_mask]

    # cxcywh → xyxy（letterbox 空间）
    xyxy = np.empty_like(boxes_cxcywh)
    xyxy[:, 0] = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
    xyxy[:, 1] = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
    xyxy[:, 2] = boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2
    xyxy[:, 3] = boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2

    # 按类别分别 NMS 后合并，再映射回原图坐标
    detections = []
    raw_boxes = []
    for cls_id in np.unique(class_ids):
        idx = np.where(class_ids == cls_id)[0]
        keep = _nms(xyxy[idx], confidences[idx])
        for i in keep:
            raw_idx = int(idx[i])
            detections.append({
                "class_id": int(cls_id),
                "class": names.get(int(cls_id), str(cls_id)),
                "conf": float(confidences[raw_idx]),
            })
            raw_boxes.append(raw_idx)
    if not detections:
        return []
    boxes_orig = _scale_boxes_back(xyxy[raw_boxes], scale, dw, dh, img_w, img_h)
    for det, box in zip(detections, boxes_orig):
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        det["box"] = [x1, y1, x2, y2]
        det["center"] = (int((x1 + x2) / 2), int((y1 + y2) / 2))
    detections.sort(key=lambda d: -d["conf"])
    return detections


def compute_drag_distance(detections, offset=0):
    """根据检测结果计算拖动距离：缺口中心x − 拼图块中心x（无 puzzle 退用 slider）。
    返回 (distance 或 None, detail)"""
    gap = next((d for d in detections if d["class"] == CLASS_GAP), None)
    piece = next((d for d in detections if d["class"] == CLASS_PUZZLE), None)
    if piece is None:
        piece = next((d for d in detections if d["class"] == CLASS_SLIDER), None)
    if gap is None or piece is None:
        return None, f"检测结果不足以计算拖动距离（{[d['class'] for d in detections]}）"
    distance = int(round(gap["center"][0] - piece["center"][0])) + int(offset or 0)
    return distance, (f"gap中心x={gap['center'][0]}(conf {gap['conf']:.2f}) "
                      f"块中心x={piece['center'][0]}(conf {piece['conf']:.2f}) → 距离 {distance}px")


def _human_drag(x1, y1, x2, y2):
    """拟人化拖动滑块：先快后慢（smoothstep）+ 随机停顿 + 到达微调（沿用旧版实现）"""
    import pyautogui
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


def _capture_screen_bgr():
    """彩色全屏截图 → BGR numpy 数组"""
    import pyautogui
    shot = pyautogui.screenshot()
    try:
        arr = np.array(shot)
    finally:
        try:
            shot.close()
        except Exception:
            pass
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _hide_overlay():
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


def solve_slider_yolo(app, stop_event=None, max_attempts=None, manage_overlay=True):
    """YOLO 定位 + 拟人拖动，最多尝试 max_attempts 次（每次拖完重新检测复核）。

    返回 (found, solved, detail)：
      found=False → 屏幕上没检测到滑块元素（调用方可继续走其他处理，如 AI 点击验证）
      found=True, solved=True  → 拖动完成后复核缺口已消失
      found=True, solved=False → 检测到滑块但 N 次拖动后仍未通过（需手动）
    """
    settings = getattr(app, "settings", None) or {}
    if not is_enabled(settings):
        return False, False, "滑块YOLO处理未启用"
    model_path = resolve_model_path()
    if not model_path:
        return False, False, f"未找到权重文件 {MODEL_FILENAME}"
    try:
        confidence = float(settings.get("slider_yolo_confidence", 0.35) or 0.35)
    except (TypeError, ValueError):
        confidence = 0.35
    confidence = min(0.9, max(0.1, confidence))
    try:
        offset = int(settings.get("slider_yolo_drag_offset", 0) or 0)
    except (TypeError, ValueError):
        offset = 0
    try:
        attempts = int(max_attempts or settings.get("slider_yolo_max_attempts", 3) or 3)
    except (TypeError, ValueError):
        attempts = 3
    attempts = max(1, min(attempts, 6))

    overlay_hidden = _hide_overlay() if manage_overlay else False
    try:
        for attempt in range(1, attempts + 1):
            if stop_event is not None and stop_event.is_set():
                return False, False, "已停止"
            image = _capture_screen_bgr()
            try:
                detections = detect_targets(image, confidence=confidence, model_path=model_path)
            except Exception as e:
                return False, False, f"YOLO推理失败：{e}"
            gap = next((d for d in detections if d["class"] == CLASS_GAP), None)
            if gap is None:
                if attempt == 1:
                    # 首次就检测不到缺口：屏幕上大概率不是滑块验证
                    return False, False, "未检测到滑块元素（gap）"
                # 拖动后复核：缺口消失 → 通过
                return True, True, f"第{attempt - 1}次拖动后缺口已消失"
            distance, drag_detail = compute_drag_distance(detections, offset=offset)
            if distance is None:
                return True, False, drag_detail
            piece = next((d for d in detections if d["class"] == CLASS_PUZZLE), None) \
                or next((d for d in detections if d["class"] == CLASS_SLIDER), None)
            print(f"🧩 滑块YOLO 第{attempt}/{attempts}次：{drag_detail}")
            sx, sy = piece["center"]
            ex = int(sx + distance)
            if not _human_drag(sx, sy, ex, sy):
                return True, False, "拖动执行失败"
            if attempt < attempts:
                time.sleep(DRAG_RECHECK_WAIT_SECONDS)
        # 轮次用尽：再检测一次确认缺口是否仍在
        image = _capture_screen_bgr()
        try:
            detections = detect_targets(image, confidence=confidence, model_path=model_path)
        except Exception as e:
            return True, False, f"复核推理失败：{e}"
        still_gap = any(d["class"] == CLASS_GAP for d in detections)
        if still_gap:
            return True, False, f"{attempts}次拖动后缺口仍在，请手动完成"
        return True, True, "拖动后缺口已消失"
    finally:
        _show_overlay(overlay_hidden)


def test_slider_yolo(app):
    """设置窗口「测试」按钮：对当前屏幕跑一次检测+处理（无滑块时只报告未检测到）"""
    import threading

    def _run():
        print("🧩 滑块YOLO测试开始（3秒后截图，请把测试画面摆在前台）...")
        time.sleep(3)
        found, solved, detail = solve_slider_yolo(app, stop_event=getattr(app, "_stop_event", None))
        if not found:
            print(f"ℹ️ 滑块YOLO测试：{detail}")
        else:
            print(f"{'✅' if solved else '❌'} 滑块YOLO测试结束：{detail}")

    threading.Thread(target=_run, daemon=True).start()
