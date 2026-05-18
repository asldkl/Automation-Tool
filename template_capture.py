"""
模板上传向导
当检测到屏幕分辨率与模板不匹配时，引导用户上传所有模板图片
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import config
from PIL import Image, ImageTk


class TemplateCaptureWizard:
    """模板截图向导主窗口"""

    def __init__(self, parent, resolution_key):
        self.parent = parent
        self.resolution_key = resolution_key
        self.capture_list = config.TEMPLATE_CAPTURE_LIST + config.QQ_TEMPLATE_CAPTURE_LIST
        self.status = {}  # var_name -> "pending" | "done"

        for item in self.capture_list:
            self.status[item[0]] = "pending"

        self.win = tk.Toplevel(parent)
        self.win.title("模板上传向导")
        self.win.geometry("700x520")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        # 设置窗口图标
        try:
            icon_path = config.resource_path("picture/icon.ico")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                self._icon_photo = ImageTk.PhotoImage(icon_img)
                self.win.iconphoto(False, self._icon_photo)
        except Exception:
            pass

        self._build_ui()
        self._update_progress()

    def _build_ui(self):
        # 标题
        header = ttk.Frame(self.win)
        header.pack(fill=tk.X, padx=15, pady=(15, 5))
        ttk.Label(header, text="模板上传向导", font=('Microsoft YaHei UI', 14, 'bold')).pack(side=tk.LEFT)
        ttk.Label(header, text=f"当前分辨率：{self.resolution_key}",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(side=tk.RIGHT)

        ttk.Label(self.win, text="请按照提示逐个上传模板图片。点击「上传」后，从本地选择对应的图片文件。",
                  font=('Microsoft YaHei UI', 9), foreground='#555').pack(padx=15, anchor='w')

        # 进度
        prog_frame = ttk.Frame(self.win)
        prog_frame.pack(fill=tk.X, padx=15, pady=5)
        self.progress_label = ttk.Label(prog_frame, text="", font=('Microsoft YaHei UI', 9))
        self.progress_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(prog_frame, length=200, mode='determinate')
        self.progress_bar.pack(side=tk.RIGHT)

        # 滚动列表
        list_frame = ttk.Frame(self.win)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

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
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 为每个模板创建一行
        produce_vars = {"Produce_TechCenter", "Produce_ToolBench", "Produce_ArmorStation", "Produce_PharmacyStation"}
        produce_order = ["Produce_TechCenter", "Produce_ToolBench", "Produce_ArmorStation", "Produce_PharmacyStation"]
        self.rows = {}
        for i, (var_name, rel_path, name, hint) in enumerate(self.capture_list):
            is_produce = var_name in produce_vars
            if is_produce:
                row = tk.Frame(self.scroll_frame, bg='#FFF8F0', bd=1, relief='solid',
                               highlightbackground='#FF8C00', highlightthickness=2)
                row.pack(fill=tk.X, pady=2, padx=2)
            else:
                row = ttk.Frame(self.scroll_frame)
                row.pack(fill=tk.X, pady=2)

            # 状态图标
            if is_produce:
                status_lbl = tk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10),
                                      bg='#FFF8F0', fg='#FF8C00')
            else:
                status_lbl = ttk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10))
            status_lbl.pack(side=tk.LEFT, padx=(0, 5))

            # 名称和提示
            if is_produce:
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
                ttk.Label(info_frame, text=hint, font=('Microsoft YaHei UI', 8), foreground='#888').pack(anchor='w')

            # 上传按钮
            btn = ttk.Button(row, text="上传", width=8,
                             command=lambda v=var_name, r=rel_path: self._start_upload(v, r))
            btn.pack(side=tk.RIGHT, padx=5)
            # 恢复默认按钮
            restore_btn = ttk.Button(row, text="恢复默认", width=8,
                                     command=lambda v=var_name, r=rel_path: self._restore_template(v, r))
            restore_btn.pack(side=tk.RIGHT, padx=5)

            self.rows[var_name] = (status_lbl, btn)

            # 在最后一个产出项后添加分界线
            if var_name == produce_order[-1]:
                sep = ttk.Separator(self.scroll_frame, orient='horizontal')
                sep.pack(fill=tk.X, pady=8, padx=10)

        # 底部按钮
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(fill=tk.X, padx=15, pady=(5, 15))
        ttk.Button(btn_frame, text="全部跳过", command=self._skip_all, width=12).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="完成", command=self._finish, width=12).pack(side=tk.RIGHT)

    def _update_progress(self):
        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        self.progress_label.config(text=f"已完成 {done}/{total}")
        self.progress_bar['maximum'] = total
        self.progress_bar['value'] = done

    def _start_upload(self, var_name, rel_path):
        """打开文件对话框让用户选择模板图片"""
        filetypes = [("图片文件", "*.png;*.jpg;*.jpeg;*.bmp"), ("所有文件", "*.*")]
        src = filedialog.askopenfilename(title="选择模板图片", filetypes=filetypes)
        if not src:
            return

        try:
            os.makedirs(config.USER_TEMPLATE_DIR, exist_ok=True)
            save_path = config.user_template_path(os.path.basename(rel_path))
            with open(src, "rb") as f_in, open(save_path, "wb") as f_out:
                f_out.write(f_in.read())

            # 更新状态
            self.status[var_name] = "done"
            if var_name in self.rows:
                status_lbl, btn = self.rows[var_name]
                status_lbl.config(text="✅")
        except Exception as e:
            messagebox.showerror("错误", f"上传失败：{e}")

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
        try:
            os.remove(user_path)
        except Exception:
            pass
        # 更新状态为未完成
        self.status[var_name] = "pending"
        if var_name in self.rows:
            status_lbl, btn = self.rows[var_name]
            status_lbl.config(text="⬜")
        self._update_progress()
        utils_clear_cache()

    def _skip_all(self):
        """跳过所有未完成的上传"""
        remaining = sum(1 for s in self.status.values() if s == "pending")
        if remaining > 0:
            if not messagebox.askyesno("确认跳过", f"还有 {remaining} 个模板未上传，确定跳过吗？"):
                return
        # 更新分辨率记录（即使跳过也记录当前分辨率，避免重复提示）
        config.save_template_resolution(self.resolution_key)
        self.win.destroy()

    def _finish(self):
        """完成模板上传"""
        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        if done < total:
            remaining = total - done
            if not messagebox.askyesno("确认完成", f"还有 {remaining} 个模板未上传。确定完成吗？\n未上传的模板将使用旧图片，可能识别失败。"):
                return
        # 保存新分辨率并清除模板缓存
        config.save_template_resolution(self.resolution_key)
        utils_clear_cache()
        self.win.destroy()
        messagebox.showinfo("完成", f"模板上传完成！共上传 {done}/{total} 个模板。")


def utils_clear_cache():
    """清除 utils 中的模板缓存，使新上传的图片生效"""
    try:
        import utils
        utils.clear_template_cache()
    except Exception:
        pass
