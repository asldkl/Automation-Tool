# -*- coding: utf-8 -*-
"""本地（离线）字形匹配方案的通过率口径汇总 —— 只用 ASCII 输出，避免管道乱码。

数据：out/exp_gate_clahe_scores.json 的「基线 bh25」（= 生产候选配置，唯一进的变体）。
"""
import json
import math
import os
import sys


def _find_root(start):
    p = start
    for _ in range(6):
        if os.path.exists(os.path.join(p, "captcha_glyph_match.py")):
            return p
        p = os.path.dirname(p)
    return start


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".workbuddy", "out")
sys.path.insert(0, ROOT)
from captcha_glyph_match import (  # noqa: E402
    DEFAULT_THRESHOLD, confidence, pick_by_2means, pick_by_threshold,
)

with open(os.path.join(OUT, "exp_gate_clahe_scores.json"), encoding="utf-8") as fh:
    scores = json.load(fh)
rec = scores["基线 bh25"]
keys = list(rec)
SETS = ["根目录", "测试", "测试1"]


def pick_rank(s, k):
    return sorted(sorted(range(1, len(s) + 1), key=lambda i: -s[i - 1])[:k])


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h) * 100, min(1.0, c + h) * 100)


def show(label, k, n):
    lo, hi = wilson(k, n)
    print(f"  {label:34s} {k:2d}/{n} = {k/n*100:5.1f}%   95%CI [{lo:.1f}%, {hi:.1f}%]")


THR = DEFAULT_THRESHOLD
print(f"threshold used = {THR}   n = {len(keys)}")

print("\n[A] threshold-only, per set and total")
tot = 0
for st in SETS:
    sub = [k for k in keys if k.startswith(st + "/")]
    ok = sum(1 for k in sub if pick_by_threshold(rec[k]["scores"], THR) == rec[k]["answer"])
    tot += ok
    show(f"{st} (n={len(sub)})", ok, len(sub))
show("TOTAL", tot, len(keys))

print("\n[B] 2-means (threshold-free), per set and total")
tot2 = 0
for st in SETS:
    sub = [k for k in keys if k.startswith(st + "/")]
    ok = sum(1 for k in sub if pick_by_2means(rec[k]["scores"]) == rec[k]["answer"])
    tot2 += ok
    show(f"{st} (n={len(sub)})", ok, len(sub))
show("TOTAL", tot2, len(keys))

print("\n[C] oracle upper bound (top-k by rank, k = true count), per set and total")
tot3 = 0
for st in SETS:
    sub = [k for k in keys if k.startswith(st + "/")]
    ok = sum(1 for k in sub if pick_rank(rec[k]["scores"], len(rec[k]["answer"])) == rec[k]["answer"])
    tot3 += ok
    show(f"{st} (n={len(sub)})", ok, len(sub))
show("TOTAL", tot3, len(keys))

print("\n[D] gating: auto-submit only when conf > gate (threshold-only picking)")
for gate in (0.12, 0.14, 0.16, 0.18):
    sub = [k for k in keys
           if confidence(rec[k]["scores"], pick_by_threshold(rec[k]["scores"], THR)) > gate]
    good = [k for k in sub
            if pick_by_threshold(rec[k]["scores"], THR) == rec[k]["answer"]]
    lo, hi = wilson(len(good), len(sub))
    cov_lo, cov_hi = wilson(len(sub), len(keys))
    print(f"  gate>{gate:.2f}: auto-submit {len(sub)}/{len(keys)} "
          f"(coverage {len(sub)/len(keys)*100:.0f}%)  correct {len(good)}/{len(sub)} "
          f"precision {len(good)/max(1,len(sub))*100:.1f}%  95%CI-of-precision "
          f"[{lo:.1f}%, {hi:.1f}%]")

print("\n[E] why threshold-only loses: wrong cases and their conf")
print("     (set, file, conf, picked, answer)")
rows = []
for k in keys:
    s = rec[k]["scores"]
    p = pick_by_threshold(s, THR)
    if p != rec[k]["answer"]:
        rows.append((confidence(s, p), k, p, rec[k]["answer"]))
for c, k, p, a in sorted(rows):
    print(f"     conf={c:+.3f}  {k:22s} picked={p} answer={a}")
print(f"     total wrong = {len(rows)}/{len(keys)}")
