# -*- coding: utf-8 -*-
"""测试2（100 张，**无答案**）跑生产档位，产出可人工核对的判定结果。

口径说明：这批图没有答案，所以**算不出准确率** —— 脚本只输出：
  · 每张图的 逐块分数 / 选中块 / conf / 决策（submit 还是换一组）
  · 汇总：自动提交率、conf 分布、需人工/换一组的比例
  · 判定图（每块标注「分数」+「识别模型读出的字」），供你逐张核对

标注含义（没有答案，所以不能标对错）：
  深绿粗框 = 算法选中；灰细框 = 未选；橙标 = OCR 独读到目标字但算法没选（可疑漏选）
  每块下方 = 字形分数；上方 = OCR 读出的字（读不出则空）

用法：python tools/captcha/test_set2.py            # 打分 + 出图
      ONLY_SHEETS=1 python tools/captcha/test_set2.py   # 只重出图（用缓存）
"""
import glob
import json
import os
import re
import sys
import time

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
SHEET_DIR = os.path.join(OUT)
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "captcha"))

import ai_visual_captcha as avc  # noqa: E402
import utils  # noqa: E402
from captcha_glyph_flow import _get_matcher, read_profile  # noqa: E402
from captcha_glyph_match import decide  # noqa: E402
import config  # noqa: E402

FOLDER = os.path.join(ROOT, "图片文字点击验证例图", "测试2")
RESULT_JSON = os.path.join(OUT, "test2_result.json")
TXT_RE = re.compile(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])")
CJK = re.compile(r"[\u4e00-\u9fff]")
PER_SHEET = 10
CN_FONT = r"C:\Windows\Fonts\msyh.ttc"

LOG = []


def P(*a, **kw):
    s = " ".join(str(x) for x in a)
    LOG.append(s)
    kw.setdefault("flush", True)
    print(s, **kw)


def pick_files():
    """取今晚 00:05 那批样本（100 张）；排除 preview_* 与 09-21 的旧样本"""
    allf = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".png"))
    keep, skip = [], []
    for f in allf:
        if f.startswith("preview_"):
            skip.append((f, "UI 预览图"))
        elif "20260922-" not in f:
            skip.append((f, "非本批（时间戳不是 09-22）"))
        else:
            keep.append(f)
    return keep, skip


def score_all(prof, files, engine):
    recs = []
    t0 = time.time()
    for i, nm in enumerate(files, 1):
        path = os.path.join(FOLDER, nm)
        bgr = np.array(Image.open(path).convert("RGB"))[:, :, ::-1].copy()
        res, _ = engine(bgr)
        m = TXT_RE.search("".join(str(x[1]) for x in (res or [])))
        ch = m.group(1) if m else ""
        coords = avc.detect_image_tiles(bgr)
        tiles = [bgr[y:y + h, x:x + w].copy() for (x, y, w, h) in coords]
        if ch and tiles:
            matcher = _get_matcher(prof)
            scores = matcher.score_tiles(tiles, ch)
            d = decide(scores, threshold=prof["threshold"], gate=prof["gate"])
            # 只识别不检测：给每块标注"读出来的字"（精度 100%，用于人工核对）
            texts = []
            for t in tiles:
                try:
                    g = cv2_gray2x(t)
                    out = engine.text_recognizer([g])
                    texts.append(str(out[0][0][0]) if (out and out[0]) else "")
                except Exception:      # noqa: BLE001
                    texts.append("")
        else:
            scores, d, texts = [], {"action": "refresh", "picked": [], "conf": 0.0,
                                    "reason": "没读出目标字" if not ch else "没检出图块"}, []
        recs.append({"file": nm, "ch": ch, "n_tiles": len(tiles), "scores": [round(float(v), 4) for v in scores],
                     "picked": d["picked"], "conf": round(float(d.get("conf", 0.0)), 4),
                     "action": d["action"], "mode": d.get("mode", ""), "reason": d.get("reason", ""),
                     "ocr": texts})
        if i % 10 == 0:
            P("  …%d/%d  %.0fs" % (i, len(files), time.time() - t0))
    return recs


def cv2_gray2x(t):
    import cv2
    g = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    return cv2.resize(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), None, fx=2, fy=2,
                      interpolation=cv2.INTER_CUBIC)


