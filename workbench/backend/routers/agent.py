"""Agent 对话 API：WebSocket 实时对话 + 会话管理。

事件流三类型齐全：assistant / tool_call+tool_result / state。
"""  # reload-trigger

import asyncio
import contextlib
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from services.auth import CurrentUser, get_current_user, get_current_user_ws
from services.session_event_bus import REPLAY_BATCH, SessionEventBus

# Agent 能力对全部登录用户开放（首页免权决策 2026-08-14：菜单层 PUBLIC_MENUS + 业务层登录即可）。
# 注意：本路由含 WebSocket 端点，Request 型依赖在 WS 上无法注入，
# 因此认证放在端点级（HTTP 用 get_current_user，WS 用 get_current_user_ws）。
router = APIRouter(prefix="/api/agent", tags=["agent"])

# 确保仓库根在 sys.path
SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from agent.llm_client import LLMClient
from agent.session import SessionManager, _validate_session_id
from agent.runtime import AgentRuntime, build_system_prompt, resolve_tools
from agent.purpose_loader import load_purpose, visible_purposes
from agent.doc_read import build_doc_read
from agent.doc_write import build_doc_write

SESSIONS_ROOT = SG_ROOT / "agent" / "sessions"

# K-015: 会话级互斥——同一 session_id 只允许一个活跃 run
# （session.save 是全量覆盖写，两个并发 run 会互相冲掉对方内容，last-writer-wins；
#  用户真实会话导出文件取证：同 sid 的标签生成与草稿问答两段对话互相覆盖）
_ACTIVE_RUNS: dict[str, "asyncio.Task"] = {}

# T-1021: 会话级事件总线——run 事件发布到会话频道（fan-out 多订阅者 + 当前 run
# 事件回放缓冲），刷新/断连/第二标签页可 attach 续上实时流。
_BUS = SessionEventBus()

# T-402: 会话运行时追踪（供 cancel 端点查找并设置取消标志）
_ACTIVE_RUNTIMES: dict[str, "AgentRuntime"] = {}


def _run_in_progress(session_id: str) -> bool:
    task = _ACTIVE_RUNS.get(session_id)
    return task is not None and not task.done()


def _rebuild_reading_feed(messages: list) -> list[dict]:
    """从消息链重建阅读足迹（doc_read 事件，用于会话恢复）。

    遍历 assistant 消息的 tool_calls，对读型文档工具调用 build_doc_read
    生成阅读卡片，同文件去重合并 hunks（模拟前端 doc_read 汇聚逻辑）。
    """
    items: list[dict] = []
    key_idx: dict[str, int] = {}

    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        tcs = msg.get("tool_calls") or []
        if not tcs:
            continue
        # 收集本轮 tool 结果
        results = {}
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            cid = messages[j].get("tool_call_id", "")
            results[cid] = messages[j].get("content", "")
            j += 1
        for tc in tcs:
            fn = tc.get("function", {})
            args_raw = fn.get("arguments", "")
            if isinstance(args_raw, str):
                try:
                    args_raw = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args_raw = {}
            result_text = results.get(tc.get("id", ""), "")
            evt = build_doc_read(fn.get("name", ""), args_raw, result_text, 0)
            if evt is None:
                continue
            key = evt.get("path") or evt.get("ref") or f"{evt['tool']}:unknown"
            card = {
                "key": key, "tool": evt["tool"], "ref": evt.get("ref", ""),
                "path": evt.get("path"), "turn": 0, "size": evt.get("size", 0),
                "excerpt": evt.get("excerpt", ""), "label": evt.get("label", ""),
                "thinking": evt.get("thinking", ""),
                "hunks": evt.get("hunks", []), "reads": 1,
            }
            # 同 key 去重合并 hunks + 移到头
            rebuild_items(items, key_idx, key, card, evt)

    return items


def rebuild_items(items: list, key_idx: dict, key: str, card: dict, evt: dict):
    """辅助函数：doc_read 去重合并（模拟前端 doc_read handler）。"""
    if key in key_idx:
        idx = key_idx[key]
        old = items[idx]
        seen = {(h["start"], h["end"], h["title"]) for h in old.get("hunks", [])}
        for h in evt.get("hunks", []):
            if (h["start"], h["end"], h["title"]) not in seen:
                old["hunks"].append(h)
        old["reads"] += 1
        items.pop(idx)
        items.insert(0, old)
        key_idx.clear()
        for pos, item in enumerate(items):
            key_idx[item["key"]] = pos
    else:
        items.insert(0, card)
        key_idx.clear()
        for pos, item in enumerate(items):
            key_idx[item["key"]] = pos


def _rebuild_writing_feed(messages: list, session_id: str = "",
                          workspace: str = "") -> list[dict]:
    """重建更新足迹（doc_write 事件，用于会话恢复）。

    T-1020 双源：消息链重放为主体（verdict/findings/hunks 富字段完整）
    + product_activity DB 增强/兑底（版本号附加；消息被压缩/截断的长会话
    用 DB 活动生成简化卡片，保证足迹不丢）。DB 不可用时静默回退纯重放。
    """
    items: list[dict] = []
    key_idx: dict[str, int] = {}

    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant":
            continue
        tcs = msg.get("tool_calls") or []
        if not tcs:
            continue
        # 收集本轮 tool 结果
        results = {}
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            cid = messages[j].get("tool_call_id", "")
            results[cid] = messages[j].get("content", "")
            j += 1
        for tc in tcs:
            fn = tc.get("function", {})
            args_raw = fn.get("arguments", "")
            if isinstance(args_raw, str):
                try:
                    args_raw = json.loads(args_raw)
                except (json.JSONDecodeError, TypeError):
                    args_raw = {}
            result_text = results.get(tc.get("id", ""), "")
            evt = build_doc_write(fn.get("name", ""), args_raw, result_text, 0)
            if evt is None:
                continue
            key = evt.get("path") or evt.get("ref") or f"{evt['tool']}:unknown"
            card = {
                "key": key, "tool": evt["tool"], "ref": evt.get("ref", ""),
                "path": evt.get("path"), "turn": 0, "size": evt.get("size", 0),
                "excerpt": evt.get("excerpt", ""), "label": evt.get("label", ""),
                "thinking": evt.get("thinking", ""),
                "verdict": evt.get("verdict"),
                "findings": evt.get("findings", []),
                "hunks": evt.get("hunks", []), "writes": 1,
            }
            if key in key_idx:
                old = items[key_idx[key]]
                old["writes"] += 1
                old["verdict"] = evt.get("verdict") or old.get("verdict")
                old["findings"] = evt.get("findings") or old.get("findings", [])
                old["excerpt"] = evt.get("excerpt") or old.get("excerpt")
                old["label"] = evt.get("label") or old.get("label")
                old["thinking"] = evt.get("thinking") or old.get("thinking")
                seen = {(h["start"], h["end"], h["title"]) for h in old.get("hunks", [])}
                for h in evt.get("hunks", []):
                    if (h["start"], h["end"], h["title"]) not in seen:
                        old["hunks"].append(h)
                items.pop(key_idx[key])
                items.insert(0, old)
            else:
                items.insert(0, card)
            key_idx.clear()
            for pos, item in enumerate(items):
                key_idx[item["key"]] = pos

    # ── T-1020：DB 活动增强/兑底（product_activity 为事实源）──
    if session_id:
        try:
            from sg_core import product_activity as pa
            acts = pa.by_session(session_id)
            if workspace:
                acts = [a for a in acts if a.get("workspace") == workspace]
            if acts:
                # 最新版本号映射：drafts/A.yaml → {version_no, versions, action}
                by_path: dict[str, dict] = {}
                for a in acts:
                    by_path[a["product_path"]] = a
                counts: dict[str, int] = {}
                for a in acts:
                    counts[a["product_path"]] = counts.get(a["product_path"], 0) + 1
                # ① 重放卡片附加版本信息（write_draft 卡片的 ref=filename 直接对应）
                for card in items:
                    ref = card.get("ref") or ""
                    act = by_path.get(f"drafts/{ref}")
                    if act:
                        card["version_no"] = act["version_no"]
                        card["versions"] = counts[f"drafts/{ref}"]
                # ② 兑底：DB 有活动但重放无卡片（长会话消息被压缩）→ 简化卡片
                replay_refs = {c.get("ref", "") for c in items}
                for path, act in by_path.items():
                    ref = path.split("/", 1)[1] if path.startswith("drafts/") else ""
                    if not ref or ref in replay_refs:
                        continue
                    items.insert(0, {
                        "key": path, "tool": "draft", "ref": ref, "path": None,
                        "turn": 0, "size": act.get("size", 0),
                        "excerpt": (act.get("content") or "")[:300],
                        "label": f"{act['action']} {ref}（活动流水留档）",
                        "thinking": "", "verdict": None, "findings": [],
                        "hunks": [], "writes": counts[path],
                        "version_no": act["version_no"], "versions": counts[path],
                    })
        except Exception:
            pass  # DB 不可用 → 纯重放（旧会话/旧库无表）

    return items


