"""F-1-1：`.specguard/` 路径函数测试。

验证：
1. 工作区激活后自动创建 {workspace}/.specguard/（含 README + .gitignore）
2. .specguard/ 位置可配置（自定义路径）
3. 自定义路径穿越防护生效（如 ../.. 被拒绝）
4. drafts / plans / reports / info_packs 子目录正确返回
5. README + .gitignore 幂等生成（不覆盖已有）
6. 多工作区隔离：不同工作区的 .specguard/ 不混淆
7. 无激活工作区时 raise RuntimeError
"""

import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from test_specstd.helpers import create_valid_workspace


# ══════════════════════════════════════════════════════════
# 测试辅助
# ══════════════════════════════════════════════════════════

def _setup_workspace(tmp_path, monkeypatch, name="tdm"):
    """创建并激活一个测试工作区，返回工作区根路径。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    ws = create_valid_workspace(tmp_path / "repo")
    result = wsm.register_local(name, str(ws), "tdm", activate=True)
    assert result["ok"] is True
    return ws


# ══════════════════════════════════════════════════════════
# specguard_dir：默认路径
# ══════════════════════════════════════════════════════════

class TestSpecguardDirDefault:
    def test_creates_specguard_dir_on_activation(self, tmp_path, monkeypatch):
        """激活工作区后，{workspace}/.specguard/ 自动创建。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        sg = wsm.specguard_dir()
        assert sg.is_dir()
        assert sg.name == ".specguard"
        assert sg.parent == ws

    def test_readme_generated(self, tmp_path, monkeypatch):
        """首次创建生成 README.md。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        sg = wsm.specguard_dir()
        readme = sg / "README.md"
        assert readme.is_file()
        content = readme.read_text(encoding="utf-8")
        assert "drafts" in content
        assert "plans" in content
        assert "reports" in content
        assert "info_packs" in content

    def test_gitignore_generated(self, tmp_path, monkeypatch):
        """首次创建生成 .gitignore（忽略 reports/drafts，保留 plans/info_packs）。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        sg = wsm.specguard_dir()
        gi = sg / ".gitignore"
        assert gi.is_file()
        content = gi.read_text(encoding="utf-8")
        assert "reports/" in content
        assert "drafts/" in content
        # plans / info_packs 被注释保留
        assert "# plans/" in content
        assert "# info_packs/" in content

    def test_meta_idempotent(self, tmp_path, monkeypatch):
        """多次调用不覆盖已有的 README / .gitignore。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        sg1 = wsm.specguard_dir()
        # 修改 README 内容
        readme = sg1 / "README.md"
        custom_content = "# CUSTOM README\n"
        readme.write_text(custom_content, encoding="utf-8")
        # 再次调用
        sg2 = wsm.specguard_dir()
        assert sg1 == sg2
        assert readme.read_text(encoding="utf-8") == custom_content

    def test_explicit_workspace_root(self, tmp_path, monkeypatch):
        """显式传入 workspace_root 参数。"""
        import specstd.workspace as wsm
        ws = create_valid_workspace(tmp_path / "repo")
        sg = wsm.specguard_dir(workspace_root=ws)
        assert sg == ws / ".specguard"
        assert sg.is_dir()

    def test_no_active_workspace_raises(self, tmp_path, monkeypatch):
        """无激活工作区时 raise RuntimeError。"""
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        # 无激活工作区
        with pytest.raises(RuntimeError, match="无激活工作区"):
            wsm.specguard_dir()


# ══════════════════════════════════════════════════════════
# specguard_dir：自定义路径
# ══════════════════════════════════════════════════════════

class TestSpecguardDirCustomPath:
    def test_custom_path_used(self, tmp_path, monkeypatch):
        """custom_path 非空时使用自定义位置。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        custom = tmp_path / "external" / "specguard-artifacts"
        sg = wsm.specguard_dir(custom_path=str(custom))
        assert sg.is_dir()
        assert sg == custom.resolve()

    def test_custom_path_generates_meta(self, tmp_path, monkeypatch):
        """自定义路径也生成 README + .gitignore。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        custom = tmp_path / "external-sg"
        sg = wsm.specguard_dir(custom_path=str(custom))
        assert (sg / "README.md").is_file()
        assert (sg / ".gitignore").is_file()

    def test_custom_path_traversal_rejected(self, tmp_path, monkeypatch):
        """自定义路径含 ../.. 被拒绝。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="非法自定义路径"):
            wsm.specguard_dir(custom_path="../../etc/passwd")

    def test_custom_path_double_dot_rejected(self, tmp_path, monkeypatch):
        """自定义路径含 .. 被拒绝。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="非法自定义路径"):
            wsm.specguard_dir(custom_path="../sibling")

    def test_custom_path_empty_string_falls_back_to_default(self, tmp_path, monkeypatch):
        """空字符串 custom_path 回退到默认 {workspace}/.specguard/。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        sg = wsm.specguard_dir(custom_path="")
        assert sg == ws / ".specguard"


