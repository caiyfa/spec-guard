"""账号解析（T-1039）——试跑前确定「default 别名用哪个账号」。

用户拍板的优先级：**试跑时手动输入 > 运行时按权限解析 > 固定配置账号**。
本服务实现中间档「按权限解析」：静态提取闭包内各别名 Consumed 的资源码需求
→ 调适配包探针（systems/{system}/account_probe.probe，模块存在 = 支持）→
对全部所需资源码都有权限（has_any）的首个配置账号即匹配。

另外两档由既有通道承载，本服务不碰：
- 手动输入 → SG_OVERRIDES {kind: account, name: default, value: "ad:工号"}
  （preflight.apply_overrides 既有语义，弹窗透传即可）
- 固定配置 → 不传覆盖，conftest env_config 原样生效

边界（诚实语义）：只解析 default 别名——显式别名（如 no_access）是场景
刻意的权限语义，自动解析替换它会破坏 fail-secure 类用例；探针失败/无匹配
不阻断试跑，回退固定配置并如实提示。纯读：不落盘、不改配置。
"""

import importlib
import logging
import re
from pathlib import Path

logger = logging.getLogger("specguard.account_resolution")

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_ENV_REF_RE = re.compile(r"^\{\{env\.([A-Za-z0-9_.]+)\}\}$")
_VAR_REF_RE = re.compile(r"^\{\{vars\.([A-Za-z0-9_.]+)\}\}$")
_MAX_CANDIDATES = 6   # 探针候选上限（工号 × 资源码矩阵控量）
_MAX_CODES = 4        # 每别名资源码需求上限


def _resolve_literal(value, env_cfg):
    """资源码字面量/配置引用解析：{{env.x}} / {{vars.x}} → 配置取值。

    env 命名空间与引擎 shared_ns["env"] 同源（scenario_runner T-972 语义）：
    env.resource_code 是 default_resource_code 的别名；env.vars.* 暴露 vars 段；
    其余 env.X 直取配置顶层键。返回 None = 静态不可判（复合插值/引用落空）
    ——调用方单列如实透出，不猜不报假需求。
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    m = _ENV_REF_RE.match(v)
    if m:
        path = m.group(1)
        if path == "resource_code":    # 引擎别名映射：env.resource_code → default_resource_code
            val = env_cfg.get("default_resource_code", "")
            return str(val).strip() or None
        if path.startswith("vars."):
            path, cur = path[len("vars."):], env_cfg.get("vars") or {}
        else:
            cur = env_cfg
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return str(cur).strip() or None
    m = _VAR_REF_RE.match(v)
    if m:
        cur = env_cfg.get("vars") or {}
        for part in m.group(1).split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return str(cur).strip() or None
    if "{{" in v:
        return None
    return v or None


def extract_requirements(scenario_ids, env_cfg, scenarios_root=None):
    """静态提取闭包内「别名 → 资源码需求」。

    来源：flow 的 call 步骤（params.resourceCode）与 fetch_permission 工具步骤
    （with.resource_code / with.account）。未声明 as: 的 call 归 default
    （引擎同语义）。返回 (requirements: {alias: [codes]}, unresolved: [str])。
    """
    import services.scenario_store as store
    from engine.scenario_loader import load_scenarios
    root = str(scenarios_root or store.scenarios_root())
    by_id = {s.id: s for s in load_scenarios(root)}

    req: dict[str, set] = {}
    unresolved: list[str] = []

    def _add(alias, raw, where):
        if raw is None or not str(raw).strip():
            return
        code = _resolve_literal(raw, env_cfg)
        if code:
            req.setdefault(alias, set()).add(code)
        else:
            unresolved.append(f"{where}: resourceCode「{raw}」静态不可解析")

    for sid in scenario_ids:
        sc = by_id.get(sid)
        if sc is None:
            continue
        for step in (sc.flow or []) + (sc.teardown or []):
            if not isinstance(step, dict):
                continue
            call = step.get("call")
            if isinstance(call, dict):
                _add(call.get("as") or "default",
                     (call.get("params") or {}).get("resourceCode"), sid)
            tool = step.get("tool")
            if isinstance(tool, dict) and tool.get("use") == "fetch_permission":
                with_ = tool.get("with") or {}
                _add(with_.get("account") or "default",
                     with_.get("resource_code") or env_cfg.get("default_resource_code"),
                     f"{sid}(fetch_permission)")
    return {a: sorted(c)[:_MAX_CODES] for a, c in req.items()}, unresolved


def resolve(env_name, system, scenario_ids):
    """按权限解析 default 别名账号（探针 hr-center，纯读联网）。

    返回载荷：requirements / candidates（逐候选探针矩阵）/ matched /
    override_value（前端直接塞 SG_OVERRIDES account::default）/ reason /
    errors——每个失败面都诚实透出，不阻断试跑（回退固定配置）。
    """
    payload = {"supported": True, "env": env_name, "requirements": {},
               "unresolved": [], "candidates": [], "matched": None,
               "override_value": "", "reason": "", "errors": []}
    try:
        mod = importlib.import_module(f"systems.{system}")
        env_cfg = mod.load_env(env_name) or {}
    except Exception as e:
        payload["supported"] = False
        payload["reason"] = f"环境配置加载失败（systems.{system}.load_env('{env_name}')）: {e}"
        return payload

    try:
        requirements, unresolved = extract_requirements(scenario_ids, env_cfg)
    except Exception as e:
        payload["supported"] = False
        payload["reason"] = f"场景库加载失败: {e}"
        return payload
    payload["requirements"] = requirements
    payload["unresolved"] = unresolved

    codes = requirements.get("default") or []
    if not codes:
        others = "、".join(sorted(requirements)) if requirements else "未扫描到资源码需求"
        payload["reason"] = f"本链路 default 别名无资源码需求（{others}）——按固定配置执行即可"
        return payload

    try:
        probe_mod = importlib.import_module(f"systems.{system}.account_probe")
    except ImportError:
        payload["supported"] = False
        payload["reason"] = "该系统适配包未提供权限探针（account_probe）——仅支持固定/手动账号"
        return payload

    candidates = []
    for alias, cfg in (env_cfg.get("accounts") or {}).items():
        if not isinstance(cfg, dict) or not cfg.get("emp_no"):
            continue
        if cfg.get("type") == "internal":
            continue
        candidates.append({"alias": alias, "ad": cfg.get("ad", ""),
                           "emp_no": str(cfg["emp_no"]), "probe": {}, "matched": False})
        if len(candidates) >= _MAX_CANDIDATES:
            break
    if not candidates:
        payload["reason"] = "配置账号均无 emp_no（无候选可探针）——回退固定配置或手动输入"
        return payload

    pr = probe_mod.probe(env_cfg, [c["emp_no"] for c in candidates], codes)
    payload["errors"] = pr.get("errors") or []
    results = pr.get("results") or {}
    for c in candidates:
        row = results.get(c["emp_no"]) or {}
        c["probe"] = row
        c["matched"] = bool(row) and all(
            bool((row.get(k) or {}).get("has_any")) for k in codes)
    payload["candidates"] = candidates
    matched = next((c for c in candidates if c["matched"]), None)
    if matched:
        payload["matched"] = {"alias": matched["alias"], "ad": matched["ad"],
                              "emp_no": matched["emp_no"]}
        payload["override_value"] = f"{matched['ad']}:{matched['emp_no']}"
    else:
        payload["reason"] = ("无候选账号满足全部资源码权限——回退固定配置 default"
                             "（执行将如实反映真实权限结果）")
    return payload