def _build_scenario_context(scenario_id: str) -> str:
    """构建场景上下文字符串（基础信息包提示）。"""
    if not scenario_id:
        return ""
    try:
        BACKEND_DIR = SG_ROOT / "workbench" / "backend"
        from services import scenario_meta
        meta = scenario_meta.get_meta(scenario_id)
    except Exception:
        return ""
    if not meta:
        return ""
    files = meta.get("info_pack", [])
    if not files:
        return f"当前场景：{scenario_id}（{meta.get('name', '')}）。基础信息包为空，请用 read_spec 工具读取工作区文件。"
    # K-013：信息包清单附新鲜度标记（每条消息重建 context，天然实时感知变更）
    from specstd.workspace import safe_resolve, remote_file_marks
    paths = [e.get("path", "") if isinstance(e, dict) else str(e) for e in files]
    try:
        remote_marks = remote_file_marks(paths)
    except Exception:
        remote_marks = {}
    lines = []
    for e, path in zip(files, paths):
        stored = e.get("sha", "") if isinstance(e, dict) else ""
        mark = ""
        try:
            resolved = safe_resolve(path)
            if not resolved or not resolved.is_file():
                mark = "（已删除）"
            elif stored and scenario_meta.file_sha(resolved) != stored:
                mark = "（已变更）"
        except Exception:
            pass
        rm = remote_marks.get(path, "")
        if rm == "[远程已更新]":
            mark += "（远程已更新）"
        elif rm == "[远程不存在]":
            mark += "（远程不存在）"
        lines.append(f"  - {path}{mark}")
    file_list = "\n".join(lines)
    stale_hint = ("\n注意：标记（已变更）/（已删除）的文件与信息包记录时不一致，"
                  "请以当前内容为准，并提醒用户信息包需要更新；"
                  "标记（远程已更新）/（远程不存在）表示远程仓库与本地不同步，"
                  "建议用户先在工作区中心「同步」后重新读取。") if any("（" in ln for ln in lines) else ""
    return (
        f"当前场景：{scenario_id}（{meta.get('name', '')}）\n"
        f"模块：{meta.get('module', '')}\n"
        f"基础信息包文件：\n{file_list}\n"
        f"请用 read_info_pack 工具读取上述文件内容。{stale_hint}"
    )


def _sessions_dir(emp_no: str) -> Path:
    """按用户隔离的会话目录（M7）：agent/sessions/{emp_no}/。

    L4 修复：净化规则与 specstd.workspace._emp_subdir 对齐（允许 . 与 -，
    strip 前导点）——此前规则不一致导致含 . 工号的会话目录与产物私有区目录错位。
    """
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", emp_no or "_anonymous").strip(".")
    return SESSIONS_ROOT / (safe or "_anonymous")


# ══════════════════════════════════════════════════════════
# K-013: @引用处理（信息包关联 / 文件与草稿内容注入）
# ══════════════════════════════════════════════════════════

_REF_MAX_FILE = 20 * 1024    # 单文件注入上限 20KB
_REF_MAX_TOTAL = 60 * 1024   # 全部引用注入上限 60KB
_REF_MAX_COUNT = 10          # 单条消息最多引用数


