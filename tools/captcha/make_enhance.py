# -*- coding: utf-8 -*-
"""对照实验：原图 vs 灰度+CLAHE vs 边缘图，看图块里隐藏的字是否变得可见。

用法：python make_enhance.py 1234 [out_name]
输出：%TEMP%\enh_<name>.png —— 上排原图、中排灰度+CLAHE、下排 Sobel 边缘
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

NAME = sys.argv[1] if len(sys.argv) > 1 else "1234"


def load_bgr(path):
    return np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()


def main():
    bgr = load_bgr(os.path.join(FOLDER, NAME + ".png"))
    tiles = avc.detect_image_tiles(bgr)
    cy_all = [t[1] for t in tiles]
    mid = (min(cy_all) + max(cy_all)) / 2.0
    top = sorted([t for t in tiles if t[1] < mid], key=lambda t: t[0])
    bot = sorted([t for t in tiles if t[1] >= mid], key=lambda t: t[0])
    ordered = top + bot

    answer = {int(c) for c in NAME if c.isdigit()}
    cw, ch = 300, 302

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    panels = {"gray": [], "edge": [], "orig": []}
    for i, (x, y, tw, th) in enumerate(ordered):
        crop = bgr[y:y + th, x:x + tw]
        crop = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_CUBIC)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        enh = clahe.apply(gray)
        enh_bgr = cv2.cvtColor(enh, cv2.COLOR_GRAY2BGR)
        gx = cv2.Sobel(enh, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(enh, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        mag = np.clip(mag / max(1.0, mag.max()) * 255, 0, 255).astype(np.uint8)
        edge_bgr = cv2.cvtColor(mag, cv2.COLOR_GRAY2BGR)

        idx = i + 1
        for key, panel in (("orig", crop.copy()), ("gray", enh_bgr), ("edge", edge_bgr)):
            if idx in answer:
                cv2.rectangle(panel, (0, 0), (cw - 2, ch - 2), (0, 200, 0), 5)
            cv2.rectangle(panel, (4, 4), (76, 52), (0, 0, 0), -1)
            cv2.putText(panel, f"{idx}{key[0]}", (10, 44), cv2.FONT_HERSHEY_SIMPLEX,
                        1.1, (255, 255, 255), 3)
            panels[key].append(panel)

    for key, tiles_p in panels.items():
        canvas = np.zeros((ch * 2, cw * 3, 3), dtype=np.uint8)
        for i, panel in enumerate(tiles_p):
            r, c = divmod(i, 3)
            canvas[r * ch:(r + 1) * ch, c * cw:(c + 1) * cw] = panel
        out = os.path.join(OUT_DIR, f"enh_{NAME}_{key}.png")
        cv2.imencode(".png", canvas)[1].tofile(out)
        print(f"{NAME}[{key}] 答案={sorted(answer)} -> {out}")


if __name__ == "__main__":
    main()
