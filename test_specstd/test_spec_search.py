"""spec_search MCP 工具测试（编号重排能力：FR 引用搜索 + FR 编号解析校验）。

工具：
1. search_spec_files — 工作区内文本搜索（只读），用于编号重排的替换点定位与残留自检
2. parse_fr_id — FR-{功能}-{迭代}-{流水} 注册表锚定解析（右锚流水 + 左锚功能注册表最长匹配
   + 中段迭代自由）+ 迭代代号文件系统安全底线校验（功能名来自 specs/{module}/{feature}/ 第二级目录）
"""

import asyncio
import json
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from test_specstd.helpers import create_valid_workspace  # noqa: E402
import specstd.workspace as wsm  # noqa: E402
from specstd.workspace import register_local, unregister  # noqa: E402


@pytest.fixture(autouse=True)
def _cleanup_ctx():
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """注册合规工作区（specs/module1/feature1 + changes/delta001）。"""
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    ws = create_valid_workspace(tmp_path / "repo")
    register_local("tdm", str(ws), "tdm", activate=True)
    yield ws
    unregister("tdm")


def _call(mod, name: str, args: dict) -> dict:
    """调用 MCP 工具并解析 JSON 返回。"""
    from mcp_server.tools import spec_search
    result = asyncio.run(mod.handle(name, args))
    assert result, f"工具 {name} 无返回"
    return json.loads(result[0].text)


# ══════════════════════════════════════════════════════════
# search_spec_files
# ══════════════════════════════════════════════════════════

class TestSearchSpecFiles:
    def test_search_hits_with_line_no(self, repo):
        """字面搜索命中多文件，返回路径+行号+行文本。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "search_spec_files", {"pattern": "FR-001"})
        assert r["ok"] is True
        assert r["total"] >= 3  # spec.md 标题 / delta-spec.md / manifest 等多处
        paths = {h["path"] for h in r["hits"]}
        assert any(p.startswith("specs/") for p in paths)
        assert any(p.startswith("changes/") for p in paths)
        for h in r["hits"]:
            assert h["line"] >= 1 and h["text"].strip()

    def test_search_subdir_scope(self, repo):
        """subdir=changes 时只命中 changes/ 下文件。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "search_spec_files",
                  {"pattern": "FR-001", "subdir": "changes"})
        assert r["ok"] is True
        assert r["total"] >= 1
        assert all(h["path"].startswith("changes/") for h in r["hits"])

    def test_search_word_boundary(self, repo):
        """搜索 FR-001 不应误中 FR-0010（边界处理）。"""
        from mcp_server.tools import spec_search
        (repo / "changes" / "delta001" / "note.md").write_text(
            "引用 FR-0010 与 FR-001 两个编号\n", encoding="utf-8")
        r = _call(spec_search, "search_spec_files",
                  {"pattern": "FR-001", "subdir": "changes"})
        note_hits = [h for h in r["hits"] if h["path"].endswith("note.md")]
        assert len(note_hits) == 1
        # 命中行内 FR-0010 不算 FR-001 的匹配——返回的 matches 数应只计真匹配
        assert note_hits[0]["matches"] == 1

    def test_search_traversal_rejected(self, repo):
        """subdir 路径穿越拒绝。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "search_spec_files",
                  {"pattern": "FR", "subdir": "../"})
        assert r["ok"] is False

    def test_search_no_workspace(self, tmp_path, monkeypatch):
        """无激活工作区时报错而非崩溃。"""
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
        from mcp_server.tools import spec_search
        r = _call(spec_search, "search_spec_files", {"pattern": "FR-001"})
        assert r["ok"] is False
        assert "工作区" in r["error"]

    def test_search_regex_mode(self, repo):
        """regex=true 支持正则（如 FR-00[12]）。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "search_spec_files",
                  {"pattern": r"FR-00[12]", "regex": True})
        assert r["ok"] is True
        texts = " ".join(h["text"] for h in r["hits"])
        assert "FR-001" in texts and "FR-002" in texts


# ══════════════════════════════════════════════════════════
# parse_fr_id
# ══════════════════════════════════════════════════════════

class TestParseFrId:
    def test_valid_delta_fr(self, repo):
        """合法 delta 编号：拆出 func/iter/seq 且通过注册表校验。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "parse_fr_id", {"fr_id": "FR-feature1-delta001-001"})
        assert r["ok"] is True
        assert r["func"] == "feature1"
        assert r["iter"] == "delta001"
        assert r["seq"] == "001"
        assert r["checks"]["func_registered"] is True
        assert r["checks"]["iter_code_legal"] is True

    def test_prefix_overlap_func(self, repo):
        """同前缀子模块：feature1-extra 注册后，两编号均可解析不歧义。"""
        from mcp_server.tools import spec_search
        extra = repo / "specs" / "module1" / "feature1-extra"
        extra.mkdir(parents=True)
        (extra / "spec.md").write_text("# x\n", encoding="utf-8")
        r1 = _call(spec_search, "parse_fr_id", {"fr_id": "FR-feature1-delta001-001"})
        r2 = _call(spec_search, "parse_fr_id", {"fr_id": "FR-feature1-extra-delta001-001"})
        assert r1["ok"] and r1["func"] == "feature1"
        assert r2["ok"] and r2["func"] == "feature1-extra"

    def test_baseline_fr_rejected(self, repo):
        """基线编号 FR-001 非 delta 格式 → ok=False 并说明。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "parse_fr_id", {"fr_id": "FR-001"})
        assert r["ok"] is False
        assert "基线" in r["error"] or "格式" in r["error"]

    def test_dashed_iter_supported(self, repo):
        """核心能力：迭代含 '-'（FR-feature1-2026-08-17-001）可正常解析。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "parse_fr_id", {"fr_id": "FR-feature1-2026-08-17-001"})
        assert r["ok"] is True
        assert r["func"] == "feature1"
        assert r["iter"] == "2026-08-17"
        assert r["seq"] == "001"

    def test_illegal_iter_code(self, repo):
        """迭代代号字符非法（含空格/路径字符）→ iter_code_legal=False。"""
        from mcp_server.tools import spec_search
        for bad in ("sp rint", "a/b"):
            r = _call(spec_search, "parse_fr_id",
                      {"fr_id": "FR-feature1-delta001-001", "check_iter": bad})
            assert r["ok"] is False
            assert r["checks"]["iter_code_legal"] is False, f"{bad} 应非法"

    def test_free_form_iter_accepted(self, repo):
        """自由迭代名 S24/v2.5/2026Q3/sprint-23 均可解析。"""
        from mcp_server.tools import spec_search
        for it in ("S24", "v2.5", "2026Q3", "sprint-23"):
            r = _call(spec_search, "parse_fr_id", {"fr_id": f"FR-feature1-{it}-001"})
            assert r["ok"] is True and r["iter"] == it, f"{it} 应可解析"

    def test_unregistered_func_rejected(self, repo):
        """功能名不在注册表 → 拒绝并给可用功能清单 hint。"""
        from mcp_server.tools import spec_search
        r = _call(spec_search, "parse_fr_id", {"fr_id": "FR-no-such-feat-0817-001"})
        assert r["ok"] is False
        assert "feature1" in r.get("hint", "")
