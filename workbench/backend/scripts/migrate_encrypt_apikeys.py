"""迁移存量明文 api_key 为加密存储（幂等，可重复执行）。

用法（仓库根目录）：
    python workbench/backend/scripts/migrate_encrypt_apikeys.py

说明：
    - 只处理 model_configs 表中未加密（无 ENC: 前缀）的 api_key
    - 已加密或为空的记录自动跳过，可安全重复执行
    - 执行前建议备份 workbench/backend/data/workbench.db
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services import crypto  # noqa: E402
from services.user_store import db_connect, DB_LOCK, init_db  # noqa: E402


def migrate() -> tuple[int, int]:
    """迁移 model_configs 中的明文 api_key。

    Returns:
        (已迁移条数, 跳过条数)
    """
    init_db()
    with DB_LOCK, db_connect() as conn:
        # 表不存在则无数据可迁移（全新部署）
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='model_configs'"
        ).fetchone()
        if not table:
            print("model_configs 表不存在（全新部署），无需迁移")
            return 0, 0

        rows = conn.execute("SELECT id, api_key FROM model_configs").fetchall()

    migrated = skipped = 0
    with DB_LOCK, db_connect() as conn:
        for row in rows:
            key = row["api_key"] or ""
            if not key or crypto.is_encrypted(key):
                skipped += 1
                continue
            conn.execute(
                "UPDATE model_configs SET api_key = ? WHERE id = ?",
                (crypto.encrypt(key), row["id"]),
            )
            migrated += 1
    return migrated, skipped


if __name__ == "__main__":
    m, s = migrate()
    print(f"迁移完成：加密 {m} 条，跳过 {s} 条（已加密或为空）")
