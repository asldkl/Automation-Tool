# -*- coding: utf-8 -*-
"""优化第 2 轮：在**门控口径**下比较图像处理变体，并用交叉验证给出可信数字。

为什么换口径：`exp_preproc.py` 用逐块 AUC 选出了 CLAHE（0.985→0.997），
但 `exp_gate_clahe.py` 发现 CLAHE 让门控失去 100% 精度 —— **指标更好 ≠ 能上线**。
所以本轮直接以落地形态为准：**「100% 精度下最多能自动提交多少张」**。

三条口径（都要看，别只看最好的那个）：
  ① 阈值法 CV 全对   —— 阈值在训练折选、测试折评估（诚实）
  ② 门控 CV          —— (阈值,门限) 都在训练折选：要求训练折精度 100% 且覆盖最大；
                        再在测试折评估覆盖率与精度（**这才是上线口径**）
  ③ 拟合（同批扫）   —— 只用于看①/②的过拟合幅度

⚠️ 25 张样本量很小（CI 半宽 ±16%），结论仍需 held-out 集确认。
分数缓存到 out/gate_sweep_scores.json，可按变体增量补跑（已有变体不重算）。

用法：python tools/captcha/exp_gate_sweep.py            # 全部变体
      ONLY="clahe25" python tools/captcha/exp_gate_sweep.py
"""
import json
import os
import pickle
import re
import sys
import time

import numpy as np
from PIL import Image

_ANCHOR = "captcha_glyph_match.py"


def _find_root(start):
    p = start
    for _ in range(6):
        if os.path.exists(os.path.join(p, _ANCHOR)):
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
    DEFAULT_THRESHOLD, GATE_DEFAULT, GlyphMatcher, confidence, pick_by_2means,
    pick_by_threshold,
)

NAMES = ["根目录", "测试", "测试1"]
FOLDERS = {"根目录": BASE, "测试": os.path.join(BASE, "测试"),
           "测试1": os.path.join(BASE, "测试1")}
TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")

# (显示名, 黑帽核, 图像处理模式)
VARIANTS = [
    ("bh25（生产）", 25, "bh"),
    ("bh35", 35, "bh"),
    ("bh45", 45, "bh"),
    ("flat25", 25, "flat"),
    ("flat35", 35, "flat"),
    ("clahe25", 25, "clahe"),
    ("clahe35", 35, "clahe"),
]

TILES_PKL = os.path.join(OUT, "gate_sweep_tiles.pkl")
SCORES_JSON = os.path.join(OUT, "gate_sweep_scores.json")
REPORT_TXT = os.path.join(OUT, "exp_gate_sweep.txt")

LOG = []


def P(*a, **kw):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    kw.setdefault("flush", True)
    print(s, **kw)


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def load_tiles():
    """图块 + 目标字 + 答案（OCR 只跑一次，缓存复用）"""
    if os.path.exists(TILES_PKL):
        with open(TILES_PKL, "rb") as f:
            cache = pickle.load(f)
        P("图块缓存命中：%d 张（%s）" % (len(cache), os.path.basename(TILES_PKL)))
        return cache
    engine = utils._get_ocr_engine()
    cache = {}
    for label in NAMES:
        for nm in sorted(f for f in os.listdir(FOLDERS[label]) if f.lower().endswith(".png")):
            bgr = np.array(Image.open(os.path.join(FOLDERS[label], nm)).convert("RGB"))[:, :, ::-1].copy()
            res, _ = engine(bgr)
            m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
            coords = avc.detect_image_tiles(bgr)
            cache["%s/%s" % (label, nm)] = {
                "ch": m.group(1) if m else "",
                "answer": answer_of(nm),
                "tiles": [bgr[y:y + h, x:x + w].copy() for (x, y, w, h) in coords],
            }
    with open(TILES_PKL, "wb") as f:
        pickle.dump(cache, f)
    P("图块缓存已建立：%d 张（OCR + 图块检出，耗时一次）" % len(cache))
    return cache


