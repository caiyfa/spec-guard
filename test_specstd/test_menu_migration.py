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


class TestAgentSplitMenus:
    """T-1039 对话双菜单拆分（测试对话 /agent · 产品对话 /agent-product）。"""

    def test_fresh_db_has_split_menus(self, tmp_path):
        db = tmp_path / "wb.db"
        rbac_store.init_db(db)
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT label,path,parent_key,sort FROM menus WHERE menu_key='menu-agent-product'").fetchone()
        agent = conn.execute(
            "SELECT label,path,sort FROM menus WHERE menu_key='menu-agent'").fetchone()
        drafts = conn.execute("SELECT sort FROM menus WHERE menu_key='menu-drafts'").fetchone()
        conn.close()
        assert row == ("产品对话", "/agent-product", "group-agent", 1)
        assert agent == ("测试对话", "/agent", 0), "原「Agent 对话」更名「测试对话」"
        assert drafts[0] == 2, "草稿评审顺位后移"

    def test_legacy_label_aligned_by_upsert(self, tmp_path):
        """存量库（旧 label「Agent 对话」）init_db 后 label 被 upsert UPDATE 分支对齐。"""
        db = tmp_path / "wb.db"
        rbac_store.init_db(db)
        conn = sqlite3.connect(str(db))
        conn.execute("UPDATE menus SET label='Agent 对话' WHERE menu_key='menu-agent'")
        conn.execute("DELETE FROM menus WHERE menu_key='menu-agent-product'")  # 模拟 T-1039 前存量库
        conn.commit()
        conn.close()
        rbac_store.init_db(db)
        conn = sqlite3.connect(str(db))
        label = conn.execute("SELECT label FROM menus WHERE menu_key='menu-agent'").fetchone()[0]
        has_product = conn.execute(
            "SELECT 1 FROM menus WHERE menu_key='menu-agent-product'").fetchone()
        conn.close()
        assert label == "测试对话"
        assert has_product, "存量库应补种产品对话菜单"

    def test_public_split_menus_visible_without_grants(self, tmp_path):
        """双对话菜单均为公开菜单：零授权角色可见；/agent 带 end 精确匹配（防前缀撞车双高亮）。"""
        db = tmp_path / "wb.db"
        rbac_store.init_db(db)
        groups = rbac_store.menus_for_user(["viewer"], db)
        agent_group = next(g for g in groups if g["label"] == "Agent")
        paths = {i["to"]: i["end"] for i in agent_group["items"]}
        assert "/agent" in paths and "/agent-product" in paths
        assert paths["/agent"] is True, "存在 /agent-product 时 /agent 必须 end 精确匹配"
        assert paths["/agent-product"] is True
