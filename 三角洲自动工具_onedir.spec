# -*- mode: python ; coding: utf-8 -*-
"""onedir（文件夹版）打包配置 —— 不起临时文件夹的那一版。

为什么需要它
------------
单文件版（onefile）每次启动都要把整个包解压到 `%TEMP%\\_MEIxxxxxx`，退出时再删掉；
清理不掉就弹「PyInstaller Onefile Hidden Window / Needs to remove its temporary files」
（本机 %TEMP% 里实测留了 24 个 _MEI 残骸，共 563MB）。

**onedir 完全不产生临时文件夹**：exe 直接读同目录的 `_internal\\`，
启动也快得多（本机实测：单文件 ~24s vs onedir ~0.5s —— 单文件每次都要解包 + 杀软逐文件扫）。

⚠️ 与单文件 spec（`三角洲自动工具.spec`）的唯一差别：
   EXE 去掉 `a.binaries / a.datas` 并加 `exclude_binaries=True`，末尾补一个 COLLECT。
   Analysis 段（datas / hiddenimports / excludes）**两边必须保持一致**，改一处要同步两处。

用法：
    python -m PyInstaller --noconfirm "三角洲自动工具_onedir.spec"
产物：
    dist\\三角洲自动工具\\三角洲自动工具.exe   （+ 同目录 _internal\\）
    安装包照旧跑 `ISCC.exe installer.iss` —— 它会自动识别 onedir / onefile 两种产物。
"""
from PyInstaller.utils.hooks import collect_all

# 收集 rapidocr_onnxruntime 的所有模块、数据文件和二进制文件
_rapidocr_datas, _rapidocr_binaries, _rapidocr_hiddenimports = collect_all('rapidocr_onnxruntime')
_onnxrt_datas, _onnxrt_binaries, _onnxrt_hiddenimports = collect_all('onnxruntime')
a = Analysis(
    ['main.py'],
    pathex=[r'C:\Users\李\Desktop\创作\程序\Automation-Tool-main\Automation-Tool-main'],
    binaries=_rapidocr_binaries + _onnxrt_binaries + [('interception.dll', '.')],
    datas=[('picture', 'picture'), ('picture\\produce', 'picture\\produce'),
           ('picture\\One_Click_Sell', 'picture\\One_Click_Sell'),
           ('picture\\email', 'picture\\email'),
           ('picture\\Crafting_Controls', 'picture\\Crafting_Controls'),
           ('picture\\Facility_Controls', 'picture\\Facility_Controls'),
           ('picture\\Navigation', 'picture\\Navigation'),
           ('picture\\wegame_login', 'picture\\wegame_login'),
           ('picture\\icon', 'picture\\icon'),
           ('picture\\sniper', 'picture\\sniper')]
           # 滑块 YOLO 模型 best.onnx（约 100MB）不再打包：由用户在
           # 设置→验证码设置→滑块验证→「导入模型」导入到 %APPDATA%/DeltaAutoTool/models/
    + _rapidocr_datas + _onnxrt_datas,
    hiddenimports=[
        'config', 'utils', 'settings_window', 'template_capture', 'cooldown_manager', 'automation', 'machine_fingerprint', 'relative_mouse_move',
        'email_notifier', 'account_manager', 'scheduler', 'cooldown_watcher', 'server_client', 'automation_runner', 'asset_db', 'interception_keyboard',
        'custom_ops', 'custom_ops_window', 'template_insert_steps', 'announcements', 'sell_pending', 'template_click_coords', 'ai_visual_captcha', 'slider_captcha', 'captcha_router',
        'sample_collector', 'captcha_glyph_flow', 'captcha_glyph_match',
        'psutil', 'win32gui', 'win32con', 'win32api', 'win32event', 'win32security',
        'pystray', 'PIL', 'PIL.Image',
        'cv2', 'numpy', 'pyautogui',
        'smtplib', 'email', 'email.mime', 'email.mime.text', 'email.mime.multipart',
        # 日志遮罩（PyQt6）
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.sip', 'screen_log_overlay',
    ] + _rapidocr_hiddenimports + _onnxrt_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 排除训练依赖（torch/ultralytics/matplotlib 等），程序运行时只用 onnxruntime，不需要 torch
    # sympy/mpmath 是 matplotlib/ultralytics 带进来的，被 onnxruntime.transformers 连带收集，也用不到
    excludes=['torch', 'torchvision', 'torchaudio', 'ultralytics', 'matplotlib',
              'pandas', 'scipy', 'seaborn', 'sympy', 'mpmath', 'networkx'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # ← onedir 关键：二进制/数据不进 exe，放 _internal\
    name='三角洲自动工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['picture\\icon\\icon.ico'],
    # 文件版本资源：让 exe 的「属性 → 详细信息」显示版本号
    # （改版本号时三处要同步：本文件不涉及数字、version_info.txt 的 filevers / FileVersion / ProductVersion）
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='三角洲自动工具',          # → dist\三角洲自动工具\
)
