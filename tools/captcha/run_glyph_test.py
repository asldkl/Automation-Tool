# -*- coding: utf-8 -*-
"""用 captcha_glyph_match（字形模板匹配）跑测试集，并输出可目视核对的判定图。

输出：
  %TEMP%/captcha_out/glyph_verdict.png   每张图一行，6 块带分数
  边框颜色：绿=选中且正确  红=误选  橙=该选没选  灰=未选且正确
"""
import os
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FOLDER = os.environ.get("FOLDER", os.path.join(ROOT, "图片文字点击验证例图"))
OUT = os.path.join(os.environ.get("TEMP", "."), "captcha_out")
TAG = os.environ.get("TAG", "")
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_match import GlyphMatcher, prep_tile, solve  # noqa: E402

TW, TH = 300, 302
HDR, FTR = 58, 40
CN_FONT = r"C:\Windows\Fonts\msyh.ttc"
THR = float(os.environ.get("THRESHOLD", "0.37"))


def answer_of(name):
    """文件名里空格/括号之前的那串数字 = 答案。'13456 (2).png' → {1,3,4,5,6}"""
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})
COL_TP = (60, 190, 60)     # 绿：选中且正确
COL_FP = (60, 60, 220)     # 红：误选
COL_FN = (0, 150, 245)     # 橙：该选没选
COL_TN = (150, 150, 150)   # 灰：未选且正确


def draw_cn(img_bgr, xy, text, size=20, color=(0, 0, 0)):
    """用 PIL 在 BGR 图上写中文（cv2.putText 不支持中文）。"""
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    f = ImageFont.truetype(CN_FONT, size)
    d.text(xy, text, fill=color[::-1], font=f)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def main():
    os.makedirs(OUT, exist_ok=True)
    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()
    names = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".png"))
    print(f"目录 = {FOLDER}")
    print(f"字体 = {[os.path.basename(f) for f in matcher.fonts]}   阈值 = {THR:.3f}")
    print("=" * 92)

    rows, ok_t, ok_topk = [], 0, 0
    for name in names:
        bgr = np.array(Image.open(os.path.join(FOLDER, name)).convert("RGB"))[:, :, ::-1].copy()
        answer = answer_of(name)
        res, _ = engine(bgr)
        m = re.search(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])",
                      "".join(str(i[1]) for i in (res or [])))
        ch = m.group(1) if m else ""
        tiles = [bgr[y:y + th, x:x + tw].copy()
                 for (x, y, tw, th) in avc.detect_image_tiles(bgr)]

        t0 = time.time()
        r = solve(tiles, ch, matcher, threshold=THR)
        el = time.time() - t0
        picked, scores = r["picked"], r["scores"]
        topk = sorted(sorted(range(1, 7), key=lambda i: -scores[i - 1])[:len(answer)])
        exact, ok_topk_hit = picked == answer, topk == answer
        ok_t += exact
        ok_topk += ok_topk_hit

        print(f"{name:11s} 目标字={ch!r}  答案={answer}  "
              f"选中={picked} {'✅ 全对' if exact else '❌'}   "
              f"置信={r['confidence']:+.3f}  {el:.1f}s")
        for i, v in enumerate(scores, 1):
            tag = ("选中✔" if i in picked else "未选 ") + ("真值" if i in answer else "干扰")
            print(f"      t{i} {tag} {v:+.3f}")
        print(f"      （参考）按分数取前 {len(answer)} 名 = {topk} "
              f"{'✅' if ok_topk_hit else '❌'}")

        # ---- 拼这一行的可视化 ----
        row = np.full((HDR + TH + FTR, TW * 6, 3), 255, np.uint8)
        hdr = f"{name}    目标字「{ch}」    答案 {answer}    选中 {picked}"
        mark = "全对" if exact else f"错（应选 {answer}）"
        row = draw_cn(row, (8, 6), hdr, 19, (30, 30, 30))
        row = draw_cn(row, (8, 31), f"结果：{mark}    置信度 {r['confidence']:+.3f}"
                      f"    耗时 {el:.1f}s", 17,
                      (40, 150, 40) if exact else (200, 60, 60))
        for i, (x, y, tw, th) in enumerate(avc.detect_image_tiles(bgr), 1):
            t = cv2.resize(bgr[y:y + th, x:x + tw], (TW, TH), interpolation=cv2.INTER_CUBIC)
            g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
            bh = avc  # noqa: F841  (仅占位，避免误用)
            prepped = prep_tile(t)
            vis = cv2.cvtColor(((prepped + 1.0) * 127.5).astype(np.uint8), cv2.COLOR_GRAY2BGR)
            sel, tru = i in picked, i in answer
            col = COL_TP if (sel and tru) else COL_FP if sel else COL_FN if tru else COL_TN
            cv2.rectangle(vis, (0, 0), (TW - 1, TH - 1), col, 6)
            cv2.rectangle(vis, (8, 8), (76, 60), (0, 0, 0), -1)
            cv2.putText(vis, str(i), (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5,
                        (255, 255, 255), 3)
            cv2.rectangle(vis, (0, TH - 36), (TW, TH), (0, 0, 0), -1)
            cv2.putText(vis, f"{scores[i - 1]:+.3f}", (10, TH - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)
            row[HDR:HDR + TH, (i - 1) * TW:i * TW] = vis
            # 中文标签必须走 PIL，cv2.putText 画中文会变问号
            row = draw_cn(row, ((i - 1) * TW + TW - 66, HDR + TH - 34),
                          "已选" if sel else "未选", 20,
                          COL_TP if sel else (150, 150, 150))
        rows.append(row)

    sheet = np.vstack(rows)
    # 顶部图例
    legend = np.full((46, sheet.shape[1], 3), 255, np.uint8)
    x = 8
    for txt, c in (("绿=选中且正确", COL_TP), ("红=误选", COL_FP),
                   ("橙=该选没选", COL_FN), ("灰=未选且正确", COL_TN)):
        cv2.rectangle(legend, (x, 14), (x + 22, 32), c, -1)
        legend = draw_cn(legend, (x + 30, 11), txt, 18, (40, 40, 40))
        x += 30 + len(txt) * 20 + 26
    sheet = np.vstack([legend, sheet])

    p = os.path.join(OUT, f"glyph_verdict{TAG}.png")
    ok, buf = cv2.imencode(".png", sheet)
    with open(p, "wb") as fh:
        fh.write(buf.tobytes())
    n = len(names)
    print("=" * 92)
    print(f"合计：阈值法 {ok_t}/{n}   "
          f"（参考）按分数取前 k 名 {ok_topk}/{n}   判定图 → {p}")


if __name__ == "__main__":
    main()
