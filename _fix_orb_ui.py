#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "template_capture.py")

with open(PATH, 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    def _show_orb_results(self, results, file_path):
        """显示ORB匹配结果窗口，用户选择要应用的匹配项"""
        import shutil

        win = tk.Toplevel(self.win)
        win.title("ORB特征匹配结果")
        win.resizable(True, True)
        win.minsize(500, 400)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)

        ttk.Label(win, text="ORB特征匹配结果",
                  font=('Microsoft YaHei UI', 12, 'bold')).pack(padx=15, pady=(10, 5))

        ttk.Label(win, text="系统已识别到以下匹配项，选择要应用的模板：",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(padx=15, anchor='w')

        # 表格
        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        columns = ("模板名称", "匹配数", "得分")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)
        tree.heading("模板名称", text="模板名称", width=200)
        tree.heading("匹配数", text="匹配数", width=80, anchor=tk.CENTER)
        tree.heading("得分", text="得分", width=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        result_map = {}  # item_id -> (var_name, rel_path, name)

        for score, match_count, ratio, var_name, name, rel_path in results:
            item_id = tree.insert("", tk.END,
                                  values=(f"{name} ({var_name})", str(match_count), f"{score:.1f}"))
            result_map[item_id] = (var_name, rel_path, name)

        # 默认选中第一个
        first_item = tree.get_children()[0] if tree.get_children() else None
        if first_item:
            tree.selection_set(first_item)
            tree.focus(first_item)

        def on_confirm():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("提示", "请先选择一个模板", parent=win)
                return
            item = selected[0]
            var_name, rel_path, name = result_map[item]

            # 保存用户图片为自定义模板
            try:
                os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
                save_path = config.user_template_path(os.path.basename(rel_path))
                shutil.copy2(file_path, save_path)

                # 更新状态
                self.status[var_name] = "done"
                if var_name in self.rows:
                    status_lbl, _ = self.rows[var_name]
                    status_lbl.config(text="")

                self._update_progress()
                utils_clear_cache()

                win.destroy()
                messagebox.showinfo("成功", f"模板「{name}」已更新为上传的图片。", parent=self.win)
            except Exception as e:
                messagebox.showerror("错误", f"保存模板失败：{e}", parent=win)

        def on_apply_all():
            """自动匹配全部：逐个模板匹配，找到最佳匹配就应用"""
            import cv2
            import numpy as np

            img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return

            orb = cv2.ORB_create(nfeatures=1000)
            kp_all, des_all = orb.detectAndCompute(img, None)
            if des_all is None:
                return

            applied = 0
            for var_name, rel_path, name, hint in self.capture_list:
                if self.status.get(var_name) == "done":
                    continue  # 跳过已上传的
                default_path = config.resource_path(rel_path)
                if not os.path.exists(default_path):
                    continue
                tpl = cv2.imread(default_path, cv2.IMREAD_GRAYSCALE)
                if tpl is None:
                    continue
                kp_t, des_t = orb.detectAndCompute(tpl, None)
                if des_t is None or len(kp_t) < 3:
                    continue
                bf = cv2.BFMatcher(cv2.NORM_HAMMING)
                matches = bf.knnMatch(des_all, des_t, k=2)
                good = []
                for m, n in matches:
                    if m.distance < 0.75 * n.distance:
                        good.append(m)
                if len(good) >= 3:
                    save_path = config.user_template_path(os.path.basename(rel_path))
                    shutil.copy2(file_path, save_path)
                    self.status[var_name] = "done"
                    if var_name in self.rows:
                        status_lbl, _ = self.rows[var_name]
                        status_lbl.config(text="")
                    applied += 1

            self._update_progress()
            utils_clear_cache()
            win.destroy()
            messagebox.showinfo("完成", f"自动匹配完成！已更新 {applied} 个模板。", parent=self.win)

        # 按钮
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 10))

        ttk.Button(btn_frame, text="自动匹配全部", command=on_apply_all, width=14).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="应用选中", style='Accent.TButton',
                   command=on_confirm, width=12).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btn_frame, text="取消", command=win.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))

        utils.restore_window_geometry(win, "orb_match_geometry", "550x500", (500, 400))'''

new = '''    def _show_orb_results(self, results, file_path):
        """显示ORB匹配结果：左右图片对比 + 置信度"""
        import shutil
        from PIL import Image, ImageTk

        results = sorted(results, key=lambda x: x[0], reverse=True)
        total = len(results)
        current_idx = [0]

        win = tk.Toplevel(self.win)
        win.title("ORB特征匹配结果")
        win.resizable(True, True)
        win.minsize(700, 500)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)

        # 置信度显示行
        conf_var = tk.StringVar()
        conf_label = ttk.Label(win, textvariable=conf_var,
                               font=("Microsoft YaHei UI", 12, "bold"),
                               foreground="#e67e22")
        conf_label.pack(pady=(10, 2), padx=15, anchor="w")

        # 图片左右对比区域
        img_frame = ttk.Frame(win)
        img_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        left_frame = ttk.LabelFrame(img_frame, text=" 匹配到的模板 ", padding=5)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        right_frame = ttk.LabelFrame(img_frame, text=" 你上传的图片 ", padding=5)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        left_canvas = tk.Canvas(left_frame, bg="#f5f5f5", highlightthickness=0)
        left_canvas.pack(fill=tk.BOTH, expand=True)

        right_canvas = tk.Canvas(right_frame, bg="#f5f5f5", highlightthickness=0)
        right_canvas.pack(fill=tk.BOTH, expand=True)

        img_refs = {}

        def load_and_display(cv, img_path, max_size=(280, 280)):
            try:
                pil_img = Image.open(img_path)
                pil_img.thumbnail(max_size, Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(pil_img)
                cv.delete("all")
                cx, cy = pil_img.width // 2, pil_img.height // 2
                cv.create_image(max(cx, 140), max(cy, 140), image=tk_img, anchor=tk.CENTER)
                cv.config(width=pil_img.width, height=pil_img.height)
                return tk_img
            except Exception:
                cv.delete("all")
                cv.create_text(140, 140, text="无法加载图片", fill="#999", font=("", 10))
                return None

        def show_result(idx):
            if idx < 0 or idx >= total:
                return
            score, match_count, ratio, var_name, name, rel_path = results[idx]

            conf_var.set(f"{name}  —  置信度：{score:.1f}（匹配特征点：{match_count}）")

            default_path = config.resource_path(rel_path)
            user_path = config.user_template_path(os.path.basename(rel_path))
            tpl_path = user_path if os.path.exists(user_path) else default_path

            img_refs["left"] = load_and_display(left_canvas, tpl_path)
            img_refs["right"] = load_and_display(right_canvas, file_path)

            prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
            next_btn.config(state=tk.NORMAL if idx < total - 1 else tk.DISABLED)
            page_var.set(f"{idx + 1} / {total}")

        # 导航
        nav_frame = ttk.Frame(win)
        nav_frame.pack(fill=tk.X, padx=15, pady=(2, 5))

        prev_btn = ttk.Button(nav_frame, text="◀ 上一个", width=10,
                              command=lambda: [current_idx.__setitem__(0, current_idx[0] - 1),
                                               show_result(current_idx[0])])
        prev_btn.pack(side=tk.LEFT, padx=(0, 5))

        page_var = tk.StringVar()
        ttk.Label(nav_frame, textvariable=page_var,
                  font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=10)

        next_btn = ttk.Button(nav_frame, text="下一个 ▶", width=10,
                              command=lambda: [current_idx.__setitem__(0, current_idx[0] + 1),
                                               show_result(current_idx[0])])
        next_btn.pack(side=tk.LEFT)

        # 保存/取消按钮
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 10))

        def on_save():
            idx = current_idx[0]
            score, match_count, ratio, var_name, rel_path, name = results[idx]
            try:
                os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
                save_path = config.user_template_path(os.path.basename(rel_path))
                shutil.copy2(file_path, save_path)

                self.status[var_name] = "done"
                if var_name in self.rows:
                    status_lbl, _ = self.rows[var_name]
                    status_lbl.config(text="✅")

                self._update_progress()
                utils_clear_cache()
                win.destroy()
                messagebox.showinfo("成功", f"模板「{name}」已更新为上传的图片。", parent=self.win)
            except Exception as e:
                messagebox.showerror("错误", f"保存模板失败：{e}", parent=win)

        ttk.Button(btn_frame, text="保存", style="Accent.TButton",
                   command=on_save, width=12).pack(side=tk.RIGHT, padx=(0, 5))
        ttk.Button(btn_frame, text="取消", command=win.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))

        show_result(0)
        utils.restore_window_geometry(win, "orb_match_geometry", "750x550", (700, 500))'''

assert old in content, "Pattern not found!"
content = content.replace(old, new)

with open(PATH, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK")
