# -*- coding: utf-8 -*-
"""实验：用 OCR 的**高精度命中**当锚点，给同图内的字形分数做自校准 → 顺手解掉「该选几块」。

两个信号互补（25 张实测）：
  · OCR 只识别不检测：**精度 100%**、召回仅 ~32% → 读出来就可信，但覆盖不全（给的还是"身份"）
  · 字形模板匹配：**图内排序近乎完美**（oracle 25/25）→ 但分数跨图不可比，全局阈值不存在

把两者拼起来：
  1. 先用 OCR 读 6 块，凡是读出目标字的块 → **锚点**（因为精度 100%，可以直接采信）；
  2. 若已有锚点，就用"锚点里最低的那个字形分数"当**本图的正例下限**：
        选中集 = {块 | 字形分数 ≥ 锚点最低分}
     —— 阈值不再跨图，而是**由本图自己标定**；
  3. 没有锚点的图 → 退回现有生产档位（阈值 0.40 + 门控）。

对照口径：
  · 现有生产（阈值 0.40 直接判定）        23/25
  · OCR 单独                           见 exp_ocr_rec_tile.py
  · OCR 锚点 + 字形分数（本脚本）        ?
  · 还要看「100% 精度下能自动提交几张」

用法：python tools/captcha/exp_ocr_seed_calib.py
"""
import json
import os
import re
import sys

_ANCHOR = "captcha_glyph_match.py"


def _find_root(start):
    p = start
    for _ in range(6):
        if os.path.exists(os.path.join(p, _ANCHOR)):
            return p
        p = os.path.dirname(p)
    return start


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".workbuddy", "out")
sys.path.insert(0, ROOT)

from captcha_glyph_match import confidence, pick_by_threshold  # noqa: E402

PROD_THR = 0.40
PROD_GATE = 0.09
OCR_ROWS = os.path.join(OUT, "exp_ocr_rec_tile_rows.json")
SCORES = os.path.join(OUT, "gate_sweep_scores.json")
REPORT = os.path.join(OUT, "exp_ocr_seed_calib.txt")

LOG = []


def P(*a, **kw):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    kw.setdefault("flush", True)
    print(s, **kw)


def answer_of(key):
    name = key.split("/", 1)[1]
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def main():
    with open(SCORES, encoding="utf-8") as f:
        scores = json.load(f)["clahe35"]          # 生产档位
    with open(OCR_ROWS, encoding="utf-8") as f:
        ocr = json.load(f)

    keys = sorted(scores)
    # ---- OCR 各变体的命中集（并集）----
    seed_union = {k: set() for k in keys}
    for vname, rows in ocr.items():
        for r in rows:
            k = r["key"]
            if k in seed_union:
                seed_union[k] |= set(r["picked"])

    n_seed_img = sum(1 for k in keys if seed_union[k])
    tp = fp = fn = 0
    for k in keys:
        a = set(answer_of(k))
        s = seed_union[k]
        tp += len(s & a)
        fp += len(s - a)
        fn += len(a - s)
    P("=" * 100)
    P("OCR（7 种预处理并集，只识别不检测）在 25 张上的锚点情况")
    P("=" * 100)
    P("  有锚点的图：%d/%d       锚点逐块 精度 %.0f%%  召回 %.0f%%"
      % (n_seed_img, len(keys), tp / (tp + fp) * 100 if (tp + fp) else 0,
         tp / (tp + fn) * 100 if (tp + fn) else 0))
    P("")

    # ---- 三种策略 ----
    def prod_pick(sc):
        return pick_by_threshold(sc, PROD_THR)

    def seed_min_pick(sc, seeds, margin=0.0):
        base = min(sc[i - 1] for i in seeds) - margin
        return sorted(i for i, v in enumerate(sc, 1) if v >= base)

    def seed_mid_pick(sc, seeds):
        """下限取「锚点最低分」与「未选块最高分」的中点"""
        base = min(sc[i - 1] for i in seeds)
        others = [v for i, v in enumerate(sc, 1) if i not in seeds]
        top_other = max(others) if others else None
        if top_other is None or top_other < base:
            return sorted(i for i, v in enumerate(sc, 1) if v >= base)
        return sorted(i for i, v in enumerate(sc, 1) if v >= (base + top_other) / 2.0)

    strategies = [
        ("生产·阈值 0.40", lambda k: prod_pick(scores[k])),
        ("生产∪OCR", lambda k: sorted(set(prod_pick(scores[k])) | seed_union[k])),
        ("锚点·MIN", lambda k: seed_min_pick(scores[k], seed_union[k]) if seed_union[k] else prod_pick(scores[k])),
        ("锚点·MID", lambda k: seed_mid_pick(scores[k], seed_union[k]) if seed_union[k] else prod_pick(scores[k])),
    ]

    P("=" * 100)
    P("策略对照（25 张；口径：全对张数 / 逐块 P / R / 「100% 精度下能自动提交几张」）")
    P("=" * 100)
    summary = {}
    for name, fn_ in strategies:
        exact = 0
        tp2 = fp2 = fn2 = 0
        rows = []
        for k in keys:
            a = answer_of(k)
            p = fn_(k)
            exact += (p == a)
            for i in range(1, 7):
                ip, ia = i in p, i in a
                tp2 += ip and ia
                fp2 += ip and not ia
                fn2 += (not ip) and ia
            rows.append((k, scores[k], p, a, confidence(scores[k], p) if p and len(p) < 6 else 0.0))
        prec = tp2 / (tp2 + fp2) if (tp2 + fp2) else 0
        rec = tp2 / (tp2 + fn2) if (tp2 + fn2) else 0
        # 门控：找能让"提交且全对"最多的门限（拟合口径，只用于横向比较）
        best = (0, 0.0)
        for g in [round(-0.05 + 0.01 * i, 2) for i in range(41)]:
            sub = [r for r in rows if r[4] > g]
            good = sum(1 for r in sub if r[2] == r[3])
            if sub and good == len(sub) and len(sub) > best[0]:
                best = (len(sub), g)
        summary[name] = {"exact": exact, "prec": prec, "rec": rec, "gate": best}
        P("%-16s 全对 %2d/25   逐块 精度 %5.1f%% 召回 %5.1f%%   100%%精度门控：提交 %d/25(门限 %.2f)"
          % (name, exact, prec * 100, rec * 100, best[0], best[1]))

    P("")
    P("=" * 100)
    P("最好策略 = 锚点·MID 的逐张明细（对比答案）")
    P("=" * 100)
    for k in keys:
        a = answer_of(k)
        p = seed_mid_pick(scores[k], seed_union[k]) if seed_union[k] else prod_pick(scores[k])
        mark = "✅" if p == a else "❌"
        P("  %-18s 锚点=%-14s 选中=%-16s 答案=%-16s %s"
          % (k, str(sorted(seed_union[k])) if seed_union[k] else "无", str(p), str(a), mark))

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    with open(os.path.join(OUT, "exp_ocr_seed_calib.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    P("")
    P("已写出 out/exp_ocr_seed_calib.txt")


if __name__ == "__main__":
    main()
