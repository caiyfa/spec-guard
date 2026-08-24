"""topic_cluster.py — LLM 话题聚类作业（飞书知识图谱一期 T6；T-948 schema v2；
T-991 schema v3：category 五分类 + priority 信号推导）。

输入：私有区群聊快照 chats/{chat_sha8}/{yyyymmdd}.md（[HH:MM] 发言人: 内容 行格式）
产出：话题卡片写 _topics.yaml（状态制单文件；T-948 取代候选/确认双轨：
status: draft|confirmed|rejected，卡片带 keywords/author/rev（乐观锁）/
agent_origin（agent 原稿，人工编辑不动它），全部变更追加 _topic_history.jsonl。
T-991 v3：每卡携带 category（chat|routine|requirement|test|solution 五分类，
闲聊从「prompt 丢弃」改为「分类保留」——默认视图过滤在前端，可审计）与
priority（high|normal|low，确定性信号推导初值，人工可改）。
tag-taxonomy（pv4）：keywords 收口到词表（specflow.feishu_pool.tag_registry，
与话题库同域 _tags.yaml）——prompt 注入既有标签清单引导复用，落卡前
canonicalize（别名→主标签），未知词自动入 pending 待人工收录/归并；
agent_origin 保留 LLM 原词（原稿不动）。卡片两级结构 = keywords（二级）×
词表 domain（一级，前端分组展示派生，不落卡——存量卡词表建档即归组）。

id 稳定性铁律：图谱从文件派生而非重跑 LLM——新候选与已有话题归并
（同 chat_sha8 + 标题相似 + 同日 → 沿用旧 id），全新话题按当日 seq 分配。
LLM 输出非 JSON → 记 error 跳过该文件（诚实呈现不中断）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import yaml

from specflow.feishu_pool import tag_registry as tr
from specflow.feishu_pool.paths import pool_dirs

_MSG_RE = re.compile(r"^\[(\d{2}:\d{2})\]\s")
_TITLE_SIMILARITY = 0.6

# prompt 版本（agent_origin 归因对比依据；改 prompt 语义时递增）
# pv3：T-991 五分类 rubric + priority_hint（闲聊保留为 chat 类，不再丢弃）
# pv4：tag-taxonomy 词表复用块（known_tags）注入聚类/分段/勾选三处 prompt
_PROMPT_VERSION = "pv4"

_STATUS_ENUM = ("draft", "confirmed", "rejected")
# T-991 schema v3：分类/优先级枚举（闲聊保留默认过滤——拍板③）
_CATEGORY_ENUM = ("chat", "routine", "requirement", "test", "solution")
_PRIORITY_ENUM = ("high", "normal", "low")
_SYSTEM_EDITOR = {"emp": "", "name": "system"}

# 最近一次聚类的错误清单（诚实呈现；模块级，调用方聚类后可读）
_LAST_ERRORS: list[str] = []

# T-991：五分类操作化定义（rubric）+ few-shot——封闭集分类可靠性取决于定义
# 清晰度（与测试维度受控词表同理）；三处 prompt 共用。
_CATEGORY_RUBRIC = """category 必须从以下封闭枚举中选（操作化定义 + 示例）：
- chat：闲聊寒暄（吃饭/问候/段子/表情刷屏），无任何工作信息。示例：「中午吃啥」「早上好」
- routine：日常协作沟通（排期/通知/状态同步/找人），有工作信息但无需求/方案/测试实质。示例：「周四上线前把材料补齐」「测试环境今天重启」
- requirement：需求相关（新需求讨论/需求变更/口径确认/优先级争议）。示例：「绩效阈值要从 3.5 调到 3.8」
- test：测试相关（bug 现象/用例讨论/测试数据/验证结论/环境问题）。示例：「这个 bug 在 SIT 复现了，返回码 500」
- solution：方案相关（技术方案/设计讨论/架构决策/实现路径）。示例：「分库分表按 hash 还是范围切」"""


def derive_priority(category: str, message_count: int, participants_count: int,
                    chat_kind: str = "", llm_hint: str = "") -> str:
    """T-991 priority 初值：确定性信号推导（非纯 LLM 拍脑袋）。

    信号与权重：消息量（≥30 条 +1 / ≥10 条 +0.5）、参与人数（≥5 人 +1 /
    ≥3 人 +0.5）、来源群类型（测试/产研/用户群 +0.5，T-990 kind）、分类语义
    （requirement/test/solution +0.5）、LLM 提示（high +0.5 / low -0.5 微调）。
    闲聊恒 low；阈值：≥2 → high，≥1 → normal，否则 low。
    人工可改（edit_candidate）；T-992 关联 FR 的 P0/P1 信号纳入后可再校准。
    """
    if category == "chat":
        return "low"
    score = 0.0
    mc = int(message_count or 0)
    pc = int(participants_count or 0)
    score += 1.0 if mc >= 30 else (0.5 if mc >= 10 else 0.0)
    score += 1.0 if pc >= 5 else (0.5 if pc >= 3 else 0.0)
    if str(chat_kind) in ("测试", "产研", "用户"):
        score += 0.5
    if category in ("requirement", "test", "solution"):
        score += 0.5
    score += {"high": 0.5, "normal": 0.0, "low": -0.5}.get(str(llm_hint), 0.0)
    return "high" if score >= 2.0 else ("normal" if score >= 1.0 else "low")


def _norm_category(v) -> str:
    """LLM 输出/存量数据 → 合法分类（非法值保守归 routine，诚实不抛）。"""
    s = str(v or "")
    return s if s in _CATEGORY_ENUM else "routine"


def _norm_priority(v) -> str:
    s = str(v or "")
    return s if s in _PRIORITY_ENUM else "normal"


_PROMPT = """你是话题聚类助手。阅读以下群聊记录（每行格式：[HH:MM] 发言人: 内容，
每行开头的序号是该消息的行号），把语义相关的消息聚成话题。要求：
1. 所有话题都要聚（含闲聊——闲聊聚成 category=chat 的话题卡，供过滤与噪声统计，
   不要丢弃）；跨天延续的同一讨论聚为同一个话题
