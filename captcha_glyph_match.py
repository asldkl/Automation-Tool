# -*- coding: utf-8 -*-
"""「包含文字」类验证码 —— 字形模板匹配求解器（不依赖大模型、离线、零 API 成本）

原理
----
这类验证码的 6 张图里，目标汉字是"用绿树/山脊/雪坡/河谷等自然景物拼出来的"。
人眼在彩色原图上能看出字形，但直接做相关匹配会被风景的低频内容淹没。

关键一步是**形态学黑帽**（MORPH_BLACKHAT）：它把"比周围更亮的细结构"抽出来，
正好是笔画，滤掉大面积的山体/天空/水面。

然后把已知的目标字（由 captcha_router 从题面 OCR 得到，实测 14/14 读对）
用系统字体渲染成模板族，在多尺度/小角度范围内做归一化互相关
（TM_CCOEFF_NORMED），取每块最高分。约 3.4 秒/张。

实测数据（合并两批真实样例：set1 6 张 + set2 8 张 = 14 张）
------------------------------------------------------------
  配置                        阈值法全对  top-k排序全对
  黑帽 K25 · 4 字体             10/14        12/14
  黑帽 K30/K35/K40 · 4 字体      9~10/14      14/14
  bh25+bh45 融合(图内归一化)      10/14        14/14
  原灰度（无黑帽，对照组）          1/14         4/14
对比：AI 全部方案逐块 53~72%（「全选」基线就是 58%）、全对约 17%。

⚠️ 必须分集合看（别只看合并数）：
  set1（图片文字点击验证例图目录，6 张）阈值 0.34 → 6/6；
  set2（其下的 测试 子目录，8 张，更难）→ 4/8。
  set1 那 6 张容易，**别拿 6/6 当方法的真实水平**。

⚠️ 2026-09-21 更新：新增第三个集合 `测试1`（11 张），**合并 25 张全量重测**后上面两个数字要修正——
  阈值 0.34 的「10/14」是**集合特定的过拟合点**：25 张扫描 0.34→16/25、**0.37~0.41→19/25（平台）**、
  0.42+→15/25。所以 `DEFAULT_THRESHOLD = 0.37` 是对的，**别为了旧集的 10/14 去赌 0.34**。
  25 张成绩：阈值 0.37 → 19/25（根目录 5/6、测试 4/8、测试1 10/11）；排序取前 k（已知块数，oracle 上界）
  23/25；2 均值 16/25；「全选 6 块」基线 0/25。**6 个错例全是「该选几块」，无一例字形认错。**
  门控门限同样要上调：阈值 0.37 下要保住 100% 精度需 `conf > 0.16`（覆盖 60%），
  旧的 0.12 在 25 张上只剩 84.2%。详细数据见 memory/2026-09-21.md 与 .workbuddy/out/sweep_all.txt。

已知短板
--------
「选哪几块」已解决（排序可做到 14/14 全对），难在「该选几块」
（答案块数 2~5 不固定，题面不给）。七种定 k 法（固定阈值 / α·max / ratio /
gap_abs / gap_rel / 2means / otsu）**最好都只有 10/14**，原因是
s2_245 的允许窗口只有 (0.344, 0.365]、s2_1346 是 (0.311, 0.341]，
两者交集为空 —— 不存在一个全局阈值能同时切对。因此本模块同时提供
`pick_by_2means`，并把"置信度"暴露出去。

✅ 推荐用法：置信度门控。阈值 0.34 时 `conf > 0.12` → 提交 6/14，精度 100%；
`conf > 0.06` → 提交 9/14，精度 88.9%。即「有把握自动提交、没把握转 AI / 人工兜底」。
⚠️ 上列门限是在 14 张旧集 + 阈值 0.34 上得到的；**25 张集上要保 100% 精度需门限 0.16**（见上）。
"""
from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---- 图块统一尺寸（必须固定：黑帽核大小是相对它调出来的）----
TILE_W, TILE_H = 300, 302
BH_KERNEL = 25          # 椭圆核直径；必须大于笔画宽度，太小会失效（实测 K=15 → 排序掉到 9/14）
# 注意两个最优 K 不是同一个：
#   K=25    → 固定阈值法最好（10/14），但排序 12/14 有两张错序
#   K=30~40 → 排序满分 14/14，但分数整体下移，固定阈值反而 9~10/14
# 若要"排序全对"（例如上层按置信度自适应取 top-k），用 ORDER_KERNEL。
ORDER_KERNEL = 35
NORM_SIGMA = 3.0

