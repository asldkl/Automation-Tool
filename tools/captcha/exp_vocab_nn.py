# -*- coding: utf-8 -*-
"""实验：用**逐块分类**代替「阈值切档」，试解「不知道要选几张」。

动机（用户提出、也是唯一瓶颈）：
  现在的做法是「给每块打一个『像不像目标字』的分 → 用一个全局阈值切档」。
  但不同图难度不同、分数尺度不同（几何上不存在全局阈值），所以「该选几块」判不了。
  主流点选验证码项目的做法是**逐块分类**：每块归到某个字，然后
      选中集 = {块 | 分类结果 == 目标字}
  → **k 自动得出**，不需要阈值。

本脚本走**零训练**版本：把 GB2312 一级字库（3755 字）渲染成模板，
和每块图做「同一算子空间」的描述子最近邻：
  图块  → blackhat(核K) 笔画响应 → 取响应最强的前 q% 像素的 bbox → 裁 → 40×40 → 标准化 → L2
  模板  → 渲染成「浅底深字」（fill=0 on 255）→ **同样 blackhat** → bbox → 40×40 → 标准化 → L2
两个描述子因此语义一致（都是"深色细笔画"的响应），再比余弦相似度。

输出：逐图 选中集 vs 答案、k 是否正确、逐块 P/R，并与「现有生产阈值法」在同一批图上的成绩并列。

用法：python tools/captcha/exp_vocab_nn.py
缓存：.workbuddy/out/vocab_nn_chars.npz（模板描述子，首次约 1 分钟）、vocab_nn_tiles.npz
"""
import json
import os
import pickle
import re
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

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
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, ROOT)

from captcha_glyph_match import BH_KERNEL, _blackhat, _ellipse  # noqa: E402

KERNEL = 35          # 与生产档位一致
DESC = 40            # 描述子边长
INK_Q = 0.90         # 取响应前 (1-INK_Q) 的像素估 bbox（越大越宽松）
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONTS = ["simhei.ttf", "msyh.ttc"]
CHARS_CACHE = os.path.join(OUT, "vocab_nn_chars.npz")
TILES_PKL = os.path.join(OUT, "gate_sweep_tiles.pkl")
SCORES_JSON = os.path.join(OUT, "gate_sweep_scores.json")


def vocab_gb2312_level1():
    """GB2312 一级汉字（3755 个），覆盖常用字"""
    out = []
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.append(bytes([hi, lo]).decode("gb2312"))
            except Exception:      # noqa: BLE001
                pass
    return out


def ink_bbox(x, q=INK_Q):
    """响应图里最亮的一撮像素的 bbox（估笔画范围），退化时返回整幅"""
    h, w = x.shape[:2]
    thr = float(np.percentile(x, q * 100))
    ys, xs = np.where(x >= thr)
    if ys.size < 8:
        return 0, 0, w, h
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    if (x1 - x0) < 6 or (y1 - y0) < 6:
        return 0, 0, w, h
    return x0, y0, x1 - x0, y1 - y0


def l2_std(a):
    a = a.astype(np.float32)
    a = (a - a.mean()) / (a.std() + 1e-6)
    n = float(np.linalg.norm(a))
    return (a / n) if n else a


def desc_from_response(resp):
    """响应图 → bbox → 正方形 letterbox 到 DESC×DESC → 标准化+L2"""
    x0, y0, bw, bh = ink_bbox(resp)
    crop = resp[y0:y0 + bh, x0:x0 + bw]
    s = max(bw, bh)
    pad = np.zeros((s, s), np.float32)
    ox, oy = (s - bw) // 2, (s - bh) // 2
    pad[oy:oy + bh, ox:ox + bw] = crop
    d = cv2.resize(pad, (DESC, DESC), interpolation=cv2.INTER_AREA)
    return l2_std(d)


def tile_desc(tile_bgr):
    """图块 → 灰度 → blackhat → 描述子"""
    g = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return desc_from_response(_blackhat(g, KERNEL))


