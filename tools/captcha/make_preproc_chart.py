# -*- coding: utf-8 -*-
"""把 exp_preproc 的 10 个变体画成对比图（CV 全对 + AUC）。"""
import os

from PIL import Image, ImageDraw, ImageFont

def _find_root(start):
    """向上找带 captcha_glyph_match.py 的目录作仓库根。

    路径用「向上找 captcha_glyph_match.py」的锚点写法，换目录也不用改。
    """
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

# (名称, CV全对, 拟合全对, AUC, 是否指标不适用)
DATA = [
    ("CLAHE + bh25", 21, 23, 0.997, False),
    ("平场除 + bh25", 19, 21, 0.997, False),
    ("基线 bh25", 16, 19, 0.985, False),
    ("bh35", 16, 19, 0.986, False),
    ("bh45", 15, 19, 0.989, False),
    ("梯度幅值", 6, 7, 0.773, False),
    ("双极性 bh25+th25", 2, 4, 0.729, False),
    ("局部std31", 2, 3, 0.618, False),
    ("融合 bh25+bh35+bh45", 0, 2, 0.462, True),
    ("融合 bh25+bh45", 0, 0, 0.500, True),
]
N = 25
W, HDR, ROW, FTR = 940, 104, 42, 56
H = HDR + ROW * len(DATA) + FTR
X0, X1 = 300, 840
img = Image.new("RGB", (W, H), (255, 255, 255))
d = ImageDraw.Draw(img)
f_t = ImageFont.truetype(CN, 21)
f_s = ImageFont.truetype(CN, 15)
f_b = ImageFont.truetype(CN, 17)
f_x = ImageFont.truetype(CN, 14)

d.text((30, 22), "验证码「包含文字」预处理对比 · 25 张实测", font=f_t, fill=(25, 25, 25))
d.text((30, 52), "深色 = 2 折交叉验证全对（诚实口径，阈值由另一折选出）　浅色 = 同批图上拟合（乐观，仅示过拟合幅度）",
       font=f_s, fill=(110, 110, 110))
d.text((30, 74), "评价口径：黑帽 K25 · 4 字体 · 尺度 0.6~1.1 · 角度 ±30°；分数只算一次后缓存",
       font=f_s, fill=(150, 150, 150))


def x_of(v):
    return X0 + (X1 - X0) * v / N


for i in range(0, N + 1, 5):
    xx = x_of(i)
    d.line([(xx, HDR - 6), (xx, HDR + ROW * len(DATA))], fill=(232, 232, 232), width=1)
    d.text((xx - 7, HDR + ROW * len(DATA) + 8), str(i), font=f_x, fill=(150, 150, 150))

for k, (name, cv, fit, auc, na) in enumerate(DATA):
    y = HDR + k * ROW
    cy = y + ROW // 2
    label = name + ("  *" if na else "")
    d.text((288, cy - 9), label, font=f_b, fill=(35, 35, 35), anchor="ra")
    if na:
        fill_hi, fill_lo, txt = (222, 222, 222), (240, 240, 240), (130, 130, 130)
    elif cv >= 19:
        fill_hi, fill_lo, txt = (15, 110, 86), (159, 225, 203), (4, 52, 44)
    elif cv >= 15:
        fill_hi, fill_lo, txt = (24, 95, 165), (181, 212, 244), (4, 44, 83)
    else:
        fill_hi, fill_lo, txt = (136, 135, 128), (211, 209, 199), (44, 44, 42)
    if fit:
        d.rectangle([X0, cy - 15, x_of(fit), cy + 15], fill=fill_lo)
    if cv:
        d.rectangle([X0, cy - 15, x_of(cv), cy + 15], fill=fill_hi)
    else:
        d.line([(X0, cy - 15), (X0 + 3, cy - 15)], fill=fill_hi, width=3)
        d.line([(X0, cy + 15), (X0 + 3, cy + 15)], fill=fill_hi, width=3)
    d.rectangle([X0, cy - 15, X1, cy + 15], outline=(210, 210, 210), width=1)
    d.text((x_of(max(fit, 1)) + 8, cy - 10), f"{cv}/{N}", font=f_b, fill=txt)
    d.text((X1 + 14, cy - 9), f"AUC {auc:.3f}", font=f_x, fill=(140, 140, 140))

yy = HDR + ROW * len(DATA) + 30
d.text((30, yy), "* 融合行的指标不适用：融合做了逐图 minmax 归一化，分数跨图不可比，"
                "全局 AUC / 全局阈值对它天然失效；其正确口径是图内排序。",
       font=f_s, fill=(150, 120, 60))

p = os.path.join(OUT, "preproc_compare.png")
img.save(p)
print("saved", p, img.size)
