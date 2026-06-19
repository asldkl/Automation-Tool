"""
配置管理模块
包含 WeGame 路径自动获取、图片资源路径、置信度等全局常量，并支持用户自定义设置文件
"""
import os
import sys
import json
import winreg
import threading

# ==================== 有效期由服务器端统一校验 ====================

# ==================== 资源路径辅助 ====================
def resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包
        base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
    elif "__compiled__" in dir():
        # Nuitka 打包：使用当前模块(__file__)所在目录，兼容 standalone 和 onefile
        base_path = os.path.dirname(os.path.abspath(__file__))
    else:
        # 开发环境
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ==================== 用户设置文件路径 ====================
SETTINGS_JSON_PATH = os.path.join(os.path.expanduser("~"), ".delta_auto_settings.json")

# ==================== 用户自定义模板目录 ====================
USER_TEMPLATE_DIR = os.path.join(os.path.expanduser("~"), ".delta_auto_templates")

def user_template_path(basename):
    """获取用户自定义模板的完整路径"""
    return os.path.join(USER_TEMPLATE_DIR, basename)

def resolve_template_path(config_path):
    """优先使用用户自定义模板，不存在则使用内置资源"""
    basename = os.path.basename(config_path)
    user_path = user_template_path(basename)
    if os.path.exists(user_path):
        return user_path
    return resource_path(config_path)

# ==================== 售卖物品目录 ====================
SELL_ITEMS_DIR = os.path.join(os.path.expanduser("~"), ".delta_auto_sell_items")

def get_sell_items():
    """获取用户上传的售卖物品模板列表，返回路径列表"""
    if not os.path.exists(SELL_ITEMS_DIR):
        return []
    items = sorted([f for f in os.listdir(SELL_ITEMS_DIR)
                    if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))])
    return [os.path.join(SELL_ITEMS_DIR, f) for f in items]

# ==================== 售卖物品元数据 ====================
ITEMS_META_PATH = os.path.join(SELL_ITEMS_DIR, "items_meta.json")
ITEMS_META_BACKUP = os.path.join(SELL_ITEMS_DIR, "items_meta.backup.json")

def load_sell_items_meta():
    """加载物品元数据，自动同步目录中新增/删除的图片"""
    import shutil
    # 加载已有元数据（含备份恢复机制）
    meta = {}
    if os.path.exists(ITEMS_META_PATH):
        try:
            with open(ITEMS_META_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            # 主文件损坏，尝试从备份恢复
            if os.path.exists(ITEMS_META_BACKUP):
                try:
                    with open(ITEMS_META_BACKUP, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    # 恢复主文件
                    shutil.copy2(ITEMS_META_BACKUP, ITEMS_META_PATH)
                    print("⚠️ items_meta.json 损坏，已从备份恢复")
                except Exception:
                    meta = {}
            else:
                meta = {}

    existing_items = meta.get("items", [])
    existing_filenames = {i["filename"] for i in existing_items}

    # 扫描目录中的实际图片
    if not os.path.exists(SELL_ITEMS_DIR):
        meta.setdefault("items", [])
        return meta

    disk_filenames = sorted([f for f in os.listdir(SELL_ITEMS_DIR)
                             if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))])

    # 添加目录中存在但元数据中没有的图片
    changed = False
    for filename in disk_filenames:
        if filename not in existing_filenames:
            existing_items.append({
                "filename": filename,
                "name": os.path.splitext(filename)[0],
                "discount_times": 0,
                "quantity": 1
            })
            changed = True

    # 移除元数据中存在但目录中已删除的图片
    disk_set = set(disk_filenames)
    before_count = len(existing_items)
    existing_items = [i for i in existing_items if i["filename"] in disk_set]
    if len(existing_items) != before_count:
        changed = True

    meta["items"] = existing_items

    # 有变更时自动保存
    if changed:
        save_sell_items_meta(meta)

    return meta

def save_sell_items_meta(data):
    """保存物品元数据（原子写入+备份保护）"""
    import shutil
    os.makedirs(SELL_ITEMS_DIR, exist_ok=True)
    # 先写入临时文件，再原子替换（防止写入中途崩溃导致文件损坏）
    tmp_path = ITEMS_META_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 保存前先备份旧文件
    if os.path.exists(ITEMS_META_PATH):
        try:
            shutil.copy2(ITEMS_META_PATH, ITEMS_META_BACKUP)
        except Exception:
            pass
    # 原子替换
    shutil.move(tmp_path, ITEMS_META_PATH)

