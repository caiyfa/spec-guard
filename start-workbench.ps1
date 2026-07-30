<#
.SYNOPSIS
    SpecGuard Workbench 本地开发一键启动（后端 FastAPI :9100 热重载 + 前端 Vite :5173）

.DESCRIPTION
    本地开发专用：
    - 依赖自检：Python 关键模块缺失自动 pip install；package.json 比 node_modules 新时自动 npm install
    - 后端：workbench/backend → uvicorn --reload :9100（SG_AUTH_MODE=mock，改代码自动重载）
    - 前端：workbench/frontend → npm run dev :5173（热更新）
    - 端口归属校验：9100/5173 被非 SpecGuard 进程占用时报错退出
    - 幂等重启：自动关闭上一轮 SpecGuard 启动窗口（SpecGuard* 标题）并终止残留进程（确保运行最新代码）
    生产部署请使用 serve-prod.ps1（单端口 9100，UAC SSO）。

.PARAMETER NoBrowser
    启动完成后不自动打开浏览器

.EXAMPLE
    pwsh start-workbench.ps1
    pwsh start-workbench.ps1 -NoBrowser
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

function Test-OurBackend {
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:9100/api/health' -TimeoutSec 2
        return ($r.service -eq 'specguard-workbench')
    } catch { return $false }
}

function Test-OurFrontend {
    try {
        $r = Invoke-WebRequest -Uri 'http://localhost:5173' -TimeoutSec 2 -UseBasicParsing
        return ($r.Content -match 'SpecGuard')
    } catch { return $false }
}

function Stop-SgWindows {
    <# 按窗口标题关闭上一轮启动的 SpecGuard 前后端窗口（连带终止其进程树） #>
    $wins = Get-Process pwsh -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like 'SpecGuard*' }
    foreach ($w in $wins) {
        Write-Host "  已关闭旧窗口: $($w.MainWindowTitle) (PID $($w.Id))" -ForegroundColor DarkGray
        Stop-Process -Id $w.Id -Force -ErrorAction SilentlyContinue
    }
}

function Stop-PortProcess([int]$Port) {
    <# 终止占用指定端口的监听进程（递归杀子进程） #>
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        if (-not $procId) { continue }
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            # 递归终止子进程
            function Kill-Tree([int]$Id) {
                $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$Id" -ErrorAction SilentlyContinue
                foreach ($child in $children) { Kill-Tree $child.ProcessId }
                Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
            }
            Kill-Tree $procId
            Write-Host "  已终止进程 $procId ($($proc.ProcessName))" -ForegroundColor DarkGray
        } catch {}
    }
}

Write-Host "=== SpecGuard Workbench 开发模式启动 ===" -ForegroundColor Cyan

# ── 依赖自检：Python ──
Write-Host "[检查] Python 依赖 ..." -ForegroundColor Green
# 单行 + 仅单引号（PowerShell 传原生参数对嵌入双引号会截断）
$pyCheck = "import importlib.util as u; mods={'fastapi':'fastapi','uvicorn':'uvicorn[standard]','httpx':'httpx','yaml':'pyyaml','pymysql':'pymysql','requests':'requests','pytest':'pytest','websockets':'websockets','mcp':'mcp','jsonpath_ng':'jsonpath-ng'}; print(' '.join([p for m,p in mods.items() if not u.find_spec(m)]))"
$missingPy = (python -c $pyCheck) -join ' '
if ($LASTEXITCODE -ne 0) { throw "Python 依赖自检执行失败（检查 python 是否在 PATH）" }
if ($missingPy.Trim()) {
    Write-Host "  缺少: $missingPy → 自动安装 requirements" -ForegroundColor Yellow
    python -m pip install -r (Join-Path $SgRoot 'requirements.txt') -r (Join-Path $BackendDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw "Python 依赖安装失败" }
}

