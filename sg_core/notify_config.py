"""通知配置 CRUD（钉钉/飞书群聊 webhook）。

持久化到 SQLite（workbench.db），webhook_url 和 secret 加密存储（复用链 A-3 crypto）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sg_core.user_store import _connect, _LOCK, init_db
from sg_core import crypto

# 可用渠道
CHANNELS = ("dingtalk", "feishu")

# 可订阅事件（fail/drift/skip 为 T-996 合并 NotifyRegistry 后的用例级事件）
EVENTS = ("vulnerability", "plan_failure", "plan_success", "fail", "drift", "skip")

# 加密字段
ENCRYPTED_FIELDS = ("webhook_url", "secret")

# 可更新字段（非 id / created_by / created_at）
CONFIG_FIELDS = (
    "name", "channel", "webhook_url", "secret",
    "mention_mobiles", "events", "enabled",
    "system", "scenario_pattern",
)


def _ensure_table():
    """建表（幂等）+ 存量库补列（T-996：system/scenario_pattern 用例级过滤维度）。"""
    init_db()
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS notify_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                channel TEXT NOT NULL,
                webhook_url TEXT NOT NULL,
                secret TEXT DEFAULT '',
                mention_mobiles TEXT DEFAULT '',
                events TEXT NOT NULL DEFAULT '["plan_failure","vulnerability"]',
                enabled INTEGER NOT NULL DEFAULT 1,
                system TEXT NOT NULL DEFAULT '',
                scenario_pattern TEXT NOT NULL DEFAULT '*',
                created_by TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            )
        """)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(notify_configs)").fetchall()}
        if "system" not in cols:
            conn.execute("ALTER TABLE notify_configs ADD COLUMN system TEXT NOT NULL DEFAULT ''")
        if "scenario_pattern" not in cols:
            conn.execute("ALTER TABLE notify_configs ADD COLUMN scenario_pattern TEXT NOT NULL DEFAULT '*'")


def _next_id() -> str:
    """生成配置 ID：notify-{uuid8}。"""
    return f"notify-{uuid.uuid4().hex[:8]}"


def list_configs() -> list[dict]:
    """列出全部通知配置（webhook_url/secret 脱敏返回）。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notify_configs ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        c = _row_to_dict(r)
        c["webhook_url"] = crypto.mask(crypto.decrypt(c.get("webhook_url", "")))
        c["secret"] = crypto.mask(crypto.decrypt(c.get("secret", ""))) if c.get("secret") else ""
        result.append(c)
    return result


def get_config(cid: str) -> dict | None:
    """获取单个配置（webhook_url/secret 解密返回完整值）。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM notify_configs WHERE id = ?", (cid,)
        ).fetchone()
    if not row:
        return None
    c = _row_to_dict(row)
    c["webhook_url"] = crypto.decrypt(c.get("webhook_url", ""))
    c["secret"] = crypto.decrypt(c.get("secret", "")) if c.get("secret") else ""
    return c


def create_config(data: dict, created_by: str = "") -> dict:
    """创建通知配置。webhook_url/secret 加密存储。"""
    _ensure_table()
    cid = _next_id()
    now = datetime.now().isoformat(timespec="seconds")

    channel = data.get("channel", "")
    if channel not in CHANNELS:
        raise ValueError(f"不支持的渠道: {channel}（可选: {', '.join(CHANNELS)}）")

    events = data.get("events", ["plan_failure", "vulnerability"])
    if isinstance(events, str):
        events = [e.strip() for e in events.split(",") if e.strip()]
    invalid = [e for e in events if e not in EVENTS]
    if invalid:
        raise ValueError(f"不支持的事件: {invalid}（可选: {', '.join(EVENTS)}）")

    record = {
        "id": cid,
        "name": data.get("name", ""),
        "channel": channel,
        "webhook_url": crypto.encrypt(data.get("webhook_url", "")),
        "secret": crypto.encrypt(data.get("secret", "")) if data.get("secret") else "",
        "mention_mobiles": data.get("mention_mobiles", ""),
        "events": json.dumps(events, ensure_ascii=False),
        "enabled": 1 if data.get("enabled", True) else 0,
        "system": data.get("system") or "",
        "scenario_pattern": data.get("scenario_pattern") or "*",
        "created_by": created_by,
        "created_at": now,
    }
    with _LOCK, _connect() as conn:
        conn.execute("""
            INSERT INTO notify_configs (id, name, channel, webhook_url, secret,
                mention_mobiles, events, enabled, system, scenario_pattern, created_by, created_at)
            VALUES (:id, :name, :channel, :webhook_url, :secret,
                :mention_mobiles, :events, :enabled, :system, :scenario_pattern, :created_by, :created_at)
        """, record)
    return get_config(cid)


def update_config(cid: str, data: dict) -> dict | None:
    """更新通知配置。webhook_url/secret 加密存储。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    sets = []
    values = []
    for field in CONFIG_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if field in ENCRYPTED_FIELDS:
            value = crypto.encrypt(str(value)) if value else ""
            if not value:
                continue  # 空值不更新加密字段
        elif field == "events":
            if isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            value = json.dumps(value, ensure_ascii=False)
        elif field == "enabled":
            value = 1 if value else 0
        else:
            value = str(value)
        sets.append(f"{field} = ?")
        values.append(value)
    if not sets:
        return get_config(cid)
    values.append(cid)
    with _LOCK, _connect() as conn:
        result = conn.execute(
            f"UPDATE notify_configs SET {', '.join(sets)} WHERE id = ?", values
        )
        if result.rowcount == 0:
            return None
    return get_config(cid)


def delete_config(cid: str) -> bool:
    """删除通知配置。"""
    _ensure_table()
    with _LOCK, _connect() as conn:
        result = conn.execute(
            "DELETE FROM notify_configs WHERE id = ?", (cid,)
        )
        return result.rowcount > 0


def get_configs_by_event(event: str) -> list[dict]:
    """获取订阅了指定事件的已启用配置（webhook_url/secret 解密）。

    供 J-2 的 send_notification 调用。
    """
    _ensure_table()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notify_configs WHERE enabled = 1 ORDER BY created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        c = _row_to_dict(r)
        events = c.get("events", [])
        if event in events:
            c["webhook_url"] = crypto.decrypt(c.get("webhook_url", ""))
            c["secret"] = crypto.decrypt(c.get("secret", "")) if c.get("secret") else ""
            result.append(c)
    return result


def _row_to_dict(row) -> dict:
    """将数据库行转为字典。"""
    d = dict(row)
    d["enabled"] = bool(d.get("enabled", 0))
    # events 存为 JSON 字符串，解析回 list
    events_raw = d.get("events", "[]")
    try:
        d["events"] = json.loads(events_raw) if isinstance(events_raw, str) else events_raw
    except (json.JSONDecodeError, TypeError):
        d["events"] = []
    return d