# ==================== 默认设置 ====================
DEFAULT_SETTINGS = {
    "wegame_path": "",                # 若空则自动从注册表获取
    "delta_path": "",                 # 三角洲启动程序路径（备用）
    "confidence": 0.7,                # 全局图像匹配置信度
    "log_save_path": "",              # 日志保存目录，若为空则仅显示在界面
    "selected_operations": ["tech_center", "tool_bench", "armor_station", "pharmacy_station"],
    # 自动关机
    "auto_shutdown_enabled": False,   # 是否启用自动关机
    "auto_shutdown_time": "22:00",    # 关机时间 (HH:MM)
    # 邮件通知
    "email_enabled": False,           # 是否启用邮件通知
    "smtp_code": "",                  # SMTP 授权码
    "sender_email": "",               # 发送者邮箱
    "receiver_email": "",             # 接收者邮箱
    # 游戏启动等待
    "game_launch_wait": 0,            # 启动游戏后额外等待时间（秒，0-120）
    "run_on_startup": False,          # 开机立即运行一次程序
    # 一键出售
    "enable_sell_after_run": False,   # 主流程完成后执行一键售卖
    "sell_confidence": 0.55,          # 出售物品匹配置信度（0.40-0.80）
    "sell_time_enabled": False,       # 是否启用售卖时间区间
    "sell_time_start": "08:00",       # 售卖开始时间 (HH:MM)
    "sell_time_end": "22:00",         # 售卖结束时间 (HH:MM)
    # 邮箱货币
    "enable_email_currency": False,   # 是否启用自动领取邮箱货币
    # 冷却管理
    "enable_cooldown": False,         # 是否启用账号冷却
    "cooldown_hours": 8,              # 冷却小时数（默认8小时）
    "cooldown_delay_minutes": 1,      # 账号间隔时间（0-5分钟，默认1）
    "cooldown_run_immediately": False, # 冷却完立即运行
    "cooldown_email_enabled": False,  # 冷却结束后发送邮件提醒
    # 模板分辨率记录
    "template_resolution": "",        # 模板截图时的屏幕分辨率
    # 模板上传状态记录
    "template_upload_status": {},     # var_name -> "pending" | "done"
    # 运行完成后关机
    "post_run_shutdown_delay": 0,     # 运行完成后延迟关机（0-5分钟，0=不关机）
    # 服务器配置（可通过 ~/.delta_auto_settings.json 覆盖）
    "server_url": "http://112.74.106.69:8000",  # 服务器地址（建议生产环境使用 HTTPS）
    "client_key": "Client_Normal_Key_2026",      # 客户端认证令牌（非加密密钥，仅用于请求校验）
    # OCR 识别配置
    "ocr_configs": {},                           # var_name -> {"region": [x,y,w,h], "text": "制造", "confidence": 0.8}
    "global_ocr_enabled": False,                 # 是否启用全局 OCR（模板无需单独配置区域）
    "global_ocr_region": [0, 0, 0, 0],           # 全局 OCR 识别区域 [x, y, w, h]
    "global_ocr_confidence": 0.55,               # 全局 OCR 默认置信度
    "global_ocr_texts": {},                      # 全局 OCR 文本配置 var_name -> "text"
    "global_text_enabled": False,                # 是否启用全局文本配置
    "ocr_downgrade_enabled": True,               # OCR 超时是否降级到图片匹配
    # 资产识别
    "enable_asset_recognition": False,           # 是否启用资产识别
    "asset_region": [0, 0, 0, 0],               # 资产识别屏幕区域 [x, y, w, h]
    "asset_ocr_confidence": 0.7,                 # 资产识别置信度
}

_settings_cache = None
_settings_cache_mtime = 0
_settings_lock = threading.Lock()

