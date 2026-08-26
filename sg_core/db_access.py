"""sg_core.db_access — 只读 DB 访问统一出口（DB 面板/db_evidence/试跑三端共享）。

设计 2026-08-25（docs/superpowers/specs/2026-08-25-DB证据面板与辅助会话-design.md §A1）：
- 守卫链 = ReadOnlyDb._guard（SELECT-only/危险子句/多语句）∪ attribution.SQL_DENY_RE
  （逃逸黑名单：LOCK IN SHARE MODE/LOCK TABLES/HANDLER/LOAD DATA/DO SLEEP 等）——
  任何一端单独的守卫都不删减，统一为并集。
- 进程级连接缓存：键 = (workspace, system, env, db 配置指纹)；ReadOnlyDb._ensure_alive
  自带 ping 重连，实例可长期复用。配置指纹替代单纯 TTL——配置漂移（含测试打桩
  load_env）自动失效重装配，TTL 300s 仅作兜底。
- 插值：vars=None 跳过（db_evidence 现状语义）；vars 传入时走 engine.interpolation，
  缺键诚实报变量名（编辑态试跑引用运行时变量的引导依据）。
- 与存量测试打桩的兼容契约（test_acceptance_fixes.TestDbEvidenceConnector 的 FakeDb）：
  探活与执行一律走 db.query(sql) 单参形态；truncated 经 getattr 兜底——FakeDb 无
  scalar/max_rows 形参/last_truncated 属性，三处若用富接口会让红线测试假失败。
"""
from __future__ import annotations

import re
import threading
import time

SG_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent

# 并集守卫（attribution.py SQL_DENY_RE 全量搬运 + ReadOnlyDb._FORBIDDEN_SELECT 语义经 _guard 覆盖）
_DENY_RE = re.compile(
    r"\b(FOR\s+UPDATE|LOCK\s+IN\s+SHARE\s+MODE|INTO\s+(OUT|DUMP)FILE|LOCK\s+TABLES|"
    r"HANDLER|LOAD\s+DATA|LOAD\s+XML|DO\s+SLEEP)\b",
    re.IGNORECASE)
_ALLOWED_RE = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN)\b", re.IGNORECASE)


class DbAccessError(Exception):
    """db_access 统一错误（守卫拒绝/未配置/插值失败/连接失败）。"""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.hint = hint


# 前导注释剥离（验收复验 2026-08-25 发现：LLM 生成的 SQL 常带 --/--*/ 注释头，
# 原样进守卫会被误判为非查询语句。只剥「前导」注释用于动词判定；
# 危险子句/多语句检查仍对剥后全文执行，行内注释里的关键词保守照查不误放）。
_LEADING_COMMENT_RE = re.compile(
    r"^\s*(?:(?:--[^\n]*(?:\n|$))|(?:#[^\n]*(?:\n|$))|(?:/\*.*?\*/))+",
    re.DOTALL)


def _guard_sql(sql: str) -> None:
    """只读守卫（连接建立前触发；文案与 ReadOnlyDb._guard 同风格）。"""
    s = _LEADING_COMMENT_RE.sub("", sql or "")
    if not _ALLOWED_RE.match(s):
        raise DbAccessError(f"只读守卫拒绝非查询语句: {(sql or '')[:80]}")
    m = _DENY_RE.search(s)
    if m:
        raise DbAccessError(f"只读守卫拒绝危险子句: {m.group(1)}")
    body = s.strip().rstrip(";")
    if ";" in body:
        raise DbAccessError(f"只读守卫拒绝多语句 SQL: {s[:80]}")


def _interpolate(sql: str, vars: dict | None) -> str:
    """vars=None 原样返回；否则插值，缺键报变量名。"""
    if vars is None:
        return sql
    from engine.interpolation import render, RenderError
    try:
        out = render(sql, vars or {})
        return out if isinstance(out, str) else str(out)
    except RenderError as e:
        raise DbAccessError(f"SQL 插值失败: {e}")
    except KeyError as e:
        raise DbAccessError(f"SQL 插值失败: {e}")


def _resolve_system() -> str:
    import os
    from specstd.workspace import resolve_system
    return resolve_system() or os.environ.get("SPEC_GUARD_SYSTEM", "tdm")


def _load_env_cfg(env_name: str) -> dict:
    import importlib
    system = _resolve_system()
    return importlib.import_module(f"systems.{system}").load_env(env_name) or {}


# ── 连接缓存 ──
_CACHE: dict[tuple, tuple[dict, str, float]] = {}  # key -> (dbs, default_name, cached_at)
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 300.0


