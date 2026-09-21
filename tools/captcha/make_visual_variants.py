# -*- coding: utf-8 -*-
"""离线可视化实验：对图块做多种变换，看哪种能把隐藏的字「剥」出来。

输出：%TEMP%\v_<图名>_<变换>.png，每张 = 6 个图块（3列2行），答案块描绿框。
不调用任何 API —— 先用人眼确认「字形在某种变换下是否清晰可辨」，
这决定了后面该不该继续在预处理/模型上投入。

用法：python make_visual_variants.py 1234 [26 ...]
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image

def _find_root(start):
    """向上找 captcha_glyph_match.py 所在目录当仓库根（脚本放哪层都不会算错）"""
    p = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(p, "captcha_glyph_match.py")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            raise RuntimeError("找不到仓库根（captcha_glyph_match.py）")
        p = parent


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(ROOT, "图片文字点击验证例图")
OUT_DIR = os.path.join(ROOT, ".workbuddy", "out")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402

CW, CH = 300, 302


def load_bgr(path):
    return np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()


def order_tiles(tiles):
    cy = [t[1] for t in tiles]
    mid = (min(cy) + max(cy)) / 2.0
    return (sorted([t for t in tiles if t[1] < mid], key=lambda t: t[0])
            + sorted([t for t in tiles if t[1] >= mid], key=lambda t: t[0]))


def _norm(x):
    """按 ±3σ 截断后拉伸到 0-255，避免个别极值吃掉动态范围"""
    x = x.astype(np.float32)
    s = x.std() or 1.0
    m = x.mean()
    x = np.clip((x - m) / (3.0 * s), -1, 1)
    return ((x + 1) * 127.5).astype(np.uint8)


def t_dog(gray):
    """带通：小核减大核，去掉大尺度渐变与小尺度纹理，留下中等尺度的笔画结构"""
    g = gray.astype(np.float32)
    return _norm(cv2.GaussianBlur(g, (0, 0), 3) - cv2.GaussianBlur(g, (0, 0), 12))


def t_blur(gray):
    """重低通：纹理全糊掉，字形退化成一块干净的光斑/暗斑"""
    return cv2.GaussianBlur(gray, (0, 0), 10)


def t_downup(gray):
    """极端降采样再放大：等效低通，成本最低的版本"""
    small = cv2.resize(gray, (28, 28), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (CW, CH), interpolation=cv2.INTER_NEAREST)


def t_chroma(bgr):
    """色度异常：抛弃明度，只看 a/b 通道，找是不是用色相差异画的字"""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    a = lab[:, :, 1].astype(np.float32) - 128
    b = lab[:, :, 2].astype(np.float32) - 128
    mag = np.sqrt(a * a + b * b)
    return _norm(mag)


def t_blackhat(gray):
    """黑帽：专治「浅底上的深色细笔画」，笔画宽度小于核就会被留下"""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
    return _norm(cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k).astype(np.float32))


VARIANTS = {
    "dog": lambda bgr, gray: t_dog(gray),
    "blur": lambda bgr, gray: t_blur(gray),
    "downup": lambda bgr, gray: t_downup(gray),
    "chroma": lambda bgr, gray: t_chroma(bgr),
    "blackhat": lambda bgr, gray: t_blackhat(gray),
}


def main():
    names = sys.argv[1:] or ["1234"]
    for name in names:
        bgr = load_bgr(os.path.join(FOLDER, name + ".png"))
        answer = {int(c) for c in name if c.isdigit()}
        ordered = order_tiles(avc.detect_image_tiles(bgr))
        assert len(ordered) == 6, f"{name}: 检出 {len(ordered)} 块"

        crops, grays = [], []
        for (x, y, tw, th) in ordered:
            c = cv2.resize(bgr[y:y + th, x:x + tw], (CW, CH), interpolation=cv2.INTER_CUBIC)
            crops.append(c)
            grays.append(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY))

        for vname, fn in VARIANTS.items():
            canvas = np.zeros((CH * 2, CW * 3, 3), dtype=np.uint8)
            for i, (crop, gray) in enumerate(zip(crops, grays)):
                out = fn(crop, gray)
                if out.ndim == 2:
                    out = cv2.cvtColor(out, cv2.COLOR_GRAY2BGR)
                if i + 1 in answer:
                    cv2.rectangle(out, (0, 0), (CW - 2, CH - 2), (0, 200, 0), 5)
                cv2.rectangle(out, (4, 4), (60, 50), (0, 0, 0), -1)
                cv2.putText(out, str(i + 1), (16, 42), cv2.FONT_HERSHEY_SIMPLEX,
                            1.3, (255, 255, 255), 3)
                r, col = divmod(i, 3)
                canvas[r * CH:(r + 1) * CH, col * CW:(col + 1) * CW] = out
            p = os.path.join(OUT_DIR, f"v_{name}_{vname}.png")
            cv2.imencode(".png", canvas)[1].tofile(p)
            print(f"{name}[{vname}] 答案={sorted(answer)} -> {p}")


if __name__ == "__main__":
    main()
