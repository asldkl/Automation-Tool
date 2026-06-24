"""Email notification functions extracted from gui_app.py.

Each function receives `app` as the first parameter (replacing `self`),
accessing settings via `app.settings` and run_stats via `app.run_stats`.
"""

import datetime
import html
import threading
import time

import utils
import cooldown_manager


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

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#e74c3c;border-bottom:2px solid #e74c3c;padding-bottom:10px;">三角洲行动自动化工具 - 账号运行失败</h2>
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
            f"三角洲自动化 - 账号失败通知 ({account_name})", body
        )
        if success:
            print(f"📧 账号 {account_name} 失败通知邮件已发送")
        else:
            print(f"📧 失败通知邮件发送失败：{msg}")

    threading.Thread(target=_send, daemon=True).start()


def send_cooldown_ready_email(app, ready_accounts):
    """冷却到期时发送邮件提醒"""
    if not app.settings.get("cooldown_email_enabled", False):
        return
    cfg = _get_email_config(app)
    if not cfg:
        return
    smtp_code, sender, receiver = cfg

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    account_items = "".join(f"<li style='padding:3px 0;'>{html.escape(name)}</li>" for name in ready_accounts)
    count = len(ready_accounts)

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#27ae60;border-bottom:2px solid #27ae60;padding-bottom:10px;">三角洲行动自动化工具 - 冷却到期提醒</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">提醒时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">到期账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;font-weight:bold;">{count} 个</td></tr>
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">到期账号列表</td></tr>
<tr><td colspan="2" style="padding:8px 10px;border:1px solid #dcdde1;"><ul style="margin:0;padding-left:20px;">{account_items}</ul></td></tr>
</table>
<div style="text-align:center;padding:10px;margin-top:10px;border-radius:5px;background:#27ae6015;border:1px solid #27ae6040;">
<span style="font-size:16px;font-weight:bold;color:#27ae60;">以上账号冷却已到期，即将自动执行任务</span>
</div>
<p style="color:#7f8c8d;font-size:12px;text-align:center;margin-top:15px;">此邮件由三角洲行动自动化工具自动发送</p>
</div>"""

    def _send():
        success, msg = utils.send_email_notification(
            smtp_code, sender, receiver,
            f"三角洲自动化 - 冷却到期提醒 ({count}个账号)", body
        )
        if success:
            print(f"📧 冷却到期提醒邮件已发送（{count}个账号）")
        else:
            print(f"📧 冷却到期提醒邮件发送失败：{msg}")

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
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_color = "#27ae60" if stats["fail"] == 0 else "#e74c3c"
    status_text = "全部成功" if stats["fail"] == 0 else f"有 {stats['fail']} 个失败"

    # 已选操作
    op_names = {"tech_center": "技术中心", "tool_bench": "工作台",
                "armor_station": "防具台", "pharmacy_station": "制药台"}
    selected = app.settings.get("selected_operations", [])
    ops_text = "、".join(op_names.get(op, op) for op in selected) if selected else "无"

    # 一键出售统计
    sell_section = ""
    sell_stats = stats.get("sell_stats")
    if sell_stats:
        sell_section = f"""
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">一键出售</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">物品总数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{sell_stats['total']} 件</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功上架</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{sell_stats['sold']} 件</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">未找到</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e67e22' if sell_stats['not_found']>0 else '#2c3e50'};">{sell_stats['not_found']} 件</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e74c3c' if sell_stats['failed']>0 else '#2c3e50'};">{sell_stats['failed']} 件</td></tr>"""

    # QQ号名称列表（含下次运行时间）
    accounts_section = app._build_accounts_html(processed_accounts)

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:10px;">三角洲行动自动化工具 - 运行报告</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">基本信息</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">执行操作</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{ops_text}</td></tr>
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">账号统计</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">处理账号数</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{stats['total']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">成功</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:#27ae60;">{stats['success']} 个</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">失败</td><td style="padding:8px 10px;border:1px solid #dcdde1;color:{'#e74c3c' if stats['fail']>0 else '#2c3e50'};">{stats['fail']} 个</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">耗时</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{time_str}</td></tr>
{sell_section}
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
            f"三角洲自动化 - 运行报告 ({status_text})", body
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

    # 已选操作
    op_names = {"tech_center": "技术中心", "tool_bench": "工作台",
                "armor_station": "防具台", "pharmacy_station": "制药台"}
    selected = app.settings.get("selected_operations", [])
    ops_text = "、".join(op_names.get(op, op) for op in selected) if selected else "无"

    # 运行模式
    # QQ号名称列表（含下次运行时间）
    accounts_section = app._build_accounts_html(processed_accounts)

    body = f"""<div style="font-family:Microsoft YaHei,sans-serif;padding:20px;max-width:600px;margin:0 auto;">
<h2 style="color:#e74c3c;border-bottom:2px solid #e74c3c;padding-bottom:10px;">三角洲行动自动化工具 - 运行失败通知</h2>
<table style="border-collapse:collapse;width:100%;margin:15px 0;">
<tr><td colspan="2" style="padding:10px 10px 5px;font-size:15px;font-weight:bold;color:#2c3e50;">基本信息</td></tr>
<tr style="background:#f0f2f5;"><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;width:120px;">运行时间</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{now_str}</td></tr>
<tr><td style="padding:8px 10px;border:1px solid #dcdde1;font-weight:bold;">执行操作</td><td style="padding:8px 10px;border:1px solid #dcdde1;">{ops_text}</td></tr>
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
            "三角洲自动化 - 运行失败通知", body
        )
        if success:
            print("📧 失败通知邮件已发送")
        else:
            print(f"📧 失败通知邮件发送失败：{msg}")

    threading.Thread(target=_send, daemon=True).start()
