"""SpecGuard Workbench — FastAPI 后端入口

启动方式：
    cd workbench/backend
    uvicorn main:app --reload --port 9100

或从仓库根目录：
    python -m uvicorn workbench.backend.main:app --reload --port 9100
"""

import sys
from pathlib import Path

# 确保 backend 目录在 sys.path 中（支持直接运行）
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

SG_ROOT = Path(__file__).resolve().parent.parent.parent

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import scenarios, runs, reference, plans, spec_validation, agent, workspace, feedback, drafts, auth, users, settings, notify, schedules, lifecycle, executions, specflow_interview, specflow_decisions, specflow_materials, specflow_freeze, specflow_gate_dock, zentao, coverage, data_fab, graph, lineage, agent_skills, audit, knowledge, feishu_pool, rbac, quality
from services.auth import get_current_user
from services import user_store, rbac_store
from services.menu_guard import MenuGuardMiddleware

app = FastAPI(
    title="SpecGuard Workbench API",
    description="SpecGuard 测试流水线工作台后端：多用户 + RBAC + 执行控制 / 场景管理 / 实时流",
    version="2.0.0",
)

# CORS：允许前端 dev server 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求级工作区上下文中间件（M7，纯 ASGI 保证 contextvar 向下游传播）：
# X-SG-Workspace header → specstd 上下文 → agent runtime / MCP 工具 / covers 闸全链路透传
class WorkspaceContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            from urllib.parse import unquote
            from specstd.workspace import set_context_workspace, reset_context_workspace
            headers = dict(scope.get("headers") or [])
            # 前端 encodeURIComponent 编码后入 header（中文名），此处 unquote 还原
            raw = unquote(headers.get(b"x-sg-workspace", b"").decode()).strip()
            token = set_context_workspace(raw or None)
            try:
                await self.app(scope, receive, send)
            finally:
                reset_context_workspace(token)
        else:
            await self.app(scope, receive, send)


app.add_middleware(WorkspaceContextMiddleware)
# RBAC 菜单守卫（前后端双控后端侧）：按 API path 匹配菜单授权，无权限 403
app.add_middleware(MenuGuardMiddleware)

# 启动初始化：建表 + 清理上一生命周期遗留的 running 队列项 + 旧会话迁移 + 启动调度器
@app.on_event("startup")
def _startup():
    user_store.init_db()
    rbac_store.init_db()  # RBAC 三表 + 幂等种子（全新配置：仅 admin 保底两条授权）
    # K-xxx：业务台账投影层建表（场景/草稿/运行/会话台账，文件仍是真相源）
    from services import ledger_store
    ledger_store.ensure_tables()
    # T-061: sg_draft_gates 三闸状态机建表
    from services import draft_gates
    draft_gates.ensure_tables()
    user_store.fail_stale_running()
    _migrate_legacy_sessions()
    # S2: specflow sf_* 表初始化
    from workbench.backend.services.specflow import sf_store
    sf_store.init_tables()
    from specflow.interview.decision_ledger import init_tables as dl_init
    import sqlite3
    from pathlib import Path
    try:
        conn = sqlite3.connect(str(Path(__file__).resolve().parent / "data" / "workbench.db"))
        dl_init(conn)
        conn.close()
    except Exception:
        pass
    # I-2: 启动定时任务调度器
    from services.scheduler import start_scheduler
    start_scheduler()
    # T-082: MCP 调用审计表初始化
    from services import audit_store
    audit_store.ensure_tables()
    # T-919（飞书知识图谱二期）：事件监听托管——单用户守卫，未配置静默跳过
    from services.specflow import feishu_watcher
    feishu_watcher.start_background(SG_ROOT)


@app.on_event("shutdown")
def _shutdown():
    # I-2: 停止定时任务调度器
    from services.scheduler import shutdown_scheduler
    shutdown_scheduler()
    # T-919：watcher 优雅停（关 stdin → EOF 优雅退出，禁 kill -9）
    from services.specflow import feishu_watcher
    feishu_watcher.stop_background()


