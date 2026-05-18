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
        self.win.geometry("700x700")
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
        # 窗口居中
        self.win.update_idletasks()
        w = self.win.winfo_width()
        h = self.win.winfo_height()
        x = (self.win.winfo_screenwidth() - w) // 2
        y = (self.win.winfo_screenheight() - h) // 2
        self.win.geometry(f"{w}x{h}+{x}+{y}")

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
            # 预览按钮
            preview_btn = ttk.Button(row, text="预览", width=6,
                                     command=lambda r=rel_path, n=name: self._preview_template(r, n))
            preview_btn.pack(side=tk.RIGHT, padx=5)

            self.rows[var_name] = (status_lbl, btn, preview_btn)

            # 在最后一个产出项后添加分界线
            if var_name == produce_order[-1]:
                sep = ttk.Separator(self.scroll_frame, orient='horizontal')
                sep.pack(fill=tk.X, pady=8, padx=10)

        # 售卖物品管理区域
        sell_sep = ttk.Separator(self.win, orient='horizontal')
        sell_sep.pack(fill=tk.X, padx=15, pady=(5, 5))

        sell_frame = ttk.LabelFrame(self.win, text="  售卖物品（可上传多个，用于一键出售）  ", padding=8)
        sell_frame.pack(fill=tk.X, padx=15, pady=(0, 5))

        sell_list_frame = ttk.Frame(sell_frame)
        sell_list_frame.pack(fill=tk.X, pady=(0, 5))
        sell_scrollbar = ttk.Scrollbar(sell_list_frame, orient=tk.VERTICAL)
        self.sell_listbox = tk.Listbox(sell_list_frame, height=3,
                                       yscrollcommand=sell_scrollbar.set,
                                       selectmode=tk.SINGLE,
                                       font=('Microsoft YaHei UI', 9),
                                       bg='#fafbfc', fg='#2c3e50',
                                       selectbackground='#3498db',
                                       selectforeground='#ffffff',
                                       relief='flat', highlightthickness=1,
                                       highlightcolor='#dcdde1', borderwidth=0)
        sell_scrollbar.config(command=self.sell_listbox.yview)
        self.sell_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        sell_scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

        sell_btn_frame = ttk.Frame(sell_frame)
        sell_btn_frame.pack(fill=tk.X)
        ttk.Button(sell_btn_frame, text="添加物品", width=10,
                   command=self._add_sell_item).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(sell_btn_frame, text="删除选中", width=10,
                   command=self._delete_sell_item).pack(side=tk.LEFT)

        self._refresh_sell_list()

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
                status_lbl, btn, _ = self.rows[var_name]
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
            status_lbl, btn, _ = self.rows[var_name]
            status_lbl.config(text="⬜")
        self._update_progress()
        utils_clear_cache()

    def _preview_template(self, rel_path, name):
        """弹窗预览当前模板图片（优先显示用户自定义，否则显示内置默认）"""
        # 先检查用户自定义模板
        basename = os.path.basename(rel_path)
        user_path = config.user_template_path(basename)
        if os.path.exists(user_path):
            img_path = user_path
        else:
            # 内置模板路径
            built_in = config.resource_path(rel_path)
            if os.path.exists(built_in):
                img_path = built_in
            else:
                messagebox.showinfo("提示", f"暂无「{name}」的预览图片，请先上传模板图片。")
                return

        try:
            img = Image.open(img_path)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开图片：{e}")
            return

        # 限制预览窗口最大尺寸，等比缩放
        max_w, max_h = 800, 600
        orig_w, orig_h = img.size
        scale = min(max_w / orig_w, max_h / orig_h, 1.0)
        disp_w = int(orig_w * scale)
        disp_h = int(orig_h * scale)
        if scale < 1.0:
            img_resized = img.resize((disp_w, disp_h), Image.LANCZOS)
        else:
            img_resized = img

        # 判断来源
        is_user = os.path.exists(user_path)
        source_text = "用户自定义模板" if is_user else "内置默认模板"

        win = tk.Toplevel(self.win)
        win.title(f"预览 - {name}")
        win.resizable(False, False)
        win.transient(self.win)
        win.grab_set()
        # 设置窗口图标
        try:
            icon_path = config.resource_path("picture/icon.ico")
            if os.path.exists(icon_path):
                icon_img = Image.open(icon_path)
                win._icon_photo = ImageTk.PhotoImage(icon_img)
                win.iconphoto(False, win._icon_photo)
        except Exception:
            pass

        # 图片显示区
        photo = ImageTk.PhotoImage(img_resized)
        img_label = ttk.Label(win, image=photo)
        img_label.image = photo  # 保持引用防止被回收
        img_label.pack(padx=10, pady=10)

        # 信息栏
        info_frame = ttk.Frame(win)
        info_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(info_frame,
                  text=f"来源：{source_text}  |  原始尺寸：{orig_w}x{orig_h}",
                  font=('Microsoft YaHei UI', 9), foreground='#555').pack(side=tk.LEFT)
        ttk.Button(info_frame, text="关闭", command=win.destroy, width=8).pack(side=tk.RIGHT)

        # 居中预览窗口
        win.update_idletasks()
        pw = win.winfo_width()
        ph = win.winfo_height()
        px = (win.winfo_screenwidth() - pw) // 2
        py = (win.winfo_screenheight() - ph) // 2
        win.geometry(f"+{px}+{py}")

    def _refresh_sell_list(self):
        """刷新售卖物品列表显示"""
        self.sell_listbox.delete(0, tk.END)
        items = config.get_sell_items()
        for item in items:
            self.sell_listbox.insert(tk.END, os.path.basename(item))

    def _add_sell_item(self):
        """添加售卖物品图片"""
        filetypes = [("图片文件", "*.png;*.jpg;*.jpeg;*.bmp"), ("所有文件", "*.*")]
        src = filedialog.askopenfilename(title="选择售卖物品图片", filetypes=filetypes)
        if not src:
            return
        try:
            os.makedirs(config.SELL_ITEMS_DIR, exist_ok=True)
            basename = os.path.basename(src)
            save_path = os.path.join(config.SELL_ITEMS_DIR, basename)
            with open(src, "rb") as f_in, open(save_path, "wb") as f_out:
                f_out.write(f_in.read())
            self._refresh_sell_list()
        except Exception as e:
            messagebox.showerror("错误", f"添加失败：{e}")

    def _delete_sell_item(self):
        """删除选中的售卖物品"""
        sel = self.sell_listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要删除的物品。")
            return
        name = self.sell_listbox.get(sel[0])
        if not messagebox.askyesno("确认", f"确定删除售卖物品「{name}」？"):
            return
        try:
            os.remove(os.path.join(config.SELL_ITEMS_DIR, name))
        except Exception:
            pass
        self._refresh_sell_list()

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
