"""preflight — 执行前依赖预检扫描（T-311）。

背景：EX-92a9252f 选中 TL-RC-014 执行——账号别名 platformNoCorp 未在环境配置
accounts 定义，跑完才 SKIP（output.log 只剩「账号别名未定义」一句）。
本模块在确认执行弹窗前静态比对闭包内全部场景的执行依赖，缺失先行预警。

依赖来源（合并去重）：
1. requires 声明段（格式 2.3.0）：accounts / env / upstream
2. 静态兜底：flow/verify/teardown 原文正则提取
   - `as: xxx` / `account: xxx` → 账号别名（保留字 none/anonymous 除外）
   - `{{env.xxx}}` → 环境键（点号路径，vars.* 子键）
   - `{{场景ID.xxx}}` → 跨场景变量引用（场景 ID 以大写字母开头）
3. T-502 fixtures：tool 步骤 `with.file` 引用（oss_upload 等文件型工具）→
   比对文件存在性——缺失 = 仓库缺陷（预检阻断），与账号/环境键同类预警

比对目标（与引擎运行期一致）：
- accounts 别名 → env 配置 accounts 段有无定义
- env 键 → env 配置顶层键 / vars 子键
- 跨场景引用 → 引用场景 ID 是否在本次执行闭包内（不在 = EX-8200eada 类
  「变量未定义」提前暴露）
- with.file → 相对项目根（场景库根的上层）判文件存在；含 {{...}} 插值的
  路径静态不可判 → 单列 unknown_file_refs（诚实语义，不报假缺口）
"""

import os
import re
import sys
from pathlib import Path

import yaml

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

_YAML_LOADER = yaml.CSafeLoader if hasattr(yaml, "CSafeLoader") else yaml.SafeLoader

# 静态提取正则（flow/verify/teardown 以 YAML 文本重排后扫描）
_AS_RE = re.compile(r"^\s*as:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", re.M)
_ACCOUNT_RE = re.compile(r"^\s*account:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", re.M)
_ENV_KEY_RE = re.compile(r"\{\{env\.([A-Za-z0-9_.]+)\}\}")
# 跨场景变量引用：{{场景ID.save.字段}}（场景 ID = 大写字母开头 + 字母数字/连字符）
_UPSTREAM_RE = re.compile(r"\{\{([A-Z][A-Z0-9][A-Z0-9_-]*)\.(?:[^.}]+)")

# 保留字账号：as: none/anonymous = 不带 token 匿名调用（引擎语义）
_RESERVED_ACCOUNTS = {"none", "anonymous", "null", "undefined"}


def _load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f.read(), Loader=_YAML_LOADER) or {}


def _static_accounts(text):
    """静态提取账号别名（as:/account: 字段，排除保留字）。"""
    out = set()
    for m in _AS_RE.findall(text or "") + _ACCOUNT_RE.findall(text or ""):
        if m not in _RESERVED_ACCOUNTS:
            out.add(m)
    return out


def _static_env_keys(text):
    """静态提取 {{env.*}} 环境键（点号路径）。"""
    return set(_ENV_KEY_RE.findall(text or ""))


def _static_upstream_refs(text):
    """静态提取跨场景变量引用来源场景 ID。"""
    return set(_UPSTREAM_RE.findall(text or ""))


# T-502：tool 步骤 with.file 文件引用（oss_upload 等文件型工具）
def _static_file_refs(raw) -> list:
    """静态提取 flow/teardown tool 步骤的 with.file 引用（原始字符串，含插值）。

    形态：`- tool: {use: oss_upload, with: {file: "test-data/x.xlsx"}, save: up}`
    （tool 信封的 with 段下 file 键；非 str 值如 dict 形态不在本扫描范围）。
    """
    out = []
    for section in ("flow", "teardown"):
        for step in raw.get(section) or []:
            if not isinstance(step, dict):
                continue
            body = step.get("tool")
            if not isinstance(body, dict):
                continue
            with_ = body.get("with") or {}
            if not isinstance(with_, dict):
                continue
            f = with_.get("file")
            if isinstance(f, str) and f.strip():
                out.append(f.strip())
    return out


def _file_exists(file_path: str, project_root: Path) -> bool:
    """T-502：文件存在性判定——绝对路径直判；相对路径相对项目根解析
    （与 systems/tdm/steps.py oss_upload 的 cwd 相对口径一致——工作台从
    仓库根启动时二者等价；纯读，不进任何写路径）。"""
    p = Path(file_path)
    if p.is_absolute():
        return p.is_file()
    return (project_root / file_path).is_file()


