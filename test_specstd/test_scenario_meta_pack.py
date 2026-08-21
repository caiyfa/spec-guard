"""scenario_meta 信息包条目化（K-013）+ 新鲜度检测 测试。

隔离：user_store.DB_PATH → tmp SQLite；specstd.workspace → tmp 工作区
（fixture 模式沿用 test_plan_store.py / test_workspace_pull.py）。
"""

import json
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

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
        # T-061 适配：三闸前置（sg_draft_gates）语义由 test_s6_m07_coverage 专项覆盖，此处 mock 通过
        from services import draft_gates
        monkeypatch.setattr(draft_gates, "check_promote_allowed",
                            lambda fn, db_path=None: (True, ""))
        monkeypatch.setattr(draft_gates, "mark_promoted", lambda *a, **k: None)
        monkeypatch.setattr(draft_gates, "mark_gate3_fail", lambda *a, **k: None)
        # 关键隔离：ws(spec 仓库样例)无 scenarios/，K-016 回退会落到真实仓库根——
        # 必须钉到 tmp，防止测试产物写入真实 scenarios/（本测试类曾因此互相 conflict）
        monkeypatch.setattr(dp, "_scenarios_root", lambda: ws / "scenarios")
        import mcp_server.tools.validator as v
        monkeypatch.setattr(v, "validate_scenario_content",
                            lambda content: {"verdict": verdict, "scenario": "TL-001", "findings": []})
        # K-017：不预建模块目录——promote 应自动创建
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

    def test_promote_auto_creates_module_dir(self, ws, monkeypatch):
        """K-017：模块目录不存在时自动创建（含多级路径），不报错。"""
        dp, d = self._setup(ws, monkeypatch)
        (d / "TL-003.yaml").write_text("id: TL-003\n", encoding="utf-8")
        r = dp.promote("TL-003.yaml", "system-settings/tag-library", skip_gate=True)
        assert r["ok"]
        assert (ws / "scenarios" / "system-settings" / "tag-library" / "TL-003.yaml").is_file()

    def test_promote_creates_suite_yaml(self, ws, monkeypatch):
        """K-026：promote 到无 _suite.yaml 的目录时自动创建（module 元信息）。

        此前新模块目录无套件元信息 → 场景 module='' → DAG 编排按模块分组找不到。
        """
        dp, d = self._setup(ws, monkeypatch)
        (d / "TL-004.yaml").write_text("id: TL-004\n", encoding="utf-8")
        dp.promote("TL-004.yaml", "system-settings/tag-library", skip_gate=True)
        suite = ws / "scenarios" / "system-settings" / "tag-library" / "_suite.yaml"
        assert suite.is_file()
        assert "module: system-settings/tag-library" in suite.read_text(encoding="utf-8")

    def test_promote_records_lineage(self, ws, monkeypatch):
        """K-026：promote 成功后血缘落盘（信息包 → 已入库场景正向链路）。

        草稿的 scenario_id 来自 drafts/_meta.json（write_draft K-013 记录）。
        """
        import json as _json
        dp, d = self._setup(ws, monkeypatch)
        import mcp_server.tools.validator as v
        # 按内容返回真实场景 ID（_setup 的恒 TL-001 mock 不适用于血缘断言）
        monkeypatch.setattr(v, "validate_scenario_content", lambda content: {
            "verdict": "PASS",
            "scenario": content.split("id:")[1].split()[0] if "id:" in content else "X",
            "findings": []})
        (d / "TL-005.yaml").write_text("id: TL-005\n", encoding="utf-8")
        (d / "_meta.json").write_text(
            _json.dumps({"TL-005.yaml": {"scenario_id": "SG-META-0001"}}), encoding="utf-8")
        dp.promote("TL-005.yaml", "module1", skip_gate=True)
        promoted = scenario_meta.get_promotions("SG-META-0001")
        assert len(promoted) == 1
        assert promoted[0]["scenario_id"] == "TL-005"
        assert promoted[0]["module"] == "module1"
        assert promoted[0]["draft"] == "TL-005.yaml"
        # 重复入库同场景 → 更新而非追加
        (ws / "scenarios" / "module1" / "TL-005.yaml").unlink()  # 模拟修改后重入库
        (d / "TL-005.yaml").write_text("id: TL-005\n", encoding="utf-8")
        dp.promote("TL-005.yaml", "module1", skip_gate=True)
        assert len(scenario_meta.get_promotions("SG-META-0001")) == 1

    def test_promote_no_meta_no_lineage_no_crash(self, ws, monkeypatch):
        """无 _meta.json 关联时静默跳过血缘（不影响入库主流程）。"""
        dp, d = self._setup(ws, monkeypatch)
        (d / "TL-006.yaml").write_text("id: TL-006\n", encoding="utf-8")
        r = dp.promote("TL-006.yaml", "module1", skip_gate=True)
        assert r["ok"]

    def test_promote_sg_root_fallback_no_value_error(self, ws, monkeypatch, tmp_path):
        """K-019：scenarios 根回退 SG_ROOT 侧（工作区外）时，return 不得抛 ValueError。

        生产事故：promote 实际成功（文件已移动+基线已重建+门禁已通过），
        return 语句 target.relative_to(工作区根) 抛「not in the subpath of」，
        工具误报失败，Agent 据此放弃剩余 6 份入库（用户会话导出佐证）。
        """
        from services import draft_promote as dp
        monkeypatch.setattr(dp, "_rebuild_baseline", lambda: None)
        # T-061 适配：三闸前置 mock 通过（专项覆盖在 test_s6_m07_coverage）
        from services import draft_gates
        monkeypatch.setattr(draft_gates, "check_promote_allowed",
                            lambda fn, db_path=None: (True, ""))
        monkeypatch.setattr(draft_gates, "mark_promoted", lambda *a, **k: None)
        monkeypatch.setattr(draft_gates, "mark_gate3_fail", lambda *a, **k: None)
        # 模拟 K-016 回退：scenarios 根在工作区之外（SG_ROOT 侧）
        sg_repo = tmp_path / "sg_repo"
        monkeypatch.setattr(dp, "_scenarios_root", lambda: sg_repo / "scenarios")
        monkeypatch.setattr(dp, "SG_ROOT", sg_repo)
        import mcp_server.tools.validator as v
        monkeypatch.setattr(v, "validate_scenario_content",
                            lambda content: {"verdict": "PASS", "scenario": "TL-009", "findings": []})
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "TL-009.yaml").write_text("id: TL-009\n", encoding="utf-8")
        r = dp.promote("TL-009.yaml", "system-settings/tag-library", skip_gate=True)
        assert r["ok"] and r["scenario_id"] == "TL-009"
        assert r["target"] == "scenarios/system-settings/tag-library/TL-009.yaml"
        assert (sg_repo / "scenarios" / "system-settings" / "tag-library" / "TL-009.yaml").is_file()
        assert not (d / "TL-009.yaml").exists()

    def test_promote_conflict(self, ws, monkeypatch):
        dp, d = self._setup(ws, monkeypatch)
        (d / "TL-001.yaml").write_text("id: TL-001\n", encoding="utf-8")
        (ws / "scenarios" / "module1").mkdir(parents=True, exist_ok=True)
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


