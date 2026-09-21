# -*- coding: utf-8 -*-
"""只读探针：看看 测试1 这批图的尺寸、图块检出、OCR 目标字是否正常。
不做任何判定，不调 API。
"""
import os
import re
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOLDER = os.environ.get("FOLDER", os.path.join(ROOT, "图片文字点击验证例图", "测试1"))
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402

TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def main():
    print(f"目录 = {FOLDER}", flush=True)
    engine = utils._get_ocr_engine()
    names = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".png"))
    print(f"共 {len(names)} 张\n" + "=" * 88, flush=True)
    bad = 0
    for name in names:
        bgr = np.array(Image.open(os.path.join(FOLDER, name)).convert("RGB"))[:, :, ::-1].copy()
        h, w = bgr.shape[:2]
        tiles = avc.detect_image_tiles(bgr)
        res, _ = engine(bgr)
        full = "".join(str(i[1]) for i in (res or []))
        m = TXT_RE.search(full)
        ch = m.group(1) if m else ""
        ok = (len(tiles) == 6) and bool(ch)
        bad += (not ok)
        print(f"{name:14s} {w}x{h}  图块={len(tiles)}  {'✅' if ok else '⚠️'}  "
              f"目标字={ch!r}  答案={answer_of(name)}", flush=True)
        print(f"    OCR全文: {full.strip()[:90]!r}", flush=True)
        if len(tiles) != 6:
            print(f"    图块坐标: {tiles}", flush=True)
    print("=" * 88, flush=True)
    print(f"异常 {bad}/{len(names)}", flush=True)


if __name__ == "__main__":
    main()
