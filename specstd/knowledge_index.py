"""specstd.knowledge_index — 触景触发索引（L4 分发，T-508）。

构建「token → 触发条件 → 摘要」的确定性索引，供运行时双通道匹配：
- 源：L1 语义词典（{ws}/glossary.md）、L2 环境叙事（systems/{sys}/config/env.{env}.md）、
  L3 经验库（{ws}/.specguard/experience/*.md）
- 寻址：kg://{workspace}/{layer}/{token}（layer ∈ term/env/experience）
- 指纹失效即重建；30s TTL 热加载（复用 skill_loader 模式）
- 知识索引是派生物非事实源——源文件是真相，索引只是投影

红线（设计 §4.2）：
- 匹配只做工具结构化字段 + 用户输入两通道，**不做 agent 输出匹配**（防回环）
- 投递预算：每篇每会话一次、≤400 字符摘要 + read_knowledge 指针、会话总量 ≤4KB
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from specstd.glossary import parse_glossary, GLOSSARY_FILE, GLOSSARY_FR_RE

# 层类型
LAYER_TERM = "term"
LAYER_ENV = "env"
LAYER_EXPERIENCE = "experience"
VALID_LAYERS = (LAYER_TERM, LAYER_ENV, LAYER_EXPERIENCE)

# 投递预算硬顶（设计 §4.3）
NUDGE_MAX_CHARS = 400      # 每篇摘要 ≤400 字符
NUDGE_BUDGET = 4096        # 每会话知识注入总量 ≤4KB
NUDGE_TAG_OPEN = "<knowledge_refs>"
NUDGE_TAG_CLOSE = "</knowledge_refs>"

# 索引缓存 TTL（30s 热加载）
_CACHE_TTL = 30.0

# 错误签名 → 关联 token（工具结果文本命中时触发，优先级最高）
# 来源：经验包 EX-8200eada（变量未定义 ↔ 权限缺失）、常见业务失败
ERROR_SIGNATURES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"变量未定义|KeyError.*可用键"), "precheck-permission"),
    (re.compile(r"500000|无平台权限|无.*权限"), "business-error-500000"),
    (re.compile(r"resource_code|资源码.*未授权|无绑定账号"), "resource-code"),
]


@dataclass
class KnowledgeEntry:
    """单条知识索引条目。"""
    token: str                       # kg:// 末段（词条 token / EX-xxx / env-{env}）
    layer: str                       # term / env / experience
    title: str                       # 人类可读标题
    summary: str                     # ≤400 字符摘要（nudge 投递用）
    fr_refs: list[str] = field(default_factory=list)     # 关联 FR
    scenario_ids: list[str] = field(default_factory=list)  # 关联场景
    resource_codes: list[str] = field(default_factory=list)  # 资源码
    keywords: list[str] = field(default_factory=list)    # 用户输入匹配关键词
    source: str = ""                 # 来源路径（相对）
    line: int = 0

    @property
    def ref(self) -> str:
        return f"kg://{self.workspace}/{self.layer}/{self.token}"

    def set_workspace(self, ws: str):
        self.workspace = ws


@dataclass
class KnowledgeIndex:
    """工作区知识索引快照（指纹失效即重建）。"""
    entries: dict[str, KnowledgeEntry] = field(default_factory=dict)
    fingerprint: str = ""
    workspace: str = ""
    built_at: float = 0.0

    def __contains__(self, token: str) -> bool:
        return token in self.entries

    def __getitem__(self, token: str) -> KnowledgeEntry:
        return self.entries[token]

    def get(self, token: str) -> Optional[KnowledgeEntry]:
        return self.entries.get(token)

    def clear_cache(self):
        """清空缓存（测试/调试用）。"""
        _INDEX_CACHE.clear()


# 进程级缓存：{key: (ts, KnowledgeIndex)}
_INDEX_CACHE: dict[str, tuple[float, KnowledgeIndex]] = {}
_CACHE_LOCK = __import__("threading").RLock()


def _fingerprint(*paths: Path) -> str:
    """源文件内容指纹（sha256-12）。"""
    h = hashlib.sha256()
    for p in paths:
        if p.is_file():
            h.update(p.read_bytes())
        else:
            h.update(b"<missing>")
    return h.hexdigest()[:12]


def _glossary_entries(ws_root: Path) -> list[KnowledgeEntry]:
    """L1：语义词典 → term 层条目。"""
    gpath = ws_root / GLOSSARY_FILE
    if not gpath.is_file():
        return []
    out = []
    for e in parse_glossary(gpath):
        frs = sorted(set(GLOSSARY_FR_RE.findall(e.refs)))
        # 场景 ID（如 IS-PREP-002 / PP-RC-001）与资源码（大写带下划线）从 refs 提取
        scenarios = sorted(set(re.findall(r"\b[A-Z]{2,4}-[A-Z]{2,6}-\d{3}\b", e.refs)))
        # 资源码：大写单词（如 TDM_INV_ACTIVITY / VIEW_TELENT_SEARCH / SG_NONEXIST_RESOURCE）
        resources = sorted(set(
            t for t in re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", e.refs)
            if t not in ("FR", "AC", "HTTP", "SIT", "UAT", "TDM", "DHR", "ES", "DB")))
        summary = e.semantic or e.rules or ""
        entry = KnowledgeEntry(
            token=e.token,
            layer=LAYER_TERM,
            title=e.title,
            summary=summary[:NUDGE_MAX_CHARS],
            fr_refs=frs,
            scenario_ids=scenarios,
            resource_codes=resources,
            keywords=[e.token, e.title] + [s for s in scenarios],
            source=GLOSSARY_FILE,
            line=e.line,
        )
        entry.set_workspace(ws_root.name)
        out.append(entry)
    return out


def _env_entries(system_dir: Optional[Path]) -> list[KnowledgeEntry]:
    """L2：环境叙事 env.{env}.md → env 层条目（每个环境一条整体摘要）。"""
    if not system_dir or not system_dir.is_dir():
        return []
    out = []
    for f in sorted(system_dir.glob("env.*.md")):
        env = f.stem.split(".", 1)[1]  # env.sit.md → sit
        text = f.read_text(encoding="utf-8")
        # 摘要：定位段 + 已知坑段（截前 400 字符）
        summary = re.sub(r"\n{3,}", "\n\n", text).strip()[:NUDGE_MAX_CHARS]
        entry = KnowledgeEntry(
            token=f"env-{env}",
            layer=LAYER_ENV,
            title=f"环境叙事（{env}）",
            summary=summary,
            keywords=[f"env-{env}", env, "环境", "已知坑", "资源码"],
            source=str(f),
        )
        entry.set_workspace("")  # env 属于系统层（跨工作区）
        out.append(entry)
    return out


def _experience_entries(ws_root: Path) -> list[KnowledgeEntry]:
    """L3：经验库 {ws}/.specguard/experience/*.md → experience 层条目。"""
    exp_dir = ws_root / ".specguard" / "experience"
    if not exp_dir.is_dir():
        return []
    out = []
    for f in sorted(exp_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        # token = EX-xxxx（经验包命名前缀），非完整文件名
        token = f.stem
        m = re.search(r"(EX-[A-Za-z0-9]+)", f.stem)
        if m:
            token = m.group(1)
        # 摘要：根因/预防段（按标题切，取正文前 400 字符）
        body = re.sub(r"^#{1,3} .*$", "", text, flags=re.MULTILINE)
        summary = re.sub(r"\n{3,}", "\n\n", body).strip()[:NUDGE_MAX_CHARS]
        title = f.stem.replace("-", " ").replace("_", " ")
        entry = KnowledgeEntry(
            token=token,
            layer=LAYER_EXPERIENCE,
            title=title,
            summary=summary,
            keywords=[token, title] + re.findall(r"[A-Z]{2,4}-[A-Z0-9]{3,}", f.stem),
            source=str(f),
        )
        entry.set_workspace(ws_root.name)
        out.append(entry)
    return out


def build_index(ws_root: Path, system_dir: Optional[Path] = None,
                name: Optional[str] = None) -> KnowledgeIndex:
    """构建（或命中缓存返回）触发索引。

    指纹 = 词典 + 叙事 + 经验库内容；指纹不变且 TTL 内 → 缓存命中。
    """
    ws_root = Path(ws_root)
    ws_name = name or ws_root.name

    # 源文件集合（指纹依据）
    sources = []
    gpath = ws_root / GLOSSARY_FILE
    if gpath.is_file():
        sources.append(gpath)
    if system_dir and system_dir.is_dir():
        sources.extend(sorted(system_dir.glob("env.*.md")))
    exp_dir = ws_root / ".specguard" / "experience"
    if exp_dir.is_dir():
        sources.extend(sorted(exp_dir.glob("*.md")))

    fp = _fingerprint(*sources) if sources else "<empty>"
    key = f"{ws_name}:{fp}"

    with _CACHE_LOCK:
        cached = _INDEX_CACHE.get(key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL:
            return cached[1]
        if cached:
            del _INDEX_CACHE[key]

    idx = KnowledgeIndex(fingerprint=fp, workspace=ws_name, built_at=time.time())
    for e in _glossary_entries(ws_root) + _env_entries(system_dir) + _experience_entries(ws_root):
        idx.entries[e.token] = e

    with _CACHE_LOCK:
        _INDEX_CACHE[key] = (time.time(), idx)
    return idx


def clear_cache():
    """清空索引缓存（测试/调试用）。"""
    with _CACHE_LOCK:
        _INDEX_CACHE.clear()


# ══════════════════════════════════════════════════════════
# 双通道匹配（确定性，无 LLM 路由）
# ══════════════════════════════════════════════════════════

def _match_scenario(scenarios: list[str], target: str) -> bool:
    """场景 ID 匹配：目标等于场景或同模块前缀（IS-PREP-002 → 命中 IS-PREP-* 词条）。"""
    if not target:
        return False
    if target in scenarios:
        return True
    prefix = target.rsplit("-", 1)[0]  # IS-PREP-002 → IS-PREP
    return any(s.startswith(prefix) for s in scenarios)


def match_tool_call(idx: KnowledgeIndex, tool_name: str = "",
                    arguments: dict | None = None,
                    result_text: str = "") -> list[KnowledgeEntry]:
    """通道一（主）：工具调用/结果的结构化字段匹配。

    规则（确定性）：
    - scenario_id 参数 → 场景关联词条（精确或同模块前缀）
    - 结果文本命中错误签名 → 错误关联词条（最高优先级）
    - 结果文本命中资源码 → 资源码词条
    """
    hits: dict[str, KnowledgeEntry] = {}
    args = arguments or {}

    # 1) scenario_id → 场景
    for sid_key in ("scenario_id", "id"):
        sid = str(args.get(sid_key, "") or "")
        if sid:
            for e in idx.entries.values():
                if _match_scenario(e.scenario_ids, sid):
                    hits[e.token] = e

    # 2) 错误签名（结果文本）
    if result_text:
        for pattern, token in ERROR_SIGNATURES:
            if pattern.search(result_text) and token in idx.entries:
                hits[token] = idx.entries[token]
        # 资源码出现在结果文本 → 命中资源码词条
        for e in idx.entries.values():
            if e.layer == LAYER_TERM and e.resource_codes:
                for rc in e.resource_codes:
                    if rc and rc in result_text:
                        hits[e.token] = e

    return list(hits.values())


def match_user_text(idx: KnowledgeIndex, text: str) -> list[KnowledgeEntry]:
    """通道二（辅）：用户自由文本关键词匹配（子串，大小写不敏感）。"""
    if not text:
        return []
    low = text.lower()
    hits: dict[str, KnowledgeEntry] = {}
    for e in idx.entries.values():
        if any(kw and kw.lower() in low for kw in e.keywords):
            hits[e.token] = e
    return list(hits.values())


# ══════════════════════════════════════════════════════════
# 投递与预算纪律（设计 §4.3）
# ══════════════════════════════════════════════════════════

class KnowledgeNudger:
    """会话级知识 nudge 合成器。

    - 每篇每会话最多 nudge 一次（已读集合去重）
    - nudge = ≤400 字符摘要 + read_knowledge(ref) 指针
    - 会话知识注入总量 ≤4KB，超预算静默截断
    - 多命中按优先级：错误签名 > 显式 @ > 工具绑定 > 关键词
    """

    def __init__(self, idx: KnowledgeIndex):
        self.idx = idx
        self._read: set[str] = set()      # 已 nudge 的 token（每篇每会话一次）
        self._used_budget = 0             # 已用字符

    def _entry_line(self, e: KnowledgeEntry) -> str:
        return (f"- {e.title}（{e.layer}）：{e.summary[:NUDGE_MAX_CHARS]}"
                f" → read_knowledge({e.ref!r})")

    def compose(self, tool_context: str = "", user_text: str = "") -> str:
        """合成 <knowledge_refs> 块；无可投递或预算耗尽返回空串。

        tool_context: 工具通道上下文（scenario_id 或错误文本）
        user_text: 用户输入通道
        """
        # 双通道合并（工具优先展示）
        tool_hits = match_tool_call(self.idx, arguments={"scenario_id": tool_context},
                                    result_text=tool_context) if tool_context else []
        user_hits = match_user_text(self.idx, user_text) if user_text else []
        seen = {e.token for e in tool_hits}
        merged = tool_hits + [e for e in user_hits if e.token not in seen]
        if not merged:
            return ""

        lines = [f"{NUDGE_TAG_OPEN}（知识触景提示，按需 read_knowledge 取正文）"]
        for e in merged:
            if e.token in self._read:
                continue
            line = self._entry_line(e)
            # 预算检查：单条 ≤400 + 总量 ≤4KB
            if len(line) > NUDGE_MAX_CHARS + 120 or self._used_budget + len(line) > NUDGE_BUDGET:
                continue
            lines.append(line)
            self._read.add(e.token)
            self._used_budget += len(line)
        if len(lines) == 1:
            return ""
        lines.append(NUDGE_TAG_CLOSE)
        return "\n".join(lines)
