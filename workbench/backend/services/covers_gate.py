"""covers 关联校验前置闸（runs 与 plans 执行入口共用，单一事实源）。

规则：
- 全部场景的 doc.covers 必须能解析为当前激活工作区 spec.md 中的 FR 锚点
- 存在 ERROR 时执行入口必须拦截（HTTP 422）
- fail-open 策略（无激活工作区 / 无锚点 / 校验异常）不阻止执行，但打印 WARN 保证可观测
"""

import logging
from pathlib import Path

logger = logging.getLogger("specguard.covers_gate")

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def check_covers_gate() -> list[dict]:
    """检查全部场景的 covers 是否可解析为有效 FR ID。

    返回 covers 错误列表（空列表表示通过）。
    """
    try:
        from specstd.workspace import get_active_workspace
        from specstd.anchors import scan_anchors
        from specstd.conformance import check_covers

        ws = get_active_workspace()
        if not ws:
            logger.warning("covers 前置闸跳过：无激活工作区")
            return []

        anchors = scan_anchors(ws.root)
        if not anchors:
            logger.warning("covers 前置闸跳过：工作区 %s 无 FR 锚点", ws.name)
            return []

        scenarios_root = SG_ROOT / "scenarios"
        findings = check_covers(anchors, scenarios_root)
        return [f.to_dict() for f in findings if f.level == "ERROR"]
    except Exception as e:
        logger.warning("covers 前置闸异常放行（fail-open）: %s: %s", type(e).__name__, e)
        return []
