"""S3 材料包与信息包测试（T-030/T-031/T-032）。

覆盖：
- store：材料登记/状态机/编号全局唯一/workspace 隔离/候选确认闸门
- pipeline：sniff magic bytes / extract（docx/pdf 无文本层→failed / XXE 拒绝）/ chunk 切分
- 装配器：六分区 + 人拍板闸门（pack_included=0 不入包 / confirmed=0 不列出）
- MCP：pack_assemble / material_extract_topics / pack_read_section
- REST：上传/列表/confirm 角色闸门/include/包读取
全部离线。
"""

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))
BACKEND_DIR = SG_ROOT / "workbench" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

from specflow.materials import store, pipeline as pl, pack_assembler as pa  # noqa: E402
from specflow.materials import coverage as cov  # noqa: E402
from mcp_server.tools import specflow_pack  # noqa: E402


def _call(module, name, arguments):
    return asyncio.run(module.handle(name, arguments))


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    store.init_tables(c)
    return c


def _mk_material(conn, iv="IV-001", ws="tdm", fmt="md", name="m.md",
                 content=None, **kw):
    content = content if content is not None else "# 标题\n正文".encode("utf-8")
    return store.create_material(conn, iv, ws, name, fmt, len(content),
                                 content, kw.get("uploaded_by", "e1"),
                                 kw.get("source_url", ""), kw.get("fetched_by", ""))


# ══════════════════════════════════════════════════════════
# T-030：store 数据层
# ══════════════════════════════════════════════════════════

class TestMaterialStore:
    def test_create_material(self, conn):
        m = _mk_material(conn)
        assert m["material_id"].startswith("MAT-")
        assert m["status"] == "uploaded"
        assert m["sha256_12"]  # 指纹

    def test_material_id_global_unique(self, conn):
        """MAT-xxx 全局唯一（跨工作区不撞号）。"""
        m1 = _mk_material(conn, ws="tdm")
        m2 = _mk_material(conn, ws="other")
        assert m1["material_id"] != m2["material_id"]

    def test_status_machine(self, conn):
        m = _mk_material(conn)
        assert store.update_material_status(conn, m["material_id"], "parsing")
        assert store.update_material_status(conn, m["material_id"], "indexed")
        m2 = store.get_material(conn, m["material_id"])
        assert m2["status"] == "indexed"
        with pytest.raises(ValueError):
            store.update_material_status(conn, m["material_id"], "bogus")

    def test_workspace_isolation(self, conn):
        _mk_material(conn, ws="tdm")
        _mk_material(conn, ws="other")
        assert len(store.list_materials(conn, workspace="tdm")) == 1
        assert len(store.list_materials(conn, workspace="other")) == 1
        assert store.list_materials(conn, workspace="") == []  # fail-closed

    def test_empty_file_rejected(self, conn):
        with pytest.raises(ValueError):
            store.create_material(conn, "IV-001", "tdm", "e.md", "md", 0, b"", "e1")

    def test_topic_gate(self, conn):
        """候选 confirmed=0 出生；confirmed_only 不列出未拍板候选。"""
        m = _mk_material(conn)
        t = store.add_topic(conn, m["material_id"], "IV-001", "tdm",
                            "绩效阈值调整", "P0", ["FR-003"], "§2.7")
        assert t["confirmed"] == 0
        assert store.list_topics(conn, iv_id="IV-001", workspace="tdm",
                                 confirmed_only=True) == []
        store.confirm_topic(conn, t["topic_id"], 1)
        confirmed = store.list_topics(conn, iv_id="IV-001", workspace="tdm",
                                      confirmed_only=True)
        assert len(confirmed) == 1 and confirmed[0]["topic_id"] == t["topic_id"]

    def test_add_topic_unknown_material(self, conn):
        with pytest.raises(KeyError):
            store.add_topic(conn, "MAT-999", "IV-001", "tdm", "T")


# ══════════════════════════════════════════════════════════
# T-030：pipeline 解析管线
# ══════════════════════════════════════════════════════════

