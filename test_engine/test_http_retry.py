"""ENG-T03 文件 bytes 化：ENG-BUG-004（fd 泄漏）/ ENG-BUG-011（401 重试空 body）。

全部离线：假 Session mock requests（模拟流式句柄被消费的行为），不触网。

设计依据：docs/架构升级/ENG-T03-HTTP重试与超时看门狗.md §6.4/§6.5。
"""

import os
import sys
from types import SimpleNamespace

SG_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SG_ROOT not in sys.path:
    sys.path.insert(0, SG_ROOT)

from engine.registry import Registry  # noqa: E402
from engine.scenario_loader import Scenario  # noqa: E402
from engine.scenario_runner import RunContext, register_builtin_steps, run_scenario  # noqa: E402


# ══════════════════════════════════════════════════════════
# mock 基建
# ══════════════════════════════════════════════════════════

class FakeSession:
    """假 requests.Session：按脚本吐响应。

    模拟 requests 消费文件流的行为：读取传入的 file 对象（流式句柄因此被耗尽，
    重发时为空——这正是 ENG-BUG-011 的机理）；bytes 则可无限次重复发送。
    """

    def __init__(self, script):
        self.script = list(script)      # 每项：int 状态码 / Exception 实例
        self.calls = []                 # [(method, url, kwargs)]
        self.sent_files = []            # 每次调用消费后的 files：{field: (name, bytes)}
        self.payload_kinds = []         # 每次调用 (files 字段 payload 类型名, data 类型名)

    def request(self, method, url, **kw):
        files = kw.get("files")
        kinds_files = None
        if files:
            consumed = {}
            for k, (name, payload) in files.items():
                kinds_files = type(payload).__name__
                consumed[k] = (name, payload.read() if hasattr(payload, "read") else payload)
            self.sent_files.append(consumed)
        self.payload_kinds.append((kinds_files, type(kw.get("data")).__name__))
        self.calls.append((method, url, kw))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        resp = SimpleNamespace(status_code=item, headers={}, text="")
        resp.json = lambda: {"ok": True} if item < 400 else {"err": item}
        return resp


def _make_rctx(client_getter):
    reg = Registry()
    register_builtin_steps(reg)
    rc = RunContext(registry=reg, env_config={}, token_provider=None,
                    graph=None, run_dir=".")
    rc.http_client = client_getter
    return rc


def _upload_scenario(sid, src, body_type="form"):
    if body_type == "form":
        call = {"method": "POST", "path": "/api/upload", "body_type": "form",
                "form": {"file": f"@{src}", "kind": "photo"}, "save": "up"}
    else:
        call = {"method": "PUT", "path": "/api/upload", "body_type": "binary",
                "file": str(src), "save": "up"}
    return Scenario(id=sid, title=sid, flow=[{"call": call}],
                    verify=[{"status": {"of": "up", "eq": 200}}])


# ══════════════════════════════════════════════════════════
# 1. step_call 传给 requests 的是 bytes 而非文件句柄（确定性断言）
# ════════════════════════════════════════════════════════

def test_form_and_binary_upload_send_bytes_not_streams(tmp_path):
    src = tmp_path / "a.bin"
    payload = bytes(range(256)) * 8
    src.write_bytes(payload)

    for body_type in ("form", "binary"):
        session = FakeSession([200])
        rctx = _make_rctx(lambda acc, service="tdm": SimpleNamespace(
            request=lambda method, path, **kw: session.request(method, path, **kw)))
        rec = run_scenario(_upload_scenario(f"T-{body_type}", src, body_type), rctx)
        assert rec.verdict == "PASS", f"{body_type} 上传应 PASS: {rec.failure}"
        kinds_files, kind_data = session.payload_kinds[0]
        if body_type == "form":
            assert kinds_files == "bytes", \
                f"form 文件字段应传 bytes（此前为流式句柄 {kinds_files}，不 close 且重试不安全）"
        else:
            assert kind_data == "bytes", \
                f"binary body 应传 bytes（此前为流式句柄 {kind_data}）"
        sent = session.sent_files[0] if body_type == "form" else None
        if sent:
            assert sent["file"] == (src.name, payload), "bytes 内容必须与源文件一致"


# ══════════════════════════════════════════════════════════
# 4. 401 刷新重试后文件字节完整（ENG-BUG-011，走真实 HttpClient）
# ══════════════════════════════════════════════════════════

def test_401_retry_upload_bytes_intact(tmp_path):
    """首次 401 → invalidate + 重发 → 200：两次发送的文件字节都与源文件一致。

    此前 step_call 传 open(fpath,"rb") 流式句柄：首次请求耗尽流，401 重试发空 body
    且无任何报错迹象。
    """
    from engine.http_client import HttpClient

    src = tmp_path / "b.bin"
    payload = os.urandom(2048)
    src.write_bytes(payload)

    client = HttpClient("http://fake", account="default", token_provider=None)
    client.token_provider = SimpleNamespace(
        get_token=lambda acc: "tok", invalidate=lambda acc: None)
    client.session = FakeSession([401, 200])
    rctx = _make_rctx(lambda acc, service="tdm": client)

    rec = run_scenario(_upload_scenario("T-401UP", src), rctx)
    assert rec.verdict == "PASS", f"401 刷新重试后应 200 PASS: {rec.failure}"
    assert len(client.session.sent_files) == 2, "401 应触发一次刷新重试"
    first, second = client.session.sent_files
    assert first["file"] == (src.name, payload)
    assert second["file"] == (src.name, payload), \
        "401 重试发出的文件字节必须与首次一致（流式句柄已耗尽则此处为 b''）——ENG-BUG-011"


# ══════════════════════════════════════════════════════════
# 5. 连续 100 次上传：payload 恒为 bytes；psutil 监测进程句柄不持续增长
# ══════════════════════════════════════════════════════════

def test_100_uploads_no_handle_growth(tmp_path):
    src = tmp_path / "c.bin"
    payload = os.urandom(4096)
    src.write_bytes(payload)
    session = FakeSession([200] * 100)
    rctx = _make_rctx(lambda acc, service="tdm": SimpleNamespace(
        request=lambda method, path, **kw: session.request(method, path, **kw)))
    sc = _upload_scenario("T-FD", src)

    import psutil
    before = psutil.Process().num_handles()
    for _ in range(100):
        rec = run_scenario(sc, rctx)
        assert rec.verdict == "PASS", f"上传应 PASS: {rec.failure}"
    growth = psutil.Process().num_handles() - before
    assert growth < 20, f"100 次上传后进程句柄增长 {growth}，疑似 fd 泄漏（ENG-BUG-004）"
    for kinds_files, _kind_data in session.payload_kinds:
        assert kinds_files == "bytes", "每次上传的文件 payload 必须是 bytes"
    for sent in session.sent_files:
        assert sent["file"] == (src.name, payload)
