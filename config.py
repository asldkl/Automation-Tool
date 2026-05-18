"""
配置管理模块
包含 WeGame 路径自动获取、图片资源路径、置信度等全局常量，并支持用户自定义设置文件
"""
import os
import sys
import json
import winreg

# ==================== 资源路径辅助 ====================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ==================== 用户设置文件路径 ====================
SETTINGS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_settings.json")

# ==================== 默认设置 ====================
DEFAULT_SETTINGS = {
    "wegame_path": "",                # 若空则自动从注册表获取
    "delta_path": "",                 # 三角洲启动程序路径（备用）
    "confidence": 0.7,                # 全局图像匹配置信度
    "log_save_path": "",              # 日志保存目录，若为空则仅显示在界面
    "auto_start": False,              # 是否启用定时执行
    "start_time": "08:00",            # 定时执行时间 (HH:MM)
    "run_mode": "单次",               # "单次" 或 "每日循环"
    "silent_mode": False,             # 静默运行（最小化到托盘）
    "schedule_times": [],
    "selected_operations": ["tech_center", "tool_bench", "armor_station", "pharmacy_station"],
    # 运行前提醒
    "reminder_enabled": False,        # 是否启用运行前提醒弹窗
    "reminder_minutes": 5,            # 提前几分钟提醒（1-15）
    # 电源管理
    "wake_enabled": True,             # 运行前5分钟唤醒电脑（防休眠）
    "auto_shutdown_enabled": False,   # 是否启用自动关机
    "auto_shutdown_time": "22:00",    # 关机时间 (HH:MM)
    "auto_startup_enabled": False,    # 是否启用定时开机（从睡眠/休眠唤醒）
    "auto_startup_time": "07:00",     # 开机时间 (HH:MM)
    # QQ 路径
    "qq_path": "",                    # QQ 程序路径
    # 邮件通知
    "email_enabled": False,           # 是否启用邮件通知
    "smtp_code": "",                  # SMTP 授权码
    "sender_email": "",               # 发送者邮箱
    "receiver_email": "",             # 接收者邮箱
    # 账号列表滚动查找设置
    "qq_mouse_move_distance": 100,    # QQ 账号列表鼠标下移距离（像素）
    "scroll_amount": 100,             # 滚动幅度（pyautogui.scroll 的参数值，50-150）
    "game_launch_wait": 0,            # 启动游戏后额外等待时间（秒，0-120）
    "run_on_startup": False,          # 开机立即运行一次程序
}

def load_settings():
    """加载用户设置，若文件不存在则返回默认设置"""
    if not os.path.exists(SETTINGS_JSON_PATH):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_JSON_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # 合并默认值，防止新版本字段缺失
        settings = dict(DEFAULT_SETTINGS)
        settings.update(saved)
        return settings
    except Exception:
        return dict(DEFAULT_SETTINGS)