class TestPipeline:
    def test_sniff_pdf(self):
        assert pl.sniff(b"%PDF-1.7 xyz") == "pdf"

    def test_sniff_docx(self):
        assert pl.sniff(b"PK\x03\x04rest", "a.docx") == "docx"

    def test_sniff_docx_zip_other_ext_rejected(self):
        assert pl.sniff(b"PK\x03\x04rest", "a.xlsx") is None

    def test_sniff_md(self):
        assert pl.sniff("# 标题\n正文".encode(), "m.md") == "md"

    def test_sniff_text_without_ext(self):
        # 无扩展名时文本类回退 txt（不猜测 md）
        assert pl.sniff("plain text".encode()) == "txt"

    def test_sniff_binary_unknown(self):
        assert pl.sniff(b"\x00\x01\x02\x03binary") is None

    def test_extract_md(self):
        assert pl.extract("# T\n正文".encode(), "md") == "# T\n正文"

    def test_extract_pdf_no_text_layer(self):
        """扫描件 PDF 无文本层 → ExtractError（诚实 failed，不静默降级）。"""
        import io
        try:
            from pypdf import PdfReader, PdfWriter
        except ImportError:
            pytest.skip("pypdf 不可用")
        w = PdfWriter()
        w.add_blank_page(width=100, height=100)
        buf = io.BytesIO()
        w.write(buf)
        with pytest.raises(pl.ExtractError, match="无文本层"):
            pl.extract(buf.getvalue(), "pdf")

    def test_extract_docx_xxe_rejected(self):
        """docx XML 含 DTD/实体（XXE 载荷）→ 确定性拒绝。"""
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml",
                        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><w:document/>')
        with pytest.raises(pl.ExtractError, match="XXE"):
            pl.extract(buf.getvalue(), "docx")

    def test_chunk_markdown_headings(self):
        chunks = pl.chunk("# 一\n甲\n## 二\n乙", "md")
        assert len(chunks) == 2
        assert chunks[0]["heading"] == "一"

    def test_chunk_prd_sections(self):
        text = "--- 第 1 页 ---\n§2.7 落位规则\n绩效≥4.5 落第 9 宫格\n§2.8 名单\n冻结"
        chunks = pl.chunk(text, "pdf")
        assert any(c["section"] == "2.7" for c in chunks)
        assert any(c["section"] == "2.8" for c in chunks)


# ══════════════════════════════════════════════════════════
# T-032：六分区装配器 + 人拍板闸门
# ══════════════════════════════════════════════════════════

class TestPackAssembler:
    def test_assemble_six_sections(self, conn, tmp_path):
        m = _mk_material(conn)
        store.update_material_status(conn, m["material_id"], "indexed")
        store.set_pack_included(conn, m["material_id"], 1)  # 人拍板入包
        t = store.add_topic(conn, m["material_id"], "IV-001", "tdm",
                            "绩效阈值", "P0", ["FR-003"])
        store.confirm_topic(conn, t["topic_id"], 1)  # 人拍板确认候选

        result = pa.assemble_pack(
            "IV-001", "tdm", tmp_path, conn,
            topic_provider=lambda: {"title": "绩效域调整"},
            baseline_provider=lambda: [{"fr": "FR-003", "title": "落位规则"}],
            spq_provider=lambda: [{"spq_id": "SPQ-005", "status": "pending"}],
            report_provider=lambda: {"run": "run#23", "verdict": "FAIL"},
            decisions_provider=lambda: [{"id": "D-012", "status": "resolved"}],
        )
        sections = result["sections"]
        assert sections["topic_card"]["title"] == "绩效域调整"
        assert len(sections["materials"]) == 1
        assert sections["materials"][0]["topics"] == [t["topic_id"]]
        assert sections["baseline"][0]["fr"] == "FR-003"
        assert sections["open_spq"][0]["id"] == "SPQ-005"
        assert sections["last_report"]["verdict"] == "FAIL"
        assert sections["history_decisions"][0]["id"] == "D-012"
        # info_pack.yaml 落盘
        assert (tmp_path / "interviews" / "IV-001" / "info_pack.yaml").is_file()

    def test_pack_included_gate(self, conn, tmp_path):
        """未人拍板入包（pack_included=0）的材料不进信息包。"""
        m = _mk_material(conn)
        store.update_material_status(conn, m["material_id"], "indexed")
        result = pa.assemble_pack("IV-001", "tdm", tmp_path, conn)
        assert result["sections"]["materials"] == []

    def test_unconfirmed_topic_excluded(self, conn, tmp_path):
        """候选未确认不随材料入包（confirmed 闸门）。"""
        m = _mk_material(conn)
        store.update_material_status(conn, m["material_id"], "indexed")
        store.set_pack_included(conn, m["material_id"], 1)
        store.add_topic(conn, m["material_id"], "IV-001", "tdm", "未确认候选")
        result = pa.assemble_pack("IV-001", "tdm", tmp_path, conn)
        assert result["sections"]["materials"][0]["topics"] == []

    def test_read_section_unknown(self):
        pack = {"sections": {}}
        r = pa.read_section(pack, "bogus")
        assert "未知分区" in r["error"]


