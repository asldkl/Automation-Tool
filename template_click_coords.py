# -*- coding: utf-8 -*-
"""
模板最近成功点击坐标记录（用于日志遮罩避让）

账号运行成功识别并点击某模板时，记录该模板（按图片文件名）最近一次成功点击的全屏坐标；
模板设置窗口显示该坐标；运行时若日志遮罩覆盖即将点击的坐标，则临时移开遮罩、点完复原。

存储：独立文件 %APPDATA%\\DeltaAutoTool\\template_click_coords.json
    {"图片文件名": [x, y], ...}
"""
import os
import json
import threading

import config

COORDS_JSON = os.path.join(config.APP_DATA_DIR, "template_click_coords.json")
_lock = threading.Lock()
_cache = None


def _read_file():
    try:
        with open(COORDS_JSON, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return None
    except Exception:
        return {}


def _write_file(data):
    try:
        config.ensure_app_data_dir()
        tmp = COORDS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, COORDS_JSON)
        return True
    except Exception as e:
        print(f"⚠️ 点击坐标保存失败：{e}")
        return False


def _key(path):
    """统一 key：图片文件名（去目录）"""
    try:
        return os.path.basename(str(path))
    except Exception:
        return str(path)


def _load():
    global _cache
    with _lock:
        if _cache is None:
            d = _read_file()
            _cache = d if isinstance(d, dict) else {}
        return dict(_cache)


def get_coord(path):
    """返回该模板最近成功点击坐标 (x, y) 或 None"""
    c = _load().get(_key(path))
    if isinstance(c, (list, tuple)) and len(c) == 2:
        try:
            return int(c[0]), int(c[1])
        except Exception:
            return None
    return None


def set_coord(path, x, y):
    """记录该模板最近成功点击坐标"""
    global _cache
    with _lock:
        if _cache is None:
            d = _read_file()
            _cache = d if isinstance(d, dict) else {}
        _cache[_key(path)] = [int(x), int(y)]
        _write_file(_cache)
