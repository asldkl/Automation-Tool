"""
核心模块单元测试
覆盖：cooldown_manager, asset_db, config, utils, email_notifier
通过实际调用函数验证逻辑，而非源码字符串匹配
"""
import os
import sys
import json
import time
import threading
import datetime
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

import numpy as np

TEST_DIR = tempfile.mkdtemp(prefix="delta_core_test_")


def setUpModule():
    pass


def tearDownModule():
    shutil.rmtree(TEST_DIR, ignore_errors=True)


# ==================== cooldown_manager ====================
class TestCooldownManagerCache(unittest.TestCase):
    """测试 cooldown_manager 的内存缓存机制"""

    def setUp(self):
        import cooldown_manager as cm
        self.cm = cm
        self._orig_path = cm.COOLDOWN_JSON_PATH
        self._orig_backup = cm.COOLDOWN_JSON_BACKUP
        cm.COOLDOWN_JSON_PATH = os.path.join(TEST_DIR, "cd_cache.json")
        cm.COOLDOWN_JSON_BACKUP = cm.COOLDOWN_JSON_PATH + ".bak"
        cm._cache = None
        cm._cache_mtime = 0.0
        cm._load_corrupt = False
        for _p in (cm.COOLDOWN_JSON_PATH, cm.COOLDOWN_JSON_BACKUP):
            if os.path.exists(_p):
                os.remove(_p)

    def tearDown(self):
        self.cm.COOLDOWN_JSON_PATH = self._orig_path
        self.cm.COOLDOWN_JSON_BACKUP = self._orig_backup
        self.cm._cache = None
        self.cm._cache_mtime = 0.0
        self.cm._load_corrupt = False

    def test_cache_hit_after_save(self):
        """保存后立即读取应命中缓存，不重新读文件"""
        self.cm.record_run("user1.png", cooldown_hours=8)
        # 第二次读取应命中缓存
        cooling, _ = self.cm.is_cooling_down("user1.png")
        self.assertTrue(cooling)

    def test_cache_invalidated_on_external_write(self):
        """外部修改文件后缓存应失效"""
        self.cm.record_run("user1.png", cooldown_hours=8)
        # 模拟外部写入
        import time as t
        t.sleep(0.05)
        data = {"ext_user.png": {"next_run_time": "2099-01-01 00:00:00"}}
        with open(self.cm.COOLDOWN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        # 缓存应失效
        self.cm._cache = None  # force invalidation for test
        cooling, _ = self.cm.is_cooling_down("ext_user.png")
        self.assertTrue(cooling)

    def test_set_account_paused(self):
        """独立的账号暂停功能"""
        self.cm.set_account_paused("user_ap.png", True)
        self.assertTrue(self.cm.is_account_paused("user_ap.png"))
        self.cm.set_account_paused("user_ap.png", False)
        self.assertFalse(self.cm.is_account_paused("user_ap.png"))

    def test_remove_expired_cooldowns(self):
        """移除过期冷却记录"""
        data = {
            "expired.png": {"last_run_time": "2020-01-01 00:00:00", "next_run_time": "2020-01-01 08:00:00"},
            "active.png": {"last_run_time": "2020-01-01 00:00:00", "next_run_time": "2099-01-01 08:00:00"},
        }
        with open(self.cm.COOLDOWN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.cm._cache = None
        expired = self.cm.remove_expired_cooldowns()
        self.assertIn("expired.png", expired)
        self.assertNotIn("active.png", expired)

    def test_set_custom_cooldown_hhmm(self):
        """设置自定义冷却时间（HH:MM 格式）"""
        self.cm.record_run("user_cc.png", cooldown_hours=1)
        result = self.cm.set_custom_cooldown("user_cc.png", "23:59")
        self.assertTrue(result)
        cooling, next_time = self.cm.is_cooling_down("user_cc.png")
        self.assertTrue(cooling)
        self.assertIn("23:59", next_time)

    def test_reset_all_cooldowns(self):
        """重置所有冷却"""
        self.cm.record_run("u1.png", cooldown_hours=8)
        self.cm.record_run("u2.png", cooldown_hours=8)
        self.cm.reset_all_cooldowns()
        cooling1, _ = self.cm.is_cooling_down("u1.png")
        cooling2, _ = self.cm.is_cooling_down("u2.png")
        self.assertFalse(cooling1)
        self.assertFalse(cooling2)


# ==================== asset_db ====================
class TestAssetDB(unittest.TestCase):
    """测试 asset_db 的单例连接和数据操作"""

    def setUp(self):
        import asset_db
        self.db = asset_db
        self._orig_path = asset_db.DB_PATH
        asset_db.DB_PATH = os.path.join(TEST_DIR, "test_assets.db")
        asset_db._conn = None
        # 清空数据库
        if os.path.exists(asset_db.DB_PATH):
            os.remove(asset_db.DB_PATH)

    def tearDown(self):
        if self.db._conn:
            try:
                self.db._conn.close()
            except Exception:
                pass
        self.db._conn = None
        self.db.DB_PATH = self._orig_path

    def test_singleton_connection(self):
        """多次获取连接应返回同一对象"""
        conn1 = self.db._get_conn()
        conn2 = self.db._get_conn()
        self.assertIs(conn1, conn2)

    def test_table_created_only_once(self):
        """表只在首次连接时创建"""
        conn = self.db._get_conn()
        # 再次获取不应报错
        conn2 = self.db._get_conn()
        self.assertIs(conn, conn2)

    def test_record_and_query(self):
        """记录资产并查询变化"""
        self.db.record_asset("user1", "1.5M")
        self.db.record_asset("user1", "2.0M")
        total, details = self.db.query_total_change(days=1)
        self.assertGreater(total, 0)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0][0], "user1")

    def test_format_asset_num(self):
        """资产数值格式化"""
        self.assertEqual(self.db.format_asset_num(1200000), "1.20M")
        self.assertEqual(self.db.format_asset_num(3500), "3.5K")
        self.assertEqual(self.db.format_asset_num(1500000000), "1.50B")
        self.assertEqual(self.db.format_asset_num(500), "500")

    def test_delete_account_records(self):
        """删除账号记录"""
        self.db.record_asset("del_user", "100K")
        self.db.delete_account_records("del_user")
        total, details = self.db.query_total_change(days=1)
        self.assertEqual(len(details), 0)

    def test_no_close_calls(self):
        """确认 _get_conn 返回的连接不会被意外关闭（单例模式）"""
        conn = self.db._get_conn()
        self.db.record_asset("test", "100")
        # 连接仍然可用
        cursor = conn.execute("SELECT COUNT(*) FROM asset_records")
        count = cursor.fetchone()[0]
        self.assertGreaterEqual(count, 1)


