<#
.SYNOPSIS
    SpecGuard Workbench 生产部署启动（服务器单端口 9100，UAC SSO）

.DESCRIPTION
    服务器部署专用：
    - 依赖自检（Python 缺失自动安装；前端构建产物 dist 过期自动重建）
    - 单进程 uvicorn :9100 托管 API + 前端（SPA 兜底）
    - ⚠ workers=1 硬约束：RunManager 全局单例 + SQLite，多 worker 会破坏队列与状态
    - SG_AUTH_MODE=uac（集团 Authing SSO），SG_UAC_BASE 默认 SIT 内网地址（生产用 -UacBase 覆盖）
    - 健康等待（/api/health 就绪确认）+ 部署检查清单输出
    本地开发请使用 start-workbench.ps1（热重载 + mock 登录）。

.PARAMETER UacBase
    UAC 地址。默认 SIT 内网；生产环境应传 'http://ha.fehorizon.com/femsp/uac'

.PARAMETER Port
    服务端口（默认 9100）

.PARAMETER OpenBrowser
    启动完成后打开浏览器（服务器上一般不需要）

.EXAMPLE
    pwsh serve-prod.ps1                                            # SIT 联调
    pwsh serve-prod.ps1 -UacBase 'http://ha.fehorizon.com/femsp/uac'  # 生产环境
#>
param(
    [string]$UacBase = 'http://sit-ha.fehorizon.com/femsp/uac',
    [int]$Port = 9100,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$SgRoot      = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir  = Join-Path $SgRoot 'workbench\backend'
$FrontendDir = Join-Path $SgRoot 'workbench\frontend'
$DistDir     = Join-Path $FrontendDir 'dist'

function Test-Port([int]$P) {
    return [bool](Get-NetTCPConnection -LocalPort $P -State Listen -ErrorAction SilentlyContinue)
}

function Test-OurBackend([int]$P) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$P/api/health" -TimeoutSec 2
        return ($r.service -eq 'specguard-workbench')
    } catch { return $false }
}

Write-Host "=== SpecGuard Workbench 生产部署启动 ===" -ForegroundColor Cyan

# ── 生产域名提示 ──
if ($UacBase -match 'sit') {
    Write-Host "[提示] SG_UAC_BASE 指向 SIT 地址；生产环境请用 -UacBase 'http://ha.fehorizon.com/femsp/uac'" -ForegroundColor Yellow
}

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

# ── 前端构建（dist 缺失或源码更新时重建）──
$needBuild = -not (Test-Path (Join-Path $DistDir 'index.html'))
if (-not $needBuild) {
    $distTime = (Get-Item (Join-Path $DistDir 'index.html')).LastWriteTime
    $srcTime = (Get-ChildItem (Join-Path $FrontendDir 'src') -Recurse -File |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    if ($srcTime -gt $distTime) { $needBuild = $true }
}
if ($needBuild) {
    Write-Host "[构建] 前端 dist ..." -ForegroundColor Green
    Push-Location $FrontendDir
    try {
        if (-not (Test-Path 'node_modules')) { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install 失败" } }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败（exit=$LASTEXITCODE）" }
    } finally { Pop-Location }
} else {
    Write-Host "[跳过] 前端 dist 已是最新" -ForegroundColor Yellow
}

# ── 单进程服务（API + 前端，workers=1 硬约束）──
if (Test-Port $Port) {
    if (Test-OurBackend $Port) {
        Write-Host "[跳过] 服务已在运行  http://127.0.0.1:$Port" -ForegroundColor Yellow
    } else {
        Write-Host "[错误] 端口 $Port 被其他进程占用（非 SpecGuard），请先释放该端口" -ForegroundColor Red
        exit 1
    }
} else {
    if (-not $env:SG_ADMIN_ACCOUNTS) {
        Write-Host "[提示] SG_ADMIN_ACCOUNTS 未设置：首个登录用户将自动成为 admin（生产建议显式预置）" -ForegroundColor Yellow
    }
    Write-Host "[启动] 生产服务  http://0.0.0.0:$Port  (SG_AUTH_MODE=uac, workers=1)" -ForegroundColor Green
    Start-Process pwsh -ArgumentList @(
        '-NoExit', '-Command',
        "Set-Location '$BackendDir'; `$env:SG_AUTH_MODE='uac'; `$env:SG_UAC_BASE='$UacBase'; python -m uvicorn main:app --host 0.0.0.0 --port $Port --workers 1"
    ) -WindowStyle Normal
}

# ── 健康等待（最长 60s）──
Write-Host "等待服务就绪" -NoNewline
$ready = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    Write-Host "." -NoNewline
    if (Test-OurBackend $Port) { $ready = $true; break }
}
Write-Host ""

if (-not $ready) {
    Write-Host "⚠️ 服务未在 60s 内就绪，请检查启动窗口日志" -ForegroundColor Red
    exit 1
}

Write-Host "启动完成 ✅" -ForegroundColor Green
Write-Host "──────────────── 部署检查清单 ────────────────"
Write-Host ("  访问地址:     http://{服务器地址}:" + $Port)
Write-Host ("  认证模式:     uac（集团 SSO）  UAC: " + $UacBase)
Write-Host ("  预置管理员:   " + ($(if ($env:SG_ADMIN_ACCOUNTS) { $env:SG_ADMIN_ACCOUNTS } else { '（未设置，首登录用户自动 admin）' })))
Write-Host ("  数据文件:     workbench\backend\data\workbench.db（用户/授权/审计/队列，注意备份）")
Write-Host ("  工作区配置:   specstd\workspaces\registry.yaml + _clones\（git 型克隆）")
Write-Host "──────────────────────────────────────────────"
if ($OpenBrowser) { Start-Process "http://127.0.0.1:$Port" }