class TestInfoPackUpload:
    """K-033：信息包直接上传材料（不再只能 git 拉取工作区文件）。"""

    @staticmethod
    def _fake_upload(filename: str, data: bytes):
        class FakeUpload:
            async def read(self):
                return data
        u = FakeUpload()
        u.filename = filename
        return u

    def test_upload_adds_entry_and_file(self, ws):
        """上传 → 文件落盘 .specguard/uploads/ + 条目（带 sha 指纹）加入信息包。"""
        import asyncio
        from routers.scenarios import api_upload_info_pack_file

        meta = _create("上传测试")
        result = asyncio.run(api_upload_info_pack_file(
            meta["id"], self._fake_upload("补充材料.md", "# 补充说明\n内容".encode("utf-8"))))
        paths = [e["path"] for e in result["info_pack"]]
        assert ".specguard/uploads/补充材料.md" in paths
        # 文件真实落盘 + 条目带 sha
        from specstd.workspace import safe_resolve
        p = safe_resolve(".specguard/uploads/补充材料.md")
        assert p and p.is_file()
        entry = next(e for e in result["info_pack"] if e["path"].endswith("补充材料.md"))
        assert entry["sha"]

    def test_upload_dedup_filename(self, ws):
        """同名上传第二次 → -1 后缀去重（不覆盖）。"""
        import asyncio
        from routers.scenarios import api_upload_info_pack_file

        meta = _create("去重测试")
        asyncio.run(api_upload_info_pack_file(meta["id"], self._fake_upload("a.md", b"v1")))
        result = asyncio.run(api_upload_info_pack_file(meta["id"], self._fake_upload("a.md", b"v2")))
        paths = [e["path"] for e in result["info_pack"]]
        assert ".specguard/uploads/a.md" in paths
        assert ".specguard/uploads/a-1.md" in paths
        from specstd.workspace import safe_resolve
        assert safe_resolve(".specguard/uploads/a.md").read_text() == "v1"  # 原文件未被覆盖

    def test_upload_bad_filename_rejected(self, ws):
        """非法文件名：隐藏文件（.env 等）→ 400；路径穿越被 .name 剥离中性化。"""
        import asyncio
        from fastapi import HTTPException
        from routers.scenarios import api_upload_info_pack_file

        meta = _create("非法文件名测试")
        with pytest.raises(HTTPException) as ei:
            asyncio.run(api_upload_info_pack_file(
                meta["id"], self._fake_upload(".env", b"SECRET=x")))
        assert ei.value.status_code == 400

        # 路径穿越：Path.name 剥离目录部分，落盘仍在 uploads/ 内（中性化而非拒绝）
        result = asyncio.run(api_upload_info_pack_file(
            meta["id"], self._fake_upload("../../etc/evil.md", b"x")))
        paths = [e["path"] for e in result["info_pack"]]
        assert ".specguard/uploads/evil.md" in paths


