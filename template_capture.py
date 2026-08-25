"""
模板上传向导
当检测到屏幕分辨率与模板不匹配时，引导用户上传所有模板图片
"""
import os
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import config
import utils
from PIL import Image, ImageTk


class TemplateCaptureWizard:
    """模板截图向导主窗口"""

    def __init__(self, parent, resolution_key, app=None):
        self.parent = parent
        self.resolution_key = resolution_key
        self.app = app  # 可选，传入时显示出售测试按钮
        self.capture_list = config.TEMPLATE_CAPTURE_LIST
        self.status = {}  # var_name -> "pending" | "done"

        # 从设置中加载上次的上传状态
        settings = config.load_settings()
        saved_status = settings.get("template_upload_status", {})
        for item in self.capture_list:
            var_name = item[0]
            # 如果有保存的状态且模板文件存在，标记为已完成
            if saved_status.get(var_name) == "done":
                basename = os.path.basename(item[1])
                user_path = config.user_template_path(basename)
                if os.path.exists(user_path):
                    self.status[var_name] = "done"
                else:
                    self.status[var_name] = "pending"
            else:
                self.status[var_name] = "pending"

        self.win = tk.Toplevel(parent)
        self.win.title("模板上传向导")
        self.win.resizable(True, True)
        self.win.minsize(300, 400)
        self.win.transient(parent)
        self.win.grab_set()
        # 设置窗口图标
        utils.set_window_icon(self.win)

        # 先显示窗口，再异步构建 UI（避免窗口打开卡顿）
        self._build_header()
        self.win.after(10, self._build_body)
        # 恢复上次窗口大小和位置
        utils.restore_window_geometry(self.win, "template_capture_geometry", "550x700", (300, 400))
        # 关闭按钮保存窗口大小
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        """窗口关闭时保存大小和位置"""
        utils.save_window_geometry(self.win, "template_capture_geometry")
        utils.nav_pop(self.win)

    def _build_header(self):
        """立即构建：标题、进度条、底部按钮（窗口打开时立即显示）"""
        # 标题
        header = ttk.Frame(self.win)
        header.pack(fill=tk.X, padx=30, pady=(15, 5))
        ttk.Label(header, text="模板上传向导", font=('Microsoft YaHei UI', 14, 'bold')).pack(side=tk.LEFT)
        ttk.Label(header, text=f"当前分辨率：{self.resolution_key}",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(side=tk.RIGHT)

        ttk.Label(self.win, text="请按照提示逐个截取模板图片，点击「截取」",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(padx=30, anchor='w')

        # 进度
        prog_frame = ttk.Frame(self.win)
        prog_frame.pack(fill=tk.X, padx=30, pady=5)
        self.progress_label = ttk.Label(prog_frame, text="", font=('Microsoft YaHei UI', 9))
        self.progress_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(prog_frame, length=200, mode='determinate')
        self.progress_bar.pack(side=tk.LEFT, padx=(0, 8))
        # 初始进度显示
        done_init = sum(1 for s in self.status.values() if s == "done")
        total_init = len(self.status)
        self.progress_label.config(text=f"{done_init}/{total_init}")
        self.progress_bar["maximum"] = total_init
        self.progress_bar["value"] = done_init

        # 底部按钮（先 pack 到底部，确保始终可见）
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=30, pady=(5, 15))
        ttk.Button(btn_frame, text="一键重置", command=self._reset_all_templates, width=12).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="完成", command=self._finish, width=12).pack(side=tk.RIGHT, padx=(0, 8))


        # 加载中提示
        self._loading_label = ttk.Label(self.win, text="正在加载模板列表...",
                                        font=('Microsoft YaHei UI', 10), foreground='#999')
        self._loading_label.pack(expand=True)

    def _build_body(self):
        """延迟构建：滚动列表和模板行（窗口显示后再填充）"""
        # 移除加载提示
        if hasattr(self, '_loading_label') and self._loading_label:
            self._loading_label.destroy()
            self._loading_label = None

        # 滚动列表
        list_frame = ttk.Frame(self.win)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=5)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)

        self.scroll_frame.bind("<Configure>",
                               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定鼠标滚轮
        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ORB批量匹配上传按钮（列表顶部）
        orb_frame = ttk.Frame(self.scroll_frame)
        orb_frame.pack(fill=tk.X, pady=(5, 5))
        orb_btn = ttk.Button(orb_frame, text="🔍 图片匹配上传", style='Accent.TButton',
                             command=self._image_match_upload, width=30)
        orb_btn.pack(side=tk.LEFT, padx=2)
        ttk.Label(orb_frame, text="上传截图自动匹配最佳模板",
                  font=('Microsoft YaHei UI', 8), foreground='#7f8c8d').pack(side=tk.LEFT, padx=5)

        # 分组定义：(标题, 起始变量名集合)
        section_headers = {
            "ACCOUNT_SELECT": "wegame登录和游戏启动",
            "Observe": "游戏内导航",
            "Tech_Center": "设施操作及产出项",
            "MAKE": "制造操作",
            "EMAIL_MAIL": "邮箱货币",
            "Warehouse": "一键出售",
        }
        produce_vars = {"Produce_TechCenter", "Produce_ToolBench", "Produce_ArmorStation", "Produce_PharmacyStation"}
        optional_vars = {"ENSURE", "Observe"}
        produce_order = ["Produce_TechCenter", "Produce_ToolBench", "Produce_ArmorStation", "Produce_PharmacyStation"]
        self.rows = {}

        def _add_section_header(title):
            """添加分组标题和下划线"""
            header_frame = ttk.Frame(self.scroll_frame)
            header_frame.pack(fill=tk.X, pady=(10, 2), padx=2)
            ttk.Label(header_frame, text=title,
                      font=('Microsoft YaHei UI', 10, 'bold'),
                      foreground='#2c3e50').pack(side=tk.LEFT)
            ttk.Separator(self.scroll_frame, orient='horizontal').pack(fill=tk.X, pady=(0, 4), padx=2)

        seq_num = 0  # 序号计数器
        for i, (var_name, rel_path, name, hint) in enumerate(self.capture_list):
            # 在每个分组开始前添加标题
            if var_name in section_headers:
                _add_section_header(section_headers[var_name])

            is_produce = var_name in produce_vars
            is_optional = var_name in optional_vars
            if is_optional:
                row = tk.Frame(self.scroll_frame, bg='#E8F4FD', bd=1, relief='solid',
                               highlightbackground='#4A90D9', highlightthickness=2)
                row.pack(fill=tk.X, pady=2, padx=2)
            elif is_produce:
                row = tk.Frame(self.scroll_frame, bg='#FFF8F0', bd=1, relief='solid',
                               highlightbackground='#FF8C00', highlightthickness=2)
                row.pack(fill=tk.X, pady=2, padx=2)
            else:
                row = ttk.Frame(self.scroll_frame)
                row.pack(fill=tk.X, pady=2)

            # 序号
            seq_num += 1
            if is_optional:
                seq_lbl = tk.Label(row, text=f"{seq_num}.", width=3, font=('Microsoft YaHei UI', 9),
                                   bg='#E8F4FD', fg='#4A90D9', anchor='e')
            elif is_produce:
                seq_lbl = tk.Label(row, text=f"{seq_num}.", width=3, font=('Microsoft YaHei UI', 9),
                                   bg='#FFF8F0', fg='#B8860B', anchor='e')
            else:
                seq_lbl = ttk.Label(row, text=f"{seq_num}.", width=3, font=('Microsoft YaHei UI', 9),
                                   foreground='#999999', anchor='e')
            seq_lbl.pack(side=tk.LEFT, padx=(2, 2))

            # 状态图标
            if is_optional:
                status_lbl = tk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10),
                                      bg='#E8F4FD', fg='#4A90D9', anchor='center')
            elif is_produce:
                status_lbl = tk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10),
                                      bg='#FFF8F0', fg='#FF8C00', anchor='center')
            else:
                status_lbl = ttk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10),
                                      anchor='center')
            status_lbl.pack(side=tk.LEFT, padx=(0, 10))

            # 名称和提示
            if is_optional:
                info_frame = tk.Frame(row, bg='#E8F4FD')
                info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
                tk.Label(info_frame, text=f"{name}（非必需）", font=('Microsoft YaHei UI', 9, 'bold'),
                         bg='#E8F4FD', fg='#2C7BB6').pack(anchor='w')
                tk.Label(info_frame, text=hint, font=('Microsoft YaHei UI', 8),
                         bg='#E8F4FD', fg='#4A90D9').pack(anchor='w')
            elif is_produce:
                info_frame = tk.Frame(row, bg='#FFF8F0')
                info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
                tk.Label(info_frame, text=f"★ {name}", font=('Microsoft YaHei UI', 9, 'bold'),
                         bg='#FFF8F0', fg='#E67E22').pack(anchor='w')
                tk.Label(info_frame, text=hint, font=('Microsoft YaHei UI', 8),
                         bg='#FFF8F0', fg='#B8860B').pack(anchor='w')
            else:
                info_frame = ttk.Frame(row)
                info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
                ttk.Label(info_frame, text=name, font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w')
                ttk.Label(info_frame, text=hint, font=('Microsoft YaHei UI', 8), foreground='#7f8c8d').pack(anchor='w')

            # 模板设置按钮
            setting_btn = ttk.Button(row, text="模板设置", width=10,
                                     command=lambda v=var_name, r=rel_path, n=name: self._open_template_setting(v, r, n))
            setting_btn.pack(side=tk.RIGHT, padx=(90, 5))

            self.rows[var_name] = (status_lbl, setting_btn)

            # 应用已保存的上传状态
            if self.status.get(var_name) == "done":
                status_lbl.config(text="✅")

            # 在最后一个产出项后添加分界线
            if var_name == produce_order[-1]:
                sep = ttk.Separator(self.scroll_frame, orient='horizontal')
                sep.pack(fill=tk.X, pady=8, padx=10)

        # 售卖物品提示（已移至设置 → 售卖物品 Tab）
        sell_sep = ttk.Separator(self.win, orient='horizontal')
        sell_sep.pack(side=tk.BOTTOM, fill=tk.X, padx=30, pady=(5, 5))
        ttk.Label(self.win, text="售卖物品请在 设置 → 售卖物品 中管理",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(side=tk.BOTTOM, pady=(0, 5))

    def _update_progress(self):
        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        self.progress_label.config(text=f"{done}/{total}")
        self.progress_bar['maximum'] = total
        self.progress_bar['value'] = done

    def _start_upload(self, var_name, rel_path):
        """截取屏幕区域作为模板图片"""
        import pyautogui
        import tkinter as tk_overlay

        # 最小化向导窗口
        self.win.withdraw()
        time.sleep(0.3)

        # 全屏覆盖层
        overlay = tk_overlay.Toplevel(self.win)
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-alpha', 0.3)
        overlay.attributes('-topmost', True)
        overlay.configure(bg='black')
        overlay.config(cursor="crosshair")

        canvas = tk_overlay.Canvas(overlay, highlightthickness=0, bg='black')
        canvas.pack(fill=tk.BOTH, expand=True)

        hint = tk_overlay.Label(overlay, text="请拖动鼠标框选要识别的区域，按 Esc 取消",
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
            if x2 - x1 > 10 and y2 - y1 > 10:
                result = [x1, y1, x2 - x1, y2 - y1]
            overlay.destroy()

        def on_escape(event):
            overlay.destroy()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)

        self.win.wait_window(overlay)
        self.win.deiconify()

        if not result:
            return

        # 截图并保存
        try:
            x, y, w, h = result
            screenshot = pyautogui.screenshot(region=(x, y, w, h))
            os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
            save_path = config.user_template_path(os.path.basename(rel_path))
            screenshot.save(save_path)
            # 保存备份副本
            bak_path = save_path + ".bak"
            try:
                import shutil
                shutil.copy2(save_path, bak_path)
            except Exception:
                pass
            screenshot.close()

            # 更新状态
            self.status[var_name] = "done"
            if var_name in self.rows:
                status_lbl, _ = self.rows[var_name]
                status_lbl.config(text="✅")
        except Exception as e:
            messagebox.showerror("错误", f"截图失败：{e}")

        self._update_progress()
        utils_clear_cache()

    def _restore_template(self, var_name, rel_path):
        """恢复指定模板为内置默认图片"""
        user_path = config.user_template_path(os.path.basename(rel_path))

        if not os.path.exists(user_path):
            messagebox.showinfo("提示", "当前使用的是内置默认图片，无需恢复。")
            return
        if not messagebox.askyesno("确认", "确定恢复该模板为内置默认图片？"):
            return

        # 删除用户自定义模板
        try:
            if os.path.exists(user_path):
                os.remove(user_path)
        except Exception:
            pass

        # 更新状态为未完成
        self.status[var_name] = "pending"
        if var_name in self.rows:
            status_lbl, _ = self.rows[var_name]
            status_lbl.config(text="⬜")
        self._update_progress()
        utils_clear_cache()


    def _set_dialog_icon(self, dialog):
        """为对话框设置图标"""
        utils.set_window_icon(dialog)

    def _open_template_setting(self, var_name, rel_path, name):
        """打开模板设置窗口：预览图片 + OCR识别/恢复默认/上传 按钮"""
        # 查找图片路径
        basename = os.path.basename(rel_path)
        user_path = config.user_template_path(basename)
        if os.path.exists(user_path):
            img_path = user_path
            source_text = "用户自定义模板"
        else:
            img_path = config.resource_path(rel_path)
            if os.path.exists(img_path):
                source_text = "内置默认模板"
            else:
                img_path = None
                source_text = "暂无模板"

        # 加载图片
        photo = None
        img_resized = None
        orig_w = orig_h = 0
        if img_path:
            try:
                img = Image.open(img_path)
                orig_w, orig_h = img.size
                max_w, max_h = 500, 400
                scale = min(max_w / orig_w, max_h / orig_h, 1.0)
                disp_w = int(orig_w * scale)
                disp_h = int(orig_h * scale)
                img_resized = img.resize((disp_w, disp_h), Image.LANCZOS) if scale < 1.0 else img
                photo = ImageTk.PhotoImage(img_resized)
            except Exception as e:
                source_text = f"图片加载失败：{e}"

        # 创建窗口
        win = tk.Toplevel(self.win)
        win.title(f"模板设置 - {name}")
        win.resizable(False, False)
        win.transient(self.win)
        win.grab_set()
        self._set_dialog_icon(win)

        # 图片显示区
        if photo:
            img_label = ttk.Label(win, image=photo)
            img_label.image = photo
            img_label.pack(padx=10, pady=(10, 5))
        else:
            ttk.Label(win, text="暂无预览图片", font=('Microsoft YaHei UI', 10),
                      foreground='#999').pack(padx=10, pady=(30, 5))

        # 信息栏
        info_text = f"来源：{source_text}"
        if orig_w and orig_h:
            info_text += f"  |  尺寸：{orig_w}x{orig_h}"
        ttk.Label(win, text=info_text, font=('Microsoft YaHei UI', 9),
                  foreground='#7f8c8d').pack(padx=10, pady=(0, 8))

        # 按钮区
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        def do_upload():
            win.destroy()
            self._start_upload(var_name, rel_path)

        def do_restore():
            win.destroy()
            self._restore_template(var_name, rel_path)

        def do_test():
            """测试当前模板的识别置信度"""
            self._test_template_confidence(win, rel_path, name)

        # 不可文字识别的模板不显示 OCR 按钮
        ttk.Button(btn_frame, text="恢复默认", command=do_restore, width=10).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="测试", command=do_test, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="截取", command=do_upload, width=8).pack(side=tk.RIGHT)

        # 居中
        win.update_idletasks()
        pw = win.winfo_width()
        ph = win.winfo_height()
        px = (win.winfo_screenwidth() - pw) // 2
        py = (win.winfo_screenheight() - ph) // 2
        win.geometry(f"+{px}+{py}")

    def _test_template_confidence(self, parent_win, rel_path, name):
        """测试单个模板的识别置信度，弹窗显示结果（截图前先隐藏窗口避免干扰）"""
        import cv2
        try:
            # 截图前隐藏窗口，避免模板设置窗口本身遮挡游戏画面
            parent_win.withdraw()
            parent_win.update_idletasks()
            time.sleep(0.3)

            screen = utils._screenshot_gray()
            if screen is None:
                messagebox.showerror("测试失败", "截图失败", parent=parent_win)
                return

            template = utils._imread_unicode(config.resolve_template_path(rel_path))
            if template is None:
                messagebox.showerror("测试失败", f"模板加载失败: {rel_path}", parent=parent_win)
                return
            if len(template.shape) == 3:
                template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            confidence = float(config.load_settings().get("confidence", 0.7))
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val >= confidence:
                messagebox.showinfo(
                    "测试结果",
                    f"✅ {name}\n\n"
                    f"置信度: {max_val:.4f}\n"
                    f"阈值: {confidence:.2f}\n"
                    f"坐标: ({max_loc[0]}, {max_loc[1]})\n\n"
                    f"识别成功！",
                    parent=parent_win)
            else:
                messagebox.showwarning(
                    "测试结果",
                    f"❌ {name}\n\n"
                    f"置信度: {max_val:.4f}\n"
                    f"阈值: {confidence:.2f}\n"
                    f"坐标: ({max_loc[0]}, {max_loc[1]})\n\n"
                    f"未达到阈值，识别可能失败。\n"
                    f"可在设置中降低置信度或重新截取模板。",
                    parent=parent_win)
        except Exception as e:
            messagebox.showerror("测试失败", f"识别异常: {e}", parent=parent_win)
        finally:
            try:
                parent_win.deiconify()
                parent_win.lift()
            except Exception:
                pass

    def _image_match_upload(self):
        self._show_match_results()

    def _run_matching(self, img_data):
        """使用 pHash 感知哈希算法进行图片匹配"""
        import cv2
        import numpy as np
        user_img = cv2.imdecode(img_data, cv2.IMREAD_GRAYSCALE)
        if user_img is None:
            return []

        def _phash(img):
            img32 = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
            img32f = np.float32(img32)
            dct = cv2.dct(img32f)
            dct_low = dct[:8, :8]
            avg = np.mean(dct_low[1:])
            return np.ravel(dct_low > avg).astype(np.uint8)

        hash_user = _phash(user_img)
        results = []
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
        import cv2, shutil, numpy as np
        from PIL import Image, ImageTk
        current_idx = [0]
        current_file = [file_path]
        current_results = [[]]
        win = tk.Toplevel(self.win)
        win.title("图片匹配")
        win.resizable(True, True)
        win.minsize(680, 520)
        win.transient(self.win)
        win.grab_set()
        utils.set_window_icon(win)

        conf_var = tk.StringVar(value="请上传图片开始匹配")
        progress_var = tk.StringVar(value="已保存: 0/0")
        ttk.Label(win, textvariable=progress_var, font=("Microsoft YaHei UI", 9), foreground="#999").pack(pady=(0, 2), padx=15, anchor="w")
        ttk.Label(win, textvariable=conf_var, font=("Microsoft YaHei UI", 12, "bold"), foreground="#e67e22").pack(pady=(0, 2), padx=15, anchor="w")
        img_frame = ttk.Frame(win)
        img_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        left_frame = ttk.LabelFrame(img_frame, text=" 匹配到的模板 ", padding=5)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        right_frame = ttk.LabelFrame(img_frame, text=" 你上传的图片 ", padding=5)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        left_canvas = tk.Canvas(left_frame, width=160, height=140, bg="#f5f5f5", highlightthickness=0)
        left_canvas.pack(fill=tk.BOTH, expand=True)
        right_canvas = tk.Canvas(right_frame, width=160, height=140, bg="#f5f5f5", highlightthickness=0)
        right_canvas.pack(fill=tk.BOTH, expand=True)
        img_refs = {}
        def _cx(cv):
            try:
                cv.update_idletasks()
                return max(cv.winfo_width() // 2, 60)
            except Exception:
                return 80
        def _cy(cv):
            try:
                cv.update_idletasks()
                return max(cv.winfo_height() // 2, 50)
            except Exception:
                return 70
        def load_and_display(cv, img_path, max_size=(180, 180)):
            try:
                pil_img = Image.open(img_path)
                pil_img.thumbnail(max_size, Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(pil_img)
                cv.delete("all")
                cv.create_image(_cx(cv), _cy(cv), image=tk_img, anchor=tk.CENTER)
                return tk_img
            except Exception:
                cv.delete("all")
                cv.create_text(_cx(cv), _cy(cv), text="待上传", fill="#999", font=("", 12), anchor=tk.CENTER)
                return None
        def do_matching(fp):
            if not fp:
                return
            img_data = np.fromfile(fp, dtype=np.uint8)
            results = self._run_matching(img_data)
            current_results[0] = results
            done = sum(1 for s in self.status.values() if s == "done")
            total = len(self.status)
            progress_var.set(f"已保存: {done}/{total}")
            if results:
                current_idx[0] = 0
                show_result(0)
            else:
                conf_var.set("pHash：未匹配到任何模板，请上传其他图片")
                left_canvas.delete("all")
                left_canvas.create_text(_cx(left_canvas), _cy(left_canvas), text="无匹配", fill="#999", font=("", 12), anchor=tk.CENTER)
                right_canvas.delete("all")
                right_canvas.create_text(_cx(right_canvas), _cy(right_canvas), text="待上传", fill="#999", font=("", 12), anchor=tk.CENTER)
        def show_result(idx):
            results = current_results[0]
            total = len(results)
            if not results or idx < 0 or idx >= total:
                return
            score, match_count, ratio, var_name, name, rel_path = results[idx]
            conf_var.set(f"{name}  —  相似度：{score:.1f}（汉明距离：{64 - match_count}）")
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
        nav_frame.pack(fill=tk.X, padx=15, pady=(8, 8))
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
        upload_btn.pack(side=tk.LEFT, padx=(0, 5))

        pending_files = []
        def _load_next():
            if not pending_files:
                return
            fp = pending_files.pop(0)
            if fp is None:
                pending_files.clear()
                save_btn.config(text="保存")
                return
            test_data = np.fromfile(fp, dtype=np.uint8)
            test_img = cv2.imdecode(test_data, cv2.IMREAD_GRAYSCALE)
            if test_img is None:
                _load_next()
                return
            current_file[0] = fp
            do_matching(fp)


        def on_save():
            results = current_results[0]
            idx = current_idx[0]
            if not results or idx >= len(results):
                messagebox.showwarning("提示", "没有可保存的匹配结果", parent=win)
                return
            score, match_count, ratio, var_name, name, rel_path = results[idx]
            os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
            save_path = config.user_template_path(os.path.basename(rel_path))
            shutil.copy2(current_file[0], save_path)
            self.status[var_name] = "done"
            if var_name in self.rows:
                status_lbl, _ = self.rows[var_name]
                status_lbl.config(text="✅")
            self._update_progress()
            self._save_status()
            utils_clear_cache()
            # 更新进度显示
            done = sum(1 for s in self.status.values() if s == "done")
            total = len(self.status)
            progress_var.set(f"已保存: {done}/{total}")
            conf_var.set(f"✅ 保存成功：{name}")
            # 清空界面回到初始状态
            current_results[0] = []
            current_file[0] = None
            left_canvas.delete("all")
            left_canvas.create_text(_cx(left_canvas), _cy(left_canvas), text="待上传", fill="#999", font=("", 12), anchor=tk.CENTER)
            right_canvas.delete("all")
            right_canvas.create_text(_cx(right_canvas), _cy(right_canvas), text="待上传", fill="#999", font=("", 12), anchor=tk.CENTER)
            page_var.set("")
            prev_btn.config(state=tk.DISABLED)
            next_btn.config(state=tk.DISABLED)
            _load_next()
        save_btn = ttk.Button(nav_frame, text="保存", style="Accent.TButton", command=on_save, width=12)
        save_btn.pack(side=tk.RIGHT, padx=(0, 5))
        ttk.Button(nav_frame, text="取消", command=win.destroy, width=10).pack(side=tk.RIGHT, padx=(0, 5))

        def _upload_image():
            """上传图片/文件夹进行模板匹配测试"""
            choice = messagebox.askyesno("上传方式",
                "选择「是」上传单个或多个图片（文件选择）\n选择「否」选择整个文件夹（批量匹配）",
                parent=win)
            files = []
            if choice:
                fps = filedialog.askopenfilenames(title="选择要匹配的截图",
                    filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")], parent=win)
                if not fps:
                    return
                files = list(fps)
            else:
                folder = filedialog.askdirectory(title="选择包含截图的文件夹", parent=win)
                if not folder:
                    return
                import os
                ext = (".png", ".jpg", ".jpeg", ".bmp")
                files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                         if f.lower().endswith(ext)]
                if not files:
                    messagebox.showinfo("提示", "文件夹中没有找到图片文件", parent=win)
                    return
            pending_files.clear()
            pending_files.extend(files)
            pending_files.append(None)
            _load_next()
            save_btn.config(text="保存并下一张")
        if current_file[0]:
            do_matching(current_file[0])
        else:
            done = sum(1 for s in self.status.values() if s == "done")
            total = len(self.status)
            progress_var.set(f"已保存: {done}/{total}")
            left_canvas.create_text(_cx(left_canvas), _cy(left_canvas), text="待上传", fill="#999", font=("", 12), anchor=tk.CENTER)
            right_canvas.create_text(_cx(right_canvas), _cy(right_canvas), text="待上传", fill="#999", font=("", 12), anchor=tk.CENTER)
        utils.bind_window_geometry(win, "match_geometry", "720x540", (680, 520))

    def _save_status(self):
        """保存当前上传状态到设置文件"""
        settings = config.load_settings()
        settings["template_upload_status"] = dict(self.status)
        config.save_settings(settings)

    def _reset_all_templates(self):
        """一键重置：清除所有 OCR 配置和用户上传的模板图片"""
        if not messagebox.askyesno("确认重置",
                                   "确定要重置所有模板吗？\n\n"
                                   "将清除：\n"
                                   "- 所有用户上传的模板图片\n"
                                   "- 所有 OCR 识别配置\n"
                                   "- 全局文本配置\n\n"
                                   "此操作不可撤销。"):
            return

        settings = config.load_settings()

        # 清除所有用户上传的模板图片
        user_dir = config.USER_TEMPLATE_DIR
        if os.path.exists(user_dir):
            for f in os.listdir(user_dir):
                try:
                    os.remove(os.path.join(user_dir, f))
                except Exception:
                    pass

        # 清除所有 OCR 配置（含全局开关）
        settings["global_text_enabled"] = False
        config.save_settings(settings)

        # 重置所有状态为未完成
        for var_name in self.status:
            self.status[var_name] = "pending"
            if var_name in self.rows:
                status_lbl, _ = self.rows[var_name]
                status_lbl.config(text="⬜")

        self._update_progress()
        utils_clear_cache()
        messagebox.showinfo("重置完成", "所有模板已恢复默认。")

    def _skip_all(self):
        """跳过所有未完成的上传"""
        remaining = sum(1 for s in self.status.values() if s == "pending")
        if remaining > 0:
            if not messagebox.askyesno("确认跳过", f"还有 {remaining} 个模板未上传，确定跳过吗？"):
                return
        # 保存窗口大小和位置
        utils.save_window_geometry(self.win, "template_capture_geometry")
        # 保存上传状态（保留已完成的标记，方便下次查看）
        self._save_status()
        # 更新分辨率记录（即使跳过也记录当前分辨率，避免重复提示）
        config.save_template_resolution(self.resolution_key)
        utils.nav_pop(self.win)

    def _finish(self):
        """完成模板上传"""
        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        if done < total:
            remaining = total - done
            if not messagebox.askyesno("确认完成", f"还有 {remaining} 个模板未上传。确定完成吗？\n未上传的模板将使用旧图片，可能识别失败。"):
                return
        # 保存窗口大小和位置
        utils.save_window_geometry(self.win, "template_capture_geometry")
        # 保存上传状态
        self._save_status()
        # 保存新分辨率并清除模板缓存
        config.save_template_resolution(self.resolution_key)
        utils_clear_cache()
        utils.nav_pop(self.win)
        messagebox.showinfo("完成", f"模板上传完成！共上传 {done}/{total} 个模板。")


def utils_clear_cache():
    """清除 utils 中的模板缓存，使新上传的图片生效"""
    try:
        import utils
        utils.clear_template_cache()
    except Exception:
        pass
