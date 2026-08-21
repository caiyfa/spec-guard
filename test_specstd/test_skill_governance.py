"""test_skill_governance — 治理三件套测试（T-080/T-081/T-082）。

覆盖：
- Skill 格式校验（name/description 缺失拒载、<> 注入拒载、未知字段宽容）
- Skills REST 端点（列表正确、单技能查询）
- 悬空引用（purpose 引用不存在的 skill → warning）
- Side-effect 注册表（全量工具无遗漏、默认 none 正确、覆盖写工具正确）
- 纯读强制（none 工具写文件被拒绝、draft 工具不受限）
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 需要 mock 鉴权模式才能在 TestClient 中使用 mock token
os.environ["SG_AUTH_MODE"] = "mock"

SG_ROOT = Path(__file__).resolve().parent.parent

from agent import skill_loader, purpose_loader  # noqa: E402
from mcp_server.tools import side_effect_registry  # noqa: E402


# ══════════════════════════════════════════════════════════
# T-080: Skill 格式校验
# ══════════════════════════════════════════════════════════

class TestSkillValidation:
    """name/description 缺失拒载、<> 注入拒载、未知字段宽容。"""

    def test_missing_name_raises(self):
        """name 缺失 → ValueError。"""
        text = """---
description: 测试描述
keywords: [test]
---
正文
"""
        with pytest.raises(ValueError, match="name"):
            skill_loader._parse_skill_file("test", text)

    def test_empty_name_raises(self):
        """name 为空 → ValueError。"""
        text = """---
name: ""
description: 测试描述
---
正文
"""
        with pytest.raises(ValueError, match="name"):
            skill_loader._parse_skill_file("test", text)

    def test_missing_description_raises(self):
        """description 缺失 → ValueError。"""
        text = """---
name: test-skill
keywords: [test]
---
正文
"""
        with pytest.raises(ValueError, match="description"):
            skill_loader._parse_skill_file("test-skill", text)

    def test_empty_description_raises(self):
        """description 为空 → ValueError。"""
        text = """---
name: test-skill
description: ""
---
正文
"""
        with pytest.raises(ValueError, match="description"):
            skill_loader._parse_skill_file("test-skill", text)

    def test_injection_lt_gt_raises(self):
        """frontmatter 含 <...> 注入 → ValueError。"""
        text = """---
name: test-skill
description: 正常描述
keywords: [test]
purpose: <script>alert(1)</script>
---
正文
"""
        with pytest.raises(ValueError, match="<.*>"):
            skill_loader._parse_skill_file("test-skill", text)

    def test_unknown_fields_ignored(self):
        """未知字段静默忽略，不报错。"""
        text = """---
name: test-skill
description: 测试描述
keywords: [test]
unknown_field: 这个字段应该被忽略
another_unknown: 也忽略
---
正文
"""
        s = skill_loader._parse_skill_file("test-skill", text)
        assert s is not None
        assert s.name == "test-skill"

    def test_name_underscore_mismatch_rejected(self):
        """目录名=name 强校验：文件名用 - 而 name 用 _ → 拒载（不做 -/_ 等价）。"""
        text = """---
name: test_skill
description: 测试描述
---
正文
"""
        with pytest.raises(ValueError, match="不匹配"):
            skill_loader._parse_skill_file("test-skill", text)

    def test_version_author_parsed(self):
        """version/author/depends_tools 正确读取。"""
        text = """---
name: test-skill
version: 2.0.0
author: test-team
depends_tools:
  - write_draft
  - validate