def _process_references(references: list, scenario_id: str) -> tuple[str, str, list]:
    """处理 @引用，返回 (scenario_id, 引用内容块, 结构化引用清单)。

    - info_pack：上传即关联——无条件接管为最新信息包，且文件内容直接注入
      <references> 块（对齐业界附件模式：OpenAI input_file / Anthropic document
      block / Cursor @ 展开均是附件内容随上传那一轮 user message 直接可见，
      不依赖 system prompt 提示 + 模型自己调工具的绕圈链路）。
      生产佐证（会话 20260824_172320_84d21cfa）：旧「只关联不注入」链路 4 环全断，
      两批上传模型均看不到。
    - file / draft：读取内容（截断保护）拼 <references> 块前缀到 user message，
      同时返回含引用时 sha 的结构化清单（挂 user 消息持久化，供右侧引用面板比对新鲜度）
    """
    import hashlib
    if not references:
        return scenario_id, "", []

    from specstd.workspace import safe_resolve

    structured: list[dict] = []
    blocks: list[str] = []
    total = 0

    def _read_pack_file(fp: str) -> tuple[str, str]:
        """读信息包单个文件 → (content, sha)；与 file/draft 引用同款截断与转文本规则。"""
        try:
            resolved = safe_resolve(fp)
            if not (resolved and resolved.is_file()):
                return "", ""
            raw = resolved.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()[:12]
            # K-030 同款守卫：办公文档（xlsx/docx/pdf）转文本，避免乱码注入
            from services import file_preview
            if file_preview.is_office_doc(resolved):
                _fmt, content = file_preview.preview_text(resolved)
                content = f"[办公文档已转换为文本预览]\n{content}"
            else:
                content = raw.decode("utf-8", errors="replace")
            return content, sha
        except Exception:
            return "", ""

    for ref in references[:_REF_MAX_COUNT]:
        if not isinstance(ref, dict):
            continue
        rtype = ref.get("type", "")
        rid = str(ref.get("id") or ref.get("path") or "")
        if not rid:
            continue

        if rtype == "info_pack":
            # 上传即关联：无条件接管为最新信息包（此前仅在空时接管，
            # 已绑定场景的会话新上传被静默忽略——见上 docstring 生产佐证）
            scenario_id = rid
            structured.append({"type": "info_pack", "path": rid, "sha": ""})
            try:
                from sg_core import scenario_meta as _sm
                meta = _sm.get_meta(rid)
            except Exception:
                meta = None
            if not meta:
                blocks.append(f"--- {rid} ---\n[信息包不存在或不可读，可让用户重新上传]")
                continue
            pack_files = [e.get("path", "") if isinstance(e, dict) else str(e)
                          for e in (meta.get("info_pack") or [])]
            if not pack_files:
                blocks.append(f"--- {rid}（{meta.get('name', '')}） ---\n[信息包为空]")
                continue
            for fp in pack_files:
                content, sha = _read_pack_file(fp)
                if not content:
                    blocks.append(f"--- {fp} ---\n[文件不存在或不可读]")
                    continue
                truncated = False
                if len(content) > _REF_MAX_FILE:
                    content = content[:_REF_MAX_FILE]
                    truncated = True
                if total + len(content) > _REF_MAX_TOTAL:
                    content = content[:max(0, _REF_MAX_TOTAL - total)]
                    truncated = True
                total += len(content)
                blocks.append(f"--- {fp} (sha:{sha}) ---\n{content}"
                              + ("\n[截断]" if truncated else ""))
            continue

        if rtype == "material":
            # T-933: 材料引用——不注入全文（大文档会挤爆上下文），只注入标识/
            # 文件名/状态；正文由 agent 用 pack(action=read_material) 工具按需分页读取
            # （requirement_interview 白名单已登记）
            m = None
            try:
                from services.specflow.materials_service import _db_conn
                from specflow.materials import store
                conn = _db_conn()
                try:
                    m = store.get_material(conn, rid)
                finally:
                    conn.close()
            except Exception:
                m = None
            ws_now = ""
            try:
                from specstd.workspace import get_context_workspace
                ws_now = get_context_workspace() or ""
            except Exception:
                pass
            if m and m.get("workspace") == ws_now:
                blocks.append(
                    f"--- {rid} (material:{m['filename']}, status:{m['status']}) ---\n"
                    "[材料引用] 内容不注入——用 pack(action=read_material) 工具按需读取"
                    "（section=summary|topics|raw，raw 支持 offset/limit 分页）")
                structured.append({"type": "material", "path": rid,
                                   "sha": str(m.get("sha256_12") or ""),
                                   "label": m["filename"]})
            else:
                blocks.append(f"--- {rid} ---\n[材料不存在或不可读]")
                structured.append({"type": "material", "path": rid, "sha": "",
                                   "missing": True})
            continue

        content, sha = "", ""
        try:
            if rtype == "file":
                resolved = safe_resolve(rid)
                if resolved and resolved.is_file():
                    raw = resolved.read_bytes()
                    sha = hashlib.sha256(raw).hexdigest()[:12]
                    # K-030：办公文档（xlsx/docx/pdf）经 file_preview 转文本——
                    # 此前 errors="replace" 解码出乱码注入，Agent 读不懂信息包里的 xlsx
                    from services import file_preview
                    if file_preview.is_office_doc(resolved):
                        _fmt, content = file_preview.preview_text(resolved)
                    else:
                        content = raw.decode("utf-8", errors="replace")
            elif rtype == "draft":
                # 草稿文件名守卫（与 draft_writer 一致：禁路径分隔符和 ..）
                name = rid.replace("/", "").replace("\\", "").replace("..", "")
                from specstd.workspace import drafts_dir
                p = drafts_dir() / name
                if p.is_file():
                    raw = p.read_bytes()
                    sha = hashlib.sha256(raw).hexdigest()[:12]
                    content = raw.decode("utf-8", errors="replace")
        except Exception:
            continue

        if not content:
            blocks.append(f"--- {rid} ---\n[文件不存在或不可读]")
            structured.append({"type": rtype, "path": rid, "sha": "", "missing": True})
            continue

        # 远程新鲜度检查（只对工作区文件：远程有更新/远程不存在时标注入引用标头）
        remote_mark = ""
        if rtype == "file":
            try:
                from specstd.workspace import remote_file_marks
                rm = remote_file_marks([rid]).get(rid, "")
                if rm == "[远程已更新]":
                    remote_mark = " [远程已更新]"
                elif rm == "[远程不存在]":
                    remote_mark = " [远程不存在]"
            except Exception:
                pass

        truncated = False
        if len(content) > _REF_MAX_FILE:
            content = content[:_REF_MAX_FILE]
            truncated = True
        if total + len(content) > _REF_MAX_TOTAL:
            content = content[:max(0, _REF_MAX_TOTAL - total)]
            truncated = True
        total += len(content)
        blocks.append(f"--- {rid} (sha:{sha}){remote_mark} ---\n{content}" + ("\n[截断]" if truncated else ""))
        structured.append({"type": rtype, "path": rid, "sha": sha})

    block_text = ""
    if blocks:
        block_text = "<references>\n" + "\n\n".join(blocks) + "\n</references>\n\n"
    return scenario_id, block_text, structured


# ══════════════════════════════════════════════════════════
# 辅助会话：父会话每轮快照注入（设计 2026-08-25 §B4，主→辅单向通道）
# ══════════════════════════════════════════════════════════

_SNAPSHOT_MAX_CHARS = 8 * 1024


