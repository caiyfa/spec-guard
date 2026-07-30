"""scenario_meta 信息包条目化（K-013）+ 新鲜度检测 测试。

隔离：user_store.DB_PATH → tmp SQLite；specstd.workspace → tmp 工作区
（fixture 模式沿用 test_plan_store.py / test_workspace_pull.py）。
"""

import json
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import specstd.workspace as wsm  # noqa: E402
from services import scenario_meta, user_store  # noqa: E402
from services import info_pack_freshness  # noqa: E402
from test_specstd.conftest import create_valid_workspace  # noqa: E402


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    """隔离 DB + 激活临时本地工作区（local 型，无 commit）。"""
    monkeypatch.setattr(user_store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(wsm, "SG_ROOT", tmp_path)
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    ws_dir = tmp_path / "ws"
    create_valid_workspace(ws_dir)
    result = wsm.register_local("ws1", str(ws_dir), "tdm",
                                activate=True, run_conformance=False)
    assert result["ok"], result.get("error")
    return ws_dir


def _create(sid_name="测试场景"):
    return scenario_meta.create_meta(sid_name, "module1", workspace="ws1")


class TestPackEntries:
    def test_update_writes_entries_with_sha(self, ws):
        """update_info_pack：str 路径 → 条目（sha/added_at 写入，local 型 commit 为空）。"""
        meta = _create()
        updated = scenario_meta.update_info_pack(
            meta["id"], ["specs/module1/feature1/spec.md"])
        entries = updated["info_pack"]
        assert len(entries) == 1
        e = entries[0]
        assert e["path"] == "specs/module1/feature1/spec.md"
        assert len(e["sha"]) == 12
        assert e["added_at"]
        assert e["commit"] == ""  # local 型工作区

    def test_legacy_str_list_migrates_on_read(self, ws):
        """旧版纯路径列表（DB/YAML 中的 str）读取时自动升级为条目。"""
        meta = _create()
        # 模拟旧版数据：直接写 str 列表到 DB
        with user_store._LOCK, user_store._connect() as conn:
            conn.execute("UPDATE scenario_meta SET info_pack = ? WHERE id = ?",
                         (json.dumps(["specs/module1/feature1/spec.md"]), meta["id"]))
        loaded = scenario_meta.get_meta(meta["id"])
        e = loaded["info_pack"][0]
        assert isinstance(e, dict)
        assert e["path"] == "specs/module1/feature1/spec.md"
        assert len(e["sha"]) == 12  # 惰性计算

    def test_missing_file_entry_sha_empty(self, ws):
        """引用不存在的文件：条目保留但 sha 为空（不报错）。"""
        meta = _create()
        updated = scenario_meta.update_info_pack(meta["id"], ["no/such/file.md"])
        assert updated["info_pack"][0]["sha"] == ""

    def test_add_to_info_pack_dedup(self, ws):
        """add_to_info_pack 去重追加。"""
        meta = _create()
        scenario_meta.add_to_info_pack(meta["id"], "specs/module1/feature1/spec.md")
        updated = scenario_meta.add_to_info_pack(meta["id"], "specs/module1/feature1/spec.md")
        assert len(updated["info_pack"]) == 1

    def test_yaml_roundtrip(self, ws):
        """YAML 双写：写入条目后可从文件读回（str/dict 混合兼容）。"""
        meta = _create()
        scenario_meta.update_info_pack(meta["id"], ["specs/module1/feature1/spec.md"])
        from specstd.workspace import info_packs_dir
        yaml_path = info_packs_dir() / f"{meta['id']}.yaml"
        assert yaml_path.is_file()
        import yaml as _yaml
        data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        assert data["files"][0]["path"] == "specs/module1/feature1/spec.md"
        assert data["files"][0]["sha"]

    def test_pack_paths_helper(self, ws):
        meta = _create()
        updated = scenario_meta.update_info_pack(
            meta["id"], ["specs/module1/feature1/spec.md", "AGENTS.md"])
        assert scenario_meta.pack_paths(updated) == [
            "specs/module1/feature1/spec.md", "AGENTS.md"]


class TestFreshness:
    def test_fresh_then_stale_then_missing(self, ws):
        """状态流转：fresh → 改文件 stale → 删文件 missing。"""
        meta = _create()
        target = "specs/module1/feature1/spec.md"
        scenario_meta.update_info_pack(meta["id"], [target])

        r = info_pack_freshness.check_freshness(meta["id"])
        assert r["files"][0]["status"] == "fresh"
        assert r["stale_count"] == 0

        # 修改文件 → stale
        f = ws / target
        f.write_text(f.read_text(encoding="utf-8") + "\n变更内容\n", encoding="utf-8")
        r = info_pack_freshness.check_freshness(meta["id"])
        assert r["files"][0]["status"] == "stale"
        assert r["stale_count"] == 1
        assert r["files"][0]["stored_sha"] != r["files"][0]["current_sha"]

        # 删除文件 → missing
        f.unlink()
        r = info_pack_freshness.check_freshness(meta["id"])
        assert r["files"][0]["status"] == "missing"

    def test_local_workspace_no_discovery(self, ws):
        """local 型工作区：无 commit 概念，变更发现返回空清单。"""
        meta = _create()
        scenario_meta.update_info_pack(meta["id"], ["specs/module1/feature1/spec.md"])
        r = info_pack_freshness.discover_related_changes(meta["id"])
        assert r["inside_stale"] == []
        assert r["outside_changes"] == []
        assert r["base_commit"] == ""


class TestProcessReferences:
    """K-013：routers/agent._process_references（@引用内容注入）。"""

    def test_file_reference_injects_content_and_sha(self, ws):
        from routers.agent import _process_references
        sid, block, refs = _process_references(
            [{"type": "file", "path": "AGENTS.md"}], "")
        assert sid == ""  # 文件引用不改变场景关联
        assert "<references>" in block and "sha:" in block
        assert "Test Spec Repository" in block  # AGENTS.md 内容已注入
        assert refs[0]["type"] == "file" and len(refs[0]["sha"]) == 12

    def test_info_pack_reference_takes_over_scenario(self, ws):
        from routers.agent import _process_references
        sid, block, refs = _process_references(
            [{"type": "info_pack", "id": "SG-META-0001"}], "")
        assert sid == "SG-META-0001"  # 关联语义
        assert block == ""  # 信息包不注入内容（走 read_info_pack 标准流程）
        # 已有场景关联时不覆盖
        sid2, _, _ = _process_references(
            [{"type": "info_pack", "id": "SG-META-0002"}], "SG-META-0001")
        assert sid2 == "SG-META-0001"

    def test_draft_reference(self, ws):
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "T-001.yaml").write_text("id: T-001\ntitle: 测试\n", encoding="utf-8")
        from routers.agent import _process_references
        _, block, refs = _process_references([{"type": "draft", "id": "T-001.yaml"}], "")
        assert "T-001.yaml" in block and "id: T-001" in block
        assert refs[0]["sha"]

    def test_missing_file_marked(self, ws):
        from routers.agent import _process_references
        _, block, refs = _process_references(
            [{"type": "file", "path": "no/such.md"}], "")
        assert "不存在" in block
        assert refs[0].get("missing") is True


