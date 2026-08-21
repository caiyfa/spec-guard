"""agent.cli — POC 独立验证入口。

用法：
    python -m agent.cli "生成 PP-RC-008 场景"
    python -m agent.cli --mock "测试 mock 模式"
    python -m agent.cli --session 20260726_120000_abc12345 "继续生成"
"""

import argparse
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

from agent.llm_client import LLMClient
from agent.session import SessionManager
from agent.runtime import AgentRuntime, build_system_prompt


def main():
    parser = argparse.ArgumentParser(description="SpecGuard Agent CLI — 场景生成 POC")
    parser.add_argument("message", nargs="?", default="", help="用户消息（如 '生成 PP-RC-008 场景'）")
    parser.add_argument("--session", help="恢复指定会话 ID")
    parser.add_argument("--max-turns", type=int, default=12, help="最大轮次（默认 12）")
    parser.add_argument("--mock", action="store_true", help="强制 mock 模式（不调用 LLM）")
    parser.add_argument("--verbose", action="store_true", help="输出详细事件流")
    args = parser.parse_args()

    # 初始化 LLM 客户端
    llm = LLMClient(base_url="" if args.mock else "")

    # 初始化 session
    sessions_dir = Path(__file__).parent / "sessions"
    session = SessionManager(sessions_dir)
    session_id = args.session or session.create()
    llm.set_metrics_file(sessions_dir / f"{session_id}_metrics.jsonl")

    # 构建 system prompt
    system_prompt = build_system_prompt()

    # 运行 agent
    runtime = AgentRuntime(llm, max_turns=args.max_turns)

    # 事件订阅
    if args.verbose:
        def on_event(event):
            etype = event.get("type", "")
            if etype == "assistant":
                msg = event.get("message", {})
                content = msg.get("content", "")
                if content:
                    print(f"\n[Assistant] {content[:300]}")
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        print(f"  [Tool Call] {fn.get('name', '')}({fn.get('arguments', '')[:100]})")
            elif etype == "tool_call":
                print(f"  [Tool Result] {event.get('result', '')[:200]}")
            elif etype == "state":
                if event.get("fused"):
                    print(f"\n[FUSE] max_turns={event.get('max_turns')} 熔断")
                elif event.get("resumed"):
                    print(f"[Resumed] session={event.get('session_id')}")
        runtime.events.subscribe(on_event)

    # 执行
    user_message = args.message or "请生成一个测试场景"
    messages = runtime.run(system_prompt, user_message, session=session, session_id=session_id)

    # 输出最终回复
    last = messages[-1]
    if last.get("role") == "assistant" and last.get("content"):
        print(f"\n{'=' * 60}")
        print(last["content"])

    # 输出统计
    stats = llm.get_stats()
    print(f"\n{'=' * 60}")
    print(f"会话 ID: {session_id}")
    print(f"消息数: {len(messages)}")
    print(f"Tokens: {stats['total_tokens']}")
    print(f"模式: {'MOCK' if stats['is_mock'] else 'LIVE'} ({stats['model']})")
    print(f"缓存: hit={stats['cache_hits']}, miss={stats['cache_misses']}")


if __name__ == "__main__":
    main()
