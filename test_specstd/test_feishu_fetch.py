"""S2.5 feishu_fetch MCP 工具测试（T-025/T-026）。

覆盖：
- feishu_calendar_agenda：日程解析/空日程/参数校验/权限错误
- feishu_meeting_notes 全链路：note 主链路 / minutes 兜底 / 无产物 hint / 无权限块
- _run_lark：Windows 命令构造 / 非 JSON / 超时
全部离线：monkeypatch _run_lark，不触真实飞书。
"""

import asyncio
import subprocess
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent

from mcp_server.tools import feishu_fetch  # noqa: E402


def _call(module, name, arguments):
    return asyncio.run(module.handle(name, arguments))


def _chain_calls(monkeypatch, script):
    """按调用顺序消费 script 中的 mock 响应，返回全部调用参数。"""
    calls = []
    it = iter(script)

    def fake(args):
        calls.append(args)
        return next(it)(args)

    monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
    return calls


def _agenda_payload(events=None):
    return {"ok": True, "identity": "user", "data": events or []}


def _meeting_payload(meetings=None):
    return {"ok": True, "identity": "user",
            "data": {"meetings": meetings or []}}


# ══════════════════════════════════════════════════════════
# T-025：feishu_calendar_agenda
# ══════════════════════════════════════════════════════════

class TestAgenda:
    def test_agenda_ok(self, monkeypatch):
        calls = []

        def fake(args):
            calls.append(args)
            return _agenda_payload([{
                "event_id": "evt_1_0",
                "summary": "【线上】COE迭代评审",
                "start_time": {"datetime": "2026-08-11T09:00:00+08:00"},
                "end_time": {"datetime": "2026-08-11T10:00:00+08:00"},
                "event_organizer": {"display_name": "贺文君"},
                "app_link": "https://applink.feishu.cn/evt",
                "vchat": {"meeting_url": "https://vc.feishu.cn/j/1"},
            }])

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_calendar_agenda", {
            "start": "2026-08-11T00:00:00+08:00",
            "end": "2026-08-12T00:00:00+08:00",
        })
        text = r[0].text
        assert "'status': 'ok'" in text
        assert "COE迭代评审" in text
        assert "evt_1_0" in text
        # 命令透传：--as user --start --end --format json
        assert "--as" in calls[0] and "user" in calls[0]
        assert "2026-08-11T00:00:00+08:00" in calls[0]

    def test_agenda_empty(self, monkeypatch):
        monkeypatch.setattr(feishu_fetch, "_run_lark",
                            lambda args: _agenda_payload())
        r = _call(feishu_fetch, "feishu_calendar_agenda", {})
        assert "'events': []" in r[0].text
        assert "'total': 0" in r[0].text

    def test_agenda_max_results(self, monkeypatch):
        monkeypatch.setattr(feishu_fetch, "_run_lark", lambda args: _agenda_payload(
            [{"event_id": f"e{i}", "summary": f"S{i}",
              "start_time": {}, "end_time": {}} for i in range(5)]))
        r = _call(feishu_fetch, "feishu_calendar_agenda", {"max_results": 2})
        assert "'total': 5" in r[0].text
        # 只返回前 2 条
        assert "e0" in r[0].text and "e1" in r[0].text and "e4" not in r[0].text

    def test_agenda_bad_max_results(self, monkeypatch):
        r = _call(feishu_fetch, "feishu_calendar_agenda", {"max_results": 0})
        assert "max_results 须在 1-100 之间" in r[0].text

    def test_agenda_lark_error(self, monkeypatch):
        def boom(args):
            raise ValueError("lark-cli 调用失败: 认证未就绪")
        monkeypatch.setattr(feishu_fetch, "_run_lark", boom)
        r = _call(feishu_fetch, "feishu_calendar_agenda", {})
        assert "日程拉取失败" in r[0].text


# ══════════════════════════════════════════════════════════
# T-025：feishu_meeting_notes 全链路
# ══════════════════════════════════════════════════════════

