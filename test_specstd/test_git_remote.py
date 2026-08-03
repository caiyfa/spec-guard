"""specstd.workspace git 历史与远程新鲜度测试（git_log / remote_head_status /
check_remote_sync / remote_file_marks）。

全程离线：用临时目录中的本地 git 仓库充当 remote。
隔离方式与 test_workspace_pull.py 一致：monkeypatch REGISTRY_PATH / CLONES_DIR / SG_ROOT。
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
    # 远程检查 TTL 缓存是模块级全局，隔离到每个测试
    wsm._remote_cache.clear()

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


SPEC_PATH = "specs/module1/feature1/spec.md"


class TestGitLog:
    def test_git_log_commits_and_fields(self, git_workspace):
        """提交历史解析：init + 2 个新 commit，字段完整，变更文件带状态。"""
        src, name = git_workspace
        (src / "specs" / "module1" / "feature1" / "spec.md").write_text(
            "# Module1 - Feature1\n\n### FR-001: 查询功能（更新）\nAC-001\nAC-002\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "update spec"], cwd=src)
        (src / "specs" / "module1" / "feature1" / "api.yaml").write_text(
            "openapi: 3.0.0\ninfo: {title: t, version: v}\n", encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "update api"], cwd=src)

        # 克隆侧未 pull：git_log 只看到本地 2 条（init + 克隆时的 HEAD）
        result = wsm.git_log(name)
        assert result["ok"] is True
        assert result["workspace"] == "ws1"
        assert len(result["commits"]) == 1  # 克隆时只有 init

        # pull 后看到全部 3 条，最新在前
        wsm.pull(name)
        result = wsm.git_log(name)
        assert result["ok"] is True
        assert len(result["commits"]) == 3
        c = result["commits"][0]
        assert c["message"] == "update api"
        assert c["author"] == "specguard-test"
        assert c["email"] == "test@specguard.local"
        assert len(c["sha"]) == 40 and len(c["short_sha"]) == 7
        assert c["date"]
        # 第一个 commit 变更 api.yaml（M 修改）
        assert any(f["path"].endswith("api.yaml") and f["status"] == "M" for f in c["files"])
        # init commit：新增文件
        last = result["commits"][-1]
        assert last["parents"] == []
        assert any(f["status"] == "A" for f in last["files"])
        assert result["local_head"] == result["commits"][0]["sha"][:12]

    def test_git_log_non_git_workspace(self, git_workspace, tmp_path):
        """local 型工作区不支持 git log。"""
        local_dir = tmp_path / "local_ws"
        create_valid_workspace(local_dir)
        reg = wsm.register_local("ws_local", str(local_dir), "tdm",
                                 activate=False, run_conformance=False)
        assert reg["ok"], reg.get("error")

        result = wsm.git_log("ws_local")
        assert result["ok"] is False
        assert "不是 git 型" in result["error"]


class TestRemoteHeadStatus:
    def test_synced_when_up_to_date(self, git_workspace):
        """克隆后未变：远程与本地同步。"""
        _, name = git_workspace
        st = wsm.remote_head_status(name)
        assert st["remote_known"] is True
        assert st["synced"] is True
        assert st["remote_head"] == st["local_head"]

    def test_not_synced_when_remote_ahead(self, git_workspace):
        """远端新增 commit：synced=False，remote_head != local_head。"""
        src, name = git_workspace
        (src / "specs" / "module1" / "feature1" / "spec.md").write_text(
            "# Module1 - Feature1\n\n### FR-001: 查询功能（远程更新）\nAC-001\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "remote change"], cwd=src)

        st = wsm.remote_head_status(name)
        assert st["remote_known"] is True
        assert st["synced"] is False
        assert st["remote_head"] != st["local_head"]


class TestRemoteFileMarks:
    def test_remote_updated_when_remote_ahead(self, git_workspace):
        """远程修改了文件：标记 [远程已更新]。"""
        src, name = git_workspace
        (src / SPEC_PATH).write_text(
            "# Module1 - Feature1\n\n### FR-001: 查询功能（远程更新）\nAC-001\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "remote change"], cwd=src)

        marks = wsm.remote_file_marks([SPEC_PATH], name)
        assert marks[SPEC_PATH] == "[远程已更新]"

    def test_remote_missing_when_remote_deleted(self, git_workspace):
        """远程删除了文件，本地仍存在：标记 [远程不存在]。"""
        src, name = git_workspace
        _git(["rm", SPEC_PATH], cwd=src)
        _git(["commit", "-m", "remote delete"], cwd=src)

        marks = wsm.remote_file_marks([SPEC_PATH], name)
        assert marks[SPEC_PATH] == "[远程不存在]"

    def test_no_mark_after_pull(self, git_workspace):
        """pull 同步后：无标记。"""
        src, name = git_workspace
        (src / SPEC_PATH).write_text(
            "# Module1 - Feature1\n\n### FR-001: 查询功能（远程更新）\nAC-001\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "remote change"], cwd=src)
        wsm.pull(name)

        marks = wsm.remote_file_marks([SPEC_PATH], name)
        assert marks[SPEC_PATH] == ""

    def test_remote_missing_for_local_untracked(self, git_workspace):
        """同步状态下本地新增未推送文件：远程确实不存在 → [远程不存在]。"""
        _, name = git_workspace
        clone = wsm.get_workspace(name).root
        (clone / "docs").mkdir(parents=True, exist_ok=True)
        (clone / "docs" / "local-new.md").write_text("本地新增，未推送\n", encoding="utf-8")

        marks = wsm.remote_file_marks(["docs/local-new.md"], name)
        assert marks["docs/local-new.md"] == "[远程不存在]"

    def test_remote_unreachable_no_mark(self, git_workspace, tmp_path):
        """远程不可达：静默降级，无标记。"""
        src, name = git_workspace
        (src / SPEC_PATH).write_text(
            "# Module1 - Feature1\n\n### FR-001: 查询功能（远程更新）\nAC-001\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "remote change"], cwd=src)
        # 把克隆的 origin 指向不存在的路径（Windows 上移动 src 目录会被 git 句柄占用）
        clone = wsm.get_workspace(name).root
        _git(["remote", "set-url", "origin", str(tmp_path / "remote_gone")], cwd=clone)
        wsm._remote_cache.clear()  # 强制重新探测

        marks = wsm.remote_file_marks([SPEC_PATH], name)
        assert marks[SPEC_PATH] == ""
        st = wsm.remote_head_status(name)
        assert st["remote_known"] is False

    def test_marks_for_unchanged_file_absent(self, git_workspace):
        """远程领先但某文件未变（其他文件变了）：该文件无标记。"""
        src, name = git_workspace
        # 只改 AGENTS.md，不动 spec.md
        (src / "AGENTS.md").write_text("# 更新后的 AGENTS.md\n", encoding="utf-8")
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "agents change"], cwd=src)

        marks = wsm.remote_file_marks([SPEC_PATH], name)
        assert marks[SPEC_PATH] == ""


class TestCheckRemoteSync:
    def test_cache_ttl_reuses_result(self, git_workspace, monkeypatch):
        """TTL 缓存：连续调用不重复 ls-remote。"""
        src, name = git_workspace
        (src / SPEC_PATH).write_text("changed\n", encoding="utf-8")
        _git(["add", "-A"], cwd=src)
        _git(["commit", "-m", "remote change"], cwd=src)

        first = wsm.check_remote_sync(name)
        assert first["synced"] is False
        assert first["fetched"] is True  # fetch 成功，可离线比较

        calls = []
        orig = wsm._ls_remote_head

        def spy(info, path):
            calls.append(1)
            return orig(info, path)

        monkeypatch.setattr(wsm, "_ls_remote_head", spy)
        second = wsm.check_remote_sync(name)  # TTL 内：不触发 ls-remote
        assert second == first
        assert calls == []

        third = wsm.check_remote_sync(name, force=True)  # force：重新探测
        assert calls == [1]

    def test_non_git_returns_false(self, git_workspace, tmp_path):
        """非 git 工作区：git=False。"""
        local_dir = tmp_path / "local_ws"
        create_valid_workspace(local_dir)
        reg = wsm.register_local("ws_local", str(local_dir), "tdm",
                                 activate=False, run_conformance=False)
        assert reg["ok"], reg.get("error")

        sync = wsm.check_remote_sync("ws_local")
        assert sync["git"] is False
