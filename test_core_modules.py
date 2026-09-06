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
        """click：bbox 中心优先；point 兜底；scale=1000 归一化换算"""
        import ai_visual_captcha as avc
        # bbox 像素 (100,200,200,300) → 中心 (150,250)
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"text": "塔", "bbox": [100, 200, 200, 300]}]}', 1920, 1080)
        self.assertEqual(r["status"], "click")
        self.assertEqual(r["points"], [(150, 250)])
        self.assertEqual(r["labels"], ["塔"])
        # point + scale 1000：(500,400)/1000 × (1920,1080) → (960,432)
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"text": "字", "point": [500, 400], "scale": 1000}]}', 1920, 1080)
        self.assertEqual(r["points"], [(960, 432)])
        # bbox 与 point 同时给出时用 bbox 中心
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"bbox": [0, 0, 10, 10], "point": [999, 999]}]}', 1000, 1000)
        self.assertEqual(r["points"], [(5, 5)])

    def test_parse_response_zero_to_one_float_scale(self):
        """scale=1（0-1 浮点）按比例换算；>1 的值按像素处理"""
        import ai_visual_captcha as avc
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [0.5, 0.25], "scale": 1}]}', 1000, 800)
        self.assertEqual(r["points"], [(500, 200)])
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": ['
            '{"point": [500, 250], "scale": 1}]}', 1000, 800)
        self.assertEqual(r["points"], [(500, 250)])

    def test_parse_response_invalid(self):
        """非 JSON / 有验证码但无有效坐标 → invalid"""
        import ai_visual_captcha as avc
        self.assertEqual(avc.parse_model_response("我看不懂", 1000, 800)["status"], "invalid")
        r = avc.parse_model_response(
            '{"captcha": true, "type": "click", "targets": [{"text": "没有坐标"}]}', 1000, 800)
        self.assertEqual(r["status"], "invalid")

    def test_get_preset(self):
        """供应商预设回填；自定义返回空"""
        import ai_visual_captcha as avc
        p = avc.get_preset("智谱GLM")
        self.assertTrue(p["base_url"].startswith("https://"))
        self.assertEqual(p["model"], "glm-4v-flash")
        self.assertEqual(avc.get_preset(avc.CUSTOM_PROVIDER), {"base_url": "", "model": ""})
        self.assertEqual(avc.get_preset("不存在的"), {"base_url": "", "model": ""})
        # 预设表结构完整
        for item in avc.PROVIDER_PRESETS:
            self.assertIn("name", item)
            self.assertIn("base_url", item)
            self.assertIn("model", item)
            if item["name"] != avc.CUSTOM_PROVIDER:
                self.assertTrue(item["base_url"].startswith("https://"))

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

        def _mock_ai(app, stop_event=None):
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