class TestMeetingNotes:
    def test_note_chain_full(self, monkeypatch):
        """主链路：+meeting → vc +detail → note +detail → docs +fetch。"""
        script = [
            lambda a: _meeting_payload([{"event_id": "E1", "meeting_id": "M1"}]),
            lambda a: _meeting_payload([{"meeting_id": "M1", "topic": "T",
                                         "note_id": "N1", "minute_token": ""}]),
            # 实测 lark-cli 形态：token 在 data.note 内层
            lambda a: {"ok": True, "data": {"note": {"note_id": "N1",
                                                         "note_doc_token": "DOC1"}}},
            lambda a: {"ok": True, "data": {"content": "纪要正文内容"}},
        ]
        calls = _chain_calls(monkeypatch, script)
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "E1"})
        text = r[0].text
        assert "'source': 'note'" in text
        assert "纪要正文内容" in text
        # 链路命令顺序验证
        assert "+meeting" in calls[0] and "--event-ids" in calls[0]
        assert "vc" in calls[1] and "+detail" in calls[1]
        assert "note" in calls[2] and "--note-id" in calls[2]
        assert "docs" in calls[3] and "+fetch" in calls[3]

    def test_minutes_fallback_chain(self, monkeypatch):
        """兜底链路：vc 仅给 minute_token → minutes +detail --summary。"""
        script = [
            lambda a: _meeting_payload([{"event_id": "E1", "meeting_id": "M1"}]),
            lambda a: _meeting_payload([{"meeting_id": "M1", "topic": "T",
                                         "note_id": "", "minute_token": "MT1"}]),
            lambda a: {"ok": True, "data": {"summary": "妙记总结"}},
        ]
        calls = _chain_calls(monkeypatch, script)
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "E1"})
        text = r[0].text
        assert "'source': 'minutes'" in text
        assert "妙记总结" in text
        assert "--summary" in calls[2] and "--keyword" in calls[2]

    def test_minutes_without_keywords(self, monkeypatch):
        script = [
            lambda a: _meeting_payload([{"event_id": "E1", "meeting_id": "M1"}]),
            lambda a: _meeting_payload([{"meeting_id": "M1", "topic": "T",
                                         "note_id": "", "minute_token": "MT1"}]),
            lambda a: {"ok": True, "data": {}},
        ]
        calls = _chain_calls(monkeypatch, script)
        _call(feishu_fetch, "feishu_meeting_notes",
              {"event_id": "E1", "with_keywords": False})
        assert "--keyword" not in calls[2]

    def test_no_meeting(self, monkeypatch):
        """日程无关联会议 → not_available 友好提示（不报错）。"""
        script = [lambda a: _meeting_payload([])]
        _chain_calls(monkeypatch, script)
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "E1"})
        assert "'status': 'not_available'" in r[0].text
        assert "无关联会议" in r[0].text

    def test_meeting_in_progress(self, monkeypatch):
        """会议进行中无 note/minute → hint 原样返回。"""
        script = [
            lambda a: _meeting_payload([{"event_id": "E1", "meeting_id": "M1"}]),
            lambda a: _meeting_payload([{"meeting_id": "M1", "topic": "T",
                                         "hint": "meeting is still in progress; "
                                                 "note and minute are not generated yet"}]),
        ]
        _chain_calls(monkeypatch, script)
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "E1"})
        text = r[0].text
        assert "'status': 'not_available'" in text
        assert "进行中" in text or "not generated" in text or "暂无纪要" in text

    def test_empty_event_id(self, monkeypatch):
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "  "})
        assert "event_id 不能为空" in r[0].text

    def test_note_without_doc_token(self, monkeypatch):
        """note 存在但无 note_doc_token → 元信息 + 逐字稿路由提示。"""
        script = [
            lambda a: _meeting_payload([{"event_id": "E1", "meeting_id": "M1"}]),
            lambda a: _meeting_payload([{"meeting_id": "M1", "topic": "T",
                                         "note_id": "N1"}]),
            lambda a: {"ok": True, "data": {"note_id": "N1",
                                            "note_display_type": "normal",
                                            "verbatim_doc_token": "VD1"}},
        ]
        _chain_calls(monkeypatch, script)
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "E1"})
        assert "'source': 'note_meta'" in r[0].text
        assert "逐字稿" in r[0].text