# ------------------------- 口径实现 -------------------------
def exact_at(scores_list, answers, thr):
    return sum(1 for s, a in zip(scores_list, answers)
               if pick_by_threshold(s, thr) == a)


def best_thr(scores_list, answers, lo=0.20, hi=0.95, step=0.01):
    best = (-1, lo)
    x = lo
    while x <= hi + 1e-9:
        k = exact_at(scores_list, answers, x)
        if k > best[0]:
            best = (k, round(x, 2))
        x += step
    return best


def plan_gate(scores_list, answers, thr_grid=None, gate_grid=None):
    """在给定数据上挑 (阈值, 门限)：要求**精度 100%** 且覆盖率最大。返回 (thr, gate, 覆盖数, 总数)。

    pick_by_threshold 切出空集/全集时 decide() 会退化为 2-均值，这里与之保持一致：
    只有当「选中集非空且非全集」时才允许提交（否则 conf 不可比）。
    """
    thr_grid = thr_grid or [round(0.20 + 0.01 * i, 2) for i in range(41)]     # 0.20~0.60
    gate_grid = gate_grid or [round(-0.05 + 0.01 * i, 2) for i in range(41)]  # -0.05~0.35
    best = (None, None, -1, 0)
    for thr in thr_grid:
        rows = []
        for s, a in zip(scores_list, answers):
            p = pick_by_threshold(s, thr)
            if not p or len(p) == len(s):
                continue                      # 退化选中集：decide() 不允许提交
            rows.append((confidence(s, p), p == a))
        n_all = len(scores_list)
        for g in gate_grid:
            sub = [r for r in rows if r[0] > g]
            if not sub:
                continue
            good = sum(1 for r in sub if r[1])
            if good == len(sub) and len(sub) > best[2]:   # 精度 100% 且覆盖更大
                best = (thr, g, len(sub), n_all)
    if best[0] is None:
        return None
    return best


def eval_on(scores_list, answers, thr, gate):
    """用固定 (阈值,门限) 在数据上评估：返回 (提交数, 提交内正确数, 总数)"""
    sub, good, n = 0, 0, len(scores_list)
    for s, a in zip(scores_list, answers):
        p = pick_by_threshold(s, thr)
        if not p or len(p) == len(s):
            continue
        if confidence(s, p) > gate:
            sub += 1
            good += (p == a)
    return sub, good, n


