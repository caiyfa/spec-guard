@echo off
REM SpecGuard Workbench 一键停止

echo 停止 SpecGuard Workbench...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9100.*LISTENING" 2^>nul') do (
    echo   停止后端 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173.*LISTENING" 2^>nul') do (
    echo   停止前端 PID=%%a
    taskkill /PID %%a /F >nul 2>&1
)

echo 已停止。
