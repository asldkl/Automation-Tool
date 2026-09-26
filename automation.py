"""
自动化流程模块
包含游戏内操作、设施处理、一键出售等核心自动化逻辑
从 gui_app.py 拆分而来，降低单文件复杂度
"""
import os
import time
import random
import datetime
import pyautogui

import config
import utils


def _hook(run_insert, var_name, timing):
    """运行某模板的「插入步骤」（点击前/后）。run_insert 为空或该模板未配置 → True；
    插入步骤执行失败 → False（调用处应视为该模板失败）"""
    if run_insert is None:
        return True
    try:
        return bool(run_insert(var_name, timing))
    except Exception as e:
        print(f"⚠️ 模板[{var_name}]插入步骤回调异常：{e}")
        return True


def _click(run_insert, var_name, img_path, timeout=15, **kw):
    """识别点击某模板图并夹入其插入步骤。
    返回：True=点击成功（无插入或插入成功）；
         'nofind'=未找到图（原失败语义）；
         'insert'=插入步骤失败（应视为该模板点击失败处理）"""
    if not _hook(run_insert, var_name, "before"):
        return "insert"
    if not utils.find_and_click_smart(img_path, timeout=timeout, **kw):
        return "nofind"
    if not _hook(run_insert, var_name, "after"):
        return "insert"
    return True


def _craft_tail(facility_name, stop_event, run_insert=None):
    """制造流程的后半段：#21 一键补齐 → #22 游戏币购买 → #23 产出

    正常流程（handle_facility）与自纠错（_self_correct_vacancies）**共用这一段**，
    保证两条路点的是同一批按钮、同样夹插入步骤（插入步骤可能正是「让按钮可点」的前提，
    所以自纠错也必须执行，不能省）。

    返回 ""=成功；"未制造"=点产出失败；"中断"=收到停止信号
    """
    # 一键补齐（可选模板）：未找到/插入失败均按「材料已足够」继续
    if not _hook(run_insert, "Auto_fill", "before"):
        print("ℹ️ 一键补齐 插入步骤(点击前)失败，按材料足够处理")
    elif utils.find_and_click_smart(config.Auto_fill, timeout=8):
        print(f"🔧 一键补齐材料 ({facility_name})")
        _hook(run_insert, "Auto_fill", "after")   # 失败仅记录，不中断
    else:
        print(f"ℹ️ 材料已足够，无需补齐 ({facility_name})")
    utils.human_pause()

    # 游戏币购买（while 循环按钮）：整个购买块前/后各触发一次插入步骤
    _hook(run_insert, "COIN_GAME", "before")
    buy_attempts = 0
    while utils.find_and_click_smart(config.COIN_GAME, timeout=5):
        if stop_event.is_set():
            return "中断"
        print(f"💰 购买材料 ({buy_attempts + 1}/5)")
        utils.human_pause()
        buy_attempts += 1
        if buy_attempts >= 5:
            print("⚠️ 购买尝试已达上限，可能价格波动频繁")
            break
    if buy_attempts > 0:
        _hook(run_insert, "COIN_GAME", "after")

    if _click(run_insert, "Produce", config.Produce, 15) is not True:
        return "未制造"
    utils.human_pause()
    return ""