def build_char_desc(vocab, force=False):
    if os.path.exists(CHARS_CACHE) and not force:
        z = np.load(CHARS_CACHE, allow_pickle=True)
        chars, mat = list(z["chars"]), z["mat"]
        if len(chars) == len(vocab):
            print("模板缓存命中：%d 字 × %d 模板，矩阵 %s" % (len(chars), len(FONTS), mat.shape),
                  flush=True)
            return chars, mat
    print("渲染 %d 字 × %d 字体模板…" % (len(vocab), len(FONTS)), flush=True)
    t0 = time.time()
    per_char = []
    for i, ch in enumerate(vocab):
        rows = []
        for fp in FONTS:
            path = os.path.join(FONT_DIR, fp)
            if not os.path.exists(path):
                continue
            img = Image.new("L", (192, 192), 255)          # 浅底
            try:
                ImageDraw.Draw(img).text((60, 30), ch, fill=0,
                                         font=ImageFont.truetype(path, 128))
            except Exception:                              # noqa: BLE001
                continue
            g = np.asarray(img, np.float32)
            rows.append(desc_from_response(_blackhat(g, KERNEL)))
        if rows:
            per_char.append(np.stack(rows))
        if (i + 1) % 500 == 0:
            print("  %d/%d … %.0fs" % (i + 1, len(vocab), time.time() - t0), flush=True)
    chars, mat = vocab, np.stack(per_char)                 # (V, F, DESC*DESC)
    np.savez_compressed(CHARS_CACHE, chars=np.array(chars), mat=mat)
    print("模板渲染完成 %.0fs，矩阵 %s（已缓存）" % (time.time() - t0, mat.shape), flush=True)
    return chars, mat


def main():
    vocab = vocab_gb2312_level1()
    chars, mat = build_char_desc(vocab)
    flat = mat.reshape(mat.shape[0] * mat.shape[1], -1)     # (V*F, D)
    char_of_row = np.repeat(np.arange(mat.shape[0]), mat.shape[1])

    with open(TILES_PKL, "rb") as f:
        tiles = pickle.load(f)
    print("图 %d 张，词表 %d 字 × %d 模板" % (len(tiles), len(chars), len(FONTS)), flush=True)
    print("", flush=True)

    rows = []
    for key in sorted(tiles):
        rec = tiles[key]
        ans, target = rec["answer"], rec["ch"]
        if not target or not rec["tiles"]:
            continue
        t0 = time.time()
        D = np.stack([tile_desc(t) for t in rec["tiles"]]).reshape(len(rec["tiles"]), -1)
        sim = D @ flat.T                                     # (n_tile, V*F) 余弦
        best_row = sim.argmax(axis=1)
        pred_char = [chars[char_of_row[r]] for r in best_row]
        picked = sorted(i + 1 for i, c in enumerate(pred_char) if c == target)
        margin = sim.max() - np.sort(sim, axis=1)[:, -2].max()   # 仅参考
        rows.append({"key": key, "ch": target, "answer": ans, "picked": picked,
                     "pred": pred_char, "sim": [round(float(v), 3) for v in sim.max(axis=1)],
                     "sec": round(time.time() - t0, 2)})

    n_exact = n_sub = n_ok = 0
    tp = fp = fn = 0
    for r in rows:
        exact = r["picked"] == r["answer"]
        n_exact += exact
        n_sub += 1
        n_ok += exact
        for i in range(1, 7):
            in_pred, in_ans = i in r["picked"], i in r["answer"]
            tp += in_pred and in_ans
            fp += in_pred and not in_ans
            fn += (not in_pred) and in_ans
        print("  %-18s 字=%-2s 预测选中=%-16s 答案=%-16s %s  (%.1fs)"
              % (r["key"], r["ch"], str(r["picked"]), str(r["answer"]),
                 "✅" if exact else "❌", r["sec"]))
    p = tp / (tp + fp) if (tp + fp) else 0
    rc = tp / (tp + fn) if (tp + fn) else 0
    print("")
    print("逐块分类（词表最近邻，零训练）：全对 %d/%d = %.0f%%   逐块 精度 %.0f%% / 召回 %.0f%%"
          % (n_exact, n_sub, n_exact / n_sub * 100, p * 100, rc * 100))

    # 同一批图上的现有生产档位（cl ahe35 + 阈值 0.40 + 门限 0.09）作对照
    try:
        with open(SCORES_JSON, encoding="utf-8") as f:
            sc = json.load(f)["clahe35"]
        sys.path.insert(0, ROOT)
        from captcha_glyph_match import pick_by_threshold
        base_ok = 0
        for k, rec in sc.items():
            a = re.split(r"[\s(（]", os.path.splitext(k.split("/", 1)[1])[0])[0]
            ans = sorted({int(c) for c in a if c.isdigit()})
            base_ok += pick_by_threshold(rec, 0.40) == ans
        print("对照 · 现有生产档位（阈值 0.40 直接判定）：全对 %d/%d = %.0f%%"
              % (base_ok, len(sc), base_ok / len(sc) * 100))
    except Exception as e:      # noqa: BLE001
        print("对照数据不可用：%s" % e)

    with open(os.path.join(OUT, "exp_vocab_nn.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print("明细已写出 out/exp_vocab_nn.json")


if __name__ == "__main__":
    main()