# ══════════════════════════════════════════════════════════
# T-026：无权限结构化引导
# ══════════════════════════════════════════════════════════

class TestPermissionBlock:
    def test_minutes_permission_denied(self, monkeypatch):
        """minutes 无权限 → 结构化块（含 apply_command，不静默降级）。"""
        def boom(args):
            raise ValueError("无权限查看该妙记，请申请权限")
        script = [
            lambda a: _meeting_payload([{"event_id": "E1", "meeting_id": "M1"}]),
            lambda a: _meeting_payload([{"meeting_id": "M1", "topic": "机密会",
                                         "note_id": "", "minute_token": "MT9"}]),
            boom,
        ]
        _chain_calls(monkeypatch, script)
        r = _call(feishu_fetch, "feishu_meeting_notes", {"event_id": "E1"})
        text = r[0].text
        assert "'status': 'permission_denied'" in text
        assert "minutes +apply-permission --minute-token MT9" in text
        assert "申请权限" in text

    def test_agenda_permission_denied(self, monkeypatch):
        """日程拉取遇权限错误 → 确定性失败消息（含提示语）。"""
        def boom(args):
            raise ValueError("lark-cli 调用失败: no permission")
        monkeypatch.setattr(feishu_fetch, "_run_lark", boom)
        r = _call(feishu_fetch, "feishu_calendar_agenda", {})
        assert "日程拉取失败" in r[0].text


# ══════════════════════════════════════════════════════════
# _run_lark 封装
# ══════════════════════════════════════════════════════════

class TestRunLark:
    """lark-cli 封装行为（T-914 起实现迁至 specflow.feishu_pool.lark_cli，
    feishu_fetch 经 import 复用——patch 目标指向实现所在模块命名空间）。"""

    def test_windows_command_prefix(self, monkeypatch):
        """Windows 下经 cmd /c 执行 lark-cli.cmd（实测：直接 CreateProcess 会 FileNotFound）。"""
        from specflow.feishu_pool import lark_cli
        monkeypatch.setattr(lark_cli, "sys", type("S", (), {"platform": "win32"})())
        cmd = feishu_fetch._lark_command()
        assert cmd[0] == "cmd" and cmd[1] == "/c"
        assert "lark-cli" in cmd[2].lower()

    def test_non_win_command_prefix(self, monkeypatch):
        from specflow.feishu_pool import lark_cli
        monkeypatch.setattr(lark_cli, "sys", type("S", (), {"platform": "linux"})())
        assert feishu_fetch._lark_command() == ["lark-cli"]

    def test_non_json_output(self, monkeypatch):
        from specflow.feishu_pool import lark_cli
        class P:
            returncode = 1
            stdout = "some plain text"
            stderr = ""
        monkeypatch.setattr(lark_cli.subprocess, "run",
                            lambda *a, **k: P())
        with pytest.raises(ValueError, match="输出非 JSON"):
            feishu_fetch._run_lark(["calendar", "+agenda"])

    def test_ok_false(self, monkeypatch):
        class P:
            returncode = 1
            stdout = '{"ok": false, "error": "boom"}'
            stderr = ""
        from specflow.feishu_pool import lark_cli
        monkeypatch.setattr(lark_cli.subprocess, "run",
                            lambda *a, **k: P())
        with pytest.raises(ValueError, match="调用失败"):
            feishu_fetch._run_lark(["calendar", "+agenda"])

    def test_timeout(self, monkeypatch):
        from specflow.feishu_pool import lark_cli
        def hang(*a, **k):
            raise subprocess.TimeoutExpired("lark-cli", 90)
        monkeypatch.setattr(lark_cli.subprocess, "run", hang)
        with pytest.raises(ValueError, match="超时"):
            feishu_fetch._run_lark(["calendar", "+agenda"])


