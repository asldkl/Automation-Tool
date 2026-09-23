# -*- coding: utf-8 -*-
"""驱动级键盘输入模块 —— 统一键盘输入接口，按优先级自动选择后端。

后端与优先级（配置键 `keyboard_backend`）
----------------------------------------
    auto（默认）  STM32 外部硬件键盘 → Interception 驱动
    stm32        只用 STM32 外部硬件键盘（未接则失败，不回退）
    interception 只用 Interception 驱动

**为什么 auto 把 STM32 排在 Interception 前面**：两者都是硬件级输入（游戏/反作弊认），
但 Interception 是**内核键盘类上层筛选器** —— 一旦挂死会让整机键盘失效、只能重启（有实例）；
STM32 是独立的 USB HID 设备，坏了也只是它自己不按键。两者都能用时，没有理由优先用有副作用的那个。

⚠️ **已按用户要求移除 SendInput 后端**：它是纯软件模拟，按键带注入标记，
WeGame 这类目标根本不认 → 会出现「以为输入了、其实账号密码没进去」，
比直接失败更糟。所以两者都不可用时**直接返回 False**，由上层按登录失败处理。

⚠️ **不做「输入中途换后端」**：密码类输入若在中途换后端，同一个字符串会被打两遍 → 必然错误。
所以策略是「先挑一个可用后端，然后只用它」；只有当前后端**整体不可用**（比如设备被拔了）
时才会重新挑，而不是在一次输入失败后切换。

对外只返回 True/False，绝不抛异常。
"""
_settings = {}          # 由 set_settings() 注入（默认空 = 全部用默认值）
_CHOSEN = None          # 已选定的后端；仅当它不再可用时才重新挑

BACKENDS = ("stm32", "interception")
_LABEL = {
    "stm32": "STM32 外部硬件键盘",
    "interception": "Interception 驱动",
}


def set_settings(settings):
    """注入应用设置（不调用也能跑：全部走默认值，STM32 仍会按 VID/PID 自动查找）"""
    global _settings, _CHOSEN
    _settings = dict(settings or {})
    _CHOSEN = None       # 配置变了，重新挑


# --------------------------------------------------------------------------- #
# 各后端的可用性判定
# --------------------------------------------------------------------------- #

def _available(name):
    try:
        if name == "stm32":
            import stm32_keyboard
            return stm32_keyboard.is_available(_settings)
        if name == "interception":
            import interception_keyboard
            return bool(interception_keyboard.is_available())
    except Exception:
        return False
    return False


def _order():
    """按配置决定尝试顺序"""
    want = str((_settings or {}).get("keyboard_backend", "auto") or "auto").strip().lower()
    if want in BACKENDS:
        return (want,)
    return BACKENDS          # auto / 非法值 → 默认顺序


def _pick(force=False):
    """挑一个可用后端并缓存；force=True 时强制重挑"""
    global _CHOSEN
    if not force and _CHOSEN and _available(_CHOSEN):
        return _CHOSEN
    for name in _order():
        if _available(name):
            _CHOSEN = name
            return name
    _CHOSEN = None
    return None


# --------------------------------------------------------------------------- #
# 后端实现
# --------------------------------------------------------------------------- #

def _send_stm32(text, interval):
    import stm32_keyboard
    return stm32_keyboard.send_string(text, interval=interval, settings=_settings)


def _send_interception(text, interval):
    import interception_keyboard
    return interception_keyboard.send_string(text, interval=interval)


_SENDERS = {
    "stm32": _send_stm32,
    "interception": _send_interception,
}


# --------------------------------------------------------------------------- #
# 对外接口
# --------------------------------------------------------------------------- #

def is_available():
    """是否有任何可用的键盘后端"""
    return _pick() is not None


def get_backend():
    """返回当前生效的后端名（含细节），给日志与设置界面用"""
    name = _pick()
    if name is None:
        return "无可用后端"
    if name == "stm32":
        try:
            import stm32_keyboard
            return stm32_keyboard.get_backend(_settings)
        except Exception:
            pass
    if name == "interception":
        try:
            import interception_keyboard
            return interception_keyboard.get_backend()
        except Exception:
            pass
    return _LABEL.get(name, name)


def send_string(text, interval=0.02):
    """发送字符串。**只用挑定的那一个后端**（避免中途换后端把同一串打两遍）

    返回 True/False；失败时打印明确原因，绝不抛异常。
    """
    if not text:
        return True

    name = _pick()
    if name is None:
        print("⚠️ 键盘输入失败：没有可用的硬件键盘后端（STM32 未接 / Interception 驱动不可用）—— 已刻意不使用软件模拟，它无法把账号密码送进目标窗口，直接判失败更安全")
        return False

    try:
        return bool(_SENDERS[name](text, interval))
    except Exception as e:
        print("⚠️ 键盘输入失败（后端 %s 异常）：%s" % (_LABEL.get(name, name), e))
        return False


def send_key(char, interval=0.02):
    return send_string(char, interval=interval)


def backend_report():
    """各后端可用性一览（给设置界面的状态显示用）；返回 (列表, 当前选中后端)"""
    lines = []
    for name in BACKENDS:
        ok = _available(name)
        if name == "stm32":
            try:
                import stm32_keyboard
                detail = stm32_keyboard.get_backend(_settings)
                if not ok:
                    detail += " / " + (stm32_keyboard.last_error() or "不可用")
            except Exception as e:
                detail = "模块异常：%s" % e
        elif name == "interception":
            detail = "驱动可用" if ok else "驱动不可用（未安装或未启动）"
        else:
            detail = "始终可用（软件模拟，游戏可能不认）"
        lines.append(("✓" if ok else "✗", _LABEL.get(name, name), detail))
    return lines, _pick()