class TestListArtifacts:
    """K-015：list_info_pack_artifacts 产物串联工具。"""

    def test_drafts_linked_via_scenario_id(self, ws):
        import asyncio
        from mcp_server.tools import info_pack as ip
        meta = _create()
        scenario_meta.update_info_pack(meta["id"], ["specs/module1/feature1/spec.md"])
        # 模拟 K-013 write_draft 关联：草稿文件 + _meta.json 关联记录
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "TL-001.yaml").write_text("id: TL-001\ntitle: 标签场景\n", encoding="utf-8")
        (d / "_meta.json").write_text(json.dumps({
            "TL-001.yaml": {"scenario_id": meta["id"], "updated_at": "2026-07-30T15:00:00", "author": "t1"},
            "OTHER.yaml": {"scenario_id": "SG-META-9999"},
        }), encoding="utf-8")

        result = asyncio.run(ip.handle("list_info_pack_artifacts", {"scenario_id": meta["id"]}))
        payload = json.loads(result[0].text)
        assert payload["summary"]["draft_count"] == 1
        assert payload["drafts"][0]["scenario_yaml_id"] == "TL-001"
        assert payload["drafts"][0]["author"] == "t1"
        assert payload["drafts"][0]["promoted_or_missing"] is False
        assert payload["files"][0]["status"] == "fresh"

    def test_artifact_unknown_scenario(self, ws):
        import asyncio
        from mcp_server.tools import info_pack as ip
        result = asyncio.run(ip.handle("list_info_pack_artifacts", {"scenario_id": "SG-META-9999"}))
        assert "场景不存在" in result[0].text


