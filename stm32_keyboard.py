# -*- coding: utf-8 -*-
"""STM32 外部硬件键盘后端（USB 复合设备：CDC 虚拟串口 + HID 键盘）

为什么要有它
------------
Interception 是**内核键盘类上层筛选器**：它挂在 `kbdclass` 上，一旦挂死会让**整机键盘**失效
（插拔/换键盘都没用），只能重启。STM32 是**独立的 USB HID 键盘设备**，插在系统外面：
PC 侧零驱动，它坏了/线掉了也只是"这个设备不再按键"，用户自己的键盘完全不受影响。
而且对游戏/反作弊而言，它和 Interception 一样是**硬件级输入**（没有 SendInput 的注入标记）。

协议（由固件定义，与工程内 `按键模拟输入/Python/stm_kb.py` 同一套）
------------------------------------------------------------------
USB: VID:PID = 0x0483:0x57A0，产品名 "STM32 SimKeyboard CDC+HID"（Windows 免驱）
串口: 115200 8N1，**文本行协议**（`\\n` 结尾，大小写不敏感），每条指令回执 `OK...` / `ERR <3位码> 说明`

    PING | INFO | K <键[+键]> [ms] | TYPE <文本> | MEDIA <名> [ms]
    HOLD <键[+键]> ON|OFF | HOLD ALL OFF | SEQ <键,键> [ms]
    TYPE_INTERVAL <ms> | STOP | RESUME | HELP

    ERR 码：001 未知指令 / 002 参数错误 / 003 未知键名 / 004 非ASCII / 005 已停止
            006 被中断 / 007 USB未就绪 / 008 行超长

⚠️ 两点必须记住：
  1. `TYPE` 只接受 **ASCII 可见字符 + 制表符**（非 ASCII 直接 ERR 004）→ 本模块**先校验再发**，
     不把非法内容丢给固件（密码里打错一个字符就登录失败，宁可提前失败）。
  2. 固件有**紧急停止**（长按板上 PB1/PB11 0.8 秒触发）：停止后设备会拒绝按键指令（ERR 005），
     需要 `RESUME` 才恢复。这是**用户主动的安全动作**，本模块**不会自动 RESUME** ——
     只报明确提示，让人来决定。

对外只返回 True/False，绝不抛异常（与 `interception_keyboard` 一致的约定）。
日志里**永不打印输入内容**（账号/密码），只打长度。
"""
import threading
import time

# 与固件 usbd_desc.c 保持一致
VENDOR_ID = 0x0483
PRODUCT_ID = 0x57A0
DEFAULT_BAUDRATE = 115200

# 固件 TYPE_INTERVAL 的合法区间（5~500ms）
INTERVAL_MIN_MS = 5
INTERVAL_MAX_MS = 500

# TYPE 允许的字符：ASCII 可见字符 + 制表符（固件对非 ASCII 回 ERR 004）
_ALLOWED = set(chr(c) for c in range(0x20, 0x7F)) | {"\t"}

_ERR_TEXT = {
    "001": "未知指令",
    "002": "参数错误",
    "003": "未知键名",
    "004": "含非 ASCII 字符（固件不接受）",
    "005": "设备处于紧急停止状态（板上长按 PB1/PB11 触发，需 RESUME 恢复）",
    "006": "被中断",
    "007": "USB 未就绪",
    "008": "指令行超长",
}

_lock = threading.Lock()          # 串口是独占资源，同一时刻只允许一条指令在途
_last_error = ""                  # 最近一次失败原因（给界面/日志用）


def _import_serial():
    """延迟导入 pyserial：没装时不要炸，只让本后端不可用"""
    try:
        import serial
        from serial.tools import list_ports
        return serial, list_ports
    except Exception:
        return None, None


def read_config(settings):
    """从设置里读 STM32 相关配置（手填的值不能信，一律做区间校验）"""
    s = settings or {}
    port = str(s.get("stm32_port", "auto") or "auto").strip()
    if port.lower() in ("", "auto", "自动"):
        port = None                       # None = 按 VID/PID 自动查找

    def _num(key, default, lo, hi):
        try:
            v = float(s.get(key, default))
        except (TypeError, ValueError):
            return default
        return default if (v < lo or v > hi) else v

    return {
        "port": port,
        "interval_ms": int(_num("stm32_interval_ms", 25, INTERVAL_MIN_MS, INTERVAL_MAX_MS)),
        "timeout": _num("stm32_timeout", 3.0, 0.5, 30.0),
    }


