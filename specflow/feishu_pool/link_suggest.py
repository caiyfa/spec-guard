"""link_suggest.py — LLM 建边建议与防幻觉后处理（飞书知识图谱一期 T7）。

输入：材料正文（含图片替身文本拼装）× FR 锚点表（specstd.anchors 全量）
产出：候选边 [{src, dst, confidence, evidence, valid}] → 复核队列（review 服务）

三重防线（设计 §6.2，机器版硬约束）：
1. 幻觉 fr_id（不在 anchors 扫描结果）→ 直接丢弃，不进复核队列；
2. evidence 非材料原文子串 → valid=False（展示但不可确认）；
3. 已 rejected 的 (src,dst) → 不再重复建议（工作区级留痕）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from specflow.feishu_pool import facts

_MAX_ANCHORS_IN_PROMPT = 200

_PROMPT = """你是需求关联分析助手。给定一份材料正文和候选需求锚点（FR）目录，
判断材料内容与哪些 FR 存在实质关联（讨论/约定/约定了该需求的行为）。

候选 FR 目录（fr_id | 标题 | 模块/功能点）：
{anchor_catalog}

材料正文（id={src_id}）：
{material_text}

要求：
1. 只为有实质语义关联的 FR 提建议，宁缺毋滥
2. 每条建议给出：fr_id（必须来自上面目录，禁止编造）、confidence（0~1 关联程度）、
   evidence（材料原文中支撑该关联的原句摘录，必须是原文子串，禁止改写）
3. 严格输出 JSON：{{"links": [...]}}，不要输出任何其他内容"""


def _anchor_catalog(anchors: dict) -> str:
    """fr_id | title | module/feature 目录（超长截断）。"""
    lines = []
    for fr_id, info in sorted(anchors.items())[:_MAX_ANCHORS_IN_PROMPT]:
        module = getattr(info, "module", "") or ""
        feature = getattr(info, "feature", "") or ""
        title = getattr(info, "title", "") or ""
        loc = f"{module}/{feature}".strip("/")
        lines.append(f"{fr_id} | {title} | {loc}")
    return "\n".join(lines)


def _parse_llm_links(text: str) -> list[dict]:
    """解析 LLM 输出（容忍 ```json 围栏），失败返回空 list。"""
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if m:
        raw = m.group(1).strip()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    links = payload.get("links") if isinstance(payload, dict) else None
    if not isinstance(links, list):
        return []
    return [l for l in links if isinstance(l, dict) and l.get("fr_id")]


def suggest_links_for_material(src_id: str, material_text: str, anchors: dict,
                               llm, workspace_root: Path | None = None) -> list[dict]:
    """对单份材料/话题产出候选边（已过三重后处理）。

    Args:
        src_id: 材料/话题节点 id（fd:xxx / fm:xxx / tp:xxx）
        material_text: 材料正文（话题传 summary；含替身文本拼装产物）
        anchors: specstd.anchors.scan_anchors 结果 {fr_id: AnchorInfo}
        llm: LLMClient（chat(messages) -> {"content": str}）
        workspace_root: 给定则启用 rejected 过滤（防重复建议）

    Returns:
        [{src, dst, confidence, evidence, valid}]（幻觉 fr_id 已丢弃）
    """
    if not material_text.strip() or not anchors:
        return []
    try:
        resp = llm.chat([{"role": "user", "content": _PROMPT.format(
            anchor_catalog=_anchor_catalog(anchors),
            src_id=src_id, material_text=material_text)}])
        raw_links = _parse_llm_links(str(resp.get("content", "")))
    except Exception:
        return []

    out: list[dict] = []
    for rl in raw_links:
        fr_id = str(rl.get("fr_id", ""))
        # 防线 1：幻觉 fr_id 丢弃
        if fr_id not in anchors:
            continue
        # 防线 3：已拒绝不再建议
        if workspace_root is not None and facts.is_rejected(
                workspace_root, src_id, fr_id):
            continue
        evidence = str(rl.get("evidence", ""))
        try:
            confidence = float(rl.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        # 防线 2：evidence 必须是材料原文子串
        valid = bool(evidence) and evidence in material_text
        out.append({
            "src": src_id, "dst": fr_id,
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "evidence": evidence, "valid": valid,
        })
    return out
