"""T-014：多会话产物地基——emp 维度路径 + 私有/共享状态机制。

覆盖：
1. specguard_dir(emp=) 私有区 / 空=共享区
2. drafts_dir/plans_dir/uploads_dir emp 维度
3. reports_dir/info_packs_dir 不进私有区（天然共享）
4. emp contextvar 透传（set/get/reset）
5. 私有区越权读校验 can_read_private
6. 存量 drafts 迁移脚本（migrate_drafts_emp）
"""

import json
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from specstd.workspace import (
    can_read_private,
    drafts_dir,
    get_context_emp_no,
    info_packs_dir,
    plans_dir,
    reports_dir,
    reset_context_emp_no,
    set_context_emp_no,
    specguard_dir,
    uploads_dir,
)


# ══════════════════════════════════════════════════════════
# 私有区 / 共享区路径
# ══════════════════════════════════════════════════════════

class TestSpecguardDirEmp:
    def test_shared_when_no_emp(self, tmp_path, monkeypatch):
        """emp 为空 → 工作区级共享区（向后兼容）。"""
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        sg = specguard_dir()
        assert sg == tmp_path / ".specguard"
        assert (sg / "README.md").is_file()  # 首次创建生成元数据

    def test_private_when_emp(self, tmp_path, monkeypatch):
        """emp 非空 → {ws}/.specguard/{emp}/ 私有区。"""
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        sg = specguard_dir(emp="90024166")
        assert sg == tmp_path / ".specguard" / "90024166"
        # 私有区同样生成 README/.gitignore（独立目录自解释）
        assert (sg / "README.md").is_file()

    def test_emp_sanitized(self, tmp_path, monkeypatch):
        """emp 含路径穿越（..）时拒绝——回退共享区（防路径穿越）。"""
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        sg = specguard_dir(emp="../evil")
        assert sg == tmp_path / ".specguard"  # 拒绝穿越 → 共享区
        # 未创建穿越目录（.specguard/.. 即 tmp_path 本身，用 evil 目录存在性验证）
        assert not (tmp_path / ".specguard" / "evil").exists()


class TestProductDirsEmp:
    def test_drafts_private(self, tmp_path, monkeypatch):
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        assert drafts_dir(emp="90024166") == tmp_path / ".specguard" / "90024166" / "drafts"
        assert drafts_dir() == tmp_path / ".specguard" / "drafts"  # 兼容共享

    def test_plans_private(self, tmp_path, monkeypatch):
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        assert plans_dir(emp="90024166") == tmp_path / ".specguard" / "90024166" / "plans"
        assert plans_dir() == tmp_path / ".specguard" / "plans"

    def test_uploads_private(self, tmp_path, monkeypatch):
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        assert uploads_dir(emp="90024166") == tmp_path / ".specguard" / "90024166" / "uploads"

    def test_reports_and_info_packs_stay_shared(self, tmp_path, monkeypatch):
        """天然共享产物不进私有区（reports/info_packs）。"""
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        assert reports_dir() == tmp_path / ".specguard" / "reports"
        assert info_packs_dir() == tmp_path / ".specguard" / "info_packs"

    def test_reports_shared_even_with_emp_context(self, tmp_path, monkeypatch):
        """T-014 回归：请求上下文有 emp 时 reports/info_packs 仍强制共享区。

        此前 specguard_dir() 无 emp 参数时回退请求上下文 emp，Web 登录态下
        reports 解析到私有区 → /api/runs/history 空、报告 404（浏览器验证发现）。
        """
        from specstd import workspace as wmod
        monkeypatch.setattr("specstd.workspace.get_workspace_root",
                            lambda name=None: tmp_path)
        token = wmod.set_context_emp_no("90000001")
        try:
            assert reports_dir() == tmp_path / ".specguard" / "reports"
            assert info_packs_dir() == tmp_path / ".specguard" / "info_packs"
            # 私有区产物不受影响（drafts 仍走 emp 私有区）
            assert wmod.drafts_dir() == tmp_path / ".specguard" / "90000001" / "drafts"
        finally:
            wmod.reset_context_emp_no(token)


# ══════════════════════════════════════════════════════════
# emp contextvar 透传
# ══════════════════════════════════════════════════════════

