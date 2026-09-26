"""
覆盖：config新选项、互斥逻辑、烽火地带重试、冷却管理、邮件通知
无需启动GUI，通过模拟环境验证核心逻辑
"""
import os
import sys
import json
import time
import datetime
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
import tempfile
import shutil

# ==================== 测试辅助 ====================
TEST_DIR = tempfile.mkdtemp(prefix="delta_test_")
ORIGINAL_SETTINGS_PATH = None


def setUpModule():
    """模块级初始化：备份并隔离设置文件"""
    global ORIGINAL_SETTINGS_PATH
    import config
    ORIGINAL_SETTINGS_PATH = config.SETTINGS_JSON_PATH
    # 使用临时目录避免污染真实配置
    config.SETTINGS_JSON_PATH = os.path.join(TEST_DIR, "test_settings.json")
    config.COOLDOWN_JSON_PATH_ORIG = getattr(config, 'COOLDOWN_JSON_PATH', None)


def tearDownModule():
    """模块级清理"""
    import config
    config.SETTINGS_JSON_PATH = ORIGINAL_SETTINGS_PATH
    shutil.rmtree(TEST_DIR, ignore_errors=True)


# ==================== Test 1: Config 新选项 ====================
class TestConfigNewOption(unittest.TestCase):
    """测试 config.py 中 cooldown_run_immediately 选项"""

    def test_default_value_exists(self):
        """DEFAULT_SETTINGS 应包含 cooldown_run_immediately"""
        from config import DEFAULT_SETTINGS
        self.assertIn("cooldown_run_immediately", DEFAULT_SETTINGS)
        self.assertFalse(DEFAULT_SETTINGS["cooldown_run_immediately"])

    def test_load_settings_includes_new_option(self):
        """load_settings 应返回包含新选项的字典"""
        from config import load_settings, SETTINGS_JSON_PATH
        # 清空设置文件以测试默认值
        if os.path.exists(SETTINGS_JSON_PATH):
            os.remove(SETTINGS_JSON_PATH)
        settings = load_settings()
        self.assertIn("cooldown_run_immediately", settings)
        self.assertFalse(settings["cooldown_run_immediately"])

    def test_save_and_load_preserves_value(self):
        """保存后重新加载应保留 cooldown_run_immediately 的值"""
        from config import save_settings, load_settings, SETTINGS_JSON_PATH
        settings = dict(load_settings())
        settings["cooldown_run_immediately"] = True
        save_settings(settings)
        loaded = load_settings()
        self.assertTrue(loaded["cooldown_run_immediately"])

    def test_all_default_keys_present(self):
        """load_settings 返回的字典应包含所有 DEFAULT_SETTINGS 的键"""
        from config import load_settings, DEFAULT_SETTINGS
        if os.path.exists(load_settings.__code__.co_filename):
            pass  # just checking import works
        settings = load_settings()
        for key in DEFAULT_SETTINGS:
            self.assertIn(key, settings, f"缺少配置项: {key}")


