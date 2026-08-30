"""
服务器验证与心跳模块
处理启动时的服务器许可证验证和运行时的心跳同步
"""
import os
import time
import datetime
import threading
import urllib.request
import json

from config_utils import machine_fingerprint

def validate_with_server(app):
    """
    启动时向服务器验证机器指纹和有效期
    返回 (allowed: bool, expiry: str, error: str)
    """
    server_url = app.settings.get("server_url", "").strip()
    client_key = app.settings.get("client_key", "").strip()
    if not server_url or not client_key:
        return None, None, "服务器配置为空，跳过远程验证"

    try:
        machine_id = machine_fingerprint.get_machine_id()

        url = f"{server_url}/api/v1/validate"
        payload = json.dumps({
            "machine_id": machine_id,
            "current_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Authorization", client_key)
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        if result.get("status") == "granted":
            return True, result.get("expiry", ""), ""
        else:
            reason = result.get("reason", "未知原因")
            return False, None, reason
    except Exception as e:
        return None, None, f"服务器连接失败: {e}"


def start_heartbeat(app):
    """启动心跳线程，实时同步账号状态到服务器"""
    if hasattr(app, '_heartbeat_thread') and app._heartbeat_thread and app._heartbeat_thread.is_alive():
        return
    app._heartbeat_stop = threading.Event()
    app._account_status = {}  # {filename: "running|cooling|success|failed|idle"}
    app._heartbeat_thread = threading.Thread(target=heartbeat_loop, args=(app,), daemon=True)
    app._heartbeat_thread.start()


def stop_heartbeat(app):
    """停止心跳线程"""
    if hasattr(app, '_heartbeat_stop') and app._heartbeat_stop:
        app._heartbeat_stop.set()


def heartbeat_loop(app):
    """心跳循环：每30秒向服务器发送账号状态"""
    server_url = app.settings.get("server_url", "").strip()
    client_key = app.settings.get("client_key", "").strip()
    if not server_url or not client_key:
        return

    try:
        machine_id = machine_fingerprint.get_machine_id()
    except Exception:
        return

    while not app._heartbeat_stop.is_set():
        try:
            send_heartbeat(app, server_url, client_key, machine_id)
        except Exception as e:
            print(f"⚠️ 心跳发送失败: {e}")

        # 等待30秒，分段检查停止信号
        for _ in range(6):
            if app._heartbeat_stop.is_set():
                break
            time.sleep(5)


def send_heartbeat(app, server_url, client_key, machine_id):
    """发送一次心跳到服务器，处理远程指令"""
    from data import cooldown_manager
    accounts = []
    for img_path in app.qq_account_images:
        cd_key = cooldown_manager.normalize_key(img_path)
        fname = os.path.basename(img_path)
        status = app._account_status.get(cd_key, "idle")
        accounts.append({"name": fname, "status": status})

    url = f"{server_url}/api/v1/heartbeat"
    payload = json.dumps({
        "machine_id": machine_id,
        "accounts": accounts,
        "is_running": app.running
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", client_key)
    req.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    # 处理远程指令
    commands = result.get("commands", [])
    for cmd in commands:
        action = cmd.get("action")
        if action == "run" and not app.running:
            print("📡 收到远程执行指令，正在启动任务...")
            from config_utils import utils
            utils.prevent_sleep()
            app.root.after(0, app.start)


def update_account_status(app, account_name, status):
    """更新单个账号的状态（线程安全）"""
    if hasattr(app, '_account_status'):
        app._account_status[account_name] = status
