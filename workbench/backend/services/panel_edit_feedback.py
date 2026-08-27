"""panel_edit_feedback — 草稿面板人工编辑的对话感知（T-1027 F2）。

用户在草稿产物面板直接编辑 YAML 保存后，agent 对话必须能感知这次编辑并拿到
确定性校验结论。注入通道与 skill_hint 同款语义：role=system 行落会话 JSONL——
LLM 每轮加载历史可见，前端 groupMessages 跳过 system 不渲染（界面零噪声）。

run 进行中不能动会话 JSONL（runtime 持有内存消息、轮末全量覆写落盘，并发
append 会丢行）：改写 pending 文件（与会话同目录），WS chat 开跑前
drain_panel_edits 排空为 <panel_edits> 前缀块并入本轮 user 消息
（parent_block 同款先例，随该轮 user 消息持久化）。

本模块保持纯函数/纯文件操作（不感知 HTTP 与活跃 run 状态）——busy 判定由
drafts 路由传入（routers.agent._run_in_progress），便于离线测试。
"""

from __future__ import annotations

import contextlib
import difflib
import json
import re
from pathlib import Path

# pending 文件名后缀（与会话 {sid}.jsonl 同目录共存）
PENDING_SUFFIX = "_panel_edits.jsonl"

_NOTE_MAX = 1200    # 注入文本上限（防大 diff 刷爆上下文）
_FINDING_MAX = 3    # 校验 findings ERROR 摘录条数
_MSG_SAMPLE = 240   # 单条 finding message 截断长度

_TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):")


def _top_level_owners(lines: list[str]) -> list[str]:
    """每行归属的 YAML 顶层键（缩进为 0 的 `key:` 行）；文件头注释等无归属行挂 (head)。"""
    owners: list[str] = []
    cur = "(head)"
    for ln in lines:
        m = _TOP_KEY_RE.match(ln)
        if m:
            cur = m.group(1)
        owners.append(cur)
    return owners


def build_edit_note(filename: str, old_text: str, new_text: str,
                    validate_report: dict | None) -> str:
    """构造注入文本：变更摘要（±行数 + 涉及区块）+ 自动校验结论。

    给 LLM 的定位：「用户亲手改过这个文件」——Agent 后续评审/修复必须以磁盘
    最新内容为事实源，不能拿自己上一版记忆覆盖用户改动。
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    owners_old = _top_level_owners(old_lines)
    owners_new = _top_level_owners(new_lines)
    added = deleted = 0
    touched: set[str] = set()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted += i2 - i1
            touched.update(owners_old[i1:i2])
        if tag in ("replace", "insert"):
            added += j2 - j1
            touched.update(owners_new[j1:j2])
    sections = "、".join(sorted(t for t in touched if t != "(head)")) or "(head)"

    lines = [
        f"[面板编辑] 用户在草稿产物面板直接修改了 {filename}。",
        f"变更摘要：+{added}/-{deleted} 行，涉及区块：{sections}。"
        "后续处理请以该文件最新内容为准；需要细节可用 draft 工具 read 查看。",
    ]
    report = validate_report or {}
    verdict = str(report.get("verdict", ""))
    if verdict:
        summary = report.get("summary") or {}
        head = f"保存时自动格式校验：{verdict}"
        if summary:
            head += f" · error {summary.get('error', 0)} / warn {summary.get('warn', 0)}"
        lines.append(head)
        errs = [f for f in report.get("findings", [])
                if str(f.get("level", "")).upper() == "ERROR"][:_FINDING_MAX]
        for f in errs:
            lines.append(f"- [{f.get('rule', '')}] {str(f.get('message', ''))[:_MSG_SAMPLE]}")
        if errs:
            lines.append("校验存在 ERROR——用户编辑可能引入问题，请主动关注是否需要协助修复。")
    return "\n".join(lines)[:_NOTE_MAX]


def _pending_file(sessions_dir: str | Path, workspace: str, session_id: str) -> Path:
    # 目录布局与 SessionManager 一致：sessions_dir/{workspace}/{sid}.jsonl（workspace 空 → 直接根）
    base = Path(sessions_dir) / workspace if workspace else Path(sessions_dir)
    return base / f"{session_id}{PENDING_SUFFIX}"


def inject_edit_note(sessions_dir: str | Path, workspace: str,
                     session_id: str, note: str, busy: bool) -> dict:
    """注入一条面板编辑感知。返回 {'mode': appended|pending|session_not_found}。

    busy=False 且会话存在 → role=system 行直接 append 会话 JSONL；
    busy=True → 写 pending 文件，等 WS 开跑前 drain_panel_edits 排空。
    """
    from agent.session import SessionManager

    sm = SessionManager(Path(sessions_dir), workspace=workspace)
    if sm.load(session_id) is None:
        return {"mode": "session_not_found"}
    if busy:
        p = _pending_file(sessions_dir, workspace, session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"note": note}, ensure_ascii=False) + "\n")
        return {"mode": "pending"}
    sm.append(session_id, {"role": "system", "content": note})
    return {"mode": "appended"}


def drain_panel_edits(sessions_dir: str | Path, workspace: str, session_id: str) -> str:
    """排空 pending 编辑注记，返回 <panel_edits> 前缀块（无 pending 返回空串）。

    幂等：读后即删，同一批注记只会被并入一次。
    """
    p = _pending_file(sessions_dir, workspace, session_id)
    if not p.is_file():
        return ""
    notes: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            n = json.loads(line).get("note", "")
            if n:
                notes.append(n)
        except json.JSONDecodeError:
            continue
    with contextlib.suppress(OSError):
        p.unlink()
    body = "\n\n".join(notes)
    return f"<panel_edits>\n{body}\n</panel_edits>\n" if body else ""
