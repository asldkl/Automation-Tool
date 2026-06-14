"""
账号管理模块
从 gui_app.py 提取的账号管理功能，作为模块级函数，接收 app 作为第一个参数
"""
import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import config
import utils
import cooldown_manager
import asset_db
import pyautogui
import cv2
import numpy as np

ACCOUNTS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_accounts.json")


def _account_key_from_path(path):
    """从账号路径提取账号标识（去掉 account: 前缀和 .png 后缀）"""
    name = os.path.basename(path)
    if name.startswith("account:"):
        return name[len("account:"):]
    return os.path.splitext(name)[0]


# ---------- 账号持久化 ----------
def save_accounts(app):
    try:
        data = {"wegame": [], "qq": app.qq_account_images,
                "assets": app._account_assets,
                "asset_history": app._asset_history,
                "notes": app._account_notes}
        with open(ACCOUNTS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存账号列表失败：{e}")


def load_accounts(app):
    if not os.path.exists(ACCOUNTS_JSON_PATH):
        return
    try:
        with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 兼容旧格式（纯列表 → 丢弃，不再使用 WeGame 账号列表）
        if isinstance(data, list):
            app.qq_account_images = []
        else:
            app.qq_account_images = [p for p in data.get("qq", [])
                                     if p.startswith("account:") or os.path.exists(p)]
            # 只保留当前存在的账号对应的资产和备注数据
            current_names = {_account_key_from_path(p) for p in app.qq_account_images}
            app._account_assets = {k: v for k, v in data.get("assets", {}).items() if k in current_names}
            app._asset_history = {k: v for k, v in data.get("asset_history", {}).items() if k in current_names}
            app._account_notes = {k: v for k, v in data.get("notes", {}).items() if k in current_names}
        # 刷新账号列表
        refresh_account_tree(app)
        print(f"✅ 已加载 {len(app.qq_account_images)} 个 QQ 账号")
    except Exception as e:
        print(f"⚠️ 加载历史账号失败：{e}")


def add_account(app):
    """添加账号：弹出账号信息设置窗口"""
    _open_account_info_window(app, None)


def _open_account_info_window(app, account_key=None):
    """打开账号信息设置窗口
    account_key: 为 None 时是新建账号，否则是编辑已有账号
    """
    is_new = account_key is None

    win = tk.Toplevel(app.root)
    win.title("账号信息设置")
    win.geometry("400x350")
    win.resizable(True, True)
    win.minsize(350, 300)
    win.transient(app.root)
    win.grab_set()
    utils.set_window_icon(win)

    # 窗口居中
    win.update_idletasks()
    w, h = 400, 350
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    # 解析已有数据
    if not is_new and account_key:
        existing = app._account_notes.get(account_key, {})
        if isinstance(existing, dict):
            saved_game = existing.get("game_name", "")
            saved_user = existing.get("account", "")
            saved_pass = existing.get("password", "")
            saved_note = existing.get("note", "")
        else:
            saved_game = ""
            saved_user = ""
            saved_pass = ""
            saved_note = existing if isinstance(existing, str) else ""
    else:
        saved_game = ""
        saved_user = ""
        saved_pass = ""
        from datetime import datetime
        saved_note = f"添加时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"

    # 输入框区域
    input_frame = ttk.Frame(win)
    input_frame.pack(fill=tk.X, padx=15, pady=(12, 5))

    row_game = ttk.Frame(input_frame)
    row_game.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(row_game, text="备注：", width=10, anchor='e').pack(side=tk.LEFT)
    game_var = tk.StringVar(value=saved_game)
    ttk.Entry(row_game, textvariable=game_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)

    row_user = ttk.Frame(input_frame)
    row_user.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(row_user, text="游戏账号：*", width=10, anchor='e', foreground='#e74c3c').pack(side=tk.LEFT)
    user_var = tk.StringVar(value=saved_user)
    ttk.Entry(row_user, textvariable=user_var, width=30).pack(side=tk.LEFT, fill=tk.X, expand=True)

    row_pass = ttk.Frame(input_frame)
    row_pass.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(row_pass, text="游戏密码：*", width=10, anchor='e', foreground='#e74c3c').pack(side=tk.LEFT)
    pass_var = tk.StringVar(value=saved_pass)
    pass_entry = ttk.Entry(row_pass, textvariable=pass_var, width=30, show="*")
    pass_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _toggle_show():
        if pass_entry.cget('show') == '*':
            pass_entry.config(show='')
            toggle_btn.config(text='隐藏密码')
        else:
            pass_entry.config(show='*')
            toggle_btn.config(text='显示密码')

    row_toggle = ttk.Frame(input_frame)
    row_toggle.pack(fill=tk.X, pady=(0, 4))
    ttk.Label(row_toggle, text="", width=10).pack(side=tk.LEFT)
    toggle_btn = ttk.Button(row_toggle, text="显示密码", width=10, command=_toggle_show)
    toggle_btn.pack(side=tk.LEFT)

    ttk.Label(win, text="备注信息：", font=('Microsoft YaHei UI', 9), foreground='#888').pack(padx=15, anchor='w')

    # 按钮固定在底部
    btn_frame = ttk.Frame(win)
    btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=15, pady=(0, 10))

    text_frame = ttk.Frame(win)
    text_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 10))

    text_widget = tk.Text(text_frame, wrap=tk.WORD, font=('Microsoft YaHei UI', 9),
                          bg='#fafbfc', fg='#333333', relief='flat', borderwidth=1,
                          highlightthickness=1, highlightcolor='#e0e0e0',
                          padx=8, pady=6)
    scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)
    text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
    text_widget.insert("1.0", saved_note)

    def _save():
        game_text = game_var.get().strip()
        user_text = user_var.get().strip()
        pass_text = pass_var.get().strip()
        note_text = text_widget.get("1.0", tk.END).strip()

        # 游戏账号和密码为必填
        if not user_text:
            messagebox.showwarning("提示", "游戏账号为必填项目！", parent=win)
            return
        if not pass_text:
            messagebox.showwarning("提示", "游戏密码为必填项目！", parent=win)
            return

        nonlocal account_key
        if is_new:
            # 新建账号：使用游戏账号作为标识
            account_key = user_text
            # 检查是否已存在
            if account_key in app._account_notes:
                messagebox.showwarning("提示", f"账号「{account_key}」已存在！", parent=win)
                return
            # 添加到账号列表（使用占位路径）
            placeholder = f"account:{account_key}"
            app.qq_account_images.append(placeholder)
        else:
            # 编辑已有账号：如果游戏账号改了，需要更新key
            new_key = user_text
            if new_key != account_key:
                if new_key in app._account_notes:
                    messagebox.showwarning("提示", f"账号「{new_key}」已存在！", parent=win)
                    return
                # 更新列表中的占位路径
                old_placeholder = f"account:{account_key}"
                new_placeholder = f"account:{new_key}"
                for i, p in enumerate(app.qq_account_images):
                    if p == old_placeholder:
                        app.qq_account_images[i] = new_placeholder
                        break
                # 迁移备注数据
                app._account_notes[new_key] = app._account_notes.pop(account_key, {})
                # 迁移资产数据
                app._account_assets[new_key] = app._account_assets.pop(account_key, "0")
                app._asset_history[new_key] = app._asset_history.pop(account_key, [])
                account_key = new_key

        # 保存备注
        app._account_notes[account_key] = {
            "game_name": game_text,
            "account": user_text,
            "password": pass_text,
            "note": note_text,
        }

        # 新建账号默认暂停
        if is_new:
            cooldown_manager.set_account_paused(account_key, True)

        refresh_account_tree(app)
        update_account_count(app)
        save_accounts(app)
        messagebox.showinfo("已保存", f"账号「{user_text}」已保存。", parent=win)
        win.destroy()

    ttk.Button(btn_frame, text="保存", style='Success.TButton',
               command=_save, width=10).pack(side=tk.LEFT)
    ttk.Button(btn_frame, text="取消", style='TButton',
               command=win.destroy, width=10).pack(side=tk.LEFT, padx=(8, 0))