def main():
    cache = load_tiles()
    keys = list(cache)
    ans = [cache[k]["answer"] for k in keys]
    P("图 %d 张，变体 %d 个，生产阈值 %.2f / 门限 %.2f"
      % (len(keys), len(VARIANTS), DEFAULT_THRESHOLD, GATE_DEFAULT))
    P("")

    scores_all = {}
    if os.path.exists(SCORES_JSON):
        with open(SCORES_JSON, "r", encoding="utf-8") as f:
            scores_all = json.load(f)

    only = [x.strip() for x in os.environ.get("ONLY", "").split(",") if x.strip()]
    todo = [v for v in VARIANTS if (not only) or v[0] in only]

    for vname, kernel, mode in todo:
        if vname in scores_all:
            P("  %-14s 分数已在缓存里，跳过重算" % vname)
            continue
        t0 = time.time()
        m = GlyphMatcher(kernel=kernel, mode=mode)
        per = {}
        for k in keys:
            per[k] = m.score_tiles(cache[k]["tiles"], cache[k]["ch"])
        scores_all[vname] = per
        with open(SCORES_JSON, "w", encoding="utf-8") as f:
            json.dump(scores_all, f, ensure_ascii=False, indent=1)
        P("  %-14s 打分完成 %.1fs（已存缓存）" % (vname, time.time() - t0))

    P("")
    P("=" * 96)
    P("口径①阈值法(CV 诚实)  ②门控(CV 诚实，要求精度100%)  ③拟合(同批扫，仅看过拟合幅度)")
    P("=" * 96)
    P("%-14s %10s %10s %12s %12s %10s" %
      ("变体", "阈值法拟合", "阈值法CV", "门控CV覆盖率", "门控CV精度", "oracle排序"))
    P("-" * 96)

    folds = {i: [j for j, k in enumerate(keys) if j % 2 == i] for i in (0, 1)}
    summary = {}
    for vname, kernel, mode in VARIANTS:
        if vname not in scores_all:
            continue
        sc = [scores_all[vname][k] for k in keys]
        fit_k, fit_t = best_thr(sc, ans)
        # ① 阈值法 CV
        cv_k, cv_thr_used = 0, []
        for f in (0, 1):
            tr = folds[1 - f]
            te = folds[f]
            _, thr = best_thr([sc[j] for j in tr], [ans[j] for j in tr])
            cv_thr_used.append(thr)
            cv_k += exact_at([sc[j] for j in te], [ans[j] for j in te], thr)
        # ② 门控 CV：(阈值,门限) 在训练折挑，测试折评估
        g_cov, g_good, g_n = 0, 0, 0
        picks = []
        for f in (0, 1):
            tr, te = folds[1 - f], folds[f]
            plan = plan_gate([sc[j] for j in tr], [ans[j] for j in tr])
            if plan is None:
                picks.append((f, None))
                continue
            thr, gate, _, _ = plan
            s2, g2, n2 = eval_on([sc[j] for j in te], [ans[j] for j in te], thr, gate)
            picks.append((f, (thr, gate, s2, g2, n2)))
            g_cov += s2
            g_good += g2
            g_n += n2
        rank_k = sum(1 for s, a in zip(sc, ans)
                     if sorted(sorted(range(1, len(s) + 1), key=lambda i: -s[i - 1])[:len(a)]) == a)
        prec = (g_good / g_cov * 100) if g_cov else 0.0
        P("%-14s %6d/%-3d %6d/%-3d %8d/%-3d(%.0f%%) %9.0f%% %8d/%-3d" %
          (vname, fit_k, len(keys), cv_k, len(keys), g_cov, len(keys),
           (g_cov / len(keys) * 100) if keys else 0, prec, rank_k, len(keys)))
        summary[vname] = {"fit": (fit_k, fit_t), "cv_thr": cv_k, "cv_thr_used": cv_thr_used,
                          "gate_cv": (g_cov, g_good, g_n), "gate_prec": prec,
                          "rank": rank_k, "picks": picks}

    P("")
    P("门控 CV 逐折细节（训练折挑出的参数 → 测试折成绩）：")
    for vname, s in summary.items():
        parts = []
        for f, pk in s["picks"]:
            parts.append("折%d: 无可提交" % f if pk is None else
                         "折%d: thr=%.2f gate=%.2f → 提交%d 正确%d/%d" %
                         (f, pk[0], pk[1], pk[2], pk[3], pk[4]))
        P("  %-14s %s" % (vname, " | ".join(parts)))

    P("")
    P("按「门控 CV 覆盖率」排序（这才是上线口径）：")
    for vname, s in sorted(summary.items(), key=lambda kv: -kv[1]["gate_cv"][0]):
        cov, good, n = s["gate_cv"]
        P("  %-14s 覆盖 %2d/%d (%.0f%%)  精度 %.0f%%  阈值法CV %d/%d  oracle %d/%d"
          % (vname, cov, n, (cov / n * 100) if n else 0, s["gate_prec"], s["cv_thr"], n,
             s["rank"], n))

    with open(REPORT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    with open(os.path.join(OUT, "exp_gate_sweep_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "keys": keys,
                   "threshold": DEFAULT_THRESHOLD, "gate": GATE_DEFAULT,
                   "n": len(keys)}, f, ensure_ascii=False, indent=1)
    P("")
    P("已写出 %s" % os.path.relpath(REPORT_TXT, ROOT))
    P("已写出 out/exp_gate_sweep_summary.json（画图用）")


if __name__ == "__main__":
    main()