def _parent_snapshot(sm: SessionManager, parent_sid: str, last_fp: str) -> tuple[str, str]:
    """构造父会话最新快照。返回 (注入文本, 新指纹)。

    - 父不可读 → 降级行（辅助会话继续不炸）
    - 指纹与上轮相同 → 一行「无变更」（省 token）
    - 内容：父会话 meta 概要 + 最新草稿足迹 + 最近 assistant 摘要（500 字符）
    """
    import hashlib
    msgs = None
    try:
        msgs = sm.load(parent_sid)
    except Exception:
        msgs = None
    if msgs is None:
        return "[parent_context] 父会话不可读（可能已删除）\n", last_fp

    parent_meta = sm._read_meta(sm.sessions_dir / f"{parent_sid}.jsonl") or {}

    # 最新草稿足迹（write_draft 收集——与前端 sessionDrafts 同语义）
    drafts: list[str] = []
    for m in msgs:
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        for tc in m["tool_calls"]:
            try:
                args = json.loads(tc.get("function", {}).get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            fname = tc.get("function", {}).get("name", "")
            if (fname == "write_draft" or (fname == "draft" and args.get("action") == "write")) \
                    and args.get("filename"):
                drafts.append(str(args["filename"]))

    last_assistant = ""
    for m in reversed(msgs):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            last_assistant = m["content"][:500]
            break

    parts = [
        f"父会话 {parent_sid}（title={parent_meta.get('title', '')} "
        f"purpose={parent_meta.get('purpose', '')}）最新快照：",
        f"- 最新草稿文件: {', '.join(drafts[-5:]) or '（无）'}",
        f"- 最近回复摘要: {last_assistant or '（无）'}",
    ]
    body = "\n".join(parts)
    fp = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    if last_fp and fp == last_fp:
        return "[parent_context] 主会话自上轮起无变更\n", fp
    if len(body) > _SNAPSHOT_MAX_CHARS:
        body = body[:_SNAPSHOT_MAX_CHARS] + "\n…（截断）"
    return f"<parent_context>\n{body}\n</parent_context>\n", fp


def _iter_all_session_dirs() -> list[Path]:
    """全部用户会话目录（admin 视图）。"""
    if not SESSIONS_ROOT.is_dir():
        return []
    return [d for d in sorted(SESSIONS_ROOT.iterdir())
            if d.is_dir() and not d.name.startswith((".", "_"))]


def _list_sessions_in_dir(base_dir: Path, workspace: str = "") -> list[dict]:
    """在指定目录下列出会话（支持工作区子目录）。"""
    from agent.session import SessionManager
    sessions = []
    if workspace:
        # 指定工作区：只查该子目录
        ws_dir = base_dir / workspace
        if ws_dir.is_dir():
            sm = SessionManager(base_dir, workspace=workspace)
            sessions.extend(sm.list_sessions())
    else:
        # 未指定工作区：查根目录（旧会话）+ 所有工作区子目录
        sm = SessionManager(base_dir)
        sessions.extend(sm.list_sessions())
        for sub in sorted(base_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith("_") and not sub.name.startswith("."):
                ws_sm = SessionManager(base_dir, workspace=sub.name)
                for s in ws_sm.list_sessions():
                    sessions.append(s)
    return sessions


def _find_session_owner(session_id: str) -> str:
    """查找会话归属目录名（非 admin 取消/读取时的归属校验用；未找到返回空串）。"""
    _validate_session_id(session_id)
    for d in _iter_all_session_dirs():
        if SessionManager(d).load(session_id) is not None:
            return d.name
        for sub in sorted(d.iterdir()):
            if sub.is_dir() and not sub.name.startswith((".", "_")):
                if SessionManager(d, workspace=sub.name).load(session_id) is not None:
                    return d.name
    return ""


# ══════════════════════════════════════════════════════════
# REST 端点
# ══════════════════════════════════════════════════════════

@router.get("/purposes")
def list_purposes_api(user: CurrentUser = Depends(get_current_user)):
    """T-012/T-013：当前用户可见用途清单（角色集合并集过滤；多用途用户多卡）。"""
    purposes = visible_purposes(user.roles)
    return {"purposes": [{
        "id": p.id,
        "title": p.title,
        "icon": p.icon,
        "color": p.color,
        "chips": p.chips,
        "description": p.description,
        "panels": p.panels,
    } for p in purposes]}


@router.post("/sessions")
def create_session(body: dict, user: CurrentUser = Depends(get_current_user)):
    """T-010：创建会话——唯一可写 purpose 的入口（创建期锁定，不可中途变更）。

    入参：{purpose, workspace, title?}
    purpose 非法（未定义）或无权限（角色不可见）→ 403。
    """
    purpose = str(body.get("purpose", "") or "").strip()
    workspace = str(body.get("workspace", "") or "").strip()
    title = str(body.get("title", "") or "").strip()
    if not purpose:
        raise HTTPException(status_code=400, detail="purpose 必填")
    # 用途合法性 + 角色可见性（二次鉴权）
    pdef = load_purpose(purpose)
    if pdef is None:
        raise HTTPException(status_code=403, detail=f"用途不存在或不可见: {purpose}")
    if not (set(user.roles) & set(pdef.roles)):
        raise HTTPException(status_code=403, detail=f"当前角色无权限使用用途: {purpose}")
    # 2026-08-26 验收修复：spawn_only 用途（辅助会话）不可直接建会话，只能从主会话 spawn 派生
    if getattr(pdef, "spawn_only", False):
        raise HTTPException(
            status_code=403,
            detail=f"用途 {purpose} 是辅助会话（spawn_only），请从主会话面板派生，不可直接创建")
    # L2 修复：workspace 非法（ValueError → 500）与未授权（绕过 resolve_workspace）
    # 统一前置为 4xx
    if workspace and not user.is_admin:
        from services import user_store as _us
        if not _us.has_grant(user.emp_no, workspace):
            raise HTTPException(status_code=403, detail=f"未授权工作区: {workspace}")
    try:
        sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"非法 workspace: {e}")
    # 创建会话（emp 隔离 + workspace 子目录 + purpose 锁定）
    sid = sm.create(emp_no=user.emp_no, workspace=workspace, purpose=purpose)
    # 索引投影（失败静默）
    try:
        from services import agent_session_store
        agent_session_store.upsert_session(sid, user.emp_no, workspace, purpose, title)
    except Exception:
        pass
    meta = sm.list_sessions()
    created = next((s for s in meta if s["id"] == sid), {})
    return {"ok": True, "session_id": sid, "session": created}


@router.post("/sessions/spawn")
def spawn_session(body: dict, user: CurrentUser = Depends(get_current_user)):
    """辅助会话派生（设计 2026-08-25 §B3）：从主会话派生专职 purpose 的辅助会话。

    幂等：同父会话 + 同 purpose 存在未归档 aux 会话 → 直接返回（created=False）；
    父会话的 aux 已归档时再派生新的。父会话必须存在且属当前用户。
    """
    parent_sid = str(body.get("parent_session_id", "") or "").strip()
    purpose = str(body.get("purpose", "") or "").strip()
    workspace = str(body.get("workspace", "") or "").strip()
    if not parent_sid or not purpose:
        raise HTTPException(status_code=400, detail="parent_session_id 与 purpose 必填")
    try:
        _validate_session_id(parent_sid)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 parent_session_id")
    pdef = load_purpose(purpose)
    if pdef is None or not (set(user.roles) & set(pdef.roles)):
        raise HTTPException(status_code=403, detail=f"用途不存在或无权限: {purpose}")
    try:
        sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"非法 workspace: {e}")
    if sm.load(parent_sid) is None:
        raise HTTPException(status_code=404, detail="父会话不存在")
    # 幂等：同父 + 同 purpose 的未归档 aux 直接复用
    for s in sm.list_sessions():
        if (s.get("kind") == "aux"
                and s.get("parent_session_id") == parent_sid
                and s.get("purpose") == purpose
                and not s.get("archived")):
            return {"ok": True, "session_id": s["id"], "created": False}
    sid = sm.create(
        emp_no=user.emp_no, workspace=workspace, purpose=purpose,
        extra_meta={"kind": "aux", "parent_session_id": parent_sid})
    try:
        from services import agent_session_store
        agent_session_store.upsert_session(sid, user.emp_no, workspace, purpose, "")
    except Exception:
        pass
    return {"ok": True, "session_id": sid, "created": True}