def delete_account(app):
    sel = app.account_tree.selection()
    if sel:
        if "separator" in app.account_tree.item(sel[0], "tags"):
            return
        idx = _tree_idx_to_account_idx(app, sel[0])
        # 在删除前获取账号名称，用于清理资产数据
        account_name = _account_key_from_path(app.qq_account_images[idx])
        del app.qq_account_images[idx]
        # 清理该账号的资产和备注数据
        app._account_assets.pop(account_name, None)
        app._asset_history.pop(account_name, None)
        app._account_notes.pop(account_name, None)
        # 清理 SQLite 中的资产记录
        try:
            asset_db.delete_account_records(account_name)
        except Exception:
            pass
        refresh_account_tree(app)
        update_account_count(app)
        save_accounts(app)


def clear_accounts(app):
    app.qq_account_images.clear()
    app._account_assets.clear()
    app._asset_history.clear()
    refresh_account_tree(app)
    update_account_count(app)
    save_accounts(app)


def update_account_count(app):
    app.total_steps = len(app.qq_account_images) * 4
    app.progress['maximum'] = max(1, app.total_steps)


# ---------- 账号排序 ----------
def move_up(app):
    sel = app.account_tree.selection()
    if sel:
        if "separator" in app.account_tree.item(sel[0], "tags"):
            return
        idx = _tree_idx_to_account_idx(app, sel[0])
        if idx > 0:
            app.qq_account_images[idx], app.qq_account_images[idx-1] = app.qq_account_images[idx-1], app.qq_account_images[idx]
            refresh_account_tree(app)


def move_down(app):
    sel = app.account_tree.selection()
    if sel:
        if "separator" in app.account_tree.item(sel[0], "tags"):
            return
        idx = _tree_idx_to_account_idx(app, sel[0])
        if idx < len(app.qq_account_images) - 1:
            app.qq_account_images[idx], app.qq_account_images[idx+1] = app.qq_account_images[idx+1], app.qq_account_images[idx]
            refresh_account_tree(app)


def _tree_idx_to_account_idx(app, tree_item):
    """将 Treeview 项目 ID 转换为账号列表索引（跳过分隔行）"""
    tree_idx = app.account_tree.index(tree_item)
    # 计算该位置之前有多少个分隔行
    children = app.account_tree.get_children()
    separator_count = 0
    for i in range(tree_idx):
        if "separator" in app.account_tree.item(children[i], "tags"):
            separator_count += 1
    return tree_idx - separator_count


