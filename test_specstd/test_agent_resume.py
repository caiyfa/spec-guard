"""T-1021 会话运行中重连续传测试。

两层：
  - TestSessionEventBus：总线纯逻辑（fan-out/回放/生命周期/懒清理）
  - TestWsAttach：WS 端到端（attach 回放+实时续推+断连不打断保持；TestClient 双连接 + 桩 runtime）
    核心场景复现：发起连接断连（模拟刷新页面）→ run 继续后台执行 → 新连接 attach
    续上完整事件流（回放已发生事件 + 实时收到尾部与 done）。

全部离线：SG_AUTH_MODE=mock，桩 runtime 无 LLM 依赖。
"""

import asyncio
import importlib
import os
import time
from pathlib import Path

import pytest

SG_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = SG_ROOT / "workbench" / "backend"

# mock 认证必须在 services.auth 首次导入前生效
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_ADMIN_ACCOUNTS", None)

import services.auth as auth_mod  # noqa: E402
importlib.reload(auth_mod)

from services import user_store  # noqa: E402

import sys  # noqa: E402
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ══════════════════════════════════════════════════════════
# 总线纯逻辑
# ══════════════════════════════════════════════════════════

class TestSessionEventBus:

    def _bus(self):
        from services.session_event_bus import SessionEventBus
        return SessionEventBus()

    def test_fanout_two_subscribers(self):
        bus = self._bus()
        bus.run_started("s1", baseline_len=3)
        s1, replay1, meta1 = bus.attach("s1")
        s2, replay2, meta2 = bus.attach("s1")
        assert meta1["baseline_len"] == 3 and meta2["baseline_len"] == 3
        bus.publish("s1", {"type": "state", "turn": 0})
        bus.publish("s1", {"type": "assistant", "message": {"role": "assistant"}})
        assert s1.queue.qsize() == 2 and s2.queue.qsize() == 2
        assert replay1 == [] and replay2 == []  # attach 时无已缓冲事件
        assert bus.snapshot("s1")["seq"] == 2

    def test_attach_replays_buffered_events(self):
        bus = self._bus()
        bus.run_started("s1", baseline_len=0)
        bus.publish("s1", {"type": "state", "turn": 0})
        bus.publish("s1", {"type": "assistant_delta", "delta": "你"})
        sub, replay, meta = bus.attach("s1")
        assert [e["type"] for e in replay] == ["state", "assistant_delta"]
        assert meta["seq"] == 2 and meta["done"] is False
        # attach 之后的新事件进 queue（不重复回放）
        bus.publish("s1", {"type": "assistant_delta", "delta": "好"})
        assert sub.queue.qsize() == 1
        assert sub.queue.get_nowait()["delta"] == "好"

    def test_done_marks_channel_done(self):
        bus = self._bus()
        bus.run_started("s1", baseline_len=1)
        sub, _, _ = bus.attach("s1")
        bus.publish("s1", {"type": "done", "messages": []})
        assert bus.snapshot("s1")["done"] is True
        assert sub.queue.get_nowait()["type"] == "done"  # 订阅者收到结束信号

    def test_detach_stops_delivery(self):
        bus = self._bus()
        bus.run_started("s1", baseline_len=0)
        sub, _, _ = bus.attach("s1")
        bus.detach("s1", sub)
        bus.publish("s1", {"type": "state", "turn": 0})
        assert sub.queue.qsize() == 0  # 已退订不再收

    def test_publish_unknown_sid_ignored(self):
        bus = self._bus()
        bus.publish("nope", {"type": "state"})  # 不炸、不建频道
        assert bus.snapshot("nope")["exists"] is False

    def test_attach_unknown_sid_returns_none(self):
        bus = self._bus()
        assert bus.attach("nope") is None
        assert bus.attach_live("nope") is None

    def test_run_started_resets_channel(self):
        bus = self._bus()
        bus.run_started("s1", baseline_len=0)
        bus.publish("s1", {"type": "state", "turn": 0})
        bus.publish("s1", {"type": "done"})
        # 新 run 重置：缓冲清空、基线更新、seq 归零
        bus.run_started("s1", baseline_len=5)
        sub, replay, meta = bus.attach("s1")
        assert replay == []
        assert meta["baseline_len"] == 5 and meta["seq"] == 0 and meta["done"] is False

    def test_gc_removes_stale_channels(self):
        from services import session_event_bus as seb_mod
        bus = self._bus()
        bus.run_started("s1", baseline_len=0)
        bus.publish("s1", {"type": "done"})
        # 手动把 done_at 拨回过去（懒清理在 run_started/attach 时触发）
        ch = bus._channels["s1"]
        ch.done_at = time.monotonic() - (seb_mod.IDLE_TTL_SECONDS + 1)
        bus.run_started("s2", baseline_len=0)  # 触发 _gc
        assert "s1" not in bus._channels
        assert "s2" in bus._channels

    def test_buffer_truncation_keeps_tail(self):
        from services import session_event_bus as seb_mod
        bus = self._bus()
        # 缩小缓冲上限验证截断语义（50000 太大跑不动）
        bus.run_started("s1", baseline_len=0)
        ch = bus._channels["s1"]
        ch.buffer = __import__("collections").deque(maxlen=3)
        for i in range(5):
            bus.publish("s1", {"type": "state", "turn": i})
        sub, replay, _ = bus.attach("s1")
        assert [e["turn"] for e in replay] == [2, 3, 4]  # 头部被截，尾部保留
        assert ch.seq == 5  # seq 不回退（单调递增语义）