# ---- 模板参数 ----
SCALES = (0.6, 0.7, 0.8, 0.9, 1.0, 1.1)
ANGLES = (-30, -25, -20, -15, -10, -5, 0, 5, 10, 15, 20, 25, 30)
FONT_NAMES = ("simhei.ttf", "msyh.ttc", "simsun.ttc", "Deng.ttf")
# 装饰性字体会拉高干扰块分数（实测 8 字体配置干扰最高分 0.427 → 阈值法掉到 4/6），别加回来
EXPERIMENTAL_FONTS: tuple[str, ...] = ()

DEFAULT_THRESHOLD = 0.37   # 14 张合并样本的阈值扫描：0.34→10/14（**尖峰**，靠 0.337/0.339 恰好被排除、
                           # 0.343 恰好被纳入，实为过拟合点）；0.35~0.36→8/14；**0.37~0.41→9/14（平台）**；
                           # 0.42+ 迅速退化。默认取平台中点 0.37，别为了 10/14 去赌 0.34。
MIN_TEMPLATE_PX = 20

# ---- 门控：「有把握才提交，没把握就换一组」----
# conf = 选中块最低分 − 未选中块最高分；只有 conf > GATE_DEFAULT 才允许提交。
# 25 张实测（阈值 0.37）门限递进：0.12 → 覆盖 76% / 精度 84.2%；0.14 → 68% / 94.1%；
# 0.16 → 60% / **100%**；0.18 → 36% / 100%。默认取「精度 100% 里覆盖率最高」的 0.16。
# ⚠️ 这组数字是在同一批 25 张上扫出来的（属调参、不是成绩）；改门限请用 held-out 集重新标定。
GATE_DEFAULT = 0.16


def _font_dir() -> str:
    win = os.environ.get("WINDIR") or r"C:\Windows"
    return os.path.join(win, "Fonts")


def resolve_fonts() -> list[str]:
    """返回实际存在的字体文件路径（按可用性过滤，缺字体不会崩）。"""
    d = _font_dir()
    out = [os.path.join(d, n) for n in FONT_NAMES + EXPERIMENTAL_FONTS]
    return [p for p in out if os.path.isfile(p)]


# --------------------------------------------------------------------------- #
# 预处理
# --------------------------------------------------------------------------- #
def normalize_3sigma(x: np.ndarray) -> np.ndarray:
    """减均值、除 3σ、截断到 ±1 再拉伸到 0-255。"""
    x = x.astype(np.float32)
    std = float(x.std()) or 1.0
    x = np.clip((x - float(x.mean())) / (NORM_SIGMA * std), -1.0, 1.0)
    return ((x + 1.0) * 127.5).astype(np.uint8)


def prep_tile(tile_bgr: np.ndarray,
              kernel: int = BH_KERNEL) -> np.ndarray:
    """图块 → 固定尺寸灰度 → 形态学黑帽 → 归一化（float32，值域约 ±1）。"""
    t = cv2.resize(tile_bgr, (TILE_W, TILE_H), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel))
    bh = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k).astype(np.float32)
    x = bh.astype(np.float32)
    std = float(x.std()) or 1.0
    return np.clip((x - float(x.mean())) / (NORM_SIGMA * std), -1.0, 1.0)


# --------------------------------------------------------------------------- #
# 模板
# --------------------------------------------------------------------------- #
def _render_glyph(ch: str, font_path: str, px: int = 200) -> np.ndarray | None:
    try:
        font = ImageFont.truetype(font_path, px)
    except Exception:  # noqa: BLE001
        return None
    img = Image.new("L", (px * 3, px * 3), 0)
    ImageDraw.Draw(img).text((px, px), ch, fill=255, font=font)
    box = img.getbbox()
    if not box:
        return None
    return np.array(img.crop(box), dtype=np.uint8)