def refresh_account_tree(app):
    """刷新账号列表（Treeview），更新冷却和资产信息"""
    import cooldown_manager
    # 保存当前选中账号名称
    selected_name = None
    sel = app.account_tree.selection()
    if sel:
        vals = app.account_tree.item(sel[0], "values")
        if vals and "separator" not in app.account_tree.item(sel[0], "tags"):
            selected_name = vals[0]
    # 清空并重新填充
    for item in app.account_tree.get_children():
        app.account_tree.delete(item)
    all_cooldowns = cooldown_manager.get_all_cooldowns()
    seq = 0
    for i, p in enumerate(app.qq_account_images):
        name = _account_key_from_path(p)
        note_data = app._account_notes.get(name, {})
        if isinstance(note_data, dict) and note_data.get("account"):
            display_name = note_data["account"]
        else:
            display_name = name
        seq += 1
        display_name = f"{seq}. {display_name}"
        asset = app._account_assets.get(name, "0")
        # 备注信息（取单行备注字段）
        note_text = ""
        if isinstance(note_data, dict):
            note_text = note_data.get("game_name", "")
        # 计算下次运行时间（合并冷却剩余和下次运行）
        next_run_str = ""
        tag = "runnable"  # 默认可运行
        # 检查账号暂停状态（独立于冷却暂停）
        if cooldown_manager.is_account_paused(name):
            next_run_str = "已暂停"
            tag = "paused"
        elif name in all_cooldowns:
            cd_info = all_cooldowns[name]
            paused = cd_info.get("paused", False)
            next_time = cd_info.get("next_run_time", "")
            if paused:
                remaining = cd_info.get("remaining_seconds", 0)
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                next_run_str = f"冷却暂停 {hours}h {minutes}m"
                tag = "paused"
            elif next_time:
                from datetime import datetime
                try:
                    next_dt = datetime.fromisoformat(next_time)
                    now = datetime.now()
                    if next_dt > now:
                        diff = next_dt - now
                        hours = int(diff.total_seconds() // 3600)
                        minutes = int((diff.total_seconds() % 3600) // 60)
                        time_str = next_dt.strftime("%H:%M")
                        next_run_str = f"{hours}h {minutes}m({time_str})"
                        tag = "cooling"
                    else:
                        next_run_str = "已到期"
                except Exception:
                    pass
        app.account_tree.insert("", tk.END, values=(display_name, asset, next_run_str, note_text), tags=(tag,))
        # 插入分隔行（最后一行不插入）
        if i < len(app.qq_account_images) - 1:
            app.account_tree.insert("", tk.END, values=("", "", "", ""), tags=("separator",))
    # 恢复选中（按账号名称匹配）
    if selected_name:
        for child in app.account_tree.get_children():
            vals = app.account_tree.item(child, "values")
            if vals and vals[0] == selected_name and "separator" not in app.account_tree.item(child, "tags"):
                app.account_tree.selection_set(child)
                break
    save_accounts(app)


# ---------- 账号右键菜单 ----------
def show_account_menu(app, event):
    item = app.account_tree.identify_row(event.y)
    if not item:
        return
    if "separator" in app.account_tree.item(item, "tags"):
        return
    app.account_tree.selection_set(item)
    # 动态更新"暂停账号"/"恢复账号"菜单标签（使用固定索引，避免标签变化后找不到）
    import cooldown_manager
    idx = _tree_idx_to_account_idx(app, item)
    if idx < len(app.qq_account_images):
        name = _account_key_from_path(app.qq_account_images[idx])
        is_paused = cooldown_manager.is_account_paused(name)
        if is_paused:
            app.account_menu.entryconfigure(8, label="恢复账号")
        else:
            app.account_menu.entryconfigure(8, label="暂停账号")
    app.account_menu.tk_popup(event.x_root, event.y_root)


def manual_add_cooldown(app, event):
    """双击账号列表手动为该账号记录冷却时间"""
    sel = app.account_tree.selection()
    if not sel:
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    if idx >= len(app.qq_account_images):
        return
    account_name = _account_key_from_path(app.qq_account_images[idx])

    if not app.settings.get("enable_cooldown", False):
        messagebox.showinfo("提示",
            "冷却功能未启用，请先在设置中启用「账号冷却」。",
            parent=app.root)
        return

    cooling, next_time = cooldown_manager.is_cooling_down(account_name)
    cd_hours = app.settings.get("cooldown_hours", 8)

    if cooling:
        if not messagebox.askyesno("确认加入冷却",
                f"「{account_name}」当前仍在冷却中（下次运行：{next_time}）。\n\n"
                f"是否重新记录冷却时间（{cd_hours}小时）？",
                parent=app.root):
            return
    else:
        if not messagebox.askyesno("确认加入冷却",
                f"确定将「{account_name}」加入冷却？\n\n"
                f"冷却时间：{cd_hours}小时\n"
                f"加入后该账号在冷却期间不会被自动执行。",
                parent=app.root):
            return

    cooldown_manager.record_run(account_name, cd_hours)
    _, new_next = cooldown_manager.is_cooling_down(account_name)
    refresh_account_tree(app)
    messagebox.showinfo("已记录冷却",
        f"「{account_name}」已记录冷却时间。\n\n"
        f"下次运行时间：{new_next or '未知'}",
        parent=app.root)


def reset_selected_cooldown(app):
    """重置选中账号的冷却"""
    import cooldown_manager
    sel = app.account_tree.selection()
    if not sel:
        messagebox.showwarning("提示", "请先选中一个账号", parent=app.root)
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    if idx >= len(app.qq_account_images):
        return
    account_name = _account_key_from_path(app.qq_account_images[idx])
    cooling, next_time = cooldown_manager.is_cooling_down(account_name)
    if not cooling:
        messagebox.showinfo("提示", f"「{account_name}」当前没有在冷却中。", parent=app.root)
        return
    if messagebox.askyesno("确认重置", f"确定要重置「{account_name}」的冷却时间吗？", parent=app.root):
        cooldown_manager.reset_cooldown(account_name)
        refresh_account_tree(app)
        messagebox.showinfo("已重置", f"「{account_name}」的冷却已重置。", parent=app.root)


def custom_cooldown_time(app):
    """自定义选中账号的冷却时间"""
    import cooldown_manager
    sel = app.account_tree.selection()
    if not sel:
        messagebox.showwarning("提示", "请先选中一个账号", parent=app.root)
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    if idx >= len(app.qq_account_images):
        return
    account_name = _account_key_from_path(app.qq_account_images[idx])

    # 弹出输入对话框
    dialog = tk.Toplevel(app.root)
    dialog.title("自定义冷却时间")
    dialog.geometry("300x170")
    dialog.resizable(False, False)
    dialog.transient(app.root)
    dialog.grab_set()
    # 居中
    dialog.update_idletasks()
    dx = (dialog.winfo_screenwidth() - 300) // 2
    dy = (dialog.winfo_screenheight() - 170) // 2
    dialog.geometry(f"300x170+{dx}+{dy}")
    utils.set_window_icon(dialog)

    ttk.Label(dialog, text=f"账号：{account_name}").pack(pady=(15, 5))
    ttk.Label(dialog, text="冷却小时数：").pack()
    hours_var = tk.IntVar(value=app.settings.get("cooldown_hours", 8))
    spin = ttk.Spinbox(dialog, from_=1, to=72, textvariable=hours_var, width=10)
    spin.pack(pady=5)

    def confirm():
        hours = hours_var.get()
        cooldown_manager.record_run(account_name, hours)
        refresh_account_tree(app)
        _, new_next = cooldown_manager.is_cooling_down(account_name)
        messagebox.showinfo("已设置", f"「{account_name}」冷却 {hours} 小时。\n下次运行：{new_next or '未知'}", parent=app.root)
        dialog.destroy()

    ttk.Button(dialog, text="确认", command=confirm).pack(pady=10)


def reset_all_cooldowns(app):
    """一键重置所有账号冷却"""
    import cooldown_manager
    if not app.qq_account_images:
        messagebox.showinfo("提示", "账号列表为空。", parent=app.root)
        return
    if messagebox.askyesno("确认重置", "确定要重置所有账号的冷却时间吗？", parent=app.root):
        cooldown_manager.reset_all_cooldowns()
        refresh_account_tree(app)
        messagebox.showinfo("已重置", "所有账号的冷却已重置。", parent=app.root)


def toggle_account_pause(app):
    """暂停或恢复选中账号（暂停后运行时跳过该账号）"""
    import cooldown_manager
    sel = app.account_tree.selection()
    if not sel:
        messagebox.showwarning("提示", "请先选中一个账号", parent=app.root)
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    if idx >= len(app.qq_account_images):
        return
    account_name = _account_key_from_path(app.qq_account_images[idx])
    is_paused = cooldown_manager.is_account_paused(account_name)
    if is_paused:
        cooldown_manager.set_account_paused(account_name, False)
        refresh_account_tree(app)
        messagebox.showinfo("已恢复", f"「{account_name}」已恢复，运行时将正常执行。", parent=app.root)
    else:
        cooldown_manager.set_account_paused(account_name, True)
        refresh_account_tree(app)
        messagebox.showinfo("已暂停", f"「{account_name}」已暂停，运行时将跳过该账号。", parent=app.root)


def start_periodic_tree_refresh(app):
    """启动账号列表定时刷新（每60秒）"""
    refresh_account_tree(app)
    app._tree_refresh_timer = app.root.after(60000, lambda: start_periodic_tree_refresh(app))


def test_recognition(app):
    sel = app.account_tree.selection()
    if not sel:
        messagebox.showwarning("提示", "请先选中一个账号")
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    img_path = app.qq_account_images[idx]
    if not os.path.exists(img_path):
        messagebox.showerror("错误", "截图文件不存在")
        return
    try:
        import cv2
        import numpy as np
        screen = pyautogui.screenshot()
        gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)
        screen.close()
        template = cv2.imread(img_path, 0)
        if template is None:
            messagebox.showerror("错误", "无法读取截图文件")
            return

        # 标准灰度匹配
        res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        # 边缘匹配（对头像轮廓、文字笔画、数字形状更敏感）
        screen_edges = cv2.Canny(gray, 50, 150)
        template_edges = cv2.Canny(template, 50, 150)
        res_edge = cv2.matchTemplate(screen_edges, template_edges, cv2.TM_CCOEFF_NORMED)
        _, edge_val, _, edge_loc = cv2.minMaxLoc(res_edge)

        # 复合多尺度匹配
        matched_ms, max_val_ms, max_loc_ms, best_scale, (ms_h, ms_w) = \
            utils._match_template_multiscale(gray, template, 0.0)

        conf = int(max_val * 100)
        conf_edge = int(edge_val * 100)
        conf_ms = int(max_val_ms * 100)
        threshold = int(config.CONFIDENCE * 100)

        if max_val >= config.CONFIDENCE:
            status = "✅ 灰度匹配成功"
        elif edge_val >= config.CONFIDENCE:
            status = "✅ 边缘匹配成功（头像/文字/数字特征）"
        elif max_val_ms >= config.CONFIDENCE:
            status = f"✅ 复合多尺度匹配成功（缩放 {best_scale:.2f}x）"
        else:
            status = "❌ 匹配度不足，建议裁剪截图保留头像+名称+QQ号区域"

        scale_info = f"（缩放 {best_scale:.2f}x）" if best_scale != 1.0 else "（原始比例）"
        messagebox.showinfo(
            "测试结果",
            f"截图：{os.path.basename(img_path)}\n"
            f"模板尺寸：{template.shape[1]}x{template.shape[0]}\n\n"
            f"灰度匹配度：{conf}% (阈值：{threshold}%)\n"
            f"边缘匹配度：{conf_edge}% （头像轮廓/文字/数字特征）\n"
            f"复合多尺度：{conf_ms}% {scale_info}\n\n"
            f"结论：{status}\n\n"
            f"提示：截图应包含头像+名称+QQ号，这些特征组合可帮助精确区分不同账号。"
        )
    except Exception as e:
        messagebox.showerror("测试失败", f"识别过程出错：{e}")


def crop_account_image(app):
    """裁剪QQ账号截图，框选包含头像+名称+QQ号的区域以提高识别精度"""
    sel = app.account_tree.selection()
    if not sel:
        messagebox.showwarning("提示", "请先选中一个账号", parent=app.root)
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    img_path = app.qq_account_images[idx]
    if not os.path.exists(img_path):
        messagebox.showerror("错误", "截图文件不存在", parent=app.root)
        return

    try:
        from PIL import Image, ImageTk, ImageDraw
        img = Image.open(img_path)
    except Exception as e:
        messagebox.showerror("错误", f"无法打开图片：{e}", parent=app.root)
        return

    # 创建裁剪窗口
    crop_win = tk.Toplevel(app.root)
    crop_win.title(f"裁剪截图 - {os.path.basename(img_path)}")
    crop_win.resizable(True, True)
    crop_win.transient(app.root)
    crop_win.grab_set()

    # 设置图标
    utils.set_window_icon(crop_win)

    # 说明文字
    ttk.Label(crop_win, text="拖动鼠标框选包含头像+名称+QQ号的区域（三个特征组合可精确区分不同账号），然后点击「保存裁剪」",
              font=('Microsoft YaHei UI', 9), foreground='#555').pack(padx=10, pady=(10, 5), anchor='w')

    # 图片显示区域
    canvas_frame = ttk.Frame(crop_win)
    canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    canvas = tk.Canvas(canvas_frame, bg='#2c3e50', cursor='crosshair')
    canvas.pack(fill=tk.BOTH, expand=True)

    # 显示图片
    orig_w, orig_h = img.size
    canvas.update_idletasks()
    # 初始缩放以适应窗口
    display_img = img.copy()
    max_canvas_w, max_canvas_h = 800, 500
    scale_x = max_canvas_w / orig_w if orig_w > max_canvas_w else 1.0
    scale_y = max_canvas_h / orig_h if orig_h > max_canvas_h else 1.0
    display_scale = min(scale_x, scale_y, 1.0)
    disp_w = int(orig_w * display_scale)
    disp_h = int(orig_h * display_scale)
    if display_scale < 1.0:
        display_img = img.resize((disp_w, disp_h), Image.LANCZOS)
    else:
        display_img = img.copy()

    photo = ImageTk.PhotoImage(display_img)
    canvas.create_image(0, 0, anchor='nw', image=photo)
    canvas.config(scrollregion=canvas.bbox("all"))

    # 裁剪状态
    crop_state = {'start_x': 0, 'start_y': 0, 'rect_id': None, 'crop_rect': None}

    def on_press(event):
        crop_state['start_x'] = event.x
        crop_state['start_y'] = event.y
        if crop_state['rect_id']:
            canvas.delete(crop_state['rect_id'])
        crop_state['rect_id'] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline='#e74c3c', width=2, dash=(4, 4))

    def on_drag(event):
        if crop_state['rect_id']:
            canvas.coords(crop_state['rect_id'],
                          crop_state['start_x'], crop_state['start_y'],
                          event.x, event.y)

    def on_release(event):
        x1 = min(crop_state['start_x'], event.x)
        y1 = min(crop_state['start_y'], event.y)
        x2 = max(crop_state['start_x'], event.x)
        y2 = max(crop_state['start_y'], event.y)
        # 转换回原始图片坐标
        orig_x1 = int(x1 / display_scale)
        orig_y1 = int(y1 / display_scale)
        orig_x2 = int(x2 / display_scale)
        orig_y2 = int(y2 / display_scale)
        # 确保在图片范围内
        orig_x1 = max(0, min(orig_x1, orig_w))
        orig_y1 = max(0, min(orig_y1, orig_h))
        orig_x2 = max(0, min(orig_x2, orig_w))
        orig_y2 = max(0, min(orig_y2, orig_h))
        if orig_x2 - orig_x1 > 5 and orig_y2 - orig_y1 > 5:
            crop_state['crop_rect'] = (orig_x1, orig_y1, orig_x2, orig_y2)
            size_text = f"选区：{orig_x2-orig_x1}x{orig_y2-orig_y1} 像素"
            crop_info_label.config(text=size_text)
        else:
            crop_state['crop_rect'] = None
            crop_info_label.config(text="选区过小，请重新框选")

    canvas.bind('<ButtonPress-1>', on_press)
    canvas.bind('<B1-Motion>', on_drag)
    canvas.bind('<ButtonRelease-1>', on_release)

    # 底部信息和按钮
    bottom_frame = ttk.Frame(crop_win)
    bottom_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

    crop_info_label = ttk.Label(bottom_frame, text=f"原始尺寸：{orig_w}x{orig_h}  |  请拖动鼠标框选区域",
                                font=('Microsoft YaHei UI', 9), foreground='#7f8c8d')
    crop_info_label.pack(side=tk.LEFT)

    def save_crop():
        if not crop_state['crop_rect']:
            messagebox.showwarning("提示", "请先框选要裁剪的区域", parent=crop_win)
            return
        x1, y1, x2, y2 = crop_state['crop_rect']
        cropped = img.crop((x1, y1, x2, y2))
        try:
            cropped.save(img_path)
            app.qq_account_images[idx] = img_path  # 路径不变
            print(f"✅ 截图已裁剪并保存：{img_path} ({x2-x1}x{y2-y1})")
            messagebox.showinfo("完成",
                f"截图已裁剪并保存！\n\n"
                f"裁剪区域：{x2-x1}x{y2-y1} 像素\n"
                f"建议：保留头像+名称+QQ号三个特征区域，组合可精确区分不同账号。\n"
                f"可在右键菜单中使用「测试截图识别」验证效果。",
                parent=crop_win)
            crop_win.destroy()
        except Exception as e:
            messagebox.showerror("错误", f"保存失败：{e}", parent=crop_win)

    def cancel_crop():
        crop_win.destroy()

    ttk.Button(bottom_frame, text="保存裁剪", command=save_crop, width=10).pack(side=tk.RIGHT, padx=(5, 0))
    ttk.Button(bottom_frame, text="取消", command=cancel_crop, width=8).pack(side=tk.RIGHT)

    # 居中窗口
    crop_win.update_idletasks()
    w = max(crop_win.winfo_width(), 850)
    h = max(crop_win.winfo_height(), 600)
    x = (crop_win.winfo_screenwidth() - w) // 2
    y = (crop_win.winfo_screenheight() - h) // 2
    crop_win.geometry(f"{w}x{h}+{x}+{y}")