def handle_facility(facility_img, produce_item_img, facility_name, stop_event, set_operation,
                    update_ui_callback=None, fac_var="", prod_var="", run_insert=None,
                    stage_sink=None):
    """
    处理单个设施的完整流程：进入设施 → 收取 → 选择产出 → 补齐材料 → 生产
    fac_var / prod_var: 设施图标与产出项的模板 var_name（插入步骤用）
    run_insert: 插入步骤执行回调 ri(var_name, timing)
    stage_sink: 可选 dict，失败时写入 {"stage": "未领取"/"未制造"/...}，供日志与邮件报告说明是哪一步断的
    返回 True=成功，False=失败
    """
    def _fail(stage=""):
        if stage_sink is not None and stage:
            stage_sink["stage"] = stage
        return False

    if stop_event.is_set():
        return False
    print(f"🏭 开始处理 {facility_name} ...")
    if _click(run_insert, fac_var, facility_img, 15) is not True:
        return _fail("未进入设施")
    utils.human_pause()

    if _click(run_insert, "MAKE", config.MAKE, 15) is not True:
        return _fail("未找到制造页")
    utils.human_pause()

    if _click(run_insert, "Collect", config.Collect, 15) is not True:
        return _fail("未领取")
    utils.human_pause()

    # 领取奖励：直接按两次空格领取（无需图片识别，对应模板第20步）
    pyautogui.press("Space")
    time.sleep(0.3)
    pyautogui.press("Space")
    utils.human_pause()

    if _click(run_insert, prod_var, produce_item_img, 15) is not True:
        return _fail("未找到产出项")
    utils.human_pause()

    # 制造后半段（#21 一键补齐 → #22 游戏币 → #23 产出）与自纠错共用，见 _craft_tail
    _tail = _craft_tail(facility_name, stop_event, run_insert)
    if _tail == "中断":
        return False          # 停止信号：与原来一致，不写 stage
    if _tail:
        return _fail(_tail)

    pyautogui.press("esc")
    utils.human_pause()
    print(f"✅ {facility_name} 处理完毕")
    if update_ui_callback:
        update_ui_callback()
    return True


def _self_correct_vacancies(facilities, stop_event, set_operation, run_insert=None):
    """自纠错：进特勤处后先把「已领取但未制造」的空缺补掉（开关 self_correct_enabled）

    一圈做 4 步：
      1. 只识别「制造空缺」#33（**不点击**）—— 拿到坐标就停手；没找到 → 结束预扫描
      2. 点它 → 进该设施，再只识别 4 个产出项 → 反认是哪个设施
      3. 点 #21 一键补齐 → #22 游戏币 → #23 产出（与正常流程共用 _craft_tail）
      4. Esc 回特勤处，记下「已补」→ 回到第 1 步（最多 4 圈，对应 4 个设施）

    ⚠️ 任何一步失败 / 认出重复设施 → **立即收手，不中断账号**（自纠错是加分项，不是必需项）。
    ⚠️ 缺第 33 项模板时直接返回空 dict（当作没开），不报错、不影响主流程。

    facilities: 完整元组列表 [(key, fac_img, prod_img, fac_name, fac_var, prod_var), ...]
    返回 (已补设施 {key: 名称}, 说明文本)
    """
    done = {}
    notes = []

    vacancy_img = config.resolve_template_path(config.Manufacture_Vacancy)
    if not vacancy_img or not os.path.exists(vacancy_img):
        return done, "未截取第 33 项「制造空缺」模板 → 自纠错本次不生效"

    max_rounds = max(1, len(facilities))
    for rnd in range(1, max_rounds + 1):
        if stop_event.is_set():
            notes.append("收到停止信号")
            break
        set_operation(f"自纠错：扫描制造空缺（{rnd}/{max_rounds}）")
        _ensure_game_focused()

        # ① 只识别不点击：确认真有空缺，避免往空白处乱点
        ok, pos = utils.find_image_pos(vacancy_img, timeout=5, stop_event=stop_event)
        if not ok:
            print(f"ℹ️ 自纠错：第 {rnd} 圈未识别到制造空缺，结束预扫描")
            if rnd == 1:
                notes.append("未发现制造空缺")
            break

        # ② 点它进设施（find_image_pos 只给坐标，点击由这里做）
        print(f"🧩 自纠错：发现制造空缺（{pos[0]},{pos[1]}），进入该设施...")
        utils.smooth_move_to(pos[0], pos[1], duration=0.2)
        utils.human_click_delay()
        pyautogui.click()
        utils.human_pause()

        # 靠 4 个产出项反认是哪个设施（空缺图标 4 设施共用，认不出设施就不敢乱补）
        hit_key, hit_name = "", ""
        for _key, _fac_img, _prod_img, _fac_name, _fac_var, _prod_var in facilities:
            if stop_event.is_set():
                break
            _found, _ = utils.find_image_pos(_prod_img, timeout=2, stop_event=stop_event)
            if _found:
                hit_key, hit_name = _key, _fac_name
                break
        if not hit_key:
            print("⚠️ 自纠错：4 个产出项都没认出来，无法确定是哪个设施 → 收手")
            notes.append(f"第 {rnd} 圈认不出设施，收手")
            pyautogui.press("esc")
            utils.human_pause()
            break
        if hit_key in done:
            print(f"⚠️ 自纠错：又认出「{hit_name}」（本轮已补过）→ 收手，避免反复点同一个")
            notes.append(f"第 {rnd} 圈重复认出「{hit_name}」，收手")
            pyautogui.press("esc")
            utils.human_pause()
            break

        # ③ 补制造（与正常流程同一段）
        print(f"🧩 自纠错：空缺属于「{hit_name}」，补制造流程...")
        _tail = _craft_tail(hit_name, stop_event, run_insert)

        # ④ Esc 回特勤处，准备下一圈
        pyautogui.press("esc")
        utils.human_pause()

        if _tail:
            print(f"⚠️ 自纠错：「{hit_name}」补制造失败（{_tail}）→ 收手")
            notes.append(f"「{hit_name}」补制造失败（{_tail}），收手")
            break
        done[hit_key] = hit_name
        notes.append(f"已补「{hit_name}」")

    return done, "；".join(notes)


