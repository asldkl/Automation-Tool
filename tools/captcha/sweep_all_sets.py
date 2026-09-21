# -*- coding: utf-8 -*-
"""三个集合 × 全部 25 张：**分数只算一次**（贵），之后所有阈值/门控分析走缓存（便宜）。

产出：
  .workbuddy/out/scores_all.json   每张图的 {ch, answer, scores}
  .workbuddy/out/sweep_all.txt     阈值扫描 + 门控扫描 + 2均值 + 排序上界

为什么要缓存：黑帽 K25 的分数与"选哪几块"无关，改阈值不该重算 3.2s/张。
"""
import json
import os
import re
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, "图片文字点击验证例图")
OUT = os.path.join(ROOT, ".workbuddy", "out")
CACHE = os.path.join(OUT, "scores_all.json")
sys.path.insert(0, ROOT)

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_match import GlyphMatcher, confidence, pick_by_2means, pick_by_threshold  # noqa: E402

NAMES = ["根目录", "测试", "测试1"]
FOLDERS = {n: os.path.join(BASE, n) for n in NAMES}
FOLDERS["根目录"] = BASE
TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")
FORCE = "--force" in sys.argv


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def build_cache():
    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()          # 默认 = 黑帽 K25（阈值法最优的那个核）
    data = {}
    t_all = time.time()
    for label in NAMES:
        folder = FOLDERS[label]
        for name in sorted(f for f in os.listdir(folder) if f.lower().endswith(".png")):
            bgr = np.array(Image.open(os.path.join(folder, name)).convert("RGB"))[:, :, ::-1].copy()
            res, _ = engine(bgr)
            m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
            ch = m.group(1) if m else ""
            coords = avc.detect_image_tiles(bgr)
            tiles = [bgr[y:y + th, x:x + tw].copy() for (x, y, tw, th) in coords]
            t0 = time.time()
            scores = matcher.score_tiles(tiles, ch)
            el = time.time() - t0
            data[f"{label}/{name}"] = {"ch": ch, "answer": answer_of(name),
                                       "scores": scores, "n_tiles": len(coords),
                                       "sec": round(el, 2)}
            print(f"  算分 {label}/{name:14s} 字={ch!r} n={len(coords)} "
                  f"{[f'{v:+.3f}' for v in scores]} {el:.1f}s", flush=True)
    print(f"总耗时 {time.time()-t_all:.1f}s", flush=True)
    os.makedirs(OUT, exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return data


def load():
    if FORCE or not os.path.isfile(CACHE):
        print("== 重新计算分数 ==", flush=True)
        return build_cache()
    print(f"== 复用缓存 {CACHE} ==", flush=True)
    with open(CACHE, encoding="utf-8") as fh:
        return json.load(fh)


def tally(data, picker):
    """picker(name, rec) -> picked；返回 {集合: [对, 总]}"""
    st = {n: [0, 0] for n in NAMES}
    st["合计"] = [0, 0]
    for key, rec in data.items():
        g = key.split("/", 1)[0]
        got = picker(key, rec)
        hit = 1 if got == rec["answer"] else 0
        for k in (g, "合计"):
            st[k][0] += hit
            st[k][1] += 1
    return st


def fmt(label, st):
    parts = "  ".join(f"{n} {st[n][0]}/{st[n][1]}" for n in NAMES)
    a, b = st["合计"]
    return f"{label:24s} 合计 {a:2d}/{b} ({a/b*100:5.1f}%)   [{parts}]"


def main():
    data = load()
    n = len(data)
    print(f"\n共 {n} 张；配置 = 黑帽 K25 · 4 字体 · 尺度 0.6~1.1 · 角度 ±30°", flush=True)
    print("=" * 104, flush=True)

    print("【1】固定阈值扫描（纯阈值，无 2 均值回退）", flush=True)
    print("=" * 104, flush=True)
    best = (0, 0)
    for i in range(30, 46):
        thr = i / 100.0
        st = tally(data, lambda k, r, t=thr: pick_by_threshold(r["scores"], t))
        a = st["合计"][0]
        best = max(best, (a, thr))
        print("  " + fmt(f"阈值 {thr:.2f}", st), flush=True)
    print(f"  → 单点最好 {best[0]}/{n} @ 阈值 {best[1]:.2f}", flush=True)

    print("\n【2】无阈值方案 / 排序上界", flush=True)
    print("=" * 104, flush=True)
    print("  " + fmt("2 均值(无需阈值)", tally(data, lambda k, r: pick_by_2means(r["scores"]))), flush=True)
    print("  " + fmt("排序取前 k 名(已知块数)",
                     tally(data, lambda k, r: sorted(sorted(range(1, 7),
                           key=lambda i: -r["scores"][i - 1])[:len(r["answer"])]))), flush=True)
    print("  " + fmt("全选 6 块(瞎选基线)", tally(data, lambda k, r: [1, 2, 3, 4, 5, 6])), flush=True)

    for base_thr in (0.37, 0.34):
        print(f"\n【3】置信度门控扫描（阈值 {base_thr:.2f} 下：conf = 选中块最低分 − 未选中块最高分）",
              flush=True)
        print("=" * 104, flush=True)
        print(f"  {'门限':>6s} {'自动提交':>8s} {'自动里对':>8s} {'自动精度':>8s} "
              f"{'转兜底':>7s} {'兜底里对':>8s} {'兜底精度':>8s} {'覆盖':>6s}", flush=True)
        for gi in range(0, 31):
            gate = gi / 100.0
            auto = auto_ok = dfr = dfr_ok = 0
            for key, rec in data.items():
                sc = rec["scores"]
                picked = pick_by_threshold(sc, base_thr)
                if not picked or len(picked) == len(sc):
                    picked = pick_by_2means(sc)
                good = picked == rec["answer"]
                if confidence(sc, picked) > gate:
                    auto += 1
                    auto_ok += good
                else:
                    dfr += 1
                    dfr_ok += good
            ap = auto_ok / auto * 100 if auto else 0.0
            dp = dfr_ok / dfr * 100 if dfr else 0.0
            print(f"  {gate:>6.2f} {auto:>8d} {auto_ok:>8d} {ap:>7.1f}% "
                  f"{dfr:>7d} {dfr_ok:>8d} {dp:>7.1f}% {auto/n*100:>5.0f}%", flush=True)


if __name__ == "__main__":
    main()
