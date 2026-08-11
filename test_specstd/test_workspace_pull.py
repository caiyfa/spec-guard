"""specstd.workspace.pull() 测试（K-009：修复 git 子命令返回码被静默忽略）。

全程离线：用临时目录中的本地 git 仓库充当 remote。
隔离方式与 test_acceptance_fixes.py 一致：monkeypatch REGISTRY_PATH / CLONES_DIR / SG_ROOT。
"""

import subprocess
from pathlib import Path

import pytest

import specstd.workspace as wsm
from test_specstd.conftest import create_valid_workspace


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """执行 git 命令，失败即断言（测试基建自身不应失败）。"""
    proc = subprocess.run(
        ["git", "-c", "user.email=test@specguard.local", "-c", "user.name=specguard-test",
         *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} 失败: {proc.stderr}"
    return proc


@pytest.fixture()
def git_workspace(tmp_path, monkeypatch):
    """搭建：本地源仓库（合规 spec 内容）→ register_git 克隆注册。

    返回 (源仓库路径, 工作区名)。注册表/克隆目录全部隔离到 tmp_path。
    """
    monkeypatch.setattr(wsm, "SG_ROOT", tmp_path)
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")

    # 源仓库（充当 remote）
    src = tmp_path / "remote_src"
    create_valid_workspace(src)
    _git(["init", "-b", "main"], cwd=src)
    _git(["add", "-A"], cwd=src)
    _git(["commit", "-m", "init"], cwd=src)

    result = wsm.register_git("ws1", str(src), "tdm", branch="main",
                              activate=False, run_conformance=False)
    assert result["ok"], result.get("error")
    return src, "ws1"


class TestPull:
    def test_pull_no_change(self, git_workspace):
        """远端无新 commit：ok 且 changed=False。"""
        _, name = git_workspace
        result = wsm.pull(name)
        assert result["ok"] is True
        assert result["changed"] is False
        assert result["old_commit"] == result["new_commit"]
        assert "report" in result

    def test_pull_with_new_commit(self, git_workspace):
        """远端新增 commit：changed=True，注册表 last_commit 更新。"""
        src, name = git_workspace
        (src / "specs" / "module1" / "feature1" / "spec.md").write_text(
            "# Module1 - Feature1\n\n### FR-001: 查询功能（更新）\nAC-001\nAC-002\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "update spec"], cwd=src)

        result = wsm.pull(name)
        assert result["ok"] is True
        assert result["changed"] is True
        assert result["old_commit"] != result["new_commit"]
        # 注册表中的 last_commit 已更新为新值
        assert wsm.get_workspace(name).last_commit == result["new_commit"]

    def test_pull_remote_gone_reports_error(self, git_workspace, tmp_path):
        """远端不可达：ok=False 且 error 指明 git 步骤（K-009 修复前会静默成功）。"""
        src, name = git_workspace
        # 修改克隆仓库的 remote URL 到不存在的路径，使 git fetch 失败
        # 不 rename src 目录：Windows 上 .git 对象文件句柄未释放时 rename 会 PermissionError
        clone_dir = wsm.CLONES_DIR / name
        _git(["remote", "set-url", "origin", str(tmp_path / "does_not_exist")], cwd=clone_dir)

        result = wsm.pull(name)
        assert result["ok"] is False
        assert "git fetch 失败" in result["error"]

    def test_pull_non_git_workspace_rejected(self, git_workspace, tmp_path):
        """local 型工作区不支持 pull。"""
        local_dir = tmp_path / "local_ws"
        create_valid_workspace(local_dir)
        reg = wsm.register_local("ws_local", str(local_dir), "tdm",
                                 activate=False, run_conformance=False)
        assert reg["ok"], reg.get("error")

        result = wsm.pull("ws_local")
        assert result["ok"] is False
        assert "不是 git 型" in result["error"]
