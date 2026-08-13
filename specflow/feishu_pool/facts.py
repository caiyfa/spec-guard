"""facts.py — 共享区事实源读写（topics.yaml / material_links.yaml）。

确定性纪律：
- 写入前全排序（links 按 (src, dst, edge)，topics 按 id），同键覆盖幂等；
- rejected 留痕防重复建议（工作区级，builder 派生时过滤不进图谱）；
- 文件由机器写机器读（无人手注释），允许 yaml.safe_dump（与「不用 js-yaml 写
  含中文注释 YAML」约束不冲突——该约束针对人手编辑的 spec/场景文件）。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from specflow.feishu_pool.paths import shared_dirs

_LINK_KEY_FIELDS = ("src", "dst", "edge", "confidence", "evidence",
                    "status", "confirmed_by", "confirmed_at")
_TOPIC_KEY_FIELDS = ("id", "title", "summary", "chat_sha8", "window",
                     "message_count", "participants_count", "source")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_yaml(path: Path, list_key: str) -> list[dict]:
    if not path.is_file():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    items = raw.get(list_key) or []
    return [dict(i) for i in items if isinstance(i, dict)]


def _save_yaml(path: Path, list_key: str, items: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": 1, list_key: items},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")


# ══════════════════════════════════════════════════════════
# material_links.yaml
# ══════════════════════════════════════════════════════════

def load_links(workspace_root: Path) -> list[dict]:
    """读取关联边事实源（缺失返回空 list，按 (src, dst, edge) 排序）。"""
    return _load_yaml(shared_dirs(workspace_root)["links_yaml"], "links")


def _save_links(workspace_root: Path, links: list[dict]):
    links = sorted(links, key=lambda l: (str(l.get("src", "")),
                                         str(l.get("dst", "")),
                                         str(l.get("edge", ""))))
    _save_yaml(shared_dirs(workspace_root)["links_yaml"], "links", links)


def append_link(workspace_root: Path, *, src: str, dst: str, edge: str,
                confidence: float, evidence: str, confirmed_by: str,
                status: str = "confirmed") -> dict:
    """追加/覆盖一条关联边（同 (src,dst,edge) 覆盖，自动填 confirmed_at）。"""
    links = load_links(workspace_root)
    links = [l for l in links
             if not (l.get("src") == src and l.get("dst") == dst
                     and l.get("edge") == edge)]
    entry = {
        "src": src, "dst": dst, "edge": edge,
        "confidence": confidence, "evidence": evidence,
        "status": status, "confirmed_by": confirmed_by,
        "confirmed_at": _now(),
    }
    links.append(entry)
    _save_links(workspace_root, links)
    return entry


def is_rejected(workspace_root: Path, src: str, dst: str) -> bool:
    """该 (src,dst) 是否已被拒绝（防 LLM 重复建议）。"""
    return any(l.get("src") == src and l.get("dst") == dst
               and l.get("status") == "rejected"
               for l in load_links(workspace_root))


# ══════════════════════════════════════════════════════════
# topics.yaml
# ══════════════════════════════════════════════════════════

def load_topics(workspace_root: Path) -> list[dict]:
    """读取话题事实源（缺失返回空 list，按 id 排序）。"""
    return _load_yaml(shared_dirs(workspace_root)["topics_yaml"], "topics")


def upsert_topic(workspace_root: Path, topic: dict) -> None:
    """按 id 覆盖式写入话题（id 稳定 = 确定性重建前提）。"""
    topics = [t for t in load_topics(workspace_root)
              if t.get("id") != topic.get("id")]
    topics.append({k: topic.get(k) for k in _TOPIC_KEY_FIELDS if k in topic})
    topics.sort(key=lambda t: str(t.get("id", "")))
    _save_yaml(shared_dirs(workspace_root)["topics_yaml"], "topics", topics)
