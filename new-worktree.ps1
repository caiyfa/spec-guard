# new-worktree.ps1 — 创建 git worktree 并从主库同步本地运行状态
#
# 用途：多会话并行开发。每个任务一棵树一个分支，新建的树自动带上主库的
# 本地运行状态（不入 git、git 合并天然不碰的那些文件），免去每次从头配置。
#
# 同步内容（白名单，node_modules 除外）：
#   workbench/backend/data/workbench.db   —— SQLite（用户/RBAC/LLM 配置），
#                                            用 Python sqlite3 在线备份 API 拷贝，
#                                            主库后端运行中也安全，产物为完整单文件
#   specstd/workspaces/                   —— 工作区注册表 + _clones（相对路径落点，
#                                            复制后按新树根解析，天然独立；注册表中
#                                            指向库外的绝对路径工作区仍为共享）
#   .lark-cli/                            —— 飞书 CLI token/缓存（存在才拷）
#   feedback/registry.json                —— 通知 webhook 注册表（存在才拷；
#                                            注意：拷贝后从本树跑工作台执行会真实推送通知）
#   .env / .env.*                         —— 根目录环境文件（存在才拷）
#
# 显式不同步：node_modules（前端任务进树后自行 npm install）、.zcode/ 与
# .workbuddy/（会话/自动化状态，按树隔离，复制会导致定时任务重复触发）、
# agent/sessions/、reports/、drafts/、data/logs/（含 dev-pids.json 进程状态）、
# 各类缓存与构建产物。
#
# 用法（仓库根执行）：
#   pwsh new-worktree.ps1 ENG-T01                     # 建 wt\ENG-T01，分支 feature/ENG-T01，基于 master
#   pwsh new-worktree.ps1 ENG-T02 -Base feature/T-948 # 指定基线分支
#   pwsh new-worktree.ps1 ENG-T01 -SyncOnly           # 树已存在，仅重做状态同步（幂等）
#   pwsh new-worktree.ps1 ENG-T01 -Path D:\wt\T01     # 自定义落点
#
# 收尾：git worktree remove <路径>（先停掉从该目录起的 uvicorn/npm 进程，
# Windows 文件锁否则删不掉）；分支合并回主线后 git branch -d feature/<名>。

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Name,

    [string]$Base = "master",
    [string]$Branch = "",
    [string]$Path = "",
    [switch]$SyncOnly
)

$ErrorActionPreference = "Stop"
$MainRoot = $PSScriptRoot
Push-Location $MainRoot   # git 命令一律在主库上下文执行，与调用方 cwd 无关
try {
if (-not $Branch) { $Branch = "feature/$Name" }
if (-not $Path) { $Path = Join-Path (Split-Path $MainRoot -Parent) "wt\$Name" }

function Sync-RuntimeState([string]$Target) {
    $copied = @()

    # ── 1. workbench SQLite：在线备份 API，主库后端运行中也一致 ──
    $srcDb = Join-Path $MainRoot "workbench\backend\data\workbench.db"
    if (Test-Path $srcDb) {
        $dstDir = Join-Path $Target "workbench\backend\data"
        New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
        $dstDb = Join-Path $dstDir "workbench.db"
        $py = @"
import sqlite3, sys
s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2])
s.backup(d); d.close(); s.close()
"@
        $py | python - "$srcDb" "$dstDb"
        if ($LASTEXITCODE -eq 0) { $copied += "workbench.db（sqlite 在线备份）" }
        else {
            # 兜底：直接拷贝三件套（要求主库后端无活跃写入）
            Copy-Item $srcDb $dstDb -Force
            foreach ($ext in @("-wal", "-shm")) {
                $f = "$srcDb$ext"
                if (Test-Path $f) { Copy-Item $f "$dstDb$ext" -Force }
            }
            $copied += "workbench.db（直接拷贝，python 备份失败回退）"
        }
    }

    # ── 2. specstd/workspaces（注册表 + _clones）──
    $srcWs = Join-Path $MainRoot "specstd\workspaces"
    if (Test-Path $srcWs) {
        $dstWs = Join-Path $Target "specstd\workspaces"
        robocopy $srcWs $dstWs /E /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -lt 8) { $copied += "specstd/workspaces（注册表+克隆）" }
        else { Write-Warning "robocopy 同步 specstd/workspaces 失败（exit=$LASTEXITCODE）" }
    }

    # ── 3. 零星状态文件/目录（存在才拷）──
    foreach ($item in @(".lark-cli", "feedback\registry.json")) {
        $src = Join-Path $MainRoot $item
        if (Test-Path $src) {
            $dst = Join-Path $Target $item
            New-Item -ItemType Directory -Force -Path (Split-Path $dst -Parent) | Out-Null
            if ((Get-Item $src) -is [System.IO.DirectoryInfo]) {
                robocopy $src $dst /E /NFL /NDL /NJH /NJS /NP | Out-Null
                if ($LASTEXITCODE -ge 8) { Write-Warning "robocopy 同步 $item 失败（exit=$LASTEXITCODE）"; continue }
            } else {
                Copy-Item $src $dst -Force
            }
            $copied += $item
        }
    }
    $envFiles = Get-ChildItem $MainRoot -Force -Filter ".env*" -File -ErrorAction SilentlyContinue
    foreach ($f in $envFiles) {
        if ($f.Name -eq ".env.example") { continue }
        Copy-Item $f.FullName (Join-Path $Target $f.Name) -Force
        $copied += $f.Name
    }

    return $copied
}

# ── 建/验 worktree ──
if (-not $SyncOnly) {
    if (Test-Path $Path) { throw "目标路径已存在: $Path（重同步请用 -SyncOnly）" }
    $branchExists = $false
    git show-ref --verify --quiet "refs/heads/$Branch"
    if ($LASTEXITCODE -eq 0) { $branchExists = $true }
    if ($branchExists) {
        git worktree add $Path $Branch
    } else {
        git worktree add $Path -b $Branch $Base
    }
    if ($LASTEXITCODE -ne 0) { throw "git worktree add 失败" }
    Write-Host "✔ worktree 已建: $Path（分支 $Branch，基于 $Base）"
} else {
    if (-not (Test-Path $Path)) { throw "-SyncOnly 但目标不存在: $Path" }
    Write-Host "↻ 仅同步模式: $Path"
}

# ── 状态同步 ──
$done = Sync-RuntimeState $Path
if ($done.Count) { $done | ForEach-Object { Write-Host "✔ 已同步: $_" } }
else { Write-Host "（主库暂无可同步的运行状态）" }

# ── 收尾提示 ──
Write-Host ""
Write-Host "下一步："
Write-Host "  1. 会话直接在 $Path 目录开展工作，不要碰主树"
Write-Host "  2. 前端/工作台任务：进树后 cd workbench/frontend && npm install（首次一次性）"
Write-Host "  3. 并行纪律：联网场景测试只在主库串行跑；worktree 里只跑离线测试"
Write-Host "     （test_engine / engine_modes）；工作台端口 :9100/:5173 不可两树同起"
Write-Host "  4. 验收：代码合并回主库后，在主库做手动实际测试验收（状态已与主库同源）"
} finally {
    Pop-Location
}
