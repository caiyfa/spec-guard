"""doc_write 更新足迹事件测试（S0.6 · 更新与产物页签）。

验证：
1. build_doc_write 纯函数：七写型工具字段映射 / verdict 解析（conformance/门禁）/
   读型与查询型 None / 错误结果 None
2. runtime 集成：写型工具成功后发 doc_write WS 事件（含 thinking 捎带）
3. 会话恢复：_rebuild_writing_feed 从消息链重建（同文件去重合并 + 次数累计）
"""

import json
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.doc_write import WRITE_TOOLS, build_doc_write
from agent.runtime import AgentRuntime


class MockLLM:
    """可配置响应序列的 mock LLM（与 test_doc_read.py 同款）。"""

    def __init__(self, responses: list[dict] = None):
        self.responses = responses or []
        self._call_count = 0
        self.max_context_tokens = 0

    @property
    def is_mock(self):
        return True

    def chat(self, messages, tools=None, temperature=0.7, on_delta=None):
        if self._call_count < len(self.responses):
            resp = self.responses[self._call_count]
        else:
            resp = {"role": "assistant", "content": "（默认停止）"}
        self._call_count += 1
        return resp, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def set_metrics_file(self, path):
        pass

    def get_stats(self):
        return {"total_tokens": 0, "is_mock": True, "model": "mock"}


def _tool_call(name: str, arguments: str, call_id: str = "c1") -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": arguments}}


# ══════════════════════════════════════════════════════════
# build_doc_write 纯函数
# ══════════════════════════════════════════════════════════

