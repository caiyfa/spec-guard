"""tag_registry.py — 话题标签词表（tag-taxonomy：AI 分类标签爆炸收口）。

背景：话题卡 keywords 原为 LLM 自由文本（2~5 词/卡），无词表无归并——
14 张卡裂出 40+ 标签芯片（Bug / Bug 140594 / 140594 同义三分，人名、单号、
过细动作词混入）。本模块是受控词汇事实源：

- 落点：与话题库同域 pool root 下 `_tags.yaml`（T-949 生产形态=共享材料区，
  全用户同一份词表才能收敛；私有回退随 base 自然成立）
- 状态制：active（人工收录）/ pending（LLM 或人工新词自动入待收录区，
  待工作台账收录、归并或丢弃）——与话题卡 draft→confirmed 同一哲学
- 别名归并：alias → 主标签；查找键忽略全部空白与大小写
  （"Bug 140594" / "bug140594" 同键），显示名保留主标签原形
- 两级结构：domain 挂在**标签**上而非话题卡上——卡只携带 keywords
  （词表归一后的主标签），前端标签栏按 标签.domain 分组即得两级视图；
  存量卡无需重跑 LLM，词表建档后旧卡标签自动归组
- 历史：人工动作（merge/promote/set_domain/drop）追加 `_tags_history.jsonl`；
  自动注册（auto_register）**不落历史**——聚类每次新词量 5~20，
  落历史会淹没人工动作留痕（降噪决策）
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from specflow.feishu_pool.paths import pool_dirs

_VERSION = 1
_TAG_STATUS = ("active", "pending")
_SYSTEM_EDITOR = {"emp": "", "name": "system"}


def _tags_path(base: Path) -> Path:
    return pool_dirs(base)["root"] / "_tags.yaml"


def _history_path(base: Path) -> Path:
    return pool_dirs(base)["root"] / "_tags_history.jsonl"


def _norm_key(s) -> str:
    """查找键：剔除全部空白 + 小写（显示名不动，仅匹配用）。"""
    return re.sub(r"\s+", "", str(s or "")).lower()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm_entry(raw) -> dict:
    e = dict(raw) if isinstance(raw, dict) else {}
    status = str(e.get("status") or "active")
    return {
        "aliases": [str(a) for a in (e.get("aliases") or []) if str(a)],
        "domain": str(e.get("domain") or ""),
        "status": status if status in _TAG_STATUS else "active",
        "source": str(e.get("source") or "human"),
        "created_at": str(e.get("created_at") or ""),
    }


def load_registry(base: Path) -> dict:
    """读词表（缺文件/坏 YAML → 空骨架，诚实不抛；存量条目补默认字段）。"""
    path = _tags_path(base)
    raw: dict = {}
    if path.is_file():
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            raw = {}
    tags = {str(k): _norm_entry(v) for k, v in (raw.get("tags") or {}).items()}
    domains = {}
    for k, v in (raw.get("domains") or {}).items():
        d = dict(v) if isinstance(v, dict) else {}
        d.setdefault("status", "active")
        d.setdefault("created_at", "")
        domains[str(k)] = d
    return {"version": _VERSION, "tags": tags, "domains": domains}


def save_registry(base: Path, reg: dict):
    path = _tags_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"version": _VERSION,
                        "tags": reg.get("tags") or {},
                        "domains": reg.get("domains") or {}},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def canonical_map(reg: dict) -> dict[str, str]:
    """规范键 → 主标签名。主标签自身优先建档，别名不覆盖主标签键。"""
    out: dict[str, str] = {}
    for name in (reg.get("tags") or {}):
        out[_norm_key(name)] = name
    for name, entry in (reg.get("tags") or {}).items():
        for a in entry.get("aliases") or []:
            out.setdefault(_norm_key(a), name)
    return out


def canonicalize(reg: dict, words) -> tuple[list[str], list[str]]:
    """词列表 → (主标签列表, 未知词列表)。按主标签去重保序；未知词透传。"""
    cmap = canonical_map(reg)
    canon: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for w in words or []:
        w = str(w).strip()
        if not w:
            continue
        hit = cmap.get(_norm_key(w))
        c = hit if hit is not None else w
        if _norm_key(c) in seen:
            continue
        seen.add(_norm_key(c))
        canon.append(c)
        if hit is None:
            unknown.append(w)
    return canon, unknown


def register_pending(reg: dict, words, source: str = "llm") -> list[str]:
    """未知词入待收录（内存态，幂等）；返回本次新登记的名字列表。"""
    cmap = canonical_map(reg)
    tags = reg.setdefault("tags", {})
    added: list[str] = []
    for w in words or []:
        w = str(w).strip()
        if not w or _norm_key(w) in cmap:
            continue
        tags[w] = {"aliases": [], "domain": "", "status": "pending",
                   "source": source or "llm", "created_at": _now()}
        cmap[_norm_key(w)] = w
        added.append(w)
    return added


def canonicalize_and_register(base: Path, words, source: str = "llm") -> list[str]:
    """单发便捷路径：归一 + 未知词落 pending 存盘（不写历史），返回主标签列表。"""
    reg = load_registry(base)
    canon, unknown = canonicalize(reg, words)
    if unknown and register_pending(reg, unknown, source=source):
        save_registry(base, reg)
    return canon


def _append_history(base: Path, action: str, editor: dict | None, changes: dict):
    rec = {"at": _now(), "action": action,
           "editor": editor or _SYSTEM_EDITOR, "changes": changes}
    path = _history_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _resolve(reg: dict, name: str) -> str | None:
    """任意写法（主标签/别名/待收录）→ 主标签名；未登记返回 None。"""
    return canonical_map(reg).get(_norm_key(name))


def merge_tag(base: Path, source: str, target: str,
              editor: dict | None = None) -> dict:
    """归并：source（任意写法）→ target 主标签名下别名。

    - 源是主标签：自带别名随迁，源条目移除；目标无域而源有域 → 沿用源域
    - 目标是 pending：人工归并=收录意图，目标转 active（source=human）
    - 目标未登记：以人工名义新建 active 条目（收录新词同步归并）
    - 源与目标同词（含已是其别名）→ ValueError；源未登记 → KeyError
    """
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source or not target:
        raise ValueError("source/target 不能为空")
    reg = load_registry(base)
    tags = reg.setdefault("tags", {})
    src_canon = _resolve(reg, source)
    tgt_canon = _resolve(reg, target)
    if src_canon is None:
        raise KeyError(f"标签不存在: {source}")
    if tgt_canon is not None and tgt_canon == src_canon:
        raise ValueError(f"源与目标是同一标签: {source} → {target}")
    if tgt_canon is None:
        tags[target] = {"aliases": [], "domain": "", "status": "active",
                        "source": "human", "created_at": _now()}
        tgt_canon = target
    tgt = tags[tgt_canon]
    if tgt["status"] == "pending":
        tgt["status"] = "active"
        tgt["source"] = "human"
    src_entry = tags.pop(src_canon, None)
    aliases = tgt.setdefault("aliases", [])
    for w in [src_canon] + list((src_entry or {}).get("aliases") or []):
        if _norm_key(w) != _norm_key(tgt_canon) and w not in aliases:
            aliases.append(w)
    if src_entry and src_entry.get("domain"):
        if not tgt.get("domain"):
            tgt["domain"] = src_entry["domain"]
        reg.setdefault("domains", {}).setdefault(
            src_entry["domain"], {"status": "active", "created_at": _now()})
    save_registry(base, reg)
    _append_history(base, "merge", editor,
                    {"source": source, "target": tgt_canon})
    return tgt


def promote_tag(base: Path, name: str, editor: dict | None = None) -> dict:
    """收录：pending → active（source 转 human）。未登记 → KeyError。"""
    reg = load_registry(base)
    canon = _resolve(reg, name)
    if canon is None:
        raise KeyError(f"标签不存在: {name}")
    entry = reg["tags"][canon]
    entry["status"] = "active"
    entry["source"] = "human"
    save_registry(base, reg)
    _append_history(base, "promote", editor, {"tag": canon})
    return entry


def drop_tag(base: Path, name: str, editor: dict | None = None) -> None:
    """丢弃 pending 噪音词；active 只能被归并走（ValueError）。未登记 → KeyError。"""
    reg = load_registry(base)
    canon = _resolve(reg, name)
    if canon is None:
        raise KeyError(f"标签不存在: {name}")
    if reg["tags"][canon]["status"] != "pending":
        raise ValueError(f"仅 pending 标签可丢弃（active 请用归并）: {canon}")
    reg["tags"].pop(canon)
    save_registry(base, reg)
    _append_history(base, "drop", editor, {"tag": canon})


def set_tag_domain(base: Path, name: str, domain: str,
                   editor: dict | None = None) -> dict:
    """设域（两级结构的一级）：域未建档自动建（active）；空串清除。标签未登记 → KeyError。"""
    reg = load_registry(base)
    canon = _resolve(reg, name)
    if canon is None:
        raise KeyError(f"标签不存在: {name}")
    domain = str(domain or "").strip()
    reg["tags"][canon]["domain"] = domain
    if domain:
        reg.setdefault("domains", {}).setdefault(
            domain, {"status": "active", "created_at": _now()})
    save_registry(base, reg)
    _append_history(base, "set_domain", editor, {"tag": canon, "domain": domain})
    return reg["tags"][canon]


def known_tags_digest(reg: dict, limit: int = 60) -> str:
    """prompt 注入清单：active 优先、pending 殿后（标待收录），别名随主标签标注。

    限量 limit 条（防爆 prompt）；空词表返回空串（调用方拼「（空）」占位）。
    """
    tags = reg.get("tags") or {}

    def _line(name: str) -> str:
        entry = tags[name]
        s = f"- {name}"
        if entry.get("aliases"):
            s += f"（别名: {'、'.join(entry['aliases'])}）"
        if entry.get("status") == "pending":
            s += "（待收录）"
        return s

    active = sorted(n for n, e in tags.items() if e.get("status") == "active")
    pending = sorted(n for n, e in tags.items() if e.get("status") != "active")
    return "\n".join(_line(n) for n in (active + pending)[:limit])
