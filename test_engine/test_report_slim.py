"""ENG-T04 报告体积瘦身：response_body / request body 大阈值截断（ENG-BUG-005）。

T-316 原设计「完整落盘供详细查询」的消费端（前端详细查询视图）未落地，成本在付
收益为零——复审 trade-off 后改为 20KB 上限截断（body_excerpt 摘要逻辑完全不动）。

设计依据：docs/架构升级/ENG-T04-报告体积瘦身.md §3.1/§6。
"""

import json
import os
import sys
from types import SimpleNamespace

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.execution_record import _BODY_MAX_CHARS, truncate_body  # noqa: E402
from engine.registry import Registry  # noqa: E402
from engine.scenario_loader import Scenario  # noqa: E402
from engine.scenario_runner import RunContext, register_builtin_steps, run_scenario  # noqa: E402


# ══════════════════════════════════════════════════════════
# truncate_body 单元行为
# ══════════════════════════════════════════════════════════

def test_truncate_body_small_passthrough_identity():
    """小载荷原样返回（is 同一对象——与历史行为逐字节一致）。"""
    small_str = "x" * 100
    assert truncate_body(small_str) is small_str
    small_obj = {"data": ["a", 1, None], "n": 2}
    assert truncate_body(small_obj) is small_obj


def test_truncate_body_oversized_capped_with_marker():
    """超限载荷：截到恰好 _BODY_MAX_CHARS 字符，尾部带「已截断+原始长度」留痕。"""
    big = "y" * 50_000
    out = truncate_body(big)
    assert isinstance(out, str)
    assert len(out) == _BODY_MAX_CHARS, f"截断后总长应恰为上限，实际 {len(out)}"
    assert out.startswith("y" * 100)
    assert "已截断" in out and f"原始共{len(big)}字符" in out, f"截断必须留痕: {out[-60:]}"


def test_truncate_body_object_serialized_then_capped():
    """dict/list 载荷按 JSON 序列化长度判定，超限返回带标注的截断文本。"""
    big_obj = {"rows": [{"id": i, "name": "n" * 40} for i in range(500)]}
    out = truncate_body(big_obj)
    assert isinstance(out, str)
    assert len(out) == _BODY_MAX_CHARS
    assert "已截断" in out
    full_len = len(json.dumps(big_obj, ensure_ascii=False))
    assert f"原始共{full_len}字符" in out


# ══════════════════════════════════════════════════════════
# step_call 落盘点（验收 1/2/3）
# ══════════════════════════════════════════════════════════

def _run_call(resp_obj, json_body=None):
    def _fake_request(method, path, **kw):
        resp = SimpleNamespace(status_code=200, headers={}, text="")
        resp.json = lambda: resp_obj
        return resp

    client = SimpleNamespace(request=_fake_request)
    reg = Registry()
    register_builtin_steps(reg)
    rc = RunContext(registry=reg, env_config={}, token_provider=None, graph=None, run_dir=".")
    rc.http_client = lambda acc, service="tdm": client
    call = {"method": "POST", "path": "/api/x", "json": json_body or {"q": 1}, "save": "r"}
    sc = Scenario(id="T-SLIM", flow=[{"call": call}],
                  verify=[{"status": {"of": "r", "eq": 200}}])
    return run_scenario(sc, rc)


def test_big_response_body_capped_excerpt_untouched():
    """验收1：5 万字符响应 → response_body ≤ 20KB 带截断标注；body_excerpt 仍是 500 字符摘要。"""
    resp_obj = {"data": "x" * 50_000}
    rec = _run_call(resp_obj)
    assert rec.verdict == "PASS"
    st = rec.steps[0]
    rb = st.response_body
    assert isinstance(rb, str), f"超限响应应为截断文本，实际 {type(rb).__name__}"
    assert len(rb) <= _BODY_MAX_CHARS
    assert "已截断" in rb and "原始共" in rb
    # body_excerpt 摘要逻辑完全不动：仍是 truncate 后的 500 字符上限结构
    excerpt_data = st.body_excerpt["data"]
    assert isinstance(excerpt_data, str)
    assert len(excerpt_data) <= 500 + 30, f"摘要仍应受 truncate 500 字符约束: {len(excerpt_data)}"
    assert "共50000字符" in excerpt_data, f"摘要应保留原文长度信息: {excerpt_data[-40:]}"


def test_small_response_body_byte_identical():
    """验收2：小响应（<20KB）→ response_body 与改动前逐字节一致（原对象直通）。"""
    resp_obj = {"data": {"list": [1, 2, 3], "msg": "ok"}}
    rec = _run_call(resp_obj)
    assert rec.verdict == "PASS"
    assert rec.steps[0].response_body == resp_obj, "小响应必须是原对象（非截断副本）"
    # 小请求体同样直通
    assert rec.steps[0].request["body"] == {"q": 1}


def test_big_request_body_also_capped():
    """请求体同治：超 20KB 的 json body → request['body'] 截断留痕。"""
    big_req = {"bulk": [{"k": i, "pad": "p" * 60} for i in range(500)]}
    rec = _run_call({"ok": True}, json_body=big_req)
    assert rec.verdict == "PASS"
    body = rec.steps[0].request["body"]
    assert isinstance(body, str) and len(body) <= _BODY_MAX_CHARS
    assert "已截断" in body


def test_run_json_size_reduction_for_big_list_response():
    """验收3：1000+ 行列表响应 → 落盘体积较全量行为显著下降（同一数据前后对比）。"""
    rows = [{"id": i, "empNo": f"9000{i:04d}", "score": 88.5, "level": "B"} for i in range(1200)]
    full_size = len(json.dumps(rows, ensure_ascii=False))          # 改动前 response_body 的体积
    rec = _run_call(rows)
    assert rec.verdict == "PASS"
    rb = rec.steps[0].response_body
    new_size = len(rb) if isinstance(rb, str) else len(json.dumps(rb, ensure_ascii=False))
    assert new_size <= _BODY_MAX_CHARS < full_size
    assert full_size / new_size > 3, \
        f"1200 行列表的全量 {full_size}B 截到 {new_size}B，应显著下降（>3 倍）"
