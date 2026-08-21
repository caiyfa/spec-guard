"""多模型配置 CRUD（多模型多数据源）。

支持注册多个 LLM 模型配置（如 DeepSeek、OpenAI、本地模型），
每个配置独立的 base_url / api_key / model / 高级选项。
持久化到 SQLite（workbench.db）。
"""

from __future__ import annotations

from datetime import datetime

from sg_core.user_store import db_connect, DB_LOCK, init_db
from sg_core import crypto

# 模型配置字段
MODEL_FIELDS = (
    "name", "base_url", "api_key", "model",
    "timeout", "temperature",
    "max_context_tokens", "max_output_tokens",
    "thinking_enabled", "reasoning_effort",
)


def _ensure_table():
    """建表（幂等）。"""
    init_db()
    with DB_LOCK, db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                api_key TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                timeout TEXT NOT NULL DEFAULT '120',
                temperature TEXT NOT NULL DEFAULT '0.7',
                max_context_tokens TEXT NOT NULL DEFAULT '',
                max_output_tokens TEXT NOT NULL DEFAULT '',
                thinking_enabled TEXT NOT NULL DEFAULT 'false',
                reasoning_effort TEXT NOT NULL DEFAULT '',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)


def _is_key_unchanged(value) -> bool:
    """判断 api_key 提交值是否为「未修改」占位（空 或 脱敏掩码），应跳过不覆盖。

    前端列表接口返回脱敏 key（sk-a***bcde），若用户未改 key 就保存，
    脱敏值会随表单回传——直接加密落库会覆盖真实 key（线上事故回归防护）。
    """
    s = str(value or "")
    return s == "" or "***" in s


def _next_id() -> str:
    """生成下一个模型 ID。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            "SELECT id FROM model_configs WHERE id LIKE 'model-%' ORDER BY id"
        ).fetchall()
    max_num = 0
    for r in rows:
        try:
            num = int(r["id"].replace("model-", ""))
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            pass
    return f"model-{max_num + 1:03d}"


def list_models() -> list[dict]:
    """列出全部模型配置（api_key 脱敏返回，前端列表用）。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        rows = conn.execute(
            "SELECT * FROM model_configs ORDER BY is_default DESC, updated_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        m = _row_to_dict(r)
        # 列表默认脱敏：先解密再 mask，兼容明文与密文
        decrypted = crypto.decrypt(m.get("api_key", ""))
        m["has_api_key"] = bool(decrypted)  # 前端占位符提示用（不回显脱敏值）
        m["api_key"] = crypto.mask(decrypted)
        result.append(m)
    return result


def get_model(mid: str) -> dict | None:
    """获取单个模型配置（api_key 解密返回完整值，LLMClient 用）。

    T-951b：id 精确命中优先；未命中且 mid 是用途别名（text/vision）时按
    name 回退——设置页新建模型把名称填为 text/vision 即绑定该用途
    （create_model 自动 id（model-NNN）否则永远无法被 get_model("text") 命中）。
    """
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM model_configs WHERE id = ?", (mid,)
        ).fetchone()
        if row is None and mid in ("text", "vision"):
            row = conn.execute(
                "SELECT * FROM model_configs WHERE name = ?"
                " ORDER BY updated_at DESC LIMIT 1", (mid,)
            ).fetchone()
    if not row:
        return None
    m = _row_to_dict(row)
    m["api_key"] = crypto.decrypt(m.get("api_key", ""))
    return m


def get_default_model() -> dict | None:
    """获取默认模型配置（api_key 解密返回完整值）。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM model_configs WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM model_configs ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
    if not row:
        return None
    m = _row_to_dict(row)
    m["api_key"] = crypto.decrypt(m.get("api_key", ""))
    return m


def create_model(data: dict) -> dict:
    """创建模型配置。"""
    _ensure_table()
    mid = _next_id()
    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "id": mid,
        "name": data.get("name", ""),
        "base_url": data.get("base_url", ""),
        "api_key": crypto.encrypt(data.get("api_key", "")),  # 加密存储
        "model": data.get("model", ""),
        "timeout": data.get("timeout", "120"),
        "temperature": data.get("temperature", "0.7"),
        "max_context_tokens": data.get("max_context_tokens", ""),
        "max_output_tokens": data.get("max_output_tokens", ""),
        "thinking_enabled": data.get("thinking_enabled", "false"),
        "reasoning_effort": data.get("reasoning_effort", ""),
        "is_default": 0,
        "created_at": now,
        "updated_at": now,
    }
    with DB_LOCK, db_connect() as conn:
        conn.execute("""
            INSERT INTO model_configs (id, name, base_url, api_key, model, timeout,
                temperature, max_context_tokens, max_output_tokens,
                thinking_enabled, reasoning_effort, is_default, created_at, updated_at)
            VALUES (:id, :name, :base_url, :api_key, :model, :timeout,
                :temperature, :max_context_tokens, :max_output_tokens,
                :thinking_enabled, :reasoning_effort, :is_default, :created_at, :updated_at)
        """, record)
        # 如果是第一个模型，自动设为默认
        count = conn.execute("SELECT COUNT(*) as c FROM model_configs").fetchone()["c"]
        if count == 1:
            conn.execute("UPDATE model_configs SET is_default = 1 WHERE id = ?", (mid,))
    return get_model(mid)


def update_model(mid: str, data: dict) -> dict | None:
    """更新模型配置。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")
    sets = []
    values = []
    for field in MODEL_FIELDS:
        if field in data:
            value = data[field]
            if field == "api_key":
                if _is_key_unchanged(value):
                    # 空值或脱敏占位 → 视为未修改，不覆盖已存密钥
                    continue
                value = crypto.encrypt(str(value))  # 加密存储
            sets.append(f"{field} = ?")
            values.append(str(value))
    if not sets:
        return get_model(mid)
    sets.append("updated_at = ?")
    values.append(now)
    values.append(mid)
    with DB_LOCK, db_connect() as conn:
        result = conn.execute(
            f"UPDATE model_configs SET {', '.join(sets)} WHERE id = ?", values
        )
        if result.rowcount == 0:
            return None
    return get_model(mid)


def delete_model(mid: str) -> bool:
    """删除模型配置。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        # 不允许删除默认模型（除非是唯一模型）
        row = conn.execute(
            "SELECT is_default FROM model_configs WHERE id = ?", (mid,)
        ).fetchone()
        if not row:
            return False
        count = conn.execute("SELECT COUNT(*) as c FROM model_configs").fetchone()["c"]
        if row["is_default"] == 1 and count > 1:
            return False
        conn.execute("DELETE FROM model_configs WHERE id = ?", (mid,))
        # 如果删除后只剩一个模型，自动设为默认
        if count == 2:
            conn.execute("UPDATE model_configs SET is_default = 1")
    return True


def set_default(mid: str) -> dict | None:
    """设置默认模型。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT id FROM model_configs WHERE id = ?", (mid,)
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE model_configs SET is_default = 0")
        conn.execute("UPDATE model_configs SET is_default = 1 WHERE id = ?", (mid,))
    return get_model(mid)


def _row_to_dict(row) -> dict:
    """将数据库行转为字典。"""
    d = dict(row)
    d["is_default"] = bool(d.get("is_default", 0))
    return d
