"""开发期按 sessionId 排查 Agent 会话（T-321）。

背景：开发 SpecGuard 时排障 Agent 对话问题——会话 jsonl（append-only，实时落盘）
里 system prompt 巨大、tool 调用与错误散布消息链，直接翻文件低效；让用户 export
又麻烦。本模块输出结构化排查视图：错误汇总优先 + 工具调用链 + 截断消息链。

用法：
  python -m agent.inspect <session_id> [--workspace tdm] [--json] [--full]

定位：agent/sessions/{emp}/{workspace}/{sid}.jsonl（兼容旧格式 {emp}/{sid}.jsonl）。
"""

import argparse
import json
import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent

_SESSIONS_ROOT = SG_ROOT / "agent" / "sessions"

# 错误形态标记（汇总用）
_ERROR_PREFIXES = ("[ERROR]", "工具执行异常", "错误：", "未知工具")


def find_session_file(sessions_root: Path, session_id: str, workspace: str = "") -> Path | None:
    """定位会话 jsonl：{emp}/{workspace}/{sid}.jsonl 优先，{emp}/{sid}.jsonl 兜底。"""
    from agent.session import _validate_session_id
    try:
        _validate_session_id(session_id)
    except ValueError:
        return None
    for emp_dir in sorted(sessions_root.iterdir()) if sessions_root.is_dir() else []:
        if not emp_dir.is_dir():
            continue
        candidates = []
        if workspace:
            candidates.append(emp_dir / workspace / f"{session_id}.jsonl")
        candidates.append(emp_dir / f"{session_id}.jsonl")
        for c in candidates:
            if c.is_file():
                return c
    return None


def _truncate(text: str, n: int) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= n:
        return text
    return text[:n] + f"…(共{len(text)}字符)"


def summarize_messages(messages: list[dict], truncate_chars: int = 300) -> dict:
    """消息链 → 排查视图（纯函数）：
    - system prompt 只显示长度（不刷屏）
    - 错误行（[ERROR]/工具执行异常/错误：/未知工具）标记 error 并汇总到 errors
    - tool_calls 提取为 tool_calls 清单
    """
    turns = []
    tool_calls = []
    errors = []
    for m in messages or []:
        role = m.get("role", "?")
        entry: dict = {"role": role}
        if role == "system":
            content = str(m.get("content", ""))
            if content.startswith("[ERROR]"):
                entry["content"] = _truncate(content, truncate_chars)
                entry["error"] = True
                errors.append(content)
            else:
                entry["kind"] = "prompt"
                entry["length"] = len(content)
        elif role == "user":
            entry["content"] = _truncate(m.get("content", ""), truncate_chars)
            refs = m.get("references")
            if refs:
                entry["references"] = refs
        elif role == "assistant":
            content = str(m.get("content", "") or "")
            entry["content"] = _truncate(content, truncate_chars)
            tcs = m.get("tool_calls") or []
            if tcs:
                entry["tool_calls"] = [
                    {"tool": tc.get("function", {}).get("name", ""),
                     "arguments": _truncate(tc.get("function", {}).get("arguments", ""), truncate_chars)}
                    for tc in tcs
                ]
                tool_calls.extend(entry["tool_calls"])
        elif role == "tool":
            content = str(m.get("content", "") or "")
            entry["content"] = _truncate(content, truncate_chars)
            entry["tool_call_id"] = m.get("tool_call_id", "")
            if content.startswith(_ERROR_PREFIXES):
                entry["error"] = True
                errors.append(content)
        turns.append(entry)
    return {"turns": turns, "tool_calls": tool_calls, "errors": errors,
            "message_count": len(turns)}


def load_session(sessions_root: Path, session_id: str, workspace: str = "") -> dict | None:
    """完整加载会话：meta + messages + metrics（无则 None）。"""
    path = find_session_file(sessions_root, session_id, workspace)
    if path is None:
        return None
    meta, messages, metrics = {}, [], None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = msg.get("_type")
            if t == "session_meta":
                meta = msg
            elif t in ("metrics", "todo_list", "compaction_summary"):
                continue
            else:
                messages.append(msg)
    # metrics：{sid}_metrics.jsonl 最后一行（LLM stats）
    metrics_path = path.with_name(path.stem + "_metrics.jsonl")
    if metrics_path.is_file():
        try:
            last = None
            with open(metrics_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        last = json.loads(line)
            metrics = last
        except Exception:
            pass
    return {"session_id": session_id, "meta": meta, "messages": messages,
            "metrics": metrics, "file": str(path)}


def _render(data: dict, full: bool = False) -> str:
    """人类可读排查视图：错误优先 + 消息链。"""
    meta = data["meta"]
    s = summarize_messages(data["messages"], truncate_chars=0 if full else 300)
    lines = []
    lines.append(f"══ session {data['session_id']} ══")
    lines.append(f"文件: {data['file']}")
    lines.append(f"emp={meta.get('emp_no', '')} | workspace={meta.get('workspace', '')} | "
                 f"created={meta.get('created_at', '')} | 消息 {s['message_count']} 条 | "
                 f"工具调用 {len(s['tool_calls'])} | 错误 {len(s['errors'])}")
    if data["metrics"]:
        m = data["metrics"]
        lines.append(f"metrics: calls={m.get('calls')} total_tokens={m.get('total_tokens')} "
                     f"errors={m.get('errors') or m.get('llm_errors') or 0}")
    if s["errors"]:
        lines.append("── 错误汇总 ──")
        for e in s["errors"]:
            lines.append(f"❌ {e[:400]}")
    lines.append("── 消息链 ──")
    for i, t in enumerate(s["turns"], 1):
        role = t["role"]
        if role == "system":
            if t.get("kind") == "prompt":
                lines.append(f"[{i}] system (prompt, {t['length']} 字符)")
            else:
                lines.append(f"[{i}] system ❌ {t['content']}")
        elif role == "user":
            lines.append(f"[{i}] user: {t['content']}")
        elif role == "assistant":
            tcs = t.get("tool_calls")
            extra = f" (调用: {', '.join(tc['tool'] for tc in tcs)})" if tcs else ""
            lines.append(f"[{i}] assistant: {t['content']}{extra}")
        elif role == "tool":
            flag = " ❌" if t.get("error") else ""
            lines.append(f"[{i}] tool{flag}: {t['content']}")
        else:
            lines.append(f"[{i}] {role}: {t.get('content', '')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="按 sessionId 排查 Agent 会话")
    parser.add_argument("session_id", help="会话 ID（agent/sessions 下目录名）")
    parser.add_argument("--workspace", default="", help="工作区（默认自动兼容新旧目录）")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--full", action="store_true", help="不截断消息内容")
    args = parser.parse_args(argv)

    data = load_session(_SESSIONS_ROOT, args.session_id, args.workspace)
    if data is None:
        print(f"会话不存在: {args.session_id}（agent/sessions/ 下未找到）", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(_render(data, full=args.full))
    return 0


if __name__ == "__main__":
    sys.exit(main())
