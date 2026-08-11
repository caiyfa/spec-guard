"""topic.py — 议题卡 topic.yaml 模型定义、解析、生成（M02 §4.2，T-021）。

支持 7 种 source 类型：prd_section, spq, feishu_doc, feishu_base,
feishu_minutes, feishu_im, zentao_story。

缺挂链时创建被拒或 WARNING（确定性校验）。
"""

from __future__ import annotations

import re
import threading
import yaml
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 合法 source 类型 ──
VALID_SOURCE_TYPES = frozenset({
    "prd_section", "spq",
    "feishu_doc", "feishu_base", "feishu_minutes", "feishu_im",
    "zentao_story",
})


@dataclass
class SourceRef:
    """议题来源引用（落笔即挂链）。"""
    type: str          # 来源类型
    ref: str           # 来源引用标识
    url: str = ""      # 可选 URL
    note: str = ""     # 可选备注
    material: str = "" # 可选材料文件名

    def validate(self) -> Optional[str]:
        """校验来源引用的合法性，返回错误消息，合法时返回 None。"""
        if self.type not in VALID_SOURCE_TYPES:
            return f"非法 source 类型: {self.type!r}（允许: {sorted(VALID_SOURCE_TYPES)}）"
        if not self.ref:
            return "source ref 不能为空"
        return None


@dataclass
class BaselineRef:
    """基线锚点引用（specstd 解析，只读引用）。"""
    fr: str          # FR-xxx
    file: str = ""   # 文件路径
    note: str = ""   # 备注


@dataclass
class Topic:
    """议题卡（对应 topic.yaml schema）。"""
    iv_id: str                              # IV-xxx
    title: str                              # 议题标题
    initiator: dict                         # {emp, role}
    opened_at: str                          # ISO8601
    source: list[SourceRef] = field(default_factory=list)
    target_delta: str = ""                  # 冻结目标（三段式 + manifest 一致）
    baseline_refs: list[BaselineRef] = field(default_factory=list)
    history_decisions: list[str] = field(default_factory=list)
    status: str = "interviewing"            # 状态机见 IV 生命周期

    def to_yaml(self) -> str:
        """序列化为 topic.yaml 字符串。"""
        data = asdict(self)
        return yaml.dump(data, allow_unicode=True, indent=2, sort_keys=False,
                         default_flow_style=False)

    @classmethod
    def from_yaml(cls, text: str) -> "Topic":
        """从 topic.yaml 字符串反序列化。"""
        data = yaml.safe_load(text)
        sources = [SourceRef(**s) for s in data.pop("source", [])]
        refs = [BaselineRef(**r) for r in data.pop("baseline_refs", [])]
        return cls(source=sources, baseline_refs=refs, **data)

    def validate(self) -> list[str]:
        """校验完整性，返回错误消息列表；空列表 = 完全合法。"""
        errors: list[str] = []
        if not self.iv_id:
            errors.append("iv_id 不能为空")
        if not self.title:
            errors.append("title 不能为空")
        if not self.source:
            errors.append("议题卡必须至少有一个 source（缺挂链）")
        for s in self.source:
            err = s.validate()
            if err:
                errors.append(f"source[{s.ref}]: {err}")
        return errors

    def write(self, interviews_dir: Path):
        """写入议题卡文件（开标即落盘）。"""
        topic_path = interviews_dir / "topic.yaml"
        topic_path.write_text(self.to_yaml(), encoding="utf-8")


# IV-xxx 编号生成锁（并发开标防撞号）
_IV_ID_LOCK = threading.Lock()


def _next_iv_id(interviews_root: Path) -> str:
    """在 interviews 目录下生成下一个 IV-xxx 编号（并发安全）。"""
    with _IV_ID_LOCK:
        max_num = 0
        if interviews_root.is_dir():
            for d in interviews_root.iterdir():
                if d.is_dir() and d.name.startswith("IV-"):
                    try:
                        num = int(d.name[3:])
                        max_num = max(max_num, num)
                    except ValueError:
                        pass
        return f"IV-{max_num + 1:03d}"


def create_topic(
    title: str,
    initiator_emp: str,
    initiator_role: str,
    source: list[SourceRef],
    target_delta: str = "",
    baseline_refs: list[BaselineRef] = None,
    history_decisions: list[str] = None,
    specflow_base: Path = None,
) -> Topic:
    """创建议题卡并写入文件。

    Args:
        title: 议题标题
        initiator_emp: 发起人工号
        initiator_role: 发起人角色
        source: 议题来源列表（至少一个）
        target_delta: 冻结目标
        baseline_refs: 基线锚点列表
        history_decisions: 历史相关决策 ID 列表
        specflow_base: .specflow 目录路径

    Returns:
        创建的 Topic 对象

    Raises:
        ValueError: 校验失败
    """
    baseline_refs = baseline_refs or []
    history_decisions = history_decisions or []
    if not specflow_base:
        from specstd.workspace import specflow_dir
        specflow_base = specflow_dir()

    interviews_dir = specflow_base / "interviews"
    interviews_dir.mkdir(parents=True, exist_ok=True)

    iv_id = _next_iv_id(interviews_dir)
    topic = Topic(
        iv_id=iv_id,
        title=title,
        initiator={"emp": initiator_emp, "role": initiator_role},
        opened_at=datetime.now(timezone.utc).isoformat(),
        source=source,
        target_delta=target_delta,
        baseline_refs=baseline_refs,
        history_decisions=history_decisions,
        status="opened",
    )

    errors = topic.validate()
    if errors:
        raise ValueError(f"议题卡校验失败: {'; '.join(errors)}")

    # 创建 IV-xxx 目录
    iv_dir = interviews_dir / iv_id
    iv_dir.mkdir(parents=True, exist_ok=True)
    # 创建子目录
    (iv_dir / "materials").mkdir(exist_ok=True)

    topic.write(iv_dir)
    return topic


def load_topic(iv_id: str, specflow_base: Path = None) -> Optional[Topic]:
    """按 IV-xxx 加载议题卡。

    Args:
        iv_id: 面试编号
        specflow_base: .specflow 目录路径

    Returns:
        Topic 对象，不存在时返回 None

    Raises:
        ValueError: iv_id 格式非法（防路径穿越）
    """
    from specflow.interview.iv_lifecycle import validate_iv_id
    err = validate_iv_id(iv_id)
    if err:
        raise ValueError(err)
    if not specflow_base:
        from specstd.workspace import specflow_dir
        specflow_base = specflow_dir()
    topic_path = specflow_base / "interviews" / iv_id / "topic.yaml"
    if not topic_path.is_file():
        return None
    return Topic.from_yaml(topic_path.read_text(encoding="utf-8"))