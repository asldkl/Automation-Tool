# -*- coding: utf-8 -*-
"""
模板「插入步骤」模块

给某个模板（var_name，如 "Hazard_Operations" 烽火地带入口）配置一段自定义步骤，
在自动化"识别点击该模板图片"的点击前 / 点击后执行；执行完自然继续后续流程。

数据存储：
    settings.json["template_insert_steps"] = {
        "Hazard_Operations": {"timing": "before"|"after", "steps": [custom_ops 步骤, ...]},
        ...
    }
    步骤格式与图片目录复用 custom_ops（图片存 custom_ops/images/）。
    某模板 steps 为空时 save 即删除该项 → 向导红勾消失、运行时不执行。

执行：
    复用 custom_ops._run_batch_steps（支持 jump/condition 控制流）；
    custom_ops._execute_step 对 app 依赖仅 .settings，故运行上下文可用
    types.SimpleNamespace(settings=设置字典) 提供，不依赖完整 App 对象。

失败语义：
    run_for_account 返回 False 仅表示「该模板插入步骤执行失败」，
    调用处（登录/启动/game_operations 等）应把它当作该模板识别点击失败处理。
"""
import threading
import types

import config
import custom_ops

SETTINGS_KEY = "template_insert_steps"
# 运行时 stop_event 缺省时的兜底（永不置位）
_DUMMY_EVENT = threading.Event()


def load_map():
    """读取全部插入步骤配置 {var_name: {"timing":.., "steps":[..]}}"""
    s = config.load_settings()
    m = s.get(SETTINGS_KEY) or {}
    return m if isinstance(m, dict) else {}


def get(var_name):
    """返回某模板插入步骤配置 {"timing","steps"}；未配置返回 None"""
    cfg = load_map().get(var_name)
    if not cfg or not isinstance(cfg, dict):
        return None
    if not isinstance(cfg.get("steps"), list):
        return None
    return cfg


def has_steps(var_name):
    """某模板是否配置了非空插入步骤（模板上传向导红勾判定用）"""
    cfg = get(var_name)
    return bool(cfg and cfg.get("steps"))


def save(var_name, timing, steps):
    """保存某模板插入步骤；steps 为空视为删除。返回保存是否成功"""
    steps = [s for s in (steps or []) if isinstance(s, dict)]
    timing = "after" if timing == "after" else "before"
    s = config.load_settings()
    # 注意：load_settings 返回浅拷贝，嵌套 dict 与 DEFAULT_SETTINGS/_settings_cache 共享对象，
    # 必须先 dict() 拷贝再改，避免把数据写进默认配置（导致删文件/重置后仍残留）
    m = dict(s.get(SETTINGS_KEY)) if isinstance(s.get(SETTINGS_KEY), dict) else {}
    if steps:
        m[var_name] = {"timing": timing, "steps": steps}
    else:
        m.pop(var_name, None)
    s[SETTINGS_KEY] = m
    config.save_settings(s)   # 失败内部已打印告警，此处视为成功返回
    return True


def run_for_account(settings, stop_event, account_name, var_name, timing):
    """在模板 var_name 点击前(timing='before')/后('after')执行其插入步骤。

    返回：
      True  = 无配置 / 时序不符 / 无步骤（不执行）或插入步骤执行成功
      False = 该模板插入步骤执行失败（调用处应视为该模板失败）
    """
    if timing not in ("before", "after"):
        return True
    cfg = get(var_name)
    if not cfg or cfg.get("timing") != timing or not cfg.get("steps"):
        return True
    steps = cfg["steps"]
    if stop_event is None:
        stop_event = _DUMMY_EVENT
    label = "点击前" if timing == "before" else "点击后"
    print(f"▶ 模板[{var_name}]插入步骤（{label}）：共 {len(steps)} 步，开始执行...")
    # 最小执行上下文：custom_ops 单步只读 app.settings；stop_event 由入参提供
    ctx = types.SimpleNamespace(settings=settings if settings is not None else {})
    try:
        ok = custom_ops._run_batch_steps(ctx, account_name or "", steps, stop_event)
    except Exception as e:
        print(f"❌ 模板[{var_name}]插入步骤执行异常：{e}")
        ok = False
    print(f"{'✅' if ok else '❌'} 模板[{var_name}]插入步骤（{label}）执行{'完成' if ok else '失败'}")
    return ok


def make_editor_app(app):
    """供 UI（模板上传向导）构造编辑器 app 上下文：
    app 可能为 None（启动分辨率路径），此时用 settings 兜底，保证编辑/测试可用"""
    if app is not None:
        return app
    return types.SimpleNamespace(settings=config.load_settings(),
                                 _stop_event=_DUMMY_EVENT)
