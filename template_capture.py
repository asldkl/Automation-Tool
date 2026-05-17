"""
模板截图向导
当检测到屏幕分辨率与模板不匹配时，引导用户重新截取所有模板图片
"""
import os
import tkinter as tk
from tkinter import ttk, messagebox
import config


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
        self.win.title("模板截图向导")
        self.win.geometry("700x520")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()

        self._build_ui()
        self._update_progress()

    def _build_ui(self):
        # 标题
        header = ttk.Frame(self.win)
        header.pack(fill=tk.X, padx=15, pady=(15, 5))
        ttk.Label(header, text="模板截图向导", font=('Microsoft YaHei UI', 14, 'bold')).pack(side=tk.LEFT)
        ttk.Label(header, text=f"当前分辨率：{self.resolution_key}",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(side=tk.RIGHT)

        ttk.Label(self.win, text="请按照提示逐个截取模板图片。点击「截图」后，用鼠标框选屏幕上的对应区域。",
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

            # 截图按钮
            btn = ttk.Button(row, text="截图", width=8,
                             command=lambda v=var_name, r=rel_path: self._start_capture(v, r))
            btn.pack(side=tk.RIGHT, padx=5)

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

    def _start_capture(self, var_name, rel_path):
        """启动区域截图：最小化向导，显示全屏遮罩供用户框选"""
        self.win.withdraw()
        # 延迟一下确保窗口完全隐藏
        self.win.after(300, lambda: self._do_capture(var_name, rel_path))

    def _do_capture(self, var_name, rel_path):
        """显示全屏半透明遮罩，用户拖拽框选区域"""
        overlay = tk.Toplevel()
        overlay.attributes('-fullscreen', True)
        overlay.attributes('-topmost', True)
        overlay.attributes('-alpha', 0.3)
        overlay.configure(bg='gray')
        overlay.cursor = "crosshair"

        # 用 Canvas 实现框选
        canvas = tk.Canvas(overlay, highlightthickness=0, bg='gray', cursor='cross')
        canvas.pack(fill=tk.BOTH, expand=True)

        start_x = [0]
        start_y = [0]
        rect_id = [None]

        def on_press(event):
            start_x[0] = event.x_root
            start_y[0] = event.y_root
            # 切换为不透明截图模式
            overlay.attributes('-alpha', 0)

        def on_drag(event):
            if rect_id[0]:
                canvas.delete(rect_id[0])
            # 在 overlay 关闭后截图，所以这里只做视觉反馈
            pass

        def on_release(event):
            overlay.destroy()
            end_x = event.x_root
            end_y = event.y_root

            # 计算选区
            x1 = min(start_x[0], end_x)
            y1 = min(start_y[0], end_y)
            x2 = max(start_x[0], end_x)
            y2 = max(start_y[0], end_y)
            w = x2 - x1
            h = y2 - y1

            if w < 10 or h < 10:
                print(f"⚠️ 选区太小，已跳过")
                self._show_again()
                return

            # 截图并保存
            try:
                import pyautogui
                screenshot = pyautogui.screenshot(region=(x1, y1, w, h))
                save_path = config.resource_path(rel_path)
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                screenshot.save(save_path)
                print(f"✅ 已保存模板：{rel_path} ({w}x{h})")

                # 更新状态
                self.status[var_name] = "done"
                if var_name in self.rows:
                    status_lbl, btn = self.rows[var_name]
                    status_lbl.config(text="✅")
            except Exception as e:
                print(f"❌ 截图保存失败：{e}")

            self._show_again()

        def on_escape(event):
            overlay.destroy()
            self._show_again()

        overlay.bind("<ButtonPress-1>", on_press)
        overlay.bind("<B1-Motion>", on_drag)
        overlay.bind("<ButtonRelease-1>", on_release)
        overlay.bind("<Escape>", on_escape)

    def _show_again(self):
        """截图完成后重新显示向导"""
        self._update_progress()
        utils_clear_cache()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def _skip_all(self):
        """跳过所有未完成的截图"""
        remaining = sum(1 for s in self.status.values() if s == "pending")
        if remaining > 0:
            if not messagebox.askyesno("确认跳过", f"还有 {remaining} 个模板未截图，确定跳过吗？"):
                return
        # 更新分辨率记录（即使跳过也记录当前分辨率，避免重复提示）
        config.save_template_resolution(self.resolution_key)
        self.win.destroy()

    def _finish(self):
        """完成截图向导"""
        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        if done < total:
            remaining = total - done
            if not messagebox.askyesno("确认完成", f"还有 {remaining} 个模板未截图。确定完成吗？\n未截图的模板将使用旧图片，可能识别失败。"):
                return
        # 保存新分辨率并清除模板缓存
        config.save_template_resolution(self.resolution_key)
        utils_clear_cache()
        self.win.destroy()
        messagebox.showinfo("完成", f"模板截图完成！共截取 {done}/{total} 个模板。")


def utils_clear_cache():
    """清除 utils 中的模板缓存，使新截图生效"""
    try:
        import utils
        utils.clear_template_cache()
    except Exception:
        pass
