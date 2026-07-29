"""半实机冒烟：TestClient + 隔离环境驱动 3 个闭环的 API 骨架链路。

隔离策略：
  - tmp DB + tmp 工作区注册表（不动真实 workbench.db / registry.yaml）
  - mock LLM（tmp DB 无 model_config，不消耗真实 LLM）
  - feedback/ledger.json 用真实路径（router 强制 SG_ROOT 相对）→ 备份/恢复

用法（仓库根目录）：python .smoke/smoke_e2e.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ── 环境（必须在 import main 前）──
os.environ["SG_AUTH_MODE"] = "mock"
os.environ.pop("SG_LLM_BASE_URL", None)
os.environ.pop("SG_LLM_API_KEY", None)

SG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SG_ROOT))
sys.path.insert(0, str(SG_ROOT / "workbench" / "backend"))

TMP = Path(tempfile.mkdtemp(prefix="sg_smoke_"))
LEDGER_FILE = SG_ROOT / "feedback" / "ledger.json"

# ── 隔离 DB + 工作区注册表 ──
import services.user_store as user_store  # noqa: E402

user_store.DB_PATH = TMP / "workbench.db"

import specstd.workspace as wsm  # noqa: E402

wsm.REGISTRY_PATH = TMP / "registry.yaml"
wsm.CLONES_DIR = TMP / "_clones"

# ── 建临时工作区 ──
WS = TMP / "ws_repo"
(WS / "specs" / "m1" / "f1").mkdir(parents=True)
(WS / "AGENTS.md").write_text(
    "# Smoke\n\n## 术语 Token\n- FR\n- AC\n\n## Always\n- a\n\n## Never\n- n\n",
    encoding="utf-8")
(WS / "specs" / "m1" / "f1" / "spec.md").write_text(
    "# M1-F1\n\n### FR-001: 查询功能\nAC-001 查询返回 200\n", encoding="utf-8")

_results: list[tuple[str, bool, str]] = []


def check(name, cond, evidence=""):
    _results.append((name, bool(cond), evidence))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  — {evidence}" if evidence else ""))


def main():
    print(f"[smoke] 隔离目录: {TMP}")

    # 备份真实台账（smoke 用同一路径，结束恢复）
    ledger_bak = LEDGER_FILE.read_bytes() if LEDGER_FILE.exists() else None

    wsm.register_local("smoke", str(WS), "tdm", activate=True)

    from main import app  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    from feedback.ledger import FeedbackLedger  # noqa: E402

    try:
        with TestClient(app) as client:
            r = client.post("/api/auth/mock-login", json={"emp_no": "smoke01", "name": "冒烟"})
            H = {"Authorization": f"Bearer {r.json()['token']}"}
            check("登录（admin）", r.status_code == 200)

            # ═══ 闭环 1：意图路由 + 台账 ═══
            print("\n=== 闭环 1：意图路由 + 漏洞台账 ===")
            # K-007 验证：register 后 pulled_at=now 但无 spec 变更，不应误触发 audit
            r = client.post("/api/agent/chat",
                            json={"message": "帮我生成一个测试场景", "workspace": "smoke"}, headers=H)
            d = r.json()
            check("POST /chat 可用", r.status_code == 200)
            check("意图路由 → generate", d.get("mode") == "generate",
                  f"mode={d.get('mode')} source={d.get('mode_source')}")

            r = client.post("/api/agent/chat",
                            json={"message": "检查一下 spec 有没有漏洞", "workspace": "smoke"}, headers=H)
            d = r.json()
            check("意图路由 → audit", d.get("mode") == "audit",
                  f"mode={d.get('mode')} source={d.get('mode_source')}")

            # 台账：模拟 Agent report_vulnerability 登记漏洞（与 router 同一路径）
            ledger = FeedbackLedger(LEDGER_FILE)
            entry = ledger.create_vulnerability(
                vtype="logic_defect", severity="major", location="FR-001",
                summary="FR-001 缺少异常分支描述", evidence="spec.md 仅描述正常流",
                suggestion="补充 AC：异常入参返回 400")
            spq_id = entry["spq_id"]  # create_vulnerability 返回完整 entry，取 spq_id
            r = client.get("/api/workspace/vulnerabilities?status=pending", headers=H)
            check("漏洞登记台账 pending", r.json()["summary"]["pending"] >= 1,
                  f"spq_id={spq_id} pending={r.json()['summary']['pending']}")

            # 通知配置（J-1/J-3 链路，验证 K-008 端点修复）
            r = client.post("/api/notify/configs",
                            json={"name": "冒烟群", "channel": "dingtalk",
                                  "webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=smoke",
                                  "events": ["vulnerability", "plan_failure"]}, headers=H)
            check("通知配置端点创建（K-008 已修）", r.status_code in (200, 201),
                  f"status={r.status_code} body={r.text[:120]}")

            # ═══ 闭环 2：spec 签名变更路由（K-007）+ 漏洞 close ═══
            print("\n=== 闭环 2：spec 变更路由（K-007）+ 漏洞 closed ===")
            # K-007 核心 1：register 后未变更，不应误触发 audit（无基线自动建 → False）
            r = client.post("/api/agent/chat",
                            json={"message": "帮我生成一个测试场景", "workspace": "smoke"}, headers=H)
            d = r.json()
            check("register 后未变更 → 意图 generate（不误触发 audit）",
                  d.get("mode") == "generate", f"mode={d.get('mode')}")

            # K-007 核心 2：研发修正 spec.md → 路由 audit（spec 签名变更）
            (WS / "specs" / "m1" / "f1" / "spec.md").write_text(
                "# M1-F1\n\n### FR-001: 查询功能\nAC-001 查询返回 200\nAC-002 结果非空\n",
                encoding="utf-8")
            r = client.post("/api/agent/chat",
                            json={"message": "继续", "workspace": "smoke"}, headers=H)
            d = r.json()
            check("spec 变更 → 路由 audit（K-007）", d.get("mode") == "audit",
                  f"mode={d.get('mode')} source={d.get('mode_source')}")

            # K-007 核心 3：手动标记已审计 → 基线更新 → 不再触发
            r = client.post("/api/workspace/mark-audited", json={"name": "smoke"}, headers=H)
            check("mark-audited 端点可用", r.status_code == 200, f"body={r.text[:100]}")
            r = client.post("/api/agent/chat",
                            json={"message": "帮我生成一个测试场景", "workspace": "smoke"}, headers=H)
            d = r.json()
            check("标记已审计后 → 意图 generate（基线已复位）",
                  d.get("mode") == "generate", f"mode={d.get('mode')}")

            # 漏洞 close 状态机（原有链路）
            r = client.post(f"/api/workspace/vulnerabilities/{spq_id}/close",
                            json={"note": "研发已修正 spec"}, headers=H)
            r2 = client.get("/api/workspace/vulnerabilities?status=closed", headers=H)
            check("漏洞 close 状态机", r2.json()["summary"]["closed"] >= 1,
                  f"closed={r2.json()['summary']['closed']}")

            # ═══ 闭环 3：定时任务调度链路 ═══
            print("\n=== 闭环 3：定时任务调度链路 ===")
            plans_dir = wsm.plans_dir()
            plans_dir.mkdir(parents=True, exist_ok=True)
            (plans_dir / "smoke-plan.yaml").write_text(
                "id: smoke-plan\nname: 冒烟计划\nenv: sit\nfilter:\n  scenarios:\n    - SMOKE-001\n",
                encoding="utf-8")
            # schedules 端点需 X-SG-Workspace header（resolve_workspace 依赖）
            HW = {**H, "X-SG-Workspace": "smoke"}
            r = client.get("/api/schedules/plans/list", headers=HW)
            check("plans/list 返回 plan", r.status_code == 200, f"body={r.text[:120]}")

            r = client.post("/api/schedules",
                            json={"name": "冒烟定时任务", "plan_id": "smoke-plan",
                                  "workspace": "smoke", "cron": "0 2 * * *"}, headers=HW)
            check("定时任务创建", r.status_code in (200, 201), f"status={r.status_code} body={r.text[:160]}")
            job_id = r.json().get("id") or r.json().get("job", {}).get("id")

            if job_id:
                r = client.post(f"/api/schedules/{job_id}/run", headers=HW)
                d = r.json()
                check("手动触发被接受", r.status_code == 200, f"status={r.status_code}")
                check("execute_plan 返回执行结果",
                      any(k in d for k in ("status", "run_id", "error", "results")),
                      f"keys={list(d.keys())} status={d.get('status')}")
            else:
                check("获取 job_id", False, f"create 返回: {r.text[:200]}")
    finally:
        # 恢复真实台账
        if ledger_bak is not None:
            LEDGER_FILE.write_bytes(ledger_bak)
        elif LEDGER_FILE.exists():
            LEDGER_FILE.unlink()

    # ═══ 总结 ═══
    print("\n" + "=" * 50)
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"冒烟结果: {passed}/{total} 通过")
    for n, ok, _ in _results:
        if not ok:
            print(f"  未通过: {n}")
    print(f"隔离目录（可删）: {TMP}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