class TestEmpContextVar:
    def test_set_get_reset(self):
        assert get_context_emp_no() is None
        token = set_context_emp_no("90024166")
        assert get_context_emp_no() == "90024166"
        reset_context_emp_no(token)
        assert get_context_emp_no() is None

    def test_context_isolation(self):
        """不同上下文互不干扰（仿 workspace contextvar 语义）。"""
        import contextvars
        t1 = set_context_emp_no("u1")
        t2 = set_context_emp_no("u2")
        assert get_context_emp_no() == "u2"
        reset_context_emp_no(t2)
        assert get_context_emp_no() == "u1"
        reset_context_emp_no(t1)
        assert get_context_emp_no() is None


# ══════════════════════════════════════════════════════════
# 私有区越权读校验
# ══════════════════════════════════════════════════════════

class TestCanReadPrivate:
    def test_owner_can_read(self):
        assert can_read_private(owner_emp="90024166", current_emp="90024166", is_admin=False)

    def test_admin_can_read_any(self):
        assert can_read_private(owner_emp="90024166", current_emp="90000001", is_admin=True)

    def test_other_user_denied(self):
        assert not can_read_private(owner_emp="90024166", current_emp="90024167", is_admin=False)

    def test_empty_owner_denied(self):
        """无归属（共享区）不适用私有校验——空 owner 视为不可私有读。"""
        assert not can_read_private(owner_emp="", current_emp="90024166", is_admin=False)


# ══════════════════════════════════════════════════════════
# 存量 drafts 迁移脚本
# ══════════════════════════════════════════════════════════

class TestMigrateDraftsEmp:
    def _make_sessions(self, root: Path):
        """造会话目录：{root}/agent/sessions/{emp}/{ws}/{sid}.jsonl（首行 meta 带 emp_no）。"""
        for emp, ws, sid in (
            ("90024166", "tdm", "s1"),
            ("90024167", "tdm", "s2"),
        ):
            d = root / "agent" / "sessions" / emp / ws
            d.mkdir(parents=True)
            meta = {"_type": "session_meta", "session_id": sid, "emp_no": emp, "workspace": ws}
            (d / f"{sid}.jsonl").write_text(json.dumps(meta) + "\n", encoding="utf-8")

    def test_migrate_moves_drafts_by_emp(self, tmp_path, monkeypatch):
        """共享 drafts 中的文件按会话归属迁入 {emp}/drafts/。"""
        self._make_sessions(tmp_path)
        ws_root = tmp_path / "ws"
        shared = ws_root / ".specguard" / "drafts"
        shared.mkdir(parents=True)
        (shared / "ST-EMP-001.yaml").write_text("id: ST-EMP-001\n", encoding="utf-8")

        # 会话 JSONL 含 draft 引用（source_files 模拟）
        sess_path = tmp_path / "agent" / "sessions" / "90024166" / "tdm" / "s1.jsonl"
        lines = [json.dumps({"_type": "session_meta", "session_id": "s1", "emp_no": "90024166"}),
                 json.dumps({"role": "tool", "content": "draft 引用 ST-EMP-001.yaml"})]
        sess_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 执行迁移（简化入口：import 后调用内部函数）
        from migrate_drafts_emp import migrate
        moved, kept = migrate(ws_root=ws_root, sessions_root=tmp_path / "agent" / "sessions")
        assert "ST-EMP-001.yaml" in moved
        # 文件已迁入 90024166 私有区
        assert (ws_root / ".specguard" / "90024166" / "drafts" / "ST-EMP-001.yaml").is_file()
        assert not (shared / "ST-EMP-001.yaml").exists()

    def test_migrate_keeps_unattributed(self, tmp_path, monkeypatch):
        """无归属 drafts 保留共享区。"""
        ws_root = tmp_path / "ws"
        shared = ws_root / ".specguard" / "drafts"
        shared.mkdir(parents=True)
        (shared / "ST-ORPHAN-001.yaml").write_text("id: ST-ORPHAN-001\n", encoding="utf-8")

        from migrate_drafts_emp import migrate
        moved, kept = migrate(ws_root=ws_root, sessions_root=tmp_path / "agent" / "sessions")
        assert "ST-ORPHAN-001.yaml" in kept
        assert (shared / "ST-ORPHAN-001.yaml").is_file()
