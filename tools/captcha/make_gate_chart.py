# -*- coding: utf-8 -*-
"""门控形态对照图：精度 vs 覆盖率（基线黑帽 vs CLAHE+黑帽）。

数据来自 `tools/captcha/out/exp_gate_clahe.txt`（25 张、阈值 0.37 下的选中集）。
怎么看：越靠右 = 自动提交比例越高；越靠上 = 越可靠。**100% 精度那条线才是能放手自动提交的区域**。
"""
import os

from PIL import Image, ImageDraw, ImageFont


def _find_root(start):
    """向上找带 captcha_glyph_match.py 的目录（本脚本在 tools/captcha/ 下）。"""
    p = start
    for _ in range(6):
        if os.path.exists(os.path.join(p, "captcha_glyph_match.py")):
            return p
        p = os.path.dirname(p)
    return start


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".workbuddy", "out")
os.makedirs(OUT, exist_ok=True)
CN = r"C:\Windows\Fonts\msyh.ttc"

# 变体 → [(conf门限, 提交张数, 精度%, 覆盖%)]
DATA = {
    "基线 bh25": [
        (0.00, 25, 76.0, 100.0), (0.06, 23, 78.3, 92.0), (0.10, 21, 76.2, 84.0),
        (0.12, 19, 84.2, 76.0), (0.14, 17, 94.1, 68.0), (0.16, 15, 100.0, 60.0),
        (0.18, 9, 100.0, 36.0), (0.20, 7, 100.0, 28.0), (0.25, 5, 100.0, 20.0),
        (0.30, 2, 100.0, 8.0),
    ],
    "CLAHE+bh25": [
        (0.00, 25, 80.0, 100.0), (0.06, 24, 83.3, 96.0), (0.10, 18, 88.9, 72.0),
        (0.12, 16, 87.5, 64.0), (0.14, 15, 93.3, 60.0), (0.16, 13, 92.3, 52.0),
        (0.18, 11, 90.9, 44.0), (0.20, 9, 88.9, 36.0), (0.25, 6, 83.3, 24.0),
        (0.30, 3, 66.7, 12.0),
    ],
}
COLOR = {"基线 bh25": (24, 95, 165), "CLAHE+bh25": (200, 96, 28)}

W, H = 940, 660
L, R, T, B = 120, 870, 134, 500          # 绘图区
XMIN, XMAX = 0.0, 100.0                  # 覆盖率 %
YMIN, YMAX = 50.0, 100.0                 # 精度 %

img = Image.new("RGB", (W, H), (255, 255, 255))
d = ImageDraw.Draw(img)
f_t = ImageFont.truetype(CN, 22)
f_s = ImageFont.truetype(CN, 15)
f_b = ImageFont.truetype(CN, 17)
f_x = ImageFont.truetype(CN, 14)

d.text((40, 26), "门控形态对照 · 25 张实测（阈值 0.37 下的选中集）", font=f_t, fill=(25, 25, 25))
d.text((40, 58), "越靠右 = 自动提交比例越高；越靠上 = 越可靠。只有站在 100% 精度线上，才敢放手自动提交。",
       font=f_s, fill=(105, 105, 105))
d.text((40, 82), "conf = 选中块最低分 − 未选中块最高分；门限越高 → 提交越少、越保守。每个点 = 一个门限档位。",
       font=f_s, fill=(150, 150, 150))


def xp(cov):
    return L + (R - L) * (cov - XMIN) / (XMAX - XMIN)


def yp(prec):
    return B - (B - T) * (prec - YMIN) / (YMAX - YMIN)


# 网格 + 坐标
for prec in range(50, 101, 10):
    y = yp(prec)
    d.line([(L, y), (R, y)], fill=(236, 236, 236), width=1)
    d.text((L - 12, y - 8), f"{prec}%", font=f_x, fill=(150, 150, 150), anchor="ra")
for cov in range(0, 101, 20):
    x = xp(cov)
    d.line([(x, T), (x, B)], fill=(244, 244, 244), width=1)
    d.text((x, B + 12), f"{cov}%", font=f_x, fill=(150, 150, 150), anchor="ma")

d.rectangle([L, T, R, B], outline=(205, 205, 205), width=1)
d.text(((L + R) / 2, B + 36), "覆盖率（自动提交的图 / 25 张）", font=f_b, fill=(60, 60, 60), anchor="ma")

# 100% 精度线
y100 = yp(100.0)
for x in range(L, R, 12):
    d.line([(x, y100), (x + 6, y100)], fill=(198, 40, 40), width=2)
d.text((R - 4, y100 + 10), "100% 精度（可放手自动提交）", font=f_b, fill=(198, 40, 40), anchor="ra")

# 两条折线
for name, series in DATA.items():
    pts = [(xp(c), yp(p)) for (_g, _n, p, c) in series]
    d.line(pts, fill=COLOR[name], width=3, joint="curve")
    for (g, n, p, c), (x, y) in zip(series, pts):
        d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=COLOR[name])

# 关键点：只画圈，文字统一放进左下角空白处的说明框
for name, g in (("基线 bh25", 0.16), ("CLAHE+bh25", 0.14)):
    g_, n, p, c = next(s for s in DATA[name] if abs(s[0] - g) < 1e-9)
    x, y = xp(c), yp(p)
    d.ellipse([x - 7, y - 7, x + 7, y + 7], outline=COLOR[name], width=3)
    d.line([(x, y), (x + 46, B - 108)], fill=COLOR[name], width=1)

bx0, by0 = L + 22, B - 104
d.rectangle([bx0, by0, bx0 + 330, by0 + 88], fill=(250, 250, 250), outline=(216, 216, 216), width=1)
d.text((bx0 + 12, by0 + 9), "同覆盖率下的关键点对比", font=f_b, fill=(60, 60, 60))
d.line([(bx0 + 12, by0 + 34), (bx0 + 38, by0 + 34)], fill=COLOR["基线 bh25"], width=4)
d.text((bx0 + 46, by0 + 26), "基线  门限 0.16 → 覆盖 60%，精度 100%", font=f_s, fill=(45, 45, 45))
d.line([(bx0 + 12, by0 + 60), (bx0 + 38, by0 + 60)], fill=COLOR["CLAHE+bh25"], width=4)
d.text((bx0 + 46, by0 + 52), "CLAHE 门限 0.14 → 覆盖 60%，精度 93.3%", font=f_s, fill=(45, 45, 45))

# 图例
lx, ly = L + 10, T + 14
for i, name in enumerate(DATA):
    yy = ly + i * 26
    d.line([(lx, yy), (lx + 30, yy)], fill=COLOR[name], width=4)
    d.text((lx + 38, yy - 9), name, font=f_b, fill=(45, 45, 45))

# 结论条（两行，确保不超宽）
d.text((40, H - 54),
       "结论：CLAHE 把 AUC、CV、排序 oracle 全部做上去了，却让 conf 的分离度变差 —— 没有任何门限能到 100% 精度。",
       font=f_s, fill=(150, 90, 20))
d.text((40, H - 32),
       "落地形态是门控，所以「指标更好」≠「可上线」：先别把 CLAHE 换进生产。",
       font=f_s, fill=(150, 90, 20))

p = os.path.join(OUT, "gate_compare.png")
img.save(p)
print("saved", p, img.size)
