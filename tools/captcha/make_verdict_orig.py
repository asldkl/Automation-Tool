# -*- coding: utf-8 -*-
"""和 run_glyph_test.py 同样的判定，但可视化用**原图图块**（不是黑帽预处理图），
这样人能直接看清字、核对算法选得对不对。

边框：绿=选中且正确  红=误选  橙=该选没选  灰=未选且正确
"""
import os
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOLDER = os.environ.get("FOLDER", os.path.join(ROOT, "图片文字点击验证例图", "测试1"))
TAG = os.environ.get("TAG", "")
OUT = os.path.join(ROOT, ".workbuddy", "out", "captcha_out")
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_match import GlyphMatcher, solve  # noqa: E402

TW, TH = 280, 282
HDR, FTR = 56, 34
CN_FONT = r"C:\Windows\Fonts\msyh.ttc"
THR = float(os.environ.get("THRESHOLD", "0.37"))
COL_TP, COL_FP, COL_FN, COL_TN = (60, 190, 60), (60, 60, 220), (0, 150, 245), (150, 150, 150)
TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def draw_cn(img_bgr, xy, text, size=20, color=(0, 0, 0)):
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    d.text(xy, text, fill=color[::-1], font=ImageFont.truetype(CN_FONT, size))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def main():
    os.makedirs(OUT, exist_ok=True)
    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()
    names = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".png"))
    rows, ok_t, ok_topk = [], 0, 0
    for name in names:
        bgr = np.array(Image.open(os.path.join(FOLDER, name)).convert("RGB"))[:, :, ::-1].copy()
        answer = answer_of(name)
        res, _ = engine(bgr)
        m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
        ch = m.group(1) if m else ""
        coords = avc.detect_image_tiles(bgr)
        tiles = [bgr[y:y + th, x:x + tw].copy() for (x, y, tw, th) in coords]
        r = solve(tiles, ch, matcher, threshold=THR)
        picked, scores = r["picked"], r["scores"]
        topk = sorted(sorted(range(1, 7), key=lambda i: -scores[i - 1])[:len(answer)])
        exact = picked == answer
        ok_t += exact
        ok_topk += (topk == answer)
        print(f"{name:14s} 目标字={ch!r} 答案={answer} 选中={picked} "
              f"{'✅' if exact else '❌'} conf={r['confidence']:+.3f}", flush=True)

        row = np.full((HDR + TH + FTR, TW * 6, 3), 255, np.uint8)
        row = draw_cn(row, (8, 4), f"{name}   目标字「{ch}」   答案 {answer}   选中 {picked}",
                      18, (30, 30, 30))
        row = draw_cn(row, (8, 29), f"{'结果：全对' if exact else f'结果：错（应选 {answer}）'}"
                      f"   置信 {r['confidence']:+.3f}", 16,
                      (40, 150, 40) if exact else (200, 60, 60))
        for i, (x, y, tw, th) in enumerate(coords, 1):
            # 原图图块直接缩放（不做黑帽预处理），人眼可读
            t = cv2.resize(bgr[y:y + th, x:x + tw], (TW, TH), interpolation=cv2.INTER_CUBIC)
            sel, tru = i in picked, i in answer
            col = COL_TP if (sel and tru) else COL_FP if sel else COL_FN if tru else COL_TN
            cv2.rectangle(t, (0, 0), (TW - 1, TH - 1), col, 7)
            cv2.rectangle(t, (6, 6), (60, 52), (0, 0, 0), -1)
            cv2.putText(t, str(i), (16, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
            cv2.rectangle(t, (6, TH - 30), (200, TH - 6), (0, 0, 0), -1)
            cv2.putText(t, f"{scores[i-1]:+.3f}", (12, TH - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            row[HDR:HDR + TH, (i - 1) * TW:i * TW] = t
            row = draw_cn(row, ((i - 1) * TW + TW - 72, HDR + TH + 4),
                          "已选" if sel else "未选", 17,
                          COL_TP if sel else (150, 150, 150))
            row = draw_cn(row, ((i - 1) * TW + 6, HDR + TH + 4),
                          "真值" if tru else "干扰", 16,
                          (60, 120, 60) if tru else (170, 100, 100))
        rows.append(row)

    legend = np.full((44, TW * 6, 3), 255, np.uint8)
    x = 8
    for txt, c in (("绿=选中且正确", COL_TP), ("红=误选", COL_FP),
                   ("橙=该选没选", COL_FN), ("灰=未选且正确", COL_TN)):
        cv2.rectangle(legend, (x, 13), (x + 22, 31), c, -1)
        legend = draw_cn(legend, (x + 30, 10), txt, 17, (40, 40, 40))
        x += 30 + len(txt) * 19 + 24
    sheet = np.vstack([legend] + rows)
    p = os.path.join(OUT, f"verdict_orig{TAG}.png")
    ok, buf = cv2.imencode(".png", sheet)
    with open(p, "wb") as fh:
        fh.write(buf.tobytes())
    n = len(names)
    print("=" * 88, flush=True)
    print(f"阈值法 {ok_t}/{n}   按分数取前 k 名 {ok_topk}/{n}   判定图 → {p}", flush=True)


if __name__ == "__main__":
    main()