class TestPromoteBatch:
    """K-021⑥：批量入库（一次基线重建 + 一次门禁；不合格单份跳过；失败整批回滚）。"""

    def _setup(self, ws, monkeypatch, verdict="PASS"):
        from services import draft_promote as dp
        calls = {"rebuild": 0, "gate": 0}
        monkeypatch.setattr(dp, "_rebuild_baseline",
                            lambda: calls.__setitem__("rebuild", calls["rebuild"] + 1))
        # T-061 适配：三闸前置 mock 通过（专项覆盖在 test_s6_m07_coverage）
        from services import draft_gates
        monkeypatch.setattr(draft_gates, "check_promote_allowed",
                            lambda fn, db_path=None: (True, ""))
        monkeypatch.setattr(draft_gates, "mark_promoted", lambda *a, **k: None)
        monkeypatch.setattr(draft_gates, "mark_gate3_fail", lambda *a, **k: None)
        # 关键隔离：钉到 tmp，防测试产物写入真实 scenarios/（同 TestPromote 教训）
        monkeypatch.setattr(dp, "_scenarios_root", lambda: ws / "scenarios")
        import mcp_server.tools.validator as v
        monkeypatch.setattr(v, "validate_scenario_content",
                            lambda content: {"verdict": verdict, "scenario": "TL-B", "findings": []})
        from specstd.workspace import drafts_dir
        d = drafts_dir()
        d.mkdir(parents=True, exist_ok=True)
        return dp, d, calls

    def test_batch_success_baseline_once(self, ws, monkeypatch):
        """两份草稿一次入库：基线只重建一次（逐份 promote 会跑 N 次）。"""
        dp, d, calls = self._setup(ws, monkeypatch)
        (d / "TL-B1.yaml").write_text("id: TL-B1\n", encoding="utf-8")
        (d / "TL-B2.yaml").write_text("id: TL-B2\n", encoding="utf-8")
        r = dp.promote_batch(["TL-B1.yaml", "TL-B2.yaml"], "module1", skip_gate=True)
        assert r["ok"] and len(r["promoted"]) == 2 and not r["skipped"]
        assert calls["rebuild"] == 1
        assert (ws / "scenarios" / "module1" / "TL-B1.yaml").is_file()
        assert (ws / "scenarios" / "module1" / "TL-B2.yaml").is_file()
        assert not (d / "TL-B1.yaml").exists() and not (d / "TL-B2.yaml").exists()

    def test_batch_default_all_drafts(self, ws, monkeypatch):
        """filenames 省略 → drafts/ 全部 YAML。"""
        dp, d, _ = self._setup(ws, monkeypatch)
        (d / "TL-B1.yaml").write_text("id: TL-B1\n", encoding="utf-8")
        (d / "TL-B2.yaml").write_text("id: TL-B2\n", encoding="utf-8")
        r = dp.promote_batch(None, "module1", skip_gate=True)
        assert r["ok"] and len(r["promoted"]) == 2

    def test_batch_partial_skip(self, ws, monkeypatch):
        """不合格单份跳过（不拖垮整批）：1 份校验失败 + 1 份正常 → 1 入库 1 跳过。"""
        dp, d, _ = self._setup(ws, monkeypatch)
        import mcp_server.tools.validator as v
        monkeypatch.setattr(v, "validate_scenario_content", lambda content: (
            {"verdict": "PASS", "scenario": "TL-GOOD", "findings": []}
            if "GOOD" in content else
            {"verdict": "REJECT", "scenario": "TL-BAD",
             "findings": [{"level": "ERROR", "rule": "T1", "message": "bad"}]}))
        (d / "TL-GOOD.yaml").write_text("id: TL-GOOD\n", encoding="utf-8")
        (d / "TL-BAD.yaml").write_text("id: TL-BAD\n", encoding="utf-8")
        r = dp.promote_batch(None, "module1", skip_gate=True)
        assert r["ok"] and len(r["promoted"]) == 1 and len(r["skipped"]) == 1
        assert r["skipped"][0]["file"] == "TL-BAD.yaml"
        assert (ws / "scenarios" / "module1" / "TL-GOOD.yaml").is_file()
        assert (d / "TL-BAD.yaml").is_file()  # 不合格草稿留在 drafts

    def test_batch_gate_failure_rollback(self, ws, monkeypatch):
        """门禁失败整批回滚：文件回 drafts/，无半截入库。"""
        dp, d, _ = self._setup(ws, monkeypatch)
        monkeypatch.setattr(dp, "_run_release_gate",
                            lambda: {"ok": False, "output": "gate boom", "skipped": False})
        (d / "TL-B1.yaml").write_text("id: TL-B1\n", encoding="utf-8")
        (d / "TL-B2.yaml").write_text("id: TL-B2\n", encoding="utf-8")
        with pytest.raises(dp.PromoteError) as ei:
            dp.promote_batch(None, "module1", skip_gate=False)
        assert ei.value.code == "gate_failed"
        assert (d / "TL-B1.yaml").is_file() and (d / "TL-B2.yaml").is_file()
        assert not (ws / "scenarios" / "module1" / "TL-B1.yaml").exists()

    def test_batch_none_qualified(self, ws, monkeypatch):
        """全部不合格 → ok=False 且不动任何文件。"""
        dp, d, _ = self._setup(ws, monkeypatch, verdict="REJECT")
        (d / "TL-B1.yaml").write_text("id: TL-B1\n", encoding="utf-8")
        r = dp.promote_batch(None, "module1", skip_gate=True)
        assert not r["ok"] and len(r["skipped"]) == 1
        assert (d / "TL-B1.yaml").is_file()


