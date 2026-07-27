<#
.SYNOPSIS
    SpecGuard Workbench 一键启动（开发模式 / 生产模式）

.DESCRIPTION
    开发模式（默认）：
    - 后端：workbench/backend → uvicorn main:app :9100（SG_AUTH_MODE=mock，本地登录页）
    - 前端：workbench/frontend → npm run dev :5173（热更新）
    生产模式（-Prod）：
    - 前端先构建（npm run build → dist/）
    - 单进程 uvicorn :9100 托管 API + 前端（SG_AUTH_MODE=uac，集团 SSO）
    - ⚠ 必须 workers=1：RunManager 全局单例 + SQLite，多 worker 会破坏队列与状态
    - 幂等：端口已在监听则跳过对应服务

.PARAMETER Prod
    生产模式：构建前端并以单端口 9100 服务（UAC 认证）

.PARAMETER NoBrowser
    启动完成后不自动打开浏览器

.EXAMPLE
    pwsh start-workbench.ps1                 # 开发模式（mock 登录）
    pwsh start-workbench.ps1 -Prod           # 生产模式（UAC SSO，单端口 9100）
    pwsh start-workbench.ps1 -Prod -NoBrowser
#>
param(
    [switch]$Prod,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$SgRoot      = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $SgRoot 'workbench\backend'
$FrontendDir = Join-Path $SgRoot 'workbench\frontend'

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if ($Prod) {
    Write-Host "=== SpecGuard Workbench 生产模式启动 ===" -ForegroundColor Cyan

    # ── 前端构建 ──
    Write-Host "[构建] 前端 dist ..." -ForegroundColor Green
    Push-Location $FrontendDir
    try {
        if (-not (Test-Path 'node_modules')) { npm install }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败（exit=$LASTEXITCODE）" }
    } finally {
        Pop-Location
    }

    # ── 单进程服务（API + 前端 :9100）──
    if (Test-Port 9100) {
        Write-Host "[跳过] 服务已在运行  http://127.0.0.1:9100" -ForegroundColor Yellow
    } else {
        if (-not $env:SG_AUTH_MODE) { $env:SG_AUTH_MODE = 'uac' }
        if (-not $env:SG_UAC_BASE) { $env:SG_UAC_BASE = 'http://sit-ha.fehorizon.com/femsp/uac' }
        Write-Host "[启动] 生产服务  http://0.0.0.0:9100  (SG_AUTH_MODE=$env:SG_AUTH_MODE, workers=1)" -ForegroundColor Green
        Start-Process pwsh -ArgumentList @(
            '-NoExit', '-Command',
            "Set-Location '$BackendDir'; `$env:SG_AUTH_MODE='$env:SG_AUTH_MODE'; `$env:SG_UAC_BASE='$env:SG_UAC_BASE'; python -m uvicorn main:app --host 0.0.0.0 --port 9100 --workers 1"
        ) -WindowStyle Normal
    }

    Write-Host "启动完成 ✅  访问: http://{服务器地址}:9100" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:9100" }
    exit 0
}

Write-Host "=== SpecGuard Workbench 开发模式启动 ===" -ForegroundColor Cyan

# ── 后端（FastAPI :9100，mock 认证）──
if (Test-Port 9100) {
    Write-Host "[跳过] 后端已在运行  http://127.0.0.1:9100" -ForegroundColor Yellow
} else {
    $authMode = if ($env:SG_AUTH_MODE) { $env:SG_AUTH_MODE } else { 'mock' }
    Write-Host "[启动] 后端 FastAPI  http://127.0.0.1:9100  (SG_AUTH_MODE=$authMode, API 文档 /docs)" -ForegroundColor Green
    Start-Process pwsh -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$BackendDir'; if (-not `$env:SG_AUTH_MODE) { `$env:SG_AUTH_MODE = '$authMode' }; python -m uvicorn main:app --host 127.0.0.1 --port 9100"
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
    Write-Host "  前端工作台:  http://localhost:5173  （mock 登录页：输工号直接登录）"
    Write-Host "  后端 API:    http://127.0.0.1:9100/docs"
    Write-Host "  停止方式:    关闭两个启动窗口即可"
    if (-not $NoBrowser) { Start-Process "http://localhost:5173" }
} else {
    Write-Host "⚠️ 服务未在 60s 内就绪，请检查两个启动窗口的日志输出" -ForegroundColor Red
    exit 1
}
