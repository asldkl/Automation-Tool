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
}


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
        ttk.Button(toolbar, text="＋ 屏幕框选", style='Accent.TButton',
                   command=self._capture_from_screen, width=12).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="选择图片", style='TButton',
                   command=self._add_step_from_file, width=9).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="＋ 坐标点击", style='TButton',
                   command=self._add_coordinate_step, width=11).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="＋ OCR点击", style='TButton',
                   command=self._add_ocr_step, width=10).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Button(toolbar, text="上移", style='TButton',
                   command=self._move_up, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="下移", style='TButton',
                   command=self._move_down, width=5).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(toolbar, text="删除", style='TButton',
                   command=self._delete_step, width=5).pack(side=tk.LEFT)

        # ----- 选项行：自动执行 + 随机偏移开关 -----
        opt = ttk.Frame(self.win, padding=(8, 2))
        opt.pack(fill=tk.X)
        self._auto_var = tk.BooleanVar(value=bool(self.app.settings.get("enable_custom_ops", False)))
        ttk.Checkbutton(opt, text="主流程完成后自动执行自定义操作",
                        variable=self._auto_var,
                        command=self._save_auto_setting).pack(side=tk.LEFT)
        self._jitter_var = tk.BooleanVar(value=bool(self.app.settings.get("custom_ops_jitter", False)))
        ttk.Checkbutton(opt, text="点击受随机偏移影响",
                        variable=self._jitter_var,
                        command=self._save_jitter_setting).pack(side=tk.LEFT, padx=(12, 0))

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
        self.tree.column("seq", width=46, anchor=tk.CENTER)
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
        menu.add_command(label="✅ 设为找图点击", command=lambda: self._set_step_type("image"),
                         state='normal' if t != "image" else 'disabled')
        menu.add_command(label="✅ 设为坐标点击", command=lambda: self._set_step_type("coordinate"),
                         state='normal' if t != "coordinate" else 'disabled')
        menu.add_command(label="✅ 设为OCR点击", command=lambda: self._set_step_type("ocr"),
                         state='normal' if t != "ocr" else 'disabled')
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

    def _save_auto_setting(self):
        self.app.settings["enable_custom_ops"] = self._auto_var.get()
        config.save_settings(self.app.settings)
        print(f"📌 自定义操作自动执行：{'开启' if self._auto_var.get() else '关闭'}")

    def _save_jitter_setting(self):
        self.app.settings["custom_ops_jitter"] = self._jitter_var.get()
        config.save_settings(self.app.settings)
        print(f"📌 自定义操作点击随机偏移：{'开启' if self._jitter_var.get() else '关闭'}")

    # ==================== 添加步骤 ====================
    def _capture_from_screen(self):
        """隐藏自定义操作窗口，全屏拖拽框选截图作为新步骤
        （父窗口设置窗口已被导航栈隐藏，无需再处理）"""
        self.win.withdraw()
        self.win.after(300, self._show_capture_overlay)

    def _show_capture_overlay(self):
        """全屏拖拽框选：截图区域 → 创建步骤"""
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
        overlay.bind("<Escape>", on_escape)

        self.win.wait_window(overlay)
        self.win.deiconify()
        self.win.grab_set()   # 重新获取模态

        if result:
            self._add_step_from_region(result)

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
        step.setdefault("name", f"步骤{len(self.ops) + 1}")
        step.setdefault("pause_after", float(self.app.settings.get("custom_ops_pause", 0.5)))
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

        # 类型切换
        type_var = tk.StringVar(value=op.get("type", "image"))
        tr = ttk.Frame(form)
        tr.pack(fill=tk.X, pady=3)
        ttk.Label(tr, text="类型", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
        type_combo = ttk.Combobox(tr, textvariable=type_var,
                                  values=[k for k in STEP_TYPES], state='readonly', width=12)
        type_combo.pack(side=tk.LEFT)

        name_var = tk.StringVar(value=op.get("name", f"步骤{idx + 1}"))
        pause_var = tk.StringVar(value=str(op.get("pause_after", 0.5)))

        # 各类型字段变量
        conf_var = tk.StringVar(value=str(op.get("confidence", 0.7)))
        timeout_var = tk.StringVar(value=str(op.get("timeout", 5)))
        x_var = tk.StringVar(value=str(op.get("x", 0)))
        y_var = tk.StringVar(value=str(op.get("y", 0)))
        text_var = tk.StringVar(value=op.get("text", ""))

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
            t = type_var.get()
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
            else:  # image
                cr = ttk.Frame(fields); cr.pack(fill=tk.X, pady=3)
                ttk.Label(cr, text="置信度", style='Settings.TLabel', width=10).pack(side=tk.LEFT)
                ttk.Entry(cr, textvariable=conf_var, width=6).pack(side=tk.LEFT)
                ttk.Label(cr, text="超时(秒)", width=8).pack(side=tk.LEFT, padx=(8, 0))
                ttk.Entry(cr, textvariable=timeout_var, width=6).pack(side=tk.LEFT)
                img_path = custom_ops.image_path(op.get("image", ""))
                if os.path.exists(img_path):
                    try:
                        from PIL import Image, ImageTk
                        im = Image.open(img_path)
                        im.thumbnail((200, 120))
                        photo = ImageTk.PhotoImage(im)
                        lbl = ttk.Label(fields, image=photo)
                        lbl.image = photo
                        lbl.pack(pady=4)
                    except Exception:
                        pass

        type_combo.bind("<<ComboboxSelected>>", lambda e: _rebuild_fields())
        _rebuild_fields()

        _row("停顿(秒)", pause_var, 8)

        def on_save():
            try:
                op["type"] = type_var.get()
                op["name"] = name_var.get().strip() or f"步骤{idx + 1}"
                op["pause_after"] = max(0, float(pause_var.get()))
                if op["type"] == "coordinate":
                    op["x"] = int(float(x_var.get()))
                    op["y"] = int(float(y_var.get()))
                elif op["type"] == "ocr":
                    op["text"] = text_var.get().strip()
                    op["confidence"] = max(0.1, min(float(conf_var.get()), 0.99))
                    op["timeout"] = max(1, float(timeout_var.get()))
                else:
                    op["confidence"] = max(0.1, min(float(conf_var.get()), 0.99))
                    op["timeout"] = max(1, float(timeout_var.get()))
            except ValueError:
                messagebox.showwarning("输入无效", "数字字段格式不正确", parent=dlg)
                return
            self._save_ops_now()
            self._refresh_list()
            dlg.destroy()

        btns = ttk.Frame(form)
        btns.pack(pady=(10, 0))
        ttk.Button(btns, text="保存", style='Accent.TButton',
                   command=on_save, width=8).pack(side=tk.LEFT, padx=4)
        ttk.Button(btns, text="取消", style='TButton',
                   command=dlg.destroy, width=8).pack(side=tk.LEFT)

    def _pick_point(self, x_var, y_var, dlg):
        """屏幕取点：隐藏窗口 → 点击屏幕一点 → 记录坐标到 x_var/y_var"""
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
        hint = tk.Label(overlay, text="点击游戏里要点击的位置（任意位置点一下，Esc 取消）",
                        font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
        hint.place(relx=0.5, rely=0.05, anchor='center')

        def on_click(e):
            x_var.set(str(e.x_root))
            y_var.set(str(e.y_root))
            overlay.destroy()

        def on_esc(_):
            overlay.destroy()

        overlay.bind('<Button-1>', on_click)
        overlay.bind('<Escape>', on_esc)
        self.win.wait_window(overlay)
        self.win.deiconify()
        self.win.grab_set()
        try:
            if dlg and dlg.winfo_exists():
                dlg.deiconify()
                dlg.grab_set()
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
