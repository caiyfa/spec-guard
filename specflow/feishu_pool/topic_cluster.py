"""topic_cluster.py — LLM 话题聚类作业（飞书知识图谱一期 T6）。

输入：私有区群聊快照 chats/{chat_sha8}/{yyyymmdd}.md（[HH:MM] 发言人: 内容 行格式）
产出：候选话题写 _candidate_topics.yaml（私有区；复核确认后经 review 服务提升共享区）

id 稳定性铁律：图谱从文件派生而非重跑 LLM——新候选与已有话题归并
（同 chat_sha8 + 标题相似 + 同日 → 沿用旧 id），全新话题按当日 seq 分配。
LLM 输出非 JSON → 记 error 跳过该文件（诚实呈现不中断）。
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from specflow.feishu_pool.paths import pool_dirs

_MSG_RE = re.compile(r"^\[(\d{2}:\d{2})\]\s")
_TITLE_SIMILARITY = 0.6

# 最近一次聚类的错误清单（诚实呈现；模块级，调用方聚类后可读）
_LAST_ERRORS: list[str] = []

_PROMPT = """你是话题聚类助手。阅读以下群聊记录（每行格式：[HH:MM] 发言人: 内容），
把语义相关的消息聚成话题。要求：
1. 只聚类有实质讨论内容的消息（需求/方案/决策/问题）；闲聊（吃饭问候等）不聚类
2. 每个话题给出：title（≤20字）、summary（≤80字结论摘要）、
   msg_range（该话题首条与末条消息的时间戳，格式 ["[HH:MM]", "[HH:MM]"]）、
   participants_count（参与人数）
3. 若某话题是近期已有话题的延续讨论，附 continues: "已有话题id"（只能从下面清单选，禁止编造）：
{existing_topics}
4. 严格输出 JSON：{{"topics": [...]}}，不要输出任何其他内容

