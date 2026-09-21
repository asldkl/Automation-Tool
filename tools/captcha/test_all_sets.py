# -*- coding: utf-8 -*-
"""一次性把「图片文字点击验证例图」下三个集合全部跑一遍字形模板匹配。

集合：根目录(6) / 测试(8) / 测试1(11)
输出：
  - 终端逐张明细（目标字、答案、选中、逐块分数、conf）
  - 汇总：阈值法 / 取前 k 名 / 置信度门控(conf>0.12) 的覆盖率与精度
  - 每个集合一张原图版判定图 → .workbuddy/out/captcha_out/verdict_all_<tag>.png
"""
import os
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, "图片文字点击验证例图")
OUT = os.path.join(ROOT, ".workbuddy", "out", "captcha_out")
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_match import GlyphMatcher, solve  # noqa: E402

SETS = [
    ("根目录", BASE, "_root"),
    ("测试", os.path.join(BASE, "测试"), "_t"),
    ("测试1", os.path.join(BASE, "测试1"), "_t1"),
]

TW, TH = 268, 270
HDR, FTR = 54, 32
CN_FONT = r"C:\Windows\Fonts\msyh.ttc"
THR = float(os.environ.get("THRESHOLD", "0.37"))
GATE = float(os.environ.get("GATE", "0.12"))
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