@router.post("/sessions/{session_id}/clear")
def clear_session_messages(session_id: str, workspace: str = "",
                           user: CurrentUser = Depends(get_current_user)):
    """清空会话消息（辅助会话长对话瘦身，2026-08-26）。

    保留首行 meta（purpose/kind/parent 链接/白名单/标题）；辅助会话同步重置
    last_parent_fp——父会话快照是每轮注入（§B4），指纹清空后下一轮重新注入
    完整 <parent_context>，清空不丢主会话关键信息。owner 权限（本人会话）；
    执行中的会话拒绝清空（与后台 run 落盘竞争，K-015 同语义）。
    """
    try:
        _validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="非法 session_id") from e
    sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    # 存在性用 is None 判断（空会话 load 返回 []，falsy 会误判不存在）
    if sm.load(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if _run_in_progress(session_id):
        raise HTTPException(status_code=409, detail="会话仍在后台执行上一条消息，请等待完成或先停止再清空")
    sm.save(session_id, [])  # 清空消息（meta 继承：purpose/kind/parent 链接）
    sm.set_meta_fields(session_id, last_parent_fp="")  # 重置快照指纹 → 下轮注入完整父快照
    return {"ok": True, "session_id": session_id}


@router.patch("/sessions/{session_id}")
def patch_session(session_id: str, body: dict,
                  workspace: str = "",
                  user: CurrentUser = Depends(get_current_user)):
    """T-010：改标题/归档；请求体含 purpose → 409（用途创建即锁定）。"""
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    if "purpose" in body:
        raise HTTPException(status_code=409, detail="用途创建即锁定，不可中途变更（换用途 = 新建会话）")
    sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    # 存在性用 is None 判断（空会话 load 返回 []，falsy 会误判不存在）
    if sm.load(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    title = str(body.get("title", "") or "").strip()
    if title:
        sm.update_title(session_id, title)
        try:
            from services import agent_session_store
            agent_session_store.update_title(session_id, title)
        except Exception:
            pass
    # 归档/恢复（T-010 扩展：列表瘦身，归档不删文件）
    if "archived" in body:
        sm.set_archived(session_id, bool(body.get("archived")))
    return {"ok": True, "session_id": session_id}


@router.post("/sessions/batch-archive")
def batch_archive_sessions(body: dict,
                           workspace: str = "",
                           user: CurrentUser = Depends(get_current_user)):
    """批量归档/恢复会话（T-010 扩展）：owner 权限——每个用户只管理自己创建的会话，admin 无越权。

    入参：{session_ids: [...], archived: bool}
    返回：{processed: n, skipped: [id...]}（skipped 仅当 id 不在本人目录；前端只允许勾选本人会话，UI 上零跳过）
    """
    raw_ids = body.get("session_ids", []) or []
    if not isinstance(raw_ids, list) or not raw_ids:
        raise HTTPException(status_code=400, detail="session_ids 必填（非空数组）")
    archived = bool(body.get("archived", True))
    sm = SessionManager(_sessions_dir(user.emp_no), workspace=workspace)
    processed = 0
    skipped = []
    for sid in raw_ids:
        sid = str(sid).strip()
        if not sid:
            continue
        try:
            _validate_session_id(sid)
        except ValueError:
            skipped.append(sid)
            continue
        # 存在性用 is None（空会话 load 返回 []，falsy 会误判）；不在本人目录 = 他人会话，跳过
        if sm.load(sid) is None:
            skipped.append(sid)
            continue
        # set_archived 返回 False = 首行非 session_meta（异常文件），按失败计入 skipped
        if not sm.set_archived(sid, archived):
            skipped.append(sid)
            continue
        processed += 1
    return {"ok": True, "processed": processed, "skipped": skipped, "archived": archived}


@router.get("/sessions")
def list_sessions(workspace: str = "", purpose: str = "", include_archived: int = 0,
                  user: CurrentUser = Depends(get_current_user)):
    """列出会话：owner 权限——每个用户只列出自己创建的会话（admin 无聚合特权，他人会话不出现在列表中）。

    支持按工作区/用途筛选；默认不含已归档会话。
    """
    sm_dir = _sessions_dir(user.emp_no)
    sessions = _list_sessions_in_dir(sm_dir, workspace=workspace)
    # owner 字段统一（前端 owner 权限判断依赖；本列表均为本人会话）
    for s in sessions:
        s.setdefault("owner", user.emp_no)
    if purpose:
        sessions = [s for s in sessions if s.get("purpose") == purpose]
    if not include_archived:
        sessions = [s for s in sessions if not s.get("archived")]
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, workspace: str = "", user: CurrentUser = Depends(get_current_user)):
    """获取会话详情（本人会话；admin 可查全部）。支持工作区子目录。

    M3 修复：product 加入读取权限（多角色扩展遗漏——product 能建会话却读不到自己历史）。
    非 admin 目录限定本人（_sessions_dir(user.emp_no)），天然隔离他人会话。
    """
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    dirs = _iter_all_session_dirs() if user.is_admin else [_sessions_dir(user.emp_no)]
    # T-1021: run 进行中标志 + 基线消息数（前端据此 attach 续传并截断去重）
    snap = _BUS.snapshot(session_id)
    for d in dirs:
        # 尝试工作区子目录 + 根目录
        sm = SessionManager(d, workspace=workspace)
        messages = sm.load(session_id)
        if messages is not None:
            reading_feed = _rebuild_reading_feed(messages)
            writing_feed = _rebuild_writing_feed(messages, session_id, workspace)
            return {"session_id": session_id, "messages": messages,
                    "reading_feed": reading_feed, "writing_feed": writing_feed,
                    "owner": d.name, "workspace": workspace,
                    "run_in_progress": _run_in_progress(session_id),
                    "run_baseline_len": snap["baseline_len"] if snap["exists"] else 0}
        # 如果指定工作区未找到，也尝试无工作区（兼容旧会话）
        if workspace:
            sm2 = SessionManager(d)
            messages = sm2.load(session_id)
            if messages is not None:
                return {"session_id": session_id, "messages": messages,
                        "reading_feed": _rebuild_reading_feed(messages),
                        "writing_feed": _rebuild_writing_feed(messages, session_id, ""),
                        "owner": d.name, "workspace": "",
                        "run_in_progress": _run_in_progress(session_id),
                        "run_baseline_len": snap["baseline_len"] if snap["exists"] else 0}
    raise HTTPException(status_code=404, detail="会话不存在")


def _generate_session_title(llm: LLMClient, messages: list[dict]) -> str:
    """用 LLM 生成会话标题（首条用户消息 + 首条助手回复 → 简短标题）。

    mock 模式下回退为用户消息截断。
    """
    user_msg = next((m for m in messages if m.get("role") == "user"), None)
    assistant_msg = next((m for m in messages if m.get("role") == "assistant"), None)
    if not user_msg:
        return "新会话"
    user_content = str(user_msg.get("content", ""))[:200]
    if llm.is_mock:
        # mock 模式：截取用户消息前 15 字符
        title = user_content[:15].replace("\n", " ").strip()
        return title or "新会话"
    try:
        prompt_msgs = [
            {"role": "system", "content": "请用10个字以内概括以下对话的主题，只输出标题文字，不要加引号或标点。"},
            {"role": "user", "content": f"用户：{user_content}\n助手：{str(assistant_msg.get('content', ''))[:200] if assistant_msg else ''}"},
        ]
        msg, _ = llm.chat(prompt_msgs, tools=None)
        title = str(msg.get("content", "")).strip().replace("\n", " ")[:20]
        return title or "新会话"
    except Exception:
        return user_content[:15].replace("\n", " ").strip() or "新会话"


@router.get("/sessions/{session_id}/export")
def export_session(session_id: str, workspace: str = "", user: CurrentUser = Depends(get_current_user)):
    """导出会话为 JSON（元数据 + 消息 + 指标），便于排查问题。M3：product 可导出本人会话。"""
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")
    dirs = _iter_all_session_dirs() if user.is_admin else [_sessions_dir(user.emp_no)]
    for d in dirs:
        sm = SessionManager(d, workspace=workspace)
        data = sm.export_session(session_id)
        if data is not None:
            return data
        if workspace:
            sm2 = SessionManager(d)
            data = sm2.export_session(session_id)
            if data is not None:
                return data
    raise HTTPException(status_code=404, detail="会话不存在")


@router.post("/cancel/{session_id}")
async def cancel_agent(session_id: str,
                       user: CurrentUser = Depends(get_current_user)):
    """T-402：取消指定会话的当前运行（真打断）。

    设置运行时 cancellation 标志 → 当前轮次 tool 执行完即停止，不再推进下一轮，
    且不再写会话文件。M3：product 新增可取消权；非 admin 归属校验——只能取消自己的会话。
    """
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="非法 session_id")

    runtime = _ACTIVE_RUNTIMES.get(session_id)
    if not runtime:
        raise HTTPException(status_code=404, detail="该会话没有活跃的运行")

    # M3：归属校验（_ACTIVE_RUNTIMES 为全局表，不能只靠会话存在性放行）
    if not user.is_admin:
        owner = _find_session_owner(session_id)
        if owner != _sessions_dir(user.emp_no).name:
            raise HTTPException(status_code=403, detail="无权取消他人会话")

    runtime.cancel()
    return {"ok": True, "session_id": session_id, "message": "已请求取消"}


