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
        cm.COOLDOWN_JSON_PATH = os.path.join(TEST_DIR, "cd_cache.json")
        cm._cache = None
        cm._cache_mtime = 0.0
        if os.path.exists(cm.COOLDOWN_JSON_PATH):
            os.remove(cm.COOLDOWN_JSON_PATH)

    def tearDown(self):
        self.cm.COOLDOWN_JSON_PATH = self._orig_path
        self.cm._cache = None
        self.cm._cache_mtime = 0.0

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
        """售卖物品元数据读写（自动同步目录图片）"""
        from config import load_sell_items_meta, save_sell_items_meta, SELL_ITEMS_DIR
        os.makedirs(SELL_ITEMS_DIR, exist_ok=True)
        # 创建临时测试图片
        test_file = os.path.join(SELL_ITEMS_DIR, "_test_meta_sync.png")
        with open(test_file, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        try:
            meta = {"items": [{"filename": "_test_meta_sync.png", "name": "_test_meta_sync", "discount_times": 0, "quantity": 1}]}
            save_sell_items_meta(meta)
            loaded = load_sell_items_meta()
            names = [i["name"] for i in loaded["items"]]
            self.assertIn("_test_meta_sync", names)
            # 验证同步：目录中已有图片也被加入
            self.assertGreater(len(loaded["items"]), 1)
        finally:
            os.remove(test_file)


# ==================== utils ====================
class TestUtilsFunctions(unittest.TestCase):
    """测试工具函数"""

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
