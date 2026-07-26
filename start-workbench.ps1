<#
.SYNOPSIS
    SpecGuard Workbench 一键启动（后端 FastAPI :9100 + 前端 Vite :5173）

.DESCRIPTION
    - 后端：tests/specguard/workbench/backend → uvicorn main:app :9100（API 文档 /docs）
    - 前端：tests/specguard/workbench/frontend → npm run dev :5173（DAG 编排 /dag）
    - 幂等：端口已在监听则跳过对应服务；两个服务各起独立窗口便于看日志
    - 停止方式：直接关闭两个启动窗口（或 Stop-Process）

.PARAMETER NoBrowser
    启动完成后不自动打开浏览器

.EXAMPLE
    pwsh tests/specguard/start-workbench.ps1
    pwsh tests/specguard/start-workbench.ps1 -NoBrowser
#>
param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$SgRoot      = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $SgRoot 'workbench\backend'
$FrontendDir = Join-Path $SgRoot 'workbench\frontend'

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-Host "=== SpecGuard Workbench 一键启动 ===" -ForegroundColor Cyan

# ── 后端（FastAPI :9100）──
if (Test-Port 9100) {
    Write-Host "[跳过] 后端已在运行  http://127.0.0.1:9100" -ForegroundColor Yellow
} else {
    Write-Host "[启动] 后端 FastAPI  http://127.0.0.1:9100  (API 文档 /docs)" -ForegroundColor Green
    Start-Process pwsh -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$BackendDir'; python -m uvicorn main:app --host 127.0.0.1 --port 9100"
    ) -WindowStyle Normal
}

# ── 前端（Vite :5173）──
if (Test-Port 5173) {
    Write-Host "[跳过] 前端已在运行  http://localhost:5173" -ForegroundColor Yellow
} else {
    Write-Host "[启动] 前端 Vite     http://localhost:5173" -ForegroundColor Green
    Start-Process pwsh -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$FrontendDir'; npm run dev -- --port 5173 --strictPort"
    ) -WindowStyle Normal
}

# ── 健康等待（最长 60s）──
Write-Host "等待服务就绪" -NoNewline
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    if ((Test-Port 9100) -and (Test-Port 5173)) { $ready = $true; break }
}
Write-Host ""

if ($ready) {
    Write-Host "启动完成 ✅" -ForegroundColor Green
    Write-Host "  前端工作台:  http://localhost:5173/dag"
    Write-Host "  后端 API:    http://127.0.0.1:9100/docs"
    Write-Host "  停止方式:    关闭两个启动窗口即可"
    if (-not $NoBrowser) { Start-Process "http://localhost:5173/dag" }
} else {
    Write-Host "⚠️ 服务未在 60s 内就绪，请检查两个启动窗口的日志输出" -ForegroundColor Red
    exit 1
}