def load_settings():
    """加载用户设置（敏感字段自动解密），带文件修改时间缓存（线程安全）"""
    global _settings_cache, _settings_cache_mtime
    with _settings_lock:
        try:
            mtime = os.path.getmtime(SETTINGS_JSON_PATH) if os.path.exists(SETTINGS_JSON_PATH) else 0
        except Exception:
            mtime = 0
        if _settings_cache is not None and mtime == _settings_cache_mtime:
            return dict(_settings_cache)
        if not os.path.exists(SETTINGS_JSON_PATH):
            _settings_cache = dict(DEFAULT_SETTINGS)
            _settings_cache_mtime = 0
            return dict(_settings_cache)
        try:
            with open(SETTINGS_JSON_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            settings = dict(DEFAULT_SETTINGS)
            settings.update(saved)
            _settings_cache = settings
            _settings_cache_mtime = mtime
            return dict(settings)
        except Exception:
            _settings_cache = dict(DEFAULT_SETTINGS)
            _settings_cache_mtime = 0
            return dict(_settings_cache)

def save_settings(settings):
    """保存用户设置到 JSON 文件（线程安全）"""
    global _settings_cache, _settings_cache_mtime
    with _settings_lock:
        try:
            with open(SETTINGS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            # 保存后立即更新缓存
            _settings_cache = dict(settings)
            _settings_cache_mtime = os.path.getmtime(SETTINGS_JSON_PATH)
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
# WeGame 登录
IMAGE_LOGIN_BTN      = resource_path("picture/wegame_login/login_btn.png")
DELTA_GAME_ICON     = resource_path("picture/wegame_login/delta_game_icon.png")
DELTA_LAUNCH_BTN    = resource_path("picture/wegame_login/delta_launch_btn.png")
LOGIN_AGAIN         = resource_path("picture/wegame_login/login_again.png")

ACCOUNT_SELECT      = resource_path("picture/wegame_login/account_select.png")
SIGN_IN             = resource_path("picture/wegame_login/Sign-in.png")
IMAGE_INPUT_FIELD   = resource_path("picture/wegame_login/Input.png")

# 游戏内导航
Hazard_Operations   = resource_path("picture/Navigation/hazard_operations.png")
Special_Ops         = resource_path("picture/Navigation/special_ops.png")

# 设施控制
Tech_Center         = resource_path("picture/Facility_Controls/tech_center.png")
Tool_Bench          = resource_path("picture/Facility_Controls/tool_bench.png")
Armor_Station       = resource_path("picture/Facility_Controls/Armor_Station.png")
Pharmacy_Station    = resource_path("picture/Facility_Controls/Pharmacy_Station.png")

# 制造控制
MAKE                = resource_path("picture/Crafting_Controls/Make.png")
Produce             = resource_path("picture/Crafting_Controls/Produce.png")
Collect             = resource_path("picture/Crafting_Controls/Collect.png")
Auto_fill           = resource_path("picture/Crafting_Controls/Auto_fill.png")
Claim_Reward        = resource_path("picture/Crafting_Controls/Claim_Reward.png")
COIN_GAME           = resource_path("picture/Crafting_Controls/coin_game.png")

# ==================== 邮箱货币图片 ====================
EMAIL_MAIL              = resource_path("picture/email/mail.png")
EMAIL_TRADE_HOUSE       = resource_path("picture/email/Trade_House.png")
EMAIL_CLAIM_ALL         = resource_path("picture/email/Claim_All.png")
EMAIL_RECEIVE_COMPLETED = resource_path("picture/email/Receive_Completed.png")

# ==================== 一键出售图片 ====================
Warehouse           = resource_path("picture/One_Click_Sell/Warehouse.png")
Sell                = resource_path("picture/One_Click_Sell/Sell.png")
List_Item           = resource_path("picture/One_Click_Sell/List.png")
Discount            = resource_path("picture/One_Click_Sell/Discount.png")
Confirm_Listing     = resource_path("picture/One_Click_Sell/Confirm Listing.png")

Produce_TechCenter  = resource_path("picture/produce/produce_tech_center.png")
Produce_ToolBench   = resource_path("picture/produce/produce_tool_bench.png")
Produce_ArmorStation = resource_path("picture/produce/produce_armor_station.png")
Produce_PharmacyStation = resource_path("picture/produce/produce_pharmacy_station.png")

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
    ("IMAGE_LOGIN_BTN",      "picture/wegame_login/login_btn.png",      "WeGame 登录按钮",     "在 WeGame 登录界面，截取「登录」按钮"),
    ("DELTA_GAME_ICON",      "picture/wegame_login/delta_game_icon.png", "三角洲游戏图标",     "在 WeGame 首页，截取三角洲行动的游戏图标"),
    ("DELTA_LAUNCH_BTN",     "picture/wegame_login/delta_launch_btn.png","启动游戏按钮",       "在三角洲游戏页面，截取「启动」按钮"),
    ("LOGIN_AGAIN",          "picture/wegame_login/login_again.png",   "重新登录按钮",       "在 WeGame 登录失败后，截取「重新登录」按钮"),
    ("ACCOUNT_SELECT",       "picture/wegame_login/account_select.png", "WeGame 账号选择框",   "在 WeGame 登录界面，截取账号选择框"),
    ("IMAGE_INPUT_FIELD",    "picture/wegame_login/Input.png",          "WeGame 密码输入框",   "在 WeGame 登录界面，截取密码输入框"),
    ("SIGN_IN",              "picture/wegame_login/Sign-in.png",        "WeGame 登录确认按钮", "在 WeGame 登录界面，截取「登录」确认按钮"),
    ("Hazard_Operations",    "picture/Navigation/hazard_operations.png","烽火地带入口",      "在游戏主菜单，截取「烽火地带」图标"),
    ("Special_Ops",          "picture/Navigation/special_ops.png",     "特勤处入口",         "在大厅界面，截取「特勤处」图标"),
    ("Tech_Center",          "picture/Facility_Controls/tech_center.png",     "技术中心",           "在特勤处界面，截取「技术中心」设施图标"),
    ("Tool_Bench",           "picture/Facility_Controls/tool_bench.png",      "工作台",             "在特勤处界面，截取「工作台」设施图标"),
    ("Armor_Station",        "picture/Facility_Controls/Armor_Station.png",   "防具台",             "在特勤处界面，截取「防具台」设施图标"),
    ("Pharmacy_Station",     "picture/Facility_Controls/Pharmacy_Station.png","制药台",             "在特勤处界面，截取「制药台」设施图标"),
    ("MAKE",                 "picture/Crafting_Controls/Make.png",            "制造按钮",           "在设施界面，截取「制造」按钮"),
    ("Produce",              "picture/Crafting_Controls/Produce.png",         "产出按钮",           "在制造界面，截取「产出」相关按钮"),
    ("Collect",              "picture/Crafting_Controls/Collect.png",         "收取按钮",           "在制造界面，截取「收取」按钮"),
    ("Auto_fill",            "picture/Crafting_Controls/Auto_fill.png",       "一键补齐按钮",       "在制造界面，截取「一键补齐」按钮"),
    ("Claim_Reward",         "picture/Crafting_Controls/Claim_Reward.png",    "领取奖励按钮",       "在制造界面，截取「领取奖励」按钮"),
    ("COIN_GAME",            "picture/Crafting_Controls/coin_game.png",       "游戏币购买按钮",     "在制造界面，截取游戏币购买按钮"),
    # 一键出售相关
    ("Warehouse",            "picture/One_Click_Sell/Warehouse.png",       "仓库入口",     "在游戏主界面，截取「仓库」图标"),
    ("Sell",                 "picture/One_Click_Sell/Sell.png",            "出售按钮",     "在物品详情界面，截取「出售」按钮"),
    ("List_Item",            "picture/One_Click_Sell/List.png",            "上架按钮",     "在出售界面，截取「上架」按钮"),
    ("Discount",             "picture/One_Click_Sell/Discount.png",        "降价按钮",     "在上架界面，截取「降价」按钮"),
    ("Confirm_Listing",      "picture/One_Click_Sell/Confirm Listing.png", "确认上架按钮", "在上架界面，截取「确认上架」按钮"),
    # 邮箱货币相关
    ("EMAIL_MAIL",              "picture/email/mail.png",              "邮箱入口",         "在游戏主界面，截取「邮箱」图标"),
    ("EMAIL_TRADE_HOUSE",       "picture/email/Trade_House.png",       "交易中心入口",     "在邮箱界面，截取「交易中心」图标"),
    ("EMAIL_CLAIM_ALL",         "picture/email/Claim_All.png",         "全部领取按钮",     "在交易中心界面，截取「全部领取」按钮"),
    ("EMAIL_RECEIVE_COMPLETED", "picture/email/Receive_Completed.png", "领取完成确认按钮", "在领取界面，截取「领取完成」按钮"),
]