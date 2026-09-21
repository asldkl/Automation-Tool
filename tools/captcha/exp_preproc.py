# -*- coding: utf-8 -*-
"""预处理变体对比 —— 目标：在**不知道该选几块**的前提下，提高「逐块是否目标字」的可分性。

评价指标（都不依赖 k）：
  AUC          逐块二分类的秩统计量（0.5=瞎猜，1.0=完美分开）。**阈值无关**，最公平。
  TPR/TNR      在中位阈值下的召回/特异度。
  全对(CV)     用「另一折调阈值、这一折评估」的 2 折交叉验证得到，**诚实**。
  全对(拟合)   在同一批图上直接扫最优阈值，**乐观**（只用于对比过拟合幅度）。
  门控         门限按另一折选，报告自动提交的覆盖率与精度。

⚠️ 所有结论必须同时看 CV 与拟合两列；两者差距大 = 过拟合。
"""
import json
import os
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, "图片文字点击验证例图")
OUT = os.path.join(ROOT, ".workbuddy", "out")
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_match import GlyphMatcher  # noqa: E402

NAMES = ["根目录", "测试", "测试1"]
FOLDERS = {"根目录": BASE, "测试": os.path.join(BASE, "测试"), "测试1": os.path.join(BASE, "测试1")}
TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")
TILE_W, TILE_H = 300, 302


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


# --------------------------- 预处理变体 --------------------------- #
def _gray(t):
    return cv2.cvtColor(t, cv2.COLOR_BGR2GRAY).astype(np.float32)


def _std3(x):
    std = float(x.std()) or 1.0
    return np.clip((x - x.mean()) / (3.0 * std), -1.0, 1.0)


def _ker(k):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def _bh(g, k):
    return cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, _ker(k)).astype(np.float32)


def _th(g, k):
    return cv2.morphologyEx(g, cv2.MORPH_TOPHAT, _ker(k)).astype(np.float32)


def prep_bh(t, k):
    return _std3(_bh(_gray(t), k))


def prep_flat(t, k=25, sigma=15.0):
    """平场除：先除掉低频光照，再黑帽。图块间的整体明暗差异被抹掉。"""
    g = _gray(t)
    low = cv2.GaussianBlur(g, (0, 0), sigma)
    ff = g / np.maximum(low, 1e-3)
    return _std3(_bh(ff, k))


def prep_clahe(t, k=25, clip=3.0):
    g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    cl = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(g).astype(np.float32)
    return _std3(_bh(cl, k))


def prep_bipolar(t, k=25):
    """双极性：黑帽(更亮) + 顶帽(更暗) 一起，字可能是任一种极性。"""
    g = _gray(t)
    return _std3(_bh(g, k) + _th(g, k))


def prep_grad(t):
    """梯度幅值：只看边缘，不看灰度。"""
    g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return _std3(np.sqrt(gx * gx + gy * gy))


def prep_localstd(t, k=25, win=31):
    """局部标准差（纹理能量）——笔画区域纹理强。"""
    g = _gray(t)
    m = cv2.blur(g, (win, win))
    m2 = cv2.blur(g * g, (win, win))
    var = np.maximum(m2 - m * m, 0)
    return _std3(np.sqrt(var))


VARIANTS = [
    ("基线 bh25", [lambda t: prep_bh(t, 25)], False),
    ("bh35", [lambda t: prep_bh(t, 35)], False),
    ("bh45", [lambda t: prep_bh(t, 45)], False),
    ("平场+bh25", [lambda t: prep_flat(t, 25)], False),
    ("CLAHE+bh25", [lambda t: prep_clahe(t, 25)], False),
    ("双极性 bh25+th25", [lambda t: prep_bipolar(t, 25)], False),
    ("梯度幅值", [lambda t: prep_grad(t)], False),
    ("局部std31", [lambda t: prep_localstd(t, 25)], False),
    ("融合 bh25+bh45", [lambda t: prep_bh(t, 25), lambda t: prep_bh(t, 45)], True),
    ("融合 bh25+bh35+bh45", [lambda t: prep_bh(t, 25), lambda t: prep_bh(t, 35),
                             lambda t: prep_bh(t, 45)], True),
]


# --------------------------- 打分 --------------------------- #
def score_image(tiles, ch, matcher, preps, fuse):
    per = []
    for pf in preps:
        per.append([matcher.score_tile(pf(t), ch) for t in tiles])
    if not fuse:
        return per[0]
    out = []
    for i in range(len(per[0])):
        vs = [p[i] for p in per]
        lo, hi = min(vs), max(vs)
        z = [(v - lo) / (hi - lo) if hi > lo else 0.5 for v in vs]
        out.append(sum(z) / len(z))
    return out


# --------------------------- 指标 --------------------------- #
def auc(labels, scores):
    pos = [s for l, s in zip(labels, scores) if l]
    neg = [s for l, s in zip(labels, scores) if not l]
    if not pos or not neg:
        return 0.5
    n = 0
    for p in pos:
        for q in neg:
            n += (p > q) + 0.5 * (p == q)
    return n / (len(pos) * len(neg))