# ---------- 冷却查看 ----------
def show_cooldown_window(app):
    """弹出冷却状态查看窗口"""
    win = tk.Toplevel(app.root)
    win.title("账号冷却状态")
    win.geometry("700x480")
    win.resizable(False, False)
    win.transient(app.root)
    win.grab_set()
    # 居中
    win.update_idletasks()
    x = (win.winfo_screenwidth() - 700) // 2
    y = (win.winfo_screenheight() - 480) // 2
    win.geometry(f"700x480+{x}+{y}")
    # 图标
    utils.set_window_icon(win)

    # Treeview 区域（独立 Frame，确保与按钮区域垂直排列）
    tree_frame = ttk.Frame(win)
    tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    columns = ("account", "last_run", "remaining", "next_run")
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=10)
    tree.heading("account", text="账号名称")
    tree.heading("last_run", text="上次运行时间")
    tree.heading("remaining", text="冷却剩余")
    tree.heading("next_run", text="下次运行时间")
    tree.column("account", width=150, anchor="center")
    tree.column("last_run", width=150, anchor="center")
    tree.column("remaining", width=120, anchor="center")
    tree.column("next_run", width=150, anchor="center")

    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))

    def _format_remaining(seconds):
        if seconds <= 0:
            return "已冷却"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        if h > 0:
            return f"{h}小时{m}分钟"
        return f"{m}分钟"

    def _refresh():
        tree.delete(*tree.get_children())
        all_cd = cooldown_manager.get_all_cooldowns()
        for name, info in sorted(all_cd.items()):
            remaining_str = _format_remaining(info["remaining_seconds"])
            tree.insert("", tk.END, values=(
                name,
                info["last_run_time"],
                remaining_str,
                info["next_run_time"],
            ))

    _refresh()

    # 按钮区域（固定在底部）
    btn_frame = ttk.Frame(win)
    btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

    def _do_reset(account_name):
        """重置指定账号的冷却"""
        if messagebox.askyesno("确认",
                f"确定重置「{account_name}」的冷却？\n\n"
                f"重置后该账号将可以立即运行。",
                parent=win):
            cooldown_manager.reset_cooldown(account_name)
            _refresh()
            # 重置后更新唤醒定时器
            app._set_next_wake_timer()

    def _reset_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要重置的账号。", parent=win)
            return
        item = tree.item(sel[0])
        account_name = item["values"][0]
        _do_reset(account_name)

    def _on_double_click(event):
        """双击某行直接重置该账号冷却"""
        sel = tree.identify_row(event.y)
        if not sel:
            return
        tree.selection_set(sel)
        item = tree.item(sel)
        account_name = item["values"][0]
        _do_reset(account_name)

    tree.bind("<Double-1>", _on_double_click)

    ttk.Button(btn_frame, text="重置选中账号冷却", style='TButton',
               command=_reset_selected, width=16).pack(side=tk.LEFT)

    def _set_custom_time():
        """为选中账号设置自定义冷却结束时间"""
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要设置的账号。", parent=win)
            return
        item = tree.item(sel[0])
        account_name = item["values"][0]

        # 弹出输入对话框
        dialog = tk.Toplevel(win)
        dialog.title("自定义冷却时间")
        dialog.geometry("350x180")
        dialog.resizable(False, False)
        dialog.transient(win)
        dialog.grab_set()
        # 居中
        dialog.update_idletasks()
        dx = (dialog.winfo_screenwidth() - 350) // 2
        dy = (dialog.winfo_screenheight() - 180) // 2
        dialog.geometry(f"350x180+{dx}+{dy}")

        ttk.Label(dialog, text=f"为「{account_name}」设置冷却结束时间",
                  font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=(15, 5))
        ttk.Label(dialog, text="输入格式：HH:MM（当天/明天）或 YYYY-MM-DD HH:MM:SS",
                  font=('Microsoft YaHei UI', 8), foreground='#7f8c8d').pack()

        time_var = tk.StringVar()
        entry = ttk.Entry(dialog, textvariable=time_var, width=25)
        entry.pack(pady=8)
        entry.focus_set()

        def _confirm():
            raw = time_var.get().strip()
            if not raw:
                messagebox.showwarning("提示", "请输入时间", parent=dialog)
                return
            if cooldown_manager.set_custom_cooldown(account_name, raw):
                dialog.destroy()
                _refresh()
                app._set_next_wake_timer()
                messagebox.showinfo("完成", f"「{account_name}」冷却时间已更新。", parent=win)
            else:
                messagebox.showerror("错误", "时间格式不正确，请使用 HH:MM 或 YYYY-MM-DD HH:MM:SS", parent=dialog)

        btn_f = ttk.Frame(dialog)
        btn_f.pack(pady=5)
        ttk.Button(btn_f, text="确定", command=_confirm, width=8).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_f, text="取消", command=dialog.destroy, width=8).pack(side=tk.LEFT, padx=5)
        # 回车确认
        dialog.bind("<Return>", lambda e: _confirm())

    ttk.Button(btn_frame, text="自定义冷却时间", style='TButton',
               command=_set_custom_time, width=14).pack(side=tk.LEFT, padx=(10, 0))
    ttk.Button(btn_frame, text="刷新", style='TButton',
               command=_refresh, width=8).pack(side=tk.LEFT, padx=(10, 0))

    def _reset_all():
        all_cd = cooldown_manager.get_all_cooldowns()
        if not all_cd:
            messagebox.showinfo("提示", "当前没有任何冷却记录。", parent=win)
            return
        count = len(all_cd)
        if messagebox.askyesno("确认",
                f"确定重置所有 {count} 个账号的冷却？\n\n"
                f"重置后所有账号将可以立即运行。",
                parent=win):
            cooldown_manager.reset_all_cooldowns()
            _refresh()
            # 重置后更新唤醒定时器
            app._set_next_wake_timer()

    ttk.Button(btn_frame, text="一键重置所有", style='TButton',
               command=_reset_all, width=12).pack(side=tk.LEFT, padx=(10, 0))
    ttk.Button(btn_frame, text="关闭", style='TButton',
               command=win.destroy, width=8).pack(side=tk.RIGHT)