# ══════════════════════════════════════════════════════════
# S5 增补：feishu_doc_read（云文档正文）
# ══════════════════════════════════════════════════════════

_DOC_PAYLOAD = {"ok": True, "data": {"document": {
    "content": "<title>测试文档</title><p>正文内容</p>",
    "document_id": "D1", "revision_id": 1}}}


def _doc_payload(*args):
    return _DOC_PAYLOAD


class TestDocRead:
    def test_doc_read_ok(self, monkeypatch):
        calls = []

        def fake(args, **kwargs):
            calls.append(args)
            return _DOC_PAYLOAD

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_doc_read",
                  {"doc": "https://x.feishu.cn/docx/DnUwXXX"})
        text = r[0].text
        assert "'ok': True" in text
        assert "测试文档" in text
        # 命令构造：--doc-format markdown + URL 原样传递
        assert calls[0][:3] == ["docs", "+fetch", "--as"]
        assert "--doc-format" in calls[0] and "markdown" in calls[0]
        assert "https://x.feishu.cn/docx/DnUwXXX" in calls[0]

    def test_doc_read_truncate(self, monkeypatch):
        def fake(args, **kwargs):
            return {"ok": True, "data": {"document": {"content": "x" * 9000}}}

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_doc_read",
                  {"doc": "D1", "max_chars": 100})
        text = r[0].text
        assert "'truncated': True" in text
        assert len(text) < 2000  # 截断生效

    def test_doc_read_empty_doc(self, monkeypatch):
        r = _call(feishu_fetch, "feishu_doc_read", {})
        assert "doc 必填" in r[0].text

    def test_doc_read_permission_denied(self, monkeypatch):
        def boom(args, **kwargs):
            raise ValueError("lark-cli 调用失败: 无权限查看该文档")

        monkeypatch.setattr(feishu_fetch, "_run_lark", boom)
        r = _call(feishu_fetch, "feishu_doc_read",
                  {"doc": "https://x.feishu.cn/docx/D1"})
        text = r[0].text
        assert "'status': 'permission_denied'" in text
        assert "'resource_type': 'docx'" in text


# ══════════════════════════════════════════════════════════
# S5 增补：feishu_base_query（多维表格记录）
# ══════════════════════════════════════════════════════════

_BASE_RESOLVE = {"ok": True, "data": {"base_token": "b1", "table_id": "t1"}}
_BASE_RECORDS = {"ok": True, "data": {"records": [{"fields": {"名称": "A"}}]}}


class TestBaseQuery:
    def test_base_query_ok(self, monkeypatch):
        calls = []
        script = [
            lambda a: _BASE_RESOLVE,
            lambda a: _BASE_RECORDS,
        ]
        it = iter(script)

        def fake(args, **kwargs):
            calls.append(args)
            return next(it)(args)

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_base_query",
                  {"url": "https://x.feishu.cn/base/b1"})
        text = r[0].text
        assert "'ok': True" in text
        assert "'record_count': 1" in text
        assert calls[0][:3] == ["base", "+url-resolve", "--url"]
        assert "--base-token" in calls[1] and "b1" in calls[1]
        assert "--table-id" in calls[1] and "t1" in calls[1]

    def test_base_query_no_base_token(self, monkeypatch):
        monkeypatch.setattr(feishu_fetch, "_run_lark",
                            lambda args, **kwargs: {"ok": True, "data": {}})
        r = _call(feishu_fetch, "feishu_base_query",
                  {"url": "https://x.feishu.cn/base/b9"})
        assert "未返回 base_token" in r[0].text

    def test_base_query_permission_denied(self, monkeypatch):
        def boom(args, **kwargs):
            raise ValueError("lark-cli 调用失败: permission denied")

        monkeypatch.setattr(feishu_fetch, "_run_lark", boom)
        r = _call(feishu_fetch, "feishu_base_query",
                  {"url": "https://x.feishu.cn/base/b1"})
        assert "'status': 'permission_denied'" in r[0].text
        assert "'resource_type': 'base'" in r[0].text


