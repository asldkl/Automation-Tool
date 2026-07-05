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

ACCOUNTS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_accounts.json")


def _account_key_from_path(path):
    """从账号路径提取账号标识（去掉 account: 前缀和扩展名）"""
    name = os.path.basename(path)
    if ":" in name:
        name = name.split(":", 1)[1]
    return os.path.splitext(name)[0]


# 统一使用 cooldown_manager.normalize_key
def _get_cooldown_key(img_path):
    """获取冷却数据中使用的 key（统一短名称格式）"""
    return cooldown_manager.normalize_key(img_path)


# ---------- 账号持久化 ----------
def save_accounts(app):
    try:
        data = {"wegame": [], "qq": app.qq_account_images,
                "assets": app._account_assets,
                "asset_history": app._asset_history,
                "notes": app._account_notes}
        tmp_path = ACCOUNTS_JSON_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, ACCOUNTS_JSON_PATH)
    except Exception as e:
        print(f"⚠️ 保存账号列表失败：{e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def load_accounts(app):
    if not os.path.exists(ACCOUNTS_JSON_PATH):
        return
    try:
        with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        app.qq_account_images = list(data.get("qq", []))
        # 只保留当前存在的账号对应的资产和备注数据
        current_names = {_account_key_from_path(p) for p in app.qq_account_images}
        app._account_assets = {k: v for k, v in data.get("assets", {}).items() if k in current_names}
        app._asset_history = {k: v for k, v in data.get("asset_history", {}).items() if k in current_names}
        app._account_notes = {k: v for k, v in data.get("notes", {}).items() if k in current_names}
        # 刷新账号列表
        refresh_account_tree(app)
        print(f"✅ 已加载 {len(app.qq_account_images)} 个账号")
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
    win.resizable(True, True)
    win.minsize(350, 300)
    win.transient(app.root)
    win.grab_set()
    utils.set_window_icon(win)

    # 恢复窗口大小 + 关闭时自动保存
    utils.bind_window_geometry(win, "account_info_geometry", "400x350", (350, 300))

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
                # 迁移冷却数据
                old_cd = cooldown_manager.get_all_cooldowns().get(account_key)
                if old_cd:
                    cooldown_manager.reset_cooldown(account_key)
                    if old_cd.get("next_run_time"):
                        cooldown_manager.set_custom_cooldown(new_key, old_cd["next_run_time"])
                    if old_cd.get("account_paused"):
                        cooldown_manager.set_account_paused(new_key, True)
                account_key = new_key

        # 保存备注
        app._account_notes[account_key] = {
            "game_name": game_text,
            "account": user_text,
            "password": pass_text,
            "note": note_text,
        }

        # 新建账号立即在内存中标记暂停（确保 UI 刷新时显示正确颜色）
        if is_new:
            cooldown_manager.set_account_paused(account_key, True)

        # 立即刷新 UI
        refresh_account_tree(app)
        update_account_count(app)

        # 磁盘操作放到后台线程，避免卡 UI
        def _save_to_disk():
            try:
                save_accounts(app)
            except Exception as e:
                print(f"⚠️ 保存账号数据失败: {e}")

        import threading
        threading.Thread(target=_save_to_disk, daemon=True).start()

        # 关闭窗口后再弹提示（避免模态窗口遮挡）
        utils.save_window_geometry(win, "account_info_geometry")
        win.destroy()
        messagebox.showinfo("已保存", f"账号「{user_text}」已保存。", parent=app.root)

    def _close():
        utils.save_window_geometry(win, "account_info_geometry")
        win.destroy()

    ttk.Button(btn_frame, text="保存", style='Success.TButton',
               command=_save, width=10).pack(side=tk.LEFT)
    ttk.Button(btn_frame, text="取消", style='TButton',
               command=_close, width=10).pack(side=tk.LEFT, padx=(8, 0))


def delete_account(app):
    import cooldown_manager
    sel = app.account_tree.selection()
    if sel:
        if "separator" in app.account_tree.item(sel[0], "tags"):
            return
        idx = _tree_idx_to_account_idx(app, sel[0])
        img_path = app.qq_account_images[idx]
        account_name = _account_key_from_path(img_path)
        del app.qq_account_images[idx]
        # 清理该账号的所有数据
        app._account_assets.pop(account_name, None)
        app._asset_history.pop(account_name, None)
        app._account_notes.pop(account_name, None)
        cooldown_manager.reset_cooldown(account_name)
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
    app._account_notes.clear()
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
            save_accounts(app)


def move_down(app):
    sel = app.account_tree.selection()
    if sel:
        if "separator" in app.account_tree.item(sel[0], "tags"):
            return
        idx = _tree_idx_to_account_idx(app, sel[0])
        if idx < len(app.qq_account_images) - 1:
            app.qq_account_images[idx], app.qq_account_images[idx+1] = app.qq_account_images[idx+1], app.qq_account_images[idx]
            refresh_account_tree(app)
            save_accounts(app)


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
        # 统一显示为 M 格式（如 78,394K → 78.39M）
        if asset and asset != "0":
            try:
                asset_num = utils.parse_asset_value(asset)
                if asset_num > 0:
                    asset = utils.format_asset_num(asset_num)
            except Exception:
                pass
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
            game_failed = cd_info.get("game_failed", False)
            next_time = cd_info.get("next_run_time", "")
            if paused:
                remaining = cd_info.get("remaining_seconds", 0)
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                next_run_str = f"冷却暂停 {hours}h {minutes}m"
                tag = "paused"
            elif game_failed:
                remaining = cd_info.get("remaining_seconds", 0)
                hours = int(remaining // 3600)
                minutes = int((remaining % 3600) // 60)
                next_run_str = f"游戏失败 {hours}h {minutes}m"
                tag = "game_failed"
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


# ---------- 账号右键菜单 ----------
def show_account_menu(app, event):
    item = app.account_tree.identify_row(event.y)
    if not item:
        return
    if "separator" in app.account_tree.item(item, "tags"):
        return
    app.account_tree.selection_set(item)
    # 动态更新"暂停账号"/"恢复账号"菜单标签
    import cooldown_manager
    idx = _tree_idx_to_account_idx(app, item)
    if idx < len(app.qq_account_images):
        name = _account_key_from_path(app.qq_account_images[idx])
        is_paused = cooldown_manager.is_account_paused(name)
        new_label = "恢复账号" if is_paused else "暂停账号"
        # 遍历菜单项找到"暂停账号"或"恢复账号"并更新
        for i in range(app.account_menu.index(tk.END) + 1):
            try:
                current = app.account_menu.entrycget(i, "label")
                if current in ("暂停账号", "恢复账号"):
                    app.account_menu.entryconfigure(i, label=new_label)
                    break
            except tk.TclError:
                continue
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
    img_path = app.qq_account_images[idx]
    account_name = _get_cooldown_key(img_path)

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
    img_path = app.qq_account_images[idx]
    account_name = _get_cooldown_key(img_path)
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
    img_path = app.qq_account_images[idx]
    account_name = _get_cooldown_key(img_path)

    # 弹出输入对话框
    dialog = tk.Toplevel(app.root)
    dialog.title("自定义冷却时间")
    dialog.resizable(True, True)
    dialog.minsize(320, 200)
    dialog.transient(app.root)
    dialog.grab_set()
    utils.set_window_icon(dialog)
    utils.bind_window_geometry(dialog, "custom_cooldown_geometry", "360x220", (320, 200))

    ttk.Label(dialog, text=f"账号：{account_name}", font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=(15, 10))

    # 小时 + 分钟
    time_frame = ttk.Frame(dialog)
    time_frame.pack(pady=5)

    ttk.Label(time_frame, text="冷却时间：", font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(0, 8))
    hours_var = tk.IntVar(value=app.settings.get("cooldown_hours", 8))
    minutes_var = tk.IntVar(value=0)
    hours_spin = ttk.Spinbox(time_frame, from_=0, to=72, textvariable=hours_var, width=5, font=('Microsoft YaHei UI', 11))
    hours_spin.pack(side=tk.LEFT, padx=(0, 4))
    ttk.Label(time_frame, text="小时", font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(0, 12))
    minutes_spin = ttk.Spinbox(time_frame, from_=0, to=59, increment=5, textvariable=minutes_var, width=5, font=('Microsoft YaHei UI', 11))
    minutes_spin.pack(side=tk.LEFT, padx=(0, 4))
    ttk.Label(time_frame, text="分钟", font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT)

    def confirm():
        hours = hours_var.get()
        minutes = minutes_var.get()
        if hours <= 0 and minutes <= 0:
            messagebox.showwarning("提示", "冷却时间不能为 0", parent=dialog)
            return
        total_hours = hours + minutes / 60.0
        cooldown_manager.record_run(account_name, total_hours)
        refresh_account_tree(app)
        _, new_next = cooldown_manager.is_cooling_down(account_name)
        time_text = f"{hours}小时" if minutes == 0 else f"{hours}小时{minutes}分钟" if hours > 0 else f"{minutes}分钟"
        messagebox.showinfo("已设置", f"「{account_name}」冷却 {time_text}。\n下次运行：{new_next or '未知'}", parent=dialog)
        dialog.destroy()

    ttk.Button(dialog, text="确认", command=confirm).pack(pady=15)


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


# ---------- 冷却查看 ----------
def show_cooldown_window(app):
    """弹出冷却状态查看窗口"""
    win = tk.Toplevel(app.root)
    win.title("账号冷却状态")
    win.resizable(True, True)
    win.minsize(500, 350)
    win.transient(app.root)
    win.grab_set()
    utils.set_window_icon(win)
    utils.bind_window_geometry(win, "cooldown_window_geometry", "700x480", (500, 350))
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
        dialog.resizable(True, True)
        dialog.minsize(300, 150)
        dialog.transient(win)
        dialog.grab_set()
        utils.set_window_icon(dialog)
        utils.bind_window_geometry(dialog, "custom_cooldown_geometry", "350x180", (300, 150))

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
    win.minsize(350, 300)
    win.resizable(True, True)
    win.transient(app.root)
    win.grab_set()

    # 设置图标
    utils.set_window_icon(win)

    # 恢复窗口大小 + 关闭时自动保存
    utils.bind_window_geometry(win, "asset_history_geometry", "420x400", (350, 300))

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
    # 建立 tree item -> history index 的映射
    item_to_history_idx = {}
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
        item_id = tree.insert("", tk.END, values=(time_str, value, diff_str))
        item_to_history_idx[item_id] = i

    # 双击编辑资产值
    def _on_double_click(event):
        region = tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = tree.identify_column(event.x)
        row_id = tree.identify_row(event.y)
        if not row_id or column != "#2":  # 只允许编辑第2列（资产）
            return

        hist_idx = item_to_history_idx.get(row_id)
        if hist_idx is None:
            return

        bbox = tree.bbox(row_id, column)
        if not bbox:
            return
        x, y, w, h = bbox
        current_val = tree.item(row_id, "values")[1]

        entry_widget = ttk.Entry(tree, width=10)
        entry_widget.insert(0, current_val)
        entry_widget.select_range(0, tk.END)
        entry_widget.place(x=x, y=y, width=w, height=h)
        entry_widget.focus_set()

        def _confirm(e=None):
            new_val = entry_widget.get().strip()
            entry_widget.destroy()
            if not new_val or new_val == current_val:
                return
            # 更新内存中的历史记录
            history[hist_idx]["value"] = new_val
            # 更新 SQLite
            raw_time = history[hist_idx].get("time", "")
            asset_db.update_asset_record(account_name, raw_time, new_val)
            # 更新当前资产为最新值（history 末尾）
            app._account_assets[account_name] = history[-1].get("value", "0")
            # 刷新弹窗列表
            _refresh_tree()
            # 刷新主界面账号列表
            refresh_account_tree(app)
            # 刷新资产监测窗口（如果打开）
            if hasattr(app, '_asset_monitor_refresh') and app._asset_monitor_refresh:
                try:
                    app._asset_monitor_refresh()
                except Exception:
                    pass

        def _refresh_tree():
            tree.delete(*tree.get_children())
            item_to_history_idx.clear()
            for i in range(len(history) - 1, -1, -1):
                entry = history[i]
                t = _strip_year(entry.get("time", ""))
                v = entry.get("value", "0")
                if i > 0:
                    pv = _parse_asset_value(history[i - 1].get("value", "0"))
                    cv = _parse_asset_value(v)
                    d = cv - pv
                    if d > 0:
                        ds = f"+{_format_asset_num(d)}"
                    elif d < 0:
                        ds = f"{_format_asset_num(d)}"
                    else:
                        ds = "—"
                else:
                    ds = "—"
                iid = tree.insert("", tk.END, values=(t, v, ds))
                item_to_history_idx[iid] = i

        entry_widget.bind("<Return>", _confirm)
        entry_widget.bind("<FocusOut>", _confirm)

    tree.bind("<Double-1>", _on_double_click)

    # 底部区域：统计信息 + 清除按钮
    bottom_frame = ttk.Frame(win)
    bottom_frame.pack(fill=tk.X, padx=15, pady=(0, 10))

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
        ttk.Label(bottom_frame, text=f"共 {len(history)} 条记录  |  {trend}",
                  font=('Microsoft YaHei UI', 9), foreground=color).pack(side=tk.LEFT)
    else:
        ttk.Label(bottom_frame, text=f"共 {len(history)} 条记录",
                  font=('Microsoft YaHei UI', 9), foreground='#888').pack(side=tk.LEFT)

    # 清除记录资产按钮
    def _clear_asset_records():
        if not messagebox.askyesno("确认清除",
                f"确定要清空账号「{account_name}」的所有资产记录吗？\n\n"
                f"此操作不可撤销，主页的现有资产也会清零。",
                parent=win):
            return
        # 清空 SQLite 中的资产记录
        try:
            asset_db.delete_account_records(account_name)
        except Exception as e:
            print(f"⚠️ 清除资产记录失败: {e}")
        # 清空内存中的资产数据
        app._account_assets[account_name] = "0"
        app._asset_history[account_name] = []
        # 立即保存账号文件，防止重启后旧数据重新出现
        save_accounts(app)
        # 刷新主界面账号列表
        refresh_account_tree(app)
        # 刷新资产监测窗口（如果打开）
        if hasattr(app, '_asset_monitor_refresh') and app._asset_monitor_refresh:
            try:
                app._asset_monitor_refresh()
            except Exception:
                pass
        print(f"✅ 已清空账号 {account_name} 的资产记录")
        messagebox.showinfo("已清除", f"账号「{account_name}」的资产记录已清空。", parent=win)
        win.destroy()

    ttk.Button(bottom_frame, text="清除记录资产", style='Danger.TButton',
               command=_clear_asset_records, width=14).pack(side=tk.RIGHT)


def _format_asset_num(val):
    """代理到 utils.format_asset_num"""
    return utils.format_asset_num(val)


def show_asset_monitor(app):
    """弹出资产监测窗口：上半部分显示所有账号当前资产，下半部分按时间段统计变化"""
    win = tk.Toplevel(app.root)
    win.title("资产监测")
    win.resizable(True, True)
    win.minsize(200, 200)
    win.transient(app.root)
    win.grab_set()

    # 设置图标
    utils.set_window_icon(win)

    # 恢复窗口大小
    utils.restore_window_geometry(win, "asset_monitor_geometry", "400x400", (200, 200))

    # ===== 上半部分：当前状态 =====
    status_frame = ttk.LabelFrame(win, text=" 当前资产状态 ", padding=10)
    status_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

    tree_frame = ttk.Frame(status_frame)
    tree_frame.pack(fill=tk.BOTH, expand=True)

    columns = ("account", "asset", "ratio", "coin_value")
    asset_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=6)
    asset_tree.heading("account", text="账号名称")
    asset_tree.heading("asset", text="现有资产")
    asset_tree.heading("ratio", text="转换比例")
    asset_tree.heading("coin_value", text="纯币价值")
    asset_tree.column("account", width=80, minwidth=50)
    asset_tree.column("asset", width=50, minwidth=30, anchor=tk.CENTER)
    asset_tree.column("ratio", width=50, minwidth=30, anchor=tk.CENTER)
    asset_tree.column("coin_value", width=60, minwidth=40, anchor=tk.CENTER)

    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=asset_tree.yview)
    asset_tree.configure(yscrollcommand=scrollbar.set)
    asset_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

    # 每个账号的转换比例（默认45）
    settings = config.load_settings()
    account_ratios = settings.get("asset_conversion_ratios", {})

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
            ratio = account_ratios.get(name, 45)
            # 计算纯币价值：现有资产(万) / 转换比例
            # 资产单位是K，1万 = 10K，所以先 /10000 转换成万
            try:
                asset_num = utils.parse_asset_value(asset_value)
                asset_wan = asset_num / 10000
                coin_val = asset_wan / ratio if ratio > 0 else 0
                coin_str = f"{coin_val:.2f}"
            except Exception:
                coin_str = "-"
            asset_tree.insert("", tk.END, values=(display_name, asset_value, ratio, coin_str))

    # 双击转换比例列直接在单元格上编辑
    def _on_ratio_double_click(event):
        col = asset_tree.identify_column(event.x)
        if col != "#3":  # 只响应"转换比例"列
            return
        row_id = asset_tree.identify_row(event.y)
        if not row_id:
            return
        idx = asset_tree.index(row_id)
        if idx >= len(app.qq_account_images):
            return

        # 获取单元格位置
        bbox = asset_tree.bbox(row_id, column="#3")
        if not bbox:
            return
        x, y, w, h = bbox

        # 获取当前值
        name = _account_key_from_path(app.qq_account_images[idx])
        old_ratio = account_ratios.get(name, 45)

        # 在单元格上创建输入框
        entry = tk.Entry(asset_tree, font=('Microsoft YaHei UI', 9), justify='center')
        entry.place(x=x, y=y, width=w, height=h)
        entry.insert(0, str(old_ratio))
        entry.select_range(0, tk.END)
        entry.focus_set()

        def _commit(event=None):
            try:
                new_ratio = int(entry.get())
                if new_ratio < 1:
                    new_ratio = 1
            except ValueError:
                new_ratio = old_ratio
            account_ratios[name] = new_ratio
            settings["asset_conversion_ratios"] = account_ratios
            config.save_settings(settings)
            entry.destroy()
            _refresh_status()

        def _cancel(event=None):
            entry.destroy()

        entry.bind("<Return>", _commit)
        entry.bind("<KP_Enter>", _commit)
        entry.bind("<Escape>", _cancel)
        entry.bind("<FocusOut>", _commit)

    asset_tree.bind("<Double-1>", _on_ratio_double_click)

    # 转换比例说明
    ttk.Label(status_frame, text="提示：双击「转换比例」列可直接修改比例，回车确认，Esc 取消",
              font=('Microsoft YaHei UI', 8), foreground='#999').pack(anchor=tk.W, pady=(4, 0))

    # 延迟加载资产数据，避免阻塞窗口打开
    win.after(50, _refresh_status)

    # 注册刷新回调，供资产记录编辑后自动更新（上半部分+下半部分统计）
    def _refresh_all():
        _refresh_status()
        if hasattr(app, '_asset_monitor_refresh_stats') and app._asset_monitor_refresh_stats:
            try:
                app._asset_monitor_refresh_stats()
            except Exception:
                pass
    app._asset_monitor_refresh = _refresh_all
    def _on_monitor_close():
        utils.save_window_geometry(win, "asset_monitor_geometry")
        app._asset_monitor_refresh = None
        app._asset_monitor_refresh_stats = None
        win.destroy()
    win.protocol("WM_DELETE_WINDOW", _on_monitor_close)

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

    # 注册统计刷新回调，供资产记录编辑后自动更新统计面板
    app._asset_monitor_refresh_stats = lambda: _show_stats(days_var.get())


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
