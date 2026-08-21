"""system_package —— 系统包加载器与分级闸（T-973 动态注册）。

系统包目录契约（{SG_SYSTEMS_ROOT}/{system}/，可在仓库外）：
  manifest.yaml    必需——name(=目录名)/display_name/tier/enabled/description/layout
  config/env.{env}.yaml   环境配置（全部层级可用）
  assertions.yaml  可选——声明式断言模板（tier≥template，SELECT-only 守卫）
  extensions.py    可选——代码型扩展（tier=code，register(registry, env_config, db) 钩子）

分级接入（2026-08-21 用户拍板，闸不可绕）：
  ① config    纯配置——注册/编辑/启停即时生效（零代码零重启）
  ② template  +assertions.yaml 模板断言——注册期确定性校验（SELECT-only），
              运行期经 ReadOnlyDb（SELECT-only 硬守卫）执行
  ③ code      +extensions.py——admin 评审通过才加载；评审留痕绑定文件指纹：
              manifest.review.sha256 == sha256(extensions.py) 才放行，
              文件任何改动使指纹失配即自动回到未评审态（改文件绕不过闸）。

layout 字段决定代码加载方式：
  package（默认）——按仓内 Python 包导入 systems.{system}（git 评审留痕，信任）
  extensions      ——按文件位置 importlib 加载 extensions.py（sha256 评审闸）
"""

import hashlib
import importlib.util
import os
import re
from pathlib import Path

import yaml

_ENGINE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _ENGINE_ROOT.parent

# 系统标识 = Python 模块名底线（与 systems_catalog 一致，注册期防线）
SYSTEM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

VALID_TIERS = ("config", "template", "code")
VALID_LAYOUTS = ("package", "extensions")

# extensions 模块缓存：{system: (sha256, module)}——指纹变化即失效重建
_EXT_MODULE_CACHE: dict = {}


def systems_root() -> Path:
    """动态系统包根（SG_SYSTEMS_ROOT 环境变量，缺省仓库 systems/）。"""
    return Path(os.environ.get("SG_SYSTEMS_ROOT") or (_REPO_ROOT / "systems"))


def repo_systems_root() -> Path:
    """仓库内 systems/（tdm 等随 git 走评审的内置适配包）。"""
    return _REPO_ROOT / "systems"


def package_dir(system: str) -> Path:
    """系统包目录：优先动态根，其次仓库根（SG_SYSTEMS_ROOT 指向外部时内置包仍可用）。"""
    dyn = systems_root() / system
    if dyn.is_dir():
        return dyn
    return repo_systems_root() / system