# ══════════════════════════════════════════════════════════
# WS 端到端（TestClient + 桩 runtime）
# ══════════════════════════════════════════════════════════

class StubRuntime:
    """可控节奏的 runtime 桩：发 2 个事件 → sleep（attach 窗口）→ 尾部事件 + 落盘返回。

    线程模型与真实 AgentRuntime 一致：run 跑在 to_thread 线程，
    事件经 agent.py 的 subscribe 回调（call_soon_threadsafe）进总线。
    """

    def __init__(self, *args, **kwargs):
        from agent.events import EventBus
        self.events = EventBus()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def run(self, system_prompt, user_message, sm, sid, refs=None):
        self.events.emit("state", turn=0, max_turns=2)
        self.events.emit("assistant_delta", delta="你", turn=0)
        time.sleep(1.2)  # attach 窗口：发起连接已断连，run 后台继续
        self.events.emit("assistant_delta", delta="好", turn=0)
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": "你好"},
        ]
        sm.save(sid, msgs)
        self.events.emit("assistant", message={"role": "assistant", "content": "你好"},
                         turn=1, usage={"total_tokens": 3})
        return msgs


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import specstd.workspace as wsm
    monkeypatch.setattr(wsm, "REGISTRY_PATH", tmp_path / "registry.yaml")
    monkeypatch.setattr(wsm, "CLONES_DIR", tmp_path / "_clones")
    from routers import agent as agent_router
    monkeypatch.setattr(agent_router, "SESSIONS_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(agent_router, "AgentRuntime", StubRuntime)
    # 总线状态隔离（模块级单例：频道跨测试残留）
    from services.session_event_bus import SessionEventBus
    monkeypatch.setattr(agent_router, "_BUS", SessionEventBus())

    from test_specstd.helpers import create_valid_workspace
    repo = create_valid_workspace(tmp_path / "repo")
    wsm.register_local("tdm", str(repo), "tdm", activate=True)

    from main import app
    from fastapi.testclient import TestClient
    db_file = tmp_path / "workbench.db"
    monkeypatch.setattr(user_store, "DB_PATH", db_file)
    user_store.init_db(db_file)
    auth_mod._TOKEN_CACHE.clear()
    with TestClient(app) as c:
        yield c


def _login(client, emp_no, name=""):
    r = client.post("/api/auth/mock-login", json={"emp_no": emp_no, "name": name})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _ws_url(token, workspace="tdm"):
    return f"/api/agent/ws?token={token}&workspace={workspace}"


def _ws_connect(client, token, workspace="tdm"):
    """每次连接强制独立 portal（client.portal=None 使 _portal_factory 新建）。

    starlette 1.0 TestClient 在 __enter__ 后会复用 lifespan portal（所有 WS
    连接挤同一 loop），而本套测试的总线跨 loop 投递防护与 attach 时序按
    「每连接独立 portal loop」设计；复用单 loop 时嵌套连接的 handler 协程
    调度与真实双标签页拓扑不一致，且实测会间歇性挂死（ws_b 收不到 attached）。
    """
    client.portal = None
    return client.websocket_connect(_ws_url(token, workspace))


class TestWsAttach:

    def test_attach_resumes_stream_after_disconnect(self, client):
        """核心场景：发起连接断连（刷新页面）→ run 后台继续 → 新连接 attach 续上完整流。"""
        h = _login(client, "90000001")
        token = h["Authorization"].split(" ", 1)[1]
        sid = ""
        # 连接 A：发起 run，推送到首个 delta 后断连（模拟刷新页面）。
        # 注意：不能用 with 退出模拟断连——TestClient 退出会取消后端 handler 协程
        # （与真实断连不同），改用 close() 只关连接：后端 send 失败转入 ws_broken，
        # run 继续后台执行（断连不打断），与生产语义一致。
        with _ws_connect(client, token) as ws_a:
            ws_a.send_json({"message": "你好", "purpose": "test_workbench",
                            "session_id": "", "max_turns": 2})
            msg = ws_a.receive_json()
            assert msg["type"] == "state" and msg.get("status") == "started"
            sid = msg["session_id"]
            # 等到首个 delta（证明 run_task 已启动并进入事件推送循环）
            while True:
                ev = ws_a.receive_json()
                if ev["type"] == "assistant_delta":
                    break
                assert ev["type"] != "error", ev
            ws_a.close(1000)  # 断连；run 不取消（detach 语义），后台继续执行

            # run 进行中断言 REST 状态
            r = client.get(f"/api/agent/sessions/{sid}", headers=h)
            assert r.status_code == 200
            body = r.json()
            assert body["run_in_progress"] is True
            assert body["run_baseline_len"] == 0  # 新会话基线

            # 连接 B：attach 续上——回放已发生事件 + 实时收到尾部与 done
            with _ws_connect(client, token) as ws_b:
                ws_b.send_json({"type": "attach", "session_id": sid})
                got = [ws_b.receive_json()]
                assert got[0]["type"] == "attached"
                assert got[0]["run_in_progress"] is True
                assert got[0]["baseline_len"] == 0
                events = []
                while True:
                    ev = ws_b.receive_json()
                    if ev["type"] == "replay_batch":
                        events.extend(ev["events"])
                    elif ev["type"] in ("done", "error"):
                        events.append(ev)
                        break
                    else:
                        events.append(ev)
                types = [e["type"] for e in events]
                # 回放：state + delta"你"；实时：delta"好" + assistant；结束：done
                assert "state" in types and "assistant_delta" in types
                deltas = [e.get("delta") for e in events if e["type"] == "assistant_delta"]
                assert deltas == ["你", "好"]
                assert "assistant" in types
                done = [e for e in events if e["type"] == "done"][0]
                assert done["session_id"] == sid
                assert len(done["messages"]) == 3
        # run 结束后 REST 状态翻转为不在进行
        r = client.get(f"/api/agent/sessions/{sid}", headers=h)
        assert r.json()["run_in_progress"] is False

    def test_attach_without_run(self, client):
        """无活跃 run 时 attach：回 run_in_progress=False（前端据此解除 loading 并对齐）。"""
        h = _login(client, "90000001")
        token = h["Authorization"].split(" ", 1)[1]
        r = client.post("/api/agent/sessions", headers=h,
                        json={"purpose": "test_workbench", "workspace": "tdm"})
        sid = r.json()["session_id"]
        with _ws_connect(client, token) as ws:
            ws.send_json({"type": "attach", "session_id": sid})
            msg = ws.receive_json()
            assert msg["type"] == "attached" and msg["run_in_progress"] is False
            # attach 后连接回主循环：正常消息不受影响（游离 detach 也不炸）
            ws.send_json({"type": "detach"})
            ws.send_json({"type": "ping"})
            assert ws.receive_json() == {"type": "pong"}

    def test_attach_other_user_denied(self, client):
        """归属校验：非 admin 不能 attach 他人会话。"""
        h_a = _login(client, "90000001")
        r = client.post("/api/agent/sessions", headers=h_a,
                        json={"purpose": "test_workbench", "workspace": "tdm"})
        sid = r.json()["session_id"]
        # 90000002 授权 tdm 工作区（否则连接级 4403 先拒，测不到 attach 归属校验）
        user_store.grant_workspace("tdm", "90000002", "90000001")
        h_b = _login(client, "90000002")
        token_b = h_b["Authorization"].split(" ", 1)[1]
        with _ws_connect(client, token_b) as ws:
            ws.send_json({"type": "attach", "session_id": sid})
            msg = ws.receive_json()
            assert msg["type"] == "error" and "无权" in msg["message"]

    def test_attach_invalid_sid(self, client):
        h = _login(client, "90000001")
        token = h["Authorization"].split(" ", 1)[1]
        with _ws_connect(client, token) as ws:
            ws.send_json({"type": "attach", "session_id": "../evil"})
            msg = ws.receive_json()
            assert msg["type"] == "error"

    def test_second_tab_attaches_while_origin_connected(self, client):
        """第二标签页：发起连接在线时另一连接 attach 同样续上（fan-out）。"""
        h = _login(client, "90000001")
        token = h["Authorization"].split(" ", 1)[1]
        with _ws_connect(client, token) as ws_a:
            ws_a.send_json({"message": "你好", "purpose": "test_workbench",
                            "session_id": "", "max_turns": 2})
            started = ws_a.receive_json()
            sid = started["session_id"]
            # 确定性等待：收到 runtime 首个 delta 才证明 run 已登记并启动
            # （started 消息早于 _ACTIVE_RUNS 登记，盲等 sleep 会在慢机器上
            # 赌进登记窗口——attach 返回 run_in_progress=False 属正确语义）
            while True:
                ev = ws_a.receive_json()
                if ev["type"] == "assistant_delta":
                    break
                assert ev["type"] != "error", ev
            with _ws_connect(client, token) as ws_b:
                ws_b.send_json({"type": "attach", "session_id": sid})
                attached = ws_b.receive_json()
                assert attached["run_in_progress"] is True
                # B 收完整流（回放+实时+done）
                types = []
                while True:
                    ev = ws_b.receive_json()
                    if ev["type"] == "replay_batch":
                        types.extend(e["type"] for e in ev["events"])
                    else:
                        types.append(ev["type"])
                    if ev["type"] in ("done", "error"):
                        break
                assert "done" in types and "assistant" in types
            # A 也收到 done（run_task 完成后直发）
            a_types = []
            while True:
                ev = ws_a.receive_json()
                a_types.append(ev["type"])
                if ev["type"] in ("done", "error"):
                    break
            assert "done" in a_types

    def test_origin_error_broadcasts_to_attached(self, client):
        """run 异常时 error 广播到总线：attach 连接收到 error 并退出订阅循环。"""
        class ExplodingRuntime(StubRuntime):
            def run(self, system_prompt, user_message, sm, sid, refs=None):
                self.events.emit("state", turn=0, max_turns=2)
                time.sleep(1.2)  # attach 窗口放宽：确定性等待后仍需足够窗口完成 attach 握手
                raise RuntimeError("boom")

        from routers import agent as agent_router
        original = agent_router.AgentRuntime
        agent_router.AgentRuntime = ExplodingRuntime
        try:
            h = _login(client, "90000001")
            token = h["Authorization"].split(" ", 1)[1]
            with _ws_connect(client, token) as ws_a:
                ws_a.send_json({"message": "x", "purpose": "test_workbench"})
                sid = ws_a.receive_json()["session_id"]
                # 确定性等待：runtime state（带 turn）到达 = run 已登记启动，
                # 再 attach 必然 run_in_progress=True（原盲等 0.3s 在慢机器上
                # 会落进 started→登记窗口，attach 返回 False 属正确语义但断言假失败）
                while True:
                    ev = ws_a.receive_json()
                    if ev.get("type") == "state" and "turn" in ev:
                        break
                    assert ev["type"] != "error", ev
                with _ws_connect(client, token) as ws_b:
                    ws_b.send_json({"type": "attach", "session_id": sid})
                    attached = ws_b.receive_json()
                    assert attached["run_in_progress"] is True
                    while True:
                        ev = ws_b.receive_json()
                        if ev["type"] in ("error", "done"):
                            assert ev["type"] == "error"
                            break
        finally:
            agent_router.AgentRuntime = original