def available_ports():
    """列出所有候选串口 [(device, description)]；pyserial 缺失时返回 []"""
    _serial, list_ports = _import_serial()
    if list_ports is None:
        return []
    try:
        return [(p.device, p.description or "") for p in list_ports.comports()]
    except Exception:
        return []


def find_port(settings=None):
    """返回该用的串口号；找不到返回 None"""
    cfg = read_config(settings)
    if cfg["port"]:
        return cfg["port"]          # 用户手填的端口，直接用（不校验存在性，交给打开时报错）
    _serial, list_ports = _import_serial()
    if list_ports is None:
        return None
    try:
        for p in list_ports.comports():
            if p.vid == VENDOR_ID and p.pid == PRODUCT_ID:
                return p.device
    except Exception:
        pass
    return None


def is_available(settings=None):
    """设备是否可用 = pyserial 装好 + 找得到端口。

    ⚠️ 这里**只做查找、不打开串口**：发送是「用完就关」的，
    所以占用端口的时间极短，不会长期占着让上位机控制台连不上。
    """
    global _last_error
    _serial, _lp = _import_serial()
    if _serial is None:
        _last_error = "未安装 pyserial（pip install pyserial）"
        return False
    port = find_port(settings)
    if not port:
        _last_error = "未找到 STM32 键盘设备（期望 VID:PID=%04X:%04X，检查 USB 线）" % (
            VENDOR_ID, PRODUCT_ID)
        return False
    _last_error = ""
    return True


def get_backend(settings=None):
    """用于日志/界面显示的后端名"""
    port = find_port(settings)
    if port:
        return "STM32(%s)" % port
    _serial, _lp = _import_serial()
    if _serial is None:
        return "STM32(未装 pyserial)"
    return "STM32(未连接)"


def last_error():
    return _last_error


def _validate(text):
    """返回 (ok, 原因)：固件只吃 ASCII 可见字符 + Tab，非法就提前失败（别把脏数据打进密码框）"""
    if text is None or text == "":
        return False, "内容为空"
    bad = [c for c in text if c not in _ALLOWED]
    if bad:
        uniq = "".join(sorted(set(bad)))[:10]
        return False, "含固件不支持的字符（只接受 ASCII 可打印字符与制表符）：%r" % uniq
    return True, ""


class _Conn:
    """一次性的串口连接：打开 → 收发若干条指令 → 关闭（用完就放，不长期占用）"""

    def __init__(self, port, baudrate=DEFAULT_BAUDRATE):
        serial, _ = _import_serial()
        self.ser = serial.Serial(port, baudrate, timeout=0.1, write_timeout=1.0)
        time.sleep(0.15)
        try:
            self.ser.reset_input_buffer()      # 丢掉打开瞬间的问候语/残留
        except Exception:
            pass

    def cmd(self, line, timeout=3.0, quiet=False):
        """发一条指令并等回执。返回 (ok: bool, resp: str)"""
        try:
            self.ser.write((line + "\n").encode("ascii", errors="replace"))
            self.ser.flush()
        except Exception as e:
            return False, "串口写入失败：%s" % e

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.ser.readline()
            except Exception as e:
                return False, "串口读取失败：%s" % e
            if not raw:
                continue
            resp = raw.decode("ascii", errors="replace").strip()
            if not resp:
                continue
            if resp.startswith("OK"):
                return True, resp
            if resp.startswith("ERR"):
                parts = resp.split(" ", 2)
                code = parts[1] if len(parts) > 1 else "?"
                why = _ERR_TEXT.get(code, " ".join(parts[2:]) or "未知错误")
                return False, "设备拒绝（ERR %s %s）" % (code, why)
            # 非回执：设备问候 / 紧急停止通知等，忽略但记下来
            if not quiet:
                print("   ↳ 设备消息：%s" % resp)
        return False, "等待设备回执超时（%.1fs）" % timeout

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


