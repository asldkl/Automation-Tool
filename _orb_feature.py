#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Add ORB batch upload button and matching window to template capture wizard"""

import re

with open('template_capture.py', 'r', encoding='utf-8') as f:
    content = f.read()

# === Part 1: Add ORB batch upload button before section headers ===
old_btn_insert = '''        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 分组定义'''
new_btn_insert = '''        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ORB批量匹配上传按钮（列表顶部）
        orb_frame = ttk.Frame(self.scroll_frame)
        orb_frame.pack(fill=tk.X, pady=(5, 5))
        orb_btn = ttk.Button(orb_frame, text="\U0001f50d ORB图片匹配上传", style='Accent.TButton',
                             command=self._orb_batch_upload, width=30)
        orb_btn.pack(side=tk.LEFT, padx=2)
        ttk.Label(orb_frame, text="上传截图自动匹配最佳模板",
                  font=('Microsoft YaHei UI', 8), foreground='#7f8c8d').pack(side=tk.LEFT, padx=5)

        # 分组定义'''

assert old_btn_insert in content, "Button insert pattern not found!"
content = content.replace(old_btn_insert, new_btn_insert)

# === Part 2: Add ORB batch upload method before _save_status ===
old_method_insert = '''    def _save_status(self):
        """保存模板上传状态到设置文件"""
        settings = config.load_settings()
        settings["template_upload_status"] = {k: v for k, v in self.status.items() if v == "done"}
        config.save_settings(settings)'''

new_method_insert = '''    def _orb_batch_upload(self):
        """ORB批量匹配：用户上传一张截图，自动与所有默认模板匹配，找到最佳对应模板"""
        import cv2
        import numpy as np

        file_path = filedialog.askopenfilename(
            title="选择要匹配的截图",
            filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")],
            parent=self.win
        )
        if not file_path:
            return

        # 读取用户上传的图片
        user_img = cv2.imread(file_path, cv2.IMREAD_GRAYSCALE)
        if user_img is None:
            messagebox.showerror("错误", "无法读取图片文件，请确认格式正确。", parent=self.win)
            return

        messagebox.showinfo("提示",
            "正在执行 ORB 特征匹配，请稍候...\\n"
            "将上传的截图与所有内置模板进行比对，找到最佳匹配项。",
            parent=self.win)

        # 对每个默认模板执行 ORB 匹配
        results = []  # [(score, var_name, name, rel_path), ...]
        orb = cv2.ORB_create(nfeatures=1000)

        kp_user, des_user = orb.detectAndCompute(user_img, None)
        if des_user is None or len(kp_user) < 5:
            messagebox.showerror("错误", "上传的图片特征点不足，请选择包含游戏UI元素的截图。", parent=self.win)
            return

        for var_name, rel_path, name, hint in self.capture_list:
            # 使用内置默认模板
            default_path = config.resource_path(rel_path)
            if not os.path.exists(default_path):
                continue

            template_img = cv2.imread(default_path, cv2.IMREAD_GRAYSCALE)
            if template_img is None:
                continue

            kp_tpl, des_tpl = orb.detectAndCompute(template_img, None)
            if des_tpl is None or len(kp_tpl) < 3:
                continue

            # 特征匹配
            bf = cv2.BFMatcher(cv2.NORM_HAMMING)
            matches = bf.knnMatch(des_user, des_tpl, k=2)

            # Lowe's ratio test
            good_matches = []
            for m, n in matches:
                if m.distance < 0.75 * n.distance:
                    good_matches.append(m)

            # 计算综合得分（考虑匹配数量和特征点比例）
            match_count = len(good_matches)
            ratio = match_count / max(len(kp_tpl), 1)
            score = match_count * ratio

            results.append((score, match_count, ratio, var_name, name, rel_path))

        if not results:
            messagebox.showerror("错误", "没有找到可匹配的模板，请确认截图包含游戏UI元素。", parent=self.win)
            return

        # 按得分排序
        results.sort(key=lambda x: x[0], reverse=True)
        best = results[0]

        # 如果最佳匹配得分太低，提示用户
        if best[0] < 1.0:
            if not messagebox.askyesno("匹配结果",
                    f"最佳匹配：{best[4]}（匹配数：{best[1]}，得分：{best[0]:.1f}）\\n\\n"
                    f"匹配质量可能不佳，是否仍要应用？",
                    parent=self.win):
                return

        # 显示匹配结果窗口，让用户选择
        self._show_orb_results(results, user_img, file_path)

    def _show_orb_results(self, results, user_img, file_path):
        """显示ORB匹配结果窗口，用户选择要应用的匹配项"""
        import cv2
        import numpy as np

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

        columns = ("选择", "模板名称", "匹配数", "得分")
        tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=15)
        tree.heading("#0", text="", width=40)
        tree.heading("选择", text="选择", width=40)
        tree.heading("模板名称", text="模板名称", width=200)
        tree.heading("匹配数", text="匹配数", width=80, anchor=tk.CENTER)
        tree.heading("得分", text="得分", width=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 填充数据
        selected_var = tk.StringVar()
        result_map = {}  # item_id -> (var_name, rel_path)

        for score, match_count, ratio, var_name, name, rel_path in results:
            item_id = tree.insert("", tk.END, text="",
                                  values=("", f"{name} ({var_name})", str(match_count), f"{score:.1f}"))
            result_map[item_id] = (var_name, rel_path, name)

        # 默认选中第一个
        first_item = tree.get_children()[0] if tree.get_children() else None
        if first_item:
            tree.selection_set(first_item)

        def on_select(event):
            selected = tree.selection()
            if selected:
                item = selected[0]
                var_name, rel_path, name = result_map[item]
                selected_var.set(var_name)

        tree.bind("<<TreeviewSelect>>", on_select)

        def on_confirm():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("提示", "请先选择一个模板", parent=win)
                return
            item = selected[0]
            var_name, rel_path, name = result_map[item]

            # 保存用户图片为自定义模板
            try:
                import shutil
                os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
                save_path = config.user_template_path(os.path.basename(rel_path))
                shutil.copy2(file_path, save_path)

                # 更新状态
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

        def on_apply_all():
            """自动匹配全部：从上到下逐个匹配最佳模板"""
            import shutil
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
                        status_lbl.config(text="✅")
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

        utils.restore_window_geometry(win, "orb_match_geometry", "550x500", (500, 400))

    def _save_status(self):
        """保存模板上传状态到设置文件"""
        settings = config.load_settings()
        settings["template_upload_status"] = {k: v for k, v in self.status.items() if v == "done"}
        config.save_settings(settings)'''

assert old_method_insert in content, "Method insert pattern not found!"
content = content.replace(old_method_insert, new_method_insert)

with open('template_capture.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: ORB batch upload feature added")
