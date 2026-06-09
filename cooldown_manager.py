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
    检查账号是否在冷却中（暂停状态也算冷却中）
    返回: (is_cooling: bool, next_run_time_str: str or None)
    """
    data = _load_data()
    if account_name not in data:
        return False, None

    entry = data[account_name]
    # 暂停状态视为冷却中
    if entry.get("paused"):
        return True, entry.get("next_run_time")

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
    返回: dict, key=account_name, value={last_run_time, next_run_time, remaining_seconds, paused}
    """
    data = _load_data()
    now = datetime.datetime.now()
    result = {}
    for name, entry in data.items():
        next_run_str = entry.get("next_run_time", "")
        paused = entry.get("paused", False)
        remaining = 0
        if paused:
            remaining = entry.get("paused_remaining", 0)
        elif next_run_str:
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
            "paused": paused,
            "account_paused": entry.get("account_paused", False),
        }
    return result


def set_custom_cooldown(account_name, next_run_time_str):
    """
    为指定账号设置自定义冷却结束时间
    next_run_time_str: "YYYY-MM-DD HH:MM:SS" 或 "HH:MM" 格式
    """
    data = _load_data()
    now = datetime.datetime.now()

    # 支持 "HH:MM" 格式（当天或明天的该时间）
    try:
        if ":" in next_run_time_str and len(next_run_time_str) <= 5:
            h, m = map(int, next_run_time_str.split(":"))
            next_run = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if next_run <= now:
                next_run += datetime.timedelta(days=1)
        else:
            next_run = datetime.datetime.strptime(next_run_time_str, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False

    if account_name not in data:
        data[account_name] = {}

    data[account_name]["last_run_time"] = data[account_name].get("last_run_time", now.strftime("%Y-%m-%d %H:%M:%S"))
    data[account_name]["next_run_time"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
    _save_data(data)
    return True


def pause_cooldown(account_name):
    """暂停指定账号的冷却倒计时，保存剩余秒数"""
    data = _load_data()
    if account_name not in data:
        return False
    entry = data[account_name]
    if entry.get("paused"):
        return False  # 已经暂停
    next_run_str = entry.get("next_run_time", "")
    if not next_run_str:
        return False
    try:
        next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now()
        remaining = max(0, int((next_run - now).total_seconds()))
        if remaining <= 0:
            return False  # 已过期，无需暂停
        entry["paused"] = True
        entry["paused_remaining"] = remaining
        _save_data(data)
        return True
    except Exception:
        return False


def resume_cooldown(account_name):
    """恢复指定账号的冷却倒计时，从暂停时的剩余时间重新计算"""
    data = _load_data()
    if account_name not in data:
        return False
    entry = data[account_name]
    if not entry.get("paused"):
        return False  # 未暂停
    remaining = entry.get("paused_remaining", 0)
    if remaining <= 0:
        entry.pop("paused", None)
        entry.pop("paused_remaining", None)
        _save_data(data)
        return True
    now = datetime.datetime.now()
    next_run = now + datetime.timedelta(seconds=remaining)
    entry["next_run_time"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
    entry.pop("paused", None)
    entry.pop("paused_remaining", None)
    _save_data(data)
    return True


def is_paused(account_name):
    """检查账号的冷却是否处于暂停状态"""
    data = _load_data()
    if account_name not in data:
        return False
    return bool(data[account_name].get("paused"))


def set_account_paused(account_name, paused):
    """设置账号暂停状态（独立于冷却，暂停后运行时跳过该账号）"""
    data = _load_data()
    if account_name not in data:
        data[account_name] = {}
    data[account_name]["account_paused"] = paused
    _save_data(data)
    return True


def is_account_paused(account_name):
    """检查账号是否被暂停（暂停后运行时跳过该账号）"""
    data = _load_data()
    if account_name not in data:
        return False
    return bool(data[account_name].get("account_paused"))


def remove_expired_cooldowns():
    """
    移除所有已过期的冷却记录
    返回: 被移除的账号名称列表
    """
    data = _load_data()
    now = datetime.datetime.now()
    expired = []
    for name, entry in list(data.items()):
        next_run_str = entry.get("next_run_time", "")
        if not next_run_str:
            expired.append(name)
            continue
        try:
            next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
            if now >= next_run:
                expired.append(name)
        except Exception:
            expired.append(name)
    for name in expired:
        del data[name]
    if expired:
        _save_data(data)
    return expired