description: 测试描述
keywords: [test]
---
正文
"""
        s = skill_loader._parse_skill_file("test-skill", text)
        assert s.version == "2.0.0"
        assert s.author == "test-team"
        assert s.depends_tools == ["write_draft", "validate"]

    def test_get_skill_metadata(self):
        """get_skill_metadata 返回元数据不含正文。"""
        # 用真实 skill 文件验证
        meta = skill_loader.get_skill_metadata("generate-scenario")
        assert meta is not None
        assert "name" in meta
        assert "version" in meta
        assert "description" in meta
        assert "author" in meta
        assert "source" in meta
        # 不应包含 content 正文
        assert "content" not in meta


# ══════════════════════════════════════════════════════════
# T-080: Skills REST 端点（通过 FastAPI TestClient）
# ══════════════════════════════════════════════════════════

class TestSkillsREST:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from workbench.backend.main import app
        return TestClient(app)

    def _headers(self, client):
        """mock-login 并返回鉴权 header。"""
        r = client.post("/api/auth/mock-login", json={"emp_no": "admin001", "name": "管理员"})
        assert r.status_code == 200
        token = r.json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_list_skills(self, client):
        """GET /api/agent/skills → 200 技能列表。"""
        headers = self._headers(client)
        r = client.get("/api/agent/skills", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "skills" in data
        assert len(data["skills"]) >= 10  # 至少有 10 个 skill
        for skill in data["skills"]:
            assert "name" in skill
            assert "version" in skill
            assert "description" in skill

    def test_get_skill_ok(self, client):
        """GET /api/agent/skills/generate-scenario → 200。"""
        headers = self._headers(client)
        r = client.get("/api/agent/skills/generate-scenario", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["skill"]["name"] == "generate-scenario"

    def test_get_skill_404(self, client):
        """GET /api/agent/skills/non-existent → 404。"""
        headers = self._headers(client)
        r = client.get("/api/agent/skills/non-existent-skill", headers=headers)
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════
# T-080: 悬空引用校验
# ══════════════════════════════════════════════════════════

class TestDanglingReference:
    @pytest.fixture(autouse=True)
    def clear_caches(self):
        skill_loader.clear_cache()
        purpose_loader._CACHE.clear()

    def test_dangling_skill_reference_warns(self, caplog):
        """purpose 引用不存在的 skill → warning 日志。"""
        text = """---
name: dangling-purpose
description: 测试悬空引用
skills:
  - non-existent-skill-xyz