def _split_file_refs(file_refs, project_root):
    """T-502：文件引用二分——含 {{...}} 插值 → unknown（静态不可判）；
    其余比对存在性 → missing（仓库缺陷，预检阻断）。"""
    missing, unknown = [], []
    for f in file_refs:
        if "{{" in f:
            unknown.append(f)
        elif not _file_exists(f, project_root):
            missing.append(f)
    return missing, unknown


# 通用插值提取（未知插值检测用）
_TPL_RE = re.compile(r"\{\{([^{}]+)\}\}")


def _static_save_names(raw) -> set:
    """场景内顶层变量集合：flow/teardown 步骤的 save 名 + set_var vars 键。

    {{save名.字段}} / {{裸名}} 引用这些名字时视为已定义（T-318）。
    """
    names = set()
    for section in ("flow", "teardown"):
        for step in raw.get(section) or []:
            if not isinstance(step, dict) or len(step) != 1:
                continue
            step_type, body = next(iter(step.items()))
            if not isinstance(body, dict):
                continue
            sv = body.get("save")
            if isinstance(sv, str) and sv:
                names.add(sv)
            # tool: {use: set_var, with: {vars: {...}}}——vars 注入顶层命名空间（K-051）
            if step_type == "tool" and body.get("use") == "set_var":
                vars_ = (body.get("with") or {}).get("vars") or {}
                names.update(k for k in vars_ if isinstance(k, str))
    return names


def _static_unresolved_templates(raw, text) -> list:
    """T-318：未知插值检测——{{expr}} 既非 fn.*/env.*/上游引用/场景内 save 变量
    → 运行期「变量未定义」（EX-5c6f4c98：{{random:6}} 是 Apifox 语法，SpecGuard
    不支持，执行前应预警而非跑完 KeyError）。"""
    save_names = _static_save_names(raw)
    out = []
    for expr in _TPL_RE.findall(text or ""):
        expr = expr.strip()
        if expr.startswith("fn.") or expr.startswith("env."):
            continue
        if re.match(r"^[A-Z][A-Z0-9][A-Z0-9_-]*\.", expr):  # 上游场景 ID 引用
            continue
        root = expr.split(".", 1)[0]
        if root in save_names:
            continue
        if expr not in out:
            out.append(expr)
    return out


def _merge_deps(scenario_raw, text):
    """requires 声明 ∪ 静态提取（合并去重）。"""
    req = scenario_raw.get("requires") or {}
    accounts = set(_static_accounts(text))
    accounts |= set(req.get("accounts") or [])
    env_keys = set(_static_env_keys(text))
    env_keys |= set(req.get("env") or [])
    upstream = set(_static_upstream_refs(text))
    upstream |= set(req.get("upstream") or [])
    return sorted(accounts), sorted(env_keys), sorted(upstream)


def _env_has_key(env_config, key):
    """env 键比对——与引擎 env 命名空间语义一致（scenario_runner:98-101）：
    {{env.resource_code}} ← env 配置 default_resource_code（有默认值回退，不缺失）；
    {{env.vars.*}} ← env 配置 vars 子段；其余为 env 配置顶层键。"""
    if key == "resource_code":
        return True  # 引擎回退默认值 TDM_SNAPSHOT_ARCHIVE，运行期不会未定义
    if key.startswith("vars."):
        return (env_config.get("vars") or {}).get(key[5:]) is not None
    return key in env_config


def _closure(scenarios: dict, selected: list) -> dict:
    """依赖闭包（含自身）：BFS 回溯 depends_on。返回 {id: raw}。"""
    seen, stack = {}, list(selected)
    while stack:
        sid = stack.pop()
        if sid in seen:
            continue
        raw = scenarios.get(sid)
        if raw is None:
            continue
        seen[sid] = raw
        deps = raw.get("depends_on") or []
        for d in deps:
            did = d["id"] if isinstance(d, dict) else d
            if did not in seen:
                stack.append(did)
    return seen


