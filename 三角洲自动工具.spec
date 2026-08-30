# -*- mode: python ; coding: utf-8 -*-
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
           ('picture\\sniper', 'picture\\sniper')] + _rapidocr_datas + _onnxrt_datas,
    hiddenimports=[
        'config_utils.config', 'config_utils.utils', 'config_utils.machine_fingerprint',
        'core.automation', 'core.automation_runner', 'core.custom_ops',
        'data.account_manager', 'data.cooldown_manager', 'data.cooldown_watcher', 'data.asset_db',
        'drivers.driver_keyboard', 'drivers.interception_keyboard', 'drivers.relative_mouse_move',
        'services.email_notifier', 'services.server_client', 'services.scheduler', 'services.skin_sniper',
        'gui.gui_app', 'gui.settings_window', 'gui.template_capture', 'gui.custom_ops_window', 'gui.screen_log_overlay',
        'psutil', 'win32gui', 'win32con', 'win32api', 'win32event', 'win32security',
        'pystray', 'PIL', 'PIL.Image',
        'cv2', 'numpy', 'pyautogui',
        'smtplib', 'email', 'email.mime', 'email.mime.text', 'email.mime.multipart',
        # 日志遮罩（PyQt6）
        'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.sip',
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
)
