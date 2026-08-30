"""Email notification functions extracted from gui_app.py.

Each function receives `app` as the first parameter (replacing `self`),
accessing settings via `app.settings` and run_stats via `app.run_stats`.
"""

import datetime
import html
import threading
import time

from config_utils import utils
from data import cooldown_manager

def _get_machine_name():
    """获取电脑名称（机器名称），用于邮件标题区分设备"""
    try:
        import platform
        name = platform.node()
        return name or "未知机器"
    except Exception:
        return "未知机器"


def _get_email_config(app):
    """获取邮箱配置，返回 (smtp_code, sender, receiver) 或 None（未配置）"""
    if not app.settings.get("email_enabled", False):
        return None
    smtp_code = app.settings.get("smtp_code", "").strip()
    sender = app.settings.get("sender_email", "").strip()
    receiver = app.settings.get("receiver_email", "").strip()
    if not smtp_code or not sender or not receiver:
        return None
    return smtp_code, sender, receiver


def send_account_failure_email(app, account_name, next_run_str, processed_accounts=None, error_msg=""):
    """单个账号失败时立即发送邮件通知（含错误日志）"""
    cfg = _get_email_config(app)
    if not cfg:
        return
    smtp_code, sender, receiver = cfg

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_name = html.escape(account_name)
    safe_error = html.escape(error_msg) if error_msg else "未知错误"
    machine_name = _get_machine_name()

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#e74c3c;border-bottom:2px solid #e74c3c;padding-bottom:10px;">{machine_name}—账号运行失败</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">账号名称</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#e74c3c;font-weight:bold;">{safe_name}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">错误原因</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#e74c3c;">{safe_error}</td></tr>
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:#e74c3c15;border:1px solid #e74c3c40;">
<span style="font-size:16px;font-weight:bold;color:#e74c3c;">账号 {safe_name} 运行失败，后续账号将继续执行</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

    def _send():
        success, msg = utils.send_email_notification(
            smtp_code, sender, receiver,
            f"{machine_name}—账号失败通知 ({account_name})", body
        )
        if success:
            print(f"📧 账号 {account_name} 失败通知邮件已发送")
        else:
            print(f"📧 失败通知邮件发送失败：{msg}")

    threading.Thread(target=_send, daemon=True).start()


def send_run_report_email(app, stats, elapsed, processed_accounts=None):
    """在后台线程中发送邮件通知"""
    cfg = _get_email_config(app)
    if not cfg:
        return
    smtp_code, sender, receiver = cfg

    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    time_str = f"{h}时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"
    status_color = "#27ae60" if stats["fail"] == 0 else "#e74c3c"
    status_text = "全部成功" if stats["fail"] == 0 else f"有 {stats['fail']} 个失败"
    machine_name = _get_machine_name()

    # 已处理账号列表（表格：备注前缀 + 状态 + 下次运行）
    accounts_section = app._build_accounts_html(processed_accounts)

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px;">{machine_name}—运行报告</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">账号统计</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">处理账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{stats['total']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{stats['success']} 个</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e74c3c' if stats['fail']>0 else '#2c3e50'};">{stats['fail']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">耗时</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{time_str}</td></tr>
{accounts_section}
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:{status_color}15;border:1px solid {status_color}40;">
<span style="font-size:16px;font-weight:bold;color:{status_color};">运行状态：{status_text}</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

    def _send():
        success, msg = utils.send_email_notification(
            smtp_code, sender, receiver,
            f"{machine_name}—运行报告 ({status_text})", body
        )
        if success:
            print("📧 邮件通知已发送")
        else:
            print(f"📧 邮件通知发送失败：{msg}")

    threading.Thread(target=_send, daemon=True).start()


def send_failure_email(app, error, processed_accounts=None):
    """程序异常退出时发送失败邮件通知"""
    cfg = _get_email_config(app)
    if not cfg:
        return
    smtp_code, sender, receiver = cfg

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stats = app.run_stats
    elapsed = time.time() - stats["start_time"] if stats["start_time"] else 0
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    time_str = f"{h}时{m}分{s}秒" if h > 0 else f"{m}分{s}秒"
    # 最先运行时间（本轮开始）和最后运行时间（本轮结束）
    start_time_str = (datetime.datetime.fromtimestamp(stats["start_time"]).strftime("%Y-%m-%d %H:%M:%S")
                      if stats.get("start_time") else "未知")

    # 已选操作
    op_names = {"tech_center": "技术中心", "tool_bench": "工作台",
                "armor_station": "防具台", "pharmacy_station": "制药台"}
    selected = app.settings.get("selected_operations", [])
    ops_text = "、".join(op_names.get(op, op) for op in selected) if selected else "无"

    # 运行模式
    # QQ号名称列表（含下次运行时间）
    accounts_section = app._build_accounts_html(processed_accounts)
    machine_name = _get_machine_name()

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#e74c3c;border-bottom:2px solid #e74c3c;padding-bottom:10px;">{machine_name}—运行失败通知</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">基本信息</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">最先运行</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{start_time_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">最后运行</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">执行操作</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{ops_text}</td></tr>
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">运行统计</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">处理账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{stats['total']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{stats['success']} 个</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#e74c3c;">{stats['fail']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">已运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{time_str}</td></tr>
{accounts_section}
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#e74c3c;">错误信息</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;background:#fff5f5;color:#e74c3c;">{html.escape(str(error))}</td></tr>
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:#e74c3c15;border:1px solid #e74c3c40;">
<span style="font-size:16px;font-weight:bold;color:#e74c3c;">运行状态：程序异常退出</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

    def _send():
        success, msg = utils.send_email_notification(
            smtp_code, sender, receiver,
            f"{machine_name}—运行失败通知", body
        )
        if success:
            print("📧 失败通知邮件已发送")
        else:
            print(f"📧 失败通知邮件发送失败：{msg}")

    threading.Thread(target=_send, daemon=True).start()
