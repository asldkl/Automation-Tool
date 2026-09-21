# -*- coding: utf-8 -*-
"""把测试2 的 100 张样本改名成统一的 001.png … 100.png，方便人工核对。

顺序 = 现有文件名排序（= 时间戳顺序 = 采集顺序），序号与判定图/核对表一致。
安全措施：
  · 先写「原文件名 ↔ 新文件名」对照表（可随时还原，`--undo` 用不了就照它手动改回）
  · 目标文件已存在则整体中止（不覆盖任何东西）
  · 只处理本批 100 张；`preview_*` 与 09-21 的旧样本原样不动
顺带把 test2_result.json 里的 file 字段同步成新名，这样判定图与核对表都能直接用新序号。
"""
import csv
import json
import os
import sys

ROOT_ANCHOR = "captcha_glyph_match.py"


def _find_root(start):
    """向上找 captcha_glyph_match.py 所在目录当仓库根（脚本放哪层都不会算错）"""
    p = start
    for _ in range(6):
        if os.path.exists(os.path.join(p, ROOT_ANCHOR)):
            return p
        p = os.path.dirname(p)
    return start


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".workbuddy", "out")
FOLDER = os.path.join(ROOT, "图片文字点击验证例图", "测试2")
MAP_CSV = os.path.join(OUT, "test2_重命名对照表.csv")
RESULT_JSON = os.path.join(OUT, "test2_result.json")
P = lambda *a: print(*a, flush=True)


def pick_current():
    """本批 100 张（排除 preview_* 与非 09-22 的旧样本）。
    ⚠️ 改名前后两种命名都要认：`001.png` 与 `sample_001_20260922-000507.png`。"""
    keep, skip = [], []
    for f in sorted(os.listdir(FOLDER)):
        if not f.lower().endswith(".png"):
            continue
        if f.startswith("preview_"):
            skip.append((f, "UI 预览图"))
        elif len(f) == 7 and f[:3].isdigit():
            keep.append(f)                      # 已改名
        elif "20260922-" in f:
            keep.append(f)                      # 原名
        else:
            skip.append((f, "非本批（时间戳不是 09-22）"))
    return keep, skip


def sync_json_from_map_csv():
    """用对照表把 result.json 里的 file 字段换成新名（幂等，可重复跑）"""
    if not (os.path.exists(MAP_CSV) and os.path.exists(RESULT_JSON)):
        P("没有对照表或 result.json，跳过同步")
        return
    with open(MAP_CSV, encoding="utf-8-sig", newline="") as f:
        lut = {r["原文件名"]: r["新文件名"] for r in csv.DictReader(f)}
    news = set(lut.values())
    with open(RESULT_JSON, encoding="utf-8") as f:
        doc = json.load(f)
    changed = miss = 0
    for r in doc["records"]:
        if r["file"] in lut:
            r["file"] = lut[r["file"]]
            changed += 1
        elif r["file"] not in news:
            miss += 1
    with open(RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    P("已用对照表同步 result.json：%d 条改成新名，%d 条对不上" % (changed, miss))


def main():
    files, skip = pick_current()
    P("目录：%s" % FOLDER)
    P("待改名：%d 张；跳过 %d 个：%s" % (len(files), len(skip), [s[0] for s in skip]))
    assert len(files) == 100, "本批应为 100 张，实际 %d 张 —— 请先确认目录内容" % len(files)

    # 已改名过？（存在 001.png 这种）
    already = [f for f in files if len(f) == 7 and f[:3].isdigit()]
    if len(already) == len(files):
        P("检测到已经是统一命名（%s … %s），无需再改，只做 JSON 同步" % (files[0], files[-1]))
        sync_json_from_map_csv()
        sys.exit(0)

    mapping = []

    # ① 先查冲突
    for i, old in enumerate(files, 1):
        new = "%03d.png" % i
        if os.path.exists(os.path.join(FOLDER, new)) and new != old:
            P("❌ 目标已存在，中止：%s" % new)
            sys.exit(1)
        mapping.append((old, new))

    # ② 落对照表（改名前写，保证可还原）
    with open(MAP_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["序号", "新文件名", "原文件名"])
        for i, (old, new) in enumerate(mapping, 1):
            w.writerow([i, new, old])
    P("对照表已写出：%s" % os.path.relpath(MAP_CSV, ROOT))

    # ③ 用中间名两步改名（避免与尚未改名的旧名相撞）
    for old, new in mapping:
        os.rename(os.path.join(FOLDER, old), os.path.join(FOLDER, "__tmp__" + new))
    for _old, new in mapping:
        os.rename(os.path.join(FOLDER, "__tmp__" + new), os.path.join(FOLDER, new))
    P("改名完成：%s … %s" % (mapping[0][1], mapping[-1][1]))
    P("  例：%s → %s" % (mapping[0][0], mapping[0][1]))
    P("  例：%s → %s" % (mapping[-1][0], mapping[-1][1]))

    # ④ 同步 result.json 里的文件名
    sync_json_from_map_csv()

    cur = sorted(f for f in os.listdir(FOLDER) if f.lower().endswith(".png"))
    P("目录现状：%d 个 png —— %s" % (len(cur), cur[:3] + ["…"] + cur[-3:]))


if __name__ == "__main__":
    main()