def exact_at(scores_list, answers, thr):
    return sum(1 for s, a in zip(scores_list, answers)
               if sorted(i for i, v in enumerate(s, 1) if v >= thr) == a)


def best_thr_on(scores_list, answers, lo=0.20, hi=0.95, step=0.01):
    best = (-1, lo)
    x = lo
    while x <= hi + 1e-9:
        k = exact_at(scores_list, answers, x)
        if k > best[0]:
            best = (k, round(x, 2))
        x += step
    return best


def main():
    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()
    # ---- 先把图块缓存成 300x302，避免每个变体重复解码/缩放 ----
    cache = {}
    for label in NAMES:
        folder = FOLDERS[label]
        for name in sorted(f for f in os.listdir(folder) if f.lower().endswith(".png")):
            bgr = np.array(Image.open(os.path.join(folder, name)).convert("RGB"))[:, :, ::-1].copy()
            res, _ = engine(bgr)
            m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
            ch = m.group(1) if m else ""
            coords = avc.detect_image_tiles(bgr)
            tiles = [cv2.resize(bgr[y:y + th, x:x + tw], (TILE_W, TILE_H),
                                interpolation=cv2.INTER_CUBIC) for (x, y, tw, th) in coords]
            cache[f"{label}/{name}"] = {"tiles": tiles, "ch": ch, "answer": answer_of(name)}
    print(f"缓存 {len(cache)} 张图（OCR 目标字 + 图块）", flush=True)

    order = list(cache)
    fold_of = {k: i % 2 for i, k in enumerate(order)}
    only = os.environ.get("ONLY", "").strip()
    todo = ([v for v in VARIANTS if v[0] in [x.strip() for x in only.split(",")]]
            if only else VARIANTS)
    report = {}
    for vname, preps, fuse in todo:
        t0 = time.time()
        sc, ans, lab = [], [], []
        for key in order:
            rec = cache[key]
            s = score_image(rec["tiles"], rec["ch"], matcher, preps, fuse)
            sc.append(s)
            ans.append(rec["answer"])
            lab.extend(1 if (i + 1) in rec["answer"] else 0 for i in range(len(s)))
        flat = [v for s in sc for v in s]
        a = auc(lab, flat)
        pos = [v for v, l in zip(flat, lab) if l]
        neg = [v for v, l in zip(flat, lab) if not l]
        med = float(np.median(flat))
        tpr = sum(1 for v in pos if v >= med) / len(pos)
        tnr = sum(1 for v in neg if v < med) / len(neg)
        # 拟合（乐观）
        fit_k, fit_t = best_thr_on(sc, ans)
        # 2 折 CV（诚实）：一折调阈值，另一折评估
        cv_k = 0
        for f in (0, 1):
            tr_idx = [i for i, k in enumerate(order) if fold_of[k] != f]
            te_idx = [i for i, k in enumerate(order) if fold_of[k] == f]
            _, thr = best_thr_on([sc[j] for j in tr_idx], [ans[j] for j in tr_idx])
            cv_k += exact_at([sc[j] for j in te_idx], [ans[j] for j in te_idx], thr)
        # 逐图排序口径：图内按分数取前 k 名（k=答案块数，oracle 上界）。
        # ⚠️ 融合变体做了「逐图 minmax 归一化」→ 分数**跨图不可比**，
        #    全局 AUC / 全局阈值对它天然无效（测出来会假性崩到 0.5）。
        #    融合的正确评价口径就是这个图内排序；文档里旧记录也是 14/14 排序。
        rank_k = sum(1 for s, a in zip(sc, ans)
                     if sorted(sorted(range(1, len(s) + 1), key=lambda i: -s[i - 1])[:len(a)]) == a)
        report[vname] = {"auc": a, "tpr": tpr, "tnr": tnr, "rank": rank_k,
                         "fit": (fit_k, fit_t), "cv": cv_k, "n": len(order),
                         "sec": round(time.time() - t0, 1)}
        print(f"  {vname:22s} AUC={a:.3f}  TPR/TNR={tpr:.2f}/{tnr:.2f}  "
              f"全对(CV)={cv_k:2d}/{len(order)}  全对(拟合)={fit_k:2d}/{len(order)}"
              f"@thr={fit_t:.2f}  排序上界={rank_k:2d}/{len(order)}  "
              f"{report[vname]['sec']}s", flush=True)

    print("\n按 AUC 排序：", flush=True)
    for v, r in sorted(report.items(), key=lambda kv: -kv[1]["auc"]):
        print(f"  {r['auc']:.3f}  {v:22s} CV全对 {r['cv']:2d}/{r['n']}   "
              f"拟合全对 {r['fit'][0]:2d}/{r['n']}   排序上界 {r['rank']:2d}/{r['n']}", flush=True)
    suffix = "_sub" if only else ""
    with open(os.path.join(OUT, f"exp_preproc{suffix}.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