# ══════════════════════════════════════════════════════════
# T-034：coverage_map 覆盖率机打依据
# ══════════════════════════════════════════════════════════

class TestCoverageMap:
    def _anchors(self):
        from specstd.anchors import AnchorInfo
        return {
            "FR-003": AnchorInfo(fr_id="FR-003", file_path="x", module="", feature="",
                                 title="落位规则与绩效阈值", ac_ids=[]),
            "FR-006": AnchorInfo(fr_id="FR-006", file_path="x", module="", feature="",
                                 title="存量名单冻结", ac_ids=[]),
        }

    def test_high_confidence_match(self):
        """PRD 条目命中 FR 标题关键词 → high 置信机打映射。"""
        chunks = [{"section": "2.7", "content": "绩效≥4.5 落第 9 宫格。"},
                  {"section": "2.8", "content": "存量名单冻结不动。"}]
        cm = cov.build_coverage_map(chunks, self._anchors())
        entries = cm["entries"]
        assert len(entries) == 2
        assert entries[0]["mapped"]["ref"] == "FR-003"
        assert entries[0]["mapped"]["confidence"] == "high"
        assert entries[1]["mapped"]["ref"] == "FR-006"
        assert entries[0]["section"] == "2.7"

    def test_unmapped_item_skipped(self):
        """未命中 FR 词表的条目不产出映射（确定性，不编造）。"""
        chunks = [{"section": "9.9", "content": "页面样式与配色说明。"}]
        cm = cov.build_coverage_map(chunks, self._anchors())
        assert cm["entries"] == []

    def test_write_and_read_back(self, tmp_path):
        cm = {"source": "coverage_map",
              "entries": [{"prd_item": "x", "section": "2.7",
                           "mapped": {"type": "fr", "ref": "FR-003",
                                       "title": "落位规则", "confidence": "high"}}]}
        p = cov.write_coverage_map(cm, tmp_path, "prd-v3.2")
        assert p.is_file()
        import yaml
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert loaded["entries"][0]["mapped"]["ref"] == "FR-003"

    def test_gap_summary(self):
        cm = {"entries": [{"section": "2.7"}, {"section": "2.7"}]}
        assert cov.gap_summary(cm) == ["2.7"]

    def test_prd_upload_produces_coverage(self, rest_env):
        """PRD 类 pdf 上传 → coverage_map.yaml 落盘（F3 验收 4）。"""
        headers = _as_product(rest_env)
        iv_id = _open_iv(rest_env, headers)
        # 构造带文本层的 pdf（pypdf 写入）
        import io
        try:
            from pypdf import PdfWriter
        except ImportError:
            import pytest as _pt
            _pt.skip("pypdf 不可用")
        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        w.write(buf)
        r = rest_env.post(
            f"/api/specflow/interviews/{iv_id}/materials",
            headers=headers,
            files={"file": ("prd-v3.2.pdf", buf.getvalue(), "application/pdf")})
        assert r.status_code == 200, r.text
        # 无文本层的空白页 → failed（诚实呈现）；有文本层才产出 coverage
        assert r.json()["status"] in ("failed", "indexed")


# ══════════════════════════════════════════════════════════
# MCP 工具层（specflow_pack）
# ══════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _cleanup_ctx():
    yield
    from specstd.workspace import set_context_emp_no, set_context_workspace
    set_context_emp_no(None)
    set_context_workspace(None)


