<#
.SYNOPSIS
    SpecGuard Workbench 本地开发一键启动（后端 FastAPI :9100 + 前端 Vite :5173）

.DESCRIPTION
    本地开发专用：
    - 依赖自检：Python 关键模块缺失自动 pip install；package.json 比 node_modules 新时自动 npm install
    - 后端：workbench/backend → uvicorn :9100（SG_AUTH_MODE=mock；默认不带 --reload，改后端代码需重新运行本脚本）
    - 前端：workbench/frontend → npm run dev :5173（热更新，改前端代码即时生效）
    - 前端 dist 自动构建：源码比 dist/ 新时自动 npm run build（9100 后端托管 dist 静态文件，
      不改构建则 9100 上的前端永远是旧版）
    - 后台隐藏进程运行（不开新窗口），日志在 workbench/backend/data/logs/，PID 记录于 dev-pids.json
    - 端口归属校验：9100/5173 被非 SpecGuard 进程占用时报错退出
    - 幂等重启：自动终止上一轮后台进程（PID 文件 + 旧版标题窗口 + 端口兜底），确保运行最新代码
    生产部署请使用 serve-prod.ps1（单端口 9100，UAC SSO）。

.PARAMETER Reload
    显式开启后端热重载（--reload）。默认关闭：任何文件保存不会触发后端重启，
    WebSocket 聊天连接不受影响；改后端代码后需重新运行本脚本生效。

.PARAMETER BackendOnly
    只重启后端 FastAPI（不动 Vite dev server / 5173）。
    改 Python 代码后的推荐重启方式：浏览器页面不刷新（vite 不重启就不会触发强制 reload），
    AgentChat 的 WS 断开后自动重连即可（服务就绪后几秒内）。

.PARAMETER NoBrowser
    启动完成后不自动打开浏览器

.PARAMETER Stats
    只显示启动历史统计（不启动服务）

.PARAMETER ListenAll
    后端绑定 0.0.0.0：局域网同事可通过 http://<本机IP>:9100 访问完整工作台（9100 托管 dist；
    5173 vite dev 仍仅本机）。⚠ mock 认证下任何人可用任意工号登录（含 admin），仅在内网可信环境使用。

.EXAMPLE
    pwsh start-workbench.ps1
    pwsh start-workbench.ps1 -NoBrowser
    pwsh start-workbench.ps1 -Reload   # 开启后端热重载（改代码自动重启，聊天会断连）
    pwsh start-workbench.ps1 -BackendOnly   # 只重启后端（改 Python 代码后推荐；页面不刷新）
    pwsh start-workbench.ps1 -ListenAll     # 局域网同事可通过 http://<本机IP>:9100 试用
    pwsh start-workbench.ps1 -Stats