# ══════════════════════════════════════════════════════════
# 子目录函数
# ══════════════════════════════════════════════════════════

class TestSubDirs:
    def test_drafts_dir(self, tmp_path, monkeypatch):
        """drafts_dir() 返回 .specguard/drafts。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        d = wsm.drafts_dir()
        assert d == ws / ".specguard" / "drafts"

    def test_plans_dir(self, tmp_path, monkeypatch):
        """plans_dir() 返回 .specguard/plans。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        d = wsm.plans_dir()
        assert d == ws / ".specguard" / "plans"

    def test_reports_dir(self, tmp_path, monkeypatch):
        """reports_dir() 返回 .specguard/reports。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        d = wsm.reports_dir()
        assert d == ws / ".specguard" / "reports"

    def test_info_packs_dir(self, tmp_path, monkeypatch):
        """info_packs_dir() 返回 .specguard/info_packs。"""
        import specstd.workspace as wsm
        ws = _setup_workspace(tmp_path, monkeypatch)
        d = wsm.info_packs_dir()
        assert d == ws / ".specguard" / "info_packs"

    def test_subdirs_not_auto_created(self, tmp_path, monkeypatch):
        """子目录函数只返回路径，不自动创建（由调用方按需 mkdir）。"""
        import specstd.workspace as wsm
        _setup_workspace(tmp_path, monkeypatch)
        d = wsm.drafts_dir()
        assert not d.exists()  # 路径存在但不自动创建


# ══════════════════════════════════════════════════════════
# 多工作区隔离
# ══════════════════════════════════════════════════════════

class TestMultiWorkspaceIsolation:
    def test_different_workspaces_different_specguard_dirs(self, tmp_path, monkeypatch):
        """不同工作区的 .specguard/ 路径不同。"""
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")

        ws1 = create_valid_workspace(tmp_path / "repo1")
        ws2 = create_valid_workspace(tmp_path / "repo2")
        wsm.register_local("ws1", str(ws1), "tdm", activate=True)
        wsm.register_local("ws2", str(ws2), "tdm", activate=True)

        # 激活 ws1
        wsm.set_active("ws1")
        sg1 = wsm.specguard_dir()

        # 激活 ws2
        wsm.set_active("ws2")
        sg2 = wsm.specguard_dir()

        assert sg1 != sg2
        assert sg1 == ws1 / ".specguard"
        assert sg2 == ws2 / ".specguard"

    def test_context_workspace_isolation(self, tmp_path, monkeypatch):
        """通过 context var 切换工作区时，specguard_dir 随之变化。"""
        import specstd.workspace as wsm
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")

        ws1 = create_valid_workspace(tmp_path / "repo1")
        ws2 = create_valid_workspace(tmp_path / "repo2")
        wsm.register_local("ws1", str(ws1), "tdm", activate=False)
        wsm.register_local("ws2", str(ws2), "tdm", activate=False)

        # 通过 context var 设置 ws1
        token = wsm.set_context_workspace("ws1")
        sg1 = wsm.specguard_dir()
        assert sg1 == ws1 / ".specguard"
        wsm.reset_context_workspace(token)

        # 通过 context var 设置 ws2
        token2 = wsm.set_context_workspace("ws2")
        sg2 = wsm.specguard_dir()
        assert sg2 == ws2 / ".specguard"
        wsm.reset_context_workspace(token2)
