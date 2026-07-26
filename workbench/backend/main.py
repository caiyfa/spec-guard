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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import scenarios, runs, reference, plans, spec_validation, agent, workspace, feedback

app = FastAPI(
    title="SpecGuard Workbench API",
    description="SpecGuard 测试流水线工作台后端：执行控制 / 场景管理 / 实时流",
    version="1.0.0",
)

# CORS：允许前端 dev server 跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(scenarios.router)
app.include_router(runs.router)
app.include_router(reference.router)
app.include_router(plans.router)
app.include_router(spec_validation.router)
app.include_router(agent.router)
app.include_router(workspace.router)
app.include_router(feedback.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "specguard-workbench"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9100)