def _migrate_legacy_sessions():
    """M7：单用户时代顶层会话文件迁移到 agent/sessions/_legacy/（只读归档）。"""
    import shutil

    sessions_root = SG_ROOT / "agent" / "sessions"
    if not sessions_root.is_dir():
        return
    legacy = sessions_root / "_legacy"
    for f in sessions_root.glob("*.jsonl"):
        legacy.mkdir(exist_ok=True)
        target = legacy / f.name
        if not target.exists():
            shutil.move(str(f), str(target))


# 注册路由（auth 公开认证配置；users 端点自带角色依赖；其余全部挂认证）
# 注意：runs / agent 路由内含 WebSocket 端点，Request 型依赖在 WS 上无法注入，
# 因此这两个路由改为端点级认证（HTTP 用 get_current_user，WS 用 get_current_user_ws）。
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(scenarios.router, dependencies=[Depends(get_current_user)])
app.include_router(runs.router)
app.include_router(reference.router, dependencies=[Depends(get_current_user)])
app.include_router(executions.router, dependencies=[Depends(get_current_user)])
app.include_router(plans.router, dependencies=[Depends(get_current_user)])
app.include_router(spec_validation.router, dependencies=[Depends(get_current_user)])
app.include_router(agent.router)
app.include_router(workspace.router, dependencies=[Depends(get_current_user)])
app.include_router(feedback.router, dependencies=[Depends(get_current_user)])
app.include_router(drafts.router, dependencies=[Depends(get_current_user)])
app.include_router(lifecycle.router, dependencies=[Depends(get_current_user)])
app.include_router(settings.router, dependencies=[Depends(get_current_user)])
app.include_router(notify.router, dependencies=[Depends(get_current_user)])
app.include_router(schedules.router, dependencies=[Depends(get_current_user)])
app.include_router(specflow_interview.router, dependencies=[Depends(get_current_user)])
app.include_router(specflow_decisions.router, dependencies=[Depends(get_current_user)])
app.include_router(specflow_materials.router, dependencies=[Depends(get_current_user)])
app.include_router(specflow_freeze.router, dependencies=[Depends(get_current_user)])
app.include_router(specflow_gate_dock.router, dependencies=[Depends(get_current_user)])
app.include_router(zentao.router, dependencies=[Depends(get_current_user)])
app.include_router(coverage.router, dependencies=[Depends(get_current_user)])
app.include_router(data_fab.router, dependencies=[Depends(get_current_user)])
app.include_router(graph.router, dependencies=[Depends(get_current_user)])
app.include_router(lineage.router, dependencies=[Depends(get_current_user)])
app.include_router(agent_skills.router, dependencies=[Depends(get_current_user)])
app.include_router(audit.router, dependencies=[Depends(get_current_user)])
app.include_router(knowledge.router, dependencies=[Depends(get_current_user)])
app.include_router(feishu_pool.router, dependencies=[Depends(get_current_user)])
app.include_router(rbac.router)  # RBAC 菜单/角色/授权（守卫在 MenuGuardMiddleware）
app.include_router(quality.router, dependencies=[Depends(get_current_user)])  # 质量中心（2026-08-14 基线可视化）


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "specguard-workbench"}


# ══════════════════════════════════════════════════════════
# 前端静态托管（服务化部署，M8）：单端口 9100 同时服务 API 与前端
# 前端构建：cd workbench/frontend && npm run build（产物 dist/）
# ══════════════════════════════════════════════════════════
from fastapi import HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

FRONTEND_DIST = SG_ROOT / "workbench" / "frontend" / "dist"
if FRONTEND_DIST.is_dir():
    # vite 构建的哈希资源（js/css，长缓存）
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    """SPA 兜底：API 以外的路径一律回 index.html（前端路由接管）。"""
    if full_path.startswith("api/") or full_path.startswith("api\\"):
        raise HTTPException(status_code=404, detail="API 不存在")
    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(
            status_code=503,
            detail="前端未构建：请先 cd workbench/frontend && npm run build，或使用 vite dev（:5173）")
    # 根级静态文件（favicon 等）直接返回
    if full_path and "/" not in full_path and ".." not in full_path:
        candidate = FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
    # index.html 不缓存（每次重新验证，保证 dist 更新后 F5 立即生效）
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9100)