def scan_dependencies(scenario_ids, env_name="sit", scenarios_root=None,
                      env_config=None, system: str = "") -> dict:
    """闭包内场景执行依赖预检。

    scenario_ids: 选中场景 ID 列表
    scenarios_root: 场景库根（默认工作区场景库；测试注入）
    env_config: 环境配置 dict（默认 systems.{system}.load_env(env_name)）
    system: 被测系统（默认工作区/SPEC_GUARD_SYSTEM/tdm）

    返回：{env, system, scenarios:[...], accounts, env_keys, upstream_refs,
          missing_accounts, missing_env, unresolved_upstream, has_gaps, error?}
    """
    root = Path(scenarios_root) if scenarios_root else None
    env = env_config if env_config is not None else _load_env(env_name, system)

    # 全库场景 YAML（id → raw）
    scenarios: dict = {}
    if root is None:
        from services.scenario_store import scenarios_root as _ss_root
        root = Path(_ss_root())
    for dirpath, _dirs, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            p = Path(dirpath) / fn
            try:
                raw = _load_yaml(p)
            except Exception:
                continue
            sid = raw.get("id")
            if sid:
                scenarios[str(sid)] = raw

    # 未知选中场景 → error（前端提示，不抛异常）
    unknown = [s for s in scenario_ids if s not in scenarios]
    if unknown:
        return {"error": f"未知场景: {', '.join(unknown)}", "scenarios": []}

    closure = _closure(scenarios, scenario_ids)
    env_accounts = (env or {}).get("accounts") or {}
    # T-502：场景库根的上层 = 项目根（scenarios/ 与 test-data/ 同级）
    project_root = root.parent

    items, all_accounts, all_env, all_up, all_unresolved = [], set(), set(), set(), set()
    all_files, all_unknown = set(), set()
    for sid, raw in sorted(closure.items()):
        # flow/verify/teardown 以 YAML 文本重排（dict repr 无法跑正则）
        text = ""
        for section in ("flow", "verify", "teardown"):
            val = raw.get(section)
            if val:
                text += yaml.safe_dump(val, allow_unicode=True) + "\n"
        accounts, env_keys, upstream = _merge_deps(raw, text)
        miss_acc = [a for a in accounts if a not in env_accounts]
        miss_env = [k for k in env_keys if not _env_has_key(env, k)]
        miss_up = [u for u in upstream if u not in closure]
        # T-318：未知插值（{{random:6}} 类）——运行期变量未定义提前预警
        unresolved = _static_unresolved_templates(raw, text)
        # T-502：fixtures 文件引用——缺失 = 仓库缺陷（预检阻断）；插值路径不可判
        file_refs = _static_file_refs(raw)
        missing_files, unknown_file_refs = _split_file_refs(file_refs, project_root)
        all_accounts |= set(accounts)
        all_env |= set(env_keys)
        all_up |= set(upstream)
        all_unresolved |= set(unresolved)
        all_files |= set(file_refs)
        all_unknown |= set(unknown_file_refs)
        items.append({
            "id": sid,
            "accounts": accounts, "env_keys": env_keys, "upstream_refs": upstream,
            "unresolved_templates": unresolved,
            "file_refs": file_refs,
            "missing_files": missing_files, "unknown_file_refs": unknown_file_refs,
            "missing_accounts": miss_acc, "missing_env": miss_env,
            "unresolved_upstream": miss_up,
            "has_gaps": bool(miss_acc or miss_env or miss_up or unresolved
                             or missing_files or unknown_file_refs),
        })

    def _group(attr, key_name="key"):
        """缺失项按「键 → 涉及场景」归组。"""
        m: dict = {}
        for it in items:
            for v in it[attr]:
                m.setdefault(v, []).append(it["id"])
        return [{key_name: k, "scenarios": sorted(v)} for k, v in m.items()]

    has_gaps = any(it["has_gaps"] for it in items)
    from specstd.workspace import resolve_system
    return {
        "env": env_name,
        "system": resolve_system(system),
        "selected": list(scenario_ids),
        "scenario_count": len(closure),
        "scenarios": items,
        "accounts": sorted(all_accounts),
        "env_keys": sorted(all_env),
        "upstream_refs": sorted(all_up),
        "unresolved_templates": sorted(all_unresolved),
        "file_refs": sorted(all_files),
        "missing_accounts": _group("missing_accounts", "account"),
        "missing_env": _group("missing_env", "key"),
        "unresolved_upstream": _group("unresolved_upstream", "ref"),
        "unresolved_templates_gaps": _group("unresolved_templates", "tpl"),
        "missing_files": _group("missing_files", "file"),
        "unknown_file_refs": sorted(all_unknown),
        "unknown_file_refs_gaps": _group("unknown_file_refs", "file"),
        "has_gaps": has_gaps,
    }


