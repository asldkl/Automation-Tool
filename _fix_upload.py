#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(ROOT, "template_capture.py")

with open(PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove batch button
content = content.replace(
    '        batch_btn = ttk.Button(nav_frame, text="\U0001f4c2 批量匹配", style="Accent.TButton",\n                               command=lambda: self._batch_match_upload())\n        batch_btn.pack(side=tk.LEFT)\n',
    ''
)
print("1. Removed batch button")

# 2. Remove batch methods
start = content.find('    def _batch_match_upload(self):')
if start >= 0:
    end = content.find('    def _save_status(self):', start)
    if end >= 0:
        content = content[:start] + content[end:]
        print("2. Removed batch methods")
    else:
        print("2. WARN: _save_status not found after batch methods")
else:
    print("2. Batch methods not found (already removed)")

# 3. Replace _upload_image
old = '        def _upload_image():\n            fp = filedialog.askopenfilename(title="选择要匹配的截图",\n                filetypes=[("图片文件", "*.png *.jpg *.jpeg *.bmp")], parent=win)\n            if not fp:\n                return\n            test_data = np.fromfile(fp, dtype=np.uint8)\n            test_img = cv2.imdecode(test_data, cv2.IMREAD_GRAYSCALE)\n            if test_img is None:\n                messagebox.showerror("错误", "无法读取图片文件，请确认格式正确。\\n路径可能包含中文或特殊字符。", parent=win)\n                return\n            current_file[0] = fp\n            do_matching(fp)'

new = '''        pending_files = []
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
        def _upload_image():
            choice = messagebox.askyesno("上传方式",
                "选择「是」上传单个或多个图片（文件选择）\\n选择「否」选择整个文件夹（批量匹配）",
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
            save_btn.config(text="保存并下一张")'''

if old not in content:
    print("3. ERROR: _upload_image pattern not found!")
    print("   Searching for partial match...")
    idx = content.find('def _upload_image():')
    if idx >= 0:
        print(f"   Found at position {idx}")
        print(f"   Context: {content[idx:idx+200]}")
else:
    content = content.replace(old, new)
    print("3. Updated _upload_image")

# 4. Update on_save to call _load_next after save, not clear state
old_save_tail = '''                conf_var.set(f"\\u2705 保存成功：{name}")
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
            except Exception as e:'''

new_save_tail = '''                conf_var.set(f"\\u2705 保存成功：{name}")
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
                # 加载下一张
                _load_next()
            except Exception as e:'''

if old_save_tail not in content:
    print("4. ERROR: on_save tail not found!")
else:
    content = content.replace(old_save_tail, new_save_tail)
    print("4. Updated on_save to auto-load next")

with open(PATH, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done!")
