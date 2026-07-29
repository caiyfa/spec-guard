"""轻量 KV 设置存储（系统级开关，K-007 自动更新基线等）。

单表 settings(key, value)。区别于 model_config / notify_config 的领域配置，
本模块存放通用系统开关。
"""

from __future__ import annotations

from services.user_store import _connect, _LOCK, init_db

# K-007：审计完成后自动更新 spec 签名基线（默认 False=手动标记）
KEY_AUDIT_AUTO_UPDATE_BASELINE = "audit_auto_update_baseline"


def _ensure_table():
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)


def get_setting(key: str, default: str = "") -> str:
    _ensure_table()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    _ensure_table()
    with _LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value))


def get_bool(key: str, default: bool = False) -> bool:
    return get_setting(key, "true" if default else "false").lower() == "true"


def set_bool(key: str, value: bool):
    set_setting(key, "true" if value else "false")


def audit_auto_update_baseline() -> bool:
    """是否开启「审计完成自动更新 spec 签名基线」（默认手动）。"""
    return get_bool(KEY_AUDIT_AUTO_UPDATE_BASELINE, False)