# ══════════════════════════════════════════════════════════
# WebSocket 端点
# ══════════════════════════════════════════════════════════

async def _handle_attach(websocket: WebSocket, data: dict, user, emp_no: str):
    """T-1021: attach——订阅运行中会话的事件频道（断连/刷新/第二标签页续传）。

    回放当前 run 已缓冲事件 + 实时续推直到 done/error（或前端 detach / 连接断开），
    之后返回主循环——连接恢复正常收发（下一条消息走既有路径）。
    前端配合：attach 前按 getSession 的 run_baseline_len 截断消息到基线，
    回放事件流经既有渲染管线重建「运行中」现场，done 后全量对齐。
    """
    sid = str(data.get("session_id", "") or "")
    try:
        _validate_session_id(sid)
    except ValueError:
        await websocket.send_json({"type": "error", "message": "非法 session_id"})
        return
    # 归属校验：非 admin 只能 attach 本人会话（与 cancel 端点同口径）
    if not user.is_admin and _find_session_owner(sid) != emp_no:
        await websocket.send_json({"type": "error", "message": "无权访问该会话"})
        return
    if not _run_in_progress(sid):
        # 竞态：attach 前刚好完成——告知前端全量拉取对齐即可（done 可能已落盘）
        await websocket.send_json({"type": "attached", "session_id": sid,
                                   "run_in_progress": False})
        return
    attached = _BUS.attach(sid)
    if attached is None:  # 防御：run 登记与频道建立之间的极端竞态
        await websocket.send_json({"type": "attached", "session_id": sid,
                                   "run_in_progress": False})
        return
    sub, replay, meta = attached
    try:
        try:
            await websocket.send_json({"type": "attached", "session_id": sid,
                                       "run_in_progress": True,
                                       "baseline_len": meta["baseline_len"]})
            # 回放分批推送（长 run 全量回放拆帧，前端逐条喂既有事件管线）
            for i in range(0, len(replay), REPLAY_BATCH):
                await websocket.send_json({"type": "replay_batch", "session_id": sid,
                                           "events": replay[i:i + REPLAY_BATCH]})
        except Exception:
            return  # 回放阶段连接已断：退订返回（run 不受影响）
        # 实时续推：reader 并发监听 detach/ping；主侧推事件直到结束信号
        detach_event = asyncio.Event()

        async def _reader():
            try:
                while True:
                    msg = await websocket.receive_json()
                    t = msg.get("type", "")
                    if t == "detach":
                        detach_event.set()
                        return
                    if t == "ping":
                        await websocket.send_json({"type": "pong"})
            except Exception:
                detach_event.set()  # 连接断开视为 detach
                return

        reader = asyncio.create_task(_reader())
        try:
            heartbeat_tick = 0
            while True:
                if detach_event.is_set():
                    break
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=0.2)
                    await websocket.send_json(event)
                    heartbeat_tick = 0
                    if event.get("type") in ("done", "error"):
                        break
                except TimeoutError:
                    heartbeat_tick += 1
                    if heartbeat_tick >= 50:  # 10s 无事件：保活心跳（同主循环节奏）
                        try:
                            await websocket.send_json({"type": "heartbeat"})
                        except Exception:
                            break
                        heartbeat_tick = 0
                    # 兜底：run 已结束且终态事件丢失（异常路径/极端竞态）→ 合成
                    # attached(run_in_progress=false) 让前端解除 loading 并全量拉取对齐。
                    # 三重条件防误触发：_run_in_progress 与 queue.empty() 非原子检查，
                    # 两次检查之间 done 可能恰好尚未发布（worker 已返回、主循环还没走
                    # 到 publish）——此时提前退订会错过紧接着的 done。必须再加总线
                    # 频道的 done 标记（publish 内同步置位，证明终态确已发布）。
                    if not _run_in_progress(sid) and sub.queue.empty() \
                            and _BUS.snapshot(sid)["done"]:
                        with contextlib.suppress(Exception):
                            await websocket.send_json({"type": "attached", "session_id": sid,
                                                       "run_in_progress": False})
                        break
                    continue
                except Exception:
                    break  # 连接断开
        finally:
            reader.cancel()
    finally:
        _BUS.detach(sid, sub)