def sha256_of(path) -> str:
    """文件 sha256 十六进制（评审指纹）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ══════════════════════════════════════════════════════════
# manifest 读写
# ══════════════════════════════════════════════════════════

def load_manifest(system: str) -> dict:
    """读 manifest.yaml（不存在返回 {}——按 legacy 包处理）。失败抛 ValueError。"""
    p = package_dir(system) / "manifest.yaml"
    if not p.is_file():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"manifest.yaml 解析失败: {e}") from e
    if not isinstance(raw, dict):
        raise ValueError(f"manifest.yaml 必须是 YAML 对象: {p}")
    tier = raw.get("tier", "code")
    layout = raw.get("layout", "package")
    if tier not in VALID_TIERS:
        raise ValueError(f"manifest.tier 非法: {tier}（允许: {VALID_TIERS}）")
    if layout not in VALID_LAYOUTS:
        raise ValueError(f"manifest.layout 非法: {layout}（允许: {VALID_LAYOUTS}）")
    raw.setdefault("name", system)
    raw.setdefault("display_name", system)
    raw.setdefault("enabled", True)
    raw.setdefault("description", "")
    raw.setdefault("layout", "package")
    return raw


def save_manifest(system: str, manifest: dict) -> Path:
    """写 manifest.yaml（UI 注册/编辑/评审留痕落盘）。

    写入位置：已存在于仓内根的系统（如 tdm）就地更新；其余一律落动态根
    systems_root()——新系统注册不得污染仓库目录。
    """
    dyn = systems_root() / system
    repo_pkg = repo_systems_root() / system
    d = repo_pkg if repo_pkg.is_dir() and not dyn.is_dir() else dyn
    d.mkdir(parents=True, exist_ok=True)
    p = d / "manifest.yaml"
    p.write_text(yaml.safe_dump(manifest, allow_unicode=True,
                                default_flow_style=False, sort_keys=False),
                 encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════
# 代码型评审闸（不可绕）
# ══════════════════════════════════════════════════════════

def extension_gate_status(system: str) -> dict:
    """extensions.py 评审闸状态。

    返回 {present, sha256, approved_sha256, approved_by, approved_at, loadable, reason}
    loadable=False 的 reason 直接给用户（谁审的/指纹为何失配）。
    """
    ext = package_dir(system) / "extensions.py"
    review = (load_manifest(system).get("review") or {})
    approved_sha = str(review.get("sha256") or "")
    present = ext.is_file()
    sha = sha256_of(ext) if present else ""
    loadable = bool(present and approved_sha and sha == approved_sha)
    if not present:
        reason = "extensions.py 不存在（纯配置/模板系统）"
    elif not approved_sha:
        reason = "extensions.py 待评审（admin 评审通过前不加载——闸不可绕）"
    elif sha != approved_sha:
        reason = (f"extensions.py 指纹失配（评审通过的是 {approved_sha[:12]}…，"
                  f"当前 {sha[:12]}…）——文件已改动，需重新评审")
    else:
        reason = ""
    return {"present": present, "sha256": sha, "approved_sha256": approved_sha,
            "approved_by": review.get("approved_by", ""),
            "approved_at": review.get("approved_at", ""),
            "loadable": loadable, "reason": reason}


def load_extensions_module(system: str):
    """按文件位置加载 extensions.py（评审闸内——调用前必须 gate 检查通过）。

    模块缓存按 (system, sha256) 键控：热重建（文件变化）自动失效；
    模块名用 sg_ext_{system} 避免与 systems.{system} 包名冲突。
    """
    ext = package_dir(system) / "extensions.py"
    sha = sha256_of(ext)
    cached = _EXT_MODULE_CACHE.get(system)
    if cached and cached[0] == sha:
        return cached[1]
    mod_name = f"sg_ext_{system}"
    spec = importlib.util.spec_from_file_location(mod_name, ext)
    module = importlib.util.module_from_spec(spec)
    # 系统包内相对导入不可用（按文件加载无包上下文）；注入包路径形式的 __package__ 空
    module.__package__ = ""
    spec.loader.exec_module(module)
    _EXT_MODULE_CACHE[system] = (sha, module)
    return module


# ══════════════════════════════════════════════════════════
# 模板断言（tier=template，SELECT-only 守卫）
# ══════════════════════════════════════════════════════════

_SELECT_ONLY_RE = re.compile(r"^\s*(select|show|describe|explain)\b", re.I)


def _validate_template_sql(sql: str, name: str):
    """注册期确定性校验：SELECT-only + 禁多语句（与 db_oracle.ReadOnlyDb 同底线）。"""
    if not _SELECT_ONLY_RE.match(sql or ""):
        raise ValueError(f"断言模板 '{name}' 的 sql 必须 SELECT/SHOW/DESCRIBE/EXPLAIN 开头")
    if ";" in (sql or ""):
        raise ValueError(f"断言模板 '{name}' 的 sql 禁止多语句（含分号）")


def register_assertions(registry, system: str):
    """加载 assertions.yaml 声明式断言模板 → 注册为 oracle。

    模板格式：
      assertions:
        - name: order_count_matches     # oracle 名（YAML verify: - oracle: 名）
          desc: 订单数与 DB 一致
          sql: "SELECT COUNT(*) AS c FROM orders WHERE user_id = :user_id"
          expect: {c: "#number"}         # schema_match 规则（engine.schema_match）
    返回注册的 oracle 名列表（无文件返回空）。
    """
    p = package_dir(system) / "assertions.yaml"
    if not p.is_file():
        return []
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    entries = raw.get("assertions") or []
    names = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        sql = str(entry.get("sql") or "").strip()
        if not name or not sql:
            raise ValueError(f"断言模板缺少 name/sql: {entry}")
        _validate_template_sql(sql, name)
        expect = entry.get("expect") or {}
        desc = str(entry.get("desc") or f"模板断言（{system}）: {name}")
        registry.oracle(name, _make_template_oracle(name, sql, expect, desc))
        names.append(name)
    return names


def _make_template_oracle(name, sql, expect, desc):
    """构造模板断言 oracle fn——运行期经 rctx DB（ReadOnlyDb SELECT-only 硬守卫）。

    params 中的值支持 {{var}} 插值后以命名参数绑定（防注入）；
    结果行数与 expect 的 schema_match 规则比对（首行）。
    """
    from engine.schema_match import match

    def oracle_fn(params, rctx, ns, record):
        fn_params = dict(params or {})
        bound = {}
        for k, v in fn_params.items():
            if isinstance(v, str):
                from engine.scenario_runner import render
                v = render(v, ns)
            bound[k] = v
        db = rctx.db
        if db is None:
            from engine.scenario_runner import SkipScenario
            raise SkipScenario(f"模板断言 '{name}' 需要 DB 连接（当前环境不可用）",
                               category="db_unavailable")
        rows = db.query(sql, params=bound)
        record.db_traces.append({"purpose": f"assertion:{name}",
                                 "sql": sql, "rows": len(rows),
                                 "excerpt": str(rows[:1])[:200]})
        row = rows[0] if rows else {}
        if expect:
            fail = match(expect, row)
            if fail:
                raise AssertionError(f"模板断言 '{name}' 失败: {fail}（实际首行: {row}）")
        else:
            if not rows:
                raise AssertionError(f"模板断言 '{name}' 失败: 查询无结果行")

    oracle_fn.__doc__ = desc
    return oracle_fn


# ══════════════════════════════════════════════════════════
# 装配入口（bootstrap.build_registry 调用）
# ══════════════════════════════════════════════════════════

def apply_system_package(registry, system: str, env_config: dict, db=None) -> str:
    """把系统包能力装入 registry，返回装载方式（package/extensions/config/legacy）。

    bootstrap 的唯一系统装配入口：
    - 无 manifest → legacy：importlib 导入 systems.{system}（仓内包，现状不变）
    - layout=package → 仓内包导入（manifest 仅提供元信息）
    - layout=extensions → assertions 模板断言（总是装）+ 评审闸内的 extensions.py
    """
    manifest = load_manifest(system)
    if not manifest:
        return "legacy"
    if not manifest.get("enabled", True):
        raise ValueError(f"系统 '{system}' 已停用（manifest.enabled=false）")

    layout = manifest.get("layout", "package")
    if layout == "package":
        return "package"

    # layout=extensions：模板断言（声明式，注册期已 SELECT-only 校验）
    register_assertions(registry, system)

    # 代码型：评审闸（不可绕）——指纹绑定，失配即不加载
    gate = extension_gate_status(system)
    if gate["present"] and not gate["loadable"]:
        print(f"[SpecGuard WARN] 系统 '{system}' 的 extensions.py 未加载——{gate['reason']}；"
              f"当前按配置/模板级降级运行", flush=True)
        return "extensions-gated"
    if gate["present"] and gate["loadable"]:
        from engine.tool_registry import _CTX_REGISTERING_SYSTEM
        module = load_extensions_module(system)
        token = _CTX_REGISTERING_SYSTEM.set(system)
        try:
            if hasattr(module, "register"):
                module.register(registry, env_config, db)
        finally:
            _CTX_REGISTERING_SYSTEM.reset(token)
        return "extensions"
    return "config"


def load_package_env(system: str, env_name: str) -> dict:
    """动态包（layout=extensions）的通用环境配置加载。

    与 systems/{system}/config.py 同语义：${VAR:default} 占位符替换 + DB 密码
    回退（env → SG_DB_PASSWORD → devops 凭据文件）。共享层打底（systems/_shared）。
    """
    import re as _re
    cfg_dir = package_dir(system) / "config"
    path = cfg_dir / f"env.{env_name}.yaml"
    if not path.is_file():
        raise ValueError(f"环境配置不存在: {path}")
    placeholder = _re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")

    def _sub(value):
        if isinstance(value, dict):
            return {k: _sub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_sub(v) for v in value]
        if isinstance(value, str):
            def rep(m):
                var, default = m.group(1), m.group(2)
                v = os.environ.get(var)
                return v if v else (default if default is not None else "")
            return placeholder.sub(rep, value)
        return value

    cfg = _sub(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    # 共享层打底（systems/_shared，存在才合并）
    shared_path = repo_systems_root() / "_shared" / "config" / f"env.{env_name}.yaml"
    if shared_path.is_file():
        shared = _sub(yaml.safe_load(shared_path.read_text(encoding="utf-8")) or {})
        merged = dict(shared)
        merged.update(cfg)
        cfg = merged
    cfg["env_name"] = env_name
    return cfg