class TestBuildDocWrite:
    def test_write_delta_doc_fields(self):
        """write_delta_doc：path 取自结果、verdict 取自 conformance 校验。"""
        result = json.dumps({
            "ok": True, "path": "changes/0817/delta-spec.md", "backup": True,
            "size": 100,
            "validation": {"verdict": "REJECT", "findings": [
                {"level": "ERROR", "rule": "STRUCT",
                 "message": "delta '0817' 缺少必备文件: proposal.md"}]},
        }, ensure_ascii=False)
        evt = build_doc_write(
            "write_delta_doc",
            {"delta_id": "0817", "filename": "delta-spec.md",
             "content": "# 变更\n行2\n行3"},
            result, turn=3, thinking="替换 FR 编号为 FR-0817-xxx")
        assert evt is not None
        assert evt["tool"] == "write_delta_doc"
        assert evt["ref"] == "0817/delta-spec.md"
        assert evt["path"] == "changes/0817/delta-spec.md"
        assert evt["turn"] == 3
        assert evt["verdict"] == "REJECT"
        # 失败原因与 verdict 同源提取（Agent 据此定位修复）
        assert evt["findings"] == [{"level": "ERROR", "rule": "STRUCT",
                                    "message": "delta '0817' 缺少必备文件: proposal.md"}]
        assert evt["label"] == "更新 delta-spec.md（delta 0817）"
        assert evt["thinking"] == "替换 FR 编号为 FR-0817-xxx"
        assert evt["excerpt"] == "# 变更\n行2\n行3"  # 写后内容头部
        assert evt["hunks"][0]["start"] == 1
        assert evt["hunks"][0]["end"] == 3
        # hunk note 含写型工具关键参数（delta_id/filename）
        note = evt["hunks"][0]["note"]
        assert "delta_id=0817" in note and "filename=delta-spec.md" in note

    def test_write_delta_doc_pass_verdict(self):
        result = json.dumps({"ok": True, "path": "changes/x/a.md",
                             "validation": {"verdict": "PASS", "findings": []}},
                            ensure_ascii=False)
        evt = build_doc_write("write_delta_doc",
                              {"delta_id": "x", "filename": "a.md", "content": "c"},
                              result, turn=1)
        assert evt["verdict"] == "PASS"
        assert evt["findings"] == []  # PASS 无失败原因

    def test_findings_capped_and_truncated(self):
        """失败原因上限 20 条、message 截断 200 字符（防 WS 事件膨胀）。"""
        findings = [{"level": "ERROR", "rule": "STRUCT", "message": f"缺文件 {i}"}
                    for i in range(25)]
        result = json.dumps({"ok": True, "path": "changes/x/a.md",
                             "validation": {"verdict": "REJECT", "findings": findings}},
                            ensure_ascii=False)
        evt = build_doc_write("write_delta_doc",
                              {"delta_id": "x", "filename": "a.md", "content": "c"},
                              result, turn=1)
        assert len(evt["findings"]) == 20
        long_msg = json.dumps({"ok": True, "path": "changes/x/a.md",
                               "validation": {"verdict": "REJECT",
                                               "findings": [{"level": "ERROR", "rule": "R",
                                                              "message": "长" * 500}]}},
                              ensure_ascii=False)
        evt2 = build_doc_write("write_delta_doc",
                               {"delta_id": "x", "filename": "a.md", "content": "c"},
                               long_msg, turn=1)
        assert len(evt2["findings"][0]["message"]) == 200

    def test_write_draft_create(self):
        result = json.dumps({"ok": True, "action": "create",
                             "path": ".specguard/drafts/PP-RC-008.yaml",
                             "size": 50}, ensure_ascii=False)
        evt = build_doc_write("write_draft",
                              {"filename": "PP-RC-008.yaml", "content": "id: PP-RC-008\ncovers:\n  - FR-009"},
                              result, turn=1)
        assert evt["label"] == "写入草稿 PP-RC-008.yaml"
        assert evt["path"] == ".specguard/drafts/PP-RC-008.yaml"
        assert evt["verdict"] is None

    def test_write_draft_patch_label(self):
        result = json.dumps({"ok": True, "action": "patch",
                             "path": ".specguard/drafts/x.yaml", "size": 60,
                             "backup": "x.yaml.bak"}, ensure_ascii=False)
        evt = build_doc_write("write_draft",
                              {"filename": "x.yaml", "content": "追加行", "mode": "patch"},
                              result, turn=2)
        assert evt["label"] == "追加草稿 x.yaml（patch）"

    def test_commit_delta_changes(self):
        result = json.dumps({"ok": True, "commit": "abc123",
                             "files": ["changes/0817/spec.md", "changes/0817/api-delta.yaml"],
                             "message": "feat: 0817 更新"}, ensure_ascii=False)
        evt = build_doc_write("commit_delta_changes", {"delta_id": "0817"}, result, turn=4)
        assert evt["label"] == "提交 delta 0817 变更（2 文件）"
        assert evt["path"] is None
        assert evt["verdict"] == "PASS"

    def test_add_to_info_pack(self):
        result = json.dumps({"ok": True, "scenario_id": "SG-META-0001",
                             "added_file": "specs/a/spec.md",
                             "info_pack": ["specs/a/spec.md"]}, ensure_ascii=False)
        evt = build_doc_write("add_to_info_pack",
                              {"scenario_id": "SG-META-0001", "path": "specs/a/spec.md"},
                              result, turn=1)
        assert evt["label"] == "信息包补充 specs/a/spec.md（SG-META-0001）"
        assert evt["ref"] == "SG-META-0001"
        assert evt["path"] is None

    def test_promote_draft_gate_verdicts(self):
        """入库 verdict 取自发布门禁：PASS / SKIP / REJECT 三态。"""
        ok = json.dumps({"ok": True, "scenario_id": "PP-RC-008",
                         "target": "scenarios/rc/PP-RC-008.yaml",
                         "gate": {"ok": True}}, ensure_ascii=False)
        evt = build_doc_write("promote_draft", {"filename": "PP-RC-008.yaml"}, ok, turn=5)
        assert evt["verdict"] == "PASS"
        assert evt["path"] == "scenarios/rc/PP-RC-008.yaml"
        assert evt["label"] == "入库草稿 PP-RC-008.yaml → scenarios/rc/PP-RC-008.yaml"

        skipped = json.dumps({"ok": True, "gate": {"skipped": True}}, ensure_ascii=False)
        assert build_doc_write("promote_draft", {"filename": "x.yaml"}, skipped, 1)["verdict"] == "SKIP"

        failed = json.dumps({"ok": True, "gate": {"ok": False}}, ensure_ascii=False)
        assert build_doc_write("promote_draft", {"filename": "x.yaml"}, failed, 1)["verdict"] == "REJECT"

    def test_promote_drafts_batch(self):
        result = json.dumps({"ok": True, "promoted": [{"file": "a.yaml"}, {"file": "b.yaml"}],
                             "gate": {"ok": True}}, ensure_ascii=False)
        evt = build_doc_write("promote_drafts", {"module": "rc"}, result, turn=6)
        assert evt["label"] == "批量入库 2 份草稿"
        assert evt["ref"] == "batch"
        assert evt["verdict"] == "PASS"

    def test_undo_draft(self):
        result = json.dumps({"ok": True, "action": "undo",
                             "path": ".specguard/drafts/x.yaml",
                             "restored_from": "x.yaml.bak"}, ensure_ascii=False)
        evt = build_doc_write("undo_draft", {"filename": "x.yaml"}, result, turn=2)
        assert evt["label"] == "撤销草稿 x.yaml（.bak 恢复）"
        assert evt["path"] == ".specguard/drafts/x.yaml"

    def test_non_write_tools_rejected(self):
        """读型/查询型工具不上更新足迹（对称边界纪律）。"""
        for tool in ("read_spec", "read_scenario", "list_scenarios",
                     "query_registry", "validate", "run_scenario", "todo_write"):
            assert tool not in WRITE_TOOLS
            assert build_doc_write(tool, {}, "任意结果", turn=1) is None

    def test_error_results_rejected(self):
        """错误结果不产生更新足迹（写失败不是更新依据）。"""
        assert build_doc_write("write_draft", {"filename": "x"}, "错误：缺少 content 参数", 1) is None
        assert build_doc_write("write_delta_doc", {}, "工具执行异常: boom", 1) is None
        assert build_doc_write("write_draft", {}, "OUT_OF_SCOPE: 越界", 1) is None
        bad_json = json.dumps({"ok": False, "error": "delta 不存在或代号非法"})
        assert build_doc_write("write_delta_doc", {"delta_id": "x", "filename": "a"},
                               bad_json, 1) is None

    def test_excerpt_budget(self):
        """excerpt ≤ 2000 字符（写后内容头部摘录，宁少勿多）。"""
        content = "行" * 5000
        result = json.dumps({"ok": True, "path": "changes/x/a.md",
                             "validation": {"verdict": "PASS"}}, ensure_ascii=False)
        evt = build_doc_write("write_delta_doc",
                              {"delta_id": "x", "filename": "a.md", "content": content},
                              result, turn=1)
        assert len(evt["excerpt"]) == 2000
        assert evt["size"] == len(result)