def invalidate_cache() -> None:
    """清空连接缓存（配置/工作区切换场景兜底）。"""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_key(env_name: str, cfg_fp: str) -> tuple:
    try:
        from specstd.workspace import get_context_workspace
        ws = get_context_workspace() or ""
    except Exception:
        ws = ""
    return (ws, _resolve_system(), env_name, cfg_fp)


def _cfg_fingerprint(db_cfg: dict) -> str:
    """db 段配置指纹（缓存键组成）：配置/凭据占位符变化 → 指纹变 → 自动重装配。"""
    import hashlib
    import json
    return hashlib.sha256(
        json.dumps(db_cfg, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]


def get_db_connections(env_name: str = "") -> tuple[dict, str]:
    """取命名连接注册表（进程级缓存；DB 不可达的 schema 跳过并 WARN——与
    engine.db_oracle.build_db_connections 同语义，但保留实例复用）。

    返回 (dbs: dict[str, ReadOnlyDb], default_name: str)。
    """
    import os
    env_name = env_name or os.environ.get("SG_ENV", "sit")
    cfg = _load_env_cfg(env_name)
    db_cfg = cfg.get("db") or {}
    if not db_cfg:
        raise DbAccessError(
            f"环境配置未设置 db 段（env={env_name}）",
            hint="请在系统配置页补充 DB 只读连接，或检查 systems 配置包 env yaml")
    key = _cache_key(env_name, _cfg_fingerprint(db_cfg))
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and (now - cached[2]) < _CACHE_TTL:
            return cached[0], cached[1]
    # 建连（每 schema 探活；失败跳过该 schema——诚实降级）
    from engine.db_oracle import ReadOnlyDb, normalize_db_config
    conns_cfg, default_name = normalize_db_config(db_cfg)
    dbs: dict = {}
    for name, c in conns_cfg.items():
        if not c.get("host") or not c.get("user"):
            continue
        try:
            db = ReadOnlyDb(
                host=c["host"], port=c.get("port", 3306), user=c["user"],
                password=c.get("password", ""), database=c.get("name", "hr_center"),
                charset=c.get("charset", "utf8mb4"))
            db.query("SELECT 1")  # 探活（单参形态——兼容存量测试 FakeDb 打桩）
            dbs[name] = db
        except Exception as e:
            print(f"[SpecGuard WARN] DB 连接失败（schema={name}），该 schema 不可用: {e}")
    with _CACHE_LOCK:
        _CACHE[key] = (dbs, default_name, time.time())
    return dbs, default_name


def execute_readonly(sql: str, schema: str = "", max_rows: int = 1000,
                     vars: dict | None = None, env_name: str = "",
                     _bypass_cache: bool = False) -> dict:
    """统一只读执行：守卫 → 插值 → 执行。

    返回 {rows: list[dict], row_count: int, truncated: bool, elapsed_ms: int,
    sql_rendered: str}。守卫/配置/插值/连接错误统一抛 DbAccessError（hint 可选）。
    _bypass_cache 仅测试用（绕过连接缓存强制走装配路径）。
    """
    import time as _time
    _guard_sql(sql)
    sql_rendered = _interpolate(sql, vars)
    if _bypass_cache:
        invalidate_cache()
    try:
        dbs, default_name = get_db_connections(env_name)
    except DbAccessError:
        raise
    if not dbs:
        raise DbAccessError(
            "DB 连接不可用（所有 schema 均连接失败或未配置）",
            hint="请检查系统配置页的 DB 连接配置")
    db = dbs.get(schema) if schema else dbs.get(default_name)
    if db is None:
        raise DbAccessError(
            f"schema {schema or default_name!r} 不存在或不可用",
            hint=f"可用 schema: {', '.join(sorted(dbs))}")
    t0 = _time.time()
    try:
        # 单参调用（兼容存量测试 FakeDb 打桩）；ReadOnlyDb 默认上限与本函数默认一致，
        # 非默认 max_rows 由下方二次截断兜底（截断事实并集外抛）。
        rows = db.query(sql_rendered)
    except DbAccessError:
        raise
    except Exception as e:
        raise DbAccessError(f"DB 查询失败: {e}", hint="请检查 SQL 语法与数据源连通性")
    truncated = bool(getattr(db, "last_truncated", False))
    if len(rows) > max_rows:
        rows = rows[:max_rows]
        truncated = True
    return {
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": int((_time.time() - t0) * 1000),
        "sql_rendered": sql_rendered,
    }