#>
param(
    [switch]$Reload,
    [switch]$NoBrowser,
    [switch]$BackendOnly,
    [switch]$Stats,
    [switch]$ListenAll
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
        $reloadTag = if ($_.reload) { ' reload' } else { '' }
        Write-Host ("  {0} {1}  auth={2}{3} backend_pid={4} frontend_pid={5}" -f $mark, $_.ts, $_.auth, $reloadTag, $_.backend_pid, $_.frontend_pid)
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

# ── 依赖自检：Node（-BackendOnly 跳过：不动前端）──
if (-not $BackendOnly) {
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
}

# ── 前端构建（-BackendOnly 跳过；dist 缺失或源码更新时重建——9100 后端托管 dist，不重建则 9100 为旧版）──
$DistDir = Join-Path $FrontendDir 'dist'
if (-not $BackendOnly) {
    $needBuild = -not (Test-Path (Join-Path $DistDir 'index.html'))
    if (-not $needBuild) {
        $distTime = (Get-Item (Join-Path $DistDir 'index.html')).LastWriteTime
        $srcTime = (Get-ChildItem (Join-Path $FrontendDir 'src') -Recurse -File |
                    Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
        if ($srcTime -gt $distTime) { $needBuild = $true }
    }
    if ($needBuild) {
        Write-Host "[构建] 前端 dist（源码已更新）..." -ForegroundColor Green
        Push-Location $FrontendDir
        try {
            if (-not (Test-Path 'node_modules')) { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install 失败" } }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "前端构建失败（exit=$LASTEXITCODE）" }
        } finally { Pop-Location }
    } else {
        Write-Host "[跳过] 前端 dist 已是最新" -ForegroundColor DarkGray
    }
}

# ── 清理上一轮进程（隐藏后台 PID 文件 + 旧版标题窗口；端口兜底仍在下方）──
# -BackendOnly：只杀后端（PID 数组约定 [0]=backend [1]=frontend），Vite 保留运行
if ($BackendOnly) {
    if (Test-Path $PidFile) {
        try {
            $pids = Get-Content $PidFile -Raw | ConvertFrom-Json
            $bePid = @($pids)[0]
            if ($bePid -and (Get-Process -Id $bePid -ErrorAction SilentlyContinue)) {
                Write-Host "  已终止上一轮后端进程树 (PID $bePid)" -ForegroundColor DarkGray
                Kill-Tree $bePid
            }
        } catch {}
        # PID 文件保留 frontend PID（下轮全量重启仍需清理），交给下方写入时更新
    }
    Stop-SgWindows | Out-Null
} else {
    Stop-PreviousRun
    Stop-SgWindows
}

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
# -ListenAll：0.0.0.0 全接口监听（局域网同事可访问 9100）；默认 127.0.0.1 仅本机
$bindHost = if ($ListenAll) { '0.0.0.0' } else { '127.0.0.1' }
$lanIps = @()
if ($ListenAll) {
    $lanIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.InterfaceAlias -notmatch 'Loopback|vEthernet|VMware|VirtualBox' } |
        Select-Object -ExpandProperty IPAddress -Unique)
    if ($authMode -eq 'mock') {
        Write-Host "[警告] 0.0.0.0 + mock 认证：局域网内任何人可用任意工号登录（含你的工号/admin），仅在内网可信环境、试用期间使用" -ForegroundColor Yellow
    }
}
$backendOut = Join-Path $LogDir 'backend.log'
$backendErr = Join-Path $LogDir 'backend.err.log'
# 热重载：默认关闭（改文件不重启后端，WS 聊天不断连）；-Reload 显式开启
$reloadArgs = ''
if ($Reload) {
    $reloadArgs = " --reload --reload-dir '$BackendDir' --reload-dir '$SgRoot\agent' --reload-dir '$SgRoot\mcp_server' --reload-dir '$SgRoot\engine' --reload-dir '$SgRoot\specstd' --reload-dir '$SgRoot\systems'"
}
# WS ping 超时调大到 120s（默认 20s），LLM 生成长回复期间不因协议层 ping timeout 断连
$wsPingArgs = ' --ws-ping-interval 30 --ws-ping-timeout 120'
Write-Host "[启动] 后端 FastAPI  http://${bindHost}:9100  (SG_AUTH_MODE=$authMode, reload=$(if ($Reload) { 'ON' } else { 'OFF' }), ws-ping-timeout=120s, 后台隐藏进程)" -ForegroundColor Green
$backendProc = Start-Process pwsh -ArgumentList @(
    '-NoProfile', '-Command',
    "Set-Location '$BackendDir'; if (-not `$env:SG_AUTH_MODE) { `$env:SG_AUTH_MODE = '$authMode' }; python -m uvicorn main:app$reloadArgs$wsPingArgs --host $bindHost --port 9100"
) -WindowStyle Hidden -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru

# ── 前端（Vite :5173，-BackendOnly 跳过：不动 Vite 就不会触发浏览器页面强制 reload）──
$frontendOut = Join-Path $LogDir 'frontend.log'
$frontendErr = Join-Path $LogDir 'frontend.err.log'
$frontendProc = $null
$keepFrontendPid = $null
if ($BackendOnly) {
    # 保留现有 Vite：PID 供写入 PID 文件（下轮全量重启仍可清理）
    if (Test-Path $PidFile) {
        try { $keepFrontendPid = @(Get-Content $PidFile -Raw | ConvertFrom-Json)[1] } catch {}
    }
    if (Test-OurFrontend) {
        Write-Host "[保留] 前端 Vite 继续运行（-BackendOnly）" -ForegroundColor DarkGray
    } else {
        Write-Host "[提示] 前端 Vite 未运行（-BackendOnly 不启动它；需要前端请去掉 -BackendOnly）" -ForegroundColor Yellow
    }
} else {
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

    Write-Host "[启动] 前端 Vite     http://127.0.0.1:5173  (后台隐藏进程)" -ForegroundColor Green
    $frontendProc = Start-Process pwsh -ArgumentList @(
        '-NoProfile', '-Command',
        "Set-Location '$FrontendDir'; npm run dev"
    ) -WindowStyle Hidden -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -PassThru
}

# ── 记录 PID（下次运行先按此精确清理；-BackendOnly 保留 frontend PID）──
$frontendPidVal = if ($frontendProc) { $frontendProc.Id } else { $keepFrontendPid }
$pidList = @($backendProc.Id) | Where-Object { $_ }
if ($frontendPidVal) { $pidList = @($backendProc.Id, $frontendPidVal) }
$pidList | ConvertTo-Json | Set-Content $PidFile -Encoding utf8

# ── 健康等待（最长 60s；-BackendOnly 只等后端）──
Write-Host "等待服务就绪" -NoNewline
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    if ($BackendOnly) {
        if (Test-OurBackend) { $ready = $true; break }
    } else {
        if ((Test-OurBackend) -and (Test-OurFrontend)) { $ready = $true; break }
    }
}
Write-Host ""

