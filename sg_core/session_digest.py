"""会话脉络摘要（T-1032）：主会话消息链 → 紧凑转录 → LLM 摘要 / 骨架兜底。

方案②+③合并的核心纯函数层：sg_core 下沉（agent/mcp_server 双方可复用，
依赖方向 sg_core→无，不 import 任何上层包）。

产物协议：
- 摘要文件   `{sid}_digest.md`     —— 面向 LLM/用户的 markdown 脉络摘要
- 覆盖度文件 `{sid}_digest.json`  —— {covered_len, covered_sha, updated_at, mode, turns}
  covered_* = 已摘要覆盖的消息条数与首行 meta+全部内容的 sha256-12，
  用于确定性判 staleness（消息数或内容指纹变化即视为过期）。

纪律：
- 本模块零 I/O 副作用之外的假设——路径由调用方给，读写字符串进出；
- LLM 失败/未配置时诚实降级「骨架摘要」并在正文标注 mode=skeleton，
  绝不把截断原文冒充 LLM 摘要；
- 注入块（<references>/<parent_context>/<viewing_context>/<knowledge_refs>/
  [parent_context] 行）一律剥除后再入转录——它们是通道载荷不是对话内容。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

# ── 转录预算（chars；粗算 token 的 1/4）──
TRANSCRIPT_MAX_CHARS = 20_000      # 进入 LLM 的转录上限
USER_MSG_KEEP = 600                # 每条用户消息保留
ASSISTANT_MSG_KEEP = 500           # 每条助手回复保留
TOOL_RESULT_KEEP = 160             # 工具结果摘要保留
RECENT_WINDOW_MESSAGES = 14        # parent(recent) 最近轮窗条数
RECENT_WINDOW_CHARS = 12_000       # parent(recent) 窗口总预算

_INJECTED_BLOCK_RE = re.compile(
    r"<references>[\s\S]*?</references>|"
    r"<parent_context>[\s\S]*?</parent_context>|"
    r"<viewing_context>[\s\S]*?</viewing_context>|"
    r"<knowledge_refs>[\s\S]*?</knowledge_refs>|"
    r"\[parent_context\][^\n]*(?:\n|$)")


def strip_injected_blocks(text: str) -> str:
    """剥离后端注入块（后端侧口径；前端展示另有 utils.stripRefBlock 同语义）。"""
    return _INJECTED_BLOCK_RE.sub("", text or "")


def _shorten(text: str, keep: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= keep else t[:keep] + "…"


def _tool_call_line(tc: dict) -> str:
    fn = tc.get("function", {}) or {}
    name = fn.get("name", "?")
    try:
        args = json.loads(fn.get("arguments") or "{}")
        keys = ["filename", "path", "target", "scenario_id", "action", "sql", "query"]
        hints = ", ".join(f"{k}={args[k]}" for k in keys
                          if isinstance(args.get(k), str) and args[k])
    except (json.JSONDecodeError, TypeError):
        hints = ""
    return f"→ 调用 {name}({hints})" if hints else f"→ 调用 {name}"


def render_transcript(msgs: list[dict]) -> str:
    """消息链 → 紧凑转录（系统层/注入块剔除；超预算时保尾部——近期上下文更相关）。"""
    lines: list[str] = []
    for m in msgs:
        role = m.get("role")
        if role == "system":
            continue
        if role == "user":
            body = _shorten(strip_injected_blocks(m.get("content") or ""), USER_MSG_KEEP)
            if body.strip():
                lines.append(f"[用户] {body}")
        elif role == "assistant":
            body = _shorten(strip_injected_blocks(m.get("content") or ""), ASSISTANT_MSG_KEEP)
            if body.strip():
                lines.append(f"[助手] {body}")
            for tc in (m.get("tool_calls") or []):
                lines.append("  " + _tool_call_line(tc))
        elif role == "tool":
            body = _shorten(m.get("content") or "", TOOL_RESULT_KEEP)
            if body.strip():
                lines.append(f"  （结果）{body}")
    transcript = "\n".join(lines)
    if len(transcript) > TRANSCRIPT_MAX_CHARS:
        transcript = "…（早期内容略）\n" + transcript[-TRANSCRIPT_MAX_CHARS:]
    return transcript


DIGEST_SYSTEM_PROMPT = (
    "你是 SpecGuard 会话分析器。把主测试工作会话的记录提炼成给另一个 AI 助手看的脉络摘要。"
    "输出 markdown 要点（300-600 字），固定包含以下小节：\n"
    "## 当前主题\n一句话说明正在做什么。\n"
    "## 关键里程碑\n按时间列已完成事项（含场景 ID / FR 锚点 / 试跑结论等具体标识）。\n"
    "## 产物清单\n已落盘草稿、报告等文件名列表。\n"
    "## 进行中与下一步\n当前卡点与预期动作。\n"
    "只依据记录本身，不要推测记录外的事实。")


def skeleton_digest(parent_sid: str, msgs: list[dict]) -> str:
    """LLM 不可用时的确定性兜底摘要（诚实标注 mode=skeleton）。"""
    user_heads = [_shorten(strip_injected_blocks(m.get("content") or ""), 80)
                  for m in msgs if m.get("role") == "user"]
    drafts, focus = _collect_markers(msgs)
    lines = [
        "# 主会话脉络摘要（骨架模式）",
        "",
        "> LLM 摘要暂不可用，以下为确定性要点提取；工具能力恢复后会自动替换为完整摘要。",
        "",
        f"- 来源会话：{parent_sid}（共 {len(msgs)} 条消息）",
    ]
    if user_heads:
        lines.append("- 用户提出过的请求：")
        lines += [f"  - {h}" for h in user_heads[-6:]]
    if drafts:
        lines.append(f"- 涉及草稿：{'、'.join(drafts[-5:])}")
    if focus:
        lines.append(f"- 近期聚焦场景：{'、'.join(focus[-3:])}")
    return "\n".join(lines)


def _collect_markers(msgs: list[dict]) -> tuple[list[str], list[str]]:
    """从消息链提取（草稿名清单， 聚焦场景清单）——与快照注入同口径的轻量版。"""
    drafts: list[str] = []
    focus: list[str] = []
    focus_tools = {"scenario.run", "run_scenario", "validate", "scenario.edit"}
    focus_keys = ("target", "scenario_id", "scenario")
    for m in msgs:
        if m.get("role") != "assistant":
            continue
        for tc in (m.get("tool_calls") or []):
            try:
                args = json.loads((tc.get("function") or {}).get("arguments") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            fname = (tc.get("function") or {}).get("name", "")
            if (fname == "write_draft" or (fname == "draft" and args.get("action") == "write")) \
                    and args.get("filename"):
                drafts.append(str(args["filename"]))
            if fname in focus_tools:
                v = next((str(args[k]) for k in focus_keys
                          if isinstance(args.get(k), str) and args.get(k)), "")
                if v:
                    focus.append(v)
    seen: set[str] = set()
    drafts = [d for d in drafts if not (d in seen or seen.add(d))]
    seen2: set[str] = set()
    focus = [f for f in focus if not (f in seen2 or seen2.add(f))]
    return drafts, focus


def render_recent_window(msgs: list[dict],
                         max_messages: int = RECENT_WINDOW_MESSAGES,
                         max_chars: int = RECENT_WINDOW_CHARS) -> str:
    """最近轮窗渲染（parent 工具 action=recent）：保最新优先，输出保持时间顺序。"""
    presentable = [m for m in msgs if m.get("role") in ("user", "assistant", "tool")]
    picked: list[dict] = []
    budget = max_chars
    for m in reversed(presentable):
        if len(picked) >= max_messages or budget <= 200:
            break
        keep = {"user": USER_MSG_KEEP, "assistant": ASSISTANT_MSG_KEEP,
                "tool": TOOL_RESULT_KEEP}[m["role"]]
        text = strip_injected_blocks(m.get("content") or "")
        cost = min(len(text), keep)
        if cost > budget:
            continue
        picked.append(m)
        budget -= cost
    picked.reverse()
    lines: list[str] = []
    for m in picked:
        role_label = {"user": "[用户]", "assistant": "[助手]", "tool": "[工具结果]"}[m["role"]]
        keep = {"user": USER_MSG_KEEP, "assistant": ASSISTANT_MSG_KEEP,
                "tool": TOOL_RESULT_KEEP}[m["role"]]
        body = _shorten(strip_injected_blocks(m.get("content") or ""), keep)
        if body.strip():
            lines.append(f"{role_label} {body}")
        for tc in (m.get("tool_calls") or []):
            lines.append("  " + _tool_call_line(tc))
    return "\n".join(lines) or "（窗口内无可呈现内容）"


# ── 覆盖度跟踪 ──

def messages_fingerprint(msgs: list[dict]) -> str:
    raw = json.dumps([{ "role": m.get("role"), "content": m.get("content"),
                        "tc": len(m.get("tool_calls") or []) } for m in msgs],
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def build_coverage(msgs: list[dict], mode: str) -> dict:
    return {
        "covered_len": len(msgs),
        "covered_sha": messages_fingerprint(msgs),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "turns": sum(1 for m in msgs if m.get("role") == "assistant"),
    }


def parse_coverage(meta_text: str | None) -> dict | None:
    try:
        d = json.loads(meta_text or "")
        if isinstance(d, dict) and "covered_sha" in d:
            return d
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def is_stale(msgs: list[dict], coverage: dict | None) -> bool:
    if coverage is None:
        return True
    return (coverage.get("covered_len") != len(msgs)
            or coverage.get("covered_sha") != messages_fingerprint(msgs))


def digest_staleness_note(coverage: dict | None, current_len: int) -> str:
    """read_parent(summary) 返回头部的新鲜度提示行。"""
    if coverage is None:
        return "- 新鲜度：摘要缺失。可用 action=recent 直读父会话最近轮窗。"
    behind = current_len - int(coverage.get("covered_len", current_len))
    if behind <= 0:
        return f"- 新鲜度：覆盖全部 {current_len} 条消息（{coverage.get('mode')} 模式，{coverage.get('updated_at')}）。"
    return (f"- 新鲜度：覆盖截至第 {coverage.get('covered_len')} 条"
            f"（{coverage.get('mode')} 模式，{coverage.get('updated_at')}），此后新增 {behind} 条——"
            f"最新进展请配合 action=recent 查看。")


# ── 落盘编排（T-1032 方案②）──

def paths_for(sessions_dir, sid: str) -> tuple[Path, Path]:
    """会话摘要文件对路径：(md 正文, 覆盖度 json)。与会话 JSONL 同目录。"""
    base = Path(sessions_dir)
    return base / f"{sid}_digest.md", base / f"{sid}_digest.json"


def _atomic_write(path: Path, text: str):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def refresh_digest(sessions_dir, sid: str, msgs: list[dict],
                   llm_call=None, force: bool = False) -> dict:
    """刷新主会话脉络摘要（方案②核心）。调用方负责放到后台线程。

    - 内容未变（条数+指纹均同）且非 force → 跳过（幂等，防重复烧 token）
    - 有效内容不足（<2 条消息或转录 <200 字符）→ 清理旧产物
    - llm_call(system, user) -> str 可选；缺省/抛错/空回包一律降级骨架摘要，
      诚实标注 mode=skeleton——绝不把原文截断冒充 LLM 摘要。
    返回执行报告 {action: written|skipped|removed|failed, mode?, error?}。
    """
    md_path, meta_path = paths_for(sessions_dir, sid)

    coverage = parse_coverage(meta_path.read_text(encoding="utf-8")
                              if meta_path.is_file() else None)
    if not is_stale(msgs, coverage) and not force and md_path.is_file():
        return {"action": "skipped", "mode": (coverage or {}).get("mode", ""),
                "covered_len": (coverage or {}).get("covered_len")}

    valid = sum(1 for m in msgs if m.get("role") in ("user", "assistant"))
    if len(msgs) < 2 or not render_transcript(msgs).strip() or valid < 1:
        for p in (md_path, meta_path):
            if p.exists():
                p.unlink()
        return {"action": "removed"}

    transcript = render_transcript(msgs)
    mode = "skeleton"
    body = ""
    if llm_call is not None and len(transcript) >= 200:
        try:
            out = llm_call(DIGEST_SYSTEM_PROMPT,
                           f"以下是主测试工作会话的记录转录：\n\n{transcript}")
            out = re.sub(r"^```(?:markdown)?\n|\n```$", "", (out or "").strip())
            if out.strip():
                body = out.strip()
                mode = "llm"
        except Exception as e:  # LLM 失败不阻塞会话——骨架兜底照常落盘
            body_note = f"<!-- llm_error: {e} -->\n"
        else:
            body_note = ""
    else:
        body_note = ""
    if mode == "skeleton":
        body = skeleton_digest(sid, msgs)

    coverage_new = build_coverage(msgs, mode)
    md_text = (
        f"<!-- digest of session {sid} | mode={mode} | "
        f"updated_at={coverage_new['updated_at']} -->\n"
        f"{body_note}{body}\n")
    try:
        _atomic_write(md_path, md_text)
        _atomic_write(meta_path, json.dumps(coverage_new, ensure_ascii=False))
        return {"action": "written", **coverage_new}
    except OSError as e:
        return {"action": "failed", "error": str(e)}