def send_string(text, interval=0.02, settings=None):
    """把整串文本交给硬件键盘输入。成功返回 True。

    `interval` 沿用项目里其它后端的语义（秒/字符），这里换算成固件的 TYPE_INTERVAL（毫秒）。
    ⚠️ 只打长度、不打内容 —— 账号密码不进日志。
    """
    global _last_error

    ok, why = _validate(text)
    if not ok:
        _last_error = why
        print("⚠️ STM32 键盘：%s（长度 %d）" % (why, len(text or "")))
        return False

    cfg = read_config(settings)
    port = find_port(settings)
    if not port:
        _last_error = "未找到 STM32 键盘设备"
        print("⚠️ STM32 键盘：%s" % _last_error)
        return False

    # 秒/字符 → 毫秒/字符，并按固件允许区间夹紧
    ms = int(round(float(interval) * 1000))
    ms = max(INTERVAL_MIN_MS, min(INTERVAL_MAX_MS, ms)) if ms > 0 else cfg["interval_ms"]
    # 固件按这个节奏逐字符敲；给足等待时间（每条字符的间隔 + 余量）
    timeout = max(cfg["timeout"], 2.0 + len(text) * (ms / 1000.0 + 0.02))

    with _lock:
        conn = None
        try:
            conn = _Conn(port)
            ok, resp = conn.cmd("PING", timeout=1.5)
            if not ok:
                _last_error = "握手失败：%s" % resp
                print("⚠️ STM32 键盘：%s" % _last_error)
                return False

            ok, resp = conn.cmd("TYPE_INTERVAL %d" % ms, timeout=1.5)
            if not ok:
                _last_error = "设置打字间隔失败：%s" % resp
                print("⚠️ STM32 键盘：%s" % _last_error)
                return False

            ok, resp = conn.cmd("TYPE " + text, timeout=timeout)
            if not ok:
                _last_error = resp
                print("⚠️ STM32 键盘：输入失败 —— %s（长度 %d）" % (resp, len(text)))
                return False

            print("⌨️ STM32 键盘：已输入 %d 个字符（间隔 %dms，%s）" % (len(text), ms, port))
            _last_error = ""
            return True
        except Exception as e:
            _last_error = "串口异常：%s" % e
            print("⚠️ STM32 键盘：%s" % _last_error)
            return False
        finally:
            if conn is not None:
                conn.close()          # 用完就放，端口不会被长期占用


def send_key(char, interval=0.02, settings=None):
    """接口对齐用（项目里其它后端都有）"""
    return send_string(char, interval=interval, settings=settings)


def probe(settings=None):
    """设置界面「测试连接」用：打开→PING→INFO→关闭。返回 (ok, 说明)"""
    port = find_port(settings)
    if not port:
        return False, "未找到设备（期望 VID:PID=%04X:%04X）" % (VENDOR_ID, PRODUCT_ID)
    if _import_serial()[0] is None:
        return False, "未安装 pyserial"
    with _lock:
        conn = None
        try:
            conn = _Conn(port)
            ok, resp = conn.cmd("PING", timeout=2.0)
            if not ok:
                return False, resp
            ok2, info = conn.cmd("INFO", timeout=2.0)
            return True, "%s  %s" % (resp, info if ok2 else "")
        except Exception as e:
            return False, "串口异常：%s" % e
        finally:
            if conn is not None:
                conn.close()


def stop(settings=None):
    """紧急停止（等价于板上长按 PB1/PB11）：立即释放全部按键并清空指令队列。
    停止后设备会拒绝按键指令，需要 resume()。"""
    return _simple("STOP", settings)


def resume(settings=None):
    """解除紧急停止"""
    return _simple("RESUME", settings)


def release_all(settings=None):
    """只释放按住中的键，不进入停止状态"""
    return _simple("HOLD ALL OFF", settings)


def _simple(line, settings=None):
    port = find_port(settings)
    if not port:
        return False, "未找到设备"
    with _lock:
        conn = None
        try:
            conn = _Conn(port)
            return conn.cmd(line, timeout=2.0)
        except Exception as e:
            return False, "串口异常：%s" % e
        finally:
            if conn is not None:
                conn.close()