def build_templates(ch: str, fonts: list[str] | None = None) -> list[np.ndarray]:
    """把目标字渲染成模板族（字体 × 尺度 × 角度）。"""
    fonts = fonts if fonts is not None else resolve_fonts()
    out: list[np.ndarray] = []
    for fp in fonts:
        base = _render_glyph(ch, fp)
        if base is None:
            continue
        for s in SCALES:
            w = max(MIN_TEMPLATE_PX, int(base.shape[1] * s))
            h = max(MIN_TEMPLATE_PX, int(base.shape[0] * s))
            t = cv2.resize(base, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)
            for a in ANGLES:
                tt = t
                if a:
                    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), float(a), 1.0)
                    cs, sn = abs(m[0, 0]), abs(m[0, 1])
                    nw, nh = int(h * sn + w * cs), int(h * cs + w * sn)
                    m[0, 2] += nw / 2.0 - w / 2.0
                    m[1, 2] += nh / 2.0 - h / 2.0
                    tt = cv2.warpAffine(t, m, (nw, nh), flags=cv2.INTER_LINEAR,
                                        borderValue=0)
                if (MIN_TEMPLATE_PX <= tt.shape[0] <= TILE_H
                        and MIN_TEMPLATE_PX <= tt.shape[1] <= TILE_W):
                    out.append(tt)
    return out


class GlyphMatcher:
    """按字缓存模板族，避免每次验证码都重新渲染。

    kernel: 黑帽核直径。``BH_KERNEL``(25) 阈值法最优；``ORDER_KERNEL``(35) 排序满分。
    """

    def __init__(self, fonts: list[str] | None = None,
                 kernel: int = BH_KERNEL) -> None:
        self.fonts = fonts if fonts is not None else resolve_fonts()
        self.kernel = kernel
        self._cache: dict[str, list[np.ndarray]] = {}

    def templates(self, ch: str) -> list[np.ndarray]:
        if ch not in self._cache:
            self._cache[ch] = build_templates(ch, self.fonts)
        return self._cache[ch]

    def score_tile(self, tile_prepped: np.ndarray, ch: str) -> float:
        best = -1.0
        th, tw = tile_prepped.shape[:2]
        for tpl in self.templates(ch):
            if tpl.shape[0] > th or tpl.shape[1] > tw:
                continue
            v = float(cv2.matchTemplate(tile_prepped, tpl, cv2.TM_CCOEFF_NORMED).max())
            if v > best:
                best = v
        return best

    def score_tiles(self, tiles_bgr: list[np.ndarray], ch: str) -> list[float]:
        return [self.score_tile(prep_tile(t, self.kernel), ch) for t in tiles_bgr]


# --------------------------------------------------------------------------- #
# 从分数决定"选哪几块"
# --------------------------------------------------------------------------- #
def pick_by_threshold(scores: list[float], threshold: float = DEFAULT_THRESHOLD) -> list[int]:
    return sorted(i for i, v in enumerate(scores, 1) if v >= threshold)


def pick_by_2means(scores: list[float]) -> list[int]:
    """一维 2-均值：把分数分成高低两组，取高组。无需调阈值。"""
    a = np.asarray(scores, dtype=np.float64)
    if a.size < 2:
        return []
    order = np.argsort(a)
    best_cut, best_sse = 1, None
    for cut in range(1, a.size):
        lo, hi = a[order[:cut]], a[order[cut:]]
        sse = float(((lo - lo.mean()) ** 2).sum() + ((hi - hi.mean()) ** 2).sum())
        if best_sse is None or sse < best_sse:
            best_sse, best_cut = sse, cut
    return sorted(int(order[i]) + 1 for i in range(best_cut, a.size))


def confidence(scores: list[float], picked: list[int]) -> float:
    """选中块的最低分 − 未选中块的最高分；越大越有把握（<=0 表示分不开）。"""
    sel = [scores[i - 1] for i in picked]
    rej = [v for i, v in enumerate(scores, 1) if i not in picked]
    if not sel:
        return 0.0
    if not rej:
        return 1.0
    return float(min(sel) - max(rej))


def solve(tiles_bgr: list[np.ndarray], ch: str,
          matcher: GlyphMatcher | None = None,
          threshold: float = DEFAULT_THRESHOLD) -> dict:
    """返回 {picked, scores, confidence, mode}。

    mode: "threshold" 正常；"2means" 阈值法切出空/全选时退化为 2-均值；
          出现 "2means" 或 confidence <= 0 时，上层应视为低置信（建议转人工/大模型）。
    """
    matcher = matcher or GlyphMatcher()
    scores = matcher.score_tiles(tiles_bgr, ch)
    picked = pick_by_threshold(scores, threshold)
    mode = "threshold"
    if not picked or len(picked) == len(tiles_bgr):
        picked = pick_by_2means(scores)
        mode = "2means"
    return {"picked": picked, "scores": scores, "mode": mode,
            "confidence": confidence(scores, picked)}


