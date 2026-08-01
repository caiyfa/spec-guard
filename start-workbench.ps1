<#
.SYNOPSIS
    SpecGuard Workbench 本地开发一键启动（后端 FastAPI :9100 热重载 + 前端 Vite :5173）

.DESCRIPTION
    本地开发专用：
    - 依赖自检：Python 关键模块缺失自动 pip install；package.json 比 node_modules 新时自动 npm install
    - 后端：workbench/backend → uvicorn --reload :9100（SG_AUTH_MODE=mock，改代码自动重载）
    - 前端：workbench/frontend → npm run dev :5173（热更新）
    - 后台隐藏进程运行（不开新窗口），日志在 workbench/backend/data/logs/，PID 记录于 dev-pids.json
    - 端口归属校验：9100/5173 被非 SpecGuard 进程占用时报错退出
    - 幂等重启：自动终止上一轮后台进程（PID 文件 + 旧版标题窗口 + 端口兜底），确保运行最新代码
    生产部署请使用 serve-prod.ps1（单端口 9100，UAC SSO）。

.PARAMETER NoBrowser
    启动完成后不自动打开浏览器

.PARAMETER Stats
    只显示启动历史统计（不启动服务）

.EXAMPLE
    pwsh start-workbench.ps1
    pwsh start-workbench.ps1 -NoBrowser
    pwsh start-workbench.ps1 -Stats
#>
param(
    [switch]$NoBrowser,
    [switch]$Stats
)

$ErrorActionPreference = 'Stop'
$SgRoot      = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $SgRoot 'workbench\backend'
$FrontendDir = Join-Path $SgRoot 'workbench\frontend'
$LogDir      = Join-Path $SgRoot 'workbench\backend\data\logs'   # data/ 已 gitignore
$PidFile     = Join-Path $LogDir 'dev-pids.json'
$HistoryFile = Join-Path $LogDir 'start-history.jsonl'           # 启动历史（K-054）
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ── 启动历史统计（K-054：记录每次启动时间/结果/端口 PID，统计次数）──
function Get-StartHistory {
    if (-not (Test-Path $HistoryFile)) { return @() }
    $items = @()
    foreach ($line in (Get-Content $HistoryFile -Encoding utf8 -ErrorAction SilentlyContinue)) {
        if ($line.Trim()) { try { $items += ($line | ConvertFrom-Json) } catch {} }
    }
    return $items
}

function Show-StartStats([array]$History, [int]$Tail = 10) {
    $today = (Get-Date).ToString('yyyy-MM-dd')
    $todayCount = @($History | Where-Object { $_.ts -like "$today*" }).Count
    $okCount = @($History | Where-Object { $_.ok }).Count
    Write-Host "  累计启动 $($History.Count) 次（成功 $okCount / 失败 $($History.Count - $okCount)）· 今日 $todayCount 次" -ForegroundColor DarkCyan
    if ($History.Count -gt 0) {
        $last = $History[-1]
        Write-Host "  上次启动: $($last.ts)（$(if ($last.ok) { '就绪' } else { '未就绪' })）" -ForegroundColor DarkGray
    }
}

# -Stats：只看历史不启动
if ($Stats) {
    Write-Host "=== SpecGuard Workbench 启动历史 ===" -ForegroundColor Cyan
    $h = @(Get-StartHistory)
    Show-StartStats $h
    $h | Select-Object -Last 10 | ForEach-Object {
        $mark = if ($_.ok) { '✅' } else { '❌' }
        Write-Host ("  {0} {1}  auth={2} backend_pid={3} frontend_pid={4}" -f $mark, $_.ts, $_.auth, $_.backend_pid, $_.frontend_pid)
    }
    if ($h.Count -eq 0) { Write-Host "  （暂无记录）" -ForegroundColor DarkGray }
    exit 0
}

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
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -TimeoutSec 2 -UseBasicParsing
        return ($r.Content -match 'SpecGuard')
    } catch { return $false }
}

function Kill-Tree([int]$Id) {
    <# 递归终止进程及其全部子进程 #>
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$Id" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Kill-Tree $child.ProcessId }
    Stop-Process -Id $Id -Force -ErrorAction SilentlyContinue
}

function Stop-SgWindows {
    <# 按窗口标题关闭历史版本启动的 SpecGuard 前后端窗口（兼容旧版，连带终止其进程树） #>
    $wins = Get-Process pwsh -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like 'SpecGuard*' }
    foreach ($w in $wins) {
        Write-Host "  已关闭旧窗口: $($w.MainWindowTitle) (PID $($w.Id))" -ForegroundColor DarkGray
        Kill-Tree $w.Id
    }
}

