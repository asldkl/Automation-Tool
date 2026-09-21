# -*- coding: utf-8 -*-
"""离线模拟「有把握就点、没把握就换一组」策略（25 张实测分数，ASCII 输出避免管道乱码）。

数据：out/exp_gate_clahe_scores.json 的「基线 bh25」= 生产候选配置。
策略：每张图跑 decide() → submit（点图）/ refresh（不点，等外层换一组）。
      刷新预算 N 次 → 最多 N+1 次机会；预算耗尽仍未提交则转人工/AI。

⚠️ 期望通过率按「每次出题独立同分布」算（1-(1-c)^(N+1)）。该假设**离线无法验证**：
   游戏是否总给同一难度分布、刷新是否真的换一张（而不是同一张）都未知 → 只作量级参考。
"""
import json
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
from captcha_glyph_match import DEFAULT_THRESHOLD, GATE_DEFAULT, decide  # noqa: E402

with open(os.path.join(OUT, "exp_gate_clahe_scores.json"), encoding="utf-8") as fh:
    rec = json.load(fh)["基线 bh25"]
keys = list(rec)
THR, GATE = DEFAULT_THRESHOLD, GATE_DEFAULT

print(f"threshold={THR}  gate={GATE}  n={len(keys)}")
print()
print("per-image decision")
print(f"{'set/file':26s} {'action':8s} {'conf':>7s} {'picked':22s} correct")
sub = []
for k in keys:
    d = decide(rec[k]["scores"], THR, GATE)
    correct = d["picked"] == rec[k]["answer"]
    if d["action"] == "submit":
        sub.append(correct)
    print(f"{k:26s} {d['action']:8s} {d['conf']:+7.3f} {str(d['picked']):22s} "
          f"{'OK' if correct else 'WRONG'}")

n = len(keys)
c = len(sub) / n
prec = (sum(sub) / len(sub) * 100) if sub else 0.0
print()
print(f"submit     : {len(sub)}/{n} = coverage {c*100:.1f}%   precision {prec:.1f}%")
print(f"refresh    : {n-len(sub)}/{n} = {(1-c)*100:.1f}%  (不点任何图)")
print()
print("expected pass rate with refresh budget N (assumes i.i.d. draws per attempt):")
for N in (0, 1, 2, 3):
    attempts = N + 1
    p = 1 - (1 - c) ** attempts
    print(f"  N={N}  attempts={attempts}  auto-pass = 1-(1-{c:.2f})^{attempts} = {p*100:5.1f}%")
print()
print(f"note: with budget exhausted the remaining {(1-c)*100:.0f}% goes to manual/AI, "
      f"never to a blind submit (auto-submitted part stays {prec:.0f}% correct).")
