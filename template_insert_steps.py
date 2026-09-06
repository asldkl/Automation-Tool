# -*- coding: utf-8 -*-
"""
模板「插入步骤」模块

给某个模板（var_name，如 "Hazard_Operations" 烽火地带入口 / "Special_Ops" 特勤处入口）
配置一段自定义步骤，在自动化"识别点击该模板图片"的点击前 / 点击后执行；执行完自然继续后续流程。

数据存储：
    独立文件 %APPDATA%\\DeltaAutoTool\\template_insert_steps.json
    {
        "Hazard_Operations": {"timing": "before"|"after", "steps": [custom_ops 步骤, ...]},
        ...
    }
    —— 特意不用 settings.json：运行过程中多处会用"启动时的 settings 快照"整份覆盖写回，
      会把运行中途新配的插入步骤清掉；独立文件可避免被覆盖。
    旧版本写入 settings.json 的配置会在首次读取时自动迁移到本文件。

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
import os
import json
import threading
import types

import config
import custom_ops

SETTINGS_KEY = "template_insert_steps"          # 旧版 settings 键（仅用于迁移）
INSERT_STEPS_JSON = os.path.join(config.APP_DATA_DIR, "template_insert_steps.json")
# 运行时 stop_event 缺省时的兜底（永不置位）
_DUMMY_EVENT = threading.Event()

_lock = threading.Lock()
_cache = None        # dict | None（None=尚未加载）


def _read_file():
    """读取文件；文件不存在返回 None，存在但解析失败时备份原文件并返回 {}
    （损坏文件备份保留供手动找回，避免之后 save 整份覆盖时无迹可循）"""
    try:
        with open(INSERT_STEPS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return None
    except Exception:
        try:
            import time
            backup = f"{INSERT_STEPS_JSON}.corrupt.{time.strftime('%Y%m%d_%H%M%S')}"
            os.replace(INSERT_STEPS_JSON, backup)
            print(f"⚠️ 模板插入步骤配置文件损坏，已备份为 {os.path.basename(backup)}，"
                  f"当前按空配置继续（可从备份手动找回其他模板的配置）")
        except Exception:
            pass
        return {}


def _write_file(data):
    """原子写文件（.tmp + os.replace），返回是否成功"""
    try:
        config.ensure_app_data_dir()
        tmp = INSERT_STEPS_JSON + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, INSERT_STEPS_JSON)
        return True
    except Exception as e:
        print(f"⚠️ 模板插入步骤保存失败：{e}")
        return False


def _migrate_from_settings():
    """旧版配置在 settings.json[template_insert_steps]，搬到独立文件（深拷贝，避免与 settings 缓存共享嵌套对象）"""
    try:
        s = config.load_settings()
        old = s.get(SETTINGS_KEY)
        if isinstance(old, dict) and old:
            data = json.loads(json.dumps(old))
            _write_file(data)
            return data
    except Exception:
        pass
    return {}


def load_map():
    """读取全部插入步骤配置 {var_name: {"timing":.., "steps":[..]}}（带内存缓存）"""
    global _cache
    with _lock:
        if _cache is None:
            data = _read_file()
            if data is None:
                data = _migrate_from_settings()
            _cache = data
        return dict(_cache)


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
    """保存某模板插入步骤；steps 为空视为删除。返回写入是否成功（失败时内存缓存不变，重启后可重试）"""
    global _cache
    steps = [s for s in (steps or []) if isinstance(s, dict)]
    timing = "after" if timing == "after" else "before"
    with _lock:
        if _cache is None:
            data = _read_file()
            if data is None:
                data = _migrate_from_settings()
            _cache = data
        m = dict(_cache)
        if steps:
            m[var_name] = {"timing": timing, "steps": steps}
        else:
            m.pop(var_name, None)
        if not _write_file(m):
            return False
        _cache = m
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
