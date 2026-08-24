"""test_menu_migration — 菜单种子迁移测试（T-1010「系统配置」三栏合一）。

覆盖：
- 存量库（含 menu-env-config / menu-systems / menu-workspace 授权）init_db 后：
  三个旧菜单删除、授权无损映射到 menu-system-config、新菜单落库
- menu-settings label 由「系统设置」同步为「基础设置」（upsert UPDATE 分支）
- 迁移幂等：二次 init_db 无副作用
- 全新库：直接按种子落库，无旧菜单
"""

import sqlite3
from pathlib import Path

from workbench.backend.services import rbac_store


def _make_legacy_db(db_path: Path):
    """造一个 T-1010 之前的存量库：旧菜单三件套 + admin 授权。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rbac_store.init_db(db_path)  # 先按新种子建库
    conn.close()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    now = "2026-08-01 00:00:00"
    for key, label, path, parent, sort, is_system in [
        ("menu-workspace", "工作区中心", "/workspace", "group-overview", 3, 0),
        ("menu-env-config", "环境配置", "/env-config", "group-system", 3, 0),
        ("menu-systems", "系统包管理", "/systems", "group-system", 5, 1),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO menus (menu_key,label,icon,path,parent_key,sort,visible,is_system,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,1,?,?,?)", (key, label, "", path, parent, sort, is_system, now, now))
        conn.execute("INSERT OR IGNORE INTO role_menus (role_key,menu_key) VALUES ('admin',?)", (key,))
    conn.execute("UPDATE menus SET label='系统设置' WHERE menu_key='menu-settings'")
    conn.commit()
    conn.close()


def _menu_keys(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    keys = {r[0] for r in conn.execute("SELECT menu_key FROM menus")}
    conn.close()
    return keys


def _grants(db_path: Path, role: str = "admin") -> set[str]:
    conn = sqlite3.connect(str(db_path))
    keys = {r[0] for r in conn.execute("SELECT menu_key FROM role_menus WHERE role_key=?", (role,))}
    conn.close()
    return keys


class TestSystemConfigMigration:
    def test_legacy_menus_remapped_and_removed(self, tmp_path):
        db = tmp_path / "wb.db"
        _make_legacy_db(db)
        rbac_store.init_db(db)  # 触发迁移

        keys = _menu_keys(db)
        assert "menu-system-config" in keys
        for old in ("menu-env-config", "menu-systems", "menu-workspace"):
            assert old not in keys, f"旧菜单 {old} 应被删除"

        grants = _grants(db)
        assert "menu-system-config" in grants, "旧授权应无损映射到 menu-system-config"
        for old in ("menu-env-config", "menu-systems", "menu-workspace"):
            assert old not in grants

    def test_settings_label_renamed(self, tmp_path):
        db = tmp_path / "wb.db"
        _make_legacy_db(db)
        rbac_store.init_db(db)

        conn = sqlite3.connect(str(db))
        label = conn.execute("SELECT label FROM menus WHERE menu_key='menu-settings'").fetchone()[0]
        path = conn.execute("SELECT path FROM menus WHERE menu_key='menu-system-config'").fetchone()[0]
        conn.close()
        assert label == "基础设置"
        assert path == "/system-config"

    def test_migration_idempotent(self, tmp_path):
        db = tmp_path / "wb.db"
        _make_legacy_db(db)
        rbac_store.init_db(db)
        rbac_store.init_db(db)  # 二次迁移无副作用

        keys = _menu_keys(db)
        assert "menu-system-config" in keys
        assert "menu-env-config" not in keys
        conn = sqlite3.connect(str(db))
        n = conn.execute("SELECT COUNT(*) FROM role_menus WHERE menu_key='menu-system-config'").fetchone()[0]
        conn.close()
        assert n == 1, "重复迁移不得产生重复授权"

    def test_fresh_db_has_new_menu(self, tmp_path):
        db = tmp_path / "wb.db"
        rbac_store.init_db(db)
        keys = _menu_keys(db)
        assert "menu-system-config" in keys
        assert "menu-systems" not in keys
        assert "menu-env-config" not in keys
        assert "menu-workspace" not in keys
