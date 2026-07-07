    def _image_match_upload(self):
        self._show_match_results()

    def _run_matching(self, img_data, algorithm="ORB"):
        import cv2
        import numpy as np
        user_img = cv2.imdecode(img_data, cv2.IMREAD_GRAYSCALE)
        if user_img is None:
            return []
        results = []
        if algorithm == "ORB":
            orb = cv2.ORB_create(nfeatures=1000)
            kp_user, des_user = orb.detectAndCompute(user_img, None)
            if des_user is None or len(kp_user) < 5:
                return []
            for var_name, rel_path, name, hint in self.capture_list:
                default_path = config.resource_path(rel_path)
                if not os.path.exists(default_path):
                    continue
                tpl_data = np.fromfile(default_path, dtype=np.uint8)
                template_img = cv2.imdecode(tpl_data, cv2.IMREAD_GRAYSCALE)
                if template_img is None:
                    continue
                kp_tpl, des_tpl = orb.detectAndCompute(template_img, None)
                if des_tpl is None or len(kp_tpl) < 3:
                    continue
                bf = cv2.BFMatcher(cv2.NORM_HAMMING)
                matches = bf.knnMatch(des_user, des_tpl, k=2)
                good_matches = []
                for m, n in matches:
                    if m.distance < 0.75 * n.distance:
                        good_matches.append(m)
                match_count = len(good_matches)
                ratio = match_count / max(len(kp_tpl), 1)
                score = match_count * ratio
                results.append((score, match_count, ratio, var_name, name, rel_path))
        elif algorithm == "pHash":
            def _phash(img):
                img32 = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
                img32f = np.float32(img32)
                dct = cv2.dct(img32f)
                dct_low = dct[:8, :8]
                avg = np.mean(dct_low[1:])
                return np.ravel(dct_low > avg).astype(np.uint8)
            hash_user = _phash(user_img)
            for var_name, rel_path, name, hint in self.capture_list:
                default_path = config.resource_path(rel_path)
                if not os.path.exists(default_path):
                    continue
                tpl_data = np.fromfile(default_path, dtype=np.uint8)
                template_img = cv2.imdecode(tpl_data, cv2.IMREAD_GRAYSCALE)
                if template_img is None:
                    continue
                hash_tpl = _phash(template_img)
                hamming = np.sum(hash_user != hash_tpl)
                score = max(0, 64 - hamming * 1.5)
                match_count = 64 - hamming
                results.append((score, match_count, 0, var_name, name, rel_path))
        results.sort(key=lambda x: x[0], reverse=True)
        return results

    def _show_match_results(self, file_path=None):
        import shutil, numpy as np
        from PIL import Image, ImageTk
        current_idx = [0]
        current_file = [file_path]
        current_results = [[]]
        current_algo = ["ORB"]
        win = tk.Toplevel(self.win)
        win.title("图片匹配结果")
        win.resizable(True, True)
        win.minsize(700, 500)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)
        algo_var = tk.StringVar(value="算法：ORB")
        conf_var = tk.StringVar(value="请上传图片开始匹配")
        ttk.Label(win, textvariable=algo_var, font=("Microsoft YaHei UI", 9, "bold"), foreground="#555").pack(pady=(10, 0), padx=15, anchor="w")
        ttk.Label(win, textvariable=conf_var, font=("Microsoft YaHei UI", 12, "bold"), foreground="#e67e22").pack(pady=(0, 2), padx=15, anchor="w")
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
                cv.create_image(pil_img.width // 2 + 10, pil_img.height // 2 + 10, image=tk_img, anchor=tk.CENTER)
                cv.config(width=pil_img.width + 20, height=pil_img.height + 20)
                return tk_img
            except Exception:
                cv.delete("all")
                cv.create_text(140, 140, text="请上传图片", fill="#999", font=("", 12))
                return None
        def do_matching(fp):
            if not fp:
                return
            img_data = np.fromfile(fp, dtype=np.uint8)
            algo = current_algo[0]
            results = self._run_matching(img_data, algorithm=algo)
            current_results[0] = results
            if results:
                algo_var.set(f"算法：{algo}")
                current_idx[0] = 0
                show_result(0)
            else:
                conf_var.set(f"{algo}：未匹配到任何模板，请尝试切换算法或上传其他图片")
                left_canvas.delete("all")
                left_canvas.create_text(140, 140, text="无匹配", fill="#999", font=("", 12))
                right_canvas.delete("all")
                right_canvas.create_text(140, 140, text="请上传图片", fill="#999", font=("", 12))
        def show_result(idx):
            results = current_results[0]
            total = len(results)
            if not results or idx < 0 or idx >= total:
                return
            score, match_count, ratio, var_name, name, rel_path = results[idx]
            algo = current_algo[0]
            if algo == "pHash":
                conf_var.set(f"{name}  —  相似度：{score:.1f}（汉明距离：{64 - match_count}）")
            else:
                conf_var.set(f"{name}  —  置信度：{score:.1f}（匹配特征点：{match_count}）")
            default_path = config.resource_path(rel_path)
            user_path = config.user_template_path(os.path.basename(rel_path))
            tpl_path = user_path if os.path.exists(user_path) else default_path
            img_refs["left"] = load_and_display(left_canvas, tpl_path)
            if current_file[0]:
                img_refs["right"] = load_and_display(right_canvas, current_file[0])
            prev_btn.config(state=tk.NORMAL if idx > 0 else tk.DISABLED)
            next_btn.config(state=tk.NORMAL if idx < total - 1 else tk.DISABLED)
            page_var.set(f"{idx + 1} / {total}")
        nav_frame = ttk.Frame(win)
        nav_frame.pack(fill=tk.X, padx=15, pady=(2, 2))
        prev_btn = ttk.Button(nav_frame, text="◀ 上一个", width=10,
                              command=lambda: [current_idx.__setitem__(0, current_idx[0] - 1), show_result(current_idx[0])])
        prev_btn.pack(side=tk.LEFT, padx=(0, 5))
        page_var = tk.StringVar()
        ttk.Label(nav_frame, textvariable=page_var, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=10)
        next_btn = ttk.Button(nav_frame, text="下一个 ▶", width=10,
                              command=lambda: [current_idx.__setitem__(0, current_idx[0] + 1), show_result(current_idx[0])])
        next_btn.pack(side=tk.LEFT, padx=(0, 8))
        upload_btn = ttk.Button(nav_frame, text="\U0001f4c1 上传图片", style="Accent.TButton",
                                command=lambda: _upload_image())
        upload_btn.pack(side=tk.LEFT)
        algo_frame = ttk.Frame(win)
        algo_frame.pack(fill=tk.X, padx=15, pady=(2, 5))
        algo_var_label = tk.StringVar(value="当前算法：ORB")
        ttk.Label(algo_frame, textvariable=algo_var_label, font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        def switch_algo():
            if current_algo[0] == "ORB":
                current_algo[0] = "pHash"
                algo_var_label.set("当前算法：感知哈希(pHash)")
                algo_btn.config(text="切换到 ORB")
            else:
                current_algo[0] = "ORB"
                algo_var_label.set("当前算法：ORB(特征匹配)")
                algo_btn.config(text="切换到 pHash")
            if current_file[0]:
                do_matching(current_file[0])
        algo_btn = ttk.Button(algo_frame, text="切换到 pHash", command=switch_algo, width=14)
        algo_btn.pack(side=tk.LEFT)
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 10))
        def on_save():
            results = current_results[0]
            idx = current_idx[0]
            if not results or idx >= len(results):
                messagebox.showwarning("提示", "没有可保存的匹配结果", parent=win)
                return
            score, match_count, ratio, var_name, rel_path, name = results[idx]
            try:
                os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
                save_path = config.user_template_path(os.path.basename(rel_path))
                shutil.copy2(current_file[0], save_path)
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
        def _upload_image():
            fp = filedialog.askopenfilename(title="选择要匹配的截图",
                filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")], parent=win)
            if not fp:
                return
            test_data = np.fromfile(fp, dtype=np.uint8)
            test_img = cv2.imdecode(test_data, cv2.IMREAD_GRAYSCALE)
            if test_img is None:
                messagebox.showerror("错误", "无法读取图片文件，请确认格式正确。\\n路径可能包含中文或特殊字符。", parent=win)
                return
            current_file[0] = fp
            do_matching(fp)
        ttk.Button(btn_frame, text="保存", style="Accent.TButton", command=on_save, width=12).pack(side=tk.RIGHT, padx=(0, 5))
        ttk.Button(btn_frame, text="取消", command=win.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))
        if current_file[0]:
            do_matching(current_file[0])
        else:
            left_canvas.create_text(140, 140, text="点击「上传图片」", fill="#999", font=("", 12))
            right_canvas.create_text(140, 140, text="开始匹配", fill="#999", font=("", 12))
        utils.restore_window_geometry(win, "match_geometry", "750x550", (700, 500))
