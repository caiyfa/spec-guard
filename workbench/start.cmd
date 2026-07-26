@echo off
REM ═══════════════════════════════════════════════════
REM  SpecGuard Workbench 一键启动
REM  后端: FastAPI (port 9100)  前端: Vite (port 5173)
REM ═══════════════════════════════════════════════════

setlocal EnableDelayedExpansion
cd /d %~dp0

echo.
echo  ================================================
echo   SpecGuard Workbench
echo  ================================================
echo.

REM ── 1. 杀掉旧进程 ──
echo [1/4] 清理旧进程...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9100.*LISTENING" 2^>nul') do (
    echo   杀掉后端进程 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING" 2^>nul') do (
    echo   杀掉前端进程 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

REM ── 2. 检查后端依赖 ──
echo [2/4] 检查后端依赖...
python -c "import fastapi, uvicorn, yaml" 2>nul
if errorlevel 1 (
    echo   安装后端依赖...
    pip install -q fastapi "uvicorn[standard]" websockets pyyaml
)

REM ── 3. 检查前端依赖 ──
echo [3/4] 检查前端依赖...
if not exist "frontend\node_modules" (
    echo   安装前端依赖...
    cd frontend && npm install --silent && cd ..
)

REM ── 4. 启动服务 ──
echo [4/4] 启动服务...

echo   后端  http://localhost:9100 (FastAPI + WebSocket)
start "SG-Backend" cmd /k "cd /d %~dp0backend && title SG-Backend :9100 && python -m uvicorn main:app --reload --port 9100"

timeout /t 2 /nobreak >nul

echo   前端  http://localhost:5173 (React + Vite)
start "SG-Frontend" cmd /k "cd /d %~dp0frontend && title SG-Frontend :5173 && npx vite --port 5173"

echo.
echo  ================================================
echo   SpecGuard Workbench 已启动
echo.
echo   工作台:    http://localhost:5173
echo   API 文档:  http://localhost:9100/docs
echo.
echo   关闭: 直接关闭弹出的两个命令行窗口即可
echo  ================================================
echo.

REM 等待 3 秒后自动打开浏览器
timeout /t 3 /nobreak >nul
start http://localhost:5173
