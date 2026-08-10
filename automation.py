"""
自动化流程模块
包含游戏内操作、设施处理、一键出售等核心自动化逻辑
从 gui_app.py 拆分而来，降低单文件复杂度
"""
import os
import time
import datetime
import pyautogui

import config
import utils


def handle_facility(facility_img, produce_item_img, facility_name, stop_event, set_operation, update_ui_callback=None):
    """
    处理单个设施的完整流程：进入设施 → 收取 → 选择产出 → 补齐材料 → 生产
    返回 True=成功，False=失败
    """
    if stop_event.is_set():
        return False
    print(f"🏭 开始处理 {facility_name} ...")
    if not utils.find_and_click_smart(facility_img, timeout=15):
        return False
    time.sleep(0.5)

    if not utils.find_and_click_smart(config.MAKE, timeout=15):
        return False
    time.sleep(0.5)

    if not utils.find_and_click_smart(config.Collect, timeout=15):
        return False
    time.sleep(0.5)

    if not utils.find_and_click_smart(config.Claim_Reward, timeout=15):
        print(f"⚠️ 未找到领取奖励按钮，按 Esc 返回跳过 ({facility_name})")
        pyautogui.press("esc")
        time.sleep(0.5)
        pyautogui.press("esc")
        time.sleep(0.5)
    else:
        time.sleep(0.5)

    if not utils.find_and_click_smart(produce_item_img, timeout=15):
        return False
    time.sleep(0.5)

    if utils.find_and_click_smart(config.Auto_fill, timeout=8):
        print(f"🔧 一键补齐材料 ({facility_name})")
    else:
        print(f"ℹ️ 材料已足够，无需补齐 ({facility_name})")
    time.sleep(0.5)

    buy_attempts = 0
    while utils.find_and_click_smart(config.COIN_GAME, timeout=5):
        if stop_event.is_set():
            return False
        print(f"💰 购买材料 ({buy_attempts + 1}/5)")
        time.sleep(0.5)
        buy_attempts += 1
        if buy_attempts >= 5:
            print("⚠️ 购买尝试已达上限，可能价格波动频繁")
            break

    if not utils.find_and_click_smart(config.Produce, timeout=15):
        return False
    time.sleep(0.5)

    pyautogui.press("esc")
    time.sleep(0.5)
    print(f"✅ {facility_name} 处理完毕")
    if update_ui_callback:
        update_ui_callback()
    return True


def sell_operations(settings, stop_event, set_operation):
    """
    一键出售流程：打开仓库，遍历售卖物品执行出售
    返回 (success: bool, stats: dict)
    stats: {"total": N, "sold": N, "not_found": N, "failed": N}
    """
    sell_stats = {"total": 0, "sold": 0, "not_found": 0, "failed": 0}
    print("\n--- 一键出售 ---")
    set_operation("一键出售")

    # 未配置任何售卖物品时完全跳过售卖（不进入仓库）
    items_meta = config.load_sell_items_meta()
    sell_items = items_meta.get("items", [])
    if not sell_items:
        print("⚠️ 未配置任何售卖物品，跳过售卖")
        return False, sell_stats

    # 检查售卖时间区间
    if settings.get("sell_time_enabled", False):
        now = datetime.datetime.now().time()
        start_str = settings.get("sell_time_start", "08:00")
        end_str = settings.get("sell_time_end", "22:00")
        try:
            start_time = datetime.datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.datetime.strptime(end_str, "%H:%M").time()
            if not (start_time <= now <= end_time):
                print(f"⏰ 当前时间 {now.strftime('%H:%M')} 不在售卖区间 "
                      f"{start_str}-{end_str} 内，跳过售卖")
                return False, sell_stats
        except ValueError:
            print("⚠️ 售卖时间格式错误，跳过时间区间检查")

    # 清除模板缓存，确保使用最新模板
    utils.clear_template_cache()

    if not utils.find_and_click_smart(config.Warehouse, timeout=15):
        print("❌ 未找到仓库入口")
        return False, sell_stats
    # 等待仓库界面完全加载
    time.sleep(3)

    sell_confidence = settings.get("sell_confidence", 0.55)

    for item in sell_items:
        if stop_event.is_set():
            return False, sell_stats

        item_filename = item.get("filename", "")
        item_path = os.path.join(config.SELL_ITEMS_DIR, item_filename)
        if not os.path.exists(item_path):
            print(f"⚠️ 物品图片不存在：{item_filename}")
            continue

        item_name = item.get("name", item_filename)
        discount_times = item.get("discount_times", 0)
        quantity = item.get("quantity", 1)

        print(f"📦 出售物品：{item_name}（数量：{quantity}，降价：{discount_times}次）")
        sell_stats["total"] += quantity

        for qty in range(quantity):
            if stop_event.is_set():
                return False, sell_stats

            if quantity > 1:
                print(f"  📦 第 {qty + 1}/{quantity} 次出售")

            # 用户上传的出售物品图片无对应 OCR 文本，直接图像匹配
            if not utils.find_and_click(item_path, timeout=10, confidence=sell_confidence):
                print(f"⚠️ 未找到物品 {item_name}，跳过")
                sell_stats["not_found"] += 1
                break
            time.sleep(0.5)

            if not utils.find_and_click_smart(config.Sell, timeout=10):
                print(f"❌ 未找到出售按钮")
                sell_stats["failed"] += 1
                break
            time.sleep(0.5)

            if not utils.find_and_click_smart(config.List_Item, timeout=10):
                print(f"❌ 未找到上架按钮")
                sell_stats["failed"] += 1
                break
            utils.smooth_move_to(20, 20)
            time.sleep(0.5)

            if discount_times > 0:
                # 首次识别降价按钮并点击，鼠标停在按钮位置
                if utils.find_and_click_smart(config.Discount, timeout=5):
                    print(f"📉 降价 1/{discount_times}")
                    time.sleep(0.3)
                    # 鼠标已在按钮上，原地继续点击剩余次数
                    for _ in range(1, discount_times):
                        pyautogui.click()
                        time.sleep(0.3)

            if not utils.find_and_click_smart(config.Confirm_Listing, timeout=10):
                print(f"❌ 未找到确认上架按钮")
                sell_stats["failed"] += 1
                break
            time.sleep(1.5)
            sell_stats["sold"] += 1
            if quantity > 1:
                print(f"  ✅ 第 {qty + 1}/{quantity} 次出售完成")

        print(f"✅ {item_name} 出售完成")

    print(f"✅ 一键出售完成：共 {sell_stats['total']} 件，"
          f"成功 {sell_stats['sold']} 件，"
          f"未找到 {sell_stats['not_found']} 件，"
          f"失败 {sell_stats['failed']} 件")
    return True, sell_stats


