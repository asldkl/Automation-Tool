"""
Scheduler / cooldown watcher functions extracted from gui_app.py.

Each function accepts ``app`` as its first parameter (the App instance).
All former ``self.xxx`` references are replaced with ``app.xxx``.
"""

import os
import datetime

import utils
import cooldown_manager
import cooldown_watcher


def set_next_wake_timer(app):
    """计算下一个冷却到期时间，提前5分钟设置唤醒定时器"""
    try:
        # 取消旧定时器
        if app._wake_timer_handle:
            utils.cancel_wake_timer(app._wake_timer_handle)
            app._wake_timer_handle = None

        now = datetime.datetime.now()
        next_run = None

        # 冷却完立即运行模式：取最早冷却到期时间
        if app.settings.get("cooldown_run_immediately", False):
            cd_data = cooldown_manager._load_data()
            earliest = cooldown_manager.find_earliest_cooldown(cd_data)
            if earliest and earliest > now:
                next_run = earliest

        if next_run:
            wake_time = next_run - datetime.timedelta(minutes=5)
            min_gap = datetime.timedelta(seconds=60)
            if wake_time > now + min_gap:
                if app._last_wake_time == wake_time:
                    return
                handle = utils.set_wake_timer(wake_time)
                if handle:
                    app._wake_timer_handle = handle
                    app._last_wake_time = wake_time
                    print(f"🔔 已设置唤醒定时器：{wake_time.strftime('%H:%M')}")
    except Exception as e:
        print(f"⚠️ 设置唤醒定时器失败: {e}")


def update_cooldown_wake_timer(app):
    """冷却监听专用：根据最早冷却到期时间更新唤醒定时器"""
    if not app.settings.get("cooldown_run_immediately", False):
        return
    try:
        now = datetime.datetime.now()
        cd_data = cooldown_manager._load_data()
        earliest_next = cooldown_manager.find_earliest_cooldown(cd_data)
        if earliest_next and earliest_next > now:
            wake_time = earliest_next - datetime.timedelta(minutes=5)
            min_gap = datetime.timedelta(seconds=60)
            if wake_time > now + min_gap:
                if app._last_wake_time == wake_time:
                    return
                if app._wake_timer_handle:
                    utils.cancel_wake_timer(app._wake_timer_handle)
                    app._wake_timer_handle = None
                handle = utils.set_wake_timer(wake_time)
                if handle:
                    app._wake_timer_handle = handle
                    app._last_wake_time = wake_time
                    print(f"🔔 已设置冷却唤醒定时器：{wake_time.strftime('%H:%M')}")
    except Exception as e:
        print(f"⚠️ 更新冷却唤醒定时器失败: {e}")


def apply_auto_settings(app):
    """从设置窗口保存后应用自动任务设置（冷却执行模式）"""
    # 冷却完立即运行监听
    if app.settings.get("cooldown_run_immediately", False):
        cooldown_watcher.start_cooldown_watcher(app)
    else:
        cooldown_watcher.stop_cooldown_watcher(app)
