"""通用只读数据库客户端：连接配置驱动 + SELECT-only 守卫。

守卫规则：
- 仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN 开头的语句
- 拒绝多语句（含分号），防止注入写操作

K-055：多 schema 命名连接注册表——微服务系统一个环境常连多个 schema
（hr_center / tdm / uac ...），env yaml 的 db 段支持两种形态：
  旧：db: {host, user, password, name: hr_center}      → 自动视为 default
  新：db: {default: {...hr_center}, tdm: {...}, uac: {...}}
"""

import re

import pymysql
import pymysql.cursors

_ALLOWED = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN)\b", re.IGNORECASE)
# 禁止危险子句（即使 SELECT 前缀也拒绝）
_FORBIDDEN_SELECT = re.compile(
    r"\b(?:INTO\s+(OUTFILE|DATAFILE|DUMPFILE)|FOR\s+UPDATE|FOR\s+SHARE)",
    re.IGNORECASE)


class SqlGuardError(Exception):
    pass


class ReadOnlyDb:
    def __init__(self, host, port, user, password, database, charset="utf8mb4",
                 connect_timeout=10, read_timeout=30):
        self._conn = pymysql.connect(
            host=host, port=int(port), user=user, password=password,
            database=database, charset=charset,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=connect_timeout, read_timeout=read_timeout,
        )

    @staticmethod
    def _guard(sql):
        if not _ALLOWED.match(sql or ""):
            raise SqlGuardError(f"只读守卫拒绝非查询语句: {(sql or '')[:80]}")
        # 禁止危险子句（INTO OUTFILE / FOR UPDATE）
        if _FORBIDDEN_SELECT.search(sql or ""):
            raise SqlGuardError(f"只读守卫拒绝危险子句: {(sql or '')[:80]}")
        # 去掉行尾分号后仍存在分号 → 多语句，拒绝
        body = sql.strip().rstrip(";")
        if ";" in body:
            raise SqlGuardError(f"只读守卫拒绝多语句 SQL: {sql[:80]}")

    def query(self, sql, params=None, max_rows=1000):
        """执行只读查询，返回 list[dict]（超出 max_rows 截断）"""
        self._guard(sql)
        self._ensure_alive()
        with self._conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchmany(max_rows + 1)
        if len(rows) > max_rows:
            return rows[:max_rows]
        return rows

    def query_one(self, sql, params=None):
        rows = self.query(sql, params, max_rows=2)
        return rows[0] if rows else None

    def scalar(self, sql, params=None):
        """返回首行首列的值"""
        row = self.query_one(sql, params)
        if not row:
            return None
        return next(iter(row.values()))

    def _ensure_alive(self):
        try:
            self._conn.ping(reconnect=True)
        except Exception:
            pass

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


def normalize_db_config(db_cfg):
    """db 段归一化为 {名称: 连接配置}（K-055 双形态兼容）。

    旧形态 {host, user, ...} → {"default": 原样}；
    新形态 {default: {...}, tdm: {...}} → 原样（缺 default 时取第一个为 default）。
    返回 (connections_cfg: dict, default_name: str)。
    """
    if not db_cfg:
        return {}, ""
    if "host" in db_cfg:  # 旧单连接形态
        return {"default": db_cfg}, "default"
    conns = {k: v for k, v in db_cfg.items() if isinstance(v, dict) and v.get("host")}
    default_name = "default" if "default" in conns else (next(iter(conns), ""))
    return conns, default_name


def build_db_connections(db_cfg, password_fallback=None):
    """由 db 段构建命名连接注册表（K-055，conftest 与 plan_executor 共用装配）。

    每个连接独立探活（SELECT 1），失败打印 WARN 并跳过（该 schema 能力降级 SKIP），
    不阻断其他连接。password_fallback: 可选回调(cfg)->str，提供环境变量/devops 凭据回退。
    返回 (dbs: dict[str, ReadOnlyDb], default_name: str)。
    """
    conns_cfg, default_name = normalize_db_config(db_cfg)
    dbs = {}
    for name, cfg in conns_cfg.items():
        if not cfg.get("host") or not cfg.get("user"):
            continue
        password = cfg.get("password", "") or (password_fallback(cfg) if password_fallback else "")
        try:
            conn = ReadOnlyDb(
                host=cfg["host"], port=cfg.get("port", 3306),
                user=cfg["user"], password=password,
                database=cfg.get("name", "hr_center"),
                charset=cfg.get("charset", "utf8mb4"),
            )
            conn.scalar("SELECT 1")
            dbs[name] = conn
        except Exception as e:
            print(f"[SpecGuard WARN] DB 连接失败（schema={name}），相关校对能力降级为 SKIP: {e}")
    return dbs, default_name