class TestPromote:
    """K-015：draft_promote 入库服务（离线，门禁跳过，validator/baseline mock）。"""

    def _setup(self, ws, monkeypatch, verdict="PASS"):
        from services import draft_promote as dp
        monkeypatch.setattr(dp, "_rebuild_baseline", lambda: None)
        import mcp_server.tools.validator as v
        monkeypatch.setattr(v, "validate_scenario_content",
                            lambda content: {"verdict": verdict, "scenario": "TL-001", "findings": []})
        (ws / "scenarios" / "module1").mkdir(parents=True, exist_ok=True)
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        return dp, d

    def test_promote_success(self, ws, monkeypatch):
        dp, d = self._setup(ws, monkeypatch)
        (d / "TL-001.yaml").write_text("id: TL-001\n", encoding="utf-8")
        r = dp.promote("TL-001.yaml", "module1", skip_gate=True)
        assert r["ok"] and r["scenario_id"] == "TL-001"
        assert (ws / "scenarios" / "module1" / "TL-001.yaml").is_file()
        assert not (d / "TL-001.yaml").exists()

    def test_promote_conflict(self, ws, monkeypatch):
        dp, d = self._setup(ws, monkeypatch)
        (d / "TL-001.yaml").write_text("id: TL-001\n", encoding="utf-8")
        (ws / "scenarios" / "module1" / "TL-001.yaml").write_text("existing", encoding="utf-8")
        with pytest.raises(dp.PromoteError) as ei:
            dp.promote("TL-001.yaml", "module1", skip_gate=True)
        assert ei.value.code == "conflict"

    def test_promote_draft_not_found(self, ws, monkeypatch):
        dp, _ = self._setup(ws, monkeypatch)
        with pytest.raises(dp.PromoteError) as ei:
            dp.promote("NOPE.yaml", "module1", skip_gate=True)
        assert ei.value.code == "draft_not_found"

    def test_promote_validation_failed_keeps_draft(self, ws, monkeypatch):
        dp, d = self._setup(ws, monkeypatch, verdict="FAIL")
        (d / "TL-002.yaml").write_text("bad", encoding="utf-8")
        with pytest.raises(dp.PromoteError) as ei:
            dp.promote("TL-002.yaml", "module1", skip_gate=True)
        assert ei.value.code == "validation_failed"
        assert (d / "TL-002.yaml").is_file()  # 格式闸拒绝，草稿未移动


class TestGitDiscovery:
    def test_outside_changes_via_git_diff(self, tmp_path, monkeypatch):
        """git 型：git diff base..HEAD 拆信息包内/外变更（夹具沿用 test_workspace_pull）。"""
        import subprocess
        monkeypatch.setattr(user_store, "DB_PATH", tmp_path / "test.db")
        monkeypatch.setattr(wsm, "SG_ROOT", tmp_path)
        monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
        monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")

        def git(args, cwd):
            proc = subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                cwd=str(cwd), capture_output=True, text=True, timeout=60)
            assert proc.returncode == 0, proc.stderr

        # 源仓库（充当 remote）
        src = tmp_path / "remote_src"
        create_valid_workspace(src)
        git(["init", "-b", "main"], src)
        git(["add", "-A"], src)
        git(["commit", "-m", "init"], src)

        result = wsm.register_git("gws", str(src), "tdm", branch="main",
                                  activate=True, run_conformance=False)
        assert result["ok"], result.get("error")

        # 在克隆的工作区里建信息包（此时 commit = init）
        meta = scenario_meta.create_meta("git 场景", "module1", workspace="gws")
        scenario_meta.update_info_pack(meta["id"], ["specs/module1/feature1/spec.md"])

        # remote 新增提交：改信息包内文件 + 新增信息包外文件
        (src / "specs/module1/feature1/spec.md").write_text("# 更新\n", encoding="utf-8")
        (src / "specs/module1/feature1/new-api.md").write_text("# 新文件\n", encoding="utf-8")
        git(["add", "-A"], src)
        git(["commit", "-m", "update"], src)

        # pull 使 HEAD 前进
        pull_r = wsm.pull("gws")
        assert pull_r["ok"] and pull_r["changed"]

        r = info_pack_freshness.discover_related_changes(meta["id"])
        assert r["inside_stale"] == ["specs/module1/feature1/spec.md"]
        assert "specs/module1/feature1/new-api.md" in r["outside_changes"]
        assert r["base_commit"] != r["head_commit"]
