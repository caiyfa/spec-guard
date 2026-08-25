"""info_pack @引用注入测试（对齐业界附件模式）。

生产佐证（会话 20260824_172320_84d21cfa）：两批上传（SG-META-0007 3 文件 /
SG-META-0008 5 文件）均落盘成功，但 info_pack 引用只关联不注入——
模型上下文从未出现新信息包提示，只能拿工具描述示例 ID 读到旧包，
两轮均报告「没看到新附件」。

业界模式（OpenAI input_file / Anthropic document block / Cursor @ 展开）：
附件内容直接注入上传那一轮的 user message，模型当轮即见，无需工具绕圈。
"""
import hashlib

import pytest
from routers.agent import _process_references


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """隔离工作区：上传文件落盘 + safe_resolve 指向临时根。"""
    import specstd.workspace as wsm
    ws_root = tmp_path / "ws"
    uploads = ws_root / ".specguard" / "90024166" / "uploads"
    uploads.mkdir(parents=True)
    f1 = uploads / "权限文档.md"
    f1.write_text("# 权限文档\n\ncorpCode 过滤规则：无权限平台行必须剔除", encoding="utf-8")
    f2 = uploads / "映射表.csv"
    f2.write_text("resourceCode,接口\nPERS_LIST,/api/person/list", encoding="utf-8")

    def fake_resolve(p, name=None):
        target = (ws_root / p).resolve()
        return target if target.exists() else None

    monkeypatch.setattr(wsm, "safe_resolve", fake_resolve)

    def fake_meta(sid):
        if sid == "SG-META-0007":
            return {"id": sid, "name": "权限文档", "workspace": "人才发展",
                    "info_pack": [
                        {"path": ".specguard/90024166/uploads/权限文档.md", "sha": "aaa"},
                        {"path": ".specguard/90024166/uploads/映射表.csv", "sha": "bbb"},
                    ]}
        return None

    import sg_core.scenario_meta as sm_mod
    monkeypatch.setattr(sm_mod, "get_meta", fake_meta)
    return {"md": f1, "csv": f2}


def _sha(p) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


class TestInfoPackInjection:
    def test_ref_injects_file_contents(self, ws):
        """info_pack 引用注入全部文件内容（sha 标头 + 正文），模型当轮可见。"""
        sid, block, structured = _process_references(
            [{"type": "info_pack", "id": "SG-META-0007", "path": "SG-META-0007"}], "")
        assert sid == "SG-META-0007"
        assert block.startswith("<references>")
        assert "corpCode 过滤规则" in block
        assert "PERS_LIST,/api/person/list" in block
        assert f"(sha:{_sha(ws['md'])})" in block
        assert structured and structured[0]["type"] == "info_pack"

    def test_ref_takes_over_bound_scenario(self, ws):
        """已有绑定场景时，新上传的信息包无条件接管（生产案例：SG-META-0001 挡住 0007/0008）。"""
        sid, block, _ = _process_references(
            [{"type": "info_pack", "id": "SG-META-0007", "path": "SG-META-0007"}],
            "SG-META-0001")
        assert sid == "SG-META-0007"
        assert "corpCode" in block

    def test_missing_pack_visible_hint(self, ws):
        """信息包不存在时注入可见提示（不再静默让模型自己猜 ID）。"""
        sid, block, structured = _process_references(
            [{"type": "info_pack", "id": "SG-META-9999", "path": "SG-META-9999"}], "")
        assert sid == "SG-META-9999"
        assert "SG-META-9999" in block
        assert "不存在" in block or "不可读" in block

    def test_truncation_guard(self, ws, tmp_path, monkeypatch):
        """单文件超 _REF_MAX_FILE 截断 + 总量超 _REF_MAX_TOTAL 截断。"""
        import specstd.workspace as wsm
        ws_root = tmp_path / "ws"
        big = ws_root / ".specguard" / "90024166" / "uploads" / "大文档.md"
        big.write_text("x" * (25 * 1024), encoding="utf-8")

        def fake_resolve(p, name=None):
            target = (ws_root / p).resolve()
            return target if target.exists() else None

        monkeypatch.setattr(wsm, "safe_resolve", fake_resolve)
        import sg_core.scenario_meta as sm_mod
        monkeypatch.setattr(sm_mod, "get_meta", lambda sid: {
            "id": sid, "name": "大文档", "info_pack": [
                {"path": ".specguard/90024166/uploads/大文档.md"}]})

        _, block, _ = _process_references(
            [{"type": "info_pack", "id": "SG-META-BIG", "path": "SG-META-BIG"}], "")
        assert "[截断]" in block
        # 20KB 上限生效
        assert len(block) < 25 * 1024 + 500

    def test_office_doc_preview(self, ws, monkeypatch, tmp_path):
        """办公文档走 file_preview 转文本（K-030 同款守卫）。"""
        import specstd.workspace as wsm
        ws_root = tmp_path / "ws"
        f = ws_root / ".specguard" / "90024166" / "uploads" / "表.xlsx"
        f.write_bytes(b"PK-fake-xlsx")

        def fake_resolve(p, name=None):
            target = (ws_root / p).resolve()
            return target if target.exists() else None

        monkeypatch.setattr(wsm, "safe_resolve", fake_resolve)
        import sg_core.scenario_meta as sm_mod
        monkeypatch.setattr(sm_mod, "get_meta", lambda sid: {
            "id": sid, "name": "表", "info_pack": [
                {"path": ".specguard/90024166/uploads/表.xlsx"}]})

        from services import file_preview as fp_mod
        monkeypatch.setattr(fp_mod, "is_office_doc", lambda p: True)
        monkeypatch.setattr(fp_mod, "preview_text", lambda p: ("xlsx", "转换后的表格文本"))

        _, block, _ = _process_references(
            [{"type": "info_pack", "id": "SG-META-X", "path": "SG-META-X"}], "")
        assert "转换后的表格文本" in block
