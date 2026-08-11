"""iv_lifecycle.py — IV-xxx 面试会话生命周期状态机（M02 §4.4，T-020）。

状态机：
opened ──装配信息包/首轮提问──> interviewing
interviewing ──gate.py: 台账无 pending P0──> p0_cleared
p0_cleared ──影响面人工确认 + 五维≥70 + 产品确认──> frozen
frozen ──verify-delta + 合并基线──> archived
任何状态 ──发起人或 admin──> closed（中止，留档不删）
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── 合法状态 ──
VALID_STATUSES = frozenset({"opened", "interviewing", "p0_cleared",
                            "frozen", "archived", "closed"})

# IV-xxx 编号格式（路径拼接入口统一校验，防路径穿越）
IV_ID_RE = re.compile(r"^IV-\d{3,}$")


def validate_iv_id(iv_id: str) -> Optional[str]:
    """校验 IV-xxx 编号格式，返回错误消息或 None。

    所有用 iv_id 拼接路径的入口必须先过此校验（防目录穿越）。
    """
    if not iv_id or not isinstance(iv_id, str):
        return "iv_id 不能为空"
    if not IV_ID_RE.match(iv_id):
        return f"非法 IV 编号: {iv_id!r}（格式应为 IV-xxx）"
    return None

# 合法状态流转（closed 为终态，不可重开）
ALLOWED_TRANSITIONS = {
    "opened": {"interviewing"},
    "interviewing": {"p0_cleared", "closed"},
    "p0_cleared": {"frozen", "closed"},
    "frozen": {"archived"},
    "archived": set(),     # 终态
    "closed": set(),       # 终态
}


def validate_transition(current: str, next_status: str) -> Optional[str]:
    """校验状态流转是否合法，返回错误消息，合法时返回 None。"""
    if current not in VALID_STATUSES:
        return f"非法当前状态: {current!r}"
    if next_status not in VALID_STATUSES:
        return f"非法目标状态: {next_status!r}"
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if next_status not in allowed:
        return (f"非法状态流转: {current} → {next_status}"
                f"（允许: {sorted(allowed) or '无（终态）'}）")
    return None


def transition_status(current: str, next_status: str) -> str:
    """执行状态流转，不合法时抛出 ValueError。"""
    err = validate_transition(current, next_status)
    if err:
        raise ValueError(err)
    return next_status


# ── 面试流水 transcript.jsonl 操作 ──

def append_transcript(transcript_path: Path, entry: dict):
    """追加一条面试流水记录到 transcript.jsonl。

    Args:
        transcript_path: transcript.jsonl 路径
        entry: 流水条目 {ts, role, q_ref?, text, extracted_decision?, confirmed?}
    """
    import json
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_transcript(transcript_path: Path) -> list[dict]:
    """读取全部面试流水记录。"""
    if not transcript_path.is_file():
        return []
    import json
    entries = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ── 目录结构 ──

def iv_dir(specflow_base: Path, iv_id: str) -> Path:
    """返回 IV-xxx 目录路径（iv_id 必须通过格式校验，防路径穿越）。"""
    err = validate_iv_id(iv_id)
    if err:
        raise ValueError(err)
    return specflow_base / "interviews" / iv_id


def iv_topic_path(specflow_base: Path, iv_id: str) -> Path:
    return iv_dir(specflow_base, iv_id) / "topic.yaml"


def iv_transcript_path(specflow_base: Path, iv_id: str) -> Path:
    return iv_dir(specflow_base, iv_id) / "transcript.jsonl"


def iv_materials_dir(specflow_base: Path, iv_id: str) -> Path:
    return iv_dir(specflow_base, iv_id) / "materials"


def iv_snapshot_path(specflow_base: Path, iv_id: str) -> Path:
    return iv_dir(specflow_base, iv_id) / "impact_snapshot.json"


def iv_archive_meta_path(specflow_base: Path, iv_id: str) -> Path:
    return iv_dir(specflow_base, iv_id) / "archive_meta.yaml"


def list_interviews(specflow_base: Path) -> list[str]:
    """列出 interviews 目录下全部 IV-xxx。"""
    interviews_root = specflow_base / "interviews"
    if not interviews_root.is_dir():
        return []
    result = []
    for d in sorted(interviews_root.iterdir()):
        if d.is_dir() and d.name.startswith("IV-"):
            result.append(d.name)
    return result