"""
自定义操作向导窗口
从「设置 → 自动任务」页「配置自定义操作」打开：配置"找图→单击"步骤序列，供主流程完成后自动执行。
- 顶部工具栏：＋屏幕框选、选择图片、上移、下移、删除
- 选项行：主流程完成后自动执行、点击受随机偏移影响
- 步骤列表（Treeview）：序号 / 名称 / 置信度 / 超时(s) / 点击后停顿(s)
- 双击步骤可编辑名称和参数（含图片预览）
- 底部：左下角运行测试/停止，右下角保存步骤
"""
import os
import time
import shutil
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import config
import utils
import custom_ops

# 步骤类型：key → 中文名
STEP_TYPES = {
    "image": "找图点击",
    "coordinate": "坐标点击",
    "ocr": "OCR点击",
    "keyboard": "键盘输入",
    "multi_image": "多图点击",
    "drag": "鼠标拖拽",
    "scroll": "鼠标滚轮",
    "condition": "条件跳转",
    "jump": "跳转",
}
NAME_TO_TYPE = {v: k for k, v in STEP_TYPES.items()}   # 中文名 → key
TYPE_NAMES = list(STEP_TYPES.values())                 # 中文名列表（下拉显示用）


class CustomOpsWindow:
    def __init__(self, parent, app):
        self.app = app
        self.parent_win = parent          # 设置窗口
        self.ops = custom_ops.load_ops()  # [{name, image, confidence, timeout, pause_after}, ...]
        self._test_stop = threading.Event()
        self._test_thread = None

        self.win = tk.Toplevel(parent)
        self.win.title("自定义操作")
        self.win.resizable(True, True)
        self.win.minsize(560, 420)
        # 注意：不加 transient —— 父窗口（设置窗口）已被导航栈隐藏，transient 到隐藏窗口可能不映射
        self.win.grab_set()   # 模态：阻止操作背后的实验功能/设置窗口
        self.win.lift()
        utils.set_window_icon(self.win)

        self._build_ui()
        self._refresh_list()

    # ==================== UI 构建 ====================
    def _build_ui(self):
        # ----- 顶部工具栏 -----
        toolbar = ttk.Frame(self.win, padding=(8, 8, 8, 4))
        toolbar.pack(fill=tk.X)
        add_btn = ttk.Menubutton(toolbar, text="＋ 添加步骤", style='Accent.TButton')
        add_menu = tk.Menu(add_btn, tearoff=0)
        add_menu.add_command(label="找图点击（框选截图）", command=self._capture_from_screen)
        add_menu.add_command(label="找图点击（导入图片）", command=self._add_step_from_file)
        add_menu.add_separator()
        add_menu.add_command(label="坐标点击", command=self._add_coordinate_step)
        add_menu.add_command(label="OCR点击", command=self._add_ocr_step)
        add_menu.add_command(label="键盘输入", command=self._add_keyboard_step)
        add_menu.add_command(label="多图点击", command=self._add_multi_image_step)
        add_menu.add_command(label="鼠标拖拽", command=self._add_drag_step)
        add_menu.add_command(label="鼠标滚轮", command=self._add_scroll_step)
        add_menu.add_separator()
        add_menu.add_command(label="条件跳转", command=self._add_condition_step)
        add_menu.add_command(label="跳转", command=self._add_jump_step)
        add_btn.config(menu=add_menu)
        add_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Button(toolbar, text="上移", style='TButton',
                   command=self._move_up, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="下移", style='TButton',
                   command=self._move_down, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="删除", style='TButton',
                   command=self._delete_step, width=5).pack(side=tk.LEFT)

        # ----- 步骤列表 -----
        list_frame = ttk.Frame(self.win, padding=(8, 2))
        list_frame.pack(fill=tk.BOTH, expand=True)
        cols = ("seq", "type", "name", "param", "pause")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8)
        self.tree.heading("seq", text="序号")
        self.tree.heading("type", text="类型")
        self.tree.heading("name", text="名称")
        self.tree.heading("param", text="参数")
        self.tree.heading("pause", text="停顿(s)")
        self.tree.column("seq", width=32, anchor=tk.CENTER, stretch=False)
        self.tree.column("type", width=72, anchor=tk.CENTER)
        self.tree.column("name", width=150)
        self.tree.column("param", width=190)
        self.tree.column("pause", width=64, anchor=tk.CENTER)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())
        self.tree.bind("<Delete>", lambda e: self._delete_step())
        self.tree.bind("<Button-3>", self._show_context_menu)

        # ----- 说明 -----
        tip = ("说明：支持三种步骤——找图点击（匹配图片）/ 坐标点击（固定位置）/ OCR点击（识别文字）。\n"
               "主流程每个账号运行完、游戏回到主界面后，会依次执行这些步骤；"
               "某一步找不到目标则中止该账号的自定义操作，跳到下一个账号。\n"
               "双击或右键可修改步骤属性（含类型）。")
        ttk.Label(self.win, text=tip, style='SettingsSmall.TLabel', justify=tk.LEFT,
                  padding=(10, 4)).pack(anchor=tk.W, fill=tk.X)

        # ----- 底部操作栏：运行测试/停止（左下角）+ 保存步骤（右下角） -----
        bottom = ttk.Frame(self.win, padding=(8, 2, 8, 8))
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="▶ 运行测试", style='TButton',
                   command=self._run_test, width=9).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bottom, text="⏹ 停止", style='TButton',
                   command=self._stop_test, width=7).pack(side=tk.LEFT)
        ttk.Button(bottom, text="保存步骤", style='Accent.TButton',
                   command=self._save_ops_now, width=10).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="设置", style='TButton',
                   command=self._open_settings, width=8).pack(side=tk.RIGHT, padx=(0, 4))

        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    # ==================== 步骤列表操作 ====================
    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(self.ops):
            return idx
        return None

    def _step_param(self, op):
        """生成步骤参数摘要（用于列表显示）"""
        t = op.get("type", "image")
        if t == "coordinate":
            return f"({op.get('x', 0)}, {op.get('y', 0)})"
        if t == "ocr":
            return f"「{op.get('text', '')}」  conf={op.get('confidence', 0.6)}"
        if t == "keyboard":
            mode = "按键" if op.get("key_mode", "key") != "text" else "文本"
            return f"{mode}: {op.get('keys', '')}"
        if t == "multi_image":
            return f"{len(op.get('images', []) or [])} 张图  conf={op.get('confidence', 0.7)}"
        if t == "drag":
            return f"({op.get('x1', 0)},{op.get('y1', 0)})→({op.get('x2', 0)},{op.get('y2', 0)})"
        if t == "scroll":
            return f"{op.get('scroll_amount', 3)} 格"
        if t == "condition":
            cond = op.get("cond_type", "image")
            if cond == "ocr":
                return f"OCR「{op.get('text', '')}」 满足→第{op.get('jump_to', 1)}步"
            return f"找图 满足→第{op.get('jump_to', 1)}步"
        if t == "jump":
            return f"→ 第 {op.get('jump_to', 1)} 步"
        return f"conf={op.get('confidence', 0.7)}  超时={op.get('timeout', 5)}s"

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for i, op in enumerate(self.ops):
            t = op.get("type", "image")
            self.tree.insert("", tk.END, iid=str(i), values=(
                i + 1,
                STEP_TYPES.get(t, t),
                op.get("name", f"步骤{i+1}"),
                self._step_param(op),
                op.get("pause_after", 0.5)))

    def _move_up(self):
        idx = self._selected_index()
        if idx is None or idx == 0:
            return
        self.ops[idx - 1], self.ops[idx] = self.ops[idx], self.ops[idx - 1]
        self._save_ops_now()
        self._refresh_list()
        self.tree.selection_set(str(idx - 1))

    def _move_down(self):
        idx = self._selected_index()
        if idx is None or idx >= len(self.ops) - 1:
            return
        self.ops[idx + 1], self.ops[idx] = self.ops[idx], self.ops[idx + 1]
        self._save_ops_now()
        self._refresh_list()
        self.tree.selection_set(str(idx + 1))

    def _delete_step(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选中一个步骤", parent=self.win)
            return
        op = self.ops[idx]
        if not messagebox.askyesno("删除步骤", f"确定删除步骤「{op.get('name','')}」？",
                                   parent=self.win):
            return
        try:
            img = custom_ops.image_path(op.get("image", ""))
            if os.path.exists(img):
                os.remove(img)
        except Exception:
            pass
        self.ops.pop(idx)
        self._save_ops_now()
        self._refresh_list()

    def _show_context_menu(self, event):
        """右键菜单：修改属性 / 排序 / 删除 / 切换类型"""
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        idx = int(row)
        op = self.ops[idx]
        t = op.get("type", "image")
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label="✏️ 修改属性", command=self._edit_selected)
        menu.add_separator()
        menu.add_command(label="上移", command=self._move_up)
        menu.add_command(label="下移", command=self._move_down)
        menu.add_separator()
        menu.add_command(label="删除步骤", command=self._delete_step)
        menu.add_separator()
        for st, st_name in STEP_TYPES.items():
            menu.add_command(
                label=f"✅ 设为{st_name}",
                command=lambda s=st: self._set_step_type(s),
                state='normal' if t != st else 'disabled')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _set_step_type(self, new_type):
        """把选中步骤改为指定类型，并打开编辑窗口"""
        idx = self._selected_index()
        if idx is None:
            return
        op = self.ops[idx]
        t = op.get("type", "image")
        if t == new_type:
            self._edit_selected()
            return
        op["type"] = new_type
        if new_type == "coordinate":
            op.setdefault("x", 0)
            op.setdefault("y", 0)
        elif new_type == "ocr":
            op.setdefault("text", "")
            op.setdefault("confidence", 0.6)
            op.setdefault("timeout", 5)
        elif new_type == "keyboard":
            op.setdefault("keys", "")
            op.setdefault("key_mode", "key")
        elif new_type == "multi_image":
            op.setdefault("images", [])
            op.setdefault("confidence", 0.7)
            op.setdefault("timeout", 2)
        elif new_type == "drag":
            for k in ("x1", "y1", "x2", "y2"):
                op.setdefault(k, 0)
            op.setdefault("duration", 0.5)
        elif new_type == "scroll":
            op.setdefault("scroll_amount", 3)
        elif new_type == "condition":
            op.setdefault("cond_type", "image")
            op.setdefault("text", "")
            op.setdefault("confidence", 0.7)
            op.setdefault("timeout", 3)
            op.setdefault("jump_to", 1)
        elif new_type == "jump":
            op.setdefault("jump_to", 1)
        else:  # image
            if not op.get("image"):
                messagebox.showinfo("提示",
                                    "找图点击需要图片，请先用「＋ 屏幕框选」或「选择图片」添加步骤",
                                    parent=self.win)
                return
            op.setdefault("confidence", 0.7)
            op.setdefault("timeout", 5)
        self._save_ops_now()
        self._refresh_list()
        self.tree.selection_set(str(idx))
        self._edit_selected()

    def _save_ops_now(self):
        if custom_ops.save_ops(self.ops):
            print("💾 自定义操作步骤已保存")

    def _open_settings(self):
        """打开自定义操作设置窗口（主流程后执行 / 随机偏移 / 频率限制）"""
        dlg = tk.Toplevel(self.win)
        dlg.title("自定义操作设置")
        dlg.resizable(False, False)
        dlg.transient(self.win)
        dlg.grab_set()
        form = ttk.Frame(dlg, padding=14)
        form.pack(fill=tk.BOTH, expand=True)

        enable_var = tk.BooleanVar(value=bool(self.app.settings.get("enable_custom_ops", False)))
        ttk.Checkbutton(form, text="主流程完成后自动执行自定义操作",
                        variable=enable_var).pack(anchor='w', pady=3)
        jitter_var = tk.BooleanVar(value=bool(self.app.settings.get("custom_ops_jitter", False)))
        ttk.Checkbutton(form, text="点击受随机偏移影响",
                        variable=jitter_var).pack(anchor='w', pady=3)

        # 频率限制：每个账号 Y 天内最多运行 X 次自定义操作
        freq = ttk.Frame(form)
        freq.pack(fill=tk.X, pady=(10, 3))
        runs_var = tk.StringVar(value=str(self.app.settings.get("custom_ops_max_runs", 0)))
        days_var = tk.StringVar(value=str(self.app.settings.get("custom_ops_freq_days", 7)))
        ttk.Label(freq, text="每个账号").pack(side=tk.LEFT)
        ttk.Spinbox(freq, from_=0, to=99, textvariable=runs_var, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Label(freq, text="天内最多运行").pack(side=tk.LEFT)
        ttk.Spinbox(freq, from_=1, to=365, textvariable=days_var, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Label(freq, text="次自定义操作（0=不限）").pack(side=tk.LEFT)
        ttk.Label(form, text="超限后该账号跳过自定义操作，主流程照常运行",
                  foreground='#7f8c8d').pack(anchor='w')

        def on_save():
            try:
                self.app.settings["enable_custom_ops"] = enable_var.get()
                self.app.settings["custom_ops_jitter"] = jitter_var.get()
                self.app.settings["custom_ops_max_runs"] = max(0, int(runs_var.get()))
                self.app.settings["custom_ops_freq_days"] = max(1, int(days_var.get()))
                config.save_settings(self.app.settings)
                print(f"📌 自定义操作设置已保存：自动执行={'开' if enable_var.get() else '关'}，"
                      f"抖动={'开' if jitter_var.get() else '关'}，"
                      f"频率={runs_var.get()}次/{days_var.get()}天")
            except ValueError:
                messagebox.showwarning("输入无效", "次数/天数必须为数字", parent=dlg)
                return
            dlg.destroy()

        btns = ttk.Frame(form)
        btns.pack(pady=(12, 0))
        ttk.Button(btns, text="保存", style='Accent.TButton',
                   command=on_save, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="取消", style='TButton',
                   command=dlg.destroy, width=8).pack(side=tk.LEFT)

        # 居中显示
        dlg.update_idletasks()
        try:
            pw = self.win.winfo_width()
            ph = self.win.winfo_height()
            px = self.win.winfo_rootx()
            py = self.win.winfo_rooty()
            x = max(0, px + (pw - dlg.winfo_width()) // 2)
            y = max(0, py + (ph - dlg.winfo_height()) // 2)
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ==================== 添加步骤 ====================
    def _capture_from_screen(self):
        """隐藏窗口，全屏框选截图，作为找图步骤"""
        self._capture_region_and(self._add_step_from_region)

    def _capture_region_and(self, callback, dlg=None):
        """隐藏窗口（及可选编辑框）→ 全屏框选截图 → 用 region 回调处理 → 恢复"""
        try:
            import gui_app
            gui_app.hide_log_overlay()   # 临时隐藏日志遮罩，避免挡住框选
        except Exception:
            pass
        # 先释放所有模态抓取，避免遮罩收不到点击
        try:
            if dlg and dlg.winfo_exists():
                dlg.grab_release()
        except Exception:
            pass
        try:
            self.win.grab_release()
        except Exception:
            pass
        self.win.withdraw()
        try:
            if dlg and dlg.winfo_exists():
                dlg.withdraw()
        except Exception:
            pass
        self.win.after(300, lambda: self._show_capture_overlay(callback, dlg))

    def _show_capture_overlay(self, callback, dlg=None):
        """全屏拖拽框选：结果交给 callback(region)"""
        overlay = tk.Toplevel(self.win)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-alpha', 0.3)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='black')
        overlay.config(cursor="crosshair")
        canvas = tk.Canvas(overlay, highlightthickness=0, bg='black')
        canvas.pack(fill=tk.BOTH, expand=True)
        hint = tk.Label(overlay, text="拖动鼠标框选要点击的图标/按钮区域，按 Esc 取消",
                        font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
        hint.place(relx=0.5, rely=0.05, anchor='center')

        rect_id = None
        start_x = start_y = 0
        result = None

        def on_press(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y,
                                              outline='red', width=2)

        def on_drag(event):
            if rect_id:
                canvas.coords(rect_id, start_x, start_y, event.x, event.y)

        def on_release(event):
            nonlocal result
            x1, y1 = min(start_x, event.x), min(start_y, event.y)
            x2, y2 = max(start_x, event.x), max(start_y, event.y)
            if x2 - x1 > 5 and y2 - y1 > 5:
                result = (x1, y1, x2, y2)
            overlay.destroy()

        def on_escape(event):
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        hint.bind("<ButtonPress-1>", on_press)   # 提示文字上也能开始框选
        canvas.bind("<Escape>", on_escape)
        overlay.bind("<Escape>", on_escape)
        overlay.focus_force()
        try:
            overlay.grab_set()   # 强制抓取输入，点击一定到达遮罩
        except Exception:
            pass

        self.win.wait_window(overlay)
        self.win.deiconify()
        self.win.grab_set()   # 重新获取模态
        try:
            if dlg and dlg.winfo_exists():
                dlg.deiconify()
                dlg.grab_set()
        except Exception:
            pass
        try:
            import gui_app
            gui_app.show_log_overlay()   # 恢复日志遮罩
        except Exception:
            pass

        if result:
            callback(result)

    def _add_step_from_region(self, region):
        x1, y1, x2, y2 = region
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
        except Exception as e:
            messagebox.showerror("截图失败", f"截取屏幕区域失败：{e}", parent=self.win)
            return
        filename = custom_ops.next_image_name()
        if not custom_ops.save_captured_image(img, filename):
            return
        self._append_step({"type": "image", "image": filename,
                           "confidence": float(self.app.settings.get("custom_ops_confidence", 0.7)),
                           "timeout": float(self.app.settings.get("custom_ops_timeout", 5))})

    def _add_step_from_file(self):
        path = filedialog.askopenfilename(
            parent=self.win, title="选择步骤图片",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        if not path:
            return
        filename = custom_ops.next_image_name()
        try:
            shutil.copy2(path, custom_ops.image_path(filename))
        except Exception as e:
            messagebox.showerror("导入失败", f"复制图片失败：{e}", parent=self.win)
            return
        self._append_step({"type": "image", "image": filename,
                           "confidence": float(self.app.settings.get("custom_ops_confidence", 0.7)),
                           "timeout": float(self.app.settings.get("custom_ops_timeout", 5))})

    def _append_step(self, step):
        """追加一个步骤（支持不同 type），并立即打开编辑窗口"""
        step.setdefault("pause_after", float(self.app.settings.get("custom_ops_pause", 0.5)))
        # 默认名称 = 类型中文名 + 同类型序号（如 坐标点击1、坐标点击2）
        if not step.get("name"):
            t = step.get("type", "image")
            type_name = STEP_TYPES.get(t, t)
            same_type_count = sum(1 for o in self.ops if o.get("type", "image") == t)
            step["name"] = f"{type_name}{same_type_count + 1}"
        self.ops.append(step)
        self._save_ops_now()
        self._refresh_list()
        self.tree.selection_set(str(len(self.ops) - 1))
        self._edit_selected()

    def _add_coordinate_step(self):
        """添加坐标点击步骤"""
        self._append_step({"type": "coordinate", "x": 0, "y": 0})

    def _add_ocr_step(self):
        """添加 OCR 文字识别点击步骤"""
        self._append_step({"type": "ocr", "text": "",
                           "confidence": 0.6,
                           "timeout": float(self.app.settings.get("custom_ops_timeout", 5))})

    def _add_keyboard_step(self):
        """添加键盘输入步骤"""
        self._append_step({"type": "keyboard", "keys": "", "key_mode": "key"})

    def _add_multi_image_step(self):
        """添加多图匹配点击步骤"""
        self._append_step({"type": "multi_image", "images": [],
                           "confidence": 0.7, "timeout": 2})

    def _add_drag_step(self):
        """添加鼠标拖拽步骤"""
        self._append_step({"type": "drag", "x1": 0, "y1": 0, "x2": 0, "y2": 0,
                           "duration": 0.5})

    def _add_scroll_step(self):
        """添加鼠标滚轮步骤"""
        self._append_step({"type": "scroll", "scroll_amount": 3})

    def _add_condition_step(self):
        """添加条件跳转步骤"""
        self._append_step({"type": "condition", "cond_type": "image",
                           "image": "", "text": "",
                           "confidence": 0.7, "timeout": 3, "jump_to": 1})

    def _add_jump_step(self):
        """添加无条件跳转步骤"""
        self._append_step({"type": "jump", "jump_to": 1})

    # ==================== 编辑步骤 ====================
    def _edit_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        op = self.ops[idx]

        dlg = tk.Toplevel(self.win)
        dlg.title("编辑步骤")
        dlg.resizable(False, False)
        dlg.transient(self.win)
        dlg.grab_set()

        form = ttk.Frame(dlg, padding=12)
        form.pack(fill=tk.BOTH, expand=True)

        # 类型切换（下拉显示中文，内部存 key）
        type_var = tk.StringVar(value=STEP_TYPES.get(op.get("type", "image"), "找图点击"))
        tr = ttk.Frame(form)
        tr.pack(fill=tk.X, pady=3)
        ttk.Label(tr, text="类型", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
        type_combo = ttk.Combobox(tr, textvariable=type_var,
                                  values=TYPE_NAMES, state='readonly', width=12)
        type_combo.pack(side=tk.LEFT)

        name_var = tk.StringVar(value=op.get("name", f"步骤{idx + 1}"))
        pause_var = tk.StringVar(value=str(op.get("pause_after", 0.5)))

        # 各类型字段变量
        conf_var = tk.StringVar(value=str(op.get("confidence", 0.7)))
        timeout_var = tk.StringVar(value=str(op.get("timeout", 5)))
        x_var = tk.StringVar(value=str(op.get("x", 0)))
        y_var = tk.StringVar(value=str(op.get("y", 0)))
        text_var = tk.StringVar(value=op.get("text", ""))
        keys_var = tk.StringVar(value=op.get("keys", ""))
        key_mode_var = tk.StringVar(value=op.get("key_mode", "key"))
        x1_var = tk.StringVar(value=str(op.get("x1", 0)))
        y1_var = tk.StringVar(value=str(op.get("y1", 0)))
        x2_var = tk.StringVar(value=str(op.get("x2", 0)))
        y2_var = tk.StringVar(value=str(op.get("y2", 0)))
        duration_var = tk.StringVar(value=str(op.get("duration", 0.5)))
        scroll_var = tk.StringVar(value=str(op.get("scroll_amount", 3)))
        cond_type_var = tk.StringVar(value=op.get("cond_type", "image"))
        jump_var = tk.StringVar(value=str(op.get("jump_to", 1)))
        mi_images = list(op.get("images", []) or [])
        cond_img = op.get("image", "")
        img_name = op.get("image", "")   # 找图步骤的当前图片

        def _row(lbl, var, width=16):
            r = ttk.Frame(form)
            r.pack(fill=tk.X, pady=3)
            ttk.Label(r, text=lbl, style='Settings.TLabel', width=10).pack(side=tk.LEFT)
            ttk.Entry(r, textvariable=var, width=width).pack(side=tk.LEFT)
            return r

        _row("名称", name_var, 20)

        # 动态字段区（随类型切换）
        fields = ttk.Frame(form)
        fields.pack(fill=tk.X)

        def _rebuild_fields():
            for w in fields.winfo_children():
                w.destroy()
            t = NAME_TO_TYPE.get(type_var.get(), type_var.get())   # 中文名 → key
            if t == "coordinate":
                fx = ttk.Frame(fields); fx.pack(fill=tk.X, pady=3)
                ttk.Label(fx, text="X", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(fx, textvariable=x_var, width=8).pack(side=tk.LEFT)
                ttk.Button(fx, text="屏幕取点", style='TButton',
                           command=lambda: self._pick_point(x_var, y_var, dlg)).pack(side=tk.LEFT, padx=(10, 0))
                fy = ttk.Frame(fields); fy.pack(fill=tk.X, pady=3)
                ttk.Label(fy, text="Y", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(fy, textvariable=y_var, width=8).pack(side=tk.LEFT)
            elif t == "ocr":
                _row_in = ttk.Frame(fields)
                _row_in.pack(fill=tk.X, pady=3)
                ttk.Label(_row_in, text="文字", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(_row_in, textvariable=text_var, width=20).pack(side=tk.LEFT)
                cr = ttk.Frame(fields); cr.pack(fill=tk.X, pady=3)
                ttk.Label(cr, text="置信度", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(cr, textvariable=conf_var, width=6).pack(side=tk.LEFT)
                ttk.Label(cr, text="超时(秒)", width=8).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Entry(cr, textvariable=timeout_var, width=6).pack(side=tk.LEFT)
            elif t == "keyboard":
                fr = ttk.Frame(fields); fr.pack(fill=tk.X, pady=3)
                ttk.Label(fr, text="内容", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(fr, textvariable=keys_var, width=20).pack(side=tk.LEFT)
                ttk.Label(fr, text="方式", width=6).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Combobox(fr, textvariable=key_mode_var, values=['key', 'text'],
                             state='readonly', width=6).pack(side=tk.LEFT)
                ttk.Label(fields, text="key=按键/组合键（如 Enter、ctrl+a）；text=输入文本",
                          foreground='#7f8c8d').pack(anchor='w')
            elif t == "multi_image":
                ml = tk.Listbox(fields, height=4)
                ml.pack(fill=tk.X)
                def _refresh_mi():
                    ml.delete(0, tk.END)
                    for f in mi_images:
                        ml.insert(tk.END, f)
                _refresh_mi()
                mb = ttk.Frame(fields); mb.pack(fill=tk.X, pady=3)
                def _add_mi_capture():
                    def _on_region(region):
                        x1, y1, x2, y2 = region
                        try:
                            from PIL import ImageGrab
                            im = ImageGrab.grab(bbox=(x1, y1, x2, y2))
                        except Exception as e:
                            messagebox.showerror("截图失败", str(e), parent=dlg)
                            return
                        fn = custom_ops.next_image_name()
                        if custom_ops.save_captured_image(im, fn):
                            mi_images.append(fn)
                            _refresh_mi()
                    self._capture_region_and(_on_region, dlg)
                def _add_mi_file():
                    path = filedialog.askopenfilename(
                        parent=dlg, title="选择图片",
                        filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有", "*.*")])
                    if path:
                        fn = custom_ops.next_image_name()
                        try:
                            shutil.copy2(path, custom_ops.image_path(fn))
                        except Exception as e:
                            messagebox.showerror("导入失败", str(e), parent=dlg)
                            return
                        mi_images.append(fn)
                        _refresh_mi()
                def _del_mi():
                    sel = ml.curselection()
                    if sel:
                        mi_images.pop(sel[0])
                        _refresh_mi()
                ttk.Button(mb, text="屏幕框选添加", command=_add_mi_capture).pack(side=tk.LEFT, padx=(0, 4))
                ttk.Button(mb, text="选文件添加", command=_add_mi_file).pack(side=tk.LEFT, padx=(0, 4))
                ttk.Button(mb, text="删除选中", command=_del_mi).pack(side=tk.LEFT)
                cr = ttk.Frame(fields); cr.pack(fill=tk.X, pady=3)
                ttk.Label(cr, text="置信度", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(cr, textvariable=conf_var, width=6).pack(side=tk.LEFT)
                ttk.Label(cr, text="超时(秒)", width=8).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Entry(cr, textvariable=timeout_var, width=6).pack(side=tk.LEFT)
            elif t == "drag":
                for lbl, var in (("X1", x1_var), ("Y1", y1_var), ("X2", x2_var), ("Y2", y2_var)):
                    fr = ttk.Frame(fields); fr.pack(fill=tk.X, pady=3)
                    ttk.Label(fr, text=lbl, style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                    ttk.Entry(fr, textvariable=var, width=8).pack(side=tk.LEFT)
                fr = ttk.Frame(fields); fr.pack(fill=tk.X, pady=3)
                ttk.Label(fr, text="时长(s)", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(fr, textvariable=duration_var, width=8).pack(side=tk.LEFT)
            elif t == "scroll":
                fr = ttk.Frame(fields); fr.pack(fill=tk.X, pady=3)
                ttk.Label(fr, text="格数", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(fr, textvariable=scroll_var, width=8).pack(side=tk.LEFT)
                ttk.Label(fields, text="正数向上滚，负数向下滚（如 -3 向下 3 格）",
                          foreground='#7f8c8d').pack(anchor='w')
            elif t == "condition":
                fr = ttk.Frame(fields); fr.pack(fill=tk.X, pady=3)
                ttk.Label(fr, text="判断", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                cond_combo = ttk.Combobox(fr, textvariable=cond_type_var,
                                          values=['image', 'ocr'], state='readonly', width=8)
                cond_combo.pack(side=tk.LEFT)
                cond_target = ttk.Frame(fields)
                cond_target.pack(fill=tk.X, pady=3)
                def _rebuild_cond_target():
                    for w in cond_target.winfo_children():
                        w.destroy()
                    if cond_type_var.get() == "ocr":
                        ttk.Label(cond_target, text="文字", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                        ttk.Entry(cond_target, textvariable=text_var, width=16).pack(side=tk.LEFT)
                    else:
                        ttk.Label(cond_target, text="探测图", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                        ttk.Label(cond_target, text=cond_img or "（未设置）", width=14,
                                  foreground='#7f8c8d').pack(side=tk.LEFT)
                        def _set_cond_img():
                            def _on_region(region):
                                nonlocal cond_img
                                x1, y1, x2, y2 = region
                                try:
                                    from PIL import ImageGrab
                                    im = ImageGrab.grab(bbox=(x1, y1, x2, y2))
                                except Exception as e:
                                    messagebox.showerror("截图失败", str(e), parent=dlg)
                                    return
                                fn = custom_ops.next_image_name()
                                if custom_ops.save_captured_image(im, fn):
                                    cond_img = fn
                                    _rebuild_cond_target()
                            self._capture_region_and(_on_region, dlg)
                        ttk.Button(cond_target, text="屏幕框选", command=_set_cond_img).pack(side=tk.LEFT, padx=(6, 0))
                cond_combo.bind("<<ComboboxSelected>>", lambda e: _rebuild_cond_target())
                _rebuild_cond_target()
                cr = ttk.Frame(fields); cr.pack(fill=tk.X, pady=3)
                ttk.Label(cr, text="置信度", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(cr, textvariable=conf_var, width=6).pack(side=tk.LEFT)
                ttk.Label(cr, text="超时", width=6).pack(side=tk.LEFT, padx=(6, 0))
                ttk.Entry(cr, textvariable=timeout_var, width=6).pack(side=tk.LEFT)
                jr = ttk.Frame(fields); jr.pack(fill=tk.X, pady=3)
                ttk.Label(jr, text="满足→步骤", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(jr, textvariable=jump_var, width=6).pack(side=tk.LEFT)
            elif t == "jump":
                jr = ttk.Frame(fields); jr.pack(fill=tk.X, pady=3)
                ttk.Label(jr, text="跳转→步骤", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(jr, textvariable=jump_var, width=6).pack(side=tk.LEFT)
            else:  # image
                img_area = ttk.Frame(fields)
                img_area.pack(fill=tk.X, pady=3)
                preview_lbl = ttk.Label(fields)
                def _refresh_img():
                    for w in img_area.winfo_children():
                        w.destroy()
                    ttk.Label(img_area, text="图片", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                    ttk.Label(img_area, text=img_name or "（未设置）", width=14,
                              foreground='#7f8c8d').pack(side=tk.LEFT)
                    def _cap():
                        def _on_region(region):
                            nonlocal img_name
                            x1, y1, x2, y2 = region
                            try:
                                from PIL import ImageGrab
                                im = ImageGrab.grab(bbox=(x1, y1, x2, y2))
                            except Exception as e:
                                messagebox.showerror("截图失败", str(e), parent=dlg)
                                return
                            fn = custom_ops.next_image_name()
                            if custom_ops.save_captured_image(im, fn):
                                img_name = fn
                                _refresh_img()
                        self._capture_region_and(_on_region, dlg)
                    def _file():
                        nonlocal img_name
                        path = filedialog.askopenfilename(
                            parent=dlg, title="选择图片",
                            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有", "*.*")])
                        if path:
                            fn = custom_ops.next_image_name()
                            try:
                                shutil.copy2(path, custom_ops.image_path(fn))
                            except Exception as e:
                                messagebox.showerror("导入失败", str(e), parent=dlg)
                                return
                            img_name = fn
                            _refresh_img()
                    ttk.Button(img_area, text="屏幕框选", command=_cap).pack(side=tk.LEFT, padx=(6, 4))
                    ttk.Button(img_area, text="导入图片", command=_file).pack(side=tk.LEFT)
                    # 预览
                    try:
                        preview_lbl.config(image='', text='')
                        img_path = custom_ops.image_path(img_name)
                        if os.path.exists(img_path):
                            from PIL import Image, ImageTk
                            im = Image.open(img_path)
                            im.thumbnail((200, 120))
                            photo = ImageTk.PhotoImage(im)
                            preview_lbl.config(image=photo, text='')
                            preview_lbl.image = photo
                    except Exception:
                        pass
                _refresh_img()
                preview_lbl.pack(pady=4)
                cr = ttk.Frame(fields); cr.pack(fill=tk.X, pady=3)
                ttk.Label(cr, text="置信度", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(cr, textvariable=conf_var, width=6).pack(side=tk.LEFT)
                ttk.Label(cr, text="超时(秒)", width=8).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Entry(cr, textvariable=timeout_var, width=6).pack(side=tk.LEFT)

        type_combo.bind("<<ComboboxSelected>>", lambda e: _rebuild_fields())
        _rebuild_fields()

        _row("停顿(秒)", pause_var, 8)

        def on_save():
            try:
                op["type"] = NAME_TO_TYPE.get(type_var.get(), type_var.get())   # 中文名 → key
                op["name"] = name_var.get().strip() or f"步骤{idx + 1}"
                op["pause_after"] = max(0, float(pause_var.get()))
                t = op["type"]
                if t == "coordinate":
                    op["x"] = int(float(x_var.get()))
                    op["y"] = int(float(y_var.get()))
                elif t == "ocr":
                    op["text"] = text_var.get().strip()
                    op["confidence"] = max(0.1, min(float(conf_var.get()), 0.99))
                    op["timeout"] = max(1, float(timeout_var.get()))
                elif t == "keyboard":
                    op["keys"] = keys_var.get().strip()
                    op["key_mode"] = key_mode_var.get()
                elif t == "multi_image":
                    op["images"] = mi_images
                    op["confidence"] = max(0.1, min(float(conf_var.get()), 0.99))
                    op["timeout"] = max(1, float(timeout_var.get()))
                elif t == "drag":
                    op["x1"] = int(float(x1_var.get()))
                    op["y1"] = int(float(y1_var.get()))
                    op["x2"] = int(float(x2_var.get()))
                    op["y2"] = int(float(y2_var.get()))
                    op["duration"] = max(0.1, float(duration_var.get()))
                elif t == "scroll":
                    op["scroll_amount"] = int(scroll_var.get())
                elif t == "condition":
                    op["cond_type"] = cond_type_var.get()
                    if cond_type_var.get() == "ocr":
                        op["text"] = text_var.get().strip()
                    else:
                        op["image"] = cond_img
                    op["confidence"] = max(0.1, min(float(conf_var.get()), 0.99))
                    op["timeout"] = max(1, float(timeout_var.get()))
                    op["jump_to"] = max(1, int(jump_var.get()))
                elif t == "jump":
                    op["jump_to"] = max(1, int(jump_var.get()))
                else:  # image
                    op["image"] = img_name
                    op["confidence"] = max(0.1, min(float(conf_var.get()), 0.99))
                    op["timeout"] = max(1, float(timeout_var.get()))
            except ValueError:
                messagebox.showwarning("输入无效", "数字字段格式不正确", parent=dlg)
                return
            _save_dlg_geo()
            self._save_ops_now()
            self._refresh_list()
            dlg.destroy()

        def _save_dlg_geo():
            """记住编辑框位置（下次打开恢复）"""
            try:
                settings = config.load_settings()
                settings["custom_ops_edit_geometry"] = dlg.geometry()
                config.save_settings(settings)
            except Exception:
                pass

        def _on_cancel():
            _save_dlg_geo()
            dlg.destroy()

        btns = ttk.Frame(form)
        btns.pack(pady=(10, 0))
        ttk.Button(btns, text="保存", style='Accent.TButton',
                   command=on_save, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="取消", style='TButton',
                   command=_on_cancel, width=8).pack(side=tk.LEFT)

        # 居中 / 位置记忆：有保存位置则恢复，否则居中显示在父窗口上
        dlg.update_idletasks()
        saved_geo = ""
        try:
            saved_geo = config.load_settings().get("custom_ops_edit_geometry", "")
        except Exception:
            pass
        if saved_geo and "+" in saved_geo:
            try:
                dlg.geometry("+" + saved_geo.split("+", 1)[1])
            except Exception:
                dlg.geometry("")
        else:
            try:
                pw = self.win.winfo_width()
                ph = self.win.winfo_height()
                px = self.win.winfo_rootx()
                py = self.win.winfo_rooty()
                dw = dlg.winfo_width()
                dh = dlg.winfo_height()
                x = max(0, px + (pw - dw) // 2)
                y = max(0, py + (ph - dh) // 2)
                dlg.geometry(f"+{x}+{y}")
            except Exception:
                pass
        dlg.protocol("WM_DELETE_WINDOW", lambda: (_save_dlg_geo(), dlg.destroy()))

    def _pick_point(self, x_var, y_var, dlg):
        """屏幕取点：隐藏窗口 → 点击屏幕一点 → 记录坐标到 x_var/y_var"""
        try:
            import gui_app
            gui_app.hide_log_overlay()   # 临时隐藏日志遮罩，避免挡住点击
        except Exception:
            pass
        # 先释放所有模态抓取，避免遮罩收不到点击
        try:
            if dlg and dlg.winfo_exists():
                dlg.grab_release()
        except Exception:
            pass
        try:
            self.win.grab_release()
        except Exception:
            pass
        self.win.withdraw()
        try:
            if dlg and dlg.winfo_exists():
                dlg.withdraw()
        except Exception:
            pass
        self.win.after(300, lambda: self._show_point_overlay(x_var, y_var, dlg))

    def _show_point_overlay(self, x_var, y_var, dlg):
        overlay = tk.Toplevel(self.win)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-alpha', 0.3)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='black')
        overlay.config(cursor='crosshair')
        # 用 canvas 铺满全窗（与「屏幕框选」一致，保证点击一定到达）
        canvas = tk.Canvas(overlay, highlightthickness=0, bg='black')
        canvas.pack(fill=tk.BOTH, expand=True)
        hint = tk.Label(canvas, text="点击游戏里要点击的位置（任意位置点一下，Esc 取消）",
                        font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
        hint.place(relx=0.5, rely=0.05, anchor='center')

        def on_click(e):
            x_var.set(str(e.x_root))
            y_var.set(str(e.y_root))
            overlay.destroy()

        def on_esc(_):
            overlay.destroy()

        # canvas + 提示文字都绑定点击，确保任意位置都能取到点
        canvas.bind('<ButtonPress-1>', on_click)
        hint.bind('<ButtonPress-1>', on_click)
        canvas.bind('<Escape>', on_esc)
        overlay.bind('<Escape>', on_esc)
        overlay.focus_force()
        try:
            overlay.grab_set()   # 抓取所有输入，点击一定到达遮罩
        except Exception:
            pass
        self.win.wait_window(overlay)
        self.win.deiconify()
        self.win.grab_set()
        try:
            if dlg and dlg.winfo_exists():
                dlg.deiconify()
                dlg.grab_set()
        except Exception:
            pass
        try:
            import gui_app
            gui_app.show_log_overlay()   # 恢复日志遮罩
        except Exception:
            pass

    # ==================== 测试运行 ====================
    def _run_test(self):
        if not self.ops:
            messagebox.showinfo("提示", "请先添加至少一个步骤", parent=self.win)
            return
        if self._test_thread and self._test_thread.is_alive():
            messagebox.showinfo("提示", "测试运行已在执行中", parent=self.win)
            return
        self._test_stop.clear()
        self._test_thread = threading.Thread(target=self._test_worker, daemon=True)
        self._test_thread.start()
        print("▶ 自定义操作测试运行开始（可在日志中查看进度，点「停止」可中止）")

    def _test_worker(self):
        custom_ops.run_custom_ops_for_test(self.app, self._test_stop)

    def _stop_test(self):
        self._test_stop.set()
        print("⏹ 已发送停止信号，将在当前步骤结束后中止")

    def _on_close(self):
        try:
            if self._test_thread and self._test_thread.is_alive():
                self._test_stop.set()
        except Exception:
            pass
        # 恢复实验功能窗口（导航栈），并重新获取模态抓取
        utils.nav_pop(self.win)
        try:
            if self.parent_win and self.parent_win.winfo_exists():
                self.parent_win.grab_set()
        except Exception:
            pass
