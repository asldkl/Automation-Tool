# -*- coding: utf-8 -*-
"""测试2（100 张 held-out）结果图：左=按目标字的一次通过率，右=门控曲线（held-out 上扫）。

用法：python tools/captcha/make_test2_chart.py   →  out/test2_eval.png
"""
import csv
import json
import os
import sys

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
sys.path.insert(0, ROOT)
from captcha_glyph_match import confidence, pick_by_threshold  # noqa: E402

CN = r"C:\Windows\Fonts\msyh.ttc"


def blocks(s):
    return sorted({int(c) for c in str(s or "") if c.isdigit() and c != "0"})


with open(os.path.join(OUT, "test2_核对表.csv"), encoding="utf-8-sig", newline="") as f:
    gt = {}
    for r in csv.DictReader(f):
        gt[r["文件名"]] = blocks(r.get("正确答案块（选填）", "")) or blocks(r.get("你的核对（填 对/错）", ""))
with open(os.path.join(OUT, "test2_result.json"), encoding="utf-8") as f:
    recs = json.load(f)["records"]

# 按字统计
agg = {}
for r in recs:
    a = agg.setdefault(r["ch"], [0, 0, 0])
    a[0] += 1
    ok = r["picked"] == gt.get(r["file"])
    if r["action"] == "submit":
        a[1] += 1
        a[2] += ok
order = sorted(agg.items(), key=lambda kv: kv[1][2] / kv[1][0])

W, H = 1080, 620
img = Image.new("RGB", (W, H), (255, 255, 255))
d = ImageDraw.Draw(img)
f_t = ImageFont.truetype(CN, 22)
f_s = ImageFont.truetype(CN, 15)
f_b = ImageFont.truetype(CN, 17)
f_x = ImageFont.truetype(CN, 14)
GREEN, ORANGE, BLUE, GRAY = (29, 130, 90), (216, 130, 40), (24, 95, 165), (150, 150, 150)

d.text((36, 22), "测试2 · 100 张全新样本（你回填真值）· 生产档位 clahe/核35/阈值0.40/门限0.09", font=f_t, fill=(25, 25, 25))
n = len(recs)
sub = sum(1 for r in recs if r["action"] == "submit")
ok_sub = sum(1 for r in recs if r["action"] == "submit" and r["picked"] == gt.get(r["file"]))
pass_all = sum(1 for r in recs if r["picked"] == gt.get(r["file"]))
d.text((36, 54), "提交 %d/100（%.0f%%）· 提交精度 %.1f%% · 一次通过 %d/100 = %.0f%%   ——— "
                 "上一轮 25 张上「精度 100%%」没有通过留出验证" %
       (sub, sub / n * 100, ok_sub / sub * 100, ok_sub, ok_sub / n * 100), font=f_s, fill=(90, 90, 90))
d.text((36, 76), "蓝色 = 提交且正确（一次通过）；橙色 = 提交了但选错。右图：held-out 上扫门限（⚠️只看趋势，别拿扫出来的值当成绩）",
       font=f_s, fill=(150, 150, 150))

# ---- 左：按目标字的一次通过率 ----
LX, LY = 150, 130
ROW = 44
d.text((36, LY - 26), "按目标字的一次通过率（张数 / 提交率）", font=f_b, fill=(60, 60, 60))
for i, (ch, a) in enumerate(order):
    y = LY + i * ROW
    rate = a[2] / a[0]
    d.text((36, y + 8), "「%s」" % ch, font=f_b, fill=(45, 45, 45))
    d.rectangle([LX, y + 6, LX + 330, y + 30], fill=(244, 244, 244))
    wpx = int(330 * rate)
    if wpx:
        d.rectangle([LX, y + 6, LX + wpx, y + 30], fill=GREEN if rate >= 0.9 else ORANGE)
    d.text((LX + 6, y + 10), "%d/%d = %.0f%%" % (a[2], a[0], rate * 100), font=f_b,
           fill=(255, 255, 255) if wpx > 100 else (75, 75, 75))
    d.text((LX + 340, y + 10), "提交 %d/%d" % (a[1], a[0]), font=f_x, fill=GRAY)

# ---- 右：门控曲线 ----
RX0, RX1, RY, RB = 620, 1040, 150, 470
d.text((RX0, RY - 26), "门控曲线（held-out，阈值 0.40）", font=f_b, fill=(60, 60, 60))
rows = []
for r in recs:
    _p = pick_by_threshold(r["scores"], 0.40)
    if not _p or len(_p) == 6:
        continue
    rows.append((confidence(r["scores"], _p), _p == gt.get(r["file"])))
pts = []
for g in [round(0.00 + 0.01 * i, 2) for i in range(31)]:
    sub_l = [x for x in rows if x[0] > g]
    good = sum(1 for x in sub_l if x[1])
    if sub_l:
        pts.append((len(sub_l) / n, good / len(sub_l), g))
for cov, prec, g in pts:
    x = RX0 + (RX1 - RX0) * cov
    y = RB - (RB - RY) * max(0.0, (prec - 0.4)) / 0.6
    d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=BLUE)
for cov, prec, g in pts:
    if abs(g - 0.09) < 1e-9:
        x = RX0 + (RX1 - RX0) * cov
        y = RB - (RB - RY) * max(0.0, (prec - 0.4)) / 0.6
        d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=ORANGE, width=3)
        d.text((x - 10, y - 8), "现用门限 0.09：覆盖 %.0f%% / 精度 %.0f%%" % (cov * 100, prec * 100),
               font=f_x, fill=ORANGE, anchor="ra")
d.rectangle([RX0, RY, RX1, RB], outline=(210, 210, 210), width=1)
d.line([(RX0, RB), (RX1, RB)], fill=(180, 180, 180), width=1)
d.text(((RX0 + RX1) / 2, RB + 10), "覆盖率（提交 / 100）", font=f_x, fill=GRAY, anchor="ma")
d.text((RX0 - 10, RY - 4), "100%", font=f_x, fill=GRAY, anchor="ra")
d.text((RX0 - 10, RB - 8), "40%", font=f_x, fill=GRAY, anchor="ra")

d.text((36, H - 74), "结论：这批的错误以「漏选」为主（6 漏 / 3 误 / 2 漏+误），与旧集「全是多选」相反 —— "
                     "低笔画字（才/下/士/土）的目标块分数偏低。", font=f_s, fill=(150, 90, 20))
d.text((36, H - 50), "门控的代价：为了不提交 13 张错的，也丢掉了 6 张本来选对的；"
                     "打开「换一组」能让这 19 张自动重试，而不是直接转人工。", font=f_s, fill=(150, 90, 20))

p = os.path.join(OUT, "test2_eval.png")
img.save(p)
print("saved", p, img.size)