2. 每个话题给出：title（≤20字）、summary（≤80字结论摘要）、
   keywords（2~5个关键词——优先从下方既有标签清单选取，语义相同/相近
   即用清单原词，禁止另造近义词；括号内为别名，命中别名请输出主标签名；
   清单没有匹配再新造）、msg_lines（该话题覆盖的消息行号列表，
   行号从 1 起始，如 [1,2,3]）、participants_count（参与人数）、
   priority_hint（high|normal|low，你对重要程度的直觉判断）
   既有标签清单：
{known_tags}
3. {category_rubric}
4. 若某话题是近期已有话题的延续讨论，附 continues: "已有话题id"（只能从下面清单选，禁止编造）：
{existing_topics}
5. 严格输出 JSON：{{"topics": [...]}}，不要输出任何其他内容

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


_NO_TAGS = "（空——可自行新造，新词将入词表待收录区）"


def _tag_canonicalizer(mroot: Path):
    """词表加载 + (digest, canonicalize, flush)——批量路径一次加载、末尾落盘。

    digest：prompt 注入的既有标签清单（空词表给占位行，诚实告知可新造）；
    canonicalize：词列表 → 主标签列表（未知词暂存内存）；flush：暂存新词
    统一入 pending 落盘（无新词不写盘；自动注册不落历史——tag_registry 决策）。
    """
    reg = tr.load_registry(mroot)
    pending_new: list[str] = []

    def _canon(words) -> list[str]:
        canon, unknown = tr.canonicalize(reg, words)
        pending_new.extend(unknown)
        return canon

    def _flush(source: str):
        if tr.register_pending(reg, pending_new, source=source):
            tr.save_registry(mroot, reg)

    return tr.known_tags_digest(reg) or _NO_TAGS, _canon, _flush


def last_errors() -> list[str]:
    return list(_LAST_ERRORS)


def _candidate_path(specflow_emp_base: Path) -> Path:
    """话题库路径（T-948：_topics.yaml 状态制单文件，取代旧候选文件）。"""
    return pool_dirs(specflow_emp_base)["root"] / "_topics.yaml"


def _legacy_candidate_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / "_candidate_topics.yaml"


def _history_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / "_topic_history.jsonl"


class RevConflict(Exception):
    """乐观锁冲突（base_rev 萻后于卡片 rev）；topic 属性携带最新卡片供 409 载荷。"""

    def __init__(self, topic: dict):
        self.topic = topic
        super().__init__("rev_conflict")


def _normalize_card(t: dict) -> dict:
    """卡片字段归一化：T-948 新字段补默认（存量卡 status=draft/rev=1/keywords=[]）；
    T-991 v3 补 category（存量卡保守归 routine）/priority（normal），非法值归默认。"""
    t.setdefault("status", "draft")
    t.setdefault("rev", 1)
    t.setdefault("keywords", [])
    t.setdefault("category", "routine")
    t.setdefault("priority", "normal")
    if t.get("status") not in _STATUS_ENUM:
        t["status"] = "draft"
    t["category"] = _norm_category(t.get("category"))
    t["priority"] = _norm_priority(t.get("priority"))
    return t


def _load_candidates(specflow_emp_base: Path) -> list[dict]:
    """读话题库（_topics.yaml 优先；回退旧 _candidate_topics.yaml 兼容迁移）。"""
    path = _candidate_path(specflow_emp_base)
    if not path.is_file():
        path = _legacy_candidate_path(specflow_emp_base)
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    return [_normalize_card(dict(t)) for t in (raw.get("topics") or [])
            if isinstance(t, dict)]