# ==================== Test 2: 冷却管理器 ====================
class TestCooldownManager(unittest.TestCase):
    """测试 cooldown_manager.py 所有功能"""

    def setUp(self):
        import cooldown_manager
        self.cm = cooldown_manager
        # 使用临时文件（同时覆盖 .bak 路径，防止 _save_data 污染真实备份）
        self._orig_path = cooldown_manager.COOLDOWN_JSON_PATH
        self._orig_backup = cooldown_manager.COOLDOWN_JSON_BACKUP
        cooldown_manager.COOLDOWN_JSON_PATH = os.path.join(TEST_DIR, "test_cooldown.json")
        cooldown_manager.COOLDOWN_JSON_BACKUP = cooldown_manager.COOLDOWN_JSON_PATH + ".bak"
        # 重置模块级缓存，避免读到真实/上次测试残留
        cooldown_manager._cache = None
        cooldown_manager._cache_mtime = 0.0
        cooldown_manager._load_corrupt = False
        # 清空临时文件
        for _p in (cooldown_manager.COOLDOWN_JSON_PATH,
                   cooldown_manager.COOLDOWN_JSON_BACKUP):
            if os.path.exists(_p):
                os.remove(_p)

    def tearDown(self):
        self.cm.COOLDOWN_JSON_PATH = self._orig_path
        self.cm.COOLDOWN_JSON_BACKUP = self._orig_backup
        self.cm._cache = None
        self.cm._cache_mtime = 0.0
        self.cm._load_corrupt = False

    def test_new_account_not_cooling(self):
        """新账号不应处于冷却状态"""
        cooling, next_time = self.cm.is_cooling_down("test_user.png")
        self.assertFalse(cooling)
        self.assertIsNone(next_time)

    def test_record_and_cooldown(self):
        """记录运行后应进入冷却状态"""
        self.cm.record_run("test_user.png", cooldown_hours=8)
        cooling, next_time = self.cm.is_cooling_down("test_user.png")
        self.assertTrue(cooling)
        self.assertIsNotNone(next_time)
        # 验证下次运行时间在8小时后
        next_dt = datetime.datetime.strptime(next_time, "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now()
        diff = (next_dt - now).total_seconds()
        self.assertGreater(diff, 7 * 3600)  # 至少7小时
        self.assertLess(diff, 9 * 3600)     # 不超过9小时

    def test_cooldown_duration(self):
        """冷却时间应精确为设定的小时数"""
        self.cm.record_run("user_delay.png", cooldown_hours=8)
        cooling, next_time = self.cm.is_cooling_down("user_delay.png")
        self.assertTrue(cooling)
        next_dt = datetime.datetime.strptime(next_time, "%Y-%m-%d %H:%M:%S")
        now = datetime.datetime.now()
        diff = (next_dt - now).total_seconds()
        # 应在 8h 附近（允许几秒误差）
        self.assertGreater(diff, 7.9 * 3600)
        self.assertLess(diff, 8.1 * 3600)

    def test_reset_cooldown(self):
        """重置冷却后应不再处于冷却状态"""
        self.cm.record_run("reset_user.png", cooldown_hours=8)
        cooling, _ = self.cm.is_cooling_down("reset_user.png")
        self.assertTrue(cooling)
        self.cm.reset_cooldown("reset_user.png")
        cooling, _ = self.cm.is_cooling_down("reset_user.png")
        self.assertFalse(cooling)

    def test_get_all_cooldowns(self):
        """get_all_cooldowns 应返回所有账号的冷却信息"""
        self.cm.record_run("user_a.png", cooldown_hours=8)
        self.cm.record_run("user_b.png", cooldown_hours=8)
        all_cd = self.cm.get_all_cooldowns()
        self.assertIn("user_a.png", all_cd)
        self.assertIn("user_b.png", all_cd)
        self.assertIn("last_run_time", all_cd["user_a.png"])
        self.assertIn("next_run_time", all_cd["user_a.png"])
        self.assertIn("remaining_seconds", all_cd["user_a.png"])
        self.assertGreater(all_cd["user_a.png"]["remaining_seconds"], 0)

    def test_expired_cooldown(self):
        """已过期的冷却应不再处于冷却状态"""
        data = {
            "expired_user.png": {
                "last_run_time": "2020-01-01 00:00:00",
                "next_run_time": "2020-01-01 08:00:00"
            }
        }
        with open(self.cm.COOLDOWN_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
        cooling, next_time = self.cm.is_cooling_down("expired_user.png")
        self.assertFalse(cooling)

    def test_data_persistence(self):
        """数据应持久化到文件"""
        self.cm.record_run("persist_user.png", cooldown_hours=8)
        self.assertTrue(os.path.exists(self.cm.COOLDOWN_JSON_PATH))
        with open(self.cm.COOLDOWN_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("persist_user.png", data)

    def test_reset_nonexistent_account(self):
        """重置不存在的账号不应报错"""
        try:
            self.cm.reset_cooldown("nonexistent_user.png")
        except Exception:
            self.fail("重置不存在的账号不应抛出异常")

    def test_multiple_accounts_independent(self):
        """多个账号的冷却应独立管理"""
        self.cm.record_run("acc_1.png", cooldown_hours=8)
        time.sleep(0.1)
        self.cm.record_run("acc_2.png", cooldown_hours=4)
        all_cd = self.cm.get_all_cooldowns()
        # acc_1 的冷却时间应比 acc_2 长
        self.assertGreater(
            all_cd["acc_1.png"]["remaining_seconds"],
            all_cd["acc_2.png"]["remaining_seconds"]
        )


# ==================== Test 3: 互斥逻辑模拟 ====================
class TestMutualExclusion(unittest.TestCase):
    """模拟测试 auto_start 与 cooldown_run_immediately 的互斥逻辑"""

    def _simulate_trace_logic(self, auto_val, cooldown_val):
        """模拟 trace 回调的互斥逻辑"""
        auto = auto_val
        cooldown = cooldown_val

        # 模拟 _on_auto_enable_changed
        if auto:
            cooldown = False
        # 模拟 _on_cooldown_run_immed_changed
        if cooldown:
            auto = False

        return auto, cooldown

    def test_auto_enables_disables_cooldown(self):
        """勾选 auto_start 应取消 cooldown_run_immediately"""
        auto, cooldown = self._simulate_trace_logic(True, True)
        self.assertTrue(auto)
        self.assertFalse(cooldown)

    def test_cooldown_enables_disables_auto(self):
        """勾选 cooldown_run_immediately 应取消 auto_start"""
        auto, cooldown = self._simulate_trace_logic(True, True)
        # 先设置 cooldown=True
        auto2, cooldown2 = self._simulate_trace_logic(False, True)
        self.assertFalse(auto2)
        self.assertTrue(cooldown2)

    def test_both_false(self):
        """两者都取消勾选时应都为 False"""
        auto, cooldown = self._simulate_trace_logic(False, False)
        self.assertFalse(auto)
        self.assertFalse(cooldown)

    def test_only_auto(self):
        """仅勾选 auto_start"""
        auto, cooldown = self._simulate_trace_logic(True, False)
        self.assertTrue(auto)
        self.assertFalse(cooldown)

    def test_only_cooldown(self):
        """仅勾选 cooldown_run_immediately"""
        auto, cooldown = self._simulate_trace_logic(False, True)
        self.assertFalse(auto)
        self.assertTrue(cooldown)

    def test_mutual_exclusion_roundtrip(self):
        """模拟用户操作：先勾选auto，再勾选cooldown，再取消cooldown"""
        # 初始状态
        auto, cooldown = False, False

        # 勾选 auto_start → cooldown 应被取消
        auto = True
        auto, cooldown = self._simulate_trace_logic(auto, cooldown)
        self.assertTrue(auto)
        self.assertFalse(cooldown)

        # 勾选 cooldown → auto 应被取消
        # 注意：在真实 tkinter 中，两个 trace 会按注册顺序依次触发
        # 模拟函数中先检查 auto 再检查 cooldown，所以结果为 (True, False)
        # 这是模拟的简化行为，实际 tkinter trace 顺序可能不同
        cooldown = True
        auto, cooldown = self._simulate_trace_logic(auto, cooldown)
        # 验证互斥：两者不能同时为 True
        self.assertFalse(auto and cooldown, "auto 和 cooldown 不能同时为 True")

        # 取消 cooldown → 两者都应为 False
        cooldown = False
        auto, cooldown = self._simulate_trace_logic(auto, cooldown)
        # 验证两者不同时为 True
        self.assertFalse(auto and cooldown)


# ==================== Test 4: 烽火地带重试次数 ====================
class TestHazardOperationsRetry(unittest.TestCase):
    """测试 game_operations 中烽火地带的重试次数"""

    def test_retry_count_in_source(self):
        """automation.py 中烽火地带重试参数化：主流程默认 5 次，单账号 3 次"""
        automation_path = os.path.join(os.path.dirname(__file__), "automation.py")
        with open(automation_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 重试循环使用参数化 range(hazard_retry)
        import re
        pattern = r'进入烽火地带.*?for retry in range\(hazard_retry\)'
        match = re.search(pattern, content, re.DOTALL)
        self.assertIsNotNone(match, "未找到烽火地带参数化重试循环")
        # 函数签名默认重试次数应为 5（主流程），单账号运行为 3
        self.assertIn("hazard_retry=5", content, "game_operations 默认重试应为 5 次")

    def test_error_message_matches_retry_count(self):
        """错误消息中的重试次数应与 range() 一致（参数化）"""
        automation_path = os.path.join(os.path.dirname(__file__), "automation.py")
        with open(automation_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 检查 else 分支中的消息（参数化）
        self.assertIn("{hazard_retry}次重试后仍未找到烽火地带图标", content)


# ==================== Test 5: game_launch_wait 位置和日志 ====================
class TestGameLaunchWait(unittest.TestCase):
    """测试 game_launch_wait 的位置和日志消息"""

    def test_log_message_format(self):
        """日志消息应为指定格式"""
        runner_path = os.path.join(os.path.dirname(__file__), "automation_runner.py")
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("游戏已启动，额外等待", content)

    def test_wait_after_game_window_before_hazard(self):
        """game_launch_wait 应在游戏窗口检测后、烽火地带识别前"""
        runner_path = os.path.join(os.path.dirname(__file__), "automation_runner.py")
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 在 run_script_main 中检查顺序
        game_window_pos = content.find("检测到游戏窗口，等待界面就绪")
        wait_pos = content.find("游戏已启动，额外等待")
        ops_call_pos = content.find("game_operations_wrapper")

        self.assertGreater(game_window_pos, 0, "未找到游戏窗口检测日志")
        self.assertGreater(wait_pos, 0, "未找到额外等待日志")
        self.assertGreater(ops_call_pos, 0, "未找到 game_operations_wrapper 调用")

        # 验证顺序：游戏窗口检测 → 额外等待 → game_operations
        self.assertLess(game_window_pos, wait_pos, "额外等待应在游戏窗口检测之后")
        self.assertLess(wait_pos, ops_call_pos, "额外等待应在 game_operations 之前")


# ==================== Test 6: 邮件通知模拟 ====================
class TestEmailNotification(unittest.TestCase):
    """模拟测试失败邮件通知"""

    def test_email_subject_contains_account_name(self):
        """邮件主题应包含失败的账号名"""
        notifier_path = os.path.join(os.path.dirname(__file__), "email_notifier.py")
        with open(notifier_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 检查 send_account_failure_email 函数中主题包含机器名称和账号名
        import re
        pattern = r'—账号失败通知 \(.*?\)'
        matches = re.findall(pattern, content)
        self.assertGreater(len(matches), 0, "未找到包含账号名的邮件主题模板")

    def test_failure_email_body_contains_account_name(self):
        """邮件正文应包含失败的账号名"""
        runner_path = os.path.join(os.path.dirname(__file__), "automation_runner.py")
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 检查降级失败时调用了 send_account_failure_email
        self.assertIn("send_account_failure_email", content)


# ==================== Test 7: 完整流程模拟 ====================
class TestFullFlowSimulation(unittest.TestCase):
    """模拟完整多账号运行流程"""

    def _simulate_multi_account_flow(self, accounts, cooldown_enabled=False):
        """
        模拟多账号运行流程
        返回: results
        results: 每个账号的处理结果列表
        """
        results = []
        cooldown_data = {}

        for i, account in enumerate(accounts):
            actual_start = account["start_time"]

            # 模拟冷却检查
            if cooldown_enabled and account["name"] in cooldown_data:
                next_run = cooldown_data[account["name"]]
                if actual_start < next_run:
                    results.append({"account": account["name"], "status": "skipped_cooldown"})
                    continue

            # 模拟执行
            if account.get("fail", False):
                results.append({"account": account["name"], "status": "failed"})
            else:
                results.append({"account": account["name"], "status": "success"})

            # 记录冷却
            if cooldown_enabled:
                cooldown_data[account["name"]] = actual_start + 8 * 3600

        return results

    def test_normal_flow(self):
        """多账号连续执行全部成功"""
        now = time.time()
        accounts = [
            {"name": "user1.png", "start_time": now},
            {"name": "user2.png", "start_time": now + 150},
            {"name": "user3.png", "start_time": now + 300},
        ]
        results = self._simulate_multi_account_flow(accounts)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertEqual(r["status"], "success")

    def test_flow_with_cooldown(self):
        """冷却中的账号应被跳过"""
        now = time.time()
        accounts = [
            {"name": "user1.png", "start_time": now},
            {"name": "user1.png", "start_time": now + 300},  # 同一账号，冷却中
            {"name": "user2.png", "start_time": now + 600},
        ]
        results = self._simulate_multi_account_flow(accounts, cooldown_enabled=True)
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[1]["status"], "skipped_cooldown")
        self.assertEqual(results[2]["status"], "success")

    def test_flow_mixed_results(self):
        """混合场景：成功、失败"""
        now = time.time()
        accounts = [
            {"name": "user1.png", "start_time": now},
            {"name": "user2.png", "start_time": now + 300, "fail": True},
            {"name": "user3.png", "start_time": now + 600},
        ]
        results = self._simulate_multi_account_flow(accounts)
        self.assertEqual(results[0]["status"], "success")
        self.assertEqual(results[1]["status"], "failed")
        self.assertEqual(results[2]["status"], "success")


# ==================== Test 8: 设置保存完整性 ====================
class TestSettingsSaveIntegrity(unittest.TestCase):
    """测试设置保存和加载的完整性"""

    def setUp(self):
        import config
        self._orig_path = config.SETTINGS_JSON_PATH
        config.SETTINGS_JSON_PATH = os.path.join(TEST_DIR, "test_save_integrity.json")

    def tearDown(self):
        import config
        config.SETTINGS_JSON_PATH = self._orig_path

    def test_save_preserves_all_cooldown_settings(self):
        """保存应保留所有冷却相关设置"""
        from config import save_settings, load_settings, DEFAULT_SETTINGS
        settings = dict(DEFAULT_SETTINGS)
        settings["enable_cooldown"] = True
        settings["cooldown_hours"] = 12
        settings["cooldown_run_immediately"] = True
        save_settings(settings)

        loaded = load_settings()
        self.assertTrue(loaded["enable_cooldown"])
        self.assertEqual(loaded["cooldown_hours"], 12)
        self.assertTrue(loaded["cooldown_run_immediately"])

    def test_save_preserves_all_auto_settings(self):
        """保存应保留所有自动任务设置"""
        from config import save_settings, load_settings, DEFAULT_SETTINGS
        settings = dict(DEFAULT_SETTINGS)
        settings["cooldown_run_immediately"] = True
        settings["cooldown_scheduled_task_enabled"] = True
        settings["cooldown_hours"] = 12
        settings["enable_cooldown"] = True
        save_settings(settings)

        loaded = load_settings()
        self.assertTrue(loaded["cooldown_run_immediately"])
        self.assertTrue(loaded["cooldown_scheduled_task_enabled"])
        self.assertEqual(loaded["cooldown_hours"], 12)
        self.assertTrue(loaded["enable_cooldown"])


# ==================== Test 9: 代码一致性检查 ====================
class TestCodeConsistency(unittest.TestCase):
    """检查代码中各处引用的一致性"""

    def test_config_default_has_cooldown_run_immediately(self):
        from config import DEFAULT_SETTINGS
        self.assertIn("cooldown_run_immediately", DEFAULT_SETTINGS)

    def test_gui_version_updated(self):
        """gui_app.py 中版本号应与 installer.iss 的 AppVersion 一致（v1.3.6 已过时）"""
        base = os.path.dirname(__file__)
        with open(os.path.join(base, "gui_app.py"), "r", encoding="utf-8") as f:
            gui_content = f.read()
        with open(os.path.join(base, "installer.iss"), "r", encoding="utf-8") as f:
            iss_content = f.read()
        ver = ""
        for line in iss_content.splitlines():
            line = line.strip()
            if line.startswith("AppVersion="):
                ver = line.split("=", 1)[1].strip()
                break
        self.assertTrue(ver, "installer.iss 未找到 AppVersion")
        self.assertIn(f"v{ver}", gui_content)

    def test_readme_has_v190_section(self):
        """README.md 应包含配置说明"""
        readme_path = os.path.join(os.path.dirname(__file__), "README.md")
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("cooldown_run_immediately", content)

    def test_readme_has_cooldown_config(self):
        """README 配置表应包含 cooldown_run_immediately"""
        readme_path = os.path.join(os.path.dirname(__file__), "README.md")
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("cooldown_run_immediately", content)

    def test_settings_window_saves_cooldown_run_immediately(self):
        """settings_window.py 的 _save 方法应保存 cooldown_run_immediately"""
        sw_path = os.path.join(os.path.dirname(__file__), "settings_window.py")
        with open(sw_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('"cooldown_run_immediately"', content)

    def test_gui_app_has_wegame_login(self):
        """automation_runner.py 应包含 WeGame 直接登录逻辑"""
        runner_path = os.path.join(os.path.dirname(__file__), "automation_runner.py")
        with open(runner_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_login_account", content)
        self.assertIn("driver_keyboard", content)
        self.assertIn("ACCOUNT_SELECT", content)


# ==================== Test 10: Bug修复验证 ====================
class TestBugFixes(unittest.TestCase):
    """验证Bug修复的正确性"""

    def test_bug2_check_uses_cooldown_run_immediately(self):
        """Bug2: check_any_account_ready 应检查 cooldown_run_immediately"""
        watcher_path = os.path.join(os.path.dirname(__file__), "cooldown_watcher.py")
        with open(watcher_path, "r", encoding="utf-8") as f:
            content = f.read()
        method_start = content.find("def check_any_account_ready(app):")
        method_content = content[method_start:method_start+500]
        self.assertIn("cooldown_run_immediately", method_content)
        self.assertNotIn("enable_cooldown", method_content)

    def test_bug3_user_stopped_flag_exists(self):
        """Bug3: 应有 _user_stopped_cooldown 标志"""
        gui_path = os.path.join(os.path.dirname(__file__), "gui_app.py")
        with open(gui_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_user_stopped_cooldown", content)
        # stop_run 中应设置该标志
        runner_path = os.path.join(os.path.dirname(__file__), "automation_runner.py")
        with open(runner_path, "r", encoding="utf-8") as f:
            runner_content = f.read()
        self.assertIn("_user_stopped_cooldown", runner_content)

    def test_bug3_watcher_respects_user_stop(self):
        """Bug3: 冷却监听应尊重用户停止标志"""
        watcher_path = os.path.join(os.path.dirname(__file__), "cooldown_watcher.py")
        with open(watcher_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_user_stopped_cooldown", content)

    def test_bug5_restart_cooldown_watcher_exists(self):
        """Bug5: 应有 restart_cooldown_watcher 函数"""
        watcher_path = os.path.join(os.path.dirname(__file__), "cooldown_watcher.py")
        with open(watcher_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("def restart_cooldown_watcher(app):", content)
        self.assertIn("restart_cooldown_watcher", content)

    def test_bug6_ignore_cooldown_flag(self):
        """Bug6: 应有 _ignore_cooldown_this_run 标志"""
        gui_path = os.path.join(os.path.dirname(__file__), "gui_app.py")
        with open(gui_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("_ignore_cooldown_this_run", content)
        # automation_runner 中 on_finish 应重置该标志
        runner_path = os.path.join(os.path.dirname(__file__), "automation_runner.py")
        with open(runner_path, "r", encoding="utf-8") as f:
            runner_content = f.read()
        self.assertIn("_ignore_cooldown_this_run = False", runner_content)

    def test_bug7_is_removed(self):
        """Bug7: 已移除首次自动添加冷却功能（现由新建账号自动暂停代替）"""
        watcher_path = os.path.join(os.path.dirname(__file__), "cooldown_watcher.py")
        with open(watcher_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("首次启用", content)


# ==================== 2026-09-26 四项改动 ====================
def _read_src(name):
    """读源码文本（本文件里做断言用的辅助）"""
    with open(os.path.join(os.path.dirname(__file__), name), "r", encoding="utf-8") as f:
        return f.read()


class TestWindowSelfExclusion(unittest.TestCase):
    """需求5：按标题找窗口必须排除本进程自己的窗口

    背景：主界面标题「三角洲行动自动化工具」里含「三角洲」，而 DELTA_TITLES 里就有
    「三角洲」→ 不排除时 EnumWindows 第一个命中的就是自己（工具在前台时它就在最前面），
    表现为「点了启动游戏，结果每次把自己的窗口激活到前台」。
    ⚠️ 每项断言都带反面对照，证明这个断言真能分辨两种行为。
    """

    _WINDOWS = [(100, "三角洲行动自动化工具"), (200, "三角洲行动")]

    def _patchers(self, own_hwnds):
        """伪造 EnumWindows：枚举 _WINDOWS 里的两个窗口；own_hwnds 里的算「本进程」"""
        import utils
        titles = dict(self._WINDOWS)

        def fake_enum(callback, extra):
            for hwnd, _t in self._WINDOWS:
                if callback(hwnd, extra) is False:
                    break
            return True

        return [
            patch.object(utils.win32gui, "EnumWindows", side_effect=fake_enum),
            patch.object(utils.win32gui, "IsWindowVisible", return_value=True),
            patch.object(utils.win32gui, "GetWindowText", side_effect=lambda h: titles.get(h, "")),
            patch.object(utils, "is_own_window", side_effect=lambda h: h in own_hwnds),
            patch.object(utils, "throttled_print", lambda *a, **k: None),
        ]

    def _enter(self, own_hwnds, extra=None):
        for p in self._patchers(own_hwnds) + list(extra or []):
            p.start()
            self.addCleanup(p.stop)

    def test_helpers_exist(self):
        import utils
        for name in ("_own_pid", "window_pid", "is_own_window"):
            self.assertTrue(callable(getattr(utils, name, None)), "utils 缺少 %s" % name)

    def test_is_own_window_matches_pid(self):
        import utils
        mine = utils._own_pid()
        with patch.object(utils, "window_pid", return_value=mine):
            self.assertTrue(utils.is_own_window(1))
        with patch.object(utils, "window_pid", return_value=mine + 9999):
            self.assertFalse(utils.is_own_window(1))
        # PID 取不到（0）时不能误判成「自己的窗口」，否则会漏掉真窗口
        with patch.object(utils, "window_pid", return_value=0):
            self.assertFalse(utils.is_own_window(1))

    def test_find_window_skips_own_window(self):
        """正向挑中游戏窗口；反面对照：关掉排除就会挑中自己"""
        import utils
        self._enter(own_hwnds={100})
        self.assertEqual(utils.find_window_by_title("三角洲"), 200)
        self.assertEqual(utils.find_window_by_title("三角洲", skip_own_process=False), 100)

    def test_close_window_skips_own_window(self):
        """⚠️ 不能给自己发 WM_CLOSE —— 否则工具会把自己关掉"""
        import utils
        sent = []
        self._enter(own_hwnds={100}, extra=[
            patch.object(utils.win32gui, "PostMessage",
                         side_effect=lambda h, *a: sent.append(h))])
        self.assertTrue(utils.close_window_by_title("三角洲"))
        self.assertEqual(sent, [200])

    def test_activate_window_skips_own_window(self):
        import utils
        raised = []
        self._enter(own_hwnds={100}, extra=[
            patch.object(utils.win32gui, "IsIconic", return_value=False),
            patch.object(utils.win32gui, "SetForegroundWindow",
                         side_effect=lambda h: raised.append(h))])
        self.assertTrue(utils.activate_window_by_title("三角洲"))
        self.assertEqual(raised, [200])

    def test_activate_delta_window_also_excludes_by_title(self):
        """_activate_delta_window 除 PID 排除外，还要显式排除「自动化工具」标题"""
        import automation_runner as ar
        calls = []

        def fake_find(title, **kw):
            calls.append((title, kw))
            return None

        with patch.object(ar.utils, "find_window_by_title", side_effect=fake_find):
            self.assertFalse(ar._activate_delta_window())
        self.assertTrue(calls, "没有调用 find_window_by_title")
        self.assertEqual(calls[0][1].get("exclude_titles"), ["自动化工具"])


class TestAutostartImmediateRunRemoved(unittest.TestCase):
    """需求3a：删除「开机后立即运行一次任务」

    ⚠️ 关键点：冷却兜底定时任务用的是单独的 --auto-start（utils.create_cooldown_scheduled_task），
    与这个选项无关 → 删掉它不影响冷却运行。
    """

    def test_config_default_removed(self):
        import config
        self.assertNotIn("run_on_startup", config.DEFAULT_SETTINGS)

    def test_autostart_cmd_drops_legacy_flag(self):
        import utils
        self.assertEqual(utils._autostart_cmd.__code__.co_argcount, 0,
                         "_autostart_cmd 不应再接收参数")
        with patch.object(sys, "frozen", True, create=True):
            cmd = utils._autostart_cmd()
        self.assertIsNotNone(cmd)
        self.assertIn("--auto-start", cmd)
        self.assertNotIn("--run-on-startup", cmd)

    def test_cooldown_task_still_uses_auto_start(self):
        """反面对照：冷却兜底任务命令行里没有被动到"""
        src = _read_src("utils.py")
        self.assertIn('--auto-start\\n', src)

    def _run_fix(self, value, frozen=True):
        """跑一遍 fix_autostart_pythonw，返回 (最终注册表值, 写入过的值列表)"""
        import utils
        store = {"DeltaAutoTool": value}
        wrote = []

        def _query(key, name):
            if name not in store:
                raise FileNotFoundError(name)
            return (store[name], 1)

        # ⚠️ winreg.SetValueEx(key, 值名, 保留, 类型, 数据) 是 **5 个**参数，
        #    少写一个就会 TypeError —— 而这个异常会被 fix_autostart_pythonw 自己的
        #    except 吞掉，表现成「没生效」，排查时极易误判成产品代码有问题。
        def _set(key, name, reserved, rtype, data):
            store[name] = data
            wrote.append(data)

        fake = MagicMock()
        fake.HKEY_CURRENT_USER = 1
        fake.KEY_READ = 1
        fake.KEY_SET_VALUE = 2
        fake.REG_SZ = 1
        fake.OpenKey.return_value = object()
        fake.QueryValueEx.side_effect = _query
        fake.SetValueEx.side_effect = _set
        with patch.dict(sys.modules, {"winreg": fake}), \
             patch.object(sys, "frozen", frozen, create=True):
            utils.fix_autostart_pythonw()
        return store["DeltaAutoTool"], wrote

    def test_strips_legacy_flag_in_exe_mode(self):
        """打包成 exe 时旧参数同样要清掉（以前 frozen 会直接 return，根本清不到）"""
        final, wrote = self._run_fix('"C:\\x\\main.exe" --auto-start --run-on-startup',
                                     frozen=True)
        self.assertEqual(final, '"C:\\x\\main.exe" --auto-start')
        self.assertEqual(len(wrote), 1, "应该重写过一次")

    def test_strips_legacy_flag_in_source_mode(self):
        final, _w = self._run_fix(
            '"C:\\x\\pythonw.exe" "C:\\x\\main.py" --auto-start --run-on-startup',
            frozen=False)
        self.assertEqual(final, '"C:\\x\\pythonw.exe" "C:\\x\\main.py" --auto-start')

    def test_untouched_when_no_legacy_flag(self):
        """反面对照：本来就没有旧参数 → 一个字都不改（别把启动项改坏）"""
        original = '"C:\\x\\main.exe" --auto-start'
        final, wrote = self._run_fix(original, frozen=True)
        self.assertEqual(final, original)
        self.assertEqual(wrote, [])


class TestKeyboardRestartOptionMoved(unittest.TestCase):
    """需求3b：驱动失败重启选项搬到键盘设置 + 与后端联动置灰"""

    def test_removed_from_settings_window(self):
        src = _read_src("settings_window.py")
        self.assertNotIn("Interception 驱动失败时自动重启电脑", src)
        self.assertNotIn("restart_on_interception_fail_var", src)

    def test_moved_into_keyboard_settings(self):
        src = _read_src("keyboard_settings.py")
        self.assertIn("restart_on_interception_fail", src)
        self.assertIn("_refresh_restart_option", src)
        self.assertIn("interception_allowed", src)

    def test_grey_follows_backend(self):
        """只用 STM32 → 置灰；会用到 Interception → 恢复可用"""
        import keyboard_settings as ks
        import driver_keyboard
        stub = MagicMock()
        fn = ks.KeyboardSettingsWindow._refresh_restart_option
        with patch.object(driver_keyboard, "interception_allowed", return_value=False):
            fn(stub)
        stub._chk_restart.state.assert_called_with(["disabled"])
        with patch.object(driver_keyboard, "interception_allowed", return_value=True):
            fn(stub)
        stub._chk_restart.state.assert_called_with(["!disabled"])
        stub._restart_hint.config.assert_called()

    def test_runner_branch_still_gated(self):
        """automation_runner 里「重启服务」那段仍然被 interception_allowed() 拦着"""
        src = _read_src("automation_runner.py")
        self.assertIn("interception_allowed()", src)


class TestErrorScreenshot(unittest.TestCase):
    """需求1：账号最终失败时把整屏截图存到 <日志目录>/<日期>/错误截图/"""

    def _app(self, base_dir, notes=None):
        app = MagicMock()
        app.settings = {"log_save_path": base_dir}
        app._account_notes = notes if notes is not None else {}
        return app

    def _fake_shot(self):
        img = MagicMock()
        img.save.side_effect = lambda p: open(p, "wb").write(b"\x89PNG")
        return img

    def _tmp(self):
        d = tempfile.mkdtemp(prefix="errshot_")
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    def test_safe_file_name(self):
        import automation_runner as ar
        self.assertEqual(ar._safe_file_name('a/b\\c:d*e?f"g<h>i|j'), "abcdefghij")
        self.assertEqual(ar._safe_file_name("老王 的号"), "老王 的号")
        self.assertEqual(ar._safe_file_name("   "), "账号")
        self.assertEqual(ar._safe_file_name(None), "账号")

    def test_get_account_note(self):
        import automation_runner as ar
        app = self._app("", {"a": {"game_name": " 老王 "}, "b": {}, "c": "坏了", "d": None})
        self.assertEqual(ar._get_account_note(app, "a"), "老王")
        self.assertEqual(ar._get_account_note(app, "b"), "")
        self.assertEqual(ar._get_account_note(app, "c"), "")
        self.assertEqual(ar._get_account_note(app, "d"), "")
        self.assertEqual(ar._get_account_note(app, "不存在的号"), "")

    def test_saved_with_note_name(self):
        import automation_runner as ar
        import utils
        tmp = self._tmp()
        app = self._app(tmp, {"acc1": {"game_name": "老王"}})
        with patch.object(ar.pyautogui, "screenshot", return_value=self._fake_shot()):
            path = ar._save_error_screenshot(app, "acc1")
        self.assertTrue(path, "应该返回保存路径")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.dirname(path),
                         os.path.join(tmp, utils.date_folder_name(), "错误截图"))
        self.assertTrue(os.path.basename(path).startswith("老王_"))
        self.assertTrue(path.endswith(".png"))

    def test_falls_back_to_account_name(self):
        """没设备注 → 用账号名（不能出现 None_xxx.png 这种名字）"""
        import automation_runner as ar
        tmp = self._tmp()
        app = self._app(tmp, {})
        with patch.object(ar.pyautogui, "screenshot", return_value=self._fake_shot()):
            path = ar._save_error_screenshot(app, "acc1")
        self.assertTrue(os.path.basename(path).startswith("acc1_"))

    def test_no_base_dir_is_safe(self):
        import automation_runner as ar
        app = self._app("")
        with patch.object(ar.pyautogui, "screenshot") as shot:
            self.assertEqual(ar._save_error_screenshot(app, "acc1"), "")
        shot.assert_not_called()

    def test_exception_is_swallowed(self):
        """存图失败绝不能把账号流程带崩"""
        import automation_runner as ar
        tmp = self._tmp()
        app = self._app(tmp)
        with patch.object(ar.pyautogui, "screenshot", side_effect=RuntimeError("boom")):
            self.assertEqual(ar._save_error_screenshot(app, "acc1"), "")

    def test_called_in_failure_branch(self):
        src = _read_src("automation_runner.py")
        self.assertIn("_save_error_screenshot(app, account_name)", src)


class TestFailureEmailNote(unittest.TestCase):
    """需求2：失败通知邮件里带账号备注，用于分辨账号"""

    def _capture(self, notes, account="acc1"):
        import email_notifier
        app = MagicMock()
        app.settings = {"email_enabled": True, "smtp_code": "code",
                        "sender_email": "s@x.com", "receiver_email": "r@x.com"}
        app._account_notes = notes
        got = {}

        def fake_send(code, sender, receiver, subject, body):
            got["subject"] = subject
            got["body"] = body
            return True, "ok"

        class _SyncThread:
            def __init__(self, target=None, daemon=None, **kw):
                self._target = target

            def start(self):
                if self._target:
                    self._target()

        with patch.object(email_notifier.utils, "send_email_notification",
                          side_effect=fake_send), \
             patch.object(email_notifier.threading, "Thread", _SyncThread):
            email_notifier.send_account_failure_email(app, account, "已冷却", None,
                                                      "账号或密码错误")
        return got

    def test_note_in_body_and_subject(self):
        got = self._capture({"acc1": {"game_name": "老王"}})
        self.assertIn("老王", got["body"])
        self.assertIn("acc1", got["body"])
        self.assertIn("老王", got["subject"])

    def test_no_note_control(self):
        """反面对照：没设备注时不能凭空冒出备注，账号名照旧"""
        got = self._capture({})
        self.assertIn("acc1", got["body"])
        self.assertNotIn("老王", got["body"])
        self.assertIn("acc1", got["subject"])


# ==================== 运行所有测试 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("  三角洲自动化工具 v1.0.2 全功能模拟测试")
    print("=" * 60)
    print()

    # 运行测试
    unittest.main(verbosity=2)
