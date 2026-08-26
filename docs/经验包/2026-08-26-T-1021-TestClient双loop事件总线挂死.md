# 2026-08-26 T-1021 · TestClient 双 portal loop 下事件总线跨 loop 投递挂死

## 现象

T-1021（会话运行中重连续传）施工中，`test_agent_resume.py` 单文件全绿（15/15），
但与 `test_acceptance_fixes.py` 组合跑时 pytest **整体挂死**（600s 无输出超时）。
挂死测试固定为 `test_origin_error_broadcasts_to_attached`（run 异常 → error 广播路径），
单独跑该组合二分钉案。全量 test_specstd 曾连带出现 2 个无关测试失败（污染传播）。

## 证据链

- 逐步打印复现脚本（`.repro/repro.py` 形态，已清理）：连接 A 发起 run（桩 0.5s 后抛
  RuntimeError）→ 连接 B attach → B 收到 `attached` + `replay_batch` 后**再无事件**，
  10s 后仅收到 heartbeat；脚本卡在 B 的 `while receive_json()` 等待。
- **决定性证据**（独立线程轮询总线状态）：`poll 0: seq=1, done=False` →
  `poll 1: seq=2, done=True`——error 事件**已发布进频道缓冲**（seq=2、done 标记生效），
  但 B 的订阅队列**从未收到**该事件。
- starlette TestClient 源码：每个 `websocket_connect` 会话创建**独立 portal（独立
  event loop 线程）**——A 的 handler 与 B 的 handler 不在同一 loop（生产 uvicorn
  workers=1 单 loop，无此形态）。

## 根因

**哪个环节缺失：会话事件总线的 fan-out 假设了「所有订阅者在同一 event loop」。**

`asyncio.Queue.put_nowait` 从 A 的 loop 线程投递到 B 的 loop 上的订阅者队列时，
内部 `future.set_result`（唤醒 getter）是跨线程裸调用：撞上 B 的
`wait_for(queue.get(), 0.2)` 超时取消 future 的瞬间抛 `InvalidStateError` →
fan-out 循环中断 → **事件只进缓冲不进订阅队列**（put_nowait 先唤醒后入队，异常时
入队未执行）。B 的 attach 循环随后走「run_in_progress=False 且 queue 空」兜底退出，
但 B 客户端仍在等待终态事件 → 测试挂死。挂死的 A/B 连接 portal 清理异常又污染了
后续测试（全量跑时 2 个无关测试连带失败）。

## 修复（T-1021 树内，commit 见总控 §4/T-1021 行）

1. `session_event_bus.Subscriber` 记录创建时的 event loop；`publish` fan-out 时
   检测订阅者 loop ≠ 当前 loop → 改经 `sub.loop.call_soon_threadsafe(queue.put_nowait)`
   投递（线程安全唤醒）；单订阅者投递异常 per-sub try 不中断 fan-out。
2. `agent.py` attach 循环兜底分支（run 已结束但终态事件丢失）从「静默 break」改为
   **合成 `attached(run_in_progress=false)` 事件**发给该连接——前端已有该事件的
   处理分支（解除 loading + 全量 getSession 对齐），终态永不悬空。
3. 测试侧钉案回归：`test_origin_error_broadcasts_to_attached` 保留双连接组合形态
   （挂死修复后 49/49 组合绿、全量 1926 绿）。

## 预防（可执行检查清单）

- [ ] 任何「发布者投递 asyncio.Queue 给多个订阅者」的组件：**订阅者与发布者可能不在
      同一 event loop 时**（TestClient 每 WS 连接独立 portal、多 worker、线程池回调），
      必须按 loop 路由：同 loop 直接 `put_nowait`，跨 loop 用 `call_soon_threadsafe`。
- [ ] WS 测试模拟「断连」不要用 `with websocket_connect` 退出——TestClient 退出会
      **取消后端 handler 协程**（真实断连不取消）；用 `session.close(1000)` 只关连接，
      后端 send 失败自然转入 detach 语义（本文件同批踩坑，测试注释已钉案）。
- [ ] 事件总线类组件必须给订阅者队列投递加 per-subscriber 异常隔离——一个订阅者
      的队列异常中断整个 fan-out 是静默丢事件的温床。
- [ ] 排查「事件发布成功但订阅者没收到」：先用旁路观测器（独立线程轮询总线
      `snapshot()`）把「已发布」与「已送达」分离钉案，再查投递路径。