# ══════════════════════════════════════════════════════════
# runtime 集成（mock LLM + 实例级 _execute_tool 桩，不碰文件系统）
# ══════════════════════════════════════════════════════════

class TestRuntimeDocWrite:
    def _run_and_collect(self, tool_name: str, arguments: str,
                         tool_result: str, thinking: str = ""):
        tc = _tool_call(tool_name, arguments)
        mock = MockLLM([
            {"role": "assistant", "content": thinking, "tool_calls": [tc]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5)
        runtime._execute_tool = lambda _tc: tool_result  # 桩：跳过真实 MCP 执行
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        runtime.run("sys", "test")
        return [e for e in events if e.get("type") == "doc_write"]

    def test_write_tool_success_emits(self):
        """写型工具成功调用后发 doc_write，捎带本轮思考文本。"""
        result = json.dumps({"ok": True, "path": "changes/0817/spec.md",
                             "validation": {"verdict": "PASS", "findings": []}},
                            ensure_ascii=False)
        evts = self._run_and_collect(
            "write_delta_doc",
            '{"delta_id": "0817", "filename": "spec.md", "content": "# 新内容"}',
            result, thinking="替换 FR 编号")
        assert len(evts) == 1
        evt = evts[0]
        assert evt["tool"] == "write_delta_doc"
        assert evt["ref"] == "0817/spec.md"
        assert evt["verdict"] == "PASS"
        assert evt["thinking"] == "替换 FR 编号"

    def test_read_tool_not_emitted(self):
        """读型工具不发 doc_write。"""
        evts = self._run_and_collect("read_spec", '{"path": "specs/a/spec.md"}',
                                     "# 规格内容")
        assert evts == []

    def test_failed_write_not_emitted(self):
        """写型工具失败结果（ok:false）不发 doc_write。"""
        result = json.dumps({"ok": False, "error": "delta 不存在"})
        evts = self._run_and_collect("write_delta_doc",
                                     '{"delta_id": "x", "filename": "a"}', result)
        assert evts == []


# ══════════════════════════════════════════════════════════
# 会话恢复：_rebuild_writing_feed 重建（同文件去重合并 + 次数累计）
# ══════════════════════════════════════════════════════════

class TestRebuildWritingFeed:
    def test_rebuild_dedup_and_count(self):
        from workbench.backend.routers.agent import _rebuild_writing_feed
        ok = json.dumps({"ok": True, "path": "changes/0817/spec.md",
                         "validation": {"verdict": "PASS"}}, ensure_ascii=False)
        fail = json.dumps({"ok": True, "path": "changes/0817/spec.md",
                           "validation": {"verdict": "REJECT"}}, ensure_ascii=False)
        messages = [
            {"role": "assistant", "tool_calls": [
                _tool_call("write_delta_doc",
                           '{"delta_id": "0817", "filename": "spec.md", "content": "v1"}',
                           call_id="c1")]},
            {"role": "tool", "tool_call_id": "c1", "content": ok},
            {"role": "assistant", "tool_calls": [
                _tool_call("write_delta_doc",
                           '{"delta_id": "0817", "filename": "spec.md", "content": "v2"}',
                           call_id="c2")]},
            {"role": "tool", "tool_call_id": "c2", "content": fail},
            {"role": "assistant", "tool_calls": [
                _tool_call("write_draft",
                           '{"filename": "PP-RC-008.yaml", "content": "id: PP-RC-008"}',
                           call_id="c3")]},
            {"role": "tool", "tool_call_id": "c3",
             "content": json.dumps({"ok": True, "action": "create",
                                    "path": ".specguard/drafts/PP-RC-008.yaml"})},
        ]
        items = _rebuild_writing_feed(messages)
        assert len(items) == 2
        spec = next(i for i in items if "0817/spec.md" in i["key"])
        assert spec["writes"] == 2
        assert spec["verdict"] == "REJECT"  # 最新一次 verdict 优先
        assert spec["excerpt"] == "v2"
        draft = next(i for i in items if "PP-RC-008" in i["key"])
        assert draft["writes"] == 1
        assert draft["label"] == "写入草稿 PP-RC-008.yaml"
