# -*- coding: utf-8 -*-
"""把 exp_gate_sweep.py 的汇总画成一张对照图（PIL，不引 matplotlib）。

横条 = 门控 CV 覆盖率（上线口径：训练折挑 (阈值,门限)、测试折评估，要求精度 100%）。
绿 = 测试折精度仍 100%；橙 = 掉到 100% 以下（说明门控不稳，不能上）。
右侧两列数字 = 阈值法 CV 全对 / oracle 排序上界（都是 25 张口径）。

用法：python tools/captcha/make_gate_sweep_chart.py
输出：.workbuddy/out/gate_sweep_compare.png
"""
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
SUMMARY = os.path.join(OUT, "exp_gate_sweep_summary.json")
CN = r"C:\Windows\Fonts\msyh.ttc"

with open(SUMMARY, encoding="utf-8") as f:
    doc = json.load(f)
S = doc["summary"]
N = doc["n"]
THR = doc["threshold"]
GATE = doc["gate"]

order = sorted(S, key=lambda k: -S[k]["gate_cv"][0])
ROWH, PAD = 48, 10
L, BX0, BX1 = 190, 190, 610          # 名称列 / 条形区
W = 1000
H = 168 + ROWH * len(order) + 96

img = Image.new("RGB", (W, H), (255, 255, 255))
d = ImageDraw.Draw(img)
f_t = ImageFont.truetype(CN, 22)
f_s = ImageFont.truetype(CN, 15)
f_b = ImageFont.truetype(CN, 17)
f_x = ImageFont.truetype(CN, 14)

d.text((40, 26), "图像处理变体对照 · 门控 CV 口径（25 张，要求精度 100%）", font=f_t, fill=(25, 25, 25))
d.text((40, 58), "目标：在不牺牲可靠性的前提下，让「敢自动提交」的比例尽量高。条形越长越好，"
                 "但要连着条上的精度一起看。", font=f_s, fill=(105, 105, 105))
d.text((40, 82), "阈值与门限都在训练折上挑、在测试折上评估（2 折），没有「同批图挑超参」的乐观偏差；"
                 "橙色 = 测试折精度未达 100%。", font=f_s, fill=(150, 150, 150))
d.text((40, 108), "本次结论：生产档位由 bh25（核 25，阈值 %.2f / 门限 %.2f）改为 clahe35（核 35，阈值 0.40 / 门限 0.09）。"
       % (THR, GATE), font=f_s, fill=(95, 95, 95))

x0, y0 = BX0, 168
d.text((40, y0 - 24), "变体（图像处理）", font=f_b, fill=(60, 60, 60))
d.text((BX0, y0 - 24), "门控 CV 覆盖率（自动提交的图 / %d 张）" % N, font=f_b, fill=(60, 60, 60))
d.text((BX1 + 18, y0 - 24), "阈值法 CV", font=f_b, fill=(60, 60, 60))
d.text((BX1 + 118, y0 - 24), "oracle 排序", font=f_b, fill=(60, 60, 60))

for i, v in enumerate(order):
    r = S[v]
    cov, good, n = r["gate_cv"]
    prec = r["gate_prec"]
    yy = y0 + i * ROWH
    ok = prec >= 99.995
    col = (29, 158, 117) if ok else (216, 130, 40)
    d.text((40, yy + 12), v.replace("（生产）", "（旧档位）"), font=f_b, fill=(45, 45, 45))
    d.rectangle([BX0, yy + 8, BX1, yy + 32], fill=(244, 244, 244))
    wpx = 0 if not n else int((BX1 - BX0) * cov / n)
    if wpx:
        d.rectangle([BX0, yy + 8, BX0 + wpx, yy + 32], fill=col)
    d.text((BX1 + 18, yy + 12), "%d/%d" % (r["cv_thr"], n), font=f_b, fill=(45, 45, 45))
    d.text((BX1 + 118, yy + 12), "%d/%d" % (r["rank"], n), font=f_b, fill=(45, 45, 45))
    d.text((BX0 + 6, yy + 12), "%d/%d  (%.0f%%)  精度 %.0f%%" % (cov, n, cov / n * 100 if n else 0, prec),
           font=f_b, fill=(255, 255, 255) if wpx > 210 else (75, 75, 75))

best = S[order[0]]
best_cov = best["gate_cv"][0]
best_ok = best["gate_cv"][1]
base = S.get("bh25（生产）")
lines = []
if base is not None:
    base_cov, base_ok = base["gate_cv"][0], base["gate_cv"][1]
    if best_cov > base_cov or best_ok > base_ok:
        lines.append("结论：%s 把「提交且正确」从 %d/%d 提到 %d/%d（测试折精度 %.0f%% → %.0f%%）——已换为生产档位。"
                     % (order[0], base_ok, N, best_ok, N, base["gate_prec"], best["gate_prec"]))
    else:
        lines.append("结论：没有任何变体比旧档位（bh25）更好 → 维持 bh25，不折腾图像处理。")
lines.append("注意：n=%d，1 张图就值 4 个百分点，CI 很宽；且旧档位「精度 100%%」是同批图上扫出来的假象（CV 只有 82%%）。" % N)

yy = y0 + ROWH * len(order) + 16
for i, t in enumerate(lines):
    d.text((40, yy + i * 24), t, font=f_s, fill=(150, 90, 20) if i == 0 else (150, 150, 150))

p = os.path.join(OUT, "gate_sweep_compare.png")
img.save(p)
print("saved", p, img.size)
sys.exit(0)