class TestScenariosRootFallback:
    """K-016：场景库根回退（spec 工作区无 scenarios/ 时回退 SpecGuard 仓库根）。

    生产佐证：草稿评审页 modules 为空 → 入库按钮静默无反应。
    """

    def test_workspace_without_scenarios_falls_back(self, ws):
        from services import draft_promote as dp
        assert dp._scenarios_root() == dp.SG_ROOT / "scenarios"

    def test_workspace_with_scenarios_preferred(self, ws):
        from services import draft_promote as dp
        (ws / "scenarios").mkdir()
        assert dp._scenarios_root() == ws / "scenarios"


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


class TestAutoCreateInfoPack:
    """K-034：聊天框上传附件 → 自动创建信息包（无需先走创建向导）。"""

    @staticmethod
    def _fake_upload(filename: str, data: bytes):
        class FakeUpload:
            async def read(self):
                return data
        u = FakeUpload()
        u.filename = filename
        return u

    def test_auto_create_multi_files(self, ws):
        """多文件一次成一个包：meta 创建 + 全部落盘 + 条目化，默认名取首个文件名。"""
        import asyncio
        from routers.scenarios import api_auto_create_info_pack

        files = [
            self._fake_upload("对比导出.xlsx", b"pk\x03\x04fake"),
            self._fake_upload("说明.md", "# 说明\n".encode("utf-8")),
        ]
        result = asyncio.run(api_auto_create_info_pack(files, name="", ws_name="ws1"))
        assert result["id"].startswith("SG-META-")
        assert result["name"] == "对比导出"  # 未指定名 → 首个文件名去扩展名
        assert result["workspace"] == "ws1"
        paths = [e["path"] for e in result["info_pack"]]
        assert ".specguard/uploads/对比导出.xlsx" in paths
        assert ".specguard/uploads/说明.md" in paths
        # 文件真实落盘
        from specstd.workspace import safe_resolve
        assert safe_resolve(".specguard/uploads/对比导出.xlsx").is_file()
        assert safe_resolve(".specguard/uploads/说明.md").is_file()

    def test_auto_create_explicit_name(self, ws):
        """显式名称优先于默认名。"""
        import asyncio
        from routers.scenarios import api_auto_create_info_pack

        result = asyncio.run(api_auto_create_info_pack(
            [self._fake_upload("a.md", b"v1")], name="我的信息包", ws_name="ws1"))
        assert result["name"] == "我的信息包"

    def test_auto_create_rejects_bad_file(self, ws):
        """空文件/隐藏文件拒绝，且不创建 meta。"""
        import asyncio
        from fastapi import HTTPException
        from routers.scenarios import api_auto_create_info_pack

        before = len(scenario_meta.list_meta(workspace="ws1"))
        with pytest.raises(HTTPException):
            asyncio.run(api_auto_create_info_pack(
                [self._fake_upload("a.md", b"")], name="", ws_name="ws1"))
        with pytest.raises(HTTPException):
            asyncio.run(api_auto_create_info_pack(
                [self._fake_upload(".env", b"SECRET=1")], name="", ws_name="ws1"))
        assert len(scenario_meta.list_meta(workspace="ws1")) == before