def render_row(name, ch, answer, picked, scores, conf, coords, bgr):
    row = np.full((HDR + TH + FTR, TW * 6, 3), 255, np.uint8)
    exact = picked == answer
    row = draw_cn(row, (8, 3), f"{name}   目标字「{ch}」   答案 {answer}   选中 {picked}",
                  17, (30, 30, 30))
    row = draw_cn(row, (8, 26), f"{'全对' if exact else f'错（应选 {answer}）'}"
                  f"   置信 {conf:+.3f}", 15, (40, 150, 40) if exact else (200, 60, 60))
    for i, (x, y, tw, th) in enumerate(coords, 1):
        t = cv2.resize(bgr[y:y + th, x:x + tw], (TW, TH), interpolation=cv2.INTER_CUBIC)
        sel, tru = i in picked, i in answer
        col = COL_TP if (sel and tru) else COL_FP if sel else COL_FN if tru else COL_TN
        cv2.rectangle(t, (0, 0), (TW - 1, TH - 1), col, 7)
        cv2.rectangle(t, (6, 6), (56, 48), (0, 0, 0), -1)
        cv2.putText(t, str(i), (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (255, 255, 255), 3)
        cv2.rectangle(t, (6, TH - 28), (170, TH - 5), (0, 0, 0), -1)
        cv2.putText(t, f"{scores[i-1]:+.3f}", (11, TH - 11),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2)
        row[HDR:HDR + TH, (i - 1) * TW:i * TW] = t
        row = draw_cn(row, ((i - 1) * TW + TW - 64, HDR + TH + 3),
                      "已选" if sel else "未选", 16, COL_TP if sel else (150, 150, 150))
        row = draw_cn(row, ((i - 1) * TW + 6, HDR + TH + 3),
                      "真值" if tru else "干扰", 15, (60, 120, 60) if tru else (170, 100, 100))
    return row, exact


def main():
    os.makedirs(OUT, exist_ok=True)
    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()
    print(f"字体 = {[os.path.basename(f) for f in matcher.fonts]}   "
          f"阈值 = {THR:.2f}   门限 = {GATE:.2f}", flush=True)

    gt = {"n": 0, "ok": 0, "topk": 0, "auto": 0, "auto_ok": 0, "def": 0, "def_ok": 0}
    set_stats = []

    for label, folder, tag in SETS:
        names = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png"))
        print("\n" + "=" * 96, flush=True)
        print(f"## {label}   ({folder})   共 {len(names)} 张", flush=True)
        print("=" * 96, flush=True)
        st = {"n": 0, "ok": 0, "topk": 0, "auto": 0, "auto_ok": 0, "def": 0, "def_ok": 0}
        rows = []
        for name in names:
            bgr = np.array(Image.open(os.path.join(folder, name)).convert("RGB"))[:, :, ::-1].copy()
            answer = answer_of(name)
            res, _ = engine(bgr)
            m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
            ch = m.group(1) if m else ""
            coords = avc.detect_image_tiles(bgr)
            tiles = [bgr[y:y + th, x:x + tw].copy() for (x, y, tw, th) in coords]
            t0 = time.time()
            r = solve(tiles, ch, matcher, threshold=THR)
            el = time.time() - t0
            picked, scores, conf = r["picked"], r["scores"], r["confidence"]
            topk = sorted(sorted(range(1, 7), key=lambda i: -scores[i - 1])[:len(answer)])
            exact, okk = picked == answer, topk == answer
            auto = conf > GATE

            st["n"] += 1
            st["ok"] += exact
            st["topk"] += okk
            if auto:
                st["auto"] += 1
                st["auto_ok"] += exact
            else:
                st["def"] += 1
                st["def_ok"] += exact

            flag = "✅" if exact else "❌"
            gate = "自动" if auto else "兜底"
            print(f"{name:14s} 字={ch!r} 答案={answer} 选中={picked} {flag} "
                  f"conf={conf:+.3f} [{gate}] {el:.1f}s", flush=True)
            print(f"               分数 {[f'{s:+.3f}' for s in scores]}   "
                  f"取前{len(answer)}名={topk} {'✅' if okk else '❌'}   "
                  f"图块={len(coords)}", flush=True)
            row, _ = render_row(name, ch, answer, picked, scores, conf, coords, bgr)
            rows.append(row)

        legend = np.full((42, TW * 6, 3), 255, np.uint8)
        legend = draw_cn(legend, (8, 3),
                         f"【{label}】{st['ok']}/{st['n']} 全对    "
                         f"按分数取前k名 {st['topk']}/{st['n']}    "
                         f"门控自动 {st['auto']} 张(对{st['auto_ok']}) / 转兜底 {st['def']} 张(对{st['def_ok']})",
                         20, (20, 20, 20))
        x = 8
        for txt, c in (("绿=选中且正确", COL_TP), ("红=误选", COL_FP),
                       ("橙=该选没选", COL_FN), ("灰=未选且正确", COL_TN)):
            cv2.rectangle(legend, (x, 28), (x + 20, 40), c, -1)
            legend = draw_cn(legend, (x + 26, 26), txt, 14, (40, 40, 40))
            x += 26 + len(txt) * 16 + 22
        sheet = np.vstack([legend] + rows)
        p = os.path.join(OUT, f"verdict_all{tag}.png")
        ok, buf = cv2.imencode(".png", sheet)
        with open(p, "wb") as fh:
            fh.write(buf.tobytes())
        print(f"→ 判定图 {p}   ({sheet.shape[1]}x{sheet.shape[0]})", flush=True)

        set_stats.append((label, st))
        for k in gt:
            gt[k] += st[k]

    print("\n" + "#" * 96, flush=True)
    print("汇总（三个集合合并）", flush=True)
    print("#" * 96, flush=True)
    for label, st in set_stats:
        n = st["n"]
        print(f"  {label:6s} n={n:2d}  阈值法 {st['ok']:2d}/{n} ({st['ok']/n*100:5.1f}%)   "
              f"取前k名 {st['topk']:2d}/{n} ({st['topk']/n*100:5.1f}%)   "
              f"门控自动 {st['auto']:2d} 张，其中对 {st['auto_ok']:2d}"
              f"（精度 {st['auto_ok']/st['auto']*100 if st['auto'] else 0:.0f}%，"
              f"覆盖 {st['auto']/n*100:.0f}%）", flush=True)
    n = gt["n"]
    acc = gt["auto_ok"] / gt["auto"] * 100 if gt["auto"] else 0
    print(f"  {'合计':6s} n={n:2d}  阈值法 {gt['ok']:2d}/{n} ({gt['ok']/n*100:5.1f}%)   "
          f"取前k名 {gt['topk']:2d}/{n} ({gt['topk']/n*100:5.1f}%)   "
          f"门控自动 {gt['auto']:2d}/{n}（精度 {acc:.1f}%）  "
          f"兜底 {gt['def']:2d} 张，其中对 {gt['def_ok']:2d}", flush=True)


if __name__ == "__main__":
    main()