---
正文
"""
        # 该 purpose 应在加载时记录 warning
        result = purpose_loader._parse_purpose_file("test-dangling", text)
        # 即使有 warning，返回结果不应为 None（宽容加载）
        assert result is not None
        # 检查 warning 日志
        warnings = [r for r in caplog.records if r.levelname == "WARNING" and "non-existent-skill-xyz" in str(r.message)]
        assert len(warnings) >= 1


# ══════════════════════════════════════════════════════════
# T-081: Side-effect 注册表
# ══════════════════════════════════════════════════════════

class TestSideEffectRegistry:
    def test_all_tools_registered(self):
        """side_effect_registry 覆盖全部 ALL_TOOLS。"""
        from mcp_server.server import ALL_TOOLS
        for tool in ALL_TOOLS:
            se = side_effect_registry.get_side_effect(tool.name)
            assert se in ("none", "draft", "external-write"), f"{tool.name} 未注册 side_effect"

    def test_default_is_none(self):
        """未显式声明的工具默认 none。"""
        # 选择一个纯读工具（如 spec_reader 的工具）
        se = side_effect_registry.get_side_effect("read_spec")
        assert se == "none"

    def test_writers_are_draft(self):
        """显式声明的写工具为 draft。"""
        writers = ["write_draft", "graph_rebuild", "graph_snapshot"]
        for name in writers:
            assert side_effect_registry.get_side_effect(name) == "draft"

    def test_list_by_side_effect(self):
        """list_tools_by_side_effect 返回正确分类。"""
        none_tools = side_effect_registry.list_tools_by_side_effect("none")
        draft_tools = side_effect_registry.list_tools_by_side_effect("draft")
        ext_tools = side_effect_registry.list_tools_by_side_effect("external-write")

        assert len(none_tools) > 0
        assert len(draft_tools) > 0
        assert len(ext_tools) == 0  # 默认为空
        # draft 工具应包含已知写入工具
        assert "write_draft" in draft_tools

    def test_is_pure_read(self):
        """is_pure_read 对 none 工具返回 True。"""
        assert side_effect_registry.is_pure_read("read_spec") is True
        assert side_effect_registry.is_pure_read("write_draft") is False

    def test_invalidate_cache(self):
        """invalidate_cache 清空缓存后重新构建。"""
        side_effect_registry.invalidate_cache()
        se = side_effect_registry.get_side_effect("write_draft")
        assert se == "draft"  # 重建后仍正确


# ══════════════════════════════════════════════════════════
# T-081: 纯读强制（模拟环境）
# ══════════════════════════════════════════════════════════

class TestPureReadEnforcement:
    """纯读强制核心路径（执行后指纹变化 → 拒绝+审计）。"""

    def _make_runtime(self):
        from agent.runtime import AgentRuntime
        llm = MagicMock()
        llm.is_mock = True
        llm.max_context_tokens = 0
        llm.chat.return_value = (
            {"role": "assistant", "content": ""},
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        return AgentRuntime(llm, max_turns=1)

    def test_pure_read_tool_write_rejected(self):
        """none 工具执行后仓库指纹变化 → SIDE_EFFECT_VIOLATION + denied 审计。"""
        from agent.runtime import AgentRuntime
        from mcp.types import TextContent
        from unittest.mock import AsyncMock

        rt = self._make_runtime()
        # read_spec 是 none 级且真实注册；patch 白名单放行 + 指纹先后不同（模拟副作用）
        with patch.object(rt, "_tool_whitelist", {"read_spec"}), \
             patch.object(rt, "_tool_map", {"read_spec": MagicMock(
                 handle=AsyncMock(return_value=[TextContent(type="text", text="ok")]))}), \
             patch.object(rt, "_take_snapshot_fingerprint",
                          side_effect=["fp-before", "fp-after"]), \
             patch.object(rt, "_record_audit") as rec:
            out = rt._execute_tool({"function": {"name": "read_spec",
                                                 "arguments": "{}"}})
        assert "[SIDE_EFFECT_VIOLATION]" in out
        rec.assert_called_once()
        assert rec.call_args.args[1] == "denied-side-effect"

    def test_pure_read_tool_no_change_ok(self):
        """none 工具执行后指纹不变 → 正常放行（verdict=ok）。"""
        from mcp.types import TextContent
        from unittest.mock import AsyncMock

        rt = self._make_runtime()
        with patch.object(rt, "_tool_whitelist", {"read_spec"}), \
             patch.object(rt, "_tool_map", {"read_spec": MagicMock(
                 handle=AsyncMock(return_value=[TextContent(type="text", text="ok")]))}), \
             patch.object(rt, "_take_snapshot_fingerprint", return_value="fp-same"), \
             patch.object(rt, "_record_audit") as rec:
            out = rt._execute_tool({"function": {"name": "read_spec",
                                                 "arguments": "{}"}})
        assert "SIDE_EFFECT_VIOLATION" not in out
        assert "ok" in out
        rec.assert_called_once()
        assert rec.call_args.args[1] == "ok"

    def test_side_effect_external_write_rejected(self):
        """external-write 级工具 → 执行前确定性拒绝（不触 handle）+ denied 审计。"""
        from mcp.types import TextContent
        from unittest.mock import AsyncMock

        rt = self._make_runtime()
        handler = MagicMock(
            handle=AsyncMock(return_value=[TextContent(type="text", text="不应执行")]))
        with patch.object(rt, "_tool_whitelist", {"read_spec"}), \
             patch.object(rt, "_tool_map", {"read_spec": handler}), \
             patch("mcp_server.tools.side_effect_registry.get_side_effect",
                   return_value="external-write"), \
             patch.object(rt, "_record_audit") as rec:
            out = rt._execute_tool({"function": {"name": "read_spec",
                                                 "arguments": "{}"}})
        assert "[拒绝]" in out and "external-write" in out
        handler.handle.assert_not_awaited()  # 执行前拒绝
        rec.assert_called_once()
        assert rec.call_args.args[1] == "denied-side-effect"

    def test_todo_write_recorded_audit(self):
        """T-082：todo_write（meta 工具）同样落审计（draft 级）。"""
        rt = self._make_runtime()
        with patch.object(rt, "_record_audit") as rec:
            out = rt._execute_tool({"function": {"name": "todo_write", "arguments":
                '{"todos": [{"id": "t1", "title": "x", "status": "pending"}]}'}})
        assert "待办已更新" in out
        rec.assert_called_once()
        assert rec.call_args.args[1] == "ok"
        assert rec.call_args.args[4] == "draft"  # side_effect=draft

    def test_snapshot_fingerprint_covers_workspace(self):
        """T-081：指纹目录含工作区产物与台账 DB（纯读工具写工作区草稿可检出）。"""
        import inspect
        from agent.runtime import AgentRuntime
        src = inspect.getsource(AgentRuntime._take_snapshot_fingerprint)
        assert "specguard_dir" in src
        assert "workbench.db" in src

    def test_fingerprint_stable_without_change(self):
        """无变更时指纹稳定（旧断言保留）。"""
        rt = self._make_runtime()
        fp1 = rt._take_snapshot_fingerprint()
        fp2 = rt._take_snapshot_fingerprint()
        assert fp1 == fp2


# ══════════════════════════════════════════════════════════
# T-081/T-082：注册表一致性 + 审计脱敏
# ══════════════════════════════════════════════════════════

class TestRegistryConsistency:
    def test_no_dangling_writer_declarations(self):
        """_KNOWN_WRITERS 无僵尸声明：声明的写工具必须真实注册（add_to_info_pack 为
        runtime 模式特例——stdio 刻意排除，见 server.build_tool_modules）。"""
        from mcp_server.server import ALL_TOOLS
        reg_names = {t.name for t in ALL_TOOLS}
        allowed_missing = {"add_to_info_pack"}
        dangling = [k for k in side_effect_registry._KNOWN_WRITERS
                    if k not in reg_names and k not in allowed_missing]
        assert dangling == [], f"僵尸声明: {dangling}"

    def test_no_duplicate_writer_declarations(self):
        """_KNOWN_WRITERS 无重复键（dict 字面量重复声明会静默覆盖）。"""
        src = Path(side_effect_registry.__file__).read_text(encoding="utf-8")
        for key in side_effect_registry._KNOWN_WRITERS:
            assert src.count(f'"{key}"') == 1, f"重复声明: {key}"

    def test_pure_read_tools_classified_none(self):
        """自证纯读的工具必须为 none（纯读强制覆盖，不缩小检测面）。"""
        for name in ("query_coverage_gaps", "query_coverage_backlink",
                     "sf_check_p0_gate", "sf_read_score_gate",
                     "iv_p0_clear_check", "sf_list_decisions"):
            assert side_effect_registry.get_side_effect(name) == "none", name


class TestAuditMasking:
    def test_json_token_masked(self):
        """JSON 键值形态脱敏（此前漏网：Bearer/token 明文落库）。"""
        from workbench.backend.services.audit_store import _mask_sensitive
        assert _mask_sensitive('{"token": "abc123", "x": 1}') == '{"token": ***, "x": 1}'
        assert _mask_sensitive('{"token":abc123}') == '{"token":***}'

    def test_bearer_header_masked(self):
        """Authorization Bearer 头脱敏。"""
        from workbench.backend.services.audit_store import _mask_sensitive
        out = _mask_sensitive('{"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9"}')
        assert "eyJhbGci" not in out
        assert "***" in out

    def test_query_form_masked(self):
        """query 形态 token/password 脱敏。"""
        from workbench.backend.services.audit_store import _mask_sensitive
        assert _mask_sensitive("password=secret123&a=1") == "password=***&a=1"
        assert _mask_sensitive('{"url": "http://a.com?token=xyz&b=2"}') == \
            '{"url": "http://a.com?token=***&b=2"}'

    def test_record_call_persists_masked(self, tmp_path):
        """record_call 落库即脱敏（DB 中无明文 token）。"""
        import sqlite3
        from workbench.backend.services import audit_store
        db = tmp_path / "audit.db"
        audit_store.record_call(
            tool_name="read_spec", verdict="ok",
            args_raw='{"token": "super-secret-token-xyz"}',
            result_raw='{"Authorization": "Bearer abc.def"}',
            db_path=db,
        )
        rows = audit_store.query_calls(db_path=db)
        assert len(rows) == 1
        assert "super-secret-token-xyz" not in rows[0]["args_digest"]
        assert "abc.def" not in rows[0]["result_digest"]
        assert "***" in rows[0]["args_digest"]