群聊记录（{day}）：
{content}"""


_NO_EXISTING = "（无）"


def _existing_topics_digest(existing: list[dict], chat_sha8: str) -> str:
    """近 7 天同群已有话题清单（T-926 演进链判定依据，注入 prompt）。"""
    rows = []
    for t in existing:
        if t.get("chat_sha8") != chat_sha8:
            continue
        summary = str(t.get("summary", ""))[:80]
        rows.append(f"- {t.get('id')} | {t.get('title')} | {summary}")
    return "\n".join(rows) if rows else _NO_EXISTING


def last_errors() -> list[str]:
    return list(_LAST_ERRORS)


def _candidate_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / "_candidate_topics.yaml"


def _load_candidates(specflow_emp_base: Path) -> list[dict]:
    path = _candidate_path(specflow_emp_base)
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    return [dict(t) for t in (raw.get("topics") or []) if isinstance(t, dict)]


def _save_candidates(specflow_emp_base: Path, topics: list[dict]):
    path = _candidate_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    topics = sorted(topics, key=lambda t: str(t.get("id", "")))
    path.write_text(
        yaml.safe_dump({"version": 1, "topics": topics},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _next_seq(existing: list[dict], chat_sha8: str, day: str) -> int:
    """当日该群已有话题的最大 seq + 1。"""
    import contextlib

    prefix = f"tp:{chat_sha8}-{day}-"
    seq = 0
    for t in existing:
        tid = str(t.get("id", ""))
        if tid.startswith(prefix):
            with contextlib.suppress(ValueError):
                seq = max(seq, int(tid.rsplit("-", 1)[1]))
    return seq + 1


def _count_messages(content: str, msg_range: list) -> int:
    """msg_range 时间窗内的消息行数（[HH:MM] 前缀行）。"""
    if not msg_range or len(msg_range) < 2:
        return 0
    start = str(msg_range[0]).strip("[]")
    end = str(msg_range[-1]).strip("[]")
    count = 0
    for line in content.splitlines():
        m = _MSG_RE.match(line.strip())
        if m and start <= m.group(1) <= end:
            count += 1
    return count


def _window_of(day: str, msg_range: list) -> list[str]:
    """['2026-08-07T14:00', '2026-08-07T14:01']（msg_range → ISO 窗）。"""
    if not msg_range or len(msg_range) < 2:
        return [day, day]
    d = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    return [f"{d}T{str(msg_range[0]).strip('[]')}",
            f"{d}T{str(msg_range[-1]).strip('[]')}"]


def _parse_llm_json(text: str) -> list[dict]:
    """解析 LLM 输出（容忍 ```json 围栏），失败抛 ValueError。"""
    raw = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
    if m:
        raw = m.group(1).strip()
    payload = json.loads(raw)
    topics = payload.get("topics") if isinstance(payload, dict) else None
    if not isinstance(topics, list):
        raise ValueError("LLM 输出缺少 topics 数组")
    return [t for t in topics if isinstance(t, dict) and t.get("title")]


def _merge_one(existing: list[dict], chat_sha8: str, day: str,
               candidate: dict) -> dict:
    """归并一条候选：同群 + 标题相似 + 同日 → 沿用旧 id 修订；否则分配新 id。"""
    for old in existing:
        if old.get("chat_sha8") != chat_sha8:
            continue
        if day not in str(old.get("id", "")):
            continue
        ratio = SequenceMatcher(
            None, str(old.get("title", "")),
            str(candidate.get("title", ""))).ratio()
        if ratio >= _TITLE_SIMILARITY:
            merged = dict(old)
            merged.update({k: v for k, v in candidate.items() if v not in (None, "", [])})
            merged["id"] = old["id"]
            return merged
    seq = _next_seq(existing, chat_sha8, day)
    candidate["id"] = f"tp:{chat_sha8}-{day}-{seq:02d}"
    return candidate


def cluster_chat_snapshots(specflow_emp_base: Path, llm,
                           days: list[str] | None = None,
                           chat_windows: dict[str, int] | None = None,
                           default_days: int = 0) -> list[dict]:
    """聚类私有区群聊快照，候选话题归并写回 _candidate_topics.yaml。

    分片语义：按「群 × 天」逐文件独立聚类（天然分片，单文件单次 LLM 调用，
    消息级由 prompt 指导忽略噪音）。

    Args:
        specflow_emp_base: .specflow/{emp} 根
        llm: LLMClient（chat(messages) -> {"content": str}）
        days: 只处理这些日期（None = 不限，叠加窗口过滤）
        chat_windows: T-946 按群配置 {chat_sha8: 窗口天数}——0=该群关闭
            话题生成；缺省键回退 default_days
        default_days: T-946 默认时效窗口（近 N 天的快照才聚类，过期数据
            不提取；<=0 = 不限，向后兼容）

    Returns:
        本次新增/修订的话题列表（含稳定 id）
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    global _LAST_ERRORS
    _LAST_ERRORS = []
    chats_root = pool_dirs(specflow_emp_base)["chats"]
    existing = _load_candidates(specflow_emp_base)
    produced: list[dict] = []
    if not chats_root.is_dir():
        return produced

    def _cutoff(win_days: int) -> str:
        """窗口下限日期（yyyymmdd）；win_days<=0 不限返回 ""。"""
        if win_days <= 0:
            return ""
        return (_date.today() - _td(days=win_days)).strftime("%Y%m%d")

    for chat_dir in sorted(chats_root.iterdir()):
        if not chat_dir.is_dir():
            continue
        chat_sha8 = chat_dir.name
        # T-946 窗口解析：显式配置（chat_windows 含键）<=0 = 关闭该群；
        # 未配置回退 default_days（<=0 = 不限，向后兼容）。
        if chat_windows and chat_sha8 in chat_windows:
            win = int(chat_windows[chat_sha8])
            if win <= 0:
                continue                  # 该群显式关闭话题生成
        else:
            win = default_days
        cutoff = _cutoff(win)
        for md_file in sorted(chat_dir.glob("*.md")):
            day = md_file.stem
            if cutoff and day < cutoff:
                continue                      # T-946：时效窗口外过期不提取
            if days and day not in days:
                continue
            content = md_file.read_text(encoding="utf-8")
            try:
                resp = llm.chat([{"role": "user", "content": _PROMPT.format(
                    day=day, content=content,
                    existing_topics=_existing_topics_digest(existing, chat_sha8))}])
                raw_topics = _parse_llm_json(str(resp.get("content", "")))
            except Exception as e:
                _LAST_ERRORS.append(f"{chat_sha8}/{day}: LLM 聚类失败: {e}")
                continue
            for rt in raw_topics:
                msg_range = rt.get("msg_range") or []
                candidate = {
                    "title": str(rt.get("title", "")),
                    "summary": str(rt.get("summary", "")),
                    "chat_sha8": chat_sha8,
                    "window": _window_of(day, msg_range),
                    "message_count": _count_messages(content, msg_range),
                    "participants_count": int(rt.get("participants_count") or 0),
                    "source": f"chats/{chat_sha8}/{day}.md",
                }
                # T-926：演进链——continues 必须存在于已有话题清单（防幻觉校验）
                cont = str(rt.get("continues") or "")
                if cont and any(t.get("id") == cont for t in existing):
                    candidate["continues"] = cont
                merged = _merge_one(existing, chat_sha8, day, candidate)
                if merged.get("id") not in {t.get("id") for t in existing}:
                    existing.append(merged)
                else:
                    existing = [merged if t.get("id") == merged.get("id") else t
                                for t in existing]
                produced.append(merged)

    _save_candidates(specflow_emp_base, existing)
    return produced