def _save_candidates(specflow_emp_base: Path, topics: list[dict]):
    path = _candidate_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    topics = sorted(topics, key=lambda t: str(t.get("id", "")))
    path.write_text(
        yaml.safe_dump({"version": 1, "topics": topics},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _append_history(specflow_emp_base: Path, topic_id: str,
                    editor: dict | None, action: str,
                    base_rev: int | None = None, changes: dict | None = None):
    """编辑历史追加写（append-only 留痕；多用户协作可追溯）。"""
    rec = {"at": datetime.now().isoformat(timespec="seconds"),
           "topic_id": topic_id,
           "editor": editor or _SYSTEM_EDITOR,
           "action": action,
           "base_rev": base_rev,
           "changes": changes or {}}
    path = _history_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def list_history(specflow_emp_base: Path, topic_id: str,
                material_base: Path | None = None) -> list[dict]:
    """某卡片的历史（倒序，最新在前；缺失返回空 list）。T-949：随 material_base。"""
    path = _history_path(_mroot(specflow_emp_base, material_base))
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict) and rec.get("topic_id") == topic_id:
            out.append(rec)
    out.reverse()
    return out


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


def _llm_content(resp) -> str:
    """LLM 响应内容提取（T-955b 根因修复：LLMClient.chat 返回 (message, usage)
    tuple，而测试 mock 返回 dict——两者兼容；此前生产环境所有聚类/分段/regen
    因此 AttributeError 500，自动聚类从上线起就从未产出过话题）。"""
    if isinstance(resp, tuple):
        resp = resp[0] if resp else {}
    return str((resp or {}).get("content", ""))


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
                           default_days: int = 0,
                           chat_kinds: dict[str, str] | None = None) -> list[dict]:
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
        chat_kinds: T-991 按群类型标签 {chat_sha8: kind}（priority 信号之一；
            缺省键 = 未标注，不加分）

    Returns:
        本次新增/修订的话题列表（含稳定 id）
    """
    from datetime import date as _date
    from datetime import timedelta as _td

    global _LAST_ERRORS
    _LAST_ERRORS = []
    chats_root = pool_dirs(specflow_emp_base)["chats"]
    existing = _load_candidates(specflow_emp_base)
    # tag-taxonomy：词表随话题库同域（生产=共享材料区，见 _cluster_once 传参）
    tag_digest, _canon_tags, _flush_tags = _tag_canonicalizer(specflow_emp_base)
    kinds = chat_kinds or {}
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
            try:
                content, line_ids = _load_day_source(
                    specflow_emp_base, chat_sha8, day)
            except FileNotFoundError as e:
                _LAST_ERRORS.append(f"{chat_sha8}/{day}: {e}")
                continue
            try:
                resp = llm.chat([{"role": "user", "content": _PROMPT.format(
                    day=day, content=_numbered_lines(content),
                    existing_topics=_existing_topics_digest(existing, chat_sha8),
                    category_rubric=_CATEGORY_RUBRIC, known_tags=tag_digest)}])
                raw_topics = _parse_llm_json(_llm_content(resp))
            except Exception as e:
                _LAST_ERRORS.append(f"{chat_sha8}/{day}: LLM 聚类失败: {e}")
                continue
            for rt in raw_topics:
                msg_range = rt.get("msg_range") or []
                keywords = _canon_tags(
                    [str(k) for k in (rt.get("keywords") or []) if str(k)])
                ids = _msg_lines_to_ids(rt.get("msg_lines"), line_ids)
                category = _norm_category(rt.get("category"))
                msg_count = (len(ids) if ids
                             else _count_messages(content, msg_range))
                participants = int(rt.get("participants_count") or 0)
                candidate = {
                    "title": str(rt.get("title", "")),
                    "summary": str(rt.get("summary", "")),
                    "keywords": keywords,
                    "category": category,
                    "priority": derive_priority(
                        category, msg_count, participants,
                        chat_kind=str(kinds.get(chat_sha8, "")),
                        llm_hint=str(rt.get("priority_hint") or "")),
                    "chat_sha8": chat_sha8,
                    "window": _window_of(day, msg_range),
                    "message_count": msg_count,
                    "participants_count": participants,
                    "source": f"chats/{chat_sha8}/{day}.md",
                    "status": "draft",
                    "author": dict(_SYSTEM_EDITOR),
                    "rev": 1,
                    "agent_origin": _make_agent_origin(rt, llm),
                }
                if ids:
                    candidate["message_ids"] = ids
                # T-926：演进链——continues 必须存在于已有话题清单（防幻觉校验）
                cont = str(rt.get("continues") or "")
                if cont and any(t.get("id") == cont for t in existing):
                    candidate["continues"] = cont
                old_by_id = {t.get("id"): t for t in existing}
                merged = _merge_one(existing, chat_sha8, day, candidate)
                is_new = merged.get("id") not in old_by_id
                if is_new:
                    existing.append(merged)
                else:
                    # T-991：聚类修订沿用旧卡 priority（初值语义——人工改过
                    # 不被重算覆盖；category 属 agent 语义随修订更新）
                    old_priority = (old_by_id.get(merged.get("id")) or {}).get("priority")
                    if old_priority:
                        merged["priority"] = old_priority
                    existing = [merged if t.get("id") == merged.get("id") else t
                                for t in existing]
                _append_history(
                    specflow_emp_base, str(merged.get("id")), _SYSTEM_EDITOR,
                    "create" if is_new else "cluster", base_rev=int(merged.get("rev") or 1),
                    changes={"agent_origin": {"from": None,
                                             "to": merged.get("agent_origin")}})
                produced.append(merged)

    _save_candidates(specflow_emp_base, existing)
    _flush_tags("llm")                        # 本批新词统一入词表待收录
    return produced


# ══════════════════════════════════════════════════════════
# T-947：话题人工介入工作流（草案 / 勾选提交 / 单卡编辑 / 单卡重生成）
# ══════════════════════════════════════════════════════════

_DRAFT_PROMPT = """你是话题分段助手。阅读以下群聊记录（每行格式：[MM-DD HH:MM] 发言人: 内容，
每行开头的序号是该消息的行号），把语义相关的消息聚成候选话题段。要求：
1. 所有话题段都要聚（含闲聊——闲聊聚成 category=chat 的段，供过滤与噪声统计）；
   跨天延续的同一讨论应聚为**同一个话题段**（不要按天拆开）
2. 每个话题段给出：title（≤20字）、summary（≤80字结论摘要）、
   keywords（2~5个关键词——优先从下方既有标签清单选取，语义相同/相近
   即用清单原词，禁止另造近义词；括号内为别名，命中别名请输出主标签名；
   清单没有匹配再新造）、msg_lines（该段覆盖的消息行号列表，
   行号从 1 起始，如 [1,2,3]）、participants_count（参与人数）、
   priority_hint（high|normal|low，你对重要程度的直觉判断）
   既有标签清单：
{known_tags}
3. {category_rubric}
4. 严格输出 JSON：{{"topics": [...]}}，不要输出任何其他内容

