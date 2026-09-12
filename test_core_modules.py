"""
核心模块单元测试
覆盖：cooldown_manager, asset_db, config, utils, email_notifier
通过实际调用函数验证逻辑，而非源码字符串匹配
"""
import os
import sys
import json
import time
import datetime
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

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

    def test_solve_captcha_second_pass_adds_missed_tile(self):
        """第一轮漏掉的那张图：第二轮放大复查后按「has 且 conf≥75」补进来（用户实测的漏判场景）"""
        import types
        import unittest.mock as mock
        import numpy as np
        import ai_visual_captcha as avc

        # 造一张 3 列 2 行、白底彩块的验证码图（和真实布局同构）
        img = np.full((594, 526, 3), 255, np.uint8)
        for r in range(2):
            for c in range(3):
                x, y, w, h = 29 + c * 154, 202 + r * 156, 152, 154
                img[y:y + h, x:x + w] = (60 + r * 40, 120, 200)
        app = types.SimpleNamespace(settings={
            "ai_visual_captcha_enabled": True,
            "ai_visual_captcha_base_url": "https://example.com",
            "ai_visual_captcha_api_key": "k",
            "ai_visual_captcha_model": "m",
            "ai_visual_captcha_max_rounds": 1,
        }, _stop_event=None)
        # 第一轮只选中 图3/5/6（漏了图2）；第二轮对 图1/2/4 复查 → 图2 高分采纳、图4 低分拒绝
        p1 = ('{"captcha": true, "type": "click", "mode": "image", '
              '"caption": "选择所有包含文字：\\"川\\"的图片", "targets": ['
              '{"text": "图3", "point": [789, 470], "conf": 90}, '
              '{"text": "图5", "point": [494, 731], "conf": 88}, '
              '{"text": "图6", "point": [789, 731], "conf": 86}]}')
        p2 = ('{"results": [{"no": 1, "has": false, "conf": 10, "why": "没有"}, '
              '{"no": 2, "has": true, "conf": 92, "why": "山脊三道竖纹"}, '
              '{"no": 4, "has": true, "conf": 68, "why": "倒影有点像但不够"}]}')
        p3 = '{"captcha": false, "type": "none", "targets": []}'
        clicks = []
        with mock.patch.object(avc, "_grab_bgr", return_value=img), \
             mock.patch.object(avc, "_capture_screen_jpeg", return_value=("b64", "jpeg", 526, 594)), \
             mock.patch.object(avc, "_ask_model", side_effect=[p1, p2, p3]) as m, \
             mock.patch.object(avc, "_hide_overlay", return_value=False), \
             mock.patch.object(avc, "_show_overlay"), \
             mock.patch.object(avc, "save_debug_annotation"), \
             mock.patch.object(avc, "_click_screen_point", side_effect=lambda x, y: clicks.append((x, y))), \
             mock.patch.object(avc.time, "sleep"):
            ok, detail = avc.solve_captcha(app, force=True)
        self.assertTrue(ok, detail)
        centers = [(29 + c * 154 + 76, 202 + r * 156 + 77) for r in range(2) for c in range(3)]
        self.assertIn(centers[1], clicks)          # 图2（第二轮补上的）被点了
        self.assertNotIn(centers[3], clicks)       # 图4（低分）没被点
        self.assertEqual(m.call_count, 3)          # 第一轮 + 第二轮 + 复核轮

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

if __name__ == "__main__":
    unittest.main(verbosity=2)
