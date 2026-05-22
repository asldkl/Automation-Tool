"""
冷却管理模块
管理每个账号的运行冷却时间，防止频繁执行
"""
import os
import json
import datetime

COOLDOWN_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_cooldown.json")


def _load_data():
    """加载冷却数据"""
    if not os.path.exists(COOLDOWN_JSON_PATH):
        return {}
    try:
        with open(COOLDOWN_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_data(data):
    """保存冷却数据（原子写入，防止崩溃导致数据损坏）"""
    tmp_path = COOLDOWN_JSON_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, COOLDOWN_JSON_PATH)
    except Exception as e:
        print(f"⚠️ 保存冷却数据失败：{e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def is_cooling_down(account_name):
    """
    检查账号是否在冷却中
    返回: (is_cooling: bool, next_run_time_str: str or None)
    """
    data = _load_data()
    if account_name not in data:
        return False, None

    entry = data[account_name]
    next_run_str = entry.get("next_run_time")
    if not next_run_str:
        return False, None

    try:
        next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now()
        if now < next_run:
            return True, next_run_str
        return False, next_run_str
    except Exception:
        return False, None


def record_run(account_name, cooldown_hours=8):
    """
    记录账号运行完成，计算下次运行时间
    cooldown_hours: 冷却小时数
    """
    data = _load_data()
    now = datetime.datetime.now()
    next_run = now + datetime.timedelta(hours=cooldown_hours)

    data[account_name] = {
        "last_run_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "next_run_time": next_run.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_data(data)


def reset_cooldown(account_name):
    """重置指定账号的冷却"""
    data = _load_data()
    if account_name in data:
        del data[account_name]
        _save_data(data)


def reset_all_cooldowns():
    """重置所有账号的冷却"""
    _save_data({})


def get_all_cooldowns():
    """
    获取所有账号的冷却信息
    返回: dict, key=account_name, value={last_run_time, next_run_time, remaining_seconds}
    """
    data = _load_data()
    now = datetime.datetime.now()
    result = {}
    for name, entry in data.items():
        next_run_str = entry.get("next_run_time", "")
        remaining = 0
        if next_run_str:
            try:
                next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
                diff = (next_run - now).total_seconds()
                remaining = max(0, int(diff))
            except Exception:
                pass
        result[name] = {
            "last_run_time": entry.get("last_run_time", ""),
            "next_run_time": next_run_str,
            "remaining_seconds": remaining,
        }
    return result
