"""
皮肤抢购模块 - OCR自动监控倒计时并执行抢购（集成RapidOCR）
功能：
  1. 持续OCR识别屏幕指定区域的倒计时
  2. 可选余额区域检测，判断购买是否成功
  3. 倒计时<阈值时自动点击购买并快速确认
  4. 非抢购期每10秒刷新一次
  5. 超时自动停止
"""
import time
import re
import threading
import os
import utils


class SkinSniper:
    """皮肤抢购控制器"""

    def __init__(self):
        self._running = False
        self._thread = None
        self._stop_event = threading.Event()
        self._start_time = None

        # 配置（可在UI中修改）
        self.countdown_region = (100, 100, 200, 50)
        self.balance_region = None
        self.buy_template = None
        self.confirm_template = None
        self.refresh_template = None
        self.ocr_interval = 0.3
        self.refresh_interval = 10.0
        self.refresh_stop_threshold = 10
        self.buy_threshold = 5
        self.balance_change_threshold = 0
        self.timeout_minutes = 30

        self._last_countdown = None
        self._last_countdown_time = 0
        self._last_balance = None
        self._purchase_attempted = False
        self._purchase_success = False
        self._status_callback = None
        self._log_callback = None
        self._countdown_callback = None

    def set_callbacks(self, status_cb=None, log_cb=None, countdown_cb=None):
        self._status_callback = status_cb
        self._log_callback = log_cb
        self._countdown_callback = countdown_cb

    def _log(self, msg):
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
        self._last_countdown = None
        self._last_countdown_time = 0
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log("抢购已启动")

    def stop(self):
        self._running = False
        self._stop_event.set()
        self._log("抢购已停止")

    def _read_countdown(self):
        """OCR读取倒计时区域，成功则更新 _last_countdown，失败则保留上次值"""
        if not self.countdown_region or self.countdown_region[2] <= 0 or self.countdown_region[3] <= 0:
            return self._last_countdown
        if self._last_countdown_time and time.time() - self._last_countdown_time > 3:
            self._last_countdown = None
            self._last_countdown_time = 0
        results = utils.ocr_recognize(self.countdown_region)
        if not results:
            return self._last_countdown
        for text, conf, bbox in results:
            if conf < 0.5:
                continue
            # 格式1: HH:MM:SS (00:05:30 = 5分30秒)
            match = re.search(r'(\d+):(\d+):(\d+)', text)
            if match:
                val = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
                self._last_countdown = val
                self._last_countdown_time = time.time()
                return val
            # 格式2: MM:SS (05:30 = 5分30秒)
            match = re.search(r'(\d+):(\d+)', text)
            if match:
                val = int(match.group(1)) * 60 + int(match.group(2))
                self._last_countdown = val
                self._last_countdown_time = time.time()
                return val
            # 格式3: X分X秒 / X分 / X秒
            m = re.search(r'(\d+)\s*分\s*(\d+)?\s*秒?', text)
            if m:
                total = int(m.group(1)) * 60
                if m.group(2):
                    total += int(m.group(2))
                self._last_countdown = total
                self._last_countdown_time = time.time()
                return total
            # 格式4: 纯数字
            match = re.search(r'(\d+)', text)
            if match:
                val = float(match.group(1))
                self._last_countdown = val
                self._last_countdown_time = time.time()
                return val
        return self._last_countdown

    def _get_display_countdown(self):
        """获取用于显示的倒计时值（基于上次读取值 + 时间衰减自动递减）"""
        if self._last_countdown is None or not self._last_countdown_time:
            return None
        elapsed = time.time() - self._last_countdown_time
        remaining = self._last_countdown - elapsed
        return max(0, remaining)

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

    def _check_timeout(self):
        """检查是否超时"""
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

                countdown = self._read_countdown()
                if countdown is not None:
                    display = self._get_display_countdown()
                    if display is not None:
                        self._set_status(f"倒计时: {display:.0f}秒")
                        if self._countdown_callback:
                            self._countdown_callback(display)
                    elif self._countdown_callback:
                        self._countdown_callback(None)
                elif self._countdown_callback:
                    self._countdown_callback(None)

                    if countdown < self.buy_threshold and not self._purchase_attempted:
                        self._log(f"倒计时 {countdown:.0f}秒 < {self.buy_threshold}秒，执行抢购!")
                        self._purchase_attempted = True
                        self._execute_purchase()
                        self._sleep_or_stop(2)

                        if self.balance_region:
                            nb = self._read_balance()
                            if self._last_balance is not None and nb is not None:
                                diff = abs(nb - self._last_balance)
                                if diff > self.balance_change_threshold:
                                    self._log(f"余额变化 {diff}，购买成功!")
                                    self._purchase_success = True
                                    continue
                                else:
                                    self._log(f"余额未变化({diff})，可能失败，继续监控")
                                    self._purchase_attempted = False
                            else:
                                self._log("无法读取余额，继续监控")
                                self._purchase_attempted = False
                        else:
                            self._purchase_success = True
                            continue

                    if countdown < self.refresh_stop_threshold:
                        self._set_status(f"等待抢购: {countdown:.0f}秒")
                        self._sleep_or_stop(self.ocr_interval)
                        continue

                if refresh_timer >= self.refresh_interval:
                    if self.refresh_template and os.path.exists(self.refresh_template):
                        self._log("刷新页面")
                        utils.find_and_click_smart(self.refresh_template, timeout=5)
                    refresh_timer = 0
                else:
                    refresh_timer += self.ocr_interval

                self._sleep_or_stop(self.ocr_interval)
            except Exception as e:
                self._log(f"异常: {e}")
                self._sleep_or_stop(1)

        self._running = False

    def _execute_purchase(self):
        """等待3秒 → 快速点击确认3秒 → Esc → 刷新一次"""
        import random
        self._log("等待3秒后执行抢购...")
        self._sleep_or_stop(3)

        # 快速点击确认按钮（持续3秒）
        if self.confirm_template and os.path.exists(self.confirm_template):
            self._log("快速点击确认按钮（3秒）")
            start = time.time()
            while time.time() - start < 3 and not self._stop_event.is_set():
                if utils.find_and_click_smart(self.confirm_template, timeout=2):
                    time.sleep(random.uniform(0.05, 0.12))

        # 按 Esc 返回
        if not self._stop_event.is_set():
            import pyautogui
            pyautogui.press("esc")
            self._log("已按 Esc 返回")
            time.sleep(0.3)

        # 刷新一次
        if not self._stop_event.is_set() and self.refresh_template and os.path.exists(self.refresh_template):
            self._log("刷新页面")
            utils.find_and_click_smart(self.refresh_template, timeout=5)

    def _sleep_or_stop(self, seconds):
        chunk = 0.1
        elapsed = 0
        while elapsed < seconds and not self._stop_event.is_set():
            time.sleep(chunk)
            elapsed += chunk
