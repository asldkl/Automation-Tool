"""
冷却管理模块
管理每个账号的运行冷却时间，防止频繁执行
"""
import os
import json
import datetime
import threading
import config
import utils

COOLDOWN_JSON_PATH = os.path.join(config.APP_DATA_DIR, "cooldown.json")
COOLDOWN_JSON_BACKUP = COOLDOWN_JSON_PATH + ".bak"


def normalize_key(img_path):
    """统一 key 提取：去掉 account: 前缀和 .png 后缀
    所有模块应使用此函数获取冷却 key。
    """
    basename = os.path.basename(img_path)
    # 去掉 account: 前缀
    if ":" in basename:
        basename = basename.split(":", 1)[1]
    # 去掉扩展名
    basename = os.path.splitext(basename)[0]
    return basename


# 内存缓存：避免每次读操作都访问磁盘
_cache = None
_cache_mtime = 0.0
_lock = threading.Lock()


def _restore_from_backup():
    """从备份文件恢复冷却数据，成功返回数据，失败返回空 dict"""
    import shutil
    if not os.path.exists(COOLDOWN_JSON_BACKUP):
        return {}
    try:
        with open(COOLDOWN_JSON_BACKUP, "r", encoding="utf-8") as f:
            backup_data = json.load(f)
        if backup_data:
            # 恢复主文件
            try:
                shutil.copy2(COOLDOWN_JSON_BACKUP, COOLDOWN_JSON_PATH)
            except Exception:
                pass
            print("🔄 冷却数据已从备份恢复")
            return backup_data
    except Exception:
        pass
    return {}


