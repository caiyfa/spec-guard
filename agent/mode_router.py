"""agent.mode_router — 模式自动路由器：根据上下文 + 意图自动选择工作模式。

路由优先级：手动锁定 > 工作台上下文 > 消息意图 > 默认 chat

三层信号设计（H-2）：
    层 0：用户手动锁定（最高优先级，尊重用户意愿）
    层 1：工作台上下文信号（确定性，最强）
    层 2：用户消息意图（关键词路由，零 LLM 调用）
    层 3：默认 chat（兜底）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RouteContext:
    """路由上下文。

    前端提供：message / locked_mode / current_page / last_run_failed /
              editing_scenario_id / scenario_never_run
    后端补充：workspace_just_pulled / pending_vulnerabilities
    """
    message: str                              # 用户消息
    locked_mode: str = ""                     # 用户手动锁定的模式（非空则不自动路由）
    current_page: str = ""                    # 工作台当前页面（execution / editor / dag / chat / feedback）
    last_run_failed: bool = False             # 最近一次运行是否失败
    workspace_just_pulled: bool = False       # spec 文件相对签名基线有变更（K-007：研发修正场景包文件）
    editing_scenario_id: str = ""             # 正在编辑的场景 ID
    scenario_never_run: bool = False           # 该场景从未运行过
    pending_vulnerabilities: int = 0           # 台账中 pending 漏洞数


@dataclass
class RouteResult:
    """路由结果。"""
    mode: str          # 路由到的模式名
    source: str        # manual / context / intent / default
    reason: str        # 路由原因（展示给用户）


# 意图关键词表（零 LLM 调用，确定性）
INTENT_KEYWORDS: dict[str, list[str]] = {
    "generate": ["生成", "创建", "新建", "写个场景", "写场景", "generate",
                 "做一个用例", "单元测试", "写个测试", "帮我写"],
    "debug":    ["为什么失败", "报错", "哪错了", "失败原因", "调一下", "debug",
                 "修一下", "不对", "排查", "为什么没通过"],
    "audit":    ["审计", "检查", "漏洞", "有没有问题", "audit", "核对",
                 "一致性", "评审一下", "合规"],
    "analyze":  ["分析", "解释", "讲讲", "这个 spec", "什么意思", "梳理",
                 "analyze", "覆盖", "统计"],
}


def route_mode(ctx: RouteContext) -> RouteResult:
    """三层信号路由。

    Args:
        ctx: 路由上下文（前端 + 后端信号组装完毕）

    Returns:
        RouteResult: 路由结果（mode / source / reason）
    """
    # ── 层 0：手动锁定 ──
    if ctx.locked_mode:
        return RouteResult(ctx.locked_mode, "manual", "用户手动锁定")

    # ── 层 1：工作台上下文信号（确定性最强）──
    if ctx.workspace_just_pulled:
        # K-007：信号源为 spec 签名变更（场景包文件真被修改），非单纯 pull 时间
        return RouteResult("audit", "context", "检测到 spec 文档变更（研发已修正），自动审计")
    if ctx.current_page == "execution" and ctx.last_run_failed:
        return RouteResult("debug", "context", "检测到失败运行，自动进入调试")
    if ctx.editing_scenario_id and ctx.scenario_never_run:
        return RouteResult("generate", "context", "场景从未运行，自动进入生成")
    if ctx.pending_vulnerabilities > 0 and ctx.current_page == "feedback":
        return RouteResult("audit", "context", "存在待处理漏洞，继续审计")

    # ── 层 2：消息意图（关键词匹配，零 LLM 调用）──
    msg = ctx.message.lower()
    best_mode, best_hits = "", 0
    for mode, keywords in INTENT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in msg)
        if hits > best_hits:
            best_mode, best_hits = mode, hits
    if best_mode:
        return RouteResult(best_mode, "intent", f"消息意图匹配（{best_hits} 个关键词）")

    # ── 层 3：默认 ──
    return RouteResult("chat", "default", "无明确意图，自由对话")