# ---------- 帮助信息 ----------
def show_help(app):
    help_text = (
        "【基本操作】\n"
        "F1 / 「开始运行」 → 依次登录 WeGame → 进游戏执行任务\n"
        "F2 / 「停止」       → 终止当前运行\n\n"
        "【账号管理】\n"
        "• 添加账号：点击「添加账号」，填写游戏账号（必填）、密码、备注\n"
        "• 编辑账号：右键账号 → 账号信息设置\n"
        "• 删除账号：右键账号 → 删除选中\n"
        "• 双击账号：手动将该账号加入冷却（需先启用冷却功能）\n\n"
        "【账号冷却】\n"
        "设置 → 自动任务设置 → 启用账号冷却（默认8小时）\n"
        "• 点击「查看冷却」可查看所有账号冷却状态\n"
        "• 在冷却窗口中可重置单个账号或一键重置所有冷却\n"
        "• 运行失败或手动停止的账号不会记录冷却\n"
        "• 冷却完立即运行：冷却结束后自动执行任务\n\n"
        "【资产监测】\n"
        "• 点击「资产监测」查看所有账号资产状态\n"
        "• 输入天数后点击「查询」统计资产变化\n"
        "• 右键账号 → 查看资产记录：查看单个账号历史\n\n"
        "【自动关机】\n"
        "设置 → 其他设置 → 可配置自动关机和运行完成后延迟关机\n\n"
        "【开机自启动】\n"
        "设置 → 其他设置 → 可配置开机自启动\n\n"
        "【注意】\n"
        "• 图像识别依赖固定分辨率/缩放比例\n"
        "• 步骤超时自动跳过当前账号，继续执行下一个\n"
        "• 停止信号发出后，当前步骤完成才退出"
    )
    messagebox.showinfo("使用说明", help_text)