群聊记录（{day}）：
{content}"""


def _load_day_source(emp_base: Path, chat_sha8: str,
                     day: str) -> tuple[str, list[str] | None]:
    """读当日聚类素材（T-948 pv2：JSONL 事实源优先）。

    返回 (content, line_ids)：line_ids 与 md 消息行一一对应（1-based 行号
    → message_id 映射，msg_lines 换算依据）；无 JSONL（存量 md）回退直读
    md，line_ids=None（msg_lines 失效，走 msg_range 兼容路径）。
    """
    from specflow.feishu_pool import chat_store
    chats_root = pool_dirs(emp_base)["chats"]
    jsonl = chats_root / chat_sha8 / f"{day}.jsonl"
    md = chats_root / chat_sha8 / f"{day}.md"
    if jsonl.is_file():
        text, _imgmap, line_ids = chat_store.render_md_from_jsonl(jsonl)
        return text, line_ids
    if md.is_file():
        return md.read_text(encoding="utf-8"), None
    raise FileNotFoundError(f"快照不存在: chats/{chat_sha8}/{day}.md")


def _load_window_source(emp_base: Path, chat_sha8: str,
                        days: list[str]) -> tuple[str, list[str], list[str], list[str]]:
    """T-951c：多日窗口拼接（介入工作台跨天话题）。

    仅消费有 JSONL 事实源的日子（无快照日跳过——诚实，不虚构）；
    行格式 "[MM-DD HH:MM] 发言人: 内容"（带日期，跨日不歧义）；
    返回 (行文本, line_ids, line_ts, used_days)：行号跨日连续，msg_lines
    锚定全窗口；line_ts 供 window 取真实首末时间戳；used_days 仅含实际
    有快照的日子（卡片 days 字段来源——跳过日不记入，regen 不拼接空日）。
    """
    from specflow.feishu_pool import chat_store
    chats_root = pool_dirs(emp_base)["chats"]
    lines: list[str] = []
    line_ids: list[str] = []
    line_ts: list[str] = []
    used_days: list[str] = []
    for day in sorted(set(days or [])):
        jsonl = chats_root / chat_sha8 / f"{day}.jsonl"
        if not jsonl.is_file():
            continue
        day_rows = 0
        for r in sorted(chat_store.load_chat_jsonl(jsonl),
                        key=chat_store._sort_key):
            mmdd = str(r.get("ts") or "")[5:10] or "??-??"
            hhmm = str(r.get("ts") or "")[11:16] or "??:??"
            sender = str(r.get("sender_name") or r.get("sender_id") or "?")
            mtype = str(r.get("msg_type") or "text")
            body = (str(r.get("content") or "") if mtype == "text"
                    else f"[{mtype}消息]")
            lines.append(f"[{mmdd} {hhmm}] {sender}: {body}")
            line_ids.append(str(r.get("message_id") or ""))
            line_ts.append(str(r.get("ts") or ""))
            day_rows += 1
        if day_rows:
            used_days.append(day)
    if not lines:
        raise FileNotFoundError(
            f"窗口内无 JSONL 快照: chats/{chat_sha8}/{','.join(sorted(days or []))}")
    return "\n".join(lines), line_ids, line_ts, used_days


def _fallback_day_content(mroot: Path, chat_sha8: str, day: str) -> str:
    """单日 md 视图读取（regen 兼容路径：存量卡无 days/JSONL）。"""
    chats_root = pool_dirs(mroot)["chats"]
    md_file = chats_root / chat_sha8 / f"{day}.md"
    if not md_file.is_file():
        raise FileNotFoundError(f"原文不存在: chats/{chat_sha8}/{day}.md")
    return md_file.read_text(encoding="utf-8")


def _msg_lines_to_ids(msg_lines, line_ids: list[str] | None) -> list[str]:
    """LLM 行号列表 → message_id 列表（越界/无映射行诚实丢弃）。"""
    if not msg_lines or not line_ids:
        return []
    out = []
    for ln in msg_lines:
        try:
            idx = int(ln) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(line_ids) and line_ids[idx]:
            out.append(line_ids[idx])
    return out


_REGEN_PROMPT = """你是话题提炼助手。阅读以下群聊记录片段（{day}，时间窗 {window}），
只针对该时间窗重新提炼一个话题。要求给出：
title（≤20字）、summary（≤80字结论摘要）、category（五分类）、
priority_hint（high|normal|low 直觉判断）、
msg_range（该话题首条与末条消息的时间戳，格式 ["[HH:MM]", "[HH:MM]"]）、
participants_count（参与人数）。
{category_rubric}
严格输出 JSON：{{"topics": [...]}}，不要输出任何其他内容。

