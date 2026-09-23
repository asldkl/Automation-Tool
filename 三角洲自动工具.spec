# -*- mode: python ; coding: utf-8 -*-
# ⚠️ 单文件版（**可选/遗留**）。默认打包方式请用 `三角洲自动工具_onedir.spec`（文件夹版）。
#   原因：单文件版每次启动都要把整包解压到 %TEMP%\_MEIxxxxxx，退出时清理失败会弹
#   「PyInstaller Onefile Hidden Window / Needs to remove its temporary files」；
#   实测启动到主窗口：单文件 ~24s vs onedir ~0.8s（单文件每次都慢，不存在「跑几次就热了」）。
#   本文件只在「非要一个 exe」时使用。installer.iss 会自动识别两种产物。
#
#   ⚠️ 与 onedir spec 的 Analysis 段（datas / hiddenimports / excludes）必须保持一致 ——
#      改一处要同步另一处，否则两边打包出来的能力会不一致（漏了会静默失效）。
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
        # 键盘后端：driver_keyboard 会对 stm32_keyboard 做函数内动态 import；
        # 后者依赖 pyserial（serial / serial.tools.list_ports）—— 全部必须显式声明，
        # ⚠️ 漏了会「打包后静默失效」（不报错但功能不生效）
        'driver_keyboard', 'stm32_keyboard', 'interception_keyboard',
        'serial', 'serial.tools', 'serial.tools.list_ports',
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
    a.binaries,
    a.datas,
    [],
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