def _load_data():
    """加载冷却数据（带内存缓存，仅在文件修改时间变化时重新读取）
    主文件不存在、损坏或为空时自动从备份恢复"""
    global _cache, _cache_mtime
    try:
        mtime = os.path.getmtime(COOLDOWN_JSON_PATH)
    except OSError:
        # 主文件不存在，尝试从备份恢复
        _cache = _restore_from_backup()
        _cache_mtime = 0.0
        return _cache
    if _cache is not None and mtime == _cache_mtime:
        return _cache
    try:
        with open(COOLDOWN_JSON_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        # 主文件为空（如崩溃后变成 {}）但备份有数据 → 从备份恢复
        if not _cache and os.path.exists(COOLDOWN_JSON_BACKUP):
            backup_data = _restore_from_backup()
            if backup_data:
                _cache = backup_data
        _cache_mtime = mtime
    except Exception:
        # 读取失败（文件损坏），尝试从备份恢复
        _cache = _restore_from_backup()
        _cache_mtime = 0.0
    return _cache


def _save_data(data):
    """保存冷却数据（原子写入 + 备份保护，防止崩溃导致数据损坏/丢失）"""
    global _cache, _cache_mtime
    tmp_path = COOLDOWN_JSON_PATH + ".tmp"
    try:
        # 保存前先备份旧文件（崩溃/蓝屏后可恢复）
        if os.path.exists(COOLDOWN_JSON_PATH):
            try:
                import shutil
                shutil.copy2(COOLDOWN_JSON_PATH, COOLDOWN_JSON_BACKUP)
            except Exception:
                pass
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, COOLDOWN_JSON_PATH)
        _cache = data
        _cache_mtime = os.path.getmtime(COOLDOWN_JSON_PATH)
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
    with _lock:
        data = _load_data()
        if account_name not in data:
            return False, None

        entry = data[account_name]
        # 暂停状态（冷却暂停 或 账号暂停）均视为冷却中
        if entry.get("paused") or entry.get("account_paused"):
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
    with _lock:
        data = _load_data()
        now = datetime.datetime.now()
        next_run = now + datetime.timedelta(hours=cooldown_hours)

        if account_name in data:
            data[account_name]["last_run_time"] = now.strftime("%Y-%m-%d %H:%M:%S")
            data[account_name]["next_run_time"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
        else:
            data[account_name] = {
                "last_run_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "next_run_time": next_run.strftime("%Y-%m-%d %H:%M:%S"),
            }
        _save_data(data)

    # 新增：创建定时任务兜底（在锁外调用，避免死锁）
    # 不重复创建：只有最早冷却时间变化时才更新
    try:
        settings = config.load_settings()
        if settings.get("cooldown_scheduled_task_enabled", True):
            earliest = find_earliest_cooldown(data)
            if earliest:
                earliest_key = earliest.strftime("%Y-%m-%d %H:%M")
                if getattr(record_run, '_last_task_time', None) != earliest_key:
                    record_run._last_task_time = earliest_key
                    earliest_with_buffer = earliest + datetime.timedelta(minutes=2)
                    utils.create_cooldown_scheduled_task(earliest_with_buffer)
    except Exception as e:
        print(f"⚠️ 创建冷却定时任务失败: {e}")


def find_earliest_cooldown(data):
    """找到所有账号中最早的冷却到期时间，返回 datetime 对象或 None"""
    earliest = None
    for name, entry in data.items():
        if entry.get("paused") or entry.get("account_paused"):
            continue
        # 用短名称再检查一次暂停状态（防止多 key 导致漏检）
        short_name = name.split(":")[-1] if ":" in name else name
        if short_name != name:
            short_entry = data.get(short_name, {})
            if short_entry.get("paused") or short_entry.get("account_paused"):
                continue
        next_run_str = entry.get("next_run_time", "")
        if not next_run_str:
            continue
        try:
            next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
            if earliest is None or next_run < earliest:
                earliest = next_run
        except Exception:
            pass
    return earliest


def reset_cooldown(account_name):
    """重置指定账号的冷却"""
    with _lock:
        data = _load_data()
        if account_name in data:
            del data[account_name]
            _save_data(data)


def reset_all_cooldowns():
    """重置所有账号的冷却（保留暂停状态和游戏失败状态的账号）"""
    with _lock:
        data = _load_data()
        # 保留暂停状态和游戏失败状态的账号
        preserved = {k: v for k, v in data.items() if v.get("account_paused") or v.get("game_failed")}
        _save_data(preserved)


def get_all_cooldowns():
    """
    获取所有账号的冷却信息
    返回: dict, key=account_name, value={last_run_time, next_run_time, remaining_seconds, paused}
    """
    with _lock:
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
    with _lock:
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


def is_paused(account_name):
    """检查账号的冷却是否处于暂停状态"""
    with _lock:
        data = _load_data()
        if account_name not in data:
            return False
        return bool(data[account_name].get("paused"))


def set_account_paused(account_name, paused):
    """设置账号暂停状态（独立于冷却，暂停后运行时跳过该账号）"""
    with _lock:
        data = _load_data()
        if account_name not in data:
            data[account_name] = {}
        data[account_name]["account_paused"] = paused
        _save_data(data)
        return True


def is_account_paused(account_name):
    """检查账号是否被暂停（暂停后运行时跳过该账号）"""
    with _lock:
        data = _load_data()
        if account_name not in data:
            return False
        return bool(data[account_name].get("account_paused"))


def extend_all_cooldowns(hours=1):
    """给所有冷却中的账号延长冷却时间，不影响暂停账号
    只延长 next_run_time 还在未来（冷却中）的账号
    返回被延长的账号名称列表
    """
    with _lock:
        data = _load_data()
        now = datetime.datetime.now()
        extended = []
        for name, entry in data.items():
            # 跳过暂停账号
            if entry.get("account_paused"):
                continue
            next_run_str = entry.get("next_run_time", "")
            if not next_run_str:
                continue
            try:
                next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
                if next_run > now:  # 仅冷却中的账号
                    entry["next_run_time"] = (next_run + datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                    extended.append(name)
            except Exception:
                continue
        if extended:
            _save_data(data)
        return extended


def mark_game_failed(account_name):
    """标记账号为游戏失败状态（黄色标签）"""
    with _lock:
        data = _load_data()
        if account_name not in data:
            data[account_name] = {}
        data[account_name]["game_failed"] = True
        _save_data(data)


def remove_expired_cooldowns():
    """
    移除所有已过期的冷却记录
    保留 account_paused 状态的记录（仅清除冷却字段，不清除暂停标记）
    返回: 被移除的账号名称列表
    """
    with _lock:
        data = _load_data()
        now = datetime.datetime.now()
        removed = []
        for name, entry in list(data.items()):
            # 账号暂停状态的记录不删除，仅清除冷却相关字段
            if entry.get("account_paused"):
                if "next_run_time" in entry or "last_run_time" in entry:
                    entry.pop("next_run_time", None)
                    entry.pop("last_run_time", None)
                    entry.pop("paused", None)
                    entry.pop("paused_remaining", None)
                    entry.pop("paused_at", None)
                continue
            next_run_str = entry.get("next_run_time", "")
            if not next_run_str:
                removed.append(name)
                continue
            try:
                next_run = datetime.datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S")
                if now >= next_run:
                    removed.append(name)
            except Exception:
                removed.append(name)
        for name in removed:
            del data[name]
        if removed:
            _save_data(data)
        return removed