def save_settings(settings):
    """保存用户设置到 JSON 文件"""
    try:
        with open(SETTINGS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存设置失败：{e}")

# ==================== 自动获取 WeGame 路径 ====================
def get_wegame_path_from_reg():
    """从注册表获取 WeGame 安装路径，失败返回空字符串"""
    reg_paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WeGame",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\WeGame"
    ]
    for subkey in reg_paths:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                icon_path = winreg.QueryValueEx(key, "DisplayIcon")[0]
                exe_path = icon_path.split(",")[0]
                if os.path.exists(exe_path):
                    return exe_path
        except Exception:
            pass
    # 常见默认路径
    candidates = [
        r"C:\Program Files (x86)\WeGame\wegame.exe",
        r"C:\Program Files\WeGame\wegame.exe",
        r"D:\Program Files (x86)\WeGame\wegame.exe",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return ""

# ==================== 初始化设置（程序启动时调用） ====================
def init_settings():
    settings = load_settings()
    # 如果用户没有设置 wegame_path，自动从注册表获取
    if not settings.get("wegame_path"):
        settings["wegame_path"] = get_wegame_path_from_reg()
        save_settings(settings)
    return settings

# ==================== 全局设置实例（在 main.py 中赋值） ====================
APP_SETTINGS = {}

# ==================== 图片资源路径（固定） ====================
IMAGE_LOGIN_BTN      = resource_path("picture/login_btn.png")

DELTA_GAME_ICON     = resource_path("picture/delta_game_icon.png")
DELTA_LAUNCH_BTN    = resource_path("picture/delta_launch_btn.png")

MAKE                = resource_path("picture/make.png")
Hazard_Operations   = resource_path("picture/hazard_operations.png")
Special_Ops         = resource_path("picture/special_ops.png")
Tech_Center         = resource_path("picture/tech_center.png")
Tool_Bench          = resource_path("picture/tool_bench.png")
Armor_Station       = resource_path("picture/Armor_Station.png")
Pharmacy_Station    = resource_path("picture/Pharmacy_Station.png")

Produce             = resource_path("picture/produce.png")
Collect             = resource_path("picture/collect.png")
Auto_fill           = resource_path("picture/auto_fill.png")
Claim_Reward        = resource_path("picture/claim_reward.png")
COIN_GAME           = resource_path("picture/coin_game.png")

Produce_TechCenter  = resource_path("picture/produce/produce_tech_center.png")
Produce_ToolBench   = resource_path("picture/produce/produce_tool_bench.png")
Produce_ArmorStation = resource_path("picture/produce/produce_armor_station.png")
Produce_PharmacyStation = resource_path("picture/produce/produce_pharmacy_station.png")

# ==================== QQ 自动登录图片 ====================
QQ_ACCOUNT_SELECT = resource_path("picture/qq_login/QQ_account_select.png")
QQ_LOGIN_BTN      = resource_path("picture/qq_login/QQ_login_btn.png")

# ==================== 进程名称 ====================
WEGAME_PROCESS = "wegame.exe"
DELTA_PROCESS = "DeltaForce.exe"
QQ_PROCESS = "QQ.exe"

# ==================== 全局变量（在 main 中设置） ====================
WEGAME_PATH = ""
DELTA_PATH = ""
CONFIDENCE = 0.7
WAIT_TIME = 0.5

# ==================== 分辨率检测 ====================
def get_screen_resolution():
    """获取当前屏幕分辨率，返回 (width, height)"""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return (0, 0)

def get_resolution_key():
    """生成当前分辨率标识字符串，如 '2560x1440'"""
    w, h = get_screen_resolution()
    return f"{w}x{h}"

def load_template_resolution():
    """从设置中读取模板对应的屏幕分辨率"""
    settings = load_settings()
    return settings.get("template_resolution", "")

def save_template_resolution(resolution_key=None):
    """保存当前屏幕分辨率到设置"""
    if resolution_key is None:
        resolution_key = get_resolution_key()
    settings = load_settings()
    settings["template_resolution"] = resolution_key
    save_settings(settings)

# ==================== 需要截图的模板列表 ====================
# 每项: (配置变量名, 保存路径, 中文描述, 截图提示)
TEMPLATE_CAPTURE_LIST = [
    ("Produce_TechCenter",   "picture/produce/produce_tech_center.png",    "技术中心产出项", "在技术中心制造列表，截取要生产的物品"),
    ("Produce_ToolBench",    "picture/produce/produce_tool_bench.png",     "工作台产出项",   "在工作台制造列表，截取要生产的物品"),
    ("Produce_ArmorStation", "picture/produce/produce_armor_station.png",  "防具台产出项",   "在防具台制造列表，截取要生产的物品"),
    ("Produce_PharmacyStation","picture/produce/produce_pharmacy_station.png","制药台产出项","在制药台制造列表，截取要生产的物品"),
    ("IMAGE_LOGIN_BTN",      "picture/login_btn.png",      "WeGame 登录按钮",     "在 WeGame 登录界面，截取「登录」按钮"),
    ("DELTA_GAME_ICON",      "picture/delta_game_icon.png", "三角洲游戏图标",     "在 WeGame 首页，截取三角洲行动的游戏图标"),
    ("DELTA_LAUNCH_BTN",     "picture/delta_launch_btn.png","启动游戏按钮",       "在三角洲游戏页面，截取「启动」按钮"),
    ("Hazard_Operations",    "picture/hazard_operations.png","烽火地带入口",      "在游戏主菜单，截取「烽火地带」图标"),
    ("Special_Ops",          "picture/special_ops.png",     "特勤处入口",         "在大厅界面，截取「特勤处」图标"),
    ("Tech_Center",          "picture/tech_center.png",     "技术中心",           "在特勤处界面，截取「技术中心」设施图标"),
    ("Tool_Bench",           "picture/tool_bench.png",      "工作台",             "在特勤处界面，截取「工作台」设施图标"),
    ("Armor_Station",        "picture/Armor_Station.png",   "防具台",             "在特勤处界面，截取「防具台」设施图标"),
    ("Pharmacy_Station",     "picture/Pharmacy_Station.png","制药台",             "在特勤处界面，截取「制药台」设施图标"),
    ("MAKE",                 "picture/make.png",            "制造按钮",           "在设施界面，截取「制造」按钮"),
    ("Produce",              "picture/produce.png",         "产出按钮",           "在制造界面，截取「产出」相关按钮"),
    ("Collect",              "picture/collect.png",         "收取按钮",           "在制造界面，截取「收取」按钮"),
    ("Auto_fill",            "picture/auto_fill.png",       "一键补齐按钮",       "在制造界面，截取「一键补齐」按钮"),
    ("Claim_Reward",         "picture/claim_reward.png",    "领取奖励按钮",       "在制造界面，截取「领取奖励」按钮"),
    ("COIN_GAME",            "picture/coin_game.png",       "游戏币购买按钮",     "在制造界面，截取游戏币购买按钮"),
]

# QQ 登录相关模板
QQ_TEMPLATE_CAPTURE_LIST = [
    ("QQ_ACCOUNT_SELECT", "picture/qq_login/QQ_account_select.png", "QQ 账号选择按钮", "在 QQ 登录界面，截取账号选择按钮"),
    ("QQ_LOGIN_BTN",      "picture/qq_login/QQ_login_btn.png",      "QQ 登录按钮",     "在 QQ 登录界面，截取「登录」按钮"),
]