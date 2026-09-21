# -*- coding: utf-8 -*-
"""实验：把图块**直接送进 OCR 的识别模型**（跳过检测），看能不能读出「这块是什么字」。

背景/为什么这条以前没测过：
  早先试过 `RapidOCR(整块图)` → 一个字都读不出。但那是 **检测+识别** 全流水线，
  失败点在**检测阶段**（纹理图里找不到"文本区"）。而我们的图块本来就已经切好了，
  根本不需要检测 —— 直接调 `engine.text_recognizer([tile])`（ch_ppocr_v3_rec）即可。
  这条路径此前**从未测过**。

判据（这才是"识别"而不是"比对"）：
  - 目标块的识别结果里出现目标字 → 命中；
  - 干扰块也读出目标字 → 误报。
  k 自然得出：选中集 = {识别结果含目标字的块}，不需要任何阈值。

用法：python tools/captcha/exp_ocr_rec_tile.py
输出：out/exp_ocr_rec_tile.txt / .json
"""
import json
import os
import pickle
import re
import sys
import time

import cv2
import numpy as np

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

import utils  # noqa: E402
from captcha_glyph_match import _blackhat  # noqa: E402

TILES_PKL = os.path.join(OUT, "gate_sweep_tiles.pkl")
REPORT = os.path.join(OUT, "exp_ocr_rec_tile.txt")
JSON_OUT = os.path.join(OUT, "exp_ocr_rec_tile.json")
CJK = re.compile(r"[\u4e00-\u9fff]")

LOG = []


def P(*a, **kw):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    kw.setdefault("flush", True)
    print(s, **kw)


def _norm_gray(t):
    """blackhat 响应 → 反色成「暗字浅底」的 uint8（贴近识别模型的训练分布）"""
    g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY).astype(np.float32)
    r = _blackhat(g, 35)
    lo, hi = float(r.min()), float(r.max())
    u = ((r - lo) / (hi - lo) * 255.0).astype(np.uint8) if hi > lo else r.astype(np.uint8)
    return cv2.cvtColor(255 - u, cv2.COLOR_GRAY2BGR)


def _clahe(t):
    g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.createCLAHE(3.0, (8, 8)).apply(g), cv2.COLOR_GRAY2BGR)


def _binary(t):
    g = cv2.cvtColor(_blackhat(cv2.cvtColor(t, cv2.COLOR_BGR2GRAY).astype(np.float32), 35),
                     cv2.COLOR_GRAY2BGR)
    g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    b = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                              cv2.THRESH_BINARY, 31, -2)
    return cv2.cvtColor(255 - b, cv2.COLOR_GRAY2BGR)


def _up(x, k):
    return cv2.resize(x, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)


VARIANTS = [
    ("raw", lambda t: t),
    ("raw2x", lambda t: _up(t, 2)),
    ("gray2x", lambda t: _up(cv2.cvtColor(cv2.cvtColor(t, cv2.COLOR_BGR2GRAY),
                                        cv2.COLOR_GRAY2BGR), 2)),
    ("clahe2x", lambda t: _up(_clahe(t), 2)),
    ("bh_inv", lambda t: _norm_gray(t)),
    ("bh_inv3x", lambda t: _up(_norm_gray(t), 3)),
    ("bin_inv2x", lambda t: _up(_binary(t), 2)),
]


def main():
    eng = utils._get_ocr_engine()
    rec = eng.text_recognizer
    with open(TILES_PKL, "rb") as f:
        tiles = pickle.load(f)
    P("图 %d 张，变体 %d 个（只跑识别模型，跳过检测）" % (len(tiles), len(VARIANTS)))
    P("")

    results = {}
    for vname, prep in VARIANTS:
        t0 = time.time()
        rows = []
        for key in sorted(tiles):
            rec_img = tiles[key]
            target = rec_img["ch"]
            ans = rec_img["answer"]
            if not target or not rec_img["tiles"]:
                continue
            picked, texts = [], []
            for i, t in enumerate(rec_img["tiles"], 1):
                try:
                    out = rec([prep(t)])
                    txt = str(out[0][0][0]) if (out and out[0]) else ""
                except Exception as e:              # noqa: BLE001
                    txt = "!ERR:%s" % e
                texts.append(txt)
                if CJK.search(txt or "") and target in txt:
                    picked.append(i)
            rows.append({"key": key, "ch": target, "answer": ans,
                         "picked": sorted(picked), "texts": texts})
        tp = sum(1 for r in rows for i in r["picked"] if i in r["answer"])
        fp = sum(1 for r in rows for i in r["picked"] if i not in r["answer"])
        fn = sum(1 for r in rows for i in range(1, 7) if i in r["answer"] and i not in r["picked"])
        exact = sum(1 for r in rows if r["picked"] == r["answer"])
        hit_txt = sum(1 for r in rows for x in r["texts"] if CJK.search(x or ""))
        results[vname] = {"rows": rows, "exact": exact, "tp": tp, "fp": fp, "fn": fn,
                          "n": len(rows), "n_cjk_text": hit_txt,
                          "sec": round(time.time() - t0, 1)}
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec_ = tp / (tp + fn) if (tp + fn) else 0.0
        P("%-11s 全对 %2d/%-3d 逐块精度 %5.1f%% 召回 %5.1f%%  读出汉字的块 %d/150  %.0fs"
          % (vname, exact, len(rows), prec * 100, rec_ * 100, hit_txt, results[vname]["sec"]))

    # 抽一个变体看原始输出（判断是"读错字"还是"读不出字"）
    best = max(results.items(), key=lambda kv: (kv[1]["exact"], kv[1]["n_cjk_text"]))
    P("")
    P("=" * 96)
    P("最好变体 = %s（全对 %d/%d，读到汉字的块 %d/150）" % (best[0], best[1]["exact"],
                                                        best[1]["n"], best[1]["n_cjk_text"]))
    P("=" * 96)
    for r in best[1]["rows"][:8]:
        P("  %-18s 目标=%-2s 答案=%-16s 识别=%-16s %s"
          % (r["key"], r["ch"], str(r["answer"]),
             str([t for t in r["texts"]]), "✅" if r["picked"] == r["answer"] else "❌"))

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")
    with open(JSON_OUT, "w", encoding="utf-8") as f:
        json.dump({k: {kk: vv for kk, vv in v.items() if kk != "rows"} for k, v in results.items()},
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "exp_ocr_rec_tile_rows.json"), "w", encoding="utf-8") as f:
        json.dump({k: v["rows"] for k, v in results.items()}, f, ensure_ascii=False, indent=1)
    P("")
    P("已写出 out/exp_ocr_rec_tile.txt")


if __name__ == "__main__":
    main()
