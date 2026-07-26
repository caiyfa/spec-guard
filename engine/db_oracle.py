"""通用只读数据库客户端：连接配置驱动 + SELECT-only 守卫。

守卫规则：
- 仅允许 SELECT / SHOW / DESCRIBE / EXPLAIN 开头的语句
- 拒绝多语句（含分号），防止注入写操作
"""

import re

import pymysql
import pymysql.cursors

_ALLOWED = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN)\b", re.IGNORECASE)


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