# ── 依赖自检：Node ──
$nmDir = Join-Path $FrontendDir 'node_modules'
$needNpm = -not (Test-Path $nmDir)
if (-not $needNpm) {
    $pkgTime = (Get-Item (Join-Path $FrontendDir 'package.json')).LastWriteTime
    $nmTime = (Get-Item $nmDir).LastWriteTime
    if ($pkgTime -gt $nmTime) { $needNpm = $true }
}
if ($needNpm) {
    Write-Host "[安装] 前端依赖（npm install）..." -ForegroundColor Green
    Push-Location $FrontendDir
    try { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install 失败" } }
    finally { Pop-Location }
}

# ── 关闭上一轮启动的旧窗口（SpecGuard* 标题，连带杀进程树；端口兜底仍在下方）──
Stop-SgWindows

# ── 后端（FastAPI :9100，--reload 热重载 + mock 认证）──
if (Test-Port 9100) {
    if (Test-OurBackend) {
        Write-Host "[重启] 后端已在运行，先终止旧进程..." -ForegroundColor Yellow
        Stop-PortProcess 9100
        Start-Sleep -Seconds 1
    } else {
        Write-Host "[错误] 端口 9100 被其他进程占用（非 SpecGuard），请先释放该端口" -ForegroundColor Red
        exit 1
    }
}

$authMode = if ($env:SG_AUTH_MODE) { $env:SG_AUTH_MODE } else { 'mock' }
Write-Host "[启动] 后端 FastAPI  http://127.0.0.1:9100  (SG_AUTH_MODE=$authMode, --reload)" -ForegroundColor Green
Start-Process pwsh -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$BackendDir'; `$host.UI.RawUI.WindowTitle = 'SpecGuard 后端 :9100'; if (-not `$env:SG_AUTH_MODE) { `$env:SG_AUTH_MODE = '$authMode' }; python -m uvicorn main:app --reload --reload-dir '$BackendDir' --reload-dir '$SgRoot\agent' --reload-dir '$SgRoot\mcp_server' --reload-dir '$SgRoot\engine' --reload-dir '$SgRoot\specstd' --reload-dir '$SgRoot\systems' --host 127.0.0.1 --port 9100"
) -WindowStyle Normal

# ── 前端（Vite :5173）──
if (Test-Port 5173) {
    if (Test-OurFrontend) {
        Write-Host "[重启] 前端已在运行，先终止旧进程..." -ForegroundColor Yellow
        Stop-PortProcess 5173
        Start-Sleep -Seconds 1
    } else {
        Write-Host "[错误] 端口 5173 被其他进程占用（非 SpecGuard 前端），请先释放该端口" -ForegroundColor Red
        exit 1
    }
}

Write-Host "[启动] 前端 Vite     http://localhost:5173" -ForegroundColor Green
Start-Process pwsh -ArgumentList @(
    '-NoExit', '-Command',
    "Set-Location '$FrontendDir'; `$host.UI.RawUI.WindowTitle = 'SpecGuard 前端 :5173'; npm run dev -- --port 5173 --strictPort"
) -WindowStyle Normal

# ── 健康等待（最长 60s）──
Write-Host "等待服务就绪" -NoNewline
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    if ((Test-OurBackend) -and (Test-OurFrontend)) { $ready = $true; break }
}
Write-Host ""

if ($ready) {
    Write-Host "启动完成 ✅" -ForegroundColor Green
    Write-Host "  前端工作台:  http://localhost:5173  （mock 登录页：输工号直接登录）"
    Write-Host "  后端 API:    http://127.0.0.1:9100/docs  （--reload：改后端代码自动重载）"
    Write-Host "  生产部署:    pwsh serve-prod.ps1"
    if (-not $NoBrowser) { Start-Process "http://localhost:5173" }
} else {
    Write-Host "⚠️ 服务未在 60s 内就绪，请检查两个启动窗口的日志输出" -ForegroundColor Red
    exit 1
}