# ── 记录本次启动（K-054：时间/结果/认证模式/热重载/进程 PID 追加 jsonl；-BackendOnly 标记）──
$record = [ordered]@{
    ts           = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    ok           = $ready
    auth         = $authMode
    reload       = [bool]$Reload
    backend_only = [bool]$BackendOnly
    backend_pid  = $backendProc.Id
    frontend_pid = $frontendPidVal
}
($record | ConvertTo-Json -Compress) | Add-Content $HistoryFile -Encoding utf8

if ($ready) {
    Write-Host "启动完成 ✅（第 $($startHistory.Count + 1) 次启动）" -ForegroundColor Green
    Write-Host "  前端工作台:  http://127.0.0.1:9100  （dist 构建产物，源码改动自动重建）"
    if ($ListenAll) {
        foreach ($ip in $lanIps) {
            Write-Host "  局域网访问:  http://${ip}:9100  （同事试用入口，dist 完整工作台）" -ForegroundColor Cyan
        }
        if ($lanIps.Count -eq 0) {
            Write-Host "  局域网访问:  未检测到 LAN IPv4，请用 ipconfig 确认本机 IP 后告知同事" -ForegroundColor Yellow
        }
        Write-Host "  防火墙提示:  首次绑定 0.0.0.0 如弹 Windows 防火墙请选择允许；同事仍不通时手动放行 9100 入站" -ForegroundColor DarkGray
    }
    Write-Host "  dev 热更新:   http://127.0.0.1:5173  （vite dev，改前端源码即时生效）"
    if ($Reload) {
        Write-Host "  后端 API:    http://127.0.0.1:9100/docs  （热重载 ON：改后端代码自动重载，WS 聊天会断连重连）" -ForegroundColor Yellow
    } else {
        Write-Host "  后端 API:    http://127.0.0.1:9100/docs  （热重载 OFF：改后端代码需重跑本脚本生效，WS 聊天不受影响）"
    }
    Write-Host "  WS 超时:    ws-ping-timeout=120s（LLM 长回复不因协议层 ping 断连）"
    if ($BackendOnly) {
        Write-Host "  本次仅重启后端（-BackendOnly）：页面无需刷新，AgentChat 会自动重连" -ForegroundColor Cyan
    } else {
        Write-Host "  提示:      若浏览器已开着工作台页面，请刷新后再使用（vite 重启会强制页面 reload）" -ForegroundColor Cyan
    }
    Write-Host "  后端日志:    $backendOut"
    Write-Host "  前端日志:    $frontendOut"
    Write-Host "  启动统计:    pwsh start-workbench.ps1 -Stats"
    Write-Host "  生产部署:    pwsh serve-prod.ps1"
    if (-not $NoBrowser) { Start-Process "http://127.0.0.1:9100" }
} else {
    Write-Host "⚠️ 服务未在 60s 内就绪，请检查日志: $LogDir" -ForegroundColor Red
    exit 1
}
