"""质量中心 API（2026-08-14 基线可视化）。

端点：
- GET  /api/quality/latest       — 各工具最近一次扫描（未扫描返回带基线的空态）
- POST /api/quality/scan/{tool}  — 单工具按需扫描（oxlint/ruff/knip/jscpd/vulture）

RBAC：admin/tester（计划 §4.2）。仓库级能力，与工作区无关（不走 X-SG-Workspace）。
扫描纯读：不提供任何 --fix 入口（报告模式治理基调，计划 §4.3）。
"""

from fastapi import APIRouter, Depends, HTTPException

from services.auth import require_role
from services import quality_scan

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/latest")
def latest(user=Depends(require_role("admin", "tester"))):
    """各工具最近扫描结果（内存缓存；页面加载只读此接口，不自动触发扫描）。"""
    return quality_scan.latest()


@router.post("/scan/{tool}")
def scan_tool(tool: str, user=Depends(require_role("admin", "tester"))):
    """单工具按需扫描（subprocess，秒级；knip ~10s / jscpd ~20s 内）。"""
    try:
        return quality_scan.run_tool(tool)
    except quality_scan.QualityScanError as e:
        raise HTTPException(status_code=404, detail=str(e))