def make_sheets(recs):
    """每张图一行：目标字/选中/conf/决策 + 6 块（分数 + 识别出的字）"""
    import cv2
    f_t = ImageFont.truetype(CN_FONT, 17)
    f_s = ImageFont.truetype(CN_FONT, 14)
    f_x = ImageFont.truetype(CN_FONT, 13)
    TW = 150
    W = 40 + 6 * (TW + 6)
    ROW_H = TW + 46
    HEAD = 76
    GREEN = (29, 130, 90)
    GRAY = (150, 150, 150)
    ORANGE = (216, 130, 40)
    paths = []
    for si in range(0, len(recs), PER_SHEET):
        chunk = recs[si:si + PER_SHEET]
        H = HEAD + ROW_H * len(chunk) + 20
        img = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((28, 16), "测试2 判定结果 · 第 %d 批（%d~%d / 共 %d 张）"
               % (si // PER_SHEET + 1, si + 1, si + len(chunk), len(recs)), font=f_t, fill=(25, 25, 25))
        d.text((28, 42), "深绿粗框=算法选中 · 灰细框=未选 · 橙=OCR 独读到目标字但没被选中（可疑漏选）"
                         " · 块下数字=字形分数 · 块上字=识别模型读出的字", font=f_s, fill=(120, 120, 120))
        for ri, r in enumerate(chunk):
            y0 = HEAD + ri * ROW_H
            act = "提交" if r["action"] == "submit" else "换一组"
            col = GREEN if r["action"] == "submit" else ORANGE
            d.text((28, y0), "%s  目标「%s」  选中 %s  conf %+.3f  → %s"
                   % (r["file"].replace("sample_", "s").replace(".png", ""), r["ch"],
                      str(r["picked"]), r["conf"], act), font=f_s, fill=col)
            d.line([(28, y0 + 22), (W - 28, y0 + 22)], fill=(232, 232, 232), width=1)
            bgr = np.array(Image.open(os.path.join(FOLDER, r["file"])).convert("RGB"))[:, :, ::-1].copy()
            coords = avc.detect_image_tiles(bgr)
            for ti, (x, y, w, h) in enumerate(coords, 1):
                tile = bgr[y:y + h, x:x + w]
                tim = Image.fromarray(tile[:, :, ::-1])
                tim = tim.resize((TW, TW), Image.LANCZOS)
                tx = 40 + (ti - 1) * (TW + 6)
                ty = y0 + 26
                img.paste(tim, (tx, ty))
                sel = ti in r["picked"]
                box = [tx, ty, tx + TW - 1, ty + TW - 1]
                if sel:
                    d.rectangle(box, outline=GREEN, width=3)
                    d.text((tx + 5, ty + 4), "✓", font=f_s, fill=(255, 255, 255))
                else:
                    d.rectangle(box, outline=GRAY, width=1)
                sc = r["scores"][ti - 1] if ti <= len(r["scores"]) else None
                d.text((tx + 3, ty + TW + 2), "%.3f" % sc if sc is not None else "-", font=f_x,
                       fill=GREEN if sel else GRAY)
                ocr_txt = r["ocr"][ti - 1] if ti - 1 < len(r["ocr"]) else ""
                if ocr_txt:
                    hit = r["ch"] and r["ch"] in ocr_txt
                    d.text((tx + TW - 20, ty + TW + 2), ocr_txt[:1], font=f_s,
                           fill=ORANGE if (hit and not sel) else (60, 60, 60))
        p = os.path.join(SHEET_DIR, "test2_sheet_%02d.png" % (si // PER_SHEET + 1))
        img.save(p)
        paths.append(p)
        P("  出图 %s  %s" % (os.path.basename(p), img.size))
    return paths


def main():
    files, skip = pick_files()
    prof = read_profile(config.load_settings())
    P("目录：%s" % FOLDER)
    P("参与打分：%d 张" % len(files))
    for f, why in skip:
        P("  排除 %-34s （%s）" % (f, why))
    P("生产档位：%s" % prof)
    P("")

    if os.environ.get("ONLY_SHEETS") and os.path.exists(RESULT_JSON):
        with open(RESULT_JSON, encoding="utf-8") as f:
            recs = json.load(f)["records"]
        P("用缓存记录 %d 条，只重出图" % len(recs))
    else:
        engine = utils._get_ocr_engine()
        recs = score_all(prof, files, engine)
        with open(RESULT_JSON, "w", encoding="utf-8") as f:
            json.dump({"profile": prof, "folder": FOLDER, "n": len(recs),
                       "time": time.strftime("%Y-%m-%d %H:%M"), "records": recs},
                      f, ensure_ascii=False, indent=1)
        P("")
        P("明细已写出 %s" % os.path.relpath(RESULT_JSON, ROOT))

    # ---- 汇总（没有答案，只能报"提交率/覆盖率"，不能报准确率）----
    n = len(recs)
    n_sub = sum(1 for r in recs if r["action"] == "submit")
    P("")
    P("=" * 88)
    P("汇总（⚠️这批没有答案 → 只能算「自动提交比例」，**准确率要你核对判定图**）")
    P("=" * 88)
    P("  共 %d 张：自动提交 %d 张（%.0f%%）、转「换一组/人工」%d 张（%.0f%%）"
      % (n, n_sub, n_sub / n * 100, n - n_sub, (n - n_sub) / n * 100))
    confs = sorted(r["conf"] for r in recs if r["action"] == "submit")
    if confs:
        P("  已提交的 conf：最小 %+.3f / 中位 %+.3f / 最大 %+.3f"
          % (confs[0], confs[len(confs) // 2], confs[-1]))
    mild = [r for r in recs if r["action"] != "submit"]
    if mild:
        P("  未提交的 %d 张：" % len(mild))
        for r in mild[:15]:
            P("    %-34s 目标「%s」 conf %+.3f  选中%s  (%s)"
              % (r["file"], r["ch"], r["conf"], str(r["picked"]), r["reason"]))
    # OCR 读出目标字但算法没选 → 可疑漏选
    susp = []
    for r in recs:
        for i, t in enumerate(r["ocr"], 1):
            if t and r["ch"] and r["ch"] in t and i not in r["picked"]:
                susp.append((r["file"], r["ch"], i, r["picked"]))
    P("")
    P("  可疑漏选（OCR 明确读到目标字、算法却没选该块）：%d 处" % len(susp))
    for f, ch, i, pk in susp[:15]:
        P("    %-34s 目标「%s」 第 %d 块  算法选中%s" % (f, ch, i, str(pk)))

    P("")
    P("正在出判定图（每批 %d 张）…" % PER_SHEET)
    paths = make_sheets(recs)
    P("")
    P("判定图 %d 张：%s" % (len(paths), os.path.relpath(SHEET_DIR, ROOT)))
    with open(os.path.join(OUT, "test2_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n")


if __name__ == "__main__":
    main()