@pytest.fixture()
def mcp_env(tmp_path, monkeypatch):
    """隔离 DB + 工作区 + contextvar（MCP 调用上下文）。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from workbench.backend.services.specflow import sf_store
    monkeypatch.setattr(sf_store, "DB_PATH", tmp_path / "workbench.db")

    from test_specstd.helpers import create_valid_workspace
    ws_path = create_valid_workspace(tmp_path / "ws")
    wsm.register_local("test-s3", str(ws_path), "tdm", activate=True)
    tok_ws = wsm.set_context_workspace("test-s3")
    tok_emp = wsm.set_context_emp_no("E10001")
    yield tmp_path
    wsm.reset_context_workspace(tok_ws)
    wsm.reset_context_emp_no(tok_emp)
    wsm.unregister("test-s3")


class TestMCPPack:
    def test_pack_assemble_no_materials(self, mcp_env):
        """无材料时装配 → 空分区清单（不报错）。"""
        r = _call(specflow_pack, "pack_assemble", {"iv_id": "IV-001"})
        assert "assembled" in r[0].text
        assert "sections_available" in r[0].text

    def test_pack_read_section_not_assembled(self, mcp_env):
        r = _call(specflow_pack, "pack_read_section",
                  {"iv_id": "IV-001", "section": "baseline"})
        assert "尚无装配后的信息包" in r[0].text

    def test_material_extract_topics_unknown_material(self, mcp_env):
        r = _call(specflow_pack, "material_extract_topics",
                  {"material_id": "MAT-999", "iv_id": "IV-001", "title": "T"})
        assert "登记失败" in r[0].text

    def test_material_parse_status(self, mcp_env):
        r = _call(specflow_pack, "material_parse_status", {"iv_id": "IV-001"})
        assert "'materials': []" in r[0].text

    def test_pack_freshness_not_assembled(self, mcp_env):
        r = _call(specflow_pack, "pack_freshness_check", {"iv_id": "IV-001"})
        assert "尚无信息包" in r[0].text


def _mcp_upload_md(iv_id="IV-001", filename="read-me.md"):
    """服务层直传 md 材料（read_material 测试数据源，走完整解析管线）。"""
    from specstd.workspace import specflow_dir
    from workbench.backend.services.specflow.materials_service import db_upload_material
    result = db_upload_material(
        iv_id, "test-s3", filename,
        ("# 绩效方案要点\n\n" + ("正文讨论内容。" * 400)).encode("utf-8"),
        "E10001", specflow_dir())
    return result["material"]


class TestReadMaterial:
    """T-934 read_material：三视图 / raw 分页 / 未知 id 诚实报错。"""

    def test_summary_view(self, mcp_env):
        m = _mcp_upload_md()
        r = _call(specflow_pack, "read_material", {"material_id": m["material_id"]})
        text = r[0].text
        assert "'section'" not in text          # 默认视图非 raw
        assert "'status': 'indexed'" in text
        assert "'summary': '# 绩效方案要点" in text
        assert "'total_chars':" in text and "'chunks':" in text
        assert "'hint'" in text                 # 提示 raw 分页入口

    def test_topics_view(self, mcp_env):
        from workbench.backend.services.specflow.materials_service import db_add_topic
        m = _mcp_upload_md()
        db_add_topic(material_id=m["material_id"], iv_id=m["iv_id"],
                     workspace="test-s3", title="绩效阈值调整")
        r = _call(specflow_pack, "read_material",
                  {"material_id": m["material_id"], "section": "topics"})
        assert "'count': 1" in r[0].text
        assert "绩效阈值调整" in r[0].text
        assert "'confirmed': 0" in r[0].text

    def test_raw_pagination(self, mcp_env):
        m = _mcp_upload_md()
        mid = m["material_id"]
        p1 = _call(specflow_pack, "read_material",
                   {"material_id": mid, "section": "raw", "offset": 0, "limit": 500})
        assert "'has_more': True" in p1[0].text
        total = int(p1[0].text.split("'total_chars': ")[1].split(",")[0])
        last_offset = max(0, total - 100)
        p2 = _call(specflow_pack, "read_material",
                   {"material_id": mid, "section": "raw",
                    "offset": last_offset, "limit": 100})
        assert "'has_more': False" in p2[0].text
        assert f"'offset': {last_offset}" in p2[0].text

    def test_unknown_material_honest_error(self, mcp_env):
        r = _call(specflow_pack, "read_material", {"material_id": "MAT-999"})
        assert "材料不存在: MAT-999" in r[0].text

    def test_invalid_section(self, mcp_env):
        m = _mcp_upload_md()
        r = _call(specflow_pack, "read_material",
                  {"material_id": m["material_id"], "section": "full"})
        assert "section 仅支持 summary|topics|raw" in r[0].text


# ══════════════════════════════════════════════════════════
# REST 层（上传/列表/闸门）
# ══════════════════════════════════════════════════════════

@pytest.fixture()
def rest_env(tmp_path, monkeypatch):
    """TestClient 装配（隔离 DB + 注册工作区）。"""
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from services import user_store
    from workbench.backend.services.specflow import sf_store
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    monkeypatch.setattr(sf_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    from services.auth import _TOKEN_CACHE
    _TOKEN_CACHE.clear()

    from test_specstd.helpers import create_valid_workspace
    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
    wsm.unregister("tdm")


def _login(client, emp_no):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": ""})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _as_product(client, admin="90000001", emp="90000002"):
    from services import user_store
    h_admin = _login(client, admin)
    h_user = _login(client, emp)
    user_store.set_roles(emp, ["product"], actor=admin)
    user_store.grant_workspace("tdm", emp, admin)
    return {**h_user, "X-SG-Workspace": "tdm"}


def _open_iv(client, headers):
    """服务层开标（REST 无开标端点）。"""
    from specstd.workspace import specflow_dir, set_context_emp_no
    from workbench.backend.services.specflow.interview_service import open_interview
    set_context_emp_no("90000002")
    r = open_interview(
        title="绩效域调整", initiator_emp="90000002", initiator_role="product",
        source=[{"type": "prd_section", "ref": "PRD §2.7"}],
        session_id="SESS-1", workspace="tdm", specflow_base=specflow_dir())
    return r["iv_id"]


class TestMaterialREST:
    def test_upload_md_indexed(self, rest_env):
        """上传 .md → 解析 → indexed（F3 验收 1 主路径）。"""
        headers = _as_product(rest_env)
        iv_id = _open_iv(rest_env, headers)
        r = rest_env.post(
            f"/api/specflow/interviews/{iv_id}/materials",
            headers=headers,
            files={"file": ("meeting-notes.md",
                             "# 会议纪要\n绩效阈值调整讨论".encode("utf-8"),
                             "text/markdown")})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "indexed"
        assert data["material"]["sha256_12"]
        # 列表可见
        lst = rest_env.get(f"/api/specflow/interviews/{iv_id}/materials",
                           headers=headers)
        assert len(lst.json()["materials"]) == 1

    def test_upload_binary_failed(self, rest_env):
        """未知二进制 → failed + parse_error（不静默降级）。"""
        headers = _as_product(rest_env)
        iv_id = _open_iv(rest_env, headers)
        r = rest_env.post(
            f"/api/specflow/interviews/{iv_id}/materials",
            headers=headers,
            files={"file": ("weird.bin", b"\x00\x01\x02\x03", "application/octet-stream")})
        assert r.status_code == 200
        assert r.json()["status"] == "failed"
        assert "无法识别" in r.json()["parse_error"]

    def test_upload_empty_rejected(self, rest_env):
        headers = _as_product(rest_env)
        iv_id = _open_iv(rest_env, headers)
        r = rest_env.post(
            f"/api/specflow/interviews/{iv_id}/materials",
            headers=headers,
            files={"file": ("empty.md", b"", "text/markdown")})
        assert r.status_code == 400

    def test_topic_confirm_requires_product(self, rest_env):
        """候选确认仅 product（tester → 403）。"""
        from services import user_store
        _login(rest_env, "90000001")
        h_tester = _login(rest_env, "90000003")
        user_store.set_roles("90000003", ["tester"], actor="90000001")
        user_store.grant_workspace("tdm", "90000003", "90000001")
        headers = {**h_tester, "X-SG-Workspace": "tdm"}
        r = rest_env.post("/api/specflow/materials/MAT-001/topics/T01/confirm",
                          headers=headers, json={"confirmed": True})
        assert r.status_code == 403

    def test_include_requires_product(self, rest_env):
        from services import user_store
        _login(rest_env, "90000001")
        h_tester = _login(rest_env, "90000003")
        user_store.set_roles("90000003", ["tester"], actor="90000001")
        user_store.grant_workspace("tdm", "90000003", "90000001")
        headers = {**h_tester, "X-SG-Workspace": "tdm"}
        r = rest_env.post("/api/specflow/interviews/IV-001/materials/MAT-001/include",
                          headers=headers, json={"included": True})
        assert r.status_code == 403

    def test_pack_read_before_assemble_404(self, rest_env):
        headers = _as_product(rest_env)
        iv_id = _open_iv(rest_env, headers)
        r = rest_env.get(f"/api/specflow/interviews/{iv_id}/pack", headers=headers)
        assert r.status_code == 404
