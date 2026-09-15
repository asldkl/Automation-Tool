# -*- coding: utf-8 -*-
"""
未售次数累加（定时售卖跳过时的计数记录）

不在「售卖时间区间」时跳过一键出售 → 该账号本次未卖的“轮次”累加；
进入售卖时段、正常售卖完后清零。

注意：本模块现在【仅作记录】，不再驱动任何补卖行为。
历史上的「跳过 N 次 → 下次每件物品数量×(1+轮次) 补卖」语义已随
「出售数量」设置一起废弃 —— 上架时会点一下「最大数量」按钮一次挂满，
本来也无需按轮次补卖。get_pending() 因此只保留给测试与排查使用。

存储：独立文件 %APPDATA%\\DeltaAutoTool\\sell_pending.json（避免被 settings 快照覆盖）
    {"账号key": 轮次整数, ...}
"""
import os
import json
import threading

import config

PENDING_JSON = os.path.join(config.APP_DATA_DIR, "sell_pending.json")
_lock = threading.Lock()
_cache = None


def _read_file():
    try:
        with open(PENDING_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return None
    except Exception:
        return {}


def _write_file(data):
    try:
        config.ensure_app_data_dir()
        tmp = PENDING_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PENDING_JSON)
        return True
    except Exception as e:
        print(f"⚠️ 未售次数保存失败：{e}")
        return False


def _load():
    global _cache
    with _lock:
        if _cache is None:
            d = _read_file()
            _cache = d if isinstance(d, dict) else {}
        return dict(_cache)


def get_pending(account_key):
    """该账号已累加未卖的轮次"""
    try:
        return int(_load().get(account_key, 0) or 0)
    except Exception:
        return 0


def add_pending(account_key, rounds=1):
    """累加未卖轮次"""
    global _cache
    if not account_key:
        return 0
    with _lock:
        if _cache is None:
            d = _read_file()
            _cache = d if isinstance(d, dict) else {}
        try:
            cur = int(_cache.get(account_key, 0) or 0)
        except Exception:
            cur = 0
        cur += max(0, int(rounds or 0))
        _cache[account_key] = cur
        _write_file(_cache)
        return cur


def clear_pending(account_key):
    """清零该账号未卖轮次（补卖后调用）"""
    global _cache
    if not account_key:
        return
    with _lock:
        if _cache is None:
            d = _read_file()
            _cache = d if isinstance(d, dict) else {}
        if account_key in _cache:
            _cache.pop(account_key, None)
            _write_file(_cache)
