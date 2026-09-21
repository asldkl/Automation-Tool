# -*- coding: utf-8 -*-
"""把「图片增强」喂给 AI 视觉模型，看识别率有没有变化。

对照条件（同一批图、同一提示词，只改图）：
  raw    原图（生产当前口径）
  bh     每个图块黑帽增强后贴回原图（题目文字区保持原样，模型仍要能读题干）
  flat   每个图块平场除+黑帽后贴回原图

用法：
  python test_ai_preproc.py --smoke              # 只跑 1 张，验证链路
  python test_ai_preproc.py --limit 11           # 前 N 张 × 全部条件
  python test_ai_preproc.py --con "raw,bh"
"""
import argparse
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
import config  # noqa: E402
import utils  # noqa: E402

TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")
TILE_W, TILE_H = 300, 302


def answer_of(name):
    head = re.split(r"[\s(（]", os.path.splitext(name)[0])[0]
    return sorted({int(c) for c in head if c.isdigit()})


def enhance_tile(tile_bgr, mode):
    big = cv2.resize(tile_bgr, (TILE_W, TILE_H), interpolation=cv2.INTER_CUBIC)
    g = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    if mode == "bh":
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
        e = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, k)
    else:  # flat
        low = cv2.GaussianBlur(g.astype(np.float32), (0, 0), 15.0)
        ff = g.astype(np.float32) / np.maximum(low, 1e-3)
        e = cv2.normalize(ff, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    e = cv2.normalize(e.astype(np.float32), None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.cvtColor(e, cv2.COLOR_GRAY2BGR)


def build_image(bgr, coords, mode):
    if mode == "raw":
        return bgr.copy()
    out = bgr.copy()
    for (x, y, w, h) in coords:
        out[y:y + h, x:x + w] = cv2.resize(enhance_tile(bgr[y:y + h, x:x + w], mode),
                                           (w, h), interpolation=cv2.INTER_AREA)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=os.path.join(BASE, "测试1"))
    ap.add_argument("--con", default="raw,bh")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    conds = [c.strip() for c in args.con.split(",") if c.strip()]
    s = config.load_settings()
    base_url = s.get("ai_visual_captcha_base_url")
    api_key = s.get("ai_visual_captcha_api_key")
    model = s.get("ai_visual_captcha_model")
    space = s.get("ai_visual_captcha_coord_space", "auto")
    if not (base_url and api_key and model):
        print("❌ 供应商未配置，退出")
        return 1
    print(f"供应商 = {s.get('ai_visual_captcha_provider')} / {model}", flush=True)

    engine = utils._get_ocr_engine()
    names = sorted(f for f in os.listdir(args.folder) if f.lower().endswith(".png"))
    if args.limit:
        names = names[:args.limit]
    if args.smoke:
        names = names[:1]
        conds = conds[:1]
    print(f"目录 = {args.folder}   图 {len(names)} 张   条件 = {conds}\n" + "=" * 96, flush=True)

    rows = []
    for name in names:
        bgr = np.array(Image.open(os.path.join(args.folder, name)).convert("RGB"))[:, :, ::-1].copy()
        ans = answer_of(name)
        res, _ = engine(bgr)
        m = TXT_RE.search("".join(str(i[1]) for i in (res or [])))
        ch = m.group(1) if m else ""
        coords = avc.detect_image_tiles(bgr)
        for cond in conds:
            img = build_image(bgr, coords, cond)
            b64, mime, W, H = avc._capture_screen_jpeg(bgr=img)
            prompt = avc._build_prompt(W, H, kind="text")
            t0 = time.time()
            try:
                text = avc._ask_model(base_url, api_key, model, b64, prompt,
                                      timeout=args.timeout, retries=2)
                err = ""
            except Exception as e:
                text, err = "", f"{type(e).__name__}: {e}"
            el = time.time() - t0
            picked, raw_pts, labels = [], [], []
            if text:
                pr = avc.parse_model_response(text, W, H, coord_space=space)
                raw_pts = pr.get("points") or []
                labels = pr.get("labels") or []
                if raw_pts and coords:
                    snapped, _ = avc.snap_points_to_tiles(raw_pts, coords)
                    for pt in snapped:
                        if not pt:
                            continue
                        cx, cy = float(pt[0]), float(pt[1])
                        best, bd = None, 1e18
                        for i, (x, y, w, h) in enumerate(coords, 1):
                            d = (x + w / 2 - cx) ** 2 + (y + h / 2 - cy) ** 2
                            if d < bd:
                                bd, best = d, i
                        if best and best not in picked:
                            picked.append(best)
                    picked.sort()
            ok = picked == ans
            rows.append({"name": name, "cond": cond, "ch": ch, "answer": ans,
                         "picked": picked, "ok": ok, "sec": round(el, 1),
                         "err": err, "n_pts": len(raw_pts), "labels": labels,
                         "raw": (text or "")[:1500]})
            print(f"{name:14s} [{cond:4s}] 字={ch!r} 答案={ans} 选中={picked} "
                  f"{'✅' if ok else '❌'} 点={len(raw_pts)} {el:.1f}s {err}", flush=True)

    print("\n" + "=" * 96, flush=True)
    print("汇总", flush=True)
    for cond in conds:
        sub = [r for r in rows if r["cond"] == cond]
        hit = sum(r["ok"] for r in sub)
        # 逐块二分类指标
        tp = fp = fn = tn = 0
        for r in sub:
            for i in range(1, 7):
                if i in r["picked"] and i in r["answer"]:
                    tp += 1
                elif i in r["picked"]:
                    fp += 1
                elif i in r["answer"]:
                    fn += 1
                else:
                    tn += 1
        prec = tp / (tp + fp) * 100 if tp + fp else 0
        rec = tp / (tp + fn) * 100 if tp + fn else 0
        print(f"  {cond:5s} 全对 {hit:2d}/{len(sub)} ({hit/max(1,len(sub))*100:.0f}%)   "
              f"逐块 精度 {prec:.1f}% 召回 {rec:.1f}%  (TP{tp} FP{fp} FN{fn} TN{tn})   "
              f"平均 {sum(r['sec'] for r in sub)/max(1,len(sub)):.0f}s", flush=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    p = os.path.join(OUT, f"ai_preproc_{ts}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    print(f"\n明细 → {p}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
