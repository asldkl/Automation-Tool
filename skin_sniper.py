"""
皮肤抢购模块 - 图片识别自动监控购买按钮并执行抢购
功能：
  1. 持续在指定区域使用图片识别查找购买按钮
  2. 找到后自动点击并进入确认流程
  3. 确认阶段拟人化点击3秒
  4. 非抢购期定时刷新页面
  5. 超时自动停止
  6. 购买后按钮未消失则等待消失后继续监控
"""
import time
import re
import threading
import os
import random
import pyautogui
import utils


class SkinSniper:
    """皮肤抢购控制器"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._start_time = None

        # 配置（可在UI中修改）
        self.search_region = (100, 100, 200, 50)    # 搜索区域 [x, y, w, h]
        self.balance_region = None                   # 余额区域（可选）
        self.buy_template = None                     # 购买/确认按钮图片（同一张图）
        self.refresh_template = None                 # 刷新按钮图片
        self.refresh_interval = 10.0                 # 未找到时刷新间隔（秒）
        self.balance_change_threshold = 0            # 余额变化阈值
        self.timeout_minutes = 30                    # 超时分钟数

        self._last_balance = None
        self._purchase_attempted = False
        self._purchase_success = False
        self._status_callback = None
        self._log_callback = None

    def set_callbacks(self, status_cb=None, log_cb=None, countdown_cb=None):
        self._status_callback = status_cb
        self._log_callback = log_cb

    def _log(self, msg):
        if not hasattr(self, "_last_log_msg"):
            self._last_log_msg = ""
            self._last_log_time = 0
        now = time.time()
        if msg == self._last_log_msg and now - self._last_log_time < 5:
            return
        self._last_log_msg = msg
        self._last_log_time = now
        print(f"[皮肤抢购] {msg}")
        if self._log_callback:
            self._log_callback(msg)

    def _set_status(self, status):
        if self._status_callback:
            self._status_callback(status)

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        self._purchase_attempted = False
        self._purchase_success = False
        self._last_balance = None
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log("抢购已启动")
        self._set_status("监控中...")

    def stop(self):
        self._running = False
        self._stop_event.set()
        self._log("抢购已停止")
        self._set_status("已停止")

    def _find_buy_pos(self):
        """在搜索区域查找 buy 图片，返回 (x, y) 中心坐标或 None"""
        if not self.buy_template or not os.path.exists(self.buy_template):
            return None
        if not self.search_region or self.search_region[2] <= 0 or self.search_region[3] <= 0:
            return None

        import config as cfg
        threshold = cfg.load_settings().get("confidence", 0.7)
        template = utils._imread_unicode(self.buy_template)
        if template is None:
            return None
        gray = utils._screenshot_gray(self.search_region)
        if gray is None:
            return None

        matched, max_val, max_loc, (h, w) = utils._match_template(gray, template, threshold)
        if matched:
            x = max_loc[0] + w // 2 + self.search_region[0]
            y = max_loc[1] + h // 2 + self.search_region[1]
            return (x, y)
        return None

    def _check_timeout(self):
        if self.timeout_minutes <= 0 or self._start_time is None:
            return False
        return (time.time() - self._start_time) / 60 >= self.timeout_minutes

    def _run_loop(self):
        """抢购主循环"""
        refresh_timer = 0.0
        while not self._stop_event.is_set():
            try:
                if self._check_timeout():
                    self._log(f"抢购超时（{self.timeout_minutes}分钟），自动停止")
                    self._set_status("已超时停止")
                    break
                if self._purchase_success:
                    self._log("购买成功，监控结束")
                    self._set_status("购买成功 ✅")
                    break

                # 在搜索区域查找购买按钮
                pos = self._find_buy_pos()

                if pos:
                    self._set_status("检测到购买按钮，执行抢购")
                    self._log(f"检测到购买按钮，执行抢购")
                    self._purchase_attempted = True

                    # 执行完整购买流程
                    self._execute_purchase(pos)

                    # 检测购买后按钮是否消失
                    self._log("检测购买按钮是否消失...")
                    disappear_start = time.time()
                    disappeared = False
                    while time.time() - disappear_start < 8 and not self._stop_event.is_set():
                        if self._find_buy_pos() is None:
                            disappeared = True
                            break
                        time.sleep(0.3)

                    if disappeared:
                        self._log("购买按钮已消失，抢购成功")
                        self._set_status("抢购成功 ✅")
                        # 可选：余额检测验证
                        if self.balance_region:
                            time.sleep(0.5)
                            nb = self._read_balance()
                            if self._last_balance is not None and nb is not None:
                                diff = abs(nb - self._last_balance)
                                if diff > self.balance_change_threshold:
                                    self._log(f"余额变化 {diff}，验证成功")
                        self._purchase_success = True
                        continue
                    else:
                        # 按钮未消失（"bug"状态），停止刷新，等待消失后重新开始
                        self._log("购买后按钮仍存在，等待按钮消失后重新监控")
                        self._set_status("等待按钮消失...")
                        self._purchase_attempted = False
                        while not self._stop_event.is_set():
                            if self._find_buy_pos() is None:
                                self._log("按钮已消失，继续监控")
                                self._set_status("监控中...")
                                break
                            time.sleep(0.5)
                        # 重置刷新计时器，让它在下一轮正常刷新
                        refresh_timer = 0
                        continue

                # 没找到 → 定时刷新
                if refresh_timer >= self.refresh_interval:
                    if self.refresh_template and os.path.exists(self.refresh_template):
                        self._log("刷新页面")
                        utils.find_and_click_smart(self.refresh_template, timeout=5)
                    refresh_timer = 0
                else:
                    refresh_timer += 0.3

                self._sleep_or_stop(0.3)

            except Exception as e:
                self._log(f"异常: {e}")
                import traceback
                traceback.print_exc()
                self._sleep_or_stop(1)

        self._running = False

    def _execute_purchase(self, pos):
        """执行抢购流程：点击购买 → 等待2秒 → 拟人点击确认3秒 → Esc → 刷新"""
        # 1. 点击购买按钮
        self._log("点击购买按钮")
        utils.smooth_move_to(pos[0], pos[1], duration=0.2)
        pyautogui.click()
        time.sleep(2)

        # 2. 移动到相同位置，拟人点击 3 秒（确认购买，相同图片）
        self._log("确认购买 - 拟人点击 3 秒")
        utils.smooth_move_to(pos[0], pos[1], duration=0.2)
        start = time.time()
        while time.time() - start < 3 and not self._stop_event.is_set():
            pyautogui.click()
            time.sleep(random.uniform(0.05, 0.12))

        # 3. 按 Esc 返回
        if not self._stop_event.is_set():
            pyautogui.press("esc")
            self._log("已按 Esc 返回")
            time.sleep(0.3)

        # 4. 点击刷新
        if not self._stop_event.is_set() and self.refresh_template and os.path.exists(self.refresh_template):
            self._log("点击刷新")
            utils.find_and_click_smart(self.refresh_template, timeout=5)
            time.sleep(1)

    def _read_balance(self):
        """OCR读取余额区域"""
        if not self.balance_region or self.balance_region[2] <= 0 or self.balance_region[3] <= 0:
            return None
        results = utils.ocr_recognize(self.balance_region)
        if not results:
            return None
        for text, conf, bbox in results:
            if conf < 0.5:
                continue
            match = re.search(r'[\d,.]+', text)
            if match:
                raw = match.group(0).replace(',', '').replace('.', '')
                try:
                    return int(raw)
                except ValueError:
                    pass
        return None

    def _sleep_or_stop(self, seconds):
        chunk = 0.1
        elapsed = 0
        while elapsed < seconds and not self._stop_event.is_set():
            time.sleep(chunk)
            elapsed += chunk
