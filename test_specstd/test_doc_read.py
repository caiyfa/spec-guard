"""doc_read 阅读足迹事件测试（S0.5 · T-511 依据透明）。

验证：
1. build_doc_read 纯函数：五读型工具字段映射 / 写型与查询型 None / 错误结果 None
2. runtime 集成：读型工具调用后发 doc_read WS 事件（含 thinking 捎带）
3. read_run_log tail hunk 行区间换算
"""

import json
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from agent.doc_read import READ_DOC_TOOLS, build_doc_read
from agent.runtime import AgentRuntime


class MockLLM:
    """可配置响应序列的 mock LLM（与 test_agent.py 同款）。"""

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
# build_doc_read 纯函数
# ══════════════════════════════════════════════════════════

class TestBuildDocRead:
    def test_read_spec_fields(self):
        evt = build_doc_read(
            "read_spec", {"path": "specs/employee/person-profile/spec.md"},
            "# 规格\n内容行2\n内容行3", turn=3, thinking="确认权限过滤规则")
        assert evt is not None
        assert evt["tool"] == "read_spec"
        assert evt["ref"] == "specs/employee/person-profile/spec.md"
        assert evt["path"] == "specs/employee/person-profile/spec.md"
        assert evt["turn"] == 3
        assert evt["size"] == len("# 规格\n内容行2\n内容行3")
        assert evt["label"] == "查阅 spec.md"
        assert evt["thinking"] == "确认权限过滤规则"
        assert len(evt["hunks"]) == 1
        assert evt["hunks"][0]["start"] == 1
        assert "read_spec(path=" in evt["hunks"][0]["note"]

    def test_read_spec_anchor_label(self):
        evt = build_doc_read(
            "read_spec", {"path": "specs/a/b/spec.md", "anchor": "FR-009"},
            "chunk", turn=1)
        assert evt["label"] == "引用需求条目 FR-009"

    def test_read_spec_sg_root_not_openable(self):
        """sg:// 仓库根路径 read-file 不可达 → path=None（前端 memo 兜底）。"""
        evt = build_doc_read("read_spec", {"path": "sg://README.md"}, "内容", turn=1)
        assert evt["path"] is None
        assert evt["ref"] == "sg://README.md"

    def test_read_scenario_label(self):
        evt = build_doc_read("read_scenario", {"id": "PP-PERM-001"}, "doc: ...", turn=2)
        assert evt["label"] == "查看场景 PP-PERM-001"
        assert evt["path"] is None  # 仓库 scenarios/ 非工作区根内

    def test_read_run_report_memo_and_failed_cases(self):
        """报告类：聚合 JSON 无法映射 run.json 行区间 → path=None（memo 展示）；
        有失败场景时摘录优先给失败断言段（设计 §4.5）。"""
        ok_result = json.dumps({"run_id": "EX-abc12345", "stats": {}, "failed_cases": []})
        evt = build_doc_read("read_run_report", {"run_id": "EX-abc12345"}, ok_result, turn=1)
        assert evt["label"] == "查看执行报告 EX-abc12345"
        assert evt["path"] is None
        assert evt["hunks"][0]["title"] == "报告摘要"

        fail_result = json.dumps({"run_id": "EX-abc12345", "stats": {},
                                  "failed_cases": [{"scenario_id": "PP-RC-005",
                                                    "assertions": ["status 期望 200 实际 500"]}]},
                                 ensure_ascii=False)
        evt2 = build_doc_read("read_run_report", {"run_id": "EX-abc12345"}, fail_result, turn=1)
        assert "失败断言段" in evt2["hunks"][0]["title"]
        assert "PP-RC-005" in evt2["excerpt"]

    def test_section_header_hunk(self):
        """T-512：read_spec/read_scenario 章节分支标头 → 真实行区间 hunk。"""
        result = "--- specs/a/spec.md · FR-009：权限过滤 · 行51-58 ---\n- **FR-009**：权限过滤……"
        evt = build_doc_read("read_spec", {"path": "specs/a/spec.md", "anchor": "FR-009"},
                             result, turn=1)
        assert evt["hunks"] == [{"title": "FR-009：权限过滤", "start": 51, "end": 58,
                                 "note": "read_spec(path=specs/a/spec.md, anchor=FR-009)"}]
        result2 = "--- PP-RC-001 · flow 段 · 行10-22 ---\nflow:\n  - call: /a"
        evt2 = build_doc_read("read_scenario", {"id": "PP-RC-001", "part": "flow"},
                              result2, turn=1)
        assert evt2["hunks"][0]["start"] == 10
        assert evt2["hunks"][0]["end"] == 22
        assert evt2["label"] == "查看场景 PP-RC-001（flow 段）"

    def test_read_run_log_tail_hunk(self):
        result = json.dumps({"ok": True, "run_id": "EX-abc12345",
                             "total_lines": 500, "returned_lines": 200,
                             "log": "..."}, ensure_ascii=False)
        evt = build_doc_read("read_run_log", {"run_id": "EX-abc12345", "tail": 200},
                             result, turn=1)
        assert evt["path"] == ".specguard/reports/EX-abc12345/output.log"
        assert evt["hunks"] == [{
            "title": "尾部 200 行", "start": 301, "end": 500,
            "note": "read_run_log(run_id=EX-abc12345, tail=200)",
        }]

    def test_read_info_pack_label(self):
        evt = build_doc_read("read_info_pack", {"scenario_id": "SG-META-0001"}, "拼接", turn=1)
        assert evt["label"] == "查阅信息包 SG-META-0001"
        assert evt["path"] is None

    def test_non_doc_tools_rejected(self):
        """写型/查询型工具不上足迹（设计 §4.5 边界纪律）。"""
        for tool in ("write_draft", "promote_draft", "list_scenarios",
                     "query_registry", "read_case_detail", "validate", "run_scenario"):
            assert tool not in READ_DOC_TOOLS
            assert build_doc_read(tool, {}, "任意结果", turn=1) is None

    def test_error_results_rejected(self):
        """错误结果不产生足迹。"""
        assert build_doc_read("read_spec", {"path": "x"}, "错误：缺少 path 参数", 1) is None
        assert build_doc_read("read_spec", {"path": "x"}, "工具执行异常: boom", 1) is None
        assert build_doc_read("read_spec", {"path": "x"}, "OUT_OF_SCOPE: 越界", 1) is None
        bad_json = json.dumps({"ok": False, "error": "执行日志不存在"})
        assert build_doc_read("read_run_log", {"run_id": "EX-x"}, bad_json, 1) is None

    def test_excerpt_budget(self):
        """excerpt ≤ 2000 字符（宁少勿多）。"""
        evt = build_doc_read("read_scenario", {"id": "X"}, "长" * 5000, turn=1)
        assert len(evt["excerpt"]) == 2000
        assert evt["size"] == 5000


