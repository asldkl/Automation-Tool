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


# 全局 OCR 文本默认配置（var_name -> 默认识别文本，None 表示不可文字识别）
GLOBAL_TEXT_DEFAULTS = {
    "Produce_TechCenter": ("技术中心产出项", "多用途战术增高架"),
    "Produce_ToolBench": ("工作台产出项", "5.7x28mm SS190"),
    "Produce_ArmorStation": ("防具台产出项", "精英防弹背心"),
    "Produce_PharmacyStation": ("制药台产出项", "体能强化剂"),
    "DELTA_GAME_ICON": ("三角洲游戏图标", "三角洲行动"),
    "Hazard_Operations": ("烽火地带入口", "烽火地带"),
    "Special_Ops": ("特勤处入口", "特勤处"),
    "Tech_Center": ("技术中心", "技术中心"),
    "Tool_Bench": ("工作台", "工作台"),
    "Armor_Station": ("防具台", "防具台"),
    "Pharmacy_Station": ("制药台", "制药台"),
    "MAKE": ("制造按钮", "制造"),
    "Produce": ("产出按钮", "生成"),
    "Collect": ("收取按钮", "收获"),
    "Auto_fill": ("一键补齐按钮", "一键补齐"),
    "Claim_Reward": ("领取奖励按钮", "获得奖励"),
    "COIN_GAME": ("游戏币购买按钮", None),
    "Warehouse": ("仓库入口", "仓库"),
    "Sell": ("出售按钮", "出售"),
    "List_Item": ("上架按钮", "上架"),
    "Discount": ("降价按钮", None),
    "Confirm_Listing": ("确认上架按钮", "上架"),
    "EMAIL_MAIL": ("邮箱入口", None),
    "EMAIL_TRADE_HOUSE": ("交易中心入口", "交易行"),
    "EMAIL_CLAIM_ALL": ("全部领取按钮", "全部领取"),
    "EMAIL_RECEIVE_COMPLETED": ("领取完成确认按钮", "领取完成"),
    "DELTA_LAUNCH_BTN": ("启动游戏按钮", "启动"),
    "ACCOUNT_SELECT": ("WeGame账号选择框", None),
    "IMAGE_INPUT_FIELD": ("WeGame密码输入框", "请输入密码"),
    "SIGN_IN": ("WeGame登录确认按钮", "登录"),
    "LOGIN_AGAIN": ("重新登录按钮", "重新登录"),
}


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
        ocr_configs = settings.get("ocr_configs", {})

        for item in self.capture_list:
            var_name = item[0]
            # 如果有 OCR 配置（含有效文本），直接标记为已完成
            if var_name in ocr_configs and ocr_configs[var_name].get("text"):
                self.status[var_name] = "done"
            # 如果有保存的状态且模板文件存在，标记为已完成
            elif saved_status.get(var_name) == "done":
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
        self.win.destroy()

    def _build_header(self):
        """立即构建：标题、进度条、底部按钮（窗口打开时立即显示）"""
        # 标题
        header = ttk.Frame(self.win)
        header.pack(fill=tk.X, padx=30, pady=(15, 5))
        ttk.Label(header, text="模板上传向导", font=('Microsoft YaHei UI', 14, 'bold')).pack(side=tk.LEFT)
        ttk.Label(header, text=f"当前分辨率：{self.resolution_key}",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(side=tk.RIGHT)

        ttk.Label(self.win, text="请按照提示逐个截取模板图片。点击「截取」后，在屏幕上框选需要识别的区域。",
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack(padx=30, anchor='w')

        # 进度
        prog_frame = ttk.Frame(self.win)
        prog_frame.pack(fill=tk.X, padx=30, pady=5)
        self.progress_label = ttk.Label(prog_frame, text="", font=('Microsoft YaHei UI', 9))
        self.progress_label.pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(prog_frame, length=200, mode='determinate')
        self.progress_bar.pack(side=tk.RIGHT)

        # 底部按钮（先 pack 到底部，确保始终可见）
        btn_frame = ttk.Frame(self.win)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=30, pady=(5, 15))
        ttk.Button(btn_frame, text="一键重置", command=self._reset_all_templates, width=12).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="完成", command=self._finish, width=12).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btn_frame, text="全局OCR设置", command=self._open_global_ocr_settings, width=14).pack(anchor='center')

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

        # 分组定义：(标题, 起始变量名集合)
        section_headers = {
            "Produce_TechCenter": "产出项设置",
            "DELTA_GAME_ICON": "WeGame 登录",
            "Hazard_Operations": "游戏内导航",
            "Tech_Center": "设施操作",
            "MAKE": "制造操作",
            "Warehouse": "一键出售",
            "EMAIL_MAIL": "邮箱货币",
        }
        produce_vars = {"Produce_TechCenter", "Produce_ToolBench", "Produce_ArmorStation", "Produce_PharmacyStation"}
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
            if is_produce:
                row = tk.Frame(self.scroll_frame, bg='#FFF8F0', bd=1, relief='solid',
                               highlightbackground='#FF8C00', highlightthickness=2)
                row.pack(fill=tk.X, pady=2, padx=2)
            else:
                row = ttk.Frame(self.scroll_frame)
                row.pack(fill=tk.X, pady=2)

            # 序号
            seq_num += 1
            if is_produce:
                seq_lbl = tk.Label(row, text=f"{seq_num}.", width=3, font=('Microsoft YaHei UI', 9),
                                   bg='#FFF8F0', fg='#B8860B', anchor='e')
            else:
                seq_lbl = ttk.Label(row, text=f"{seq_num}.", width=3, font=('Microsoft YaHei UI', 9),
                                   foreground='#999999', anchor='e')
            seq_lbl.pack(side=tk.LEFT, padx=(2, 2))

            # 状态图标
            if is_produce:
                status_lbl = tk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10),
                                      bg='#FFF8F0', fg='#FF8C00', anchor='center')
            else:
                status_lbl = ttk.Label(row, text="⬜", width=3, font=('Segoe UI Emoji', 10),
                                      anchor='center')
            status_lbl.pack(side=tk.LEFT, padx=(0, 10))

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
                ttk.Label(info_frame, text=hint, font=('Microsoft YaHei UI', 8), foreground='#7f8c8d').pack(anchor='w')

            # 模板设置按钮
            setting_btn = ttk.Button(row, text="模板设置", width=10,
                                     command=lambda v=var_name, r=rel_path, n=name: self._open_template_setting(v, r, n))
            setting_btn.pack(side=tk.RIGHT, padx=(30, 5))

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

    def _refresh_status_from_ocr_configs(self):
        """根据 ocr_configs 和 global_ocr_texts 刷新所有模板的状态图标"""
        settings = config.load_settings()
        ocr_configs = settings.get("ocr_configs", {})
        global_texts = settings.get("global_ocr_texts", {})
        for item in self.capture_list:
            var_name = item[0]
            has_text = (var_name in ocr_configs and ocr_configs[var_name].get("text")) or \
                       (var_name in global_texts and global_texts[var_name])
            if has_text:
                self.status[var_name] = "done"
                if var_name in self.rows:
                    status_lbl, _ = self.rows[var_name]
                    status_lbl.config(text="✅")
        self._update_progress()

    def _update_progress(self):
        done = sum(1 for s in self.status.values() if s == "done")
        total = len(self.status)
        self.progress_label.config(text=f"已完成 {done}/{total}")
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
        """恢复指定模板为内置默认图片，并清除 OCR 配置"""
        user_path = config.user_template_path(os.path.basename(rel_path))
        has_ocr = False
        settings = config.load_settings()
        ocr_configs = settings.get("ocr_configs", {})
        if var_name in ocr_configs:
            has_ocr = True

        if not os.path.exists(user_path) and not has_ocr:
            messagebox.showinfo("提示", "当前使用的是内置默认图片，无需恢复。")
            return
        if not messagebox.askyesno("确认", "确定恢复该模板为内置默认图片？\n将同时清除 OCR 识别配置。"):
            return

        # 删除用户自定义模板
        try:
            if os.path.exists(user_path):
                os.remove(user_path)
        except Exception:
            pass

        # 清除 OCR 配置
        if var_name in ocr_configs:
            del ocr_configs[var_name]
            settings["ocr_configs"] = ocr_configs
            config.save_settings(settings)

        # 更新状态为未完成
        self.status[var_name] = "pending"
        if var_name in self.rows:
            status_lbl, _ = self.rows[var_name]
            status_lbl.config(text="⬜")
        self._update_progress()
        utils_clear_cache()

    def _setup_ocr(self, var_name, name):
        """设置 OCR 识别区域和目标文本（全局模式下跳过区域选择）"""
        # 加载现有配置
        settings = config.load_settings()
        ocr_configs = settings.get("ocr_configs", {})
        existing = ocr_configs.get(var_name, {})

        global_enabled = settings.get("global_ocr_enabled", False)
        global_region = settings.get("global_ocr_region", [0, 0, 0, 0])

        # 决定识别区域：全局模式使用全局区域，否则让用户框选
        if global_enabled and global_region[2] > 0 and global_region[3] > 0:
            result_region = tuple(global_region)
        else:
            # 释放 grab 并隐藏当前窗口，让覆盖层能接收鼠标事件
            self.win.grab_release()
            self.win.withdraw()
            import time
            time.sleep(0.3)

            # 创建全屏半透明覆盖层
            overlay = tk.Toplevel(self.win)
            overlay.attributes('-fullscreen', True)
            overlay.attributes('-alpha', 0.3)
            overlay.attributes('-topmost', True)
            overlay.configure(bg='black')
            overlay.cursor = "crosshair"

            canvas = tk.Canvas(overlay, highlightthickness=0, bg='black')
            canvas.pack(fill=tk.BOTH, expand=True)

            # 提示标签
            hint_label = tk.Label(overlay, text="请拖动鼠标框选 OCR 识别区域，按 Esc 取消",
                                  font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
            hint_label.place(relx=0.5, rely=0.05, anchor='center')

            rect_id = None
            start_x = start_y = 0
            result_region = None

            def on_press(event):
                nonlocal start_x, start_y, rect_id
                start_x, start_y = event.x, event.y
                if rect_id:
                    canvas.delete(rect_id)
                rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y,
                                                  outline='red', width=2)

            def on_drag(event):
                nonlocal rect_id
                if rect_id:
                    canvas.coords(rect_id, start_x, start_y, event.x, event.y)

            def on_release(event):
                nonlocal result_region
                x1, y1 = min(start_x, event.x), min(start_y, event.y)
                x2, y2 = max(start_x, event.x), max(start_y, event.y)
                if x2 - x1 > 10 and y2 - y1 > 10:
                    result_region = (x1, y1, x2 - x1, y2 - y1)
                overlay.destroy()

            def on_escape(event):
                overlay.destroy()

            canvas.bind("<ButtonPress-1>", on_press)
            canvas.bind("<B1-Motion>", on_drag)
            canvas.bind("<ButtonRelease-1>", on_release)
            overlay.bind("<Escape>", on_escape)

            # 等待覆盖层关闭
            self.win.wait_window(overlay)

            # 恢复窗口
            self.win.deiconify()

            if result_region is None:
                return

        # 弹出输入对话框获取目标文本
        dialog = tk.Toplevel(self.win)
        dialog.title(f"OCR 识别设置 - {name}")
        dialog.resizable(True, True)
        dialog.minsize(320, 200)
        dialog.transient(self.win)
        dialog.grab_set()
        self._set_dialog_icon(dialog)
        # 恢复窗口大小 + 关闭时自动保存
        utils.bind_window_geometry(dialog, "ocr_template_setting_geometry", "350x240", (320, 200))

        ttk.Label(dialog, text=f"模板：{name}", font=('Microsoft YaHei UI', 10, 'bold')).pack(pady=(15, 5))
        if global_enabled and global_region[2] > 0 and global_region[3] > 0:
            region_text = f"识别区域（全局）: ({result_region[0]}, {result_region[1]}, {result_region[2]}, {result_region[3]})"
        else:
            region_text = f"识别区域: ({result_region[0]}, {result_region[1]}, {result_region[2]}, {result_region[3]})"
        ttk.Label(dialog, text=region_text,
                  font=('Microsoft YaHei UI', 9), foreground='#7f8c8d').pack()

        ttk.Label(dialog, text="目标识别文本：").pack(pady=(10, 2))
        global_texts = settings.get("global_ocr_texts", {})
        default_text = existing.get("text", "") or global_texts.get(var_name, "")
        text_var = tk.StringVar(value=default_text)
        text_entry = ttk.Entry(dialog, textvariable=text_var, width=30)
        text_entry.pack(pady=2)

        conf_frame = ttk.Frame(dialog)
        conf_frame.pack(pady=5)
        ttk.Label(conf_frame, text="置信度：").pack(side=tk.LEFT)
        default_conf = existing.get("confidence") or settings.get("global_ocr_confidence", 0.8)
        conf_var = tk.DoubleVar(value=default_conf)
        conf_spin = ttk.Spinbox(conf_frame, from_=0.5, to=1.0, increment=0.05,
                                textvariable=conf_var, width=6)
        conf_spin.pack(side=tk.LEFT, padx=5)

        def save_ocr():
            text = text_var.get().strip()
            if not text:
                messagebox.showwarning("提示", "请输入目标识别文本", parent=dialog)
                return
            ocr_configs[var_name] = {
                "region": list(result_region),
                "text": text,
                "confidence": conf_var.get()
            }
            settings["ocr_configs"] = ocr_configs
            config.save_settings(settings)
            # 标记该模板为已完成
            self.status[var_name] = "done"
            if var_name in self.rows:
                status_lbl, _ = self.rows[var_name]
                status_lbl.config(text="✅")
            self._update_progress()
            messagebox.showinfo("保存成功",
                                f"OCR 配置已保存：\n区域：{result_region}\n文本：{text}\n置信度：{conf_var.get()}",
                                parent=dialog)
            dialog.destroy()

        ttk.Button(dialog, text="保存", command=save_ocr).pack(pady=10)

        # 等待对话框关闭后恢复 grab
        self.win.wait_window(dialog)
        self.win.grab_set()

    def _open_global_ocr_settings(self):
        """打开全局 OCR 设置对话框"""
        settings = config.load_settings()

        dialog = tk.Toplevel(self.win)
        dialog.title("全局 OCR 设置")
        dialog.resizable(True, True)
        dialog.minsize(450, 350)
        dialog.transient(self.win)
        dialog.grab_set()
        self._set_dialog_icon(dialog)
        # 恢复窗口大小 + 关闭时自动保存
        utils.bind_window_geometry(dialog, "global_ocr_geometry", "500x420", (450, 350))

        ttk.Label(dialog, text="全局 OCR 设置", font=('Microsoft YaHei UI', 12, 'bold')).pack(pady=(15, 10))

        global_enabled_var = tk.BooleanVar(value=settings.get("global_ocr_enabled", False))
        ttk.Checkbutton(dialog, text="启用全局 OCR 设置（模板无需单独框选区域，使用全局区域）",
                        variable=global_enabled_var).pack(anchor='w', padx=25)

        # 区域显示
        global_region = settings.get("global_ocr_region", [0, 0, 0, 0])
        region_text = f"({global_region[0]}, {global_region[1]}, {global_region[2]}, {global_region[3]})"
        if global_region[2] <= 0 or global_region[3] <= 0:
            region_text = "未设置"

        region_label = ttk.Label(dialog, text=f"当前全局区域：{region_text}",
                                 font=('Microsoft YaHei UI', 9), foreground='#7f8c8d', wraplength=450)
        region_label.pack(anchor='w', padx=25, pady=(5, 5))

        result_region = list(global_region)

        def set_global_region():
            nonlocal result_region
            dialog.grab_release()
            dialog.withdraw()
            self.win.withdraw()
            import time
            time.sleep(0.3)

            overlay = tk.Toplevel(dialog)
            overlay.attributes('-fullscreen', True)
            overlay.attributes('-alpha', 0.3)
            overlay.attributes('-topmost', True)
            overlay.configure(bg='black')
            overlay.cursor = "crosshair"

            canvas = tk.Canvas(overlay, highlightthickness=0, bg='black')
            canvas.pack(fill=tk.BOTH, expand=True)

            hint_label = tk.Label(overlay, text="请拖动鼠标框选全局 OCR 识别区域，按 Esc 取消",
                                  font=('Microsoft YaHei UI', 14, 'bold'), fg='white', bg='black')
            hint_label.place(relx=0.5, rely=0.05, anchor='center')

            rect_id = None
            start_x = start_y = 0
            overlay_result = [None]

            def on_press(event):
                nonlocal start_x, start_y, rect_id
                start_x, start_y = event.x, event.y
                if rect_id:
                    canvas.delete(rect_id)
                rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y,
                                                  outline='red', width=2)

            def on_drag(event):
                nonlocal rect_id
                if rect_id:
                    canvas.coords(rect_id, start_x, start_y, event.x, event.y)

            def on_release(event):
                nonlocal overlay_result
                x1, y1 = min(start_x, event.x), min(start_y, event.y)
                x2, y2 = max(start_x, event.x), max(start_y, event.y)
                if x2 - x1 > 10 and y2 - y1 > 10:
                    overlay_result[0] = (x1, y1, x2 - x1, y2 - y1)
                overlay.destroy()

            def on_escape(event):
                overlay.destroy()

            canvas.bind("<ButtonPress-1>", on_press)
            canvas.bind("<B1-Motion>", on_drag)
            canvas.bind("<ButtonRelease-1>", on_release)
            overlay.bind("<Escape>", on_escape)

            dialog.wait_window(overlay)

            self.win.deiconify()
            dialog.deiconify()
            dialog.grab_set()

            if overlay_result[0]:
                result_region[:] = list(overlay_result[0])
                region_label.config(text=f"当前全局区域：{overlay_result[0]}")

        ttk.Button(dialog, text="设置全局识别区域", command=set_global_region, width=18).pack(anchor='w', padx=25, pady=(0, 5))

        # 全局置信度
        conf_frame = ttk.Frame(dialog)
        conf_frame.pack(anchor='w', padx=25, pady=(5, 5))
        ttk.Label(conf_frame, text="全局默认置信度：").pack(side=tk.LEFT)
        global_conf_var = tk.DoubleVar(value=settings.get("global_ocr_confidence", 0.8))
        ttk.Spinbox(conf_frame, from_=0.5, to=1.0, increment=0.05,
                    textvariable=global_conf_var, width=6).pack(side=tk.LEFT, padx=5)
        ttk.Label(conf_frame, text="（模板未单独配置时使用此值）",
                  font=('Microsoft YaHei UI', 8), foreground='#7f8c8d',
                  wraplength=250).pack(side=tk.LEFT)

        # 启用全局文本配置
        global_text_enabled_var = tk.BooleanVar(value=settings.get("global_text_enabled", False))
        ttk.Checkbutton(dialog, text="启用全局文本配置（一键配置所有模板的识别文本）",
                        variable=global_text_enabled_var).pack(anchor='w', padx=25, pady=(5, 5))

        # 全局文本配置按钮
        ttk.Button(dialog, text="全局文本配置", command=lambda: self._open_global_text_config(dialog),
                   width=18).pack(anchor='w', padx=25, pady=(0, 5))

        # OCR 降级开关
        downgrade_var = tk.BooleanVar(value=settings.get("ocr_downgrade_enabled", True))
        ttk.Checkbutton(dialog, text="OCR 超时降级到图片匹配（关闭后 OCR 未识别到则不使用图片匹配）",
                        variable=downgrade_var).pack(anchor='w', padx=25, pady=(5, 5))

        def save_global():
            # 重新加载设置，避免覆盖全局文本配置对话框的修改
            fresh = config.load_settings()
            fresh["global_ocr_enabled"] = global_enabled_var.get()
            fresh["global_ocr_region"] = result_region
            fresh["global_ocr_confidence"] = global_conf_var.get()
            fresh["global_text_enabled"] = global_text_enabled_var.get()
            fresh["ocr_downgrade_enabled"] = downgrade_var.get()

            ocr_configs = fresh.get("ocr_configs", {})
            global_texts = fresh.get("global_ocr_texts", {})

            # 取消启用全局 OCR 时，清除使用全局区域的 ocr_configs 条目
            if not global_enabled_var.get():
                for vn in list(ocr_configs.keys()):
                    cfg = ocr_configs[vn]
                    if not cfg.get("region"):
                        del ocr_configs[vn]

            # 取消启用全局文本配置时，清除全局文本和对应 ocr_configs
            if not global_text_enabled_var.get():
                for vn in list(global_texts.keys()):
                    if vn in ocr_configs:
                        del ocr_configs[vn]
                fresh["global_ocr_texts"] = {}
            elif global_texts:
                # 启用时，将 global_ocr_texts 同步到 ocr_configs
                use_global_region = global_enabled_var.get() and result_region[2] > 0 and result_region[3] > 0
                for var_name, text_val in global_texts.items():
                    existing = ocr_configs.get(var_name, {})
                    region = existing.get("region")
                    if not region and use_global_region:
                        region = list(result_region)
                    ocr_configs[var_name] = {
                        "region": region or [],
                        "text": text_val,
                        "confidence": existing.get("confidence") or global_conf_var.get(),
                    }

            fresh["ocr_configs"] = ocr_configs
            config.save_settings(fresh)
            messagebox.showinfo("保存成功",
                                f"全局 OCR 设置已保存\n"
                                f"启用：{'是' if global_enabled_var.get() else '否'}\n"
                                f"区域：{tuple(result_region)}\n"
                                f"置信度：{global_conf_var.get()}\n"
                                f"全局文本：{'已启用' if global_text_enabled_var.get() else '未启用'}\n"
                f"OCR 降级：{'已启用' if downgrade_var.get() else '已关闭'}",
                                parent=dialog)
            dialog.destroy()
            self._refresh_status_from_ocr_configs()

        ttk.Button(dialog, text="保存", command=save_global, width=10).pack(pady=10)

    def _open_global_text_config(self, parent_dialog):
        """打开全局文本配置对话框"""
        # 每次打开重新加载设置，避免空白窗口
        settings = config.load_settings()
        saved_texts = settings.get("global_ocr_texts", {})

        win = tk.Toplevel(parent_dialog)
        win.title("全局文本配置")
        win.resizable(True, True)
        win.minsize(480, 400)
        win.transient(parent_dialog)
        win.grab_set()
        self._set_dialog_icon(win)
        # 恢复窗口大小 + 关闭时自动保存
        utils.bind_window_geometry(win, "global_text_config_geometry", "540x620", (480, 400))

        # 标题
        ttk.Label(win, text="全局文本配置", font=('Microsoft YaHei UI', 12, 'bold')).pack(pady=(10, 5))

        # 全选
        select_all_var = tk.BooleanVar(value=False)
        select_all_cb = ttk.Checkbutton(win, text="全选", variable=select_all_var)
        select_all_cb.pack(anchor='w', padx=20)

        # 滚动区域
        list_frame = ttk.Frame(win)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)

        scroll_frame.bind("<Configure>",
                          lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError:
                pass
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 构建每行：先普通项，后不可识别项
        check_vars = {}  # var_name -> BooleanVar
        text_vars = {}   # var_name -> StringVar (only for editable items)

        # 分离普通项和不可识别项
        normal_items = []
        disabled_items = []
        for var_name, (display_name, default_text) in GLOBAL_TEXT_DEFAULTS.items():
            if default_text is None:
                disabled_items.append((var_name, display_name, default_text))
            else:
                normal_items.append((var_name, display_name, default_text))

        all_items = normal_items + disabled_items  # 不可识别项放最后

        for var_name, display_name, default_text in all_items:
            row = ttk.Frame(scroll_frame)
            row.pack(fill=tk.X, pady=1)

            is_disabled = default_text is None
            initial_checked = var_name in saved_texts and bool(saved_texts[var_name])
            chk_var = tk.BooleanVar(value=initial_checked)
            check_vars[var_name] = chk_var

            if is_disabled:
                cb = ttk.Checkbutton(row, variable=chk_var, state='disabled', width=4)
                cb.pack(side=tk.LEFT)
                ttk.Label(row, text=f"{display_name}（不可文字识别）",
                          font=('Microsoft YaHei UI', 9), foreground='#999').pack(side=tk.LEFT, padx=(5, 0))
            else:
                cb = ttk.Checkbutton(row, variable=chk_var, width=4)
                cb.pack(side=tk.LEFT)
                ttk.Label(row, text=f"{display_name}：",
                          font=('Microsoft YaHei UI', 9)).pack(side=tk.LEFT, padx=(5, 0))
                t_var = tk.StringVar(value=saved_texts.get(var_name, default_text))
                text_vars[var_name] = t_var
                ttk.Entry(row, textvariable=t_var, width=22,
                          font=('Microsoft YaHei UI', 9)).pack(side=tk.RIGHT, padx=(5, 10))

        # 全选联动
        def toggle_all():
            val = select_all_var.get()
            for v, chk in check_vars.items():
                if GLOBAL_TEXT_DEFAULTS[v][1] is not None:
                    chk.set(val)

        select_all_cb.configure(command=toggle_all)

        # 一键重置文本
        def reset_texts():
            if not messagebox.askyesno("确认重置", "确定将所有文本重置为默认值？", parent=win):
                return
            for var_name, t_var in text_vars.items():
                default_text = GLOBAL_TEXT_DEFAULTS[var_name][1]
                if default_text is not None:
                    t_var.set(default_text)
            messagebox.showinfo("重置完成", "所有文本已重置为默认值", parent=win)

        # 保存
        def save_texts():
            new_texts = {}
            unchecked_names = []
            for var_name, chk in check_vars.items():
                if chk.get() and var_name in text_vars:
                    text_val = text_vars[var_name].get().strip()
                    if text_val:
                        new_texts[var_name] = text_val
                    else:
                        unchecked_names.append(GLOBAL_TEXT_DEFAULTS[var_name][0])
                elif not chk.get() and GLOBAL_TEXT_DEFAULTS[var_name][1] is not None:
                    unchecked_names.append(GLOBAL_TEXT_DEFAULTS[var_name][0])

            # 警告未配置项
            if unchecked_names:
                warn_msg = "以下模板未配置，将使用原图片识别：\n" + "、".join(unchecked_names[:10])
                if len(unchecked_names) > 10:
                    warn_msg += f"\n...等共 {len(unchecked_names)} 项"
                if not messagebox.askyesno("确认", warn_msg + "\n\n是否继续保存？", parent=win):
                    return

            # 保存全局文本
            settings["global_ocr_texts"] = new_texts

            # 同步更新 ocr_configs
            ocr_configs = settings.get("ocr_configs", {})
            global_region = settings.get("global_ocr_region", [0, 0, 0, 0])
            global_conf = settings.get("global_ocr_confidence", 0.8)
            use_global_region = settings.get("global_ocr_enabled", False) and global_region[2] > 0 and global_region[3] > 0

            for var_name, text_val in new_texts.items():
                existing = ocr_configs.get(var_name, {})
                region = existing.get("region")
                if not region and use_global_region:
                    region = list(global_region)
                ocr_configs[var_name] = {
                    "region": region or [],
                    "text": text_val,
                    "confidence": existing.get("confidence") or global_conf,
                }

            settings["ocr_configs"] = ocr_configs
            config.save_settings(settings)

            configured_count = len(new_texts)
            messagebox.showinfo("保存成功",
                                f"全局文本配置已保存\n"
                                f"已配置 {configured_count} 个模板的识别文本",
                                parent=win)
            win.destroy()
            self._refresh_status_from_ocr_configs()

        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=20, pady=(5, 10))
        ttk.Button(btn_frame, text="一键重置文本", command=reset_texts, width=14).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="保存", command=save_texts, width=10).pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="取消", command=win.destroy, width=10).pack(side=tk.RIGHT, padx=8)

        # 使用说明
        tips_text = (
            "说明：勾选需要识别的模板并填写对应文字，保存后将自动配置 OCR。\n"
            "未勾选的模板将使用图片识别，不可识别的模板（如游戏币、降价按钮）无法勾选。"
        )
        ttk.Label(win, text=tips_text, font=('Microsoft YaHei UI', 8),
                  foreground='#7f8c8d', justify=tk.LEFT, wraplength=500).pack(anchor='w', padx=20, pady=(0, 8))

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

        # 检查 OCR 配置状态
        settings = config.load_settings()
        ocr_configs = settings.get("ocr_configs", {})
        global_texts = settings.get("global_ocr_texts", {})
        has_ocr_text = bool(ocr_configs.get(var_name, {}).get("text")) or bool(global_texts.get(var_name))
        ocr_cfg_text = ocr_configs.get(var_name, {}).get("text") or global_texts.get(var_name, "")
        ocr_status = f"（已配置：{ocr_cfg_text}）" if has_ocr_text else "（未配置）"

        # 按钮区
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        def do_upload():
            win.destroy()
            self._start_upload(var_name, rel_path)

        def do_restore():
            win.destroy()
            self._restore_template(var_name, rel_path)

        def do_ocr():
            win.destroy()
            self._setup_ocr(var_name, name)

        # 不可文字识别的模板不显示 OCR 按钮
        ocr_default = GLOBAL_TEXT_DEFAULTS.get(var_name, (None, None))
        if ocr_default[1] is not None:
            ttk.Button(btn_frame, text=f"OCR识别 {ocr_status}", command=do_ocr, width=20).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="恢复默认", command=do_restore, width=10).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_frame, text="截取", command=do_upload, width=8).pack(side=tk.LEFT)

        # 居中
        win.update_idletasks()
        pw = win.winfo_width()
        ph = win.winfo_height()
        px = (win.winfo_screenwidth() - pw) // 2
        py = (win.winfo_screenheight() - ph) // 2
        win.geometry(f"+{px}+{py}")

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
        settings["ocr_configs"] = {}
        settings["global_ocr_texts"] = {}
        settings["global_ocr_enabled"] = False
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
        self.win.destroy()

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
        self.win.destroy()
        messagebox.showinfo("完成", f"模板上传完成！共上传 {done}/{total} 个模板。")


def utils_clear_cache():
    """清除 utils 中的模板缓存，使新上传的图片生效"""
    try:
        import utils
        utils.clear_template_cache()
    except Exception:
        pass