群聊记录片段：
{content}"""


def _draft_path(specflow_emp_base: Path) -> Path:
    return pool_dirs(specflow_emp_base)["root"] / "_topic_drafts.yaml"


def _load_drafts(specflow_emp_base: Path) -> dict[str, list[dict]]:
    path = _draft_path(specflow_emp_base)
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    drafts = raw.get("drafts") or {}
    return {str(k): [dict(s) for s in v if isinstance(s, dict)]
            for k, v in drafts.items() if isinstance(v, list)}


def _save_drafts(specflow_emp_base: Path, drafts: dict[str, list[dict]]):
    path = _draft_path(specflow_emp_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": 1, "drafts": drafts},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _numbered_lines(content: str) -> str:
    """聚类用行号视图：「N. [HH:MM] ...」逐行编号（msg_lines 锚定依据）。

    仅用于塞 prompt；计数/回退逻辑仍用原始 content（行首正则不受污染）。
    """
    return "\n".join(f"{i}. {line}"
                    for i, line in enumerate(content.splitlines(), 1))


def _make_agent_origin(rt: dict, llm=None) -> dict:
    """从 LLM 原始输出构造 agent_origin（T-948 R8：agent 原稿，人工编辑不动）。"""
    return {
        "title": str(rt.get("title", "")),
        "summary": str(rt.get("summary", "")),
        "keywords": [str(k) for k in (rt.get("keywords") or []) if str(k)],
        "category": _norm_category(rt.get("category")),
        "model": str(getattr(llm, "model_id", "") or getattr(llm, "model", "") or ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "prompt_version": _PROMPT_VERSION,
    }


def draft_chat_segments(emp_base: Path, llm, chat_sha8: str,
                        days: list[str],
                        material_base: Path | None = None,
                        chat_kind: str = "") -> list[dict]:
    """对单群多日窗口跑 LLM 分段，返回段列表并落 _topic_drafts.yaml（不动话题库）。

    T-948：chats/话题库读材料区（material_base），草案落私有区。
    T-951c：days 列表（单日传 [day]）；多日时行带 [MM-DD HH:MM] 日期前缀，
    msg_lines 跨日行号锚定，window 取真实 ts（跨零点话题正确表达），
    段附 days 字段（跨日卡标识，regen/展示用）。
    T-991：段带 category/priority（priority 按信号推导，chat_kind 参与）。
    """
    mroot = _mroot(emp_base, material_base)
    single_day = days[0] if len(days) == 1 else None
    if single_day:
        content, line_ids = _load_day_source(mroot, chat_sha8, single_day)
        line_ts: list[str] | None = None
        used_days = [single_day]
    else:
        content, ids, line_ts, used_days = _load_window_source(
            mroot, chat_sha8, days)
        line_ids = ids
    tag_digest, _canon_tags, _flush_tags = _tag_canonicalizer(mroot)
    resp = llm.chat([{"role": "user", "content": _DRAFT_PROMPT.format(
        day="~".join(used_days), content=_numbered_lines(content),
        category_rubric=_CATEGORY_RUBRIC, known_tags=tag_digest)}])
    raw_topics = _parse_llm_json(_llm_content(resp))
    existing = _load_candidates(mroot)
    segments: list[dict] = []
    for rt in raw_topics:
        msg_range = rt.get("msg_range") or []
        ids = _msg_lines_to_ids(rt.get("msg_lines"), line_ids)
        # T-951c：跨日窗口时 window 取首末真实 ts（多日单日均适用——
        # 单日路径无 line_ts 时回退 _window_of 拼接）
        if ids and line_ts:
            idxs = [i for i in range(len(line_ids)) if line_ids[i] in set(ids)]
            window = [line_ts[min(idxs)], line_ts[max(idxs)]] if idxs \
                else _window_of(used_days[0], msg_range)
        else:
            window = _window_of(used_days[0], msg_range)
        category = _norm_category(rt.get("category"))
        msg_count = (len(ids) if ids
                     else _count_messages(content, msg_range))
        participants = int(rt.get("participants_count") or 0)
        seg = {
            "title": str(rt.get("title", "")),
            "summary": str(rt.get("summary", "")),
            "keywords": _canon_tags(
                [str(k) for k in (rt.get("keywords") or []) if str(k)]),
            "category": category,
            "priority": derive_priority(
                category, msg_count, participants, chat_kind=chat_kind,
                llm_hint=str(rt.get("priority_hint") or "")),
            "chat_sha8": chat_sha8,
            "window": window,
            "message_count": msg_count,
            "participants_count": participants,
            "source": f"chats/{chat_sha8}/{used_days[0]}.md",
            "agent_origin": _make_agent_origin(rt, llm),
        }
        if len(used_days) > 1:
            seg["days"] = used_days           # 跨日卡标识（单日卡不携带）
        if ids:
            seg["message_ids"] = ids
        cont = str(rt.get("continues") or "")
        if cont and any(t.get("id") == cont for t in existing):
            seg["continues"] = cont
        segments.append(seg)
    drafts = _load_drafts(emp_base)
    # T-951c：草案键携带窗口标识（单日 "sha8/day"；多日 "sha8/d1~d2"）
    drafts[f"{chat_sha8}/{'~'.join(used_days)}"] = segments
    _save_drafts(emp_base, drafts)
    _flush_tags("llm")
    return segments


# T-1002：勾选原文生成话题的 prompt（行格式与 _DRAFT_PROMPT 一致，
# 但范围是用户已勾选的消息子集，不再要求全量聚类；附加上下文来自用户补充）
_COMPOSE_PROMPT = """你是话题归纳助手。用户从群聊记录中勾选了以下消息，认为它们属于同一个话题。
请根据这些消息归纳一个话题卡。要求：
1. 给出：title（≤20字）、summary（≤80字结论摘要）、keywords（2~5个关键词——
   优先从下方既有标签清单选取，语义相同/相近即用清单原词，命中别名输出
   主标签名，清单没有再新造）、category（五分类之一）、
   priority_hint（high|normal|low 重要程度直觉）