def decide(scores: list[float], threshold: float = DEFAULT_THRESHOLD,
           gate: float = GATE_DEFAULT) -> dict:
    """「有较大把握就提交、没把握就换一组」的判定（纯函数、无副作用，便于离线测）。

    action="submit"   conf > gate → 上层可以放心点击提交
    action="refresh"  conf <= gate / 选不出块 / 全选 → 上层应换一组重新出题，别硬提交

    ⚠️ confidence() 在「全部图块都被选中」时返回 1.0（没有未选中项可比），
    所以必须先单独处理「空选 / 全选」，否则会把「没把握」误判成「很有把握」。
    """
    n = len(scores)
    picked = pick_by_threshold(scores, threshold)
    mode = "threshold"
    if not picked or len(picked) == n:
        picked = pick_by_2means(scores)
        mode = "2means"
    conf = confidence(scores, picked)
    if not picked:
        return {"action": "refresh", "picked": [], "scores": scores, "conf": conf,
                "mode": mode, "reason": "没有任何图块达到阈值，定位不到目标"}
    if len(picked) == n:
        return {"action": "refresh", "picked": picked, "scores": scores, "conf": conf,
                "mode": mode, "reason": f"{n} 个图块全被选中，分不出档"}
    if conf <= gate:
        return {"action": "refresh", "picked": picked, "scores": scores, "conf": conf,
                "mode": mode, "reason": f"置信度 {conf:+.3f} 未超过门限 {gate:.2f}"}
    return {"action": "submit", "picked": picked, "scores": scores, "conf": conf,
            "mode": mode, "reason": f"置信度 {conf:+.3f} > 门限 {gate:.2f}"}


# --------------------------------------------------------------------------- #
# 自测
# --------------------------------------------------------------------------- #
def _self_test() -> None:
    import re
    import sys
    import time

    root = os.path.dirname(os.path.abspath(__file__))
    proj = os.path.dirname(root) if os.path.basename(root) == ".workbuddy" else root
    folder = os.path.join(proj, "图片文字点击验证例图")
    if not os.path.isdir(folder):
        print("找不到测试集目录:", folder)
        return
    sys.path.insert(0, proj)
    import ai_visual_captcha as avc  # noqa: E402
    import utils  # noqa: E402

    engine = utils._get_ocr_engine()
    matcher = GlyphMatcher()
    print(f"字体: {[os.path.basename(f) for f in matcher.fonts]}")

    ok_t = ok_2m = ok_topk = 0
    names = sorted(f for f in os.listdir(folder) if f.lower().endswith(".png"))
    for name in names:
        bgr = np.array(Image.open(os.path.join(folder, name)).convert("RGB"))[:, :, ::-1].copy()
        answer = sorted({int(c) for c in os.path.splitext(name)[0] if c.isdigit()})
        res, _ = engine(bgr)
        m = re.search(r"包含文字[\uff1a:\s]*[\u201c\u201d\"']?\s*([\u4e00-\u9fff])",
                      "".join(str(i[1]) for i in (res or [])))
        ch = m.group(1) if m else ""
        tiles = [bgr[y:y + th, x:x + tw].copy()
                 for (x, y, tw, th) in avc.detect_image_tiles(bgr)]
        t0 = time.time()
        r = solve(tiles, ch, matcher)
        el = time.time() - t0
        by2 = pick_by_2means(r["scores"])
        topk = sorted(sorted(range(1, 7),
                             key=lambda i: -r["scores"][i - 1])[:len(answer)])
        ok_t += r["picked"] == answer
        ok_2m += by2 == answer
        ok_topk += topk == answer
        print(f"  {name:11s} 字={ch!r} 答案={answer} "
              f"阈值法={r['picked']}{'✅' if r['picked'] == answer else '❌'} "
              f"2均值={by2}{'✅' if by2 == answer else '❌'} "
              f"conf={r['confidence']:+.3f} {el:.1f}s")
    n = len(names)
    print(f"合计: 阈值法 {ok_t}/{n}   2均值 {ok_2m}/{n}   "
          f"top-k(已知块数,上界参考) {ok_topk}/{n}")


if __name__ == "__main__":
    _self_test()
