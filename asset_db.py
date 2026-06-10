"""
资产数据 SQLite 持久化模块
记录每次资产识别的时间戳和数值，用于资产变化统计
"""
import os
import sqlite3
import datetime

from utils import parse_asset_value, format_asset_num

DB_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_assets.db")

# 单例连接：避免每次操作都重新建表和创建连接
_conn = None


def _get_conn():
    global _conn
    if _conn is not None:
        try:
            _conn.execute("SELECT 1")
            return _conn
        except Exception:
            _conn = None
    _conn = sqlite3.connect(DB_PATH)
    _conn.execute("""CREATE TABLE IF NOT EXISTS asset_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        value TEXT NOT NULL,
        value_num REAL NOT NULL
    )""")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_account_ts ON asset_records(account, timestamp)")
    _conn.commit()
    return _conn


def record_asset(account, value_str):
    """记录资产快照，自动解析 '1.2M' -> 1200000"""
    num = parse_asset_value(value_str)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    conn.execute(
        "INSERT INTO asset_records (account, timestamp, value, value_num) VALUES (?, ?, ?, ?)",
        (account, ts, value_str, num),
    )
    conn.commit()


def query_total_change(days):
    """查询最近 N 天所有账号的资产变化总和。
    返回 (total_change_num, detail_list)
    detail_list: [(account, first_val, last_val, diff), ...]
    """
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _get_conn()
    cursor = conn.execute(
        """
        SELECT account,
               (SELECT value_num FROM asset_records a2
                WHERE a2.account = a1.account AND a2.timestamp >= ?
                ORDER BY a2.timestamp ASC LIMIT 1) as first_val,
               (SELECT value_num FROM asset_records a3
                WHERE a3.account = a1.account AND a3.timestamp >= ?
                ORDER BY a3.timestamp DESC LIMIT 1) as last_val
        FROM (SELECT DISTINCT account FROM asset_records WHERE timestamp >= ?) a1
        """,
        (cutoff, cutoff, cutoff),
    )
    results = []
    total_diff = 0.0
    for row in cursor:
        account, first_val, last_val = row
        if first_val is not None and last_val is not None:
            diff = last_val - first_val
            total_diff += diff
            results.append((account, first_val, last_val, diff))
    return total_diff, results


def delete_account_records(account):
    """删除指定账号的所有资产记录"""
    conn = _get_conn()
    conn.execute("DELETE FROM asset_records WHERE account = ?", (account,))
    conn.commit()