def _in_sell_window(settings):
    """当前是否在售卖时间区间内；未启用时间限制或格式错误视为在区间内"""
    if not settings.get("sell_time_enabled", False):
        return True
    try:
        now = datetime.datetime.now().time()
        start_time = datetime.datetime.strptime(settings.get("sell_time_start", "08:00"), "%H:%M").time()
        end_time = datetime.datetime.strptime(settings.get("sell_time_end", "22:00"), "%H:%M").time()
        return start_time <= now <= end_time
    except Exception:
        return True


def sell_operations(settings, stop_event, set_operation, run_insert=None, skip_warehouse=False,
                    ignore_time_window=False):
    """
    一键出售流程：打开仓库，遍历售卖物品执行出售（每件物品走一遍）
    skip_warehouse: True 时不点「仓库入口」，直接从「逐个识别物品」开始
                    （出售测试用：由用户自行先进入仓库界面）
    ignore_time_window: True 时不检查「售卖时间区间」（出售测试用：手动点测试就该能测，
                    否则在区间外测试必然一件都不卖；主流程保持 False 仍受时间限制）
    run_insert: 插入步骤执行回调 ri(var_name, timing)
    返回 (success: bool, stats: dict)
    stats: {"total": N, "sold": N, "not_found": N, "failed": N,
            "reason": "为什么会「一件都没卖」的原因码", "missing_files": N}
           reason 取值：""(正常) / "no_items"(没配置物品) / "out_of_window"(不在售卖时段)
                        / "warehouse_not_found"(找不到仓库入口) / "stopped"(收到停止信号)
                        / "all_missing"(配了物品但图片文件都不在了)
           —— 调用方（出售测试弹窗）据此给出准确提示，避免一条笼统文案套所有情况

    注：上架后会点一下「最大数量」把数量一次挂满 —— 已改为**固定坐标点击**
    （settings["max_quantity_point"]，默认 [0, 0]＝跳过该步，向导第 30 项里取点/填写），
    不再依赖模板 Max_Quantity，也不叠加拟人随机偏移；坐标超出屏幕范围同样跳过（并告警）。
    所以不再有「出售数量」配置，也不再有补卖轮数。"""
    sell_stats = {"total": 0, "sold": 0, "not_found": 0, "failed": 0,
                  "reason": "", "missing_files": 0}
    print("\n--- 一键出售 ---")
    set_operation("一键出售")

    # 未配置任何售卖物品时完全跳过售卖（不进入仓库）
    items_meta = config.load_sell_items_meta()
    sell_items = items_meta.get("items", [])
    if not sell_items:
        print("⚠️ 未配置任何售卖物品，跳过售卖")
        sell_stats["reason"] = "no_items"
        return False, sell_stats

    # 检查售卖时间区间（出售测试传 ignore_time_window=True 可跳过）
    if ignore_time_window and not _in_sell_window(settings):
        print(f"⏭️ 出售测试：忽略「售卖时间区间」限制"
              f"（{settings.get('sell_time_start', '08:00')}-{settings.get('sell_time_end', '22:00')}）")
    elif not _in_sell_window(settings):
        now = datetime.datetime.now()
        print(f"⏰ 当前时间 {now.strftime('%H:%M')} 不在售卖区间 "
              f"{settings.get('sell_time_start', '08:00')}-{settings.get('sell_time_end', '22:00')} 内，跳过售卖")
        sell_stats["reason"] = "out_of_window"
        return False, sell_stats

    # 清除模板缓存，确保使用最新模板
    utils.clear_template_cache()

    if skip_warehouse:
        # 出售测试：不点「仓库入口」，由用户自行先进入仓库界面
        print("⏭️ 跳过「打开仓库」步骤（由用户自行进入仓库界面）")
    else:
        if _click(run_insert, "Warehouse", config.Warehouse, 15) is not True:
            print("❌ 未找到仓库入口（或插入步骤失败），结束出售")
            sell_stats["reason"] = "warehouse_not_found"
            return False, sell_stats
        # 等待仓库界面完全加载
        time.sleep(3)

    sell_confidence = settings.get("sell_confidence", 0.55)

    # 每个账号随机化售卖物品顺序（避免每次固定顺序，降低脚本特征）
    random.shuffle(sell_items)

    for item in sell_items:
        if stop_event.is_set():
            sell_stats["reason"] = "stopped"
            return False, sell_stats

        item_filename = item.get("filename", "")
        item_path = os.path.join(config.SELL_ITEMS_DIR, item_filename)
        if not os.path.exists(item_path):
            print(f"⚠️ 物品图片不存在：{item_filename}")
            sell_stats["missing_files"] += 1
            continue

        item_name = item.get("name", item_filename)
        discount_times = item.get("discount_times", 0)

        print(f"📦 出售物品：{item_name}（降价：{discount_times}次）")
        sell_stats["total"] += 1

        if stop_event.is_set():
            sell_stats["reason"] = "stopped"
            return False, sell_stats

        # 用户上传的出售物品图片无对应 OCR 文本，直接图像匹配
        if not utils.find_and_click(item_path, timeout=10, confidence=sell_confidence):
            print(f"⚠️ 未找到物品 {item_name}，跳过")
            sell_stats["not_found"] += 1
            continue
        utils.human_pause()

        if _click(run_insert, "Sell", config.Sell, 10) is not True:
            print(f"❌ 未找到出售按钮")
            sell_stats["failed"] += 1
            continue
        utils.human_pause()

        if _click(run_insert, "List_Item", config.List_Item, 10) is not True:
            print(f"❌ 未找到上架按钮")
            sell_stats["failed"] += 1
            continue
        # 鼠标随机移动到距离当前位置 300 像素以上处（避免固定在左上角的机械化特征）
        utils.human_move_away(min_dist=300)
        utils.human_pause()

        # 上架后、降价前：点一下「最大数量」，一次把数量挂满（不用再配「出售数量」）。
        # 「固定坐标点击」（模板上传向导第 30 项「模板设置」→「点击坐标」可改/屏幕取点）：
        # 该按钮位置固定，走模板匹配反而会因模板缺失或识别失败而静默跳过。
        # 这里严格点在坐标上，不叠加拟人随机偏移；坐标填 0（默认）或超出屏幕范围都跳过本步。
        mq = settings.get("max_quantity_point") or [0, 0]
        try:
            mq_x, mq_y = int(mq[0]), int(mq[1])
        except (TypeError, ValueError, IndexError):
            mq_x, mq_y = 0, 0
        try:
            _scr_w, _scr_h = pyautogui.size()
        except Exception:
            _scr_w, _scr_h = 0, 0
        mq_out_of_range = bool(_scr_w and _scr_h and (mq_x > _scr_w or mq_y > _scr_h))
        if not _hook(run_insert, "Max_Quantity", "before"):
            print("  ⚠️ 「最大数量」插入步骤(点击前)失败，跳过本步")
        elif mq_x <= 0 or mq_y <= 0:
            print("  ℹ️ 未设置「最大数量」坐标，跳过本步")
        elif mq_out_of_range:
            # 越界点击会被系统截到屏幕边缘、可能点到别的东西，宁可跳过
            print(f"  ⚠️ 「最大数量」坐标 {mq_x},{mq_y} 超出屏幕范围（{_scr_w}x{_scr_h}），已跳过该步")
        else:
            utils.smooth_move_to(mq_x, mq_y)
            utils.human_click_delay()
            pyautogui.click()
            print(f"  🔢 已选择最大数量（固定坐标 {mq_x},{mq_y}）")
            _hook(run_insert, "Max_Quantity", "after")
            utils.human_pause()

        if discount_times > 0:
            # 首次识别降价按钮并点击，鼠标停在按钮位置
            if _click(run_insert, "Discount", config.Discount, 5) is True:
                print(f"📉 降价 1/{discount_times}")
                time.sleep(0.3)
                # 鼠标已在按钮上，原地继续点击剩余次数
                for _ in range(1, discount_times):
                    pyautogui.click()
                    time.sleep(0.3)

        if _click(run_insert, "Confirm_Listing", config.Confirm_Listing, 10) is not True:
            print(f"❌ 未找到确认上架按钮")
            sell_stats["failed"] += 1
            continue
        time.sleep(1.5)
        sell_stats["sold"] += 1
        print(f"✅ {item_name} 出售完成")

    # 一件都没轮到处理：说明配置的物品其图片文件都不在了（列表里每一条都被跳过）
    if sell_stats["total"] == 0 and sell_stats["missing_files"] > 0:
        sell_stats["reason"] = "all_missing"

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


