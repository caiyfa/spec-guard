"""evals.export_case — 真实生产会话 → T-980 golden case 反向导出（T-1042）。

定位（知识库《2026-08-26-2037 评估架构体系设计》L1 样本层）：
生产会话抽样是 gold case 三类样本源之首。本模块把真实会话 JSONL 反向导出成
evals/harness.py 可直接回放的 golden case JSON：
  - llm_script   ← 会话里的 assistant 消息序列（含 tool_calls，按序回放）
  - tool_mocks   ← 会话里的 tool 结果行（同名工具多次调用按序取，末个重复）
  - expect       ← 默认给 tools_required（实际调用过的工具全集），可手工收紧

导出产物是**起点**而非终点：真实会话轨迹未必是「正确」轨迹，导出后须人工
评审（删掉错误步骤/收紧断言/标注预期 verdict），才成为回归集成员。这是
EDD「问题驱动补 case」的入口，不是自动转 gold——设计文档明确 case 只增不改。

边界：导出的 tool_mocks 让 harness 离线回放成为可能（mock 点=工具结果），
但会话里联网/DB 工具的结果也被一并 mock 固化——回放的是「当时的行为」，
不重新触网。符合 harness「禁止在 case 里调用联网/DB 工具」的纪律。
"""

from __future__ import annotations

import json
from pathlib import Path


def _resolve_current_tool(name: str) -> tuple[str, str]:
    """把任意形态工具名解析为 (合并基名, action)——runtime._tool_map 的真实键形态。

    runtime 的 _tool_map 键是合并基名（spec/scenario/draft），action 经
    arguments.action 派发；LLM 看到的工具名也是基名（spec(action=list) 只是
    文档/技能里的助记写法）。本函数把三种输入形态归一到这个真实形态：
      - legacy 逻辑 id（list_spec_files）→ ("spec", "list")  经 tool_meta.legacy_owner
      - 助记形态（spec(action=list)）  → ("spec", "list")
      - 已是基名（query_registry）       → ("query_registry", "")
    未识别时返回 (原名, "")——harness 回放会报「未注册工具」，诚实暴露。
    """
    # 助记形态 name(action=x)
    if "(" in name and name.endswith(")"):
        base = name.split("(")[0].strip()
        inner = name[name.index("(") + 1:-1]
        act = ""
        for part in inner.split(","):
            part = part.strip()
            if part.startswith("action="):
                act = part.split("=", 1)[1].strip().strip('"').strip("'")
        return base, act
    # legacy 逻辑 id → (基名, action)
    try:
        from mcp_server import server as _srv
        _srv.build_tool_modules()  # 幂等；填充 tool_meta._TOOL_META 供 legacy_owner
        from mcp_server.tools import tool_meta as tm
        owner = tm.legacy_owner(name)
    except Exception:
        owner = None
    if owner:
        return owner[0], owner[1]
    return name, ""


def export_golden_case(session_path: str | Path, case_id: str | None = None,
                       name: str | None = None,
                       task_prompt: str | None = None) -> dict:
    """把单个生产会话 JSONL 导出为 T-980 golden case dict。

    返回 dict（未落盘）——调用方决定写到哪里；缺字段时抛 ValueError。
    """
    path = Path(session_path)
    try:
        rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"会话文件解析失败: {path}: {e}") from e
    if not rows:
        raise ValueError(f"会话文件为空: {path}")

    # session_meta（首行非消息行）
    meta = next((o for o in rows if o.get("_type") == "session_meta"), {})
    sid = meta.get("session_id") or path.stem

    llm_script: list[dict] = []
    tool_mocks: dict[str, list[dict]] = {}
    first_user_content: str | None = None
    tools_called: list[str] = []

    for o in rows:
        rtype = o.get("_type") or o.get("role")
        if rtype == "user":
            if first_user_content is None and isinstance(o.get("content"), str):
                first_user_content = o["content"]
        elif rtype == "assistant":
            entry: dict = {"role": "assistant", "content": o.get("content") or ""}
            tcs = o.get("tool_calls") or []
            if tcs:
                norm_tcs = []
                for tc in tcs:
                    fn = tc.get("function") or {}
                    args = fn.get("arguments", "{}")
                    # harness 接受 arguments 为 dict（加载时归一化为 JSON 字符串）
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except json.JSONDecodeError:
                            args = {"_raw": args}
                    if not isinstance(args, dict):
                        args = {"_raw": args}
                    # 工具名归一到 runtime 真实形态：基名 + arguments.action（T-982 兼容）
                    base, act = _resolve_current_tool(fn.get("name", ""))
                    if act and "action" not in args:
                        args = dict(args, action=act)
                    norm_tcs.append({
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {"name": base, "arguments": args},
                    })
                    if base:
                        tools_called.append(base)
                entry["tool_calls"] = norm_tcs
            llm_script.append(entry)
        elif rtype == "tool":
            # tool 结果行：归到对应工具名下（经 assistant 的 tool_call_id 反查）
            pass  # 先收集 assistant，下面统一映射

    # tool 结果归到工具名：建 tool_call_id → tool_name 映射
    call_id_to_tool: dict[str, str] = {}
    for o in rows:
        if (o.get("_type") or o.get("role")) == "assistant":
            for tc in (o.get("tool_calls") or []):
                fn = tc.get("function") or {}
                call_id_to_tool[tc.get("id", "")] = fn.get("name", "")
    for o in rows:
        if (o.get("_type") or o.get("role")) == "tool":
            tool = call_id_to_tool.get(o.get("tool_call_id", ""), "")
            if not tool:
                continue
            base, _act = _resolve_current_tool(tool)  # 归一到基名（runtime._tool_map 键）
            content = o.get("content", "")
            # JSON 形态结果给 {"json": ...}，纯文本给 {"text": ...}
            spec: dict
            if isinstance(content, str) and content.strip().startswith(("{", "[")):
                try:
                    spec = {"json": json.loads(content)}
                except json.JSONDecodeError:
                    spec = {"text": content}
            else:
                spec = {"text": content if isinstance(content, str) else str(content)}
            # 同一基名的多次调用（含不同 action）按序累积——MockToolModule 按调用
            # 次数顺序返回，与 llm_script 的调用顺序一一对应
            tool_mocks.setdefault(base, []).append(spec)

    if not llm_script:
        raise ValueError(f"会话无 assistant 消息，无法导出 llm_script: {path}")

    case = {
        "id": case_id or f"GC-PROD-{sid}",
        "name": name or f"prod-{sid}",
        "description": (f"生产会话反向导出（{path.name}）。purpose="
                        f"{meta.get('purpose', '?')} workspace={meta.get('workspace', '?')}。"
                        "⚠ 导出即起点：轨迹未必正确，须人工评审收紧后才入回归集。"),
        "task_prompt": task_prompt or first_user_content or "（未提取到用户首条消息，需人工补）",
        "max_turns": max(8, len(llm_script) + 2),
        "allow_leftover": False,
        "_exported_from": str(path),
        "_export_note": "llm_script/tool_mocks 由真实会话反向导出；expect 默认 tools_required（实际工具全集），请人工收紧为轨迹断言。",
        "llm_script": llm_script,
        "tool_mocks": tool_mocks,
        "expect": [
            {"type": "tools_required", "expect": sorted(set(tools_called))},
        ],
    }
    return case


def export_to_file(session_path: str | Path, out_path: str | Path,
                   case_id: str | None = None, name: str | None = None,
                   task_prompt: str | None = None) -> Path:
    """导出并落盘为 golden case JSON 文件。"""
    case = export_golden_case(session_path, case_id=case_id, name=name,
                              task_prompt=task_prompt)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