def _parse_asset_value(val_str):
    """代理到 utils.parse_asset_value"""
    return utils.parse_asset_value(val_str)


def _strip_year(time_str):
    """去掉时间字符串中的年份前缀，如 '2026-06-07 14:30' -> '06-07 14:30'"""
    if not time_str:
        return time_str
    parts = time_str.split("-", 1)
    if len(parts) == 2 and len(parts[0]) == 4 and parts[0].isdigit():
        return parts[1]
    return time_str


def show_asset_history(app):
    """弹窗显示选中账号的资产历史记录"""
    selected = app.account_tree.selection()
    if not selected:
        messagebox.showwarning("提示", "请先选择一个账号", parent=app.root)
        return
    item = selected[0]
    if "separator" in app.account_tree.item(item, "tags"):
        return
    idx = _tree_idx_to_account_idx(app, item)
    if idx >= len(app.qq_account_images):
        return
    account_name = _account_key_from_path(app.qq_account_images[idx])

    history = app._asset_history.get(account_name, [])
    if not history:
        messagebox.showinfo("资产记录", f"账号 {account_name} 暂无资产记录", parent=app.root)
        return

    # 创建弹窗
    win = tk.Toplevel(app.root)
    win.title(f"资产记录 - {account_name}")
    win.geometry("420x400")
    win.minsize(350, 300)
    win.resizable(True, True)
    win.transient(app.root)
    win.grab_set()

    # 设置图标
    utils.set_window_icon(win)

    # 窗口居中
    win.update_idletasks()
    w, h = 420, 400
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    # 标题
    ttk.Label(win, text=f"账号：{account_name}", font=('Microsoft YaHei UI', 11, 'bold')).pack(padx=15, pady=(12, 5), anchor='w')

    # 表格容器
    tree_frame = ttk.Frame(win)
    tree_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

    columns = ("时间", "资产", "变化")
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12)
    tree.heading("时间", text="时间")
    tree.heading("资产", text="资产")
    tree.heading("变化", text="变化")
    tree.column("时间", width=150, minwidth=120)
    tree.column("资产", width=80, minwidth=60, anchor=tk.CENTER)
    tree.column("变化", width=100, minwidth=80, anchor=tk.CENTER)

    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

    # 填充数据（从新到旧）
    for i in range(len(history) - 1, -1, -1):
        entry = history[i]
        time_str = _strip_year(entry.get("time", ""))
        value = entry.get("value", "0")
        if i > 0:
            prev_val = _parse_asset_value(history[i - 1].get("value", "0"))
            cur_val = _parse_asset_value(value)
            diff = cur_val - prev_val
            if diff > 0:
                diff_str = f"+{_format_asset_num(diff)}"
            elif diff < 0:
                diff_str = f"{_format_asset_num(diff)}"
            else:
                diff_str = "—"
        else:
            diff_str = "—"
        tree.insert("", tk.END, values=(time_str, value, diff_str))

    # 底部统计
    if len(history) >= 2:
        first_val = _parse_asset_value(history[0].get("value", "0"))
        last_val = _parse_asset_value(history[-1].get("value", "0"))
        total_diff = last_val - first_val
        if total_diff > 0:
            trend = f"累计增长 +{_format_asset_num(total_diff)}"
            color = "#4caf50"
        elif total_diff < 0:
            trend = f"累计变化 {_format_asset_num(total_diff)}"
            color = "#f44336"
        else:
            trend = "累计无变化"
            color = "#888"
        ttk.Label(win, text=f"共 {len(history)} 条记录  |  {trend}",
                  font=('Microsoft YaHei UI', 9), foreground=color).pack(padx=15, pady=(0, 10), anchor='w')
    else:
        ttk.Label(win, text=f"共 {len(history)} 条记录",
                  font=('Microsoft YaHei UI', 9), foreground='#888').pack(padx=15, pady=(0, 10), anchor='w')