2. {category_rubric}
3. 严格输出 JSON：{{"topics": [...]}}（只输出一个话题），不要输出任何其他内容
既有标签清单：
{known_tags}
{extra_block}
勾选的消息（{day}）：
{content}"""


def compose_topic_from_messages(emp_base: Path, llm, chat_sha8: str,
                                message_ids: list[str],
                                days: list[str],
                                title: str = "", summary: str = "",
                                keywords: list[str] | None = None,
                                extra_context: str = "",
                                material_base: Path | None = None,
                                chat_kind: str = "") -> dict:
    """T-1002：按勾选原文消息生成单个话题草案（人工指定范围 + 可补充上下文）。

    message_ids 全部定位到其所属日（JSONL 事实源），任一 id 找不到 → KeyError
    （路由 404，防静默丢关联）；找不到的 md 回退快照（无 JSONL 行）由调用方
    前端拦截（伪 id 不入）。title/summary/keywords 为空字段交 LLM 补全
    （extra_context 作为附加上下文拼入 prompt——用户纠正归类/补充背景）。
    草案落 _topic_drafts.yaml（与 AI 分段同键位），不动话题库。
    """
    from specflow.feishu_pool import chat_store
    if not message_ids or not all(str(m).strip() for m in message_ids):
        raise ValueError("message_ids 需至少一条非空消息 id（话题不能零关联）")
    mroot = _mroot(emp_base, material_base)
    chats_root = pool_dirs(mroot)["chats"]
    # 逐日收集行：id → 行（message_id 所属日由事实源反查，不信任调用方断言）
    wanted = {str(m) for m in message_ids}
    found: dict[str, dict] = {}
    for day in sorted(set(days or [])):
        jsonl = chats_root / chat_sha8 / f"{day}.jsonl"
        if not jsonl.is_file():
            continue
        for r in chat_store.load_chat_jsonl(jsonl):
            mid = str(r.get("message_id") or "")
            if mid in wanted:
                found[mid] = dict(r, _day=day)
    missing = wanted - set(found)
    if missing:
        raise KeyError(f"消息不在快照中（可能已撤回或需更新本群）: {sorted(missing)}")
    rows = sorted(found.values(), key=chat_store._sort_key)
    used_days = sorted({str(r["_day"]) for r in rows})
    # prompt 行（沿用多日窗口格式——带日期前缀跨日不歧义；非文本行如实标注类型）
    lines: list[str] = []
    for r in rows:
        ts = str(r.get("ts") or "")
        sender = str(r.get("sender_name") or r.get("sender_id") or "?")
        mtype = str(r.get("msg_type") or "text")
        body = (str(r.get("content") or "") if mtype == "text"
                else f"[{mtype}消息]")
        lines.append(f"[{ts[5:10] or '??-??'} {ts[11:16] or '??:??'}] {sender}: {body}")
    extra_block = (f"\n用户补充说明（作为归纳的重要参考）：\n{extra_context.strip()}\n"
                   if extra_context.strip() else "")
    tag_digest = tr.known_tags_digest(tr.load_registry(mroot)) or _NO_TAGS
    rt: dict = {}
    if not (title and summary and keywords):
        resp = llm.chat([{"role": "user", "content": _COMPOSE_PROMPT.format(
            day="~".join(used_days), content="\n".join(lines),
            category_rubric=_CATEGORY_RUBRIC, known_tags=tag_digest,
            extra_block=extra_block)}])
        raw = _parse_llm_json(_llm_content(resp))
        rt = raw[0] if raw else {}
    category = _norm_category(rt.get("category"))
    participants = len({str(r.get("sender_id") or r.get("sender_name") or "")
                       for r in rows} - {""})
    # 词表归一：手工关键词 source=human，LLM 补全 source=llm（pending 溯源）
    kws = tr.canonicalize_and_register(
        mroot,
        [str(k) for k in (keywords if keywords else (rt.get("keywords") or []))
         if str(k)],
        source="human" if keywords else "llm")
    seg = {
        "title": str(title or rt.get("title", "")),
        "summary": str(summary or rt.get("summary", "")),
        "keywords": kws,
        "category": category,
        "priority": derive_priority(
            category, len(rows), participants, chat_kind=chat_kind,
            llm_hint=str(rt.get("priority_hint") or "")),
        "chat_sha8": chat_sha8,
        "window": [str(rows[0].get("ts") or ""), str(rows[-1].get("ts") or "")],
        "message_count": len(rows),
        "participants_count": participants,
        "source": f"chats/{chat_sha8}/{used_days[0]}.md",
        "agent_origin": _make_agent_origin(rt, llm),
    }
    if len(used_days) > 1:
        seg["days"] = used_days
    seg["message_ids"] = [str(r.get("message_id")) for r in rows]
    drafts = _load_drafts(emp_base)
    key = f"{chat_sha8}/{'~'.join(used_days)}"
    drafts.setdefault(key, []).append(seg)
    _save_drafts(emp_base, drafts)
    return seg


def _mroot(emp_base: Path, material_base: Path | None) -> Path:
    """T-949：材料/话题库所在根——material_base 优先（共享材料区），
    None 回退私有区（向后兼容单用户模式）。"""
    return Path(material_base) if material_base else emp_base


def list_drafts(emp_base: Path) -> dict[str, list[dict]]:
    """读全部草案 {sha8/day: [段…]}（空文件返回 {}）。"""
    return _load_drafts(emp_base)


def commit_drafts(emp_base: Path, sha8: str, day: str,
                  picked: list[dict], author: dict | None = None,
                  material_base: Path | None = None,
                  days: list[str] | None = None) -> list[dict]:
    """用户勾选的段 → 话题库：旧卡片标记 rejected（留痕不删除），
    新卡片带 v2 字段（status/author/rev/agent_origin）写入 _topics.yaml。

    T-949：话题库随 material_base（共享材料区）；草案读私有区。
    T-951c：days（多日窗口）非空时清理窗口内**各日**旧卡（跨天话题
    不残留单日旧卡）；卡 id 仍以首日（day）为 seq 锚。
    """
    author = author or _SYSTEM_EDITOR
    mroot = _mroot(emp_base, material_base)
    existing = _load_candidates(mroot)
    clear_days = sorted(set([day] + list(days or [])))
    clear_prefixes = tuple(f"tp:{sha8}-{d}-" for d in clear_days)
    for t in existing:
        if str(t.get("id", "")).startswith(clear_prefixes) \
                and t.get("status") != "rejected":
            _append_history(mroot, str(t.get("id")), author, "reject",
                            base_rev=int(t.get("rev") or 1),
                            changes={"status": {"from": t.get("status"),
                                                "to": "rejected"}})
            t["status"] = "rejected"
    existing = list(existing)                     # 全部保留（状态制）
    produced: list[dict] = []
    for seg in picked:
        if not isinstance(seg, dict):
            continue
        candidate = dict(seg)
        candidate["chat_sha8"] = sha8
        candidate.setdefault("source", f"chats/{sha8}/{day}.md")
        candidate["status"] = "draft"
        candidate["author"] = dict(author)
        candidate["rev"] = 1
        candidate.setdefault("keywords", [])
        if candidate["keywords"]:
            # tag-taxonomy 兜底：旧草案/外部传入的词过词表归一（新生段已归一）
            candidate["keywords"] = tr.canonicalize_and_register(
                mroot, candidate["keywords"], source="llm")
        # T-991 v3：旧草案（pv2 前）无分类/优先级 → 兜底补默认
        candidate["category"] = _norm_category(candidate.get("category"))
        candidate["priority"] = _norm_priority(candidate.get("priority"))
        if "agent_origin" not in candidate:
            candidate["agent_origin"] = {
                "title": candidate.get("title", ""),
                "summary": candidate.get("summary", ""),
                "keywords": list(candidate.get("keywords") or []),
                "model": "", "generated_at": datetime.now().isoformat(
                    timespec="seconds"), "prompt_version": _PROMPT_VERSION}
        merged = _merge_one(existing, sha8, day, candidate)
        existing.append(merged)
        _append_history(mroot, str(merged.get("id")), author, "commit",
                        base_rev=1,
                        changes={"status": {"from": None, "to": "draft"}})
        produced.append(merged)
    _save_candidates(mroot, existing)
    return produced


def edit_candidate(emp_base: Path, topic_id: str,
                   title: str = "", summary: str = "",
                   keywords: list[str] | None = None,
                   base_rev: int | None = None,
                   editor: dict | None = None,
                   material_base: Path | None = None,
                   category: str = "", priority: str = "",
                   message_ids: list[str] | None = None,
                   window: list[str] | None = None,
                   days: list[str] | None = None) -> dict:
    """人工编辑卡片 title/summary/keywords/category/priority（T-948 R7 +
    T-991；agent_origin 永不改动）+ 手动重关联原文（T-1001 F4：
    message_ids 整体替换，window/days 随新关联集合更新——由前端按
    消息事实源换算后传入）。

    乐观锁：base_rev 与卡片 rev 不符 → RevConflict（携带最新卡片，路由层转 409）；
    成功 → rev+1、last_edited_* 更新、history(action=edit, changes from/to)。
    空串/None 表示该字段不改。category/priority 非法枚举 → ValueError（路由 400）。
    message_ids 非 None 时必须非空（话题至少关联一条消息）；window 非空时须为
    [start, end] 两元素 → 否则 ValueError（路由 400）。
    T-949：话题库随 material_base（共享区）。
    """
    if category and category not in _CATEGORY_ENUM:
        raise ValueError(f"非法 category: {category}（合法：{'/'.join(_CATEGORY_ENUM)}）")
    if priority and priority not in _PRIORITY_ENUM:
        raise ValueError(f"非法 priority: {priority}（合法：{'/'.join(_PRIORITY_ENUM)}）")
    if message_ids is not None and (not message_ids
            or not all(isinstance(m, str) and m.strip() for m in message_ids)):
        raise ValueError("message_ids 需至少一条非空消息 id（话题不能零关联）")
    if window and len(window) != 2:
        raise ValueError("window 需为 [start, end] 两元素（ISO 时间戳）")
    mroot = _mroot(emp_base, material_base)
    existing = _load_candidates(mroot)
    topic = next((t for t in existing if t.get("id") == topic_id), None)
    if topic is None:
        raise KeyError(f"候选话题不存在: {topic_id}")
    if base_rev is not None and int(base_rev) != int(topic.get("rev") or 1):
        raise RevConflict(topic)
    changes: dict = {}
    if title and title != topic.get("title"):
        changes["title"] = {"from": topic.get("title"), "to": title}
        topic["title"] = title
    if summary and summary != topic.get("summary"):
        changes["summary"] = {"from": topic.get("summary"), "to": summary}
        topic["summary"] = summary
    if keywords is not None:
        # tag-taxonomy：人工编辑关键词同样过词表（别名归一 + 新词入待收录）
        keywords = tr.canonicalize_and_register(mroot, list(keywords),
                                                source="human")
        if list(keywords) != list(topic.get("keywords") or []):
            changes["keywords"] = {"from": list(topic.get("keywords") or []),
                                  "to": list(keywords)}
            topic["keywords"] = list(keywords)
    if category and category != topic.get("category"):
        changes["category"] = {"from": topic.get("category"), "to": category}
        topic["category"] = category
    if priority and priority != topic.get("priority"):
        changes["priority"] = {"from": topic.get("priority"), "to": priority}
        topic["priority"] = priority
    if message_ids is not None and list(message_ids) != list(topic.get("message_ids") or []):
        changes["message_ids"] = {"from": list(topic.get("message_ids") or []),
                                  "to": list(message_ids)}
        topic["message_ids"] = list(message_ids)
    if window and list(window) != list(topic.get("window") or []):
        changes["window"] = {"from": list(topic.get("window") or []),
                             "to": list(window)}
        topic["window"] = list(window)
    if days and list(days) != list(topic.get("days") or []):
        changes["days"] = {"from": list(topic.get("days") or []),
                           "to": list(days)}
        topic["days"] = list(days)
    if not changes:
        return topic                              # 无实际变化：不推 rev 不落历史
    topic["rev"] = int(topic.get("rev") or 1) + 1
    topic["last_edited_by"] = editor or _SYSTEM_EDITOR
    topic["last_edited_at"] = datetime.now().isoformat(timespec="seconds")
    _save_candidates(mroot, existing)
    _append_history(mroot, topic_id, editor, "edit",
                    base_rev=int(topic.get("rev")) - 1, changes=changes)
    return topic


def set_topic_status(emp_base: Path, topic_id: str, status: str,
                     editor: dict | None = None,
                     material_base: Path | None = None) -> dict:
    """状态翻转（T-948 D3：确认/拒绝从跨区提升退化为同文件状态位）。"""
    if status not in _STATUS_ENUM:
        raise ValueError(f"非法状态: {status}（合法：{'/'.join(_STATUS_ENUM)}）")
    mroot = _mroot(emp_base, material_base)
    existing = _load_candidates(mroot)
    topic = next((t for t in existing if t.get("id") == topic_id), None)
    if topic is None:
        raise KeyError(f"候选话题不存在: {topic_id}")
    old = topic.get("status")
    if old == status:
        return topic
    topic["status"] = status
    topic["rev"] = int(topic.get("rev") or 1) + 1
    topic["last_edited_by"] = editor or _SYSTEM_EDITOR
    topic["last_edited_at"] = datetime.now().isoformat(timespec="seconds")
    _save_candidates(mroot, existing)
    action = {"confirmed": "confirm", "rejected": "reject",
              "draft": "reopen"}[status]
    _append_history(mroot, topic_id, editor, action,
                    base_rev=int(topic.get("rev")) - 1,
                    changes={"status": {"from": old, "to": status}})
    return topic


def regen_candidate(emp_base: Path, llm, topic_id: str,
                   editor: dict | None = None,
                   material_base: Path | None = None) -> dict:
    """单卡重新生成：按 source+window 取原文片段重跑 LLM，id 不变。

    T-948：agent_origin 换新版本（model/generated_at/prompt_version 随当前生成），
    旧版本进历史（changes.agent_origin.from 可追溯）；rev 推进。
    T-949：话题库与 chats 随 material_base（共享材料区）。
    T-951c：跨日卡（topic.days 非空）拼接窗口内各日 JSONL 重提炼。
    """
    mroot = _mroot(emp_base, material_base)
    existing = _load_candidates(mroot)
    topic = next((t for t in existing if t.get("id") == topic_id), None)
    if topic is None:
        raise KeyError(f"候选话题不存在: {topic_id}")
    src = Path(str(topic.get("source", "")))
    chat_sha8 = str(topic.get("chat_sha8") or src.parent.name)
    day = src.stem
    window = topic.get("window") or []
    regen_days = [str(d) for d in (topic.get("days") or []) if str(d)]
    line_ids: list[str] | None = None
    line_ts: list[str] | None = None
    if regen_days:
        # T-951c：跨日卡——窗口内各日 JSONL 拼接（无快照日跳过）
        try:
            content, line_ids, line_ts, _used = _load_window_source(
                mroot, chat_sha8, regen_days)
        except FileNotFoundError:
            content = _fallback_day_content(mroot, chat_sha8, day)
    else:
        content = _fallback_day_content(mroot, chat_sha8, day)
    win_str = (f"{str(window[0])[5:16]} ~ {str(window[1])[5:16]}"
               if len(window) == 2 else "")
    resp = llm.chat([{"role": "user", "content": _REGEN_PROMPT.format(
        day="~".join(regen_days) if regen_days else day,
        window=win_str, content=content,
        category_rubric=_CATEGORY_RUBRIC)}])
    raw_topics = _parse_llm_json(_llm_content(resp))
    if not raw_topics:
        raise ValueError("LLM 未返回话题")
    rt = raw_topics[0]
    msg_range = rt.get("msg_range") or []
    regen_ids = _msg_lines_to_ids(rt.get("msg_lines"), line_ids)
    old_origin = topic.get("agent_origin")
    new_origin = _make_agent_origin(rt, llm)
    topic["title"] = str(rt.get("title", topic.get("title", "")))
    topic["summary"] = str(rt.get("summary", topic.get("summary", "")))
    topic["keywords"] = tr.canonicalize_and_register(
        mroot,
        [str(k) for k in (rt.get("keywords") or topic.get("keywords") or [])
         if str(k)],
        source="llm")
    # T-991：分类随重生成更新（agent 语义字段）；priority 按新信号重推导
    # （regen 是用户显式动作，重算覆盖旧值——与 title/summary 同语义）
    topic["category"] = _norm_category(rt.get("category") or topic.get("category"))
    regen_count = (len(regen_ids) if regen_ids
                   else _count_messages(content, msg_range))
    regen_participants = int(
        rt.get("participants_count")
        or topic.get("participants_count", 0))
    topic["priority"] = derive_priority(
        topic["category"], regen_count, regen_participants,
        llm_hint=str(rt.get("priority_hint") or ""))
    topic["agent_origin"] = new_origin
    if regen_ids and line_ts:
        idxs = [i for i in range(len(line_ids)) if line_ids[i] in set(regen_ids)]
        if idxs:
            topic["window"] = [line_ts[min(idxs)], line_ts[max(idxs)]]
            topic["message_ids"] = regen_ids
        else:
            topic["window"] = _window_of(day, msg_range)
    else:
        topic["window"] = _window_of(day, msg_range)
    topic["message_count"] = (len(regen_ids) if regen_ids
                               else _count_messages(content, msg_range))
    topic["participants_count"] = int(
        rt.get("participants_count")
        or topic.get("participants_count", 0))
    topic["rev"] = int(topic.get("rev") or 1) + 1
    topic["last_edited_by"] = editor or _SYSTEM_EDITOR
    topic["last_edited_at"] = datetime.now().isoformat(timespec="seconds")
    _save_candidates(mroot, existing)
    _append_history(mroot, topic_id, editor, "regen",
                    base_rev=int(topic.get("rev")) - 1,
                    changes={"agent_origin": {"from": old_origin, "to": new_origin}})
    return topic
