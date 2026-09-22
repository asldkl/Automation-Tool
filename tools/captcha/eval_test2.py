# -*- coding: utf-8 -*-
"""用用户回填的真值评估测试2（100 张）——这是第一批**带标注的 held-out 集**。

用户填的是「正确答案块」（如 12345），所以能算真·准确率：
  · 提交精度 = 提交的 81 张里选对了多少
  · 覆盖率   = 81/100
  · 一次通过 = 提交且正确
  · 「白丢」 = 没提交、但其实选对了（我们的门控太保守 → 会被送去换一组/人工）
  · 门控曲线 = 在这批 held-out 上扫门限，看 100% 精度能覆盖多少（⚠️看完别直接拿去调参再报成绩）
       —— 只用来判断现有 0.09 是否合理、以及"再收紧/放松"的代价。

用法：python tools/captcha/eval_test2.py
"""
import csv
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

GT_CSV = os.path.join(OUT, "test2_核对表.csv")
RESULT_JSON = os.path.join(OUT, "test2_result.json")
REPORT = os.path.join(OUT, "test2_评估.txt")
LOG = []
P = lambda *a, **kw: (LOG.append(" ".join(str(x) for x in a)),
                     print(*a, **dict(kw, flush=True)))


def blocks(s):
    return sorted({int(c) for c in str(s or "") if c.isdigit() and c != "0"})


def main():
    # ---- 真值 ----
    gt = {}
    with open(GT_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            ans = blocks(r.get("正确答案块（选填）", "")) or blocks(r.get("你的核对（填 对/错）", ""))
            gt[r["文件名"]] = ans
    filled = sum(1 for v in gt.values() if v)
    with open(RESULT_JSON, encoding="utf-8") as f:
        recs = json.load(f)["records"]

    P("=" * 92)
    P("测试2 评估（100 张，生产档位 clahe/核35/阈值0.40/门限0.09）")
    P("=" * 92)
    P("真值：%d/%d 张已填" % (filled, len(gt)))
    miss = [k for k, v in gt.items() if not v]
    if miss:
        P("  ⚠️ 未填的 %d 张：%s" % (len(miss), miss[:12]))

    n = 0
    sub = sub_ok = sub_bad = 0
    all_ok = 0                    # 不看门控、阈值法直接判定的全对数
    lost_ok = 0                   # 没提交、但其实选对了
    bad_rows, lost_rows = [], []
    for r in recs:
        gen = gt.get(r["file"])
        if not gen:
            continue
        n += 1
        picked = r["picked"]
        ok = picked == gen
        if r["action"] == "submit":
            sub += 1
            if ok:
                sub_ok += 1
            else:
                sub_bad += 1
                bad_rows.append((r, gen))
        else:
            if ok:
                lost_ok += 1
                lost_rows.append((r, gen))
        if pick_by_threshold(r["scores"], 0.40) == gen:
            all_ok += 1

    P("")
    P("【核心结果】")
    P("  自动提交 %d/%d（覆盖 %.0f%%），其中选对 %d 张 → **提交精度 %.1f%%**"
      % (sub, n, sub / n * 100, sub_ok, sub_ok / sub * 100 if sub else 0))
    P("  一次通过（提交且对）= **%d/%d = %.0f%%**" % (sub_ok, n, sub_ok / n * 100))
    P("  未提交 %d 张：其中**算法其实选对了的 %d 张**（被门控保守拦下 → 送去换一组/人工）"
      % (n - sub, lost_ok))
    P("  若不做门控、阈值法直接提交：全对 %d/%d = %.0f%%（但会把 %d 张错的也提交出去）"
      % (all_ok, n, all_ok / n * 100, sub_bad))
    P("")
    if bad_rows:
        P("【提交了但选错的 %d 张】" % len(bad_rows))
        for r, gen in bad_rows:
            P("  #%s 目标「%s」 算法选中 %-16s 真值 %-16s conf %+.3f"
              % (os.path.splitext(r["file"])[0], r["ch"], str(r["picked"]), str(gen), r["conf"]))
    else:
        P("【提交了但选错的】0 张 —— 提交部分 100% 正确")
    P("")
    if lost_rows:
        P("【没提交但其实选对的 %d 张（白丢的机会）】" % len(lost_rows))
        for r, gen in lost_rows:
            P("  #%s 目标「%s」 选中 %-14s 真值 %-14s conf %+.3f" %
              (os.path.splitext(r["file"])[0], r["ch"], str(r["picked"]), str(gen), r["conf"]))

    # ---- 按目标字 ----
    P("")
    P("【按目标字】")
    P("  %-4s %4s %6s %8s %9s %9s" % ("字", "张数", "提交", "提交精度", "一次通过", "白丢"))
    agg = {}
    for r in recs:
        gen = gt.get(r["file"])
        if not gen:
            continue
        a = agg.setdefault(r["ch"], [0, 0, 0, 0, 0])   # n, sub, sub_ok, pass, lost
        a[0] += 1
        ok = r["picked"] == gen
        if r["action"] == "submit":
            a[1] += 1
            a[2] += ok
        if ok:
            a[3] += 1
        elif r["action"] != "submit":
            pass
        if r["action"] != "submit" and ok:
            a[4] += 1
    for ch, a in sorted(agg.items(), key=lambda kv: kv[1][3] / kv[1][0]):
        P("  %-4s %4d %6d %7.0f%% %8.0f%% %9d" %
          (ch, a[0], a[1], (a[2] / a[1] * 100) if a[1] else 0, a[3] / a[0] * 100, a[4]))

    # ---- 门控曲线（held-out 上扫，仅用于判断现有门限是否合理）----
    P("")
    P("【门控曲线（在这批 held-out 上扫，⚠️不要拿扫出来的值当成绩）】")
    rows = []
    for r in recs:
        gen = gt.get(r["file"])
        if not gen:
            continue
        for thr in (0.36, 0.40, 0.44):
            p = pick_by_threshold(r["scores"], thr)
            if not p or len(p) == 6:
                continue
            rows.append((thr, confidence(r["scores"], p), p == gen))
    P("  %-8s %-8s %8s %8s %10s %10s" % ("阈值", "门限", "提交", "提交对", "提交精度", "覆盖"))
    for thr in (0.36, 0.40, 0.44):
        for g in (0.00, 0.05, 0.09, 0.12, 0.15, 0.20):
            sub_l = [x for x in rows if x[0] == thr and x[1] > g]
            good = sum(1 for x in sub_l if x[2])
            P("  %-8.2f %-8.2f %8d %8d %9.1f%% %9.0f%%"
              % (thr, g, len(sub_l), good, (good / len(sub_l) * 100) if sub_l else 0,
                 len(sub_l) / n * 100))

    P("")
    P("【一句话结论】")
    P("  在这批 100 张（全新、未参与调参）上：提交精度 %.0f%%、覆盖率 %.0f%%、一次通过 %.0f%%；"
      % ((sub_ok / sub * 100) if sub else 0, sub / n * 100, sub_ok / n * 100))
    P("  另有 %d 张被门控保守拦下但**其实选对了**（换成「换一组」重试就有机会拿下）。" % lost_ok)

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    P("")
    P("报告已写出 %s" % os.path.relpath(REPORT, ROOT))


if __name__ == "__main__":
    main()