@router.websocket("/ws")
async def agent_ws(websocket: WebSocket,
                   _user: CurrentUser = Depends(get_current_user_ws)):
    """WebSocket 实时对话（WS 专用角色依赖；token 经 query 参数传入）。

    前端发送：{"message": "用户消息", "session_id": "可选会话ID"}
    后端推送事件：assistant / tool_call / state / done
    """
    await websocket.accept()
    # 连接级用户身份（路由级 require_role 已完成认证，身份经 contextvar 传入）
    from services.auth import current_emp_no
    _ws_emp_no = current_emp_no()
    # T-013: 连接级角色集（白名单装配用；require_role_ws 已认证）
    _ws_roles = list(_user.roles or [])

    # 从查询参数读取工作区并设置上下文（浏览器 WebSocket 不支持自定义 header）
    from specstd.workspace import set_context_workspace, reset_context_workspace
    _ws_query_workspace = websocket.query_params.get("workspace", "")
    # 授权检查：非 admin 用户必须已被授权该工作区
    if _ws_query_workspace and not _user.is_admin:
        from services import user_store as _auth_store
        if not _auth_store.has_grant(_user.emp_no, _ws_query_workspace):
            await websocket.close(code=4403)
            return
    _ws_ctx_token = set_context_workspace(_ws_query_workspace or None)

    try:
        _idle_heartbeat_tick = 0
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=20.0)
            except asyncio.TimeoutError:
                # K-xxx: 空闲期心跳——等待用户消息期间保持连接活跃，
                # 防止代理/NAT 超时断连，同时让前端检测到连接存活
                _idle_heartbeat_tick += 1
                # 每 20s 发一次心跳（每轮超时就发，防止累计误差）；
                # 发送失败（异常类型随 uvicorn WS 实现而异）= 连接已死
                try:
                    await websocket.send_json({"type": "heartbeat"})
                except Exception:
                    raise WebSocketDisconnect(code=1006)
                continue
            except json.JSONDecodeError:
                # 非 JSON 消息：忽略（不中断连接）
                continue
            except Exception:
                # K-xxx: uvicorn WS 实现断连时抛 ConnectionClosed/RuntimeError 等
                # （非 WebSocketDisconnect）——统一转为断连语义，走 WebSocketDisconnect
                # 分支（不写 error 行到会话 JSONL）
                raise WebSocketDisconnect(code=1006)

            # 处理协议级消息（ping/pong）
            msg_type = data.get("type", "")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            # T-1021: attach——订阅运行中会话的事件频道（回放+实时续推）；
            # detach——退订（前端切会话时发送；非 attach 状态收到则静默忽略）
            if msg_type == "attach":
                await _handle_attach(websocket, data, _user, _ws_emp_no)
                continue
            if msg_type == "detach":
                continue

            # 重置空闲心跳计数（收到有效消息说明连接正常）
            _idle_heartbeat_tick = 0

            message = data.get("message", "")
            session_id = data.get("session_id", "")
            max_turns = data.get("max_turns", 12)
            workspace = data.get("workspace", "")
            scenario_id = data.get("scenario_id", "")
            model_id = data.get("model_id", "")
            purpose = data.get("purpose", "")  # T-010: 新建会话时可选传入用途
            references = data.get("references", [])  # K-013: @引用

            # 辅助会话标记（设计 2026-08-25 §B4——快照注入依据；默认空=普通会话）
            session_kind = ""
            parent_sid = ""
            last_parent_fp = ""

            if not message:
                await websocket.send_json({"type": "error", "message": "缺少 message 参数"})
                continue
            if session_id:
                try:
                    _validate_session_id(session_id)
                except ValueError:
                    await websocket.send_json({"type": "error", "message": "非法 session_id"})
                    continue

            # 初始化（会话按用户隔离 + 工作区）
            emp_no = _ws_emp_no or "_anonymous"
            llm = LLMClient(model_id=model_id) if model_id else LLMClient()
            sessions_dir = _sessions_dir(emp_no)
            sm = SessionManager(sessions_dir, workspace=workspace)
            is_new_session = not session_id
            # T-010: 新建会话必须选用途（未选使命 = 创建无用途会话：工具集不锁定、提示词不装配；
            # 前端已拦截，此处兜底拒绝绕过前端的直连 WS）
            session_purpose = purpose or ""
            session_tools_snapshot = None  # M5：已建会话的创建期 tool_whitelist 快照
            if is_new_session:
                if not session_purpose:
                    await websocket.send_json({
                        "type": "error",
                        "message": "请先选择会话用途（测试工作台 / 产品工作台）",
                    })
                    continue
                pdef = load_purpose(session_purpose)
                if pdef is None or not (set(_ws_roles) & set(pdef.roles)):
                    await websocket.send_json({
                        "type": "error",
                        "message": f"用途不存在或无权限: {session_purpose}",
                    })
                    continue
                # 2026-08-26 验收修复：spawn_only 用途拦截（与 REST create_session 同语义）
                if getattr(pdef, "spawn_only", False):
                    await websocket.send_json({
                        "type": "error",
                        "message": f"用途 {session_purpose} 是辅助会话（spawn_only），请从主会话面板派生",
                    })
                    continue
            else:
                try:
                    metas = sm.list_sessions()
                    meta = next((s for s in metas if s["id"] == session_id), {})
                    session_purpose = meta.get("purpose", "")
                    # M5：优先取创建期快照（purpose 定义热更新/文件变更不回流已建会话）；
                    # 旧会话无快照时才回退 load_purpose 现解
                    session_tools_snapshot = meta.get("tool_whitelist") or None
                    # 辅助会话：恢复 kind/父链接/快照指纹（§B4）
                    session_kind = meta.get("kind", "")
                    parent_sid = meta.get("parent_session_id", "")
                    last_parent_fp = meta.get("last_parent_fp", "")
                except Exception:
                    session_purpose = ""
                    session_tools_snapshot = None
                    session_kind = ""
                    parent_sid = ""
                    last_parent_fp = ""
            sid = session_id or sm.create(emp_no=emp_no, workspace=workspace, purpose=session_purpose)
            llm.set_metrics_file(sessions_dir / (f"{workspace}/" if workspace else "") / f"{sid}_metrics.jsonl")
            # T-010: 会话索引投影（失败静默）
            try:
                from services import agent_session_store
                agent_session_store.upsert_session(sid, emp_no, workspace, session_purpose or "")
            except Exception:
                pass

            # K-015: 同会话并发写防护（另一连接/标签页正在执行同一会话时拒绝）。
            # K-xxx: 断连不打断后台 run 后，重连重发命中此性是正常现象——提示稍候
            if _run_in_progress(sid):
                await websocket.send_json({
                    "type": "error",
                    "message": "该会话仍在后台执行上一条消息（断连不打断，完成后自动落盘），请稍候重试或点击停止后再发送",
                })
                continue

            await websocket.send_json({"type": "state", "status": "started", "session_id": sid})

            # K-013: @引用处理（先处理，避免后续 system prompt 重建）
            scenario_id, ref_block, structured_refs = _process_references(references, scenario_id)

            # 首字响应优化：发送 preparing 状态让前端即时反馈；
            # system prompt 构建移入子线程——不阻塞事件循环
            # （check_remote_sync 已非阻塞化，本地 IO 为毫秒级）
            await websocket.send_json({"type": "state", "status": "preparing"})

            def _build_prompt(sid_val: str) -> str:
                ctx = _build_scenario_context(sid_val)
                return build_system_prompt(scenario_context=ctx, purpose=session_purpose)

            system_prompt = await asyncio.to_thread(_build_prompt, scenario_id)
            # T-011: 三层交集白名单装配——TOOL_REGISTRY ∩ purpose(tools∪domains) ∩ rbac_visible_tools
            # （meta 工具 todo_write 常驻；全量用户 admin/tester 角色层不额外收窄；
            # T-982：purpose 按 domains 选领域子集，合并工具 action 粒度裁剪）
            # 工具白名单跟随配置，不锁死在会话创建时（purpose 定义变动即时生效）
            pdef_now = load_purpose(session_purpose) if session_purpose else None
            purpose_tools = list(pdef_now.tools if pdef_now else [])
            whitelist_tools = resolve_tools(
                purpose_tools=purpose_tools,
                user_roles=list(_ws_roles or []),
                purpose_domains=list(getattr(pdef_now, "domains", []) or []),
            )
            # M4：空白名单显式拒绝——绝不能回退全量（原 `or None` 会让空列表
            # 静默变成 ALL_TOOLS，防御纵深被破坏）
            if not whitelist_tools:
                await websocket.send_json({
                    "type": "error",
                    "message": "当前角色无可用的工具白名单（不允许 Agent 运行）",
                })
                continue
            runtime = AgentRuntime(llm, tools=whitelist_tools, max_turns=max_turns,
                                   purpose_name=session_purpose or "",
                                   user_roles=list(_ws_roles or []))
            # 辅助会话：父会话每轮快照前缀注入（主→辅单向；设计 §B4）
            parent_block = ""
            if session_kind == "aux" and parent_sid:
                parent_block, new_fp = _parent_snapshot(sm, parent_sid, last_parent_fp)
                try:
                    sm.set_meta_fields(sid, last_parent_fp=new_fp)
                except Exception:
                    pass
            ws_message = f"{parent_block}{ref_block}{message}" if (parent_block or ref_block) else message

            # T-1021: 事件发布到会话级总线（fan-out 多订阅者 + 当前 run 回放缓冲）——
            # 刷新/断连/第二标签页可 attach 续上实时流；本连接经 attach_live 订阅。
            # 顺序铁律：run_started → attach_live → events.subscribe（否则注册到订阅
            # 之间的事件会丢——发布进缓冲但不进本订阅者队列）。
            _BUS.run_started(sid, baseline_len=len(sm.load(sid) or []))
            loop = asyncio.get_running_loop()
            sub = _BUS.attach_live(sid)
            runtime.events.subscribe(
                lambda e: loop.call_soon_threadsafe(_BUS.publish, sid, e)
            )

            # T-402: 登记运行时供 cancel 端点查找
            _ACTIVE_RUNTIMES[sid] = runtime
            run_task = asyncio.create_task(
                asyncio.to_thread(runtime.run, system_prompt, ws_message, sm, sid,
                                  structured_refs or None)
            )
            _ACTIVE_RUNS[sid] = run_task  # K-015: 登记活跃 run（并发防护）
            try:
                heartbeat_tick = 0
                ws_broken = False  # K-xxx: WS 断连后不再取消 run——继续执行并落盘
                while True:
                    if run_task.done() and sub.queue.empty():
                        # 在飞投递防护：worker 线程的末事件经 call_soon_threadsafe
                        # 投递，future.set_result（run_task done）与回调入 ready 队存在
                        # 调度间隙——让出一轮再重查，防提前退出丢末事件（attach 中
                        # 的订阅者将收不到后续 done 广播）
                        await asyncio.sleep(0)
                        if run_task.done() and sub.queue.empty():
                            break
                    try:
                        event = await asyncio.wait_for(sub.queue.get(), timeout=0.2)
                        if not ws_broken:
                            try:
                                await websocket.send_json(event)
                                heartbeat_tick = 0  # 有事件输出，重置心跳
                            except Exception:
                                # 连接已死（异常类型随 uvicorn WS 实现而异）——转入 detach
                                ws_broken = True
                    except asyncio.TimeoutError:
                        heartbeat_tick += 1
                        if heartbeat_tick >= 50 and not ws_broken:  # 10 秒无事件（0.2s × 50）
                            # TCP 半开连接防护：定期 heartbeat 保持代理/NAT 不超时断连，
                            # 同时让前端知道后端仍活着；send 失败说明连接已死，转入 detach
                            try:
                                await websocket.send_json({"type": "heartbeat"})
                            except Exception:
                                ws_broken = True
                            heartbeat_tick = 0
                        continue
                    except (WebSocketDisconnect, RuntimeError):
                        # K-xxx: 页面 reload（vite dev 重启强制刷新）/断网——连接已死但 run 不取消：
                        # 继续执行并写完会话 JSONL，重连/刷新后恢复会话可读到完整回复。
                        # 主动打断走 POST /cancel/{sid}（T-402 真打断保留）。
                        # 事件丢弃（接收方已不存在），仅排空 queue 等 run 结束。
                        ws_broken = True
                        continue
                messages = None
                try:
                    messages = await run_task  # 运行异常在此抛出，进外层 except
                except Exception as e:
                    # T-1021: 异常也广播到总线——attach 中的连接收到 error 后退出订阅循环。
                    # 顺序：先 publish 再注销活跃标记——注销会让 attach 循环的终态兜底
                    # 条件（_run_in_progress=False）成立，若 error 还在飞会被误判为「事件已丢」
                    # 提前退订，订阅者永远收不到 error。
                    _BUS.publish(sid, {"type": "error", "message": str(e), "session_id": sid})
                    _ACTIVE_RUNS.pop(sid, None)
                    _ACTIVE_RUNTIMES.pop(sid, None)
                    raise

                # 首字响应优化：先推送 done（前端立即解除 loading），标题异步生成后单独推送。
                # T-1021: done 广播到总线（attach 中的连接经订阅队列收到，含 messages/stats
                # 供前端全量对齐）；本连接直发一份（事件循环已退出，不经订阅队列）。
                # 顺序：先 publish 再注销活跃标记（同 error 路径）——否则 done 跨 loop 投递
                # 还在飞时兜底条件成立，attach 订阅者提前退订错过 done。
                # K-xxx: WS 已断（detach 完成）时发送失败是预期——静默跳过，消息已落盘，恢复会话可见
                done_event = {
                    "type": "done",
                    "session_id": sid,
                    "messages": messages,
                    "stats": llm.get_stats(),
                    "title": "",
                }
                _BUS.publish(sid, done_event)
                _ACTIVE_RUNS.pop(sid, None)
                _ACTIVE_RUNTIMES.pop(sid, None)
                try:
                    await websocket.send_json(done_event)
                except Exception:
                    pass
            finally:
                # 兜底注销（正常路径已在 done/error 处先 publish 后 pop——
                # 顺序见上；此处幂等，防主循环异常退出时标记泄漏致 K-015 永拒）
                _ACTIVE_RUNS.pop(sid, None)
                _ACTIVE_RUNTIMES.pop(sid, None)

            # G4: 新会话标题异步生成（不阻塞 done 事件）
            if is_new_session and messages:
                async def _gen_title():
                    try:
                        title = await asyncio.to_thread(_generate_session_title, llm, messages)
                        if title:
                            sm.update_title(sid, title)
                            await websocket.send_json({
                                "type": "title_update",
                                "session_id": sid,
                                "title": title,
                            })
                    except Exception:
                        pass
                asyncio.create_task(_gen_title())

    except WebSocketDisconnect:
        # K-xxx: run 执行期间的断连已在事件推送循环内 detach 化（不取消、跑完落盘），
        # 走到这里的断连均处于 receive 等待阶段（无活跃 run）。以下取消逻辑仅作兑底
        # （防未来新增路径遗漏；正常情况下 run_task 已 done，取消为空转）。
        if 'run_task' in dir() and run_task and not run_task.done():
            run_task.cancel()
        if 'runtime' in dir() and runtime:
            try:
                runtime.cancel()
            except Exception:
                pass
        pass
    except Exception as e:
        # 记录错误到会话 JSONL（用于导出和排查）
        try:
            if 'sm' in dir() and 'sid' in dir() and sm and sid:
                sm.record_error(sid, str(e), type(e).__name__)
        except Exception:
            pass
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        # 恢复工作区上下文
        if _ws_ctx_token:
            reset_context_workspace(_ws_ctx_token)
