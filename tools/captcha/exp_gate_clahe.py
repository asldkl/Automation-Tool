# -*- coding: utf-8 -*-
"""门控形态对照：基线黑帽 vs CLAHE+黑帽（25 张）。

回答一个落地问题：**预处理带来的 AUC / CV 提升，能不能转化成"门控自动提交"的提升？**
  - 阈值法总准确率（19/25 那一路）
  - 门控：100% 精度下最多能自动提交几张（覆盖率）
  - oracle（已知块数取前 k）作为天花板参考

用法：python .workbuddy/exp_gate_clahe.py
输出：.workbuddy/out/exp_gate_clahe.txt，分数缓存 exp_gate_clahe_scores.json
"""
import json
import os
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image

_REPO_ANCHOR = "captcha_glyph_match.py"


def _find_root(start):
    """向上找带 captcha_glyph_match.py 的目录。

    路径用「向上找 captcha_glyph_match.py」的锚点写法，放在 tools/captcha/ 或 .workbuddy/ 都算得对。
    """
    p = start
    for _ in range(6):
        if os.path.exists(os.path.join(p, _REPO_ANCHOR)):
            return p
        p = os.path.dirname(p)
    return start


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "图片文字点击验证例图")
OUT = os.path.join(ROOT, ".workbuddy", "out")
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_match import (  # noqa: E402
    DEFAULT_THRESHOLD, GlyphMatcher, confidence, pick_by_2means, pick_by_threshold, prep_tile,
)

NAMES = ["根目录", "测试", "测试1"]
FOLDERS = {"根目录": BASE, "测试": os.path.join(BASE, "测试"), "测试1": os.path.join(BASE, "测试1")}
TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")
TILE_W, TILE_H = 300, 302

LOG = []


def P(*a, **kw):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    kw.setdefault("flush", True)
    print(s, **kw)


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def prep_clahe(tile_bgr, kernel=25, clip=3.0):
    """CLAHE（局部直方图均衡）+ 黑帽 + ±3σ 归一化。与 exp_preproc.py 的 CLAHE+bh25 同口径。"""
    t = cv2.resize(tile_bgr, (TILE_W, TILE_H), interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    cl = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(g).astype(np.float32)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    bh = cv2.morphologyEx(cl, cv2.MORPH_BLACKHAT, k).astype(np.float32)
    std = float(bh.std()) or 1.0
    return np.clip((bh - float(bh.mean())) / (3.0 * std), -1.0, 1.0)


VARIANTS = [("基线 bh25", lambda t: prep_tile(t, 25)),
            ("CLAHE+bh25", prep_clahe)]


def best_thr(sc, ans, lo=0.20, hi=0.95, step=0.01):
    def exact(thr):
        return sum(1 for s, a in zip(sc, ans)
                   if pick_by_threshold(s, thr) == a)
    b = (-1, lo)
    x = lo
    while x <= hi + 1e-9:
        k = exact(x)
        if k > b[0]:
            b = (k, round(x, 2))
        x += step
    return b


def gate_curve(rows, label):
    """rows: [(set, name, conf, ok, picked, answer)]；输出门限表 + 100% 精度最小门限。"""
    P(f"{'门限':>6s} {'提交数':>6s} {'提交内正确':>8s} {'精度':>8s} {'覆盖率':>8s}")
    best100 = None
    for g in (0.00, 0.06, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20, 0.25, 0.30):
        sub = [r for r in rows if r[2] > g]
        good = [r for r in sub if r[3]]
        prec = len(good) / len(sub) if sub else 0.0
        P(f"{g:6.2f} {len(sub):6d} {len(good):8d} {prec*100:7.1f}% "
          f"{len(sub)/len(rows)*100:7.1f}%")
        if prec >= 0.999 and (best100 is None or len(sub) > best100[1]):
            best100 = (g, len(sub), len(sub) / len(rows))
    if best100:
        P(f"  → 100% 精度的最佳门控：门限 {best100[0]:.2f}，自动提交 {best100[1]}/{len(rows)} "
          f"（覆盖 {best100[2]*100:.0f}%）")
    else:
        P("  → 没有任何门限做到 100% 精度")
    P("")
    return best100


def main():
    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()
    names_all = []
    for label in NAMES:
        folder = FOLDERS[label]
        for nm in sorted(f for f in os.listdir(folder) if f.lower().endswith(".png")):
            names_all.append((label, folder, nm))
    P(f"图 {len(names_all)} 张，变体 {[v[0] for v in VARIANTS]}，阈值基线 {DEFAULT_THRESHOLD}", flush=True)

    scores = {}
    for vname, prep in VARIANTS:
        t0 = time.time()
        rec = {}
        for label, folder, nm in names_all:
            bgr = np.array(Image.open(os.path.join(folder, nm)).convert("RGB"))[:, :, ::-1].copy()
            res, _ = engine(bgr)
            m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
            ch = m.group(1) if m else ""
            coords = avc.detect_image_tiles(bgr)
            tiles = [bgr[y:y + h, x:x + w] for (x, y, w, h) in coords]
            rec[f"{label}/{nm}"] = {
                "ch": ch,
                "answer": answer_of(nm),
                "scores": [matcher.score_tile(prep(t), ch) for t in tiles],
            }
        scores[vname] = rec
        P(f"  {vname:12s} 打分完成 {time.time()-t0:.1f}s", flush=True)

    with open(os.path.join(OUT, "exp_gate_clahe_scores.json"), "w", encoding="utf-8") as fh:
        json.dump(scores, fh, ensure_ascii=False, indent=1)

    for vname, _ in VARIANTS:
        rec = scores[vname]
        keys = list(rec)
        sc = [rec[k]["scores"] for k in keys]
        ans = [rec[k]["answer"] for k in keys]
        P("=" * 92)
        P(f"变体 = {vname}")
        n_thr = sum(1 for s, a in zip(sc, ans) if pick_by_threshold(s, DEFAULT_THRESHOLD) == a)
        n_2m = sum(1 for s, a in zip(sc, ans) if pick_by_2means(s) == a)
        n_rank = sum(1 for s, a in zip(sc, ans)
                     if sorted(sorted(range(1, len(s) + 1), key=lambda i: -s[i - 1])[:len(a)]) == a)
        bk, bt = best_thr(sc, ans)
        P(f"  阈值 {DEFAULT_THRESHOLD} 全对 {n_thr}/{len(sc)}   拟合最优阈值 {bt:.2f} → {bk}/{len(sc)}   "
          f"2 均值 {n_2m}/{len(sc)}   oracle(排序取前 k) {n_rank}/{len(sc)}")
        # 门控：用阈值 0.37 的选中集算 conf
        rows = []
        for k, s, a in zip(keys, sc, ans):
            p = pick_by_threshold(s, DEFAULT_THRESHOLD)
            rows.append((k.split("/")[0], k.split("/", 1)[1], confidence(s, p), p == a, p, a))
        P(f"  门控（阈值 {DEFAULT_THRESHOLD} 下的选中集）")
        gate_curve(rows, vname)
        # 未过门控的明细（谁会转人工）
        P("  conf < 0.16 的图（会转「换一组」/人工）：")
        for st, nm, c, ok, p, a in sorted(rows, key=lambda x: x[2]):
            if c <= 0.16:
                P(f"    {st:4s} {nm:16s} conf={c:+.3f} {'✅' if ok else '❌'} 选中={p} 答案={a}")
        P("")

    with open(os.path.join(OUT, "exp_gate_clahe.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    P("已写出 out/exp_gate_clahe.txt")


if __name__ == "__main__":
    main()