function Stop-PreviousRun {
    <# 按 PID 文件终止上一轮隐藏后台进程（pwsh 宿主 + python/node 子进程树） #>
    if (-not (Test-Path $PidFile)) { return }
    try {
        $pids = Get-Content $PidFile -Raw | ConvertFrom-Json
        foreach ($p in @($pids)) {
            if (Get-Process -Id $p -ErrorAction SilentlyContinue) {
                Write-Host "  已终止上一轮进程树 (PID $p)" -ForegroundColor DarkGray
                Kill-Tree $p
            }
        }
    } catch {}
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

function Stop-PortProcess([int]$Port) {
    <# 终止占用指定端口的监听进程（递归杀子进程） #>
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        if (-not $procId) { continue }
        try {
            $proc = Get-Process -Id $procId -ErrorAction Stop
            Kill-Tree $procId
            Write-Host "  已终止进程 $procId ($($proc.ProcessName))" -ForegroundColor DarkGray
        } catch {}
    }
}

Write-Host "=== SpecGuard Workbench 开发模式启动 ===" -ForegroundColor Cyan
$startHistory = @(Get-StartHistory)
Show-StartStats $startHistory

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

# ── 清理上一轮进程（隐藏后台 PID 文件 + 旧版标题窗口；端口兜底仍在下方）──
Stop-PreviousRun
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
$backendOut = Join-Path $LogDir 'backend.log'
$backendErr = Join-Path $LogDir 'backend.err.log'
Write-Host "[启动] 后端 FastAPI  http://127.0.0.1:9100  (SG_AUTH_MODE=$authMode, --reload, 后台隐藏进程)" -ForegroundColor Green
$backendProc = Start-Process pwsh -ArgumentList @(
    '-NoProfile', '-Command',
    "Set-Location '$BackendDir'; if (-not `$env:SG_AUTH_MODE) { `$env:SG_AUTH_MODE = '$authMode' }; python -m uvicorn main:app --reload --reload-dir '$BackendDir' --reload-dir '$SgRoot\agent' --reload-dir '$SgRoot\mcp_server' --reload-dir '$SgRoot\engine' --reload-dir '$SgRoot\specstd' --reload-dir '$SgRoot\systems' --host 127.0.0.1 --port 9100"
) -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru

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

$frontendOut = Join-Path $LogDir 'frontend.log'
$frontendErr = Join-Path $LogDir 'frontend.err.log'
Write-Host "[启动] 前端 Vite     http://127.0.0.1:5173  (后台隐藏进程)" -ForegroundColor Green
$frontendProc = Start-Process pwsh -ArgumentList @(
    '-NoProfile', '-Command',
    "Set-Location '$FrontendDir'; npm run dev"
) -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru

# ── 记录 PID（下次运行先按此精确清理）──
@($backendProc.Id, $frontendProc.Id) | ConvertTo-Json | Set-Content $PidFile -Encoding utf8

# ── 健康等待（最长 60s）──
Write-Host "等待服务就绪" -NoNewline
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    if ((Test-OurBackend) -and (Test-OurFrontend)) { $ready = $true; break }
}
Write-Host ""

# ── 记录本次启动（K-054：时间/结果/认证模式/进程 PID 追加 jsonl）──
$record = [ordered]@{
    ts           = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    ok           = $ready
    auth         = $authMode
    backend_pid  = $backendProc.Id
    frontend_pid = $frontendProc.Id
}
($record | ConvertTo-Json -Compress) | Add-Content $HistoryFile -Encoding utf8

if ($ready) {
    Write-Host "启动完成 ✅（第 $($startHistory.Count + 1) 次启动）" -ForegroundColor Green
    Write-Host "  前端工作台:  http://127.0.0.1:5173  （mock 登录页：输工号直接登录）"
    Write-Host "  后端 API:    http://127.0.0.1:9100/docs  （--reload：改后端代码自动重载）"
    Write-Host "  后端日志:    $backendOut"
    Write-Host "  前端日志:    $frontendOut"
    Write-Host "  启动统计:    pwsh start-workbench.ps1 -Stats"
    Write-Host "  生产部署:    pwsh serve-prod.ps1"
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5173" }
} else {
    Write-Host "⚠️ 服务未在 60s 内就绪，请检查日志: $LogDir" -ForegroundColor Red
    exit 1
}