# ══════════════════════════════════════════════════════════
# 链接统一解析入口：feishu_link_read（/docx/ /wiki/ /minutes/ /base/）
# ══════════════════════════════════════════════════════════

class TestLinkRead:
    def test_docx_route(self, monkeypatch):
        calls = []

        def fake(args, **kwargs):
            calls.append(args)
            return _DOC_PAYLOAD

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://fehorizon.feishu.cn/docx/DnUwXXX"})
        text = r[0].text
        assert "'type': 'docx'" in text
        assert "测试文档" in text
        assert calls[0][0] == "docs" and "--doc-format" in calls[0]

    def test_wiki_route(self, monkeypatch):
        monkeypatch.setattr(feishu_fetch, "_run_lark",
                            lambda args, **kwargs: _DOC_PAYLOAD)
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://x.feishu.cn/wiki/W1"})
        assert "'type': 'wiki'" in r[0].text

    def test_minutes_route(self, monkeypatch):
        """妙记链接：路径末段提取 token（剥离 query 参数），minutes +detail --summary --keyword。"""
        calls = []

        def fake(args):
            calls.append(args)
            return {"ok": True, "data": {"summary": "妙记总结内容"}}

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://x.feishu.cn/minutes/obcn123?from=share"})
        text = r[0].text
        assert "'type': 'minutes'" in text
        assert "'minute_token': 'obcn123'" in text
        assert "妙记总结内容" in text
        assert calls[0][0] == "minutes" and "--minute-tokens" in calls[0]
        assert "obcn123" in calls[0]
        assert "--summary" in calls[0] and "--keyword" in calls[0]

    def test_base_route(self, monkeypatch):
        calls = []
        script = [lambda a: _BASE_RESOLVE, lambda a: _BASE_RECORDS]
        it = iter(script)

        def fake(args, **kwargs):
            calls.append(args)
            return next(it)(args)

        monkeypatch.setattr(feishu_fetch, "_run_lark", fake)
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://x.feishu.cn/base/b1?table=tb1"})
        text = r[0].text
        assert "'type': 'base'" in text
        assert "'record_count': 1" in text
        assert calls[0][0] == "base" and "+url-resolve" in calls[0]
        assert calls[1][0] == "base" and "+record-list" in calls[1]

    def test_unknown_route(self, monkeypatch):
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://example.com/foo"})
        assert "无法识别链接类型" in r[0].text
        assert "仅支持 /docx/ /wiki/ /minutes/ /base/" in r[0].text

    def test_empty_url(self, monkeypatch):
        r = _call(feishu_fetch, "feishu_link_read", {})
        assert "url 必填" in r[0].text

    def test_minutes_permission_denied(self, monkeypatch):
        def boom(args):
            raise ValueError("lark-cli 调用失败: 无权限查看该妙记")

        monkeypatch.setattr(feishu_fetch, "_run_lark", boom)
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://x.feishu.cn/minutes/obcn99"})
        text = r[0].text
        assert "'status': 'permission_denied'" in text
        assert "'resource_type': 'minutes'" in text
        assert "minutes +apply-permission --minute-token obcn99" in text

    def test_docx_permission_denied(self, monkeypatch):
        def boom(args, **kwargs):
            raise ValueError("lark-cli 调用失败: forbidden")

        monkeypatch.setattr(feishu_fetch, "_run_lark", boom)
        r = _call(feishu_fetch, "feishu_link_read",
                  {"url": "https://x.feishu.cn/docx/D1"})
        assert "'status': 'permission_denied'" in r[0].text
        assert "'resource_type': 'docx'" in r[0].text