def scan_compliance(scenarios_root=None) -> dict:
    """T-313：全库格式合规缺口扫描——Agent 更新已有场景的依据。

    对每个场景比对「requires 声明」与「静态提取的 flow/verify/teardown 依赖」：
    - missing_*: flow 用到但 requires 未声明（2.3.0 存量场景缺口，需补声明）
    - extra_requires: requires 声明了但 flow 未用到（冗余，WARN）
    - t8_violations: requires.upstream 不在 depends_on（T8 语义违规）

    返回 {total, compliant_count, gaps: [...], summary}。纯读。
    """
    root = Path(scenarios_root) if scenarios_root else None
    if root is None:
        from services.scenario_store import scenarios_root as _ss_root
        root = Path(_ss_root())

    scenarios: dict = {}
    for dirpath, _dirs, filenames in os.walk(root):
        for fn in sorted(filenames):
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            p = Path(dirpath) / fn
            try:
                raw = _load_yaml(p)
            except Exception:
                continue
            sid = raw.get("id")
            if sid:
                scenarios[str(sid)] = raw

    gaps = []
    for sid, raw in sorted(scenarios.items()):
        text = ""
        for section in ("flow", "verify", "teardown"):
            val = raw.get(section)
            if val:
                text += yaml.safe_dump(val, allow_unicode=True) + "\n"
        # 纯静态提取（不含 requires）——与声明比对，才能暴露「用到未声明」
        accounts = set(_static_accounts(text))
        env_keys = set(_static_env_keys(text))
        upstream = set(_static_upstream_refs(text))
        # T-502：fixtures 文件引用存在性（缺失 = 仓库缺陷）
        file_refs = _static_file_refs(raw)
        missing_files, unknown_file_refs = _split_file_refs(file_refs, root.parent)
        req = raw.get("requires") or {}
        declared = {"accounts": set(req.get("accounts") or []),
                    "env": set(req.get("env") or []),
                    "upstream": set(req.get("upstream") or [])}
        missing_accounts = sorted(accounts - declared["accounts"])
        missing_env = sorted(env_keys - declared["env"])
        missing_upstream = sorted(upstream - declared["upstream"])
        extra_requires = sorted(
            (declared["accounts"] | declared["env"] | declared["upstream"]) - accounts - env_keys - upstream)
        deps = {d["id"] if isinstance(d, dict) else d for d in (raw.get("depends_on") or [])}
        t8 = sorted(declared["upstream"] - deps)
        # T-318：未知插值（{{random:6}} 类）——非法语法，执行前预警
        unresolved = _static_unresolved_templates(raw, text)
        if (missing_accounts or missing_env or missing_upstream or extra_requires
                or t8 or unresolved or missing_files or unknown_file_refs):
            gaps.append({
                "scenario_id": sid,
                "missing_accounts": missing_accounts,
                "missing_env": missing_env,
                "missing_upstream": missing_upstream,
                "extra_requires": extra_requires,
                "t8_violations": t8,
                "unresolved_templates": unresolved,
                "missing_files": missing_files,
                "unknown_file_refs": unknown_file_refs,
            })

    by_type = {"missing_accounts": 0, "missing_env": 0, "missing_upstream": 0,
               "extra_requires": 0, "t8_violations": 0, "unresolved_templates": 0,
               "missing_files": 0, "unknown_file_refs": 0}
    for g in gaps:
        for k in by_type:
            by_type[k] += len(g[k])
    return {
        "total": len(scenarios),
        "compliant_count": len(scenarios) - len(gaps),
        "gaps": gaps,
        "summary": {"gap_scenarios": len(gaps), **by_type},
    }


def apply_overrides(cfg: dict, overrides) -> dict:
    """T-312：执行变量覆盖——弹窗输入值合并进环境配置（替代改配置文件）。

    overrides: [{kind: "account"|"env", name: 别名/键, value: 值}]
    - account: cfg.accounts[name] = {ad, emp_no?}（value 格式 "ad" 或 "ad:emp_no"）
    - env: 顶层键直接赋值；vars.xxx → cfg.vars[xxx]
    空 name/value 忽略；返回副本，不落盘、不改原配置。
    conftest 从 SG_OVERRIDES 环境变量读取后调用本函数（与预检同源，避免双份语义）。
    """
    if not overrides:
        return cfg
    cfg = dict(cfg)
    for ov in overrides or []:
        if not isinstance(ov, dict):
            continue
        kind = ov.get("kind")
        name = str(ov.get("name") or "").strip()
        value = str(ov.get("value") or "").strip()
        if not name or not value:
            continue
        if kind == "account":
            accounts = dict(cfg.get("accounts") or {})
            parts = value.split(":", 1)
            info = {"ad": parts[0].strip()}
            if len(parts) > 1 and parts[1].strip():
                info["emp_no"] = parts[1].strip()
            accounts[name] = info
            cfg["accounts"] = accounts
        elif kind == "env":
            if name.startswith("vars."):
                cfg.setdefault("vars", {})[name[5:]] = value
            else:
                cfg[name] = value
    return cfg


def _load_env(env_name: str, system: str) -> dict:
    """加载环境配置（与 runs/accounts 端点同源）。失败时告警并返回空（不抛）。"""
    import importlib
    from specstd.workspace import resolve_system
    sys_name = resolve_system(system)
    try:
        mod = importlib.import_module(f"systems.{sys_name}")
        return mod.load_env(env_name) or {}
    except Exception as e:
        print(f"[SpecGuard WARN] preflight 环境配置加载失败 "
              f"(systems.{sys_name}.load_env('{env_name}')): {type(e).__name__}: {e}")
        return {}