# ══════════════════════════════════════════════════════════
# runtime 集成（mock LLM，离线）
# ══════════════════════════════════════════════════════════

class TestRuntimeDocRead:
    def _run_and_collect(self, tool_name: str, arguments: str, thinking: str = ""):
        tc = _tool_call(tool_name, arguments)
        mock = MockLLM([
            {"role": "assistant", "content": thinking, "tool_calls": [tc]},
            {"role": "assistant", "content": "完成"},
        ])
        runtime = AgentRuntime(mock, max_turns=5)
        events = []
        runtime.events.subscribe(lambda e: events.append(e))
        runtime.run("sys", "test")
        return [e for e in events if e.get("type") == "doc_read"]

    def test_read_scenario_emits(self):
        """读型文档工具调用后发 doc_read，捎带本轮思考文本。"""
        evts = self._run_and_collect(
            "read_scenario", '{"id": "PP-PERM-001"}', thinking="先确认场景前置条件")
        assert len(evts) == 1
        evt = evts[0]
        assert evt["tool"] == "read_scenario"
        assert evt["ref"] == "PP-PERM-001"
        assert evt["turn"] == 0
        assert evt["thinking"] == "先确认场景前置条件"
        assert "doc" in evt["excerpt"] or "id" in evt["excerpt"]  # YAML 头部

    def test_query_tool_not_emitted(self):
        """查询型工具（list_scenarios）不发 doc_read。"""
        evts = self._run_and_collect("list_scenarios", "{}")
        assert evts == []

    def test_write_tool_not_emitted(self):
        """写型工具（write_draft 参数不全→错误结果）不发 doc_read。"""
        evts = self._run_and_collect("write_draft", "{}")
        assert evts == []

    def test_failed_read_not_emitted(self):
        """读型工具失败结果（不存在的 run_id → ok:false）不发 doc_read。"""
        evts = self._run_and_collect("read_run_log", '{"run_id": "EX-00000000"}')
        assert evts == []