def _format_asset_num(val):
    """代理到 utils.format_asset_num"""
    return utils.format_asset_num(val)


def show_asset_monitor(app):
    """弹出资产监测窗口：上半部分显示所有账号当前资产，下半部分按时间段统计变化"""
    win = tk.Toplevel(app.root)
    win.title("资产监测")
    win.geometry("400x400")
    win.resizable(True, True)
    win.minsize(200, 200)
    win.transient(app.root)
    win.grab_set()

    # 设置图标
    utils.set_window_icon(win)

    # 窗口居中
    win.update_idletasks()
    w, h = 400, 400
    x = (win.winfo_screenwidth() - w) // 2
    y = (win.winfo_screenheight() - h) // 2
    win.geometry(f"{w}x{h}+{x}+{y}")

    # ===== 上半部分：当前状态 =====
    status_frame = ttk.LabelFrame(win, text=" 当前资产状态 ", padding=10)
    status_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

    tree_frame = ttk.Frame(status_frame)
    tree_frame.pack(fill=tk.BOTH, expand=True)

    columns = ("account", "asset")
    asset_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=6)
    asset_tree.heading("account", text="账号名称")
    asset_tree.heading("asset", text="现有资产")
    asset_tree.column("account", width=80, minwidth=50)
    asset_tree.column("asset", width=50, minwidth=30, anchor=tk.CENTER)

    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=asset_tree.yview)
    asset_tree.configure(yscrollcommand=scrollbar.set)
    asset_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

    def _refresh_status():
        for item in asset_tree.get_children():
            asset_tree.delete(item)
        for i, p in enumerate(app.qq_account_images):
            name = _account_key_from_path(p)
            note_data = app._account_notes.get(name, {})
            if isinstance(note_data, dict) and note_data.get("account"):
                display_name = note_data["account"]
            else:
                display_name = name
            display_name = f"{i+1}. {display_name}"
            asset_value = app._account_assets.get(name, "0")
            asset_tree.insert("", tk.END, values=(display_name, asset_value))

    _refresh_status()

    # ===== 下半部分：统计面板 =====
    stats_frame = ttk.LabelFrame(win, text=" 资产变化统计 ", padding=10)
    stats_frame.pack(fill=tk.X, padx=10, pady=(5, 10))

    # 按钮行
    btn_row = ttk.Frame(stats_frame)
    btn_row.pack(fill=tk.X, pady=(0, 8))

    result_label = ttk.Label(stats_frame, text="请选择时间范围查看资产变化",
                             font=('Microsoft YaHei UI', 10), foreground='#888')
    result_label.pack(fill=tk.X)

    detail_label = ttk.Label(stats_frame, text="", font=('Microsoft YaHei UI', 9),
                             foreground='#666', wraplength=650, justify=tk.LEFT)
    detail_label.pack(fill=tk.X, pady=(4, 0))

    def _show_stats(days):
        total_diff, details = asset_db.query_total_change(days)
        # 构建当前账号顺序映射（与主界面一致）
        ordered_keys = [_account_key_from_path(p) for p in app.qq_account_images]
        details_map = {d[0]: d for d in details}
        # 按主界面顺序排列，只保留当前存在的账号
        ordered_details = [details_map[k] for k in ordered_keys if k in details_map]
        total_diff = sum(d[3] for d in ordered_details) if ordered_details else 0.0

        if not ordered_details:
            result_label.config(text=f"近 {days} 天暂无资产记录", foreground='#888')
            detail_label.config(text="")
            return

        # 总变化
        diff_str = asset_db.format_asset_num(total_diff)
        if total_diff > 0:
            result_label.config(text=f"近 {days} 天总资产变化：+{diff_str}", foreground='#4caf50')
        elif total_diff < 0:
            result_label.config(text=f"近 {days} 天总资产变化：{diff_str}", foreground='#f44336')
        else:
            result_label.config(text=f"近 {days} 天总资产变化：无变化", foreground='#888')

        # 明细（带序号，与主界面顺序一致）
        lines = []
        for seq, (account, first_val, last_val, diff) in enumerate(ordered_details, 1):
            # 获取显示名称
            note_data = app._account_notes.get(account, {})
            if isinstance(note_data, dict) and note_data.get("account"):
                display_name = note_data["account"]
            else:
                display_name = account
            first_str = asset_db.format_asset_num(first_val)
            last_str = asset_db.format_asset_num(last_val)
            diff_s = asset_db.format_asset_num(diff)
            if diff > 0:
                lines.append(f"  {seq}. {display_name}：{first_str} → {last_str}（+{diff_s}）")
            elif diff < 0:
                lines.append(f"  {seq}. {display_name}：{first_str} → {last_str}（{diff_s}）")
            else:
                lines.append(f"  {seq}. {display_name}：{first_str} → {last_str}（无变化）")
        detail_label.config(text="\n".join(lines))

    ttk.Label(btn_row, text="近").pack(side=tk.LEFT)
    days_var = tk.IntVar(value=1)
    days_spin = ttk.Spinbox(btn_row, from_=1, to=365, textvariable=days_var, width=6)
    days_spin.pack(side=tk.LEFT, padx=4)
    ttk.Label(btn_row, text="天").pack(side=tk.LEFT)
    ttk.Button(btn_row, text="查询", style='Accent.TButton',
               command=lambda: _show_stats(days_var.get()), width=8).pack(side=tk.LEFT, padx=(8, 0))


def show_account_note(app):
    """弹出账号信息设置窗口，为选中账号添加/编辑备注信息"""
    sel = app.account_tree.selection()
    if not sel:
        messagebox.showwarning("提示", "请先选中一个账号", parent=app.root)
        return
    if "separator" in app.account_tree.item(sel[0], "tags"):
        return
    idx = _tree_idx_to_account_idx(app, sel[0])
    if idx >= len(app.qq_account_images):
        return
    account_name = _account_key_from_path(app.qq_account_images[idx])
    _open_account_info_window(app, account_name)
