#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "template_capture.py")

with open(PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# ===== 1. Add batch button in nav_frame after upload_btn =====
old = '''        upload_btn = ttk.Button(nav_frame, text="\U0001f4c1 上传图片", style="Accent.TButton",
                                command=lambda: _upload_image())
        upload_btn.pack(side=tk.LEFT)'''


new = '''        upload_btn = ttk.Button(nav_frame, text="\U0001f4c1 上传图片", style="Accent.TButton",
                                command=lambda: _upload_image())
        upload_btn.pack(side=tk.LEFT, padx=(0, 5))
        batch_btn = ttk.Button(nav_frame, text="\U0001f4c2 批量匹配", style="Accent.TButton",
                               command=lambda: _batch_match_upload())
        batch_btn.pack(side=tk.LEFT)'''

assert old in content, "batch button pattern not found!"
content = content.replace(old, new)

# ===== 2. Add batch methods and results window after _show_match_results =====
old = '''    def _save_status(self):
        """保存当前上传状态到设置文件"""
        settings = config.load_settings()
        settings["template_upload_status"] = dict(self.status)
        config.save_settings(settings)'''

new = '''    def _batch_match_upload(self):
        """批量匹配：选择文件夹，自动匹配所有图片"""
        folder = filedialog.askdirectory(title="选择包含截图的文件夹", parent=self.win)
        if not folder:
            return

        # 扫描图片文件
        import numpy as np
        import cv2
        extensions = (".png", ".jpg", ".jpeg", ".bmp")
        files = [f for f in os.listdir(folder) if f.lower().endswith(extensions)]
        if not files:
            messagebox.showinfo("提示", "文件夹中没有找到图片文件", parent=self.win)
            return

        # 逐个匹配
        all_results = []  # [(filename, full_path, score, match_count, var_name, name, rel_path)]
        for fname in files:
            fpath = os.path.join(folder, fname)
            try:
                img_data = np.fromfile(fpath, dtype=np.uint8)
                if img_data.size == 0:
                    continue
                results = self._run_matching(img_data)
                for score, match_count, ratio, var_name, name, rel_path in results:
                    all_results.append((fname, fpath, score, match_count, var_name, name, rel_path))
            except Exception as e:
                print(f"⚠️ 匹配失败 {fname}: {e}")

        if not all_results:
            messagebox.showinfo("提示", "所有图片均未匹配到任何模板", parent=self.win)
            return

        self._show_batch_results(all_results)

    def _show_batch_results(self, all_results):
        """批量匹配结果窗口"""
        import shutil
        import numpy as np

        win = tk.Toplevel(self.win)
        win.title("批量匹配结果")
        win.resizable(True, True)
        win.minsize(700, 500)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)

        # 顶部统计
        img_count = len(set(r[0] for r in all_results))
        match_count = len(all_results)
        info_var = tk.StringVar(value=f"共扫描 {img_count} 张图片，匹配到 {match_count} 个模板")
        ttk.Label(win, textvariable=info_var, font=("Microsoft YaHei UI", 11, "bold")).pack(padx=15, pady=(10, 2), anchor="w")

        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        progress_var = tk.StringVar(value=f"已保存: {done}/{total}")
        ttk.Label(win, textvariable=progress_var, font=("Microsoft YaHei UI", 9), foreground="#999").pack(padx=15, anchor="w")

        # Treeview
        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        columns = ("选中", "图片", "匹配模板", "相似度")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=20)
        tree.heading("选中", text="选中")
        tree.heading("图片", text="图片")
        tree.heading("匹配模板", text="匹配模板")
        tree.heading("相似度", text="相似度")
        tree.column("选中", width=50, anchor=tk.CENTER)
        tree.column("图片", width=180)
        tree.column("匹配模板", width=200)
        tree.column("相似度", width=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 数据
        check_vars = {}  # item_id -> tk.BooleanVar
        for idx, (fname, fpath, score, match_count, var_name, name, rel_path) in enumerate(all_results):
            var = tk.BooleanVar(value=True)
            item_id = tree.insert("", tk.END, values=("", fname, f"{name} ({var_name})", f"{score:.1f}"))
            check_vars[item_id] = (var, fname, fpath, score, var_name, name, rel_path)

        def toggle_all(checked):
            for item_id in check_vars:
                check_vars[item_id][0].set(checked)

        def refresh_checks():
            for item_id, (var, *_) in check_vars.items():
                values = list(tree.item(item_id, "values"))
                values[0] = "✅" if var.get() else ""
                tree.item(item_id, values=values)

        def on_save_selected():
            saved = 0
            errors = 0
            for item_id, (var, fname, fpath, score, var_name, name, rel_path) in check_vars.items():
                if not var.get():
                    continue
                try:
                    os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
                    save_path = config.user_template_path(os.path.basename(rel_path))
                    shutil.copy2(fpath, save_path)
                    self.status[var_name] = "done"
                    saved += 1
                except Exception as e:
                    print(f"⚠️ 保存失败 {name}: {e}")
                    errors += 1

            if saved > 0:
                self._save_status()
                self._update_progress()
                utils_clear_cache()
                done = sum(1 for s in self.status.values() if s == "done")
                total = len(self.status)
                progress_var.set(f"已保存: {done}/{total}")
                info_var.set(f"✅ 已保存 {saved} 个模板" + (f"，{errors} 个失败" if errors else ""))

                # 更新主界面状态
                for item_id, (var, fname, fpath, score, var_name, name, rel_path) in check_vars.items():
                    if var.get() and var_name in self.rows:
                        status_lbl, _ = self.rows[var_name]
                        status_lbl.config(text="✅")
                refresh_checks()
            if errors > 0 and saved == 0:
                messagebox.showerror("错误", f"保存失败 {errors} 个模板", parent=win)

        # 按钮
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 10))

        ttk.Button(btn_frame, text="全选", command=lambda: toggle_all(True), width=8).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="取消全选", command=lambda: toggle_all(False), width=8).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(btn_frame, text="保存选中", style="Accent.TButton",
                   command=on_save_selected, width=12).pack(side=tk.RIGHT, padx=(0, 5))
        ttk.Button(btn_frame, text="取消", command=win.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))

        utils.bind_window_geometry(win, "batch_match_geometry", "750x550", (700, 500))

    def _save_status(self):
        """保存当前上传状态到设置文件"""
        settings = config.load_settings()
        settings["template_upload_status"] = dict(self.status)
        config.save_settings(settings)'''

assert old in content, "batch methods insert pattern not found!"
content = content.replace(old, new)

with open(PATH, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: batch matching added")