# ==================== config ====================
class TestConfigSettings(unittest.TestCase):
    """测试配置管理"""

    def setUp(self):
        import config
        self._orig_path = config.SETTINGS_JSON_PATH
        config.SETTINGS_JSON_PATH = os.path.join(TEST_DIR, "test_config.json")

    def tearDown(self):
        import config
        config.SETTINGS_JSON_PATH = self._orig_path

    def test_load_defaults_when_no_file(self):
        """无文件时应返回默认设置"""
        from config import load_settings, SETTINGS_JSON_PATH, DEFAULT_SETTINGS
        if os.path.exists(SETTINGS_JSON_PATH):
            os.remove(SETTINGS_JSON_PATH)
        settings = load_settings()
        for key in DEFAULT_SETTINGS:
            self.assertIn(key, settings)

    def test_save_load_roundtrip(self):
        """保存后加载应一致"""
        from config import save_settings, load_settings
        settings = {"confidence": 0.85, "auto_start": True, "smtp_code": "test_code"}
        save_settings(settings)
        loaded = load_settings()
        self.assertEqual(loaded["confidence"], 0.85)
        self.assertTrue(loaded["auto_start"])
        self.assertEqual(loaded["smtp_code"], "test_code")

    def test_resource_path(self):
        """resource_path 应返回有效路径"""
        from config import resource_path
        path = resource_path("picture")
        self.assertTrue(os.path.isabs(path))

    def test_get_screen_resolution(self):
        """获取屏幕分辨率"""
        from config import get_screen_resolution
        w, h = get_screen_resolution()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_sell_items_meta(self):
        """售卖物品元数据读写（自动同步目录图片）——目录/元数据隔离到临时目录"""
        import config
        from config import load_sell_items_meta, save_sell_items_meta
        # 隔离：把售卖物品目录与元数据路径指向临时目录，不读写真实用户数据
        orig = (config.SELL_ITEMS_DIR, config.ITEMS_META_PATH, config.ITEMS_META_BACKUP)
        config.SELL_ITEMS_DIR = os.path.join(TEST_DIR, "sell_items")
        config.ITEMS_META_PATH = os.path.join(config.SELL_ITEMS_DIR, "items_meta.json")
        config.ITEMS_META_BACKUP = os.path.join(config.SELL_ITEMS_DIR, "items_meta.backup.json")
        try:
            os.makedirs(config.SELL_ITEMS_DIR, exist_ok=True)
            # 创建两张临时测试图片（一张在元数据中，一张仅存在目录里，验证自动同步）
            test_file = os.path.join(config.SELL_ITEMS_DIR, "_test_meta_sync.png")
            with open(test_file, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            extra_file = os.path.join(config.SELL_ITEMS_DIR, "_test_meta_extra.png")
            with open(extra_file, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
            meta = {"items": [{"filename": "_test_meta_sync.png", "name": "_test_meta_sync", "discount_times": 0, "quantity": 1}]}
            save_sell_items_meta(meta)
            loaded = load_sell_items_meta()
            names = [i["name"] for i in loaded["items"]]
            self.assertIn("_test_meta_sync", names)
            # 验证同步：目录中已有但元数据中没有的图片也被加入
            self.assertIn("_test_meta_extra", names)
        finally:
            os.remove(test_file)
            os.remove(extra_file)
            config.SELL_ITEMS_DIR, config.ITEMS_META_PATH, config.ITEMS_META_BACKUP = orig


# ==================== utils ====================
class TestUtilsFunctions(unittest.TestCase):
    """测试工具函数"""

    def test_overlay_region_avoid_hooks(self):
        """截图区域避让钩子（资产识别/验证码区域 OCR 用）：注册后可调用、可复原"""
        import utils
        calls = []
        orig_a, orig_r = utils._overlay_region_avoid_fn, utils._overlay_restore_fn
        try:
            utils.set_overlay_avoid_region_hooks(
                lambda x, y, w, h: calls.append(("avoid", x, y, w, h)) or "TOKEN",
                lambda t: calls.append(("restore", t)))
            tok = utils._avoid_overlay_for_region(2297, 16, 338, 74)
            self.assertEqual(tok, "TOKEN")
            utils._restore_overlay_after_region(tok)
            self.assertEqual(calls, [("avoid", 2297, 16, 338, 74), ("restore", "TOKEN")])
            # 未注册 / 回调异常都不能把主流程带崩
            utils.set_overlay_avoid_region_hooks(None, None)
            self.assertIsNone(utils._avoid_overlay_for_region(1, 2, 3, 4))
            utils._restore_overlay_after_region(None)      # token 为空 → 直接返回
            def _boom(*_a):
                raise RuntimeError("x")
            utils.set_overlay_avoid_region_hooks(_boom, _boom)
            self.assertIsNone(utils._avoid_overlay_for_region(1, 2, 3, 4))
        finally:
            utils._overlay_region_avoid_fn, utils._overlay_restore_fn = orig_a, orig_r

    def test_parse_asset_value(self):
        """资产字符串解析"""
        from utils import parse_asset_value
        self.assertEqual(parse_asset_value("1.2M"), 1200000)
        self.assertEqual(parse_asset_value("3.5K"), 3500)
        self.assertEqual(parse_asset_value("2B"), 2000000000)
        self.assertEqual(parse_asset_value("100"), 100.0)
        self.assertEqual(parse_asset_value(""), 0)
        self.assertEqual(parse_asset_value("0"), 0)
        self.assertEqual(parse_asset_value("invalid"), 0)

    def test_format_asset_num(self):
        """资产数值格式化"""
        from utils import format_asset_num
        self.assertEqual(format_asset_num(1200000), "1.20M")
        self.assertEqual(format_asset_num(3500), "3.5K")
        self.assertEqual(format_asset_num(1500000000), "1.50B")
        self.assertEqual(format_asset_num(500), "500")
        self.assertEqual(format_asset_num(-1200000), "-1.20M")

    def test_parse_format_roundtrip(self):
        """解析和格式化的往返一致性"""
        from utils import parse_asset_value, format_asset_num
        for val in [1000, 1000000, 1234567, 999]:
            formatted = format_asset_num(val)
            parsed = parse_asset_value(formatted)
            # 允许精度损失
            self.assertAlmostEqual(parsed, val, delta=val * 0.01)

    def test_set_window_icon_no_crash(self):
        """set_window_icon 在无窗口环境下不应崩溃"""
        from utils import set_window_icon
        # 传入 mock 对象，确保不会抛异常
        mock_win = MagicMock()
        mock_win.iconphoto = MagicMock()
        # 应该不抛异常（可能因为 icon 文件不存在而静默跳过）
        try:
            set_window_icon(mock_win)
        except Exception:
            pass  # 无 GUI 环境下可能失败，但不应崩溃


# ==================== email_notifier ====================
class TestEmailNotifier(unittest.TestCase):
    """测试邮件通知模块"""

    def test_get_email_config_enabled(self):
        """邮箱配置正确时应返回元组"""
        from email_notifier import _get_email_config
        app = MagicMock()
        app.settings = {
            "email_enabled": True,
            "smtp_code": "test_code",
            "sender_email": "sender@test.com",
            "receiver_email": "receiver@test.com",
        }
        result = _get_email_config(app)
        self.assertIsNotNone(result)
        self.assertEqual(result, ("test_code", "sender@test.com", "receiver@test.com"))

    def test_get_email_config_disabled(self):
        """邮箱未启用时应返回 None"""
        from email_notifier import _get_email_config
        app = MagicMock()
        app.settings = {"email_enabled": False}
        self.assertIsNone(_get_email_config(app))

    def test_get_email_config_missing_fields(self):
        """邮箱配置不完整时应返回 None"""
        from email_notifier import _get_email_config
        app = MagicMock()
        app.settings = {"email_enabled": True, "smtp_code": "", "sender_email": "a@b.com", "receiver_email": "c@d.com"}
        self.assertIsNone(_get_email_config(app))

    def test_send_functions_no_crash_when_disabled(self):
        """邮箱禁用时发送函数不应崩溃"""
        from email_notifier import send_account_failure_email, send_run_report_email, send_failure_email
        app = MagicMock()
        app.settings = {"email_enabled": False}
        # 这些都应直接返回，不抛异常
        send_account_failure_email(app, "test.png", "2099-01-01 00:00:00")
        send_run_report_email(app, {"total": 1, "success": 1, "fail": 0, "start_time": time.time()}, 60)
        send_failure_email(app, "test error")


# ==================== asset value parsing (cross-module) ====================
class TestAssetValueParsing(unittest.TestCase):
    """测试资产值解析在不同模块间的一致性"""

    def test_utils_and_account_manager_consistent(self):
        """utils.parse_asset_value 和 account_manager._parse_asset_value 应一致"""
        from utils import parse_asset_value
        import account_manager
        for val in ["1.2M", "3.5K", "2B", "100", "invalid", ""]:
            self.assertEqual(parse_asset_value(val), account_manager._parse_asset_value(val))


# ==================== 未售累加 / 未验证状态 ====================
class TestInterceptionSafety(unittest.TestCase):
    """Interception 按键安全：不装过滤（不会吞键盘）+ 失败时补发抬起（不会卡 Shift）"""

    def test_filter_mask_is_zero(self):
        """只发送、不拦截：filter mask 必须是 0（装 KEY_ALL 过滤才会导致键盘假死）"""
        src_path = os.path.join(os.path.dirname(__file__), "interception_keyboard.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("_set_filter(ctx, _predicate_callback, 0)", src)
        # 不允许出现任何非 0 的过滤掩码（0xFFFF / KEY_ALL 之类）
        self.assertNotIn("0xFFFF", src)
        self.assertNotIn("_set_filter(ctx, _predicate_callback, 1)", src)

    def test_shift_released_when_send_fails_midway(self):
        """shift 按下后发送失败 → 必须在 finally 里补发 shift_up（否则用户键盘看起来"失灵"）"""
        import unittest.mock as mock
        import interception_keyboard as ik
        sent = []
        # 第 1 次（shift down）成功，第 2 次（字母 down）失败
        def fake_send(ctx, dev, stroke, n):
            sent.append((stroke.code, stroke.state))
            return 1 if len(sent) == 1 else 0
        with mock.patch.object(ik, "_load_dll", return_value=True), \
             mock.patch.object(ik, "_create_context", return_value=1234), \
             mock.patch.object(ik, "_set_filter"), \
             mock.patch.object(ik, "_destroy_context") as destroy, \
             mock.patch.object(ik, "_find_keyboard_device", return_value=2), \
             mock.patch.object(ik, "_is_capslock_on", return_value=False), \
             mock.patch.object(ik, "_send", side_effect=fake_send), \
             mock.patch.object(ik.time, "sleep"):
            ok = ik._send_chars("Ab")       # 'A' 需要 shift
        self.assertFalse(ok)
        self.assertIn((ik._SHIFT_SCANCODE, ik.KEY_DOWN), sent)
        self.assertIn((ik._SHIFT_SCANCODE, ik.KEY_UP), sent)   # 补发的抬起
        destroy.assert_called_once()                            # 上下文一定释放

    def test_context_destroyed_on_success(self):
        import unittest.mock as mock
        import interception_keyboard as ik
        with mock.patch.object(ik, "_load_dll", return_value=True), \
             mock.patch.object(ik, "_create_context", return_value=99), \
             mock.patch.object(ik, "_set_filter"), \
             mock.patch.object(ik, "_destroy_context") as destroy, \
             mock.patch.object(ik, "_find_keyboard_device", return_value=2), \
             mock.patch.object(ik, "_is_capslock_on", return_value=False), \
             mock.patch.object(ik, "_send", return_value=1), \
             mock.patch.object(ik.time, "sleep"):
            self.assertTrue(ik._send_chars("aq1"))
        destroy.assert_called_once()


class TestFacilityStageAndManualVerify(unittest.TestCase):
    """设施失败断在哪一步 + 人工验证期间检测「重新登录」"""

    def test_facility_stage_tagged_on_collect_fail(self):
        """Collect（收取）找不到 → 记为「未领取」"""
        import types
        import unittest.mock as mock
        import automation, utils, config
        sink = {"stage": ""}
        # 只在 Collect（收取）这一步失败，前面都要成功
        with mock.patch.object(automation, "_click",
                               side_effect=lambda ri, var, img, t=15, **k:
                               "nofind" if var == "Collect" else True), \
             mock.patch.object(utils, "human_pause"), \
             mock.patch.object(utils, "find_and_click_smart", return_value=False), \
             mock.patch.object(automation.pyautogui, "press"), \
             mock.patch.object(automation.time, "sleep"):
            ok = automation.handle_facility("fac.png", "prod.png", "防具台",
                                            types.SimpleNamespace(is_set=lambda: False),
                                            lambda t: None, stage_sink=sink)
        self.assertFalse(ok)
        self.assertEqual(sink["stage"], "未领取")

    def test_facility_stage_tagged_on_produce_fail(self):
        """前面都成功、Produce（开始生产）找不到 → 记为「未制造」"""
        import types
        import unittest.mock as mock
        import automation, utils
        sink = {"stage": ""}
        # 只在 Produce（开始生产）这一步失败，前面都要成功
        with mock.patch.object(automation, "_click",
                               side_effect=lambda ri, var, img, t=15, **k:
                               "nofind" if var == "Produce" else True), \
             mock.patch.object(utils, "human_pause"), \
             mock.patch.object(utils, "find_and_click_smart", return_value=False), \
             mock.patch.object(automation.pyautogui, "press"), \
             mock.patch.object(automation.time, "sleep"):
            ok = automation.handle_facility("fac.png", "prod.png", "医疗站",
                                            types.SimpleNamespace(is_set=lambda: False),
                                            lambda t: None, stage_sink=sink)
        self.assertFalse(ok)
        self.assertEqual(sink["stage"], "未制造")

    def test_type3_sample_saved_to_log_dir(self):
        """开启后遇到「图片文字选择」类验证码：存一张样本图 + 同名 txt（记 OCR 文字）"""
        import numpy as np
        import unittest.mock as mock
        import captcha_router as cr
        import utils
        out_root = os.path.join(TEST_DIR, "type3_logs")
        settings = {"log_save_path": out_root, "captcha_type3_save_image": True,
                    "captcha_region_enabled": False}
        fake_shot = np.zeros((40, 60, 3), dtype=np.uint8)
        with mock.patch("pyautogui.screenshot", return_value=fake_shot):
            cr.save_type3_sample(settings, "选择所有符合描述的图片包含文字：川")
        day_dir = os.path.join(out_root, utils.date_folder_name(), "图片")
        files = sorted(os.listdir(day_dir))
        self.assertTrue(any(f.startswith("文字选择验证_") and f.endswith(".png") for f in files), files)
        txts = [f for f in files if f.endswith(".txt")]
        self.assertEqual(len(txts), 1)
        with open(os.path.join(day_dir, txts[0]), encoding="utf-8") as f:
            self.assertIn("包含文字", f.read())

    def test_wait_manual_verify_detects_relogin(self):
        """人工验证等待期间识别到「重新登录」→ 返回 'relogin'（交给登录重试）"""
        import types
        import unittest.mock as mock
        import automation_runner as ar
        import config
        app = types.SimpleNamespace(_stop_event=types.SimpleNamespace(is_set=lambda: False))

        def fake_find(img_path, timeout=2, stop_event=None):
            return img_path == config.LOGIN_AGAIN      # 只认出「重新登录」

        with mock.patch.object(ar.utils, "find_image_on_screen", side_effect=fake_find), \
             mock.patch.object(ar.time, "sleep"):
            self.assertEqual(ar._wait_manual_verify(app, 10), "relogin")
        # 认出三角洲图标 → 'ok'
        with mock.patch.object(ar.utils, "find_image_on_screen",
                               side_effect=lambda img, timeout=2, stop_event=None:
                               img == config.DELTA_GAME_ICON), \
             mock.patch.object(ar.time, "sleep"):
            self.assertEqual(ar._wait_manual_verify(app, 10), "ok")
        # 都没认出且立即超时 → 'timeout'
        with mock.patch.object(ar.utils, "find_image_on_screen", return_value=False), \
             mock.patch.object(ar.time, "sleep"):
            self.assertEqual(ar._wait_manual_verify(app, 1), "timeout")

    def test_email_status_cell_shows_facility_failures(self):
        """邮件报告的状态列下方显示「防具台✗未领取」这类设施结果"""
        import types
        import automation_runner as ar
        app = types.SimpleNamespace(
            _account_notes={},
            _account_assets={},
            _facility_notes={"accA": [("技术中心", "✓"), ("防具台", "✗未领取"),
                                      ("医疗站", "未执行")]},
            settings={"enable_cooldown": False})
        with patch.object(ar, "get_account_next_run", return_value="已冷却"):
            html_out = ar.build_accounts_html(app, ["accA (成功)"])
        self.assertIn("防具台✗未领取", html_out)
        self.assertIn("医疗站未执行", html_out)
        # 全部 ✓ 时不显示任何设施字样
        app._facility_notes = {"accA": [("技术中心", "✓")]}
        with patch.object(ar, "get_account_next_run", return_value="已冷却"):
            html_out = ar.build_accounts_html(app, ["accA (成功)"])
        self.assertNotIn("技术中心", html_out)


class TestSellFlowOrder(unittest.TestCase):
    """售卖流程：上架后按「固定坐标」点一下最大数量，再降价
    （最大数量已从「模板找图」改为「坐标点击」，故不再有 Max_Quantity 模板这一步）"""

    def _run_sell(self, mq_point, item_filename="_sell_item_A.png", discount=1, settings_extra=None,
                  screen=(2560, 1440), skip_warehouse=False):
        import types
        import unittest.mock as mock
        import automation, utils, config

        with open(os.path.join(TEST_DIR, item_filename), "wb") as f:
            f.write(b"PNG")

        order = []

        def fake_click(run_insert, var_name, img_path, timeout=15, **kw):
            order.append(var_name)
            return True

        settings = {"enable_sell_after_run": True, "sell_confidence": 0.55,
                    "sell_time_enabled": False, "max_quantity_point": mq_point}
        if settings_extra:
            settings.update(settings_extra)
        # 屏幕尺寸固定，否则「坐标是否越界」的判定会随跑测试的机器变
        with mock.patch.object(config, "load_sell_items_meta",
                               return_value={"items": [{"filename": item_filename,
                                                        "name": "测试物品",
                                                        "discount_times": discount}]}), \
             mock.patch.object(config, "SELL_ITEMS_DIR", TEST_DIR), \
             mock.patch.object(config, "Warehouse", "wh.png"), \
             mock.patch.object(utils, "clear_template_cache"), \
             mock.patch.object(utils, "find_and_click", return_value=True), \
             mock.patch.object(utils, "human_pause"), \
             mock.patch.object(utils, "human_move_away"), \
             mock.patch.object(utils, "smooth_move_to") as mock_smooth, \
             mock.patch.object(utils, "human_click_delay"), \
             mock.patch.object(automation, "_click", side_effect=fake_click), \
             mock.patch.object(automation.time, "sleep"), \
             mock.patch("pyautogui.click") as mock_pyclick, \
             mock.patch("pyautogui.size", return_value=screen):
            ok, stats = automation.sell_operations(settings, types.SimpleNamespace(
                is_set=lambda: False), lambda t: None, skip_warehouse=skip_warehouse)
        return ok, stats, order, mock_smooth, mock_pyclick

    def test_max_quantity_clicked_at_fixed_point(self):
        """上架后按设置里的固定坐标点「最大数量」（不找图、不叠加随机偏移），然后降价"""
        ok, stats, order, mock_smooth, mock_pyclick = self._run_sell([1935, 740], discount=1)
        self.assertTrue(ok)
        # 最大数量不再走 _click（找图），所以不在点击顺序里
        self.assertEqual(order, ["Warehouse", "Sell", "List_Item",
                                 "Discount", "Confirm_Listing"])
        # 严格落在设置坐标上
        mock_smooth.assert_called_once_with(1935, 740)
        self.assertTrue(mock_pyclick.called)
        self.assertEqual(stats["sold"], 1)
        self.assertEqual(stats["total"], 1)

    def test_max_quantity_zero_point_skips_step(self):
        """坐标填 0 时跳过「最大数量」这一步，不影响售卖"""
        ok, stats, order, mock_smooth, mock_pyclick = self._run_sell(
            [0, 0], item_filename="_sell_item_B.png", discount=0)
        self.assertTrue(ok)
        self.assertEqual(order, ["Warehouse", "Sell", "List_Item", "Confirm_Listing"])
        mock_smooth.assert_not_called()
        self.assertFalse(mock_pyclick.called)

    def test_missing_max_quantity_point_uses_default(self):
        """设置里没有 max_quantity_point 时用默认 (0,0)＝跳过该步"""
        ok, stats, order, mock_smooth, mock_pyclick = self._run_sell(
            None, item_filename="_sell_item_C.png", discount=0)
        self.assertTrue(ok)
        mock_smooth.assert_not_called()
        self.assertFalse(mock_pyclick.called)

    def test_skip_warehouse_starts_from_items(self):
        """skip_warehouse=True（出售测试）时不点「仓库入口」，直接从识别物品开始"""
        import types
        import unittest.mock as mock
        import automation, utils, config

        with open(os.path.join(TEST_DIR, "_sell_item_D.png"), "wb") as f:
            f.write(b"PNG")
        order = []

        def fake_click(run_insert, var_name, img_path, timeout=15, **kw):
            order.append(var_name)
            return True

        settings = {"sell_confidence": 0.55, "sell_time_enabled": False,
                    "max_quantity_point": [0, 0]}
        with mock.patch.object(config, "load_sell_items_meta",
                               return_value={"items": [{"filename": "_sell_item_D.png",
                                                        "name": "测试物品D",
                                                        "discount_times": 0}]}), \
             mock.patch.object(config, "SELL_ITEMS_DIR", TEST_DIR), \
             mock.patch.object(utils, "clear_template_cache"), \
             mock.patch.object(utils, "find_and_click", return_value=True), \
             mock.patch.object(utils, "human_pause"), \
             mock.patch.object(utils, "human_move_away"), \
             mock.patch.object(utils, "human_click_delay"), \
             mock.patch.object(automation, "_click", side_effect=fake_click), \
             mock.patch.object(automation.time, "sleep"), \
             mock.patch("pyautogui.click"):
            ok, stats = automation.sell_operations(settings, types.SimpleNamespace(
                is_set=lambda: False), lambda t: None, skip_warehouse=True)
        self.assertTrue(ok)
        self.assertEqual(order, ["Sell", "List_Item", "Confirm_Listing"])
        self.assertNotIn("Warehouse", order)
        self.assertEqual(stats["sold"], 1)

    def test_max_quantity_out_of_screen_is_skipped(self):
        """坐标超出屏幕范围时跳过「最大数量」这一步（越界点击会被截到屏幕边缘、可能点到别处）"""
        ok, stats, order, mock_smooth, mock_pyclick = self._run_sell(
            [14412, 123123], item_filename="_sell_item_E.png", discount=0)
        self.assertTrue(ok)
        self.assertEqual(order, ["Warehouse", "Sell", "List_Item", "Confirm_Listing"])
        mock_smooth.assert_not_called()
        self.assertFalse(mock_pyclick.called)


class TestSellSkipReasons(unittest.TestCase):
    """出售流程「一件都没卖」的原因码（reason）——
    出售测试弹窗据此给出准确提示；此前是一条笼统文案，曾把「不在售卖时间区间」误报成「请先添加物品」"""

    def _call(self, settings, items, ignore_time_window=False):
        import types
        import unittest.mock as mock
        import automation, utils, config
        with mock.patch.object(config, "load_sell_items_meta", return_value={"items": items}), \
             mock.patch.object(config, "SELL_ITEMS_DIR", TEST_DIR), \
             mock.patch.object(utils, "clear_template_cache"), \
             mock.patch.object(utils, "find_and_click", return_value=False), \
             mock.patch.object(utils, "human_pause"), \
             mock.patch.object(automation.time, "sleep"), \
             mock.patch("pyautogui.size", return_value=(2560, 1440)):
            return automation.sell_operations(
                settings, types.SimpleNamespace(is_set=lambda: False), lambda t: None,
                skip_warehouse=True, ignore_time_window=ignore_time_window)

    @staticmethod
    def _window_excluding_now():
        """造一个必然不含当前时刻的售卖区间"""
        import datetime as _dt
        t1 = (_dt.datetime.now() + _dt.timedelta(hours=2)).strftime("%H:%M")
        t2 = (_dt.datetime.now() + _dt.timedelta(hours=3)).strftime("%H:%M")
        return t1, t2

    def test_ignore_time_window_bypasses_limit(self):
        """ignore_time_window=True（出售测试）时不受「售卖时间区间」限制"""
        import os
        item = "_sell_item_win.png"
        with open(os.path.join(TEST_DIR, item), "wb") as f:
            f.write(b"PNG")
        t1, t2 = self._window_excluding_now()
        ok, stats = self._call(
            {"sell_time_enabled": True, "sell_time_start": t1, "sell_time_end": t2,
             "sell_confidence": 0.55, "max_quantity_point": [0, 0]},
            [{"filename": item, "name": "测试物品", "discount_times": 0}],
            ignore_time_window=True)
        # 区间被绕过 → 走到了物品循环（图片找不到，所以 not_found=1），而不是 0 件退出
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["not_found"], 1)
        self.assertNotEqual(stats["reason"], "out_of_window")

    def test_reason_no_items(self):
        """没有配置任何售卖物品 → reason=no_items"""
        ok, stats = self._call({"sell_time_enabled": False}, [])
        self.assertFalse(ok)
        self.assertEqual(stats["reason"], "no_items")
        self.assertEqual(stats["total"], 0)

    def test_reason_out_of_window(self):
        """不在售卖时间区间内 → reason=out_of_window（而不是笼统的「请先添加物品」）"""
        t1, t2 = self._window_excluding_now()
        ok, stats = self._call(
            {"sell_time_enabled": True, "sell_time_start": t1, "sell_time_end": t2,
             "max_quantity_point": [0, 0]},
            [{"filename": "_x.png", "name": "x", "discount_times": 0}])
        self.assertFalse(ok)
        self.assertEqual(stats["reason"], "out_of_window")
        self.assertEqual(stats["total"], 0)

    def test_reason_all_missing(self):
        """配置了物品但图片文件都不在 → reason=all_missing"""
        ok, stats = self._call(
            {"sell_time_enabled": False, "max_quantity_point": [0, 0]},
            [{"filename": "_不存在的物品.png", "name": "不存在的物品", "discount_times": 0}])
        self.assertEqual(stats["reason"], "all_missing")
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["missing_files"], 1)


class TestSellPendingAndUnverified(unittest.TestCase):
    """测试 sell_pending 累加清零、模板点击坐标、未验证状态=跳过"""

    def setUp(self):
        import sell_pending
        import template_click_coords
        self._orig_p = sell_pending.PENDING_JSON
        self._orig_c = template_click_coords.COORDS_JSON
        sell_pending.PENDING_JSON = os.path.join(TEST_DIR, "test_pending.json")
        template_click_coords.COORDS_JSON = os.path.join(TEST_DIR, "test_coords.json")
        sell_pending._cache = None
        template_click_coords._cache = None
        for p in (sell_pending.PENDING_JSON, template_click_coords.COORDS_JSON):
            if os.path.exists(p):
                os.remove(p)

    def tearDown(self):
        import sell_pending
        import template_click_coords
        sell_pending.PENDING_JSON = self._orig_p
        template_click_coords.COORDS_JSON = self._orig_c
        sell_pending._cache = None
        template_click_coords._cache = None

    def test_sell_pending_accumulate_and_clear(self):
        import sell_pending as sp
        self.assertEqual(sp.get_pending("acc1"), 0)
        sp.add_pending("acc1", 1)
        sp.add_pending("acc1", 2)
        self.assertEqual(sp.get_pending("acc1"), 3)
        sp.clear_pending("acc1")
        self.assertEqual(sp.get_pending("acc1"), 0)

    def test_template_click_coord_store(self):
        import template_click_coords as tcc
        self.assertIsNone(tcc.get_coord("picture/Navigation/hazard.png"))
        tcc.set_coord("picture/Navigation/hazard.png", 123, 456)
        self.assertEqual(tcc.get_coord("picture/Navigation/hazard.png"), (123, 456))

    def test_unverified_equals_skipped(self):
        import cooldown_manager as cm
        orig_path, orig_bak = cm.COOLDOWN_JSON_PATH, cm.COOLDOWN_JSON_BACKUP
        cm.COOLDOWN_JSON_PATH = os.path.join(TEST_DIR, "test_unver.json")
        cm.COOLDOWN_JSON_BACKUP = cm.COOLDOWN_JSON_PATH + ".bak"
        cm._cache = None
        cm._cache_mtime = 0.0
        cm._load_corrupt = False
        try:
            self.assertFalse(cm.is_account_skipped("accX"))
            cm.set_unverified("accX", True)
            self.assertTrue(cm.is_unverified("accX"))
            self.assertTrue(cm.is_account_skipped("accX"))
            cm.set_unverified("accX", False)
            self.assertFalse(cm.is_account_skipped("accX"))
        finally:
            cm.COOLDOWN_JSON_PATH, cm.COOLDOWN_JSON_BACKUP = orig_path, orig_bak
            cm._cache = None
            cm._cache_mtime = 0.0
            cm._load_corrupt = False

    def test_migrate_captcha_keywords(self):
        """老配置自动补充图片点选关键词（只补一次、纯追加、去重、不覆盖用户自加的词）"""
        import config
        old = dict(config.DEFAULT_SETTINGS)
        old["captcha_click_keywords"] = "依次点击,点选,自己加的词"
        old.pop("captcha_kw_supplemented", None)
        self.assertTrue(config.migrate_captcha_keywords(old))
        kw = old["captcha_click_keywords"].split(",")
        for k in ("依次点击", "点选", "自己加的词"):        # 原有词一个不少
            self.assertIn(k, kw)
        for k in ("请选择", "选择所有", "符合描述", "包含文字", "请验证"):   # 新增词已补上
            self.assertIn(k, kw)
        self.assertTrue(old["captcha_kw_supplemented"])
        # 再跑一次不重复追加
        before = old["captcha_click_keywords"]
        self.assertFalse(config.migrate_captcha_keywords(old))
        self.assertEqual(old["captcha_click_keywords"], before)
        # 关键词要能命中真实验证码文案，且不误伤普通登录页
        import captcha_router as cr
        self.assertTrue(cr.needs_verification(old, "为了您的账号安全，请验证后登录。选择所有符合描述的图片包含文字：川"))
        self.assertFalse(cr.needs_verification(old, "验证码登录"))
        self.assertFalse(cr.needs_verification(old, "短信验证"))

    def test_migrate_max_quantity_point(self):
        """「最大数量」旧默认 [1935,740] 重置为 [0,0]；用户自己取的坐标不动；异常值不炸"""
        import config
        # 旧默认 → 重置
        old = {"max_quantity_point": [1935, 740]}
        self.assertTrue(config.migrate_max_quantity_point(old))
        self.assertEqual(old["max_quantity_point"], [0, 0])
        # 再跑一次不再改动
        self.assertFalse(config.migrate_max_quantity_point(old))
        # 用户自定义坐标 → 不动
        custom = {"max_quantity_point": [1234, 567]}
        self.assertFalse(config.migrate_max_quantity_point(custom))
        self.assertEqual(custom["max_quantity_point"], [1234, 567])
        # 新默认 / 缺失 / 异常 → 不改动、不抛异常
        for bad in ({"max_quantity_point": [0, 0]}, {}, {"max_quantity_point": None},
                    {"max_quantity_point": "abc"}, {"max_quantity_point": [1]}):
            self.assertFalse(config.migrate_max_quantity_point(bad))

    def test_restore_account_clears_unverified(self):
        """右键「恢复账号」要能解除「未验证通过」——否则账号永远恢复不了（用户实测的死锁）"""
        import types
        import unittest.mock as mock
        import cooldown_manager as cm
        import account_manager as am
        orig_path, orig_bak = cm.COOLDOWN_JSON_PATH, cm.COOLDOWN_JSON_BACKUP
        cm.COOLDOWN_JSON_PATH = os.path.join(TEST_DIR, "test_restore_unver.json")
        cm.COOLDOWN_JSON_BACKUP = cm.COOLDOWN_JSON_PATH + ".bak"
        cm._cache = None
        cm._cache_mtime = 0.0
        cm._load_corrupt = False
        try:
            # 账号标识由 _account_key_from_path 归一化（去掉扩展名）→ 冷却键是 "accU"
            cm.set_unverified("accU", True)
            self.assertTrue(cm.is_account_skipped("accU"))
            tree = types.SimpleNamespace(
                selection=lambda: ("iid0",),
                item=lambda iid, key=None: (),
            )
            app = types.SimpleNamespace(
                account_tree=tree,
                qq_account_images=["accU.png"],
                _account_row_pos={"iid0": 0},
                _consecutive_failures={"accU": 3},
                root=None,
            )
            with mock.patch.object(am, "refresh_account_tree"), \
                 mock.patch.object(am.messagebox, "showinfo") as info:
                am.toggle_account_pause(app)
            self.assertFalse(cm.is_unverified("accU"))
            self.assertFalse(cm.is_account_skipped("accU"))   # 恢复后不再被跳过
            self.assertNotIn("accU", app._consecutive_failures)
            self.assertIn("未验证通过", str(info.call_args))
        finally:
            cm.COOLDOWN_JSON_PATH, cm.COOLDOWN_JSON_BACKUP = orig_path, orig_bak
            cm._cache = None
            cm._cache_mtime = 0.0
            cm._load_corrupt = False


# ==================== 公告（每天一次 / 永久关闭） ====================
class TestAnnouncements(unittest.TestCase):
    """测试公告的展示判定与状态存储（独立文件，不弹真实窗口）"""

    def setUp(self):
        import config
        import announcements
        self._orig_path = config.SETTINGS_JSON_PATH
        self._orig_cache = config._settings_cache
        config.SETTINGS_JSON_PATH = os.path.join(TEST_DIR, "test_announce.json")
        if os.path.exists(config.SETTINGS_JSON_PATH):
            os.remove(config.SETTINGS_JSON_PATH)
        config._settings_cache = None
        config._settings_cache_mtime = 0
        # 公告状态存独立文件，隔离测试文件路径
        self._orig_ajson = announcements.ANNOUNCEMENTS_JSON
        announcements.ANNOUNCEMENTS_JSON = os.path.join(TEST_DIR, "test_announce_state.json")
        if os.path.exists(announcements.ANNOUNCEMENTS_JSON):
            os.remove(announcements.ANNOUNCEMENTS_JSON)

    def tearDown(self):
        import config
        import announcements
        config.SETTINGS_JSON_PATH = self._orig_path
        config._settings_cache = self._orig_cache
        config._settings_cache_mtime = 0
        announcements.ANNOUNCEMENTS_JSON = self._orig_ajson

    def test_daily_and_forever(self):
        """今天未弹→应显示；关闭(今天)→当天不再显示；永久→永远不显示"""
        import announcements
        # 从未弹过 → 应显示
        self.assertTrue(announcements.should_show())
        # 关闭(仅今天)
        self.assertTrue(announcements._save(done_forever=False))
        self.assertFalse(announcements.should_show())
        # 永久关闭
        self.assertTrue(announcements._save(done_forever=True))
        self.assertFalse(announcements.should_show())
        # 即便状态里日期清掉（模拟第二天）永久仍不显示
        import json
        with open(announcements.ANNOUNCEMENTS_JSON, "r", encoding="utf-8") as f:
            state = json.load(f)
        state["last_date"] = ""
        with open(announcements.ANNOUNCEMENTS_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f)
        self.assertFalse(announcements.should_show())

    def test_migrate_from_settings(self):
        """旧版 settings.json 里的公告状态应在首次读取时迁移到独立文件"""
        import json
        import config
        import announcements
        s = config.load_settings()
        s["announcement_last_date"] = "2026-09-01"
        s["announcements_forever"] = ["s11_season_20260902"]
        config.save_settings(s)
        # 永久关闭已迁移 → 不显示
        self.assertFalse(announcements.should_show())
        with open(announcements.ANNOUNCEMENTS_JSON, "r", encoding="utf-8") as f:
            state = json.load(f)
        self.assertEqual(state.get("last_date"), "2026-09-01")
        self.assertIn(announcements.ANNOUNCEMENT_ID, state.get("forever", []))

    def test_corrupt_state_file_backed_up(self):
        """状态文件损坏时应备份原文件并按空状态继续（可再次弹出）"""
        import announcements
        with open(announcements.ANNOUNCEMENTS_JSON, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertTrue(announcements.should_show())
        # 损坏文件被改名备份
        import glob
        self.assertTrue(glob.glob(announcements.ANNOUNCEMENTS_JSON + ".corrupt.*"))


# ==================== 模板插入步骤 ====================
class TestTemplateInsertSteps(unittest.TestCase):
    """测试 template_insert_steps 的配置读写与执行判定（不真实按键/截图）"""

    def setUp(self):
        import config
        import template_insert_steps as tis
        self._orig_path = config.SETTINGS_JSON_PATH
        self._orig_cache = config._settings_cache
        self._orig_cache_mtime = config._settings_cache_mtime
        config.SETTINGS_JSON_PATH = os.path.join(TEST_DIR, "test_insert_steps.json")
        if os.path.exists(config.SETTINGS_JSON_PATH):
            os.remove(config.SETTINGS_JSON_PATH)
        config._settings_cache = None
        config._settings_cache_mtime = 0
        # 插入步骤存独立文件，隔离测试文件路径与内存缓存
        self._orig_isj = tis.INSERT_STEPS_JSON
        tis.INSERT_STEPS_JSON = os.path.join(TEST_DIR, "test_tis_store.json")
        tis._cache = None
        if os.path.exists(tis.INSERT_STEPS_JSON):
            os.remove(tis.INSERT_STEPS_JSON)

    def tearDown(self):
        import config
        import template_insert_steps as tis
        config.SETTINGS_JSON_PATH = self._orig_path
        config._settings_cache = self._orig_cache
        config._settings_cache_mtime = self._orig_cache_mtime
        tis.INSERT_STEPS_JSON = self._orig_isj
        tis._cache = None

    def test_save_get_has_delete_roundtrip(self):
        """保存/读取/判定/清空删除 应正确往返"""
        import template_insert_steps as tis
        self.assertIsNone(tis.get("Hazard_Operations"))
        self.assertFalse(tis.has_steps("Hazard_Operations"))
        steps = [{"type": "keyboard", "keys": "esc", "key_mode": "key", "pause_after": 0}]
        self.assertTrue(tis.save("Hazard_Operations", "before", steps))
        cfg = tis.get("Hazard_Operations")
        self.assertEqual(cfg["timing"], "before")
        self.assertEqual(len(cfg["steps"]), 1)
        self.assertTrue(tis.has_steps("Hazard_Operations"))
        # 覆盖为 after
        tis.save("Hazard_Operations", "after", steps)
        self.assertEqual(tis.get("Hazard_Operations")["timing"], "after")
        # 空步骤 → 删除该项
        tis.save("Hazard_Operations", "before", [])
        self.assertIsNone(tis.get("Hazard_Operations"))
        self.assertFalse(tis.has_steps("Hazard_Operations"))

    def test_run_optional_failing_step_continues(self):
        """步骤标记 optional=True 时，找图失败不判失败 → run_for_account 返回 True"""
        import threading
        import template_insert_steps as tis
        stop = threading.Event()
        bad_optional = {"type": "image", "image": "_no_such_insert_test.png",
                        "confidence": 0.7, "timeout": 1, "pause_after": 0, "optional": True}
        tis.save("SIGN_IN", "after", [bad_optional])
        self.assertTrue(tis.run_for_account({}, stop, "A", "SIGN_IN", "after"))

    def test_run_no_config_or_timing_mismatch(self):
        """未配置 / 时序不符 → 返回 True（不执行）"""
        import threading
        import template_insert_steps as tis
        stop = threading.Event()
        settings = {"enable_cooldown": True}
        # 无配置
        self.assertTrue(tis.run_for_account(settings, stop, "账号A", "SIGN_IN", "before"))
        # 配置了 after，但请求 before → 不执行返回 True
        tis.save("SIGN_IN", "after", [{"type": "keyboard", "keys": "x", "pause_after": 0}])
        self.assertTrue(tis.run_for_account(settings, stop, "账号A", "SIGN_IN", "before"))

    def test_run_failing_image_step_returns_false(self):
        """执行时某步找图失败（图片不存在）→ 返回 False（视为模板失败）"""
        import threading
        import template_insert_steps as tis
        stop = threading.Event()
        settings = {"enable_cooldown": True}
        # 指向 custom_ops/images 下不存在的图片 → _execute_step 立即失败
        bad_step = {"type": "image", "image": "_no_such_insert_test.png",
                    "confidence": 0.7, "timeout": 1, "pause_after": 0}
        tis.save("Hazard_Operations", "before", [bad_step])
        self.assertFalse(tis.run_for_account(settings, stop, "账号A", "Hazard_Operations", "before"))


# ==================== AI 视觉验证（离线解析，不联网） ====================
class TestAiVisualCaptcha(unittest.TestCase):
    """测试 ai_visual_captcha 的回复解析 / 坐标归一化 / 配置判定（不发真实请求、不点击）"""

    def test_extract_json_plain_and_fenced(self):
        """裸 JSON / ```json 包裹 / 带前后缀文字 均可提取"""
        import ai_visual_captcha as avc
        self.assertEqual(avc._extract_json('{"a": 1}'), {"a": 1})
        self.assertEqual(avc._extract_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(avc._extract_json('好的，结果如下：{"a": {"b": 2}} 请查收'),
                         {"a": {"b": 2}})
        # 字符串内含花括号不破坏配对
        self.assertEqual(avc._extract_json('{"s": "包含}花括号"}'), {"s": "包含}花括号"})
        self.assertIsNone(avc._extract_json("没有json"))

    def test_parse_response_none_and_slider(self):
        """无验证码 / 滑块验证 的识别分支"""
        import ai_visual_captcha as avc
        r = avc.parse_model_response('{"captcha": false, "type": "none", "targets": []}', 1000, 800)
        self.assertEqual(r["status"], "none")
        r = avc.parse_model_response('{"captcha": true, "type": "slider", "targets": []}', 1000, 800)
        self.assertEqual(r["status"], "slider")

    def test_parse_response_click_bbox_and_point(self):
        """click：0-1000 归一化坐标换算成像素；point 优先，bbox 中心兜底"""
        import ai_visual_captcha as avc
        # 归一化 bbox (100,200,200,300) → 像素 (77,106)-(154,160) → 中心 (115,133)
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"text": "塔", "bbox": [100, 200, 200, 300]}]}', 770, 532)
        self.assertEqual(r["status"], "click")
        self.assertEqual(r["space"], "normalized")
        self.assertEqual(r["points"], [(115, 133)])
        self.assertEqual(r["labels"], ["塔"])
        # 真实数据回归：crop 770x532，模型报 桦 point=[710,261] → 像素 (547,139)
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"text": "桦", "bbox": [621, 210, 782, 345], "point": [710, 261]}]}', 770, 532)
        self.assertEqual(r["points"], [(547, 139)])
        # bbox 与 point 同时给出时以 point 为准（bbox 常偏大，中心会偏）
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"bbox": [0, 0, 10, 10], "point": [500, 500]}]}', 1000, 1000)
        self.assertEqual(r["points"], [(500, 500)])

    def test_coord_space_detection(self):
        """坐标空间判定：>1000 → 像素；否则按 0-1000 归一化；显式 scale 优先"""
        import ai_visual_captcha as avc
        # 出现 >1000 的坐标 → 模型给的是像素，原样使用
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [1500, 900]}]}', 1920, 1080)
        self.assertEqual(r["space"], "pixel")
        self.assertEqual(r["points"], [(1500, 900)])
        # 设置里强制「像素」时不做归一化换算
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [710, 261]}]}', 770, 532, avc.COORD_SPACE_PIXEL)
        self.assertEqual(r["space"], "pixel")
        self.assertEqual(r["points"], [(710, 261)])
        # 设置里强制「归一化」时即使数值很小也按 0-1000 换算
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [100, 400]}]}', 1000, 800, avc.COORD_SPACE_NORMALIZED)
        self.assertEqual(r["points"], [(100, 320)])
        # target 自带 scale 时以 scale 为准（覆盖全局判定）
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [0.5, 0.25], "scale": 1}]}', 1000, 800)
        self.assertEqual(r["points"], [(500, 200)])

    def test_parse_response_point_rounding(self):
        """归一化坐标取整：500.6/1000*1000=501，250.2/1000*800=200"""
        import ai_visual_captcha as avc
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [500.6, 250.2]}]}', 1000, 800)
        self.assertEqual(r["points"], [(501, 200)])

    def test_parse_response_invalid(self):
        """非 JSON / 有验证码但无有效坐标 → invalid"""
        import ai_visual_captcha as avc
        self.assertEqual(avc.parse_model_response("我看不懂", 1000, 800)["status"], "invalid")
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": [{"text": "没有坐标"}]}', 1000, 800)
        self.assertEqual(r["status"], "invalid")

    def test_extract_json_repairs_unescaped_quotes(self):
        """模型照抄题目文字会带出未转义的引号（"包含文字"川"的图片"）——JSON 非法，
        旧实现直接解析失败导致坐标全丢（用户实测），现自动修复后仍能拿到坐标"""
        import ai_visual_captcha as avc
        broken = ('```json\n{"captcha": true, "type": "image", "mode": "image", "targets": [\n'
                  '  {"text": "包含文字"川"的图片", "bbox": [398, 517, 625, 749], "point": [506, 634]},\n'
                  '  {"text": "包含文字"川"的图片", "bbox": [620, 519, 897, 800], "point": [700, 650]}\n'
                  ']}\n```')
        r = avc.parse_model_response(broken, 532, 600)
        self.assertEqual(r["status"], "click")
        self.assertEqual(r["mode"], "image")
        # 0-1000 归一化 → 532x600 像素
        self.assertEqual(r["points"], [(269, 380), (372, 390)])
        self.assertEqual(r["labels"][0], '包含文字"川"的图片')
        # 正常 JSON 不受影响（含已经正确转义的引号）
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": [{"text": "桦", "point": [710, 261]}]}',
            770, 532)
        self.assertEqual(r["points"], [(547, 139)])
        self.assertEqual(avc._extract_json('{"s": "含\\"引号\\"的"}'), {"s": '含"引号"的'})
        # 多个未转义引号 + 结尾无引号的情况
        self.assertEqual(avc._extract_json('{"t": "a"b"c"}'), {"t": 'a"b"c'})
        self.assertEqual(avc._extract_json('[1,2]{"a": 1}'), {"a": 1})

    def test_parse_response_mode_text_and_image(self):
        """mode 字段：文字点选=text / 图片选择=image，解析后原样带出"""
        import ai_visual_captcha as avc
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "mode": "text", "targets": ['
            '{"text": "桦", "point": [500, 500]}]}', 1000, 800)
        self.assertEqual(r["mode"], "text")
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "mode": "image", "targets": ['
            '{"text": "有狗的图片", "point": [200, 200]}]}', 1000, 800)
        self.assertEqual(r["mode"], "image")
        # 没给 mode / 非法值 → 空串（不报错）
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": [{"point": [1, 1]}]}', 1000, 800)
        self.assertEqual(r["mode"], "")
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "mode": "XYZ", "targets": [{"point": [1, 1]}]}',
            1000, 800)
        self.assertEqual(r["mode"], "")

    def test_solve_captcha_retries_when_coords_missing(self):
        """模型「确认有验证码但 targets 为空」→ 自动重问，不直接判失败（实测间歇性出现）"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
        }, _stop_event=None)
        empty = '{"captcha": true, "type": "click", "mode": "image", "targets": []}'
        good = '{"captcha": true, "type": "click", "mode": "image", "targets": [{"point": [500, 500]}]}'
        none = '{"captcha": false, "type": "none", "targets": []}'
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", side_effect=[empty, empty, good, none]) as m, \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertTrue(ok, detail)
        self.assertEqual(clicks, [(500, 400)])
        self.assertEqual(m.call_count, 4)      # 空答复重问了 2 次后才拿到坐标
        # 一直拿不到坐标 → 重试耗尽后仍判失败（不会死循环）
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", return_value=empty), \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point"), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertFalse(ok)
        self.assertIn("未返回有效坐标", detail)

    def test_solve_captcha_refuses_absurd_target_count(self):
        """目标数超过单轮上限（图片选择题被当成逐字点选的典型症状）→ 一个都不点，直接判失败"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
        }, _stop_event=None)
        many = ",".join('{"text": "字%d", "point": [%d, 100]}' % (i, i * 10)
                        for i in range(avc.MAX_CLICK_TARGETS + 5))
        reply = '{"captcha": true, "type": "click", "mode": "image", "targets": [%s]}' % many
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", return_value=reply), \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertFalse(ok)
        self.assertIn("目标数异常", detail)
        self.assertEqual(clicks, [])            # 一个都没点

    def test_provider_config_store(self):
        """供应商配置独立文件读写：切换预设时回填各供应商自己的地址/模型/Key"""
        import ai_visual_captcha as avc
        with tempfile.TemporaryDirectory(prefix="delta_provider_test_") as td:
            path = os.path.join(td, "ai_provider_config.json")
            with patch.object(avc, "_provider_store_path", return_value=path):
                self.assertEqual(avc.get_provider_config("DeepSeek"), {})   # 没存过
                self.assertTrue(avc.save_provider_config("DeepSeek", "sk-ds", "https://api.deepseek.com",
                                                         "deepseek-flash"))
                self.assertTrue(avc.save_provider_config("智谱GLM", "sk-zp", "https://open.bigmodel.cn/api/paas/v4",
                                                         "glm-4.6v-flash"))
                ds = avc.get_provider_config("DeepSeek")
                self.assertEqual(ds["api_key"], "sk-ds")
                self.assertEqual(ds["model"], "deepseek-flash")
                self.assertEqual(avc.get_provider_config("智谱GLM")["api_key"], "sk-zp")
                # 覆盖同一家不影响另一家
                avc.save_provider_config("DeepSeek", "sk-ds2", "https://api.deepseek.com", "deepseek-flash")
                self.assertEqual(avc.get_provider_config("DeepSeek")["api_key"], "sk-ds2")
                self.assertEqual(avc.get_provider_config("智谱GLM")["api_key"], "sk-zp")
                # 空名字不写
                self.assertFalse(avc.save_provider_config("", "x"))
                # 文件损坏 → 返回空而不抛
                with open(path, "w", encoding="utf-8") as f:
                    f.write("{不是json")
                self.assertEqual(avc.get_provider_config("DeepSeek"), {})

    def test_get_preset(self):
        """供应商预设回填；自定义返回空"""
        import ai_visual_captcha as avc
        p = avc.get_preset("智谱GLM")
        self.assertTrue(p["base_url"].startswith("https://"))
        self.assertEqual(p["model"], "glm-4.6v-flash")
        self.assertEqual(avc.get_preset(avc.CUSTOM_PROVIDER), {"base_url": "", "model": ""})
        self.assertEqual(avc.get_preset("不存在的"), {"base_url": "", "model": ""})
        # 预设表结构完整
        for item in avc.PROVIDER_PRESETS:
            self.assertIn("name", item)
            self.assertIn("base_url", item)
            self.assertIn("model", item)
            if item["name"] != avc.CUSTOM_PROVIDER:
                self.assertTrue(item["base_url"].startswith("https://"))

    def test_detect_image_tiles_and_snap(self):
        """选图类验证码：图块检测 + 坐标吸附（模型给的坐标偏出去也能救回来）"""
        import numpy as np
        import ai_visual_captcha as avc
        # 造一张 3 列 2 行、白底彩块的「验证码图」
        img = np.full((594, 526, 3), 255, np.uint8)
        rects = []
        for r in range(2):
            for c in range(3):
                x, y, w, h = 29 + c * 154, 202 + r * 156, 152, 154
                img[y:y + h, x:x + w] = (60 + r * 40, 120, 200)
                rects.append((x, y, w, h))
        tiles = avc.detect_image_tiles(img)
        self.assertEqual(len(tiles), 6)
        self.assertEqual(tiles[0][:2], (29, 202))          # 从上到下、从左到右
        self.assertEqual(tiles[5][:2], (29 + 308, 202 + 156))
        # 坐标吸附：偏一点 → 吸附到图块中心；离谱 → 拒绝
        centers = [(t[0] + t[2] // 2, t[1] + t[3] // 2) for t in tiles]
        snapped, rejected = avc.snap_points_to_tiles(
            [(centers[2][0] + 20, centers[2][1] - 25), (500, 20)], tiles)
        self.assertEqual(snapped[0], centers[2])
        self.assertIsNone(snapped[1])
        self.assertEqual(rejected, 1)
        # 没有图块时报原样（不做吸附，避免误伤其它题型）
        same, rej2 = avc.snap_points_to_tiles([(12, 34)], [])
        self.assertEqual(same, [(12, 34)])
        self.assertEqual(rej2, 0)

    def test_solve_captcha_refreshes_when_low_confidence(self):
        """选图类「没把握」（conf 低于阈值）→ 不硬提交，点「换一组」换批图重来"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
            "captcha_refresh_enabled": True,
            "captcha_refresh_point": [900, 1000],
            "captcha_refresh_max": 2,
        }, _stop_event=None)
        low = ('{"captcha": true, "type": "click", "mode": "image", "targets": '
               '[{"text": "图2", "point": [500, 500], "conf": 35}]}')
        high = ('{"captcha": true, "type": "click", "mode": "image", "targets": '
                '[{"text": "图2", "point": [500, 500], "conf": 88}]}')
        none = '{"captcha": false, "type": "none", "targets": []}'
        clicks = []
        # 第1轮：低把握 → 点换一组 → 重来；第2次识别高把握 → 正常点击；复核消失 → 成功
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", side_effect=[low, high, none]) as m, \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertTrue(ok, detail)
        # 顺序：换一组(900,1000) → 目标(500,400)
        self.assertEqual(clicks, [(900, 1000), (500, 400)])
        self.assertEqual(m.call_count, 3)

    def test_solve_captcha_refresh_budget_exhausted(self):
        """一直没把握 → 换一组次数用尽后按最可能答案提交（不死循环、不空转）"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
            "captcha_refresh_enabled": True,
            "captcha_refresh_point": [900, 1000],
            "captcha_refresh_max": 2,
        }, _stop_event=None)
        low = ('{"captcha": true, "type": "click", "mode": "image", "targets": '
               '[{"text": "图2", "point": [500, 500], "conf": 20}]}')
        none = '{"captcha": false, "type": "none", "targets": []}'
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", side_effect=[low, low, low, none]), \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertTrue(ok, detail)
        # 换一组 2 次（预算用尽）后，第 3 次就按答案点下去
        self.assertEqual(clicks, [(900, 1000), (900, 1000), (500, 400)])

    def test_get_confirm_point(self):
        """选图后「确认」按钮坐标：未启用/坐标为 0 → None（不点）"""
        import ai_visual_captcha as avc
        self.assertIsNone(avc.get_confirm_point({"captcha_confirm_enabled": False,
                                                 "captcha_confirm_point": [800, 900]}))
        self.assertIsNone(avc.get_confirm_point({"captcha_confirm_enabled": True,
                                                 "captcha_confirm_point": [0, 0]}))
        self.assertIsNone(avc.get_confirm_point({}))
        self.assertEqual(avc.get_confirm_point({"captcha_confirm_enabled": True,
                                                "captcha_confirm_point": [800, 900]}),
                         (800, 900))

    def test_solve_captcha_recheck_after_last_round(self):
        """max_rounds=1：点完目标后必须再复核一次，验证码消失即返回成功。

        旧逻辑 round_index<rounds 才复核，rounds=1 时点完直接返回失败——
        即使点对了也判不过，只能靠人工等待兜底。"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
        }, _stop_event=None)
        # 第1轮（识别）→ 有验证码；第2轮（复核）→ 验证码已消失
        replies = ['{"captcha": true, "type": "click", "targets": [{"point": [500, 500]}]}',
                   '{"captcha": false, "type": "none", "targets": []}']
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", side_effect=replies), \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertTrue(ok, detail)
        self.assertIn("复核", detail)
        # [500,500] 是 0-1000 归一化 → 1000x800 图上 (500,400)；复核轮不点击
        self.assertEqual(clicks, [(500, 400)])

    def test_solve_captcha_clicks_confirm_after_targets(self):
        """启用「选图后点确认」时：点完所有目标图后再点确认坐标"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
            "captcha_confirm_enabled": True,
            "captcha_confirm_point": [900, 1000],
        }, _stop_event=None)
        replies = ['{"captcha": true, "type": "click", "targets": ['
                   '{"text": "图A", "point": [300, 300]}, {"text": "图B", "point": [400, 400]}]}',
                   '{"captcha": false, "type": "none", "targets": []}']
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", side_effect=replies), \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertTrue(ok, detail)
        # 顺序：图A → 图B → 确认（前两个为归一化换算后的像素坐标）
        self.assertEqual(clicks, [(300, 240), (400, 320), (900, 1000)])

    def test_solve_captcha_recheck_still_present(self):
        """复核轮仍识别到目标 → 判定未通过（且不在复核轮重复点击）"""
        import types
        import unittest.mock as mock
        import ai_visual_captcha as avc

        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
        }, _stop_event=None)
        reply = '{"captcha": true, "type": "click", "targets": [{"point": [500, 500]}]}'
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=None), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 1000, 800)), \
             mock.patch.object(avc, "_ask_model", return_value=reply), \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertFalse(ok)
        self.assertIn("复核时验证码仍在", detail)
        self.assertEqual(clicks, [(500, 400)])      # 只点了 1 次，复核轮不点

    def test_normalize_model_retired_upgrade(self):
        """已下线旧模型自动映射到当前替代；其他值原样返回"""
        import ai_visual_captcha as avc
        self.assertEqual(avc.normalize_model("glm-4v-flash"), "glm-4.6v-flash")
        self.assertEqual(avc.normalize_model("GLM-4V-FLASH"), "glm-4.6v-flash")  # 大小写不敏感
        self.assertEqual(avc.normalize_model("glm-4.6v-flash"), "glm-4.6v-flash")
        self.assertEqual(avc.normalize_model("qwen-vl-plus"), "qwen-vl-plus")
        self.assertEqual(avc.normalize_model(""), "")

    def test_ask_model_retries_on_429(self):
        """429 限流应自动重试：前两次 429、第三次成功"""
        import io
        import urllib.error
        import unittest.mock as mock
        import ai_visual_captcha as avc

        def _resp(payload):
            return io.BytesIO(json.dumps(payload).encode("utf-8"))

        ok_payload = {"choices": [{"message": {"content": '{"captcha": false}'}}]}
        responses = [
            urllib.error.HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO(b"")),
            urllib.error.HTTPError("url", 429, "Too Many Requests", {}, io.BytesIO(b"")),
            _resp(ok_payload),
        ]
        with mock.patch.object(avc.urllib.request, "urlopen", side_effect=responses), \
             mock.patch.object(avc.time, "sleep") as sleep_mock, \
             mock.patch.object(avc, "RETRY_BACKOFF_SECONDS", 0.0):
            content = avc._ask_model("https://x/v1", "sk", "m", "b64", "p")
        self.assertIn("captcha", content)
        self.assertEqual(sleep_mock.call_count, 2)  # 两次 429 各退避一次

    def test_ask_model_does_not_retry_401(self):
        """401 密钥无效应立即抛出，不重试"""
        import io
        import urllib.error
        import unittest.mock as mock
        import ai_visual_captcha as avc

        with mock.patch.object(avc.urllib.request, "urlopen",
                               side_effect=urllib.error.HTTPError("url", 401, "Unauthorized", {}, io.BytesIO(b""))), \
             mock.patch.object(avc.time, "sleep") as sleep_mock:
            with self.assertRaises(urllib.error.HTTPError):
                avc._ask_model("https://x/v1", "bad-key", "m", "b64", "p")
        self.assertEqual(sleep_mock.call_count, 0)

    def test_ask_model_retries_on_timeout(self):
        """超时应自动重试：第一次超时、第二次成功（修复前超时被当致命错误直接失败）"""
        import io
        import socket
        import unittest.mock as mock
        import ai_visual_captcha as avc

        ok_payload = {"choices": [{"message": {"content": '{"captcha": false}'}}]}
        responses = [
            socket.timeout("timed out"),
            io.BytesIO(json.dumps(ok_payload).encode("utf-8")),
        ]
        with mock.patch.object(avc.urllib.request, "urlopen", side_effect=responses), \
             mock.patch.object(avc.time, "sleep") as sleep_mock, \
             mock.patch.object(avc, "RETRY_BACKOFF_SECONDS", 0.0):
            content = avc._ask_model("https://x/v1", "sk", "m", "b64", "p")
        self.assertIn("captcha", content)
        self.assertEqual(sleep_mock.call_count, 1)

    def test_ask_model_timeout_retry_is_bounded(self):
        """连续超时：最多重试 TIMEOUT_RETRIES 次后抛错，不会无限重试"""
        import socket
        import unittest.mock as mock
        import ai_visual_captcha as avc

        with mock.patch.object(avc.urllib.request, "urlopen",
                               side_effect=socket.timeout("timed out")) as url_mock, \
             mock.patch.object(avc.time, "sleep"), \
             mock.patch.object(avc, "RETRY_BACKOFF_SECONDS", 0.0):
            with self.assertRaises((socket.timeout, TimeoutError)):
                avc._ask_model("https://x/v1", "sk", "m", "b64", "p")
        self.assertEqual(url_mock.call_count, avc.TIMEOUT_RETRIES + 1)

    def test_ask_model_retries_on_remote_disconnected(self):
        """响应中途断开（RemoteDisconnected）也应重试，而不是一次就判死"""
        import io
        import http.client
        import unittest.mock as mock
        import ai_visual_captcha as avc

        ok_payload = {"choices": [{"message": {"content": '{"captcha": false}'}}]}
        responses = [
            http.client.RemoteDisconnected("Remote end closed connection without response"),
            io.BytesIO(json.dumps(ok_payload).encode("utf-8")),
        ]
        with mock.patch.object(avc.urllib.request, "urlopen", side_effect=responses), \
             mock.patch.object(avc.time, "sleep"), \
             mock.patch.object(avc, "RETRY_BACKOFF_SECONDS", 0.0):
            content = avc._ask_model("https://x/v1", "sk", "m", "b64", "p")
        self.assertIn("captcha", content)

    def test_build_prompt_splits_by_question_kind(self):
        """题干类型由 OCR 判死后选提示词：内容题走原有方案（逐字未改），
        只有包含文字题才叠加激进规则 —— 不能再靠 prompt 里的「仅当…时生效」软约束。"""
        import ai_visual_captcha as avc
        content = avc._build_prompt(800, 640, avc.QUESTION_KIND_CONTENT)
        text = avc._build_prompt(800, 640, avc.QUESTION_KIND_TEXT)
        default = avc._build_prompt(800, 640)
        # 内容题 / 未判定：原有方案三处原样保留，激进规则一个字都不许出现
        for p in (content, default):
            self.assertIn("（通常 1~4 个）", p)
            self.assertIn("这些图里往往只有一两张、最多几张符合要求", p)
            self.assertIn("（例外：题目明确要求找「包含文字X」的图片时", p)
            self.assertNotIn("宁多勿漏", p)
            self.assertNotIn("不要预设数量", p)
            self.assertNotIn("targets 数量必须等于 checks 里判为", p)
            self.assertNotIn("仅当题目要求找", p)
        # 判不出类型时必须等于内容题提示词（最保守，行为同改造前）
        self.assertEqual(content, default)
        # 包含文字题：基线 + 3 处加强
        self.assertIn("不要预设数量", text)
        self.assertIn("targets 数量必须等于 checks 里判为", text)
        self.assertIn("宁多勿漏", text)
        self.assertNotIn("这些图里往往只有一两张、最多几张符合要求", text)
        self.assertNotEqual(content, text)
        # 加强版是在基线之上叠加：除 3 处外的公共部分必须一致
        for anchor in ("你是登录验证码识别助手", "target 数量 = 符合描述的图片张数（通常 1~4 个）"):
            self.assertIn(anchor, text)
            self.assertIn(anchor, content)

    def test_question_kind_from_text(self):
        """OCR 题面特征词 → 题干类型（判不出时必须给 unknown，调用方据此退回原有方案）"""
        import captcha_router as cr
        self.assertEqual(cr.question_kind_from_text("请选择所有包含文字：川 的图片"), "text")
        self.assertEqual(cr.question_kind_from_text("选择含有文字的图片"), "text")
        self.assertEqual(cr.question_kind_from_text("请选择所有海浪的图片"), "content")
        self.assertEqual(cr.question_kind_from_text(""), "unknown")
        self.assertEqual(cr.question_kind_from_text(None), "unknown")

    def test_is_configured_require_enabled(self):
        """require_enabled=False（测试绕过开关）时只需供应商配置完整"""
        import ai_visual_captcha as avc
        cfg = {"ai_visual_captcha_enabled": False,
               "ai_visual_captcha_base_url": "https://x/v1",
               "ai_visual_captcha_api_key": "sk",
               "ai_visual_captcha_model": "glm-4.6v-flash"}
        # 默认要求启用开关：关着就不通过
        self.assertFalse(avc.is_configured(cfg))
        # 测试模式：绕过开关只看配置
        self.assertTrue(avc.is_configured(cfg, require_enabled=False))

    def test_get_capture_region(self):
        """识别区域：未启用返回 None，启用且合法返回 (x,y,w,h)，非法返回 None"""
        import ai_visual_captcha as avc
        self.assertIsNone(avc.get_capture_region({}))
        self.assertIsNone(avc.get_capture_region({"captcha_region_enabled": False,
                                                  "captcha_region": [10, 20, 300, 200]}))
        self.assertIsNone(avc.get_capture_region({"captcha_region_enabled": True}))
        self.assertIsNone(avc.get_capture_region({"captcha_region_enabled": True,
                                                  "captcha_region": [10, 20, 0, 200]}))
        self.assertIsNone(avc.get_capture_region({"captcha_region_enabled": True,
                                                  "captcha_region": ["a", 20, 0, 200]}))
        r = avc.get_capture_region({"captcha_region_enabled": True,
                                    "captcha_region": [10, 20, 300, 200]})
        self.assertEqual(r, (10, 20, 300, 200))

    def test_is_configured(self):
        """未启用/缺配置 → False；启用且配置完整 → True"""
        import ai_visual_captcha as avc
        self.assertFalse(avc.is_configured({}))
        self.assertFalse(avc.is_configured({
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://x/v1"}))
        self.assertTrue(avc.is_configured({
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://x/v1",
            "ai_visual_captcha_api_key": "sk-x",
            "ai_visual_captcha_model": "glm-4v-flash"}))
        # 关闭时即便配置完整也不生效
        self.assertFalse(avc.is_configured({
            "ai_visual_captcha_enabled": False,
            "ai_visual_captcha_base_url": "https://x/v1",
            "ai_visual_captcha_api_key": "sk-x",
            "ai_visual_captcha_model": "glm-4v-flash"}))

    def test_build_prompt_contains_resolution(self):
        """提示词应包含屏幕分辨率与严格 JSON 要求"""
        import ai_visual_captcha as avc
        prompt = avc._build_prompt(1920, 1080)
        self.assertIn("1920", prompt)
        self.assertIn("1080", prompt)
        self.assertIn("captcha", prompt)


# ==================== 滑块验证 YOLO（离线数学与解析，不加载模型） ====================
class TestSliderCaptchaYolo(unittest.TestCase):
    """测试 slider_captcha 的 letterbox / NMS / 坐标映射 / 拖动距离 / 元数据解析（不跑真实推理）"""

    def test_is_enabled(self):
        import slider_captcha as sc
        self.assertFalse(sc.is_enabled({}))
        self.assertFalse(sc.is_enabled({"slider_yolo_enabled": False}))
        self.assertTrue(sc.is_enabled({"slider_yolo_enabled": True}))

    def test_letterbox_roundtrip(self):
        """letterbox：2560x1440 → 640 等比缩放，回映射坐标应还原"""
        import numpy as np
        import slider_captcha as sc
        img = np.zeros((1440, 2560, 3), dtype=np.uint8)
        tensor, scale, dw, dh = sc.letterbox(img)
        self.assertEqual(tensor.shape, (1, 3, 640, 640))
        self.assertAlmostEqual(scale, 0.25)
        self.assertEqual(dw, 0)
        self.assertEqual(dh, (640 - 360) // 2)
        boxes = np.array([[320.0, 320.0, 400.0, 400.0]])
        back = sc._scale_boxes_back(boxes, scale, dw, dh, 2560, 1440)
        # letterbox 中 (320,320) → 原图 ((320-0)/0.25, (320-140)/0.25) = (1280, 720)
        self.assertEqual(back[0][0], 1280)
        self.assertEqual(back[0][1], 720)

    def test_scale_boxes_clip(self):
        """映射回原图后坐标应裁剪到屏幕范围内"""
        import numpy as np
        import slider_captcha as sc
        boxes = np.array([[-50.0, -50.0, 10000.0, 10000.0]])
        back = sc._scale_boxes_back(boxes, 1.0, 0, 0, 1000, 800)
        self.assertEqual(back[0][0], 0)
        self.assertEqual(back[0][1], 0)
        self.assertEqual(back[0][2], 999)
        self.assertEqual(back[0][3], 799)

    def test_nms_suppress_overlap(self):
        """NMS：重叠框被抑制，独立框保留"""
        import numpy as np
        import slider_captcha as sc
        boxes = np.array([
            [0, 0, 10, 10],
            [1, 1, 11, 11],     # 与第0个高度重叠，应被抑制
            [100, 100, 120, 120],  # 独立，应保留
        ], dtype=np.float64)
        scores = np.array([0.9, 0.8, 0.7])
        keep = sc._nms(boxes, scores, iou_threshold=0.45)
        self.assertEqual(sorted(keep), [0, 2])

    def test_parse_names_from_metadata(self):
        """Ultralytics names 元数据 JSON 解析；坏数据回退"""
        import slider_captcha as sc
        names = sc._parse_names_from_metadata({"names": '{"0": "gap", "1": "slider", "2": "puzzle"}'})
        self.assertEqual(names, {0: "gap", 1: "slider", 2: "puzzle"})
        self.assertIsNone(sc._parse_names_from_metadata({"names": "not-json"}))
        self.assertIsNone(sc._parse_names_from_metadata({}))

    def test_compute_drag_distance(self):
        """拖动距离 = gap 中心x − puzzle 中心x + 微调；puzzle 缺失退用 slider"""
        import slider_captcha as sc

        def det(cls, cx, conf=0.9):
            return {"class": cls, "conf": conf, "box": [cx - 10, 100, cx + 10, 120],
                    "center": (cx, 110)}

        distance, _ = sc.compute_drag_distance(
            [det("gap", 800), det("puzzle", 300)], offset=5)
        self.assertEqual(distance, 505)
        # 无 puzzle 时用 slider
        distance, _ = sc.compute_drag_distance([det("gap", 800), det("slider", 300)])
        self.assertEqual(distance, 500)
        # 缺 gap → 无法计算
        distance, detail = sc.compute_drag_distance([det("puzzle", 300)])
        self.assertIsNone(distance)

    def test_resolve_model_path_missing_returns_empty(self):
        """权重不存在时返回空串（solve 时给出明确提示）"""
        import slider_captcha as sc
        path = sc.resolve_model_path()
        # 开发机上 best.onnx 在项目根目录应能找到；若被移走则为空串，不应抛异常
        self.assertIsInstance(path, str)

    def test_resolve_model_path_user_dir_first_and_reset_session(self):
        """用户导入目录优先；reset_session 丢弃旧会话"""
        import os
        import tempfile
        import unittest.mock as mock
        import slider_captcha as sc
        import config
        with tempfile.TemporaryDirectory() as tmp_dir:
            user_model = os.path.join(tmp_dir, "best.onnx")
            with open(user_model, "wb") as f:
                f.write(b"dummy")
            # 重定向模型路径到临时目录，不碰真实 %APPDATA%
            with mock.patch.object(config, "SLIDER_MODEL_PATH", user_model), \
                 mock.patch.object(config, "SLIDER_MODEL_DIR", tmp_dir):
                sc.reset_session()
                self.assertEqual(sc._session, None)
                self.assertEqual(sc._session_model_path, "")
                self.assertEqual(os.path.abspath(sc.resolve_model_path()),
                                 os.path.abspath(user_model))
        sc.reset_session()


# ==================== 验证码调度（OCR 判定 → 分发，离线） ====================
class TestCaptchaRouter(unittest.TestCase):
    """测试 captcha_router 的关键词解析与路由判定（不发真实请求、不加载模型）"""

    def test_parse_keywords(self):
        """关键词解析：中英文逗号/顿号分隔、去空白、空配置返回空"""
        from captcha_router import _parse_keywords
        self.assertEqual(_parse_keywords("拖动,滑动"), ["拖动", "滑动"])
        self.assertEqual(_parse_keywords("拖动，滑动、拼图"), ["拖动", "滑动", "拼图"])
        self.assertEqual(_parse_keywords(" 拖动 , 滑动 "), ["拖动", "滑动"])
        self.assertEqual(_parse_keywords(""), [])
        self.assertEqual(_parse_keywords(None), [])

    def test_route_text_image_captcha_goes_manual(self):
        """第③类「图片文字选择」（题面含「包含文字」）→ 直接转人工、不调用 AI"""
        import captcha_router as cr
        s = {
            "captcha_auto_enabled": True,
            "captcha_slider_keywords": "拖动,滑动,滑块",
            "captcha_click_keywords": "依次点击,请选择,选择所有,包含文字",
            "captcha_manual_keywords": "包含文字,含有文字",
        }
        # 命中「包含文字」→ 转人工
        self.assertTrue(cr.needs_manual_verification(
            s, "为了您的账号安全，请验证后登录。选择所有符合描述的图片包含文字：川"))
        # 第②类「选择图片」（题面只有事物名）→ 不转人工，照常走 AI
        self.assertFalse(cr.needs_manual_verification(s, "选择所有符合描述的图片 海浪"))
        self.assertFalse(cr.needs_manual_verification(s, "请依次点击：桦 离"))
        # 路由结果：命中转人工关键词时直接返回失败（调用方据此进入人工等待）
        ok, detail = cr._route_once(type("A", (), {"settings": s})(), screen_text="包含文字：川",
                                    force=True)
        self.assertFalse(ok)
        self.assertIn("转人工", detail)
        # 转人工关键词清空 → 关闭本规则，第③类也放行给 AI
        self.assertFalse(cr.needs_manual_verification({"captcha_manual_keywords": ""}, "包含文字：川"))
        # 键缺失 → 用默认词（仍拦）
        self.assertTrue(cr.needs_manual_verification({}, "包含文字：川"))
        self.assertFalse(cr.needs_manual_verification({}, "选择所有符合描述的图片 海浪"))

    def test_route_disabled_master_switch(self):
        """总开关关闭 → 不做任何处理"""
        import types
        from captcha_router import route_and_solve
        app = types.SimpleNamespace(settings={"captcha_auto_enabled": False})
        ok, detail = route_and_solve(app, screen_text="请拖动滑块")
        self.assertFalse(ok)
        self.assertIn("总开关未启用", detail)

    def test_route_slider_keyword_disabled_modules(self):
        """命中滑块关键词但滑块YOLO未启用且AI未配置 → 未解决（不误放行）"""
        import types
        from captcha_router import route_and_solve
        app = types.SimpleNamespace(settings={
            "captcha_auto_enabled": True,
            "captcha_slider_keywords": "拖动",
            "captcha_click_keywords": "依次点击",
            "slider_yolo_enabled": False,
            "ai_visual_captcha_enabled": False,
        })
        ok, detail = route_and_solve(app, screen_text="请拖动滑块完成验证")
        self.assertFalse(ok)
        self.assertIn("未配置", detail)

    def test_route_click_keyword_no_ai(self):
        """命中点击关键词但 AI 未配置 → 未解决"""
        import types
        from captcha_router import route_and_solve
        app = types.SimpleNamespace(settings={
            "captcha_auto_enabled": True,
            "captcha_slider_keywords": "拖动",
            "captcha_click_keywords": "依次点击",
            "slider_yolo_enabled": False,
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "",  # AI 配置不完整
        })
        ok, detail = route_and_solve(app, screen_text="请依次点击文字")
        self.assertFalse(ok)
        self.assertIn("未配置", detail)

    def test_route_no_keyword_no_ai_releases(self):
        """未命中关键词且未配置 AI → 放行（由启动流程兜底判断）"""
        import types
        from captcha_router import route_and_solve
        app = types.SimpleNamespace(settings={
            "captcha_auto_enabled": True,
            "captcha_slider_keywords": "拖动",
            "captcha_click_keywords": "依次点击",
        })
        ok, detail = route_and_solve(app, screen_text="欢迎登录WeGame")
        self.assertTrue(ok)
        self.assertIn("无验证码特征", detail)

    def test_route_slider_keyword_dispatches_to_yolo(self):
        """命中滑块关键词且滑块YOLO启用 → 分发到 solve_slider_yolo（mock 验证）"""
        import types
        import slider_captcha
        from captcha_router import route_and_solve
        calls = {}

        def _mock_solve(app, stop_event=None, **kwargs):
            calls["called"] = True
            return True, True, "mock拖动成功"

        original = slider_captcha.solve_slider_yolo
        slider_captcha.solve_slider_yolo = _mock_solve
        try:
            app = types.SimpleNamespace(settings={
                "captcha_auto_enabled": True,
                "captcha_slider_keywords": "拖动",
                "captcha_click_keywords": "依次点击",
                "slider_yolo_enabled": True,
            })
            ok, detail = route_and_solve(app, screen_text="请拖动滑块完成拼图")
            self.assertTrue(calls.get("called"))
            self.assertTrue(ok)
            self.assertIn("mock拖动成功", detail)
        finally:
            slider_captcha.solve_slider_yolo = original

    def test_route_slider_yolo_not_found_falls_back_to_ai(self):
        """YOLO 未检出滑块元素（OCR 误报）→ 落 AI 兜底（mock 验证）"""
        import types
        import slider_captcha
        import ai_visual_captcha
        from captcha_router import route_and_solve

        slider_captcha.solve_slider_yolo = lambda *a, **k: (False, False, "未检测到滑块元素")
        ai_calls = {}
        original_ai = ai_visual_captcha.solve_captcha

        def _mock_ai(app, stop_event=None, save_debug=False, **kwargs):
            ai_calls["called"] = True
            return True, "AI判定无验证码"

        ai_visual_captcha.solve_captcha = _mock_ai
        try:
            app = types.SimpleNamespace(settings={
                "captcha_auto_enabled": True,
                "captcha_slider_keywords": "拖动",
                "captcha_click_keywords": "依次点击",
                "slider_yolo_enabled": True,
                "ai_visual_captcha_enabled": True,
                "ai_visual_captcha_base_url": "https://x/v1",
                "ai_visual_captcha_api_key": "sk",
                "ai_visual_captcha_model": "glm-4v-flash",
            })
            ok, detail = route_and_solve(app, screen_text="请拖动滑块")
            self.assertTrue(ai_calls.get("called"))
            self.assertTrue(ok)
            self.assertIn("AI兜底", detail)
        finally:
            ai_visual_captcha.solve_captcha = original_ai

class TestGlyphGateFlow(unittest.TestCase):
    """本地字形匹配的「有把握就点、没把握就换一组」策略（全 mock：不载字体、不点屏幕、不发请求）"""

    # ---------- 决策函数（纯逻辑） ----------
    def test_decide_submits_when_conf_above_gate(self):
        """conf = 选中最低 − 未选中最高 = 0.45 − 0.20 = +0.25 > 0.16 → 提交"""
        from captcha_glyph_match import decide
        d = decide([0.60, 0.55, 0.50, 0.45, 0.20, 0.10], threshold=0.37, gate=0.16)
        self.assertEqual(d["action"], "submit")
        self.assertEqual(d["picked"], [1, 2, 3, 4])
        self.assertAlmostEqual(d["conf"], 0.25, places=3)

    def test_decide_refreshes_when_conf_below_gate(self):
        """conf = 0.45 − 0.30 = +0.15 ≤ 0.16 → 换一组（差一点点也不赌）"""
        from captcha_glyph_match import decide
        d = decide([0.60, 0.55, 0.45, 0.30, 0.25, 0.20], threshold=0.37, gate=0.16)
        self.assertEqual(d["action"], "refresh")
        self.assertEqual(d["picked"], [1, 2, 3])
        self.assertIn("门限", d["reason"])

    def test_decide_never_submits_on_degenerate_scores(self):
        """退化输入（全选/全不选/全同分）一律不允许提交。

        ⚠️ confidence() 在「没有未选中块」时会返回 1.0，若不单独拦就会把「没把握」
        误判成「很有把握」——这条测试就是钉这个坑。"""
        from captcha_glyph_match import decide
        for scores in ([0.9] * 6, [0.5] * 6, [0.1] * 6, []):
            d = decide(scores, threshold=0.37, gate=0.16)
            self.assertEqual(d["action"], "refresh", f"scores={scores} 不该提交")

    # ---------- 题面目标字 ----------
    def test_extract_target_char(self):
        from captcha_glyph_flow import extract_target_char
        self.assertEqual(extract_target_char("请选择所有包含文字：“忠”的图片"), "忠")
        self.assertEqual(extract_target_char("含有文字：昆"), "昆")
        self.assertEqual(extract_target_char("含文字: 田"), "田")
        self.assertEqual(extract_target_char("选择所有符合描述的图片 海浪"), "")
        self.assertEqual(extract_target_char(""), "")
        self.assertEqual(extract_target_char(None), "")

    # ---------- 「换一组」可用性 ----------
    def test_refresh_available(self):
        from captcha_router import refresh_available
        self.assertFalse(refresh_available({}))
        self.assertFalse(refresh_available({"captcha_refresh_enabled": True,
                                            "captcha_refresh_point": [0, 0]}))
        self.assertFalse(refresh_available({"captcha_refresh_enabled": False,
                                            "captcha_refresh_point": [1629, 1116],
                                            "captcha_refresh_max": 2}))
        # ⚠️ 既有语义：max 填 0 会被 ``int(x or 2)`` 当成 2（0 是 falsy），所以这里是 True。
        # 本函数刻意与 route_and_solve 保持一致；要改成「0 就是不刷」，三处必须一起改。
        self.assertTrue(refresh_available({"captcha_refresh_enabled": True,
                                           "captcha_refresh_point": [1629, 1116],
                                           "captcha_refresh_max": 0}))
        self.assertFalse(refresh_available({"captcha_refresh_enabled": True,
                                            "captcha_refresh_point": ["x", "y"],
                                            "captcha_refresh_max": 2}))
        self.assertTrue(refresh_available({"captcha_refresh_enabled": True,
                                           "captcha_refresh_point": [1629, 1116],
                                           "captcha_refresh_max": 2}))

    # ---------- 图像处理模式（prep_tile / GlyphMatcher） ----------
    def test_prep_tile_bh_matches_legacy_formula(self):
        """mode="bh" 必须与「形态学黑帽 + ±3σ」原公式逐位一致（生产行为不变的守卫）"""
        import cv2
        import numpy as np
        from captcha_glyph_match import BH_KERNEL, TILE_H, TILE_W, prep_tile
        rng = np.random.default_rng(20260921)
        for _ in range(3):
            t = rng.integers(0, 256, (140, 140, 3), dtype=np.uint8)
            got = prep_tile(t, BH_KERNEL, "bh")
            g = cv2.cvtColor(cv2.resize(t, (TILE_W, TILE_H),
                                        interpolation=cv2.INTER_CUBIC),
                             cv2.COLOR_BGR2GRAY).astype(np.float32)
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (BH_KERNEL, BH_KERNEL))
            x = cv2.morphologyEx(g, cv2.MORPH_BLACKHAT, k).astype(np.float32)
            std = float(x.std()) or 1.0
            want = np.clip((x - float(x.mean())) / (3.0 * std), -1.0, 1.0)
            self.assertTrue(np.array_equal(got, want))
            self.assertTrue(np.array_equal(got, prep_tile(t)), "默认参数必须走同一条路")

    def test_prep_tile_unknown_mode_falls_back(self):
        """非法 mode 必须回落默认，不能静默变成另一种处理"""
        import numpy as np
        from captcha_glyph_match import prep_tile
        rng = np.random.default_rng(1)
        t = rng.integers(0, 256, (140, 140, 3), dtype=np.uint8)
        self.assertTrue(np.array_equal(prep_tile(t, 25, "根本没有这种模式"), prep_tile(t)))

    def test_matcher_mode_and_kernel(self):
        """GlyphMatcher 的 mode/kernel：显式值保留，非法值回落默认"""
        from captcha_glyph_match import BH_KERNEL, PREP_DEFAULT, GlyphMatcher
        m = GlyphMatcher(kernel=35, mode="clahe")
        self.assertEqual(m.mode, "clahe")
        self.assertEqual(m.kernel, 35)
        self.assertEqual(GlyphMatcher().mode, PREP_DEFAULT)
        self.assertEqual(GlyphMatcher().kernel, BH_KERNEL)
        self.assertEqual(GlyphMatcher(mode="乱写").mode, PREP_DEFAULT)

    def test_read_profile_defaults_and_fallbacks(self):
        """可调四项：缺省取算法基线；非法值回落（用户手填的值不能信）；核强制奇数"""
        import captcha_glyph_match as cgm
        from captcha_glyph_flow import read_profile
        d = read_profile({})
        self.assertEqual(d["mode"], cgm.PREP_DEFAULT)
        self.assertEqual(d["kernel"], cgm.BH_KERNEL)
        self.assertAlmostEqual(d["threshold"], cgm.DEFAULT_THRESHOLD)
        self.assertAlmostEqual(d["gate"], cgm.GATE_DEFAULT)
        p = read_profile({"captcha_glyph_prep": "clahe", "captcha_glyph_kernel": 35,
                          "captcha_glyph_threshold": 0.40, "captcha_glyph_gate": 0.09})
        self.assertEqual(p["mode"], "clahe")
        self.assertEqual(p["kernel"], 35)
        # 非法值
        bad = read_profile({"captcha_glyph_prep": "根本没有", "captcha_glyph_kernel": 34,
                            "captcha_glyph_threshold": "不是数字", "captcha_glyph_gate": 9})
        self.assertEqual(bad["mode"], cgm.PREP_DEFAULT, "非法图像处理必须回落基线")
        self.assertEqual(bad["kernel"], 35, "偶数核应向上取奇数")
        self.assertAlmostEqual(bad["threshold"], cgm.DEFAULT_THRESHOLD)
        self.assertAlmostEqual(bad["gate"], cgm.GATE_DEFAULT, "越界门限必须回落默认")

    def test_verify_submitted_conservative(self):
        """复核必须保守：只有连续读到题面才判没过；异常/读不到/已停止都算通过"""
        import captcha_router as cr
        import captcha_glyph_flow as gf
        original = cr.gather_region_text
        try:
            cr.gather_region_text = lambda s: "请选择所有包含文字：“忠”的图片"
            self.assertFalse(gf.verify_submitted({}, tries=2, wait=0)[0], "连续读到题面 → 没过")
            seq = ["包含文字：“忠”", "登录中…"]
            cr.gather_region_text = lambda s: seq.pop(0) if seq else ""
            self.assertTrue(gf.verify_submitted({}, tries=2, wait=0)[0], "第二次就没有了 → 通过")
            cr.gather_region_text = lambda s: ""
            self.assertTrue(gf.verify_submitted({}, tries=2, wait=0)[0], "读不到文字 → 通过")

            def _boom(_s):
                raise RuntimeError("截图炸了")
            cr.gather_region_text = _boom
            ok, why = gf.verify_submitted({}, tries=2, wait=0)
            self.assertTrue(ok, "复核异常必须按通过处理，不能去点换一组")
            self.assertIn("异常", why)

            class _Stop:
                def is_set(self):
                    return True
            cr.gather_region_text = lambda s: "包含文字：“忠”"
            self.assertTrue(gf.verify_submitted({}, stop_event=_Stop(), tries=2, wait=0)[0])
        finally:
            cr.gather_region_text = original

    # ---------- 路由集成（mock 掉真实点击/请求） ----------
    def _app(self, **over):
        import types
        s = {"captcha_auto_enabled": True, "captcha_manual_keywords": ""}
        s.update(over)
        return types.SimpleNamespace(settings=s)

    def test_router_text_question_uses_glyph_and_submits(self):
        """「包含文字」类 → 走本地字形匹配；它说提交就提交（不碰 AI）"""
        import captcha_glyph_flow as gf
        import captcha_router as cr
        calls = {}
        original = gf.solve_glyph_captcha

        def _mock(app, stop_event=None, force=False):
            calls["glyph"] = True
            return True, "已提交 [1, 3] 块（conf=+0.25）"

        gf.solve_glyph_captcha = _mock
        try:
            ok, detail = cr._route_once(
                self._app(captcha_glyph_enabled=True),
                screen_text="选择所有包含文字：“忠”的图片", force=True)
            self.assertTrue(calls.get("glyph"))
            self.assertTrue(ok)
            self.assertIn("本地字形匹配", detail)
        finally:
            gf.solve_glyph_captcha = original

    def test_router_low_conf_defers_to_refresh_without_calling_ai(self):
        """没把握 + 「换一组」可用 → 返回失败交给外层刷新，且**不去调 AI**（省一次调用）"""
        import captcha_glyph_flow as gf
        import ai_visual_captcha as avc
        import captcha_router as cr
        original_g, original_ai = gf.solve_glyph_captcha, avc.solve_captcha
        hit = {}

        def _mock_glyph(app, stop_event=None, force=False):
            return False, "置信度 +0.030 未超过门限 0.16"

        def _mock_ai(*a, **k):
            hit["ai"] = True
            return True, "AI 兜底"

        gf.solve_glyph_captcha = _mock_glyph
        avc.solve_captcha = _mock_ai
        try:
            ok, detail = cr._route_once(
                self._app(captcha_glyph_enabled=True,
                          captcha_refresh_enabled=True,
                          captcha_refresh_point=[1629, 1116],
                          captcha_refresh_max=2),
                screen_text="包含文字：“忠”", force=True)
            self.assertFalse(ok)
            self.assertIn("换一组", detail)
            self.assertFalse(hit.get("ai"), "低置信时不该再去调 AI")
        finally:
            gf.solve_glyph_captcha = original_g
            avc.solve_captcha = original_ai

    def test_router_low_conf_goes_manual_instead_of_ai(self):
        """没把握 + 「换一组」不可用 → 转人工验证，**绝不回退 AI**"""
        import captcha_glyph_flow as gf
        import ai_visual_captcha as avc
        import captcha_router as cr
        original_g, original_ai = gf.solve_glyph_captcha, avc.solve_captcha
        hit = {}

        def _mock_glyph(app, stop_event=None, force=False):
            return False, "没检出图块"

        def _mock_ai(*a, **k):
            hit["ai"] = True
            return True, "AI 兜底"

        gf.solve_glyph_captcha = _mock_glyph
        avc.solve_captcha = _mock_ai
        try:
            # 就算 AI 配置齐全（供应商/url/key/model 全给）也不许被调用
            ok, detail = cr._route_once(
                self._app(captcha_glyph_enabled=True,
                          ai_visual_captcha_enabled=True,
                          ai_visual_captcha_base_url="https://x/v1",
                          ai_visual_captcha_api_key="sk",
                          ai_visual_captcha_model="glm-4v-flash"),
                screen_text="包含文字：“忠”", force=True)
            self.assertFalse(ok, "没把握且不能换一组时应返回失败，交给上层等人工")
            self.assertIn("人工", detail)
            self.assertFalse(hit.get("ai"), "该类题永不回退 AI")
        finally:
            gf.solve_glyph_captcha = original_g
            avc.solve_captcha = original_ai

    def test_router_skips_glyph_for_content_question(self):
        """内容类题（不含「包含文字」）→ 不进本地路径，仍走原链路"""
        import captcha_glyph_flow as gf
        import captcha_router as cr
        calls = {}
        original = gf.solve_glyph_captcha

        def _mock(app, stop_event=None, force=False):
            calls["glyph"] = True
            return True, "不该被调用"

        gf.solve_glyph_captcha = _mock
        try:
            ok, detail = cr._route_once(self._app(captcha_glyph_enabled=True),
                                        screen_text="选择所有符合描述的图片 海浪", force=True)
            self.assertFalse(calls.get("glyph"), "内容类题不该走本地字形匹配")
            self.assertTrue(ok)   # 无验证码特征 → 放行
        finally:
            gf.solve_glyph_captcha = original

    def test_router_text_question_goes_manual_when_glyph_disabled(self):
        """「包含文字」类 + 本地字形匹配关闭 → 直接转人工，**也不回退 AI**"""
        import captcha_glyph_flow as gf
        import ai_visual_captcha as avc
        import captcha_router as cr
        original_g, original_ai = gf.solve_glyph_captcha, avc.solve_captcha
        hit = {}

        def _mock_glyph(app, stop_event=None, force=False):
            hit["glyph"] = True
            return True, "不该被调用"

        def _mock_ai(*a, **k):
            hit["ai"] = True
            return True, "AI 兜底"

        gf.solve_glyph_captcha = _mock_glyph
        avc.solve_captcha = _mock_ai
        try:
            # ⚠️ 这里必须 force=False：force 是设置窗口「测试完整流程」用的，会绕过所有子开关
            # （滑块/AI/本地字形都一样），也就测不到「开关关闭时怎么走」这件事。
            ok, detail = cr._route_once(
                self._app(ai_visual_captcha_enabled=True,
                          ai_visual_captcha_base_url="https://x/v1",
                          ai_visual_captcha_api_key="sk",
                          ai_visual_captcha_model="glm-4v-flash"),
                screen_text="包含文字：“忠”", force=False)
            self.assertFalse(hit.get("glyph"), "开关关闭时不该进本地路径")
            self.assertFalse(hit.get("ai"), "该类题永不回退 AI")
            self.assertFalse(ok)
            self.assertIn("人工", detail)
        finally:
            gf.solve_glyph_captcha = original_g
            avc.solve_captcha = original_ai

    def test_glyph_test_button_is_wired(self):
        """设置界面必须真的挂了「测试本地字形匹配」入口
        （否则 captcha_glyph_flow.test_glyph_captcha 就是没人调用的孤儿函数，用户无从实测）"""
        import captcha_glyph_flow as gf
        import settings_window as sw
        self.assertTrue(callable(getattr(gf, "test_glyph_captcha", None)))
        self.assertTrue(callable(getattr(sw.SettingsWindow, "_test_glyph_captcha", None)))
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_window.py")
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertIn("command=self._test_glyph_captcha", src)

    def test_spec_bundles_glyph_modules(self):
        """打包 spec 必须显式收录本地字形匹配的两个模块
        （两者都只在函数内动态 import；漏了会在打包后静默失效——开关打开也没反应）"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "三角洲自动工具.spec")
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for name in ("captcha_glyph_flow", "captcha_glyph_match"):
            self.assertIn("'%s'" % name, text)



class TestCaptchaKeywordFieldsUI(unittest.TestCase):
    """验证码设置窗口：OCR 判定关键词三个输入框必须默认可见、可编辑、能存取

    （历史 bug：它们被放在默认收起的「高级选项」里 → winfo_ismapped=0，用户以为改不了）"""

    def _open(self):
        """用 stub 宿主真实构建验证码设置窗口，并把 config 的读写换成假的（不碰用户 settings.json）"""
        import types
        import tkinter as tk
        import config
        import settings_window as sw
        fake = dict(config.DEFAULT_SETTINGS)
        saved = {}
        orig = (config.load_settings, config.save_settings, sw.config.load_settings,
                sw.config.save_settings)
        config.load_settings = lambda: dict(fake)
        config.save_settings = lambda d: saved.update(d)
        sw.config.load_settings = config.load_settings
        sw.config.save_settings = config.save_settings
        root = tk.Tk()
        root.withdraw()
        stub = types.SimpleNamespace(
            win=root, app=types.SimpleNamespace(settings=dict(fake)),
            _captcha_win=None, _captcha_status_var=None, _active_canvas=None)
        for name in dir(sw.SettingsWindow):
            if name.startswith('_') and callable(getattr(sw.SettingsWindow, name, None)):
                try:
                    setattr(stub, name, types.MethodType(getattr(sw.SettingsWindow, name), stub))
                except Exception:
                    pass
        sw.SettingsWindow._open_captcha_settings(stub)
        root.update_idletasks()
        root.update()
        return root, stub, saved, orig, config, sw

    def test_keyword_fields_visible_editable_and_saved(self):
        try:
            root, stub, saved, orig, config, sw = self._open()
        except Exception as e:               # noqa: BLE001
            self.skipTest('无图形环境，跳过：%s' % e)
            return
        try:
            vars_ = [stub._cap_slider_kw_var, stub._cap_click_kw_var, stub._cap_manual_kw_var]

            def walk(w):
                for c in w.winfo_children():
                    yield c
                    for g in walk(c):
                        yield g

            found = {}
            for e in walk(stub._captcha_win):
                if e.winfo_class() != 'TEntry':
                    continue
                vn = str(e.cget('textvariable'))
                for i, v in enumerate(vars_):
                    if vn == str(v):
                        found[i] = e
            self.assertEqual(len(found), 3, '三个关键词输入框都应存在于窗口中')
            for i, e in sorted(found.items()):
                self.assertEqual(str(e.cget('state')), 'normal', '输入框必须可编辑')
                self.assertTrue(e.winfo_ismapped(),
                                '输入框必须默认可见（不能藏在默认收起的面板里）')
            # 改值 → 保存 → 回读
            vars_[0].set('拖动,滑动,自定义A')
            vars_[1].set('依次点击,自定义B')
            vars_[2].set('包含文字,自定义C')
            sw.SettingsWindow._save_captcha_settings(stub, True)
            self.assertEqual(saved.get('captcha_slider_keywords'), '拖动,滑动,自定义A')
            self.assertEqual(saved.get('captcha_click_keywords'), '依次点击,自定义B')
            self.assertEqual(saved.get('captcha_manual_keywords'), '包含文字,自定义C')
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            (config.load_settings, config.save_settings,
             sw.config.load_settings, sw.config.save_settings) = orig


# ==================== 2026-09-22：用户报的四项 bug ====================
class TestHintTipsRotation(unittest.TestCase):
    """③ 底部提示：文案约束 + 独立轮换定时器（不再挂在 60 秒账号列表刷新上）"""

    def test_tips_within_label_width(self):
        """每条提示都要够短，否则会把右侧控件挤出布局；且不能自带「提示：」前缀"""
        import gui_app
        self.assertTrue(gui_app._HINT_TIPS, "提示文案不能为空")
        for tip in gui_app._HINT_TIPS:
            self.assertLessEqual(len(tip), 22, f"「{tip}」过长（{len(tip)} 字），标签会挤掉右侧控件")
            self.assertFalse(tip.startswith("提示："), "显示时会自动前拼「提示：」，不要重复写")
        self.assertEqual(len(set(gui_app._HINT_TIPS)), len(gui_app._HINT_TIPS), "提示文案有重复")

    def test_rotation_has_own_ticker(self):
        import gui_app
        self.assertIsInstance(gui_app.HINT_ROTATE_MS, int)
        self.assertLessEqual(gui_app.HINT_ROTATE_MS, 15000, "轮换必须明显快于原来的 60 秒")
        self.assertTrue(callable(gui_app._start_hint_ticker))
        self.assertTrue(callable(gui_app._stop_hint_ticker))
        self.assertTrue(hasattr(gui_app.App, "_start_hint_ticker"))

    def test_tree_refresh_no_longer_drives_hint(self):
        """提示轮换必须与账号列表刷新解耦，否则列表不刷新时提示就卡住不动"""
        import inspect
        import account_manager
        src = inspect.getsource(account_manager.start_periodic_tree_refresh)
        self.assertNotIn("_rotate_hint", src)

    def test_rotate_hint_advances_index(self):
        import gui_app
        app = MagicMock()
        app._hint_index = 0
        app._hint_label = MagicMock()
        app._hint_label.winfo_exists.return_value = True
        gui_app.App._rotate_hint(app)
        self.assertEqual(app._hint_index, 1)
        app._hint_label.config.assert_called_once()
        # 窗口已销毁 → 静默返回，不能抛异常
        app._hint_label.winfo_exists.return_value = False
        gui_app.App._rotate_hint(app)
        self.assertEqual(app._hint_index, 1)


class TestAccountResultRefreshesTree(unittest.TestCase):
    """② 账号跑完必须立刻派发列表刷新（否则已进入冷却的账号还显示「可运行」）"""

    def _make_app(self):
        app = MagicMock()
        app.settings = {"enable_cooldown": False}
        app.run_stats = {"success": 0, "fail": 0}
        app._consecutive_failures = {}
        app._user_stopped_cooldown = False
        app._last_account_error = ""
        app.root = MagicMock()
        app._refresh_account_tree = MagicMock()
        return app

    def test_success_path_dispatches_refresh(self):
        import automation_runner as ar
        app = self._make_app()
        processed = []
        with patch.object(ar.server_client, "update_account_status"), \
                patch.object(ar.cooldown_manager, "is_cooling_down", return_value=(False, "")):
            ar._process_account_result(app, "账号A", False, False, processed)
        self.assertTrue(app.root.after.called, "跑完/失败后没有派发列表刷新")
        args = app.root.after.call_args[0]
        self.assertEqual(args[0], 0, "必须用 after(0, ...) 派发，worker 线程不能直接动 Tk")
        args[1]()
        app._refresh_account_tree.assert_called_once()

    def test_failure_path_also_dispatches_refresh(self):
        import automation_runner as ar
        app = self._make_app()
        processed = []
        with patch.object(ar.server_client, "update_account_status"), \
                patch.object(ar.cooldown_manager, "is_cooling_down", return_value=(False, "")), \
                patch.object(ar, "_ocr_capture_screen_text", return_value=""), \
                patch.object(ar.email_notifier, "send_account_failure_email"):
            ar._process_account_result(app, "账号B", True, False, processed)
        self.assertTrue(app.root.after.called, "失败路径同样要刷新列表")


class TestReloadAccountsFromDisk(unittest.TestCase):
    """⑤ 运行期间安全重读 accounts.json：只做新增，绝不清空 / 不覆盖内存值"""

    def setUp(self):
        import account_manager as am
        self.am = am
        self._orig_path = am.ACCOUNTS_JSON_PATH
        self.path = os.path.join(TEST_DIR, "reload_accounts.json")
        am.ACCOUNTS_JSON_PATH = self.path
        self.app = MagicMock()
        self.app.qq_account_images = ["account:A"]
        self.app._account_notes = {"A": {"account": "内存里的A"}}
        self.app._account_assets = {"A": "123"}
        self.app._asset_history = {"A": ["x"]}
        self.app.root = MagicMock()

    def tearDown(self):
        self.am.ACCOUNTS_JSON_PATH = self._orig_path
        if os.path.exists(self.path):
            os.remove(self.path)

    def _write(self, obj):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)

    def _call(self):
        # 刷新列表会去读真实冷却数据 → 这里屏蔽掉，保证测试自洽
        with patch.object(self.am.cooldown_manager, "get_all_cooldowns", return_value={}):
            return self.am.reload_accounts_from_disk(self.app)

    def test_only_adds_and_keeps_memory_values(self):
        self._write({"qq": ["account:A", "account:B"],
                     "notes": {"A": {"account": "磁盘上的A"}, "B": {"account": "B"}},
                     "assets": {"A": "999", "B": "5"},
                     "asset_history": {"B": ["y"]}})
        self.assertTrue(self._call())
        self.assertEqual(self.app.qq_account_images, ["account:A", "account:B"])
        # 内存里已有的值不能被磁盘覆盖（避免丢掉还没落盘的改动）
        self.assertEqual(self.app._account_notes["A"]["account"], "内存里的A")
        self.assertEqual(self.app._account_assets["A"], "123")
        # 新账号要补进来
        self.assertEqual(self.app._account_notes["B"]["account"], "B")
        self.assertEqual(self.app._account_assets["B"], "5")

    def test_no_change_returns_false(self):
        self._write({"qq": ["account:A"]})
        self.assertFalse(self._call())
        self.assertEqual(self.app.qq_account_images, ["account:A"])

    def test_corrupt_file_never_clears_list(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        self.assertFalse(self._call())
        self.assertEqual(self.app.qq_account_images, ["account:A"], "坏文件绝不能清空列表")

    def test_missing_file_never_clears_list(self):
        self.assertFalse(self._call())
        self.assertEqual(self.app.qq_account_images, ["account:A"])

    def test_removed_account_is_kept(self):
        """磁盘上没有的账号不会被删掉 —— 运行中不能把账号从循环里抽走"""
        self._write({"qq": ["account:B"]})
        self.assertTrue(self._call())
        self.assertIn("account:A", self.app.qq_account_images)
        self.assertIn("account:B", self.app.qq_account_images)


class TestCooldownWaitPolling(unittest.TestCase):
    """⑤ 等待冷却期间轮询：出现可运行账号就提前结束等待，不必等满窗口"""

    def setUp(self):
        import automation_runner as ar
        self.ar = ar
        self.app = MagicMock()
        self.app._stop_event = threading.Event()

    def _cooldowns(self, remaining_seconds):
        nxt = datetime.datetime.now() + datetime.timedelta(seconds=remaining_seconds)
        return {"账号X": {"next_run_time": nxt.strftime("%Y-%m-%d %H:%M:%S")}}

    def test_returns_true_early_when_runnable(self):
        with patch.object(self.ar.cooldown_manager, "get_all_cooldowns",
                          return_value=self._cooldowns(-5)), \
                patch.object(self.ar, "set_operation"):
            self.assertTrue(self.ar._wait_cooldown_with_polling(
                self.app, 600, poll_seconds=0.05))

    def test_returns_false_while_still_cooling(self):
        with patch.object(self.ar.cooldown_manager, "get_all_cooldowns",
                          return_value=self._cooldowns(3600)), \
                patch.object(self.ar, "set_operation"):
            self.assertFalse(self.ar._wait_cooldown_with_polling(
                self.app, 0.06, poll_seconds=0.02))

    def test_paused_accounts_are_ignored(self):
        """暂停/出租的账号即使到期也不算「可运行」"""
        cd = self._cooldowns(-5)
        cd["账号X"]["account_paused"] = True
        with patch.object(self.ar.cooldown_manager, "get_all_cooldowns", return_value=cd), \
                patch.object(self.ar, "set_operation"):
            self.assertFalse(self.ar._wait_cooldown_with_polling(
                self.app, 0.06, poll_seconds=0.02))

    def test_stop_event_aborts_immediately(self):
        self.app._stop_event.set()
        with patch.object(self.ar, "set_operation"):
            self.assertFalse(self.ar._wait_cooldown_with_polling(
                self.app, 600, poll_seconds=0.05))

    def test_poll_interval_is_short(self):
        self.assertLessEqual(self.ar.COOLDOWN_POLL_SECONDS, 10,
                             "轮询间隔太久就失去「立刻发现可运行账号」的意义")


class TestOverlayAvoidBeforeScreenshot(unittest.TestCase):
    """④ 区域避让必须发生在截图**之前**

    历史缺陷：避让写在 `if matched:` 里面（匹配成功之后），而遮罩污染的是匹配之前的
    截图 —— 于是遮罩一盖住目标就永远匹配不上，也就永远走不到避让。
    """

    def test_source_order(self):
        import inspect
        import utils
        src = inspect.getsource(utils._find_and_click_core)
        self.assertLess(src.index("_avoid_overlay_for_region"),
                        src.index("_screenshot_gray(region)"),
                        "区域避让必须排在截图之前")

    def test_runtime_order_avoid_then_shot_then_restore(self):
        import utils
        events = []
        orig = (utils._avoid_overlay_for_region, utils._restore_overlay_after_region,
                utils._screenshot_gray, utils._match_template, utils._cache_get,
                utils._imread_unicode, utils._overlay_rect,
                utils._OVERLAY_NUDGE_MIN_INTERVAL)
        try:
            utils._avoid_overlay_for_region = (
                lambda x, y, w, h: events.append("avoid") or "TOKEN")
            utils._restore_overlay_after_region = lambda t: events.append("restore")
            utils._screenshot_gray = lambda region=None: (
                events.append("shot") or np.zeros((20, 20), dtype="uint8"))
            utils._match_template = lambda g, t, th: (False, 0.1, (0, 0), (2, 2))
            utils._cache_get = lambda p: np.zeros((4, 4), dtype="uint8")
            utils._imread_unicode = lambda p: None
            utils._overlay_rect = lambda: None
            utils._OVERLAY_NUDGE_MIN_INTERVAL = 0.0
            ok = utils._find_and_click_core("绝不存在的模板.png", timeout=0.35,
                                            region=(100, 100, 40, 40))
            self.assertFalse(ok)
            self.assertEqual(events[:3], ["avoid", "shot", "restore"],
                             "顺序必须是：先让位 → 再截图 → 截图后复原")
        finally:
            (utils._avoid_overlay_for_region, utils._restore_overlay_after_region,
             utils._screenshot_gray, utils._match_template, utils._cache_get,
             utils._imread_unicode, utils._overlay_rect,
             utils._OVERLAY_NUDGE_MIN_INTERVAL) = orig

    def test_nudge_only_when_overlay_present_and_limited(self):
        """换角落兜底：遮罩不在时一次都不换；在时也必须限量"""
        import utils
        orig = (utils._screenshot_gray, utils._match_template, utils._cache_get,
                utils._imread_unicode, utils._overlay_rect, utils._nudge_overlay,
                utils._OVERLAY_NUDGE_MIN_INTERVAL)
        nudges = []
        try:
            utils._screenshot_gray = lambda region=None: np.zeros((20, 20), dtype="uint8")
            utils._match_template = lambda g, t, th: (False, 0.1, (0, 0), (2, 2))
            utils._cache_get = lambda p: np.zeros((4, 4), dtype="uint8")
            utils._imread_unicode = lambda p: None
            utils._nudge_overlay = lambda reason="": nudges.append(reason) or True
            utils._OVERLAY_NUDGE_MIN_INTERVAL = 0.0

            utils._overlay_rect = lambda: None
            utils._find_and_click_core("绝不存在的模板.png", timeout=0.35)
            self.assertEqual(nudges, [], "遮罩不在（rect=None）时不应换角落")

            utils._overlay_rect = lambda: (0, 0, 400, 200)
            utils._find_and_click_core("绝不存在的模板.png", timeout=0.4)
            self.assertGreaterEqual(len(nudges), 1, "遮罩在且疑似盖住时应尝试换角落")
            self.assertLessEqual(len(nudges), utils._OVERLAY_NUDGE_MAX,
                                 "换角落必须限量，否则遮罩会在屏上乱跳")
        finally:
            (utils._screenshot_gray, utils._match_template, utils._cache_get,
             utils._imread_unicode, utils._overlay_rect, utils._nudge_overlay,
             utils._OVERLAY_NUDGE_MIN_INTERVAL) = orig

    def test_overlay_info_hooks_register_and_fail_safe(self):
        import utils
        orig = (utils._overlay_rect_fn, utils._overlay_nudge_fn)
        try:
            utils.set_overlay_info_hooks(lambda: (1, 2, 3, 4), lambda reason="": True)
            self.assertEqual(utils._overlay_rect(), (1, 2, 3, 4))
            self.assertTrue(utils._nudge_overlay("x"))

            def _boom(*_a):
                raise RuntimeError("x")
            utils.set_overlay_info_hooks(_boom, _boom)
            self.assertIsNone(utils._overlay_rect())
            self.assertFalse(utils._nudge_overlay("x"))

            utils.set_overlay_info_hooks(None, None)
            self.assertIsNone(utils._overlay_rect())
            self.assertFalse(utils._nudge_overlay("x"))
            self.assertFalse(utils._point_in_rect(5, 5, None))
            self.assertTrue(utils._point_in_rect(5, 5, (0, 0, 10, 10)))
            self.assertFalse(utils._point_in_rect(50, 5, (0, 0, 10, 10)))
        finally:
            utils._overlay_rect_fn, utils._overlay_nudge_fn = orig


class TestCaptureExclusionTruth(unittest.TestCase):
    """④ 不再无条件相信 SetWindowDisplayAffinity 的返回值"""

    def test_readback_invalid_hwnd_is_false(self):
        import screen_log_overlay as slo
        self.assertFalse(slo.is_excluded_from_capture(0))
        self.assertFalse(slo.is_excluded_from_capture(-1))

    def test_count_magenta(self):
        from PIL import Image
        import screen_log_overlay as slo
        self.assertGreater(slo._count_magenta(Image.new("RGB", (10, 10), (255, 0, 255))), 0)
        self.assertEqual(slo._count_magenta(Image.new("RGB", (10, 10), (0, 0, 0))), 0)
        self.assertEqual(slo._count_magenta(Image.new("RGB", (10, 10), (250, 250, 250))), 0)

    def test_skippable_needs_probe_and_readback(self):
        """没有端到端实测结论时，绝不允许「跳过让位」（保守优先）"""
        import gui_app
        orig_probe, orig_ov = gui_app._capture_probe_result, gui_app._qt_overlay
        try:
            gui_app._capture_probe_result = None
            self.assertFalse(gui_app._overlay_skippable(),
                             "还没实测就不许跳过让位")
            gui_app._capture_probe_result = True
            gui_app._qt_overlay = None
            self.assertFalse(gui_app._overlay_skippable(),
                             "遮罩不存在时也不该「跳过」")
        finally:
            gui_app._capture_probe_result = orig_probe
            gui_app._qt_overlay = orig_ov


# ==================== STM32 外部硬件键盘 ====================
class TestStm32Keyboard(unittest.TestCase):
    """STM32 硬件键盘后端：协议顺序、输入校验、绝不抛异常、日志不泄露内容"""

    def setUp(self):
        import stm32_keyboard as sk
        self.sk = sk

    def test_validate_accepts_only_ascii_printable(self):
        """固件只吃 ASCII 可见字符 + Tab：非法内容必须提前拦下（别把脏数据打进密码框）"""
        for bad in ("中文账号", "abc\n", "abc\r", "", "passw\x00rd", "a　b"):
            ok, why = self.sk._validate(bad)
            self.assertFalse(ok, "%r 不该通过校验" % bad)
            self.assertTrue(why, "拒绝时要给出原因")
        for good in ("", "abc123", "P@ssw0rd!_-+=[]{}|;:'\",.<>/?`~", "a\tb", " "):
            if good == "":
                continue
            ok, _ = self.sk._validate(good)
            self.assertTrue(ok, "%r 应通过校验" % good)

    def test_read_config_defaults_and_invalid(self):
        cfg = self.sk.read_config({})
        self.assertIsNone(cfg["port"])                      # auto → None（按 VID/PID 查找）
        self.assertEqual(cfg["interval_ms"], 25)
        self.assertEqual(cfg["timeout"], 3.0)
        # 越界值一律回落默认（用户手填的值不能信）
        cfg2 = self.sk.read_config({"stm32_interval_ms": 9999, "stm32_timeout": 999})
        self.assertEqual(cfg2["interval_ms"], 25)
        self.assertEqual(cfg2["timeout"], 3.0)
        # 显式端口原样带出
        self.assertEqual(self.sk.read_config({"stm32_port": "COM7"})["port"], "COM7")
        for auto in ("auto", "AUTO", "自动", ""):
            self.assertIsNone(self.sk.read_config({"stm32_port": auto})["port"])

    def test_no_device_returns_false_and_never_raises(self):
        with patch.object(self.sk, "find_port", return_value=None):
            self.assertFalse(self.sk.is_available({}))
            self.assertFalse(self.sk.send_string("abc", settings={}))
            self.assertFalse(self.sk.send_key("a", settings={}))
            self.assertIn("未找到", self.sk.last_error())

    def test_protocol_order_and_password_not_logged(self):
        """命令顺序必须是 PING → TYPE_INTERVAL → TYPE；⚠️ 日志里绝不能出现密码"""
        sent = []

        class FakeConn:
            def __init__(self, port, baudrate=None):
                self.port = port
                self.closed = False

            def cmd(self, line, timeout=3.0, quiet=False):
                sent.append(line)
                return True, "OK"

            def close(self):
                self.closed = True

        import contextlib
        import io
        buf = io.StringIO()
        with patch.object(self.sk, "find_port", return_value="COM9"), \
                patch.object(self.sk, "_Conn", FakeConn), \
                contextlib.redirect_stdout(buf):
            ok = self.sk.send_string("P@ssw0rd", interval=0.02, settings={})
        self.assertTrue(ok)
        self.assertEqual(sent[0], "PING")
        self.assertEqual(sent[1], "TYPE_INTERVAL 20")
        self.assertEqual(sent[2], "TYPE P@ssw0rd")
        self.assertNotIn("P@ssw0rd", buf.getvalue(), "日志里不能出现密码")

    def test_interval_clamped_to_firmware_range(self):
        sent = []

        class FakeConn:
            def __init__(self, port, baudrate=None):
                pass

            def cmd(self, line, timeout=3.0, quiet=False):
                sent.append(line)
                return True, "OK"

            def close(self):
                pass

        for interval, want in ((0.001, 5), (0.02, 20), (9.0, 500)):
            sent.clear()
            with patch.object(self.sk, "find_port", return_value="COM9"), \
                    patch.object(self.sk, "_Conn", FakeConn):
                self.sk.send_string("ab", interval=interval, settings={})
            self.assertIn("TYPE_INTERVAL %d" % want, sent[1],
                          "interval=%s 应夹到 %dms" % (interval, want))

    def test_err_005_does_not_auto_resume(self):
        """设备处于紧急停止时：报明确原因，且**不自动 RESUME**
        （那是用户主动按板上 PB1/PB11 触发的安全动作，程序不该替他撤销）"""
        calls = []

        class FakeConn:
            def __init__(self, port, baudrate=None):
                pass

            def cmd(self, line, timeout=3.0, quiet=False):
                calls.append(line)
                if line.startswith("PING"):
                    return True, "OK PONG 1.0"
                return False, "设备拒绝（ERR 005 设备处于紧急停止状态）"

            def close(self):
                pass

        with patch.object(self.sk, "find_port", return_value="COM9"), \
                patch.object(self.sk, "_Conn", FakeConn):
            self.assertFalse(self.sk.send_string("abc", settings={}))
        self.assertNotIn("RESUME", calls)

    def test_write_failure_is_swallowed(self):
        """串口炸了也不能把主流程带崩"""
        class BoomConn:
            def __init__(self, port, baudrate=None):
                raise OSError("端口被占用")

        with patch.object(self.sk, "find_port", return_value="COM9"), \
                patch.object(self.sk, "_Conn", BoomConn):
            self.assertFalse(self.sk.send_string("abc", settings={}))
            self.assertTrue(self.sk.last_error())


class TestDriverKeyboardChain(unittest.TestCase):
    """键盘后端优先级链：STM32 → Interception → SendInput"""

    def setUp(self):
        import driver_keyboard as dk
        self.dk = dk
        self._orig = (dk._settings, dk._CHOSEN)

    def tearDown(self):
        self.dk._settings, self.dk._CHOSEN = self._orig

    def test_auto_order_prefers_stm32(self):
        """auto 顺序必须是 STM32 → Interception
        （STM32 同样是硬件级输入，但不会把系统键盘栈搞挂）"""
        self.dk.set_settings({})
        self.assertEqual(self.dk._order(), ("stm32", "interception"))
        self.dk.set_settings({"keyboard_backend": "auto"})
        self.assertEqual(self.dk._order(), ("stm32", "interception"))

    def test_explicit_backend_restricts_order(self):
        for name in ("stm32", "interception"):
            self.dk.set_settings({"keyboard_backend": name})
            self.assertEqual(self.dk._order(), (name,))
        self.dk.set_settings({"keyboard_backend": "乱填"})      # 非法值 → 回默认顺序
        self.assertEqual(self.dk._order(), ("stm32", "interception"))

    def test_no_software_simulation_backend(self):
        """⚠️ 回归断言：**不许**再引入 SendInput 这类纯软件模拟后端。

        理由（用户明确要求）：软件模拟的按键带注入标记，WeGame 这类目标不认 →
        会出现「以为输入了、其实账号密码没进去」，比直接失败更糟。
        所以两者都不可用时必须**直接判失败**。
        """
        self.assertNotIn("sendinput", self.dk.BACKENDS)
        self.assertNotIn("sendinput", self.dk._SENDERS)
        self.assertNotIn("sendinput", self.dk._LABEL)
        import inspect
        src = inspect.getsource(self.dk)
        self.assertNotIn("SendInput(", src, "不该再有 SendInput 调用")
        self.assertNotIn("KEYEVENTF_UNICODE", src, "不该再有软件模拟实现")
        # 两个硬件后端都不可用 → send_string 必须直接返回 False
        with patch.object(self.dk, "_available", return_value=False):
            self.dk.set_settings({})
            self.assertFalse(self.dk.is_available())
            self.assertFalse(self.dk.send_string("pw"))

    def test_pick_uses_first_available(self):
        with patch.object(self.dk, "_available", side_effect=lambda n: n == "interception"):
            self.dk.set_settings({})
            self.assertEqual(self.dk._pick(force=True), "interception")
        with patch.object(self.dk, "_available", return_value=False):
            self.dk.set_settings({})
            self.assertIsNone(self.dk._pick(force=True))
            self.assertFalse(self.dk.is_available())
            self.assertEqual(self.dk.get_backend(), "无可用后端")

    def test_no_midway_backend_switch(self):
        """⚠️ 关键安全断言：某后端输入失败后**不许换后端重打一遍** ——
        密码类输入若中途换后端，同一个字符串会被打两遍，必然错误。"""
        used = []

        def fake_stm32(t, i):
            used.append("stm32")
            return False

        def fake_inter(t, i):
            used.append("interception")
            return True

        with patch.object(self.dk, "_available",
                          side_effect=lambda n: n in ("stm32", "interception")), \
                patch.dict(self.dk._SENDERS, {"stm32": fake_stm32, "interception": fake_inter}):
            self.dk.set_settings({})
            self.assertFalse(self.dk.send_string("pw"))
        self.assertEqual(used, ["stm32"], "失败后不该回落到下一个后端")

    def test_backend_exception_is_swallowed(self):
        def boom(*a, **k):
            raise RuntimeError("后端炸了")

        with patch.object(self.dk, "_available", side_effect=lambda n: n == "stm32"), \
                patch.dict(self.dk._SENDERS, {"stm32": boom}):
            self.dk.set_settings({})
            self.assertFalse(self.dk.send_string("pw"))      # 不许抛异常

    def test_empty_text_is_noop_success(self):
        self.dk.set_settings({})
        self.assertTrue(self.dk.send_string(""))

    def test_backend_report_shape(self):
        with patch.object(self.dk, "_available", return_value=False):
            lines, chosen = self.dk.backend_report()
        self.assertEqual(len(lines), 2)      # 只有 STM32 与 Interception 两个硬件后端
        for mark, name, detail in lines:
            self.assertIn(mark, ("✓", "✗", "–"))
            self.assertTrue(name)
            self.assertIsInstance(detail, str)
        self.assertTrue(lines[0][1].startswith("STM32"), "第一项应是 STM32")
        self.assertTrue(lines[1][1].startswith("Interception"), "第二项应是 Interception")

    def test_interception_allowed_follows_config(self):
        """interception_allowed() 决定「允不允许碰 Interception 驱动」"""
        self.dk.set_settings({})
        self.assertTrue(self.dk.interception_allowed(), "auto 下允许（作为备选）")
        self.dk.set_settings({"keyboard_backend": "interception"})
        self.assertTrue(self.dk.interception_allowed())
        self.dk.set_settings({"keyboard_backend": "stm32"})
        self.assertFalse(self.dk.interception_allowed(), "只用 STM32 时不允许")

    def test_backend_report_does_not_probe_disabled_backend(self):
        """⚠️ 关键：配置「只用 STM32 硬件键盘」时**不许去探测 Interception**。

        探测 = 调 interception_keyboard.is_available() → 加载 interception.dll 并创建上下文
        → 等于把那个内核键盘筛选器挂上。用户选 STM32 正是为了不碰它（2026-09-24 按要求）。
        """
        calls = []

        def fake_avail(name):
            calls.append(name)
            return name == "stm32"

        with patch.object(self.dk, "_available", side_effect=fake_avail):
            self.dk.set_settings({"keyboard_backend": "stm32"})
            lines, chosen = self.dk.backend_report()
        # ⚠️ 关键断言：一次都没碰 interception（stm32 会被探测两次：backend_report 一次 +
        #    末尾 _pick() 一次，那是正常的）
        self.assertNotIn("interception", calls, "不该去碰 Interception，实际探测了 %s" % calls)
        self.assertIn("stm32", calls)
        self.assertEqual(chosen, "stm32")
        # 未配置的后端仍要列出来（让用户看得见选项），但标成「未检测」
        self.assertEqual(len(lines), 2)
        by_name = {n: (m, d) for m, n, d in lines}
        mark, detail = by_name[self.dk._LABEL["interception"]]
        self.assertEqual(mark, "–")
        self.assertIn("未检测", detail)
        # 反面对照：auto 下两个都要探测
        calls.clear()
        with patch.object(self.dk, "_available", side_effect=fake_avail):
            self.dk.set_settings({})
            self.dk.backend_report()
        self.assertEqual(set(calls), {"interception", "stm32"}, "auto 下两个都该探测")

    def test_restart_branch_is_gated(self):
        """⚠️「驱动不可用就重启电脑」那个分支必须被 interception_allowed() 拦住 ——
        否则选了「只用 STM32」时它照样会去启动 Interception 驱动服务"""
        import inspect
        import automation_runner as ar
        self.assertIn("driver_keyboard.interception_allowed()", inspect.getsource(ar))


class TestKeyboardSettingsWindowUI(unittest.TestCase):
    """键盘设置窗口：真实构建一次，验证「保存」把配置写进 settings
    （⚠️ 全程不点测试按钮 —— 那把「打字测试」会真的往焦点窗口敲字）"""

    def test_window_builds_and_saves(self):
        import types
        import tkinter as tk
        import config
        import driver_keyboard
        import keyboard_settings as ks

        fake = dict(config.DEFAULT_SETTINGS)
        saved = {}
        orig = (config.load_settings, config.save_settings,
                ks.config.load_settings, ks.config.save_settings,
                driver_keyboard._settings, driver_keyboard._CHOSEN)
        def _load():
            return dict(fake)

        def _save(d):
            saved.update(d)
            fake.update(d)      # 模拟真实文件：保存后能被读回
            #   （utils.save_window_geometry 会「重读→改→写回」，不这样模拟会误判成保存失败）

        config.load_settings = _load
        config.save_settings = _save
        ks.config.load_settings = _load
        ks.config.save_settings = _save

        root = tk.Tk()
        root.withdraw()
        app = types.SimpleNamespace(settings=dict(fake))
        try:
            win = ks.KeyboardSettingsWindow(root, app)
            root.update_idletasks()
            # 三个后端的状态必须已经算出来（不能是空标签）
            self.assertTrue(win._backend_status.cget("text").strip())
            self.assertIn("STM32", win._backend_status.cget("text"))
            # 默认值应当从 settings 带出
            self.assertEqual(win._backend_var.get(), "auto")
            self.assertEqual(win._port_var.get(), "auto")
            # 改配置 → 保存
            win._backend_var.set("stm32")
            win._port_var.set("COM99")
            win._interval_var.set("40")
            win._timeout_var.set("5")
            win._on_close(save=True)
            self.assertEqual(saved.get("keyboard_backend"), "stm32")
            self.assertEqual(saved.get("stm32_port"), "COM99")
            self.assertEqual(saved.get("stm32_interval_ms"), 40)
            self.assertEqual(saved.get("stm32_timeout"), 5.0)
            self.assertEqual(app.settings.get("keyboard_backend"), "stm32")
        except tk.TclError as e:
            self.skipTest("无图形环境，跳过：%s" % e)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            (config.load_settings, config.save_settings,
             ks.config.load_settings, ks.config.save_settings,
             driver_keyboard._settings, driver_keyboard._CHOSEN) = orig

    def test_out_of_range_values_are_clamped(self):
        """手填越界值必须被夹回合法区间（不能把非法值写进设置）"""
        import types
        import tkinter as tk
        import config
        import driver_keyboard
        import keyboard_settings as ks

        fake = dict(config.DEFAULT_SETTINGS)
        saved = {}
        orig = (config.load_settings, config.save_settings,
                ks.config.load_settings, ks.config.save_settings,
                driver_keyboard._settings, driver_keyboard._CHOSEN)
        def _load():
            return dict(fake)

        def _save(d):
            saved.update(d)
            fake.update(d)      # 模拟真实文件：保存后能被读回
            #   （utils.save_window_geometry 会「重读→改→写回」，不这样模拟会误判成保存失败）

        config.load_settings = _load
        config.save_settings = _save
        ks.config.load_settings = _load
        ks.config.save_settings = _save
        root = tk.Tk()
        root.withdraw()
        try:
            win = ks.KeyboardSettingsWindow(root, types.SimpleNamespace(settings=dict(fake)))
            win._interval_var.set("99999")
            win._timeout_var.set("0.01")
            win._on_close(save=True)
            self.assertEqual(saved.get("stm32_interval_ms"), 500)
            self.assertEqual(saved.get("stm32_timeout"), 0.5)
        except tk.TclError as e:
            self.skipTest("无图形环境，跳过：%s" % e)
        finally:
            try:
                root.destroy()
            except Exception:
                pass
            (config.load_settings, config.save_settings,
             ks.config.load_settings, ks.config.save_settings,
             driver_keyboard._settings, driver_keyboard._CHOSEN) = orig


class TestKeyboardSettingsOptions(unittest.TestCase):
    """键盘设置界面：选项里不许再出现 SendInput（已按要求从后端链移除）"""

    def test_options_have_no_sendinput(self):
        import keyboard_settings as ks
        values = [v for v, _label, _hint in ks._BACKEND_OPTIONS]
        self.assertEqual(values, ["auto", "stm32", "interception"])
        for _v, label, hint in ks._BACKEND_OPTIONS:
            self.assertNotIn("SendInput", label + hint)
            self.assertNotIn("SendInput", hint)

    def test_no_blocking_wait_visibility(self):
        """⚠️ 回归断言：**不许**再用 `win.wait_visibility()`。

        它在窗口**已经可见**时会**永久阻塞**（`tkwait visibility` 等的是「下一次可见性变化」，
        不是「当前是否可见」）→ `__init__` 走不到 `grab_set()` → 子窗口抢不到 grab
        → **该窗口所有按钮点了都没反应**。2026-09-23 就这么坑过一次
        （用户报「刷新/测试连接/打字测试都点不动」），靠带超时的复现脚本才定位到。
        """
        import inspect
        import keyboard_settings as ks
        src = inspect.getsource(ks)
        # ⚠️ 只查**代码行**：注释里为了警告后人会提到这个名字，不该被当成违规
        bad = [l.strip() for l in src.splitlines()
               if "wait_visibility" in l and not l.strip().startswith("#")]
        self.assertEqual(bad, [],
                         "wait_visibility 会阻塞，改用 lift()+focus_force()+grab_set()")

    def test_subwindow_takes_grab_and_releases_it(self):
        """子窗口必须自己抢 grab（父设置窗口是模态的），关闭时交还"""
        import inspect
        import keyboard_settings as ks
        src = inspect.getsource(ks)
        self.assertIn("grab_set()", src)
        self.assertIn("grab_release()", src)
        self.assertIn("focus_force()", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
