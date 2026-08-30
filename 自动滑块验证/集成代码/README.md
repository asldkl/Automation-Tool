# 滑块验证 集成代码备份

此目录保存「滑块验证自动处理」的完整集成代码与接入说明，供以后重新接入主程序使用。

> 说明：滑块验证功能已从主程序移除（主程序以「账号运行分组」代替，通过错开账号运行时间来避免频繁切换触发滑块验证）。

## 文件说明

- `slider_captcha.py` — 滑块验证处理模块（已从主程序根目录移入此处）

## 功能概述

针对 WeGame 登录点击「登录」后可能出现的**滑动拼图验证码**（背景图+拼图块）：
1. **OCR 关键词检测**滑块验证是否出现（默认关键词「拖动」，可配置）
2. **定位缺口**：ddddocr / SliderSolver 成熟算法
   - 模板匹配（Canny 50/150 + matchTemplate），用拼图块在背景图中找缺口
   - **屏蔽拼图块当前位置**（避免把拼图块误识别成缺口）
   - 失败回退：轮廓筛选 → 边缘列分析
3. **拟人化拖动**：先快后慢（smoothstep）+ 随机停顿 + 到达微调
4. 拖动距离 = 缺口左边缘 − 拼图块当前位置（可加偏移微调）

## 重新接入主程序步骤

### 1. 恢复文件
把 `slider_captcha.py` 复制回主程序根目录，并在 `三角洲自动工具.spec` 的 hiddenimports 中加入 `'slider_captcha'`。

### 2. config.py
在 DEFAULT_SETTINGS 加入：
```python
"slider_enabled": False,                     # 自动解滑块验证
"slider_detect_keyword": "拖动",             # OCR 检测关键词
"slider_detect_region": [0, 0, 0, 0],        # 检测区域（0=全屏）
"slider_bg_region": [0, 0, 0, 0],            # 背景图区域
"slider_slice_region": [0, 0, 0, 0],         # 拼图块区域（滑动拼图必需）
"slider_track_region": [0, 0, 0, 0],         # 滑块轨道区域
"slider_knob_offset": 20,                    # 滑块起点偏移
"slider_drag_offset": 0,                     # 拖动微调
"slider_debug_path": "",                     # 调试图保存路径
```

### 3. automation_runner.py 登录流程接入
在 `_login_account` 点击 Sign-in 之后（登录结果轮询之前）加入：
```python
if app.settings.get("slider_enabled", False):
    try:
        import slider_captcha
        time.sleep(1.5)  # 等待滑块验证弹出
        found, solved, detail = slider_captcha.solve_slider(app)
        if found:
            print(f"{'✅ 滑块验证已处理' if solved else '⚠️ 滑块验证处理未完成'}：{detail}")
    except Exception as e:
        print(f"⚠️ 滑块验证处理异常：{e}")
```

### 4. 设置界面
- settings_window.py `__init__` 加入滑块各配置变量（slider_enable_var / 各 region_var / 偏移 var）
- `_build_global_tab` 加入「滑块验证」区域（启用勾选、关键词、4 个区域「框选」按钮、偏移）
- 区域框选复用 `_select_screen_region(title, var)`（全屏遮罩拖框选）
- `_save` 保存滑块设置
- 测试按钮调用 `slider_captcha.test_slider(app)`，测试时隐藏设置窗口，结果输出到日志遮罩（不弹窗）

### 5. 调试
- 测试时设置 `app.settings["slider_debug_path"]`，会把背景图+检测到的缺口红框保存到 `%APPDATA%\DeltaAutoTool\slider_debug.png` 便于核对
- 遮罩顶行有实时鼠标坐标（`🖱️ (x,y)`），便于精确框选区域

## 参考的开源方案
- `../ddddocr-master` — ddddocr（滑块算法为 Canny+模板匹配，ONNX 模型仅用于文字识别）
- `../main.py` — PuzzleCaptchaSolver（拼图缺口定位参考）
- 曾测试的 `SliderSolver`（skyAerope）与本模块算法一致，已移除

## 注意
- 若重新接入，建议先解决缺口定位精度后再启用（原实现的红框定位在某些情况下偏差 20-40px，且拼图块当前位置会被误识别为缺口——已加入屏蔽但需实测校准）