def game_operations(settings, stop_event, set_operation, update_ui_callback=None, on_hub_entered=None,
                    observe_mode=False, hazard_retry=5, run_insert=None, account_name="",
                    facility_sink=None):
    """
    执行游戏内操作（导航、设施处理、一键出售、邮箱货币）
    on_hub_entered: 进入大厅（空格Tab后、特勤处前）的回调，用于资产识别
    observe_mode: 观察状态账号，在按下烽火地带前先识别并点击观察状态入口（可选模板）
    hazard_retry: 烽火地带入口识别重试次数（单账号运行为 3，主流程为 5）
    facility_sink: 可选 list，写完设施结果 [(摘要字符串, [(设施名,结果),...])]，供邮件报告使用
    run_insert: 插入步骤执行回调 ri(var_name, timing)
    返回 True=成功，False=失败
    """
    print("\n--- 进入游戏操作 ---")
    _ensure_game_focused()

    # 观察状态账号：进入烽火地带前识别观察状态入口（可选模板，最多3次重试，失败间隔4秒；仍失败则跳过）
    if observe_mode and os.path.exists(config.resolve_template_path(config.Observe)):
        set_operation("观察状态入口")
        print("🔍 观察账号：识别观察状态入口...")
        observe_found = False
        if _hook(run_insert, "Observe", "before"):
            for retry in range(5):
                if stop_event.is_set():
                    return False
                if utils.find_and_click_smart(config.Observe, timeout=8):
                    observe_found = True
                    break
                print(f"⚠️ 未找到观察状态入口，4秒后重试 ({retry + 1}/5)...")
                time.sleep(4)
        else:
            print("⚠️ 观察状态入口 插入步骤(点击前)失败，跳过")
        if observe_found:
            # 可选步骤：点击后插入步骤失败仅记录，不影响后续流程
            if _hook(run_insert, "Observe", "after"):
                print("✅ 已进入观察状态入口")
            else:
                print("⚠️ 观察状态入口 插入步骤(点击后)失败，继续主流程")
        else:
            print("ℹ️ 5次重试后仍未找到观察状态入口，跳过（不影响后续流程）")
        utils.human_pause()

    set_operation("进入烽火地带")
    print("进入烽火地带...")
    # 插入步骤（点击前）：失败按烽火地带识别失败处理（game_failed）
    if not _hook(run_insert, "Hazard_Operations", "before"):
        print("❌ 烽火地带入口 插入步骤(点击前)失败，视为模板失败")
        return "game_failed"
    hazard_clicked = False
    for retry in range(hazard_retry):
        if stop_event.is_set():
            return False
        if utils.find_and_click_smart(config.Hazard_Operations, timeout=15):
            hazard_clicked = True
            break
        print(f"⚠️ 未找到烽火地带图标，5秒后重试 ({retry + 1}/{hazard_retry})...")
        _ensure_game_focused()
        time.sleep(5)
    if not hazard_clicked:
        print(f"❌ {hazard_retry}次重试后仍未找到烽火地带图标")
        return "game_failed"
    if not _hook(run_insert, "Hazard_Operations", "after"):
        print("❌ 烽火地带入口 插入步骤(点击后)失败，视为模板失败")
        return "game_failed"

    time.sleep(5)

    _ensure_game_focused()
    set_operation("进入大厅 / 特勤处")
    print("进入大厅...")
    pyautogui.press("Space")
    utils.human_pause()
    pyautogui.press("Space")
    time.sleep(0.8)
    pyautogui.press("Tab")
    time.sleep(1)

    # 进入特勤处前，给一点时间做资产识别（候选A）
    if on_hub_entered:
        try:
            on_hub_entered()
        except Exception:
            pass

    if not _hook(run_insert, "Special_Ops", "before"):
        print("❌ 特勤处入口 插入步骤(点击前)失败，视为模板失败")
        return "game_failed"
    special_clicked = False
    for retry in range(3):
        if stop_event.is_set():
            return False
        if utils.find_and_click_smart(config.Special_Ops, timeout=15):
            special_clicked = True
            break
        print(f"⚠️ 未找到特勤处图标，5秒后重试 ({retry + 1}/3)...")
        time.sleep(5)
    if not special_clicked:
        print("❌ 多次重试后仍未找到特勤处图标")
        return "game_failed"
    if not _hook(run_insert, "Special_Ops", "after"):
        print("❌ 特勤处入口 插入步骤(点击后)失败，视为模板失败")
        return "game_failed"
    utils.human_pause()

    selected_ops = settings.get("selected_operations", [])
    all_facilities = [
        ("tech_center", config.Tech_Center, config.Produce_TechCenter, "技术中心",
         "Tech_Center", "Produce_TechCenter"),
        ("tool_bench", config.Tool_Bench, config.Produce_ToolBench, "工作台",
         "Tool_Bench", "Produce_ToolBench"),
        ("armor_station", config.Armor_Station, config.Produce_ArmorStation, "防具台",
         "Armor_Station", "Produce_ArmorStation"),
        ("pharmacy_station", config.Pharmacy_Station, config.Produce_PharmacyStation, "制药台",
         "Pharmacy_Station", "Produce_PharmacyStation"),
    ]
    # ⚠️ 保留完整元组（含设施 key）：自纠错要靠 key 记住「已补过哪个设施」，
    #    正常流程也要按 key 跳过它。索引：0=key 1=设施图 2=产出项图 3=设施名 4/5=模板 var
    facilities = [f for f in all_facilities if f[0] in selected_ops]
    if not facilities:
        print("ℹ️ 未选择任何设施操作，跳过游戏内操作")
        return True
    op_names = [f[3] for f in all_facilities if f[0] in selected_ops]
    # 4 个设施组（制造+收取等成组）执行顺序随机，降低固定顺序的脚本特征
    random.shuffle(facilities)
    print(f"🔧 将执行：{'、'.join(op_names)}")

    # ----- 自纠错：先把「已领取但未制造」的空缺补掉（默认关，见 self_correct_enabled）-----
    # 位置：进特勤处之后、正常流程之前；补过的设施在正常流程里整段跳过（连领取也不做）
    _sc_done = {}
    if settings.get("self_correct_enabled", False):
        try:
            _sc_done, _sc_note = _self_correct_vacancies(facilities, stop_event,
                                                         set_operation, run_insert)
            if _sc_note:
                print(f"🧩 自纠错：{_sc_note}")
            if _sc_done:
                print(f"🧩 自纠错：{'、'.join(_sc_done.values())} 在正常流程里整段跳过")
        except Exception as e:
            print(f"⚠️ 自纠错异常，按未启用处理（不影响正常流程）：{e}")
            _sc_done = {}

    all_success = True
    fac_results = []        # [(设施名, 结果)] 结果：✓ / 已补 / 未领取 / 未制造 / 未进入设施 ...
    _processed = 0          # 已轮到的设施数（含跳过与失败）——用于把剩下的标「未执行」
    for _idx, (_key, fac_img, prod_img, fac_name, fac_var, prod_var) in enumerate(facilities):
        if stop_event.is_set():
            return False
        if _key in _sc_done:
            print(f"⏭️ 「{fac_name}」已在自纠错里补过制造，整段跳过（连领取也不做）")
            fac_results.append((fac_name, "已补"))
            _processed = _idx + 1
            continue
        set_operation(f"处理 {fac_name}")
        _ensure_game_focused()
        _sink = {"stage": ""}
        if not handle_facility(fac_img, prod_img, fac_name, stop_event, set_operation,
                               update_ui_callback, fac_var=fac_var, prod_var=prod_var,
                               run_insert=run_insert, stage_sink=_sink):
            _processed = _idx + 1
            if not stop_event.is_set():
                _why = _sink.get("stage") or "失败"
                print(f"❌ 处理{fac_name}失败（{_why}），终止当前账号")
                fac_results.append((fac_name, f"✗{_why}"))
                all_success = False
                break
            fac_results.append((fac_name, "✗中断"))
            break
        fac_results.append((fac_name, "✓"))
        _processed = _idx + 1
        pyautogui.press("esc")
        utils.human_pause()
    # 因前面失败而没轮到的设施标记为「未执行」
    # ⚠️ 游标不能用 len(fac_results)：自纠错跳过的设施也会写进 fac_results，会整体错位
    for _f in facilities[_processed:]:
        fac_results.append((_f[3], "未执行"))
    if fac_results:
        _fac_summary = "  ".join(f"{n}{st}" for n, st in fac_results)
        print(f"📋 设施结果：{_fac_summary}")
        if facility_sink is not None:
            facility_sink.clear()
            facility_sink.append((_fac_summary, fac_results))
    if all_success:
        print("✅ 所有设施处理完成")

    if not all_success:
        return False

    # 主流程完成后执行一键出售
    sell_stats = None
    sell_skipped_by_time = False
    if settings.get("enable_sell_after_run", False):
        print("\n--- 主流程完成，执行一键出售 ---")
        pyautogui.press("esc")
        time.sleep(1)
        _acc_key = ""
        try:
            import cooldown_manager as _cm
            _acc_key = _cm.normalize_key(account_name) if account_name else ""
        except Exception:
            _acc_key = account_name or ""
        if not _in_sell_window(settings):
            # 不在售卖时段：跳过售卖（并跳过邮箱领取）
            sell_skipped_by_time = True
            print("⏰ 不在售卖时间区间：本次跳过一键出售（邮箱领取也一并跳过）")
            try:
                import sell_pending as _sp
                if _acc_key:
                    _n = _sp.add_pending(_acc_key, 1)
                    print(f"📦 账号 {_acc_key} 未售次数累加为 {_n}（仅作记录：上架时会点「最大数量」，"
                          f"进入售卖时段后一次就能挂满，不再补卖多轮）")
            except Exception as _e:
                print(f"⚠️ 未售次数累加失败：{_e}")
        else:
            _, sell_stats = sell_operations(settings, stop_event, set_operation,
                                            run_insert=run_insert)
            if _acc_key:
                try:
                    import sell_pending as _sp
                    _sp.clear_pending(_acc_key)
                except Exception:
                    pass
            # 出售完成：关闭仓库回到主界面（若接下来走邮箱流程，其开头会再 esc，无需重复）
            if not settings.get("enable_email_currency", False):
                pyautogui.press("esc")
                time.sleep(0.8)

    # --- 邮箱货币领取（出售完成后；若因不在售卖时段跳过了售卖，则本次也不领取） ---
    if settings.get("enable_email_currency", False) and sell_skipped_by_time:
        print("ℹ️ 因跳过售卖（不在售卖时段），本次不领取邮箱货币")
    elif settings.get("enable_email_currency", False):
        print("\n--- 检查邮箱货币 ---")
        set_operation("领取邮箱货币")
        # 确保回到主界面（若此前已不在二级界面，esc 会打开系统菜单，由下方补按一次 esc 纠正）
        pyautogui.press("esc")
        time.sleep(1)
        # 注意区分点击结果：True=成功、'nofind'=未找到、'insert'=点击成功但插入步骤失败（界面已切换，仍需 esc 退出）
        _mail = _click(run_insert, "EMAIL_MAIL", config.EMAIL_MAIL, 10)
        if _mail == "nofind":
            # 第一次 esc 可能误开了系统菜单（此前已在主界面）：补按一次 esc 关闭后再找一次
            pyautogui.press("esc")
            time.sleep(1)
            _mail = _click(run_insert, "EMAIL_MAIL", config.EMAIL_MAIL, 6)
        if _mail == "nofind":
            print("ℹ️ 未找到邮箱入口，跳过邮箱货币领取")
        else:
            time.sleep(1)
            _trade = _click(run_insert, "EMAIL_TRADE_HOUSE", config.EMAIL_TRADE_HOUSE, 10)
            if _trade != "nofind":
                utils.human_pause()
                _claim = _click(run_insert, "EMAIL_CLAIM_ALL", config.EMAIL_CLAIM_ALL, 10)
                if _claim is True:
                    utils.human_pause()
                    # 领取完成：直接按两次空格确认（对应模板第27步，无需图片识别）
                    pyautogui.press("Space")
                    time.sleep(0.3)
                    pyautogui.press("Space")
                    time.sleep(0.5)
                    utils.human_pause()
                    print("✅ 邮箱货币领取流程完成")
                elif _claim == "nofind":
                    print("ℹ️ 未找到全部领取按钮")
                else:
                    print("ℹ️ 全部领取 插入步骤失败")
                utils.human_pause()
            elif _trade == "insert":
                print("ℹ️ 交易中心入口 插入步骤失败")
            # 收尾：只按一次 esc 回到主界面（领取用两下空格确认，无需再逐层退出）
            pyautogui.press("esc")
            time.sleep(0.8)

    # 汇总返回数据
    extra = {}
    if sell_stats is not None:
        extra["sell_stats"] = sell_stats
    if extra:
        return True, extra
    return True
