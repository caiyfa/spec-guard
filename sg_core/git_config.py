"""git_config — git 身份与 token 持久化（多用户隔离）。

每个用户（emp_no）独立配置 user.name / user.email / git token：
- token 用 crypto.encrypt 加密落库（同 model_config api_key 方案），
  返回时脱敏（has_token 标记是否已配置）
- 供 commit_delta_changes 覆盖提交身份（git -c user.name= -c user.email=）
- 供 push_delta 注入 HTTPS token 推送远端

存储：workbench.db 的 git_configs 表（复用车贴 model_config CRUD 模式）。
"""

from __future__ import annotations

from datetime import datetime

from sg_core.user_store import db_connect, DB_LOCK, init_db
from sg_core import crypto


# git 配置字段
GIT_CONFIG_FIELDS = ("name", "email", "token")


def _ensure_table():
    """建表（幂等）。"""
    init_db()
    with DB_LOCK, db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS git_configs (
                emp_no TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            )
        """)


def get_git_config(emp_no: str) -> dict:
    """读取用户的 git 配置（token 不解密，返回 has_token 标记）。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT name, email, token FROM git_configs WHERE emp_no=?",
            (emp_no,),
        ).fetchone()
    if row is None:
        return {"name": "", "email": "", "has_token": False}
    token = row["token"]
    return {
        "name": row["name"],
        "email": row["email"],
        "has_token": bool(token) and token.startswith("ENC:"),
    }


def save_git_config(emp_no: str, name: str = "", email: str = "",
                    token: str = "") -> dict:
    """保存用户的 git 配置。token 为空时不清空（= 未修改）；
    token 含 *** 时视为未修改（脱敏回传保护，同 model_config._is_key_unchanged）；
    第一次配置或显示传入非空非脱敏 token 时加密存储。"""
    _ensure_table()
    now = datetime.now().isoformat(timespec="seconds")

    with DB_LOCK, db_connect() as conn:
        existing = conn.execute(
            "SELECT token FROM git_configs WHERE emp_no=?", (emp_no,)
        ).fetchone()

        old_token = existing["token"] if existing else ""

        # 脱敏判断：空字符串 / 含 *** → 不覆盖（保留原值）
        if not token or "***" in token:
            final_token = old_token
        else:
            final_token = crypto.encrypt(token) if token else old_token

        conn.execute("""
            INSERT INTO git_configs (emp_no, name, email, token, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(emp_no) DO UPDATE SET
                name=excluded.name,
                email=excluded.email,
                token=excluded.token,
                updated_at=excluded.updated_at
        """, (emp_no, name, email, final_token, now, now))

    return {"ok": True, "has_token": bool(final_token) and final_token.startswith("ENC:")}


def get_decrypted_token(emp_no: str) -> str:
    """解密返回用户的 git token（供 push 时注入）。无配置时返回空串。"""
    _ensure_table()
    with DB_LOCK, db_connect() as conn:
        row = conn.execute(
            "SELECT token FROM git_configs WHERE emp_no=?", (emp_no,)
        ).fetchone()
    if row is None:
        return ""
    return crypto.decrypt(row["token"] or "")