def _ensure_game_focused():
    """确保游戏窗口在前台，防止外部窗口遮挡导致识别失败"""
    try:
        import win32gui
        for title in ["三角洲行动", "DeltaForce", "Delta Force", "三角洲", "Delta"]:
            hwnd = win32gui.FindWindow(None, title)
            if hwnd:
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.3)
                return True
    except Exception:
        pass
    return False


def game_operations(settings, stop_event, set_operation, update_ui_callback=None):
    """
    执行游戏内操作（导航、设施处理、一键出售、邮箱货币）
    返回 True=成功，False=失败
    """
    print("\n--- 进入游戏操作 ---")
    _ensure_game_focused()

    set_operation("进入烽火地带")
    print("进入烽火地带...")
    for retry in range(5):
        if stop_event.is_set():
            return False
        if utils.find_and_click_smart(config.Hazard_Operations, timeout=15):
            break
        print(f"⚠️ 未找到烽火地带图标，5秒后重试 ({retry + 1}/5)...")
        _ensure_game_focused()
        time.sleep(5)
    else:
        print("❌ 5次重试后仍未找到烽火地带图标")
        return "game_failed"

    time.sleep(5)

    _ensure_game_focused()
    set_operation("进入大厅 / 特勤处")
    print("进入大厅...")
    pyautogui.press("Space")
    time.sleep(0.5)
    pyautogui.press("Space")
    time.sleep(0.8)
    pyautogui.press("Tab")
    time.sleep(1)

    for retry in range(3):
        if stop_event.is_set():
            return False
        if utils.find_and_click_smart(config.Special_Ops, timeout=15):
            break
        print(f"⚠️ 未找到特勤处图标，5秒后重试 ({retry + 1}/3)...")
        time.sleep(5)
    else:
        print("❌ 多次重试后仍未找到特勤处图标")
        return "game_failed"
    time.sleep(0.5)

    selected_ops = settings.get("selected_operations", [])
    all_facilities = [
        ("tech_center", config.Tech_Center, config.Produce_TechCenter, "技术中心"),
        ("tool_bench", config.Tool_Bench, config.Produce_ToolBench, "工作台"),
        ("armor_station", config.Armor_Station, config.Produce_ArmorStation, "防具台"),
        ("pharmacy_station", config.Pharmacy_Station, config.Produce_PharmacyStation, "制药台"),
    ]
    facilities = [(f[1], f[2], f[3]) for f in all_facilities if f[0] in selected_ops]
    if not facilities:
        print("ℹ️ 未选择任何设施操作，跳过游戏内操作")
        return True
    op_names = [f[3] for f in all_facilities if f[0] in selected_ops]
    print(f"🔧 将执行：{'、'.join(op_names)}")
    all_success = True
    for fac_img, prod_img, fac_name in facilities:
        if stop_event.is_set():
            return False
        set_operation(f"处理 {fac_name}")
        _ensure_game_focused()
        if not handle_facility(fac_img, prod_img, fac_name, stop_event, set_operation, update_ui_callback):
            if not stop_event.is_set():
                print(f"❌ 处理{fac_name}失败，终止当前账号")
                all_success = False
                break
        pyautogui.press("esc")
        time.sleep(0.5)
    if all_success:
        print("✅ 所有设施处理完成")

    if not all_success:
        return False

    # 主流程完成后执行一键出售
    sell_stats = None
    if settings.get("enable_sell_after_run", False):
        print("\n--- 主流程完成，执行一键出售 ---")
        pyautogui.press("esc")
        time.sleep(1)
        _, sell_stats = sell_operations(settings, stop_event, set_operation)

    # --- 邮箱货币领取（出售完成后） ---
    if settings.get("enable_email_currency", False):
        print("\n--- 检查邮箱货币 ---")
        set_operation("领取邮箱货币")
        # 确保回到主界面
        pyautogui.press("esc")
        time.sleep(1)
        if utils.find_and_click_smart(config.EMAIL_MAIL, timeout=10):
            time.sleep(1)
            if utils.find_and_click_smart(config.EMAIL_TRADE_HOUSE, timeout=10):
                time.sleep(0.5)
                if utils.find_and_click_smart(config.EMAIL_CLAIM_ALL, timeout=10):
                    time.sleep(0.5)
                    utils.find_and_click_smart(config.EMAIL_RECEIVE_COMPLETED, timeout=10)
                    time.sleep(0.5)
                pyautogui.press("esc")
                time.sleep(0.5)
            print("✅ 邮箱货币领取流程完成")
        else:
            print("ℹ️ 未找到邮箱入口，跳过邮箱货币领取")

    # 汇总返回数据
    extra = {}
    if sell_stats is not None:
        extra["sell_stats"] = sell_stats
    if extra:
        return True, extra
    return True
