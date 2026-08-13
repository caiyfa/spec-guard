"""rebase_resolver 测试（S0.6 · rebase 中断界面化恢复）。

覆盖：
1. smart_merge 纯函数：FR 编号等价合并 / 远端新增行保留 / 不安全拒绝
2. 真实 git 仓库 rebase 中断场景：status 检测 / conflict 解析 /
   resolve（ours/theirs/smart）/ continue / abort 全链路
"""

import subprocess
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from test_specstd.helpers import create_valid_workspace  # noqa: E402
import specstd.workspace as wsm  # noqa: E402
from specstd.workspace import register_local, unregister  # noqa: E402
from workbench.backend.services.specflow import rebase_resolver  # noqa: E402


def _git(args: list, cwd: Path):
    return subprocess.run(args, cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


@pytest.fixture(autouse=True)
def _cleanup_ctx():
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """隔离 SQLite 数据文件。"""
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from services import user_store
    monkeypatch.setattr(user_store, "DB_PATH", tmp_path / "workbench.db")
    user_store.init_db()
    return tmp_path


@pytest.fixture()
def rebase_repo(tmp_path, db):
    """构造 rebase 中断的 git 工作区：main 与 feature 同改 spec.md 冲突。"""
    ws = create_valid_workspace(tmp_path / "repo")
    _git(["git", "init", "-b", "main"], ws)
    _git(["git", "config", "user.email", "test@specguard.local"], ws)
    _git(["git", "config", "user.name", "SpecGuard Test"], ws)
    spec = ws / "spec.md"
    spec.write_text("行1\n行2\n行3\n", encoding="utf-8")
    _git(["git", "add", "-A"], ws)
    _git(["git", "commit", "-m", "chore: 基线"], ws)
    # main（模拟远端目标）：修改行2
    spec.write_text("行1\n行2-远端修改\n行3\n", encoding="utf-8")
    _git(["git", "commit", "-am", "feat: 远端修改"], ws)
    # feature（本地提交）：修改行2 → 冲突
    _git(["git", "checkout", "-b", "feature", "HEAD~1"], ws)
    spec.write_text("行1\n行2-本地修改\n行3\n", encoding="utf-8")
    _git(["git", "commit", "-am", "feat: 本地修改"], ws)
    # rebase main → 冲突中断
    r = _git(["git", "rebase", "main"], ws)
    assert r.returncode != 0  # 冲突中断
    register_local("tdm", str(ws), "tdm", activate=True)
    yield ws
    # 清理：确保不留中断状态污染后续测试
    _git(["git", "rebase", "--abort"], ws)
    unregister("tdm")


# ══════════════════════════════════════════════════════════
# smart_merge 纯函数
# ══════════════════════════════════════════════════════════

class TestSmartMerge:
    def test_fr_equivalence_merge(self):
        """ours 旧编号行与 theirs 新编号行内容等价 → 丢弃旧编号；保留远端 FIXED 行。"""
        ours = ("- ✅ ADDED: FR-009 性能逻辑组间切换，基线 V2.5 → V2.6\n"
                "- 🐛 FIXED: race 条件空值跳过导致查询恒 0 条\n")
        theirs = "- ✅ ADDED: FR-eval-360-0817-001 性能逻辑组间切换，基线 V2.5 → V2.6\n"
        merged, reason = rebase_resolver.smart_merge(ours, theirs)
        assert reason == ""
        assert "FR-eval-360-0817-001" in merged
        assert "FR-009 " not in merged  # 旧编号行被丢弃
        assert "FIXED: race 条件" in merged  # 远端 FIXED 行保留

    def test_remote_new_lines_preserved(self):
        """ours 独有的无编号行全部保留。"""
        ours = "- 共同行\n- 远端新增修复记录\n"
        theirs = "- 共同行\n"
        merged, _ = rebase_resolver.smart_merge(ours, theirs)
        assert "远端新增修复记录" in merged

    def test_unsafe_reject(self):
        """ours 含编号行在 theirs 中无等价对应 → 拒绝自动合并。"""
        ours = "- ✅ ADDED: FR-009 一个完全不同的需求描述\n"
        theirs = "- ✅ ADDED: FR-eval-360-0817-001 性能逻辑组间切换\n"
        merged, reason = rebase_resolver.smart_merge(ours, theirs)
        assert merged is None
        assert "需人工判断" in reason


# ══════════════════════════════════════════════════════════
# rebase 中断场景集成（真实 git 仓库）
# ══════════════════════════════════════════════════════════

class TestRebaseFlow:
    def test_status_detects_interruption(self, rebase_repo):
        r = rebase_resolver.get_rebase_status("tdm")
        assert r["ok"] and r["in_progress"]
        assert r["state"] == "merge"
        paths = [c["path"] for c in r["conflicts"]]
        assert "spec.md" in paths

    def test_conflict_detail_segments(self, rebase_repo):
        r = rebase_resolver.get_conflict_detail("tdm", "spec.md")
        assert r["ok"] and len(r["segments"]) == 1
        seg = r["segments"][0]
        assert "远端修改" in seg["ours"]   # rebase 目标（main）
        assert "本地修改" in seg["theirs"]  # 被应用的提交（feature）

    def test_resolve_theirs_then_continue(self, rebase_repo):
        """取本地提交版本解决 → 无剩余冲突 → continue 完成 rebase。"""
        r = rebase_resolver.resolve_conflict("tdm", "spec.md", "theirs")
        assert r["ok"] and r["remaining"] == []
        r2 = rebase_resolver.continue_rebase("tdm")
        assert r2["ok"], r2.get("error")
        # rebase 完成：状态归位 + 文件内容为本地版本
        st = rebase_resolver.get_rebase_status("tdm")
        assert st["in_progress"] is False
        content = (rebase_repo / "spec.md").read_text(encoding="utf-8")
        assert "本地修改" in content and "<<<<<<<" not in content

    def test_abort_restores_original(self, rebase_repo):
        """abort 回到 rebase 前状态（feature 分支原样）。"""
        r = rebase_resolver.abort_rebase("tdm")
        assert r["ok"]
        st = rebase_resolver.get_rebase_status("tdm")
        assert st["in_progress"] is False
        content = (rebase_repo / "spec.md").read_text(encoding="utf-8")
        assert "本地修改" in content

    def test_continue_blocked_with_conflicts(self, rebase_repo):
        """未解决冲突时 continue 被拒绝并列出剩余文件。"""
        r = rebase_resolver.continue_rebase("tdm")
        assert not r["ok"]
        assert "spec.md" in r["error"]

    def test_no_rebase_state_rejected(self, git_ws):
        """无 rebase 中断时操作被拒绝。"""
        st = rebase_resolver.get_rebase_status("tdm")
        assert st["ok"] and not st["in_progress"]
        assert not rebase_resolver.abort_rebase("tdm")["ok"]


@pytest.fixture()
def git_ws(tmp_path, db):
    """无 rebase 的普通 git 工作区。"""
    ws = create_valid_workspace(tmp_path / "plain")
    _git(["git", "init", "-b", "main"], ws)
    _git(["git", "config", "user.email", "test@specguard.local"], ws)
    _git(["git", "config", "user.name", "SpecGuard Test"], ws)
    _git(["git", "add", "-A"], ws)
    _git(["git", "commit", "-m", "chore: 基线"], ws)
    register_local("tdm", str(ws), "tdm", activate=True)
    yield ws
    unregister("tdm")
