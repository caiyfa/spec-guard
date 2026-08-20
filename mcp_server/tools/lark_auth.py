"""lark_auth.py — T-701：多用户飞书 CLI 认证服务。

MCP 工具：
  lark_auth_status: 查询当前用户飞书绑定状态
  lark_auth_login:  两阶段飞书授权（返回 verification_url → device-code 完成）
  lark_auth_logout: 解绑（清空隔离目录登录态）

REST 共用函数（供 lark_binding.py 调用）：
  do_status(emp_no) / do_login(emp_no) / do_logout(emp_no)

安全红线：
- 每用户独立 USERPROFILE 隔离目录 {SG_ROOT}/.lark-cli/{emp_no}/
- 凭据不落日志/argv（审计脱敏复用 audit_store 规则）
- 飞书 CLI 路径从环境变量/shutil.which 发现，不硬编码
- server 进程不保存用户 token，仅在服务调用时由用户上下文决定
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from mcp.types import TextContent, Tool

SG_ROOT = Path(__file__).resolve().parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

# ── 用户隔离目录 ──
_LARK_DIR = SG_ROOT / ".lark-cli"
_LOCK_CREATE = threading.Lock()
_USER_LOCKS: dict[str, threading.Lock] = {}
_LARK_TIMEOUT = 90  # login 两阶段放宽

# T-943：材料池链路必需 scope（缺失→对应功能不可用；刚授权仍缺→审核中）。
# 名单来自 2026-08-18 实测 auth status 的 scope 全集逐一核对。
_REQUIRED_SCOPES = (
    "contactuser:search",            # 通讯录搜索（监听用户选择）
    "im:chat:read",                  # 群聊列表
    "docs:document.content:read",   # 文档正文
    "docs:document.media:download",  # 图片下载（原文内嵌图）
    "search:docs:read",              # 文档搜索
    "wiki:node:read",                # wiki 链接解析
    "minutes:minutes.search:read",   # 妙记检索
    "minutes:minutes.artifacts:read",  # 妙记产物
    "drive:file:download",           # 文档增量轮询
    "docs:permission.member:retrieve",  # T-949：协作者列表（材料可见性）
    "docs:permission.setting:read",     # T-949：公开性设置（材料可见性）
)


def _lark_command() -> list[str]:
    """返回 lark-cli 可执行命令前缀（Windows 需经 cmd /c 执行 .cmd 包装）。"""
    if sys.platform == "win32":
        full = shutil.which("lark-cli") or "lark-cli"
        return ["cmd", "/c", full]
    return ["lark-cli"]


def _user_lark_dir(emp_no: str) -> Path:
    """返回并创建用户隔离目录。"""
    d = _LARK_DIR / emp_no
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inject_userprof(emp_no: str) -> dict:
    """子进程环境变量：USERPROFILE（Win）/ HOME（Linux）指向用户隔离目录。"""
    env = os.environ.copy()
    lark_dir = str(_user_lark_dir(emp_no))
    if sys.platform == "win32":
        env["USERPROFILE"] = lark_dir
    else:
        env["HOME"] = lark_dir
    return env


def _user_lock(emp_no: str) -> threading.Lock:
    """每用户并发锁（防 token 刷新互踩）。"""
    with _LOCK_CREATE:
        if emp_no not in _USER_LOCKS:
            _USER_LOCKS[emp_no] = threading.Lock()
    return _USER_LOCKS[emp_no]


def _ensure_config(emp_no: str) -> None:
    """隔离目录缺 config.json 时，从本机 lark-cli 配置导入（授权前置）。

    lark-cli 读配置路径为 {USERPROFILE}/.lark-cli/config.json；全新隔离目录
    无配置时 auth 命令报 not_configured。授权入口（do_login）调用本函数：
    本机已初始化过 lark-cli（含 appId/appSecret）则直接复制，用户无需手动
    配置；本机也无配置时静默跳过（auth login 自会返回可读错误引导）。
    """
    lark_dir = _user_lark_dir(emp_no)
    dest = lark_dir / ".lark-cli" / "config.json"
    if dest.is_file():
        return
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    src = home / ".lark-cli" / "config.json"
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _run_lark(emp_no: str, args: list[str], timeout: int = _LARK_TIMEOUT,
              json_output: bool = True) -> dict:
    """执行 lark-cli 并解析 JSON 输出（用户隔离上下文）。

    Args:
        emp_no: 用户工号（决定 USERPROFILE 隔离目录）
        args: lark-cli 命令参数
        timeout: 超时秒数
        json_output: True 自动追加 --format json；False 不追加（auth 域子命令
            仅支持 --json，需调用方自行带上）

    Returns:
        解析后的 lark-cli 响应 dict

    Raises:
        ValueError: 超时/CLI 不可用/输出非 JSON/lark-cli 返回失败
    """
    cmd = _lark_command() + args
    if json_output:
        cmd += ["--format", "json"]
    env = _inject_userprof(emp_no)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", check=False, env=env)
    except subprocess.TimeoutExpired:
        raise ValueError(
            f"lark-cli 调用超时（>{timeout}s）: {' '.join(args[:3])}") from None
    except OSError as e:
        raise ValueError(f"lark-cli 不可用: {e}") from e

    text = (proc.stdout or "") + (proc.stderr or "")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise ValueError(
            f"lark-cli 输出非 JSON（rc={proc.returncode}）: {text[:300]}") from None
    if payload.get("ok") is False:
        raise ValueError(f"lark-cli 调用失败: {text[:300]}")
    return payload


# ══════════════════════════════════════════════════════════
# 二维码生成（授权引导用：verification_url → data URI，对话/页面直接展示）
# ══════════════════════════════════════════════════════════

def _make_qr_data_uri(url: str) -> str:
    """verification_url → base64 PNG data URI（segno 纯 Python，零依赖）。

    segno 缺失时返回空串（降级为纯链接展示，不阻断授权流程）。
    """
    if not url:
        return ""
    try:
        import base64
        import io

        import segno

        buf = io.BytesIO()
        segno.make(url, error='m').save(buf, kind='png', scale=4, border=2)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════
# 底层认证函数（REST + MCP 共用）
# ══════════════════════════════════════════════════════════

def do_status(emp_no: str) -> dict:
    """查询当前用户的飞书 CLI 绑定状态。

    T-943：按真实输出结构解析（identities.user.scope 为空格分隔字符串——
    旧代码读不存在的 data.scopes 数组致身份/scopes 恒空）；
    附 missing_scopes（必需清单 ∩ 已授权补集）与 reviewing
    （刚授权 30 分钟内仍有缺失 → 敏感 scope 管理员审核未生效）。

    Returns:
        dict: bound/identity/identity_name/open_id/scopes/missing_scopes/
              reviewing/config_dir；未绑定时 bound=False 其余为空。
    """
    lark_dir = _user_lark_dir(emp_no)
    base = {"bound": False, "identity": "", "identity_name": "",
            "open_id": "", "scopes": [], "missing_scopes": list(_REQUIRED_SCOPES),
            "reviewing": False, "config_dir": str(lark_dir)}
    has_token = any(f.name.endswith(".json") for f in lark_dir.rglob("*")
                    if f.is_file())
    if not has_token:
        return base
    try:
        payload = _run_lark(emp_no, ["auth", "status", "--json"],
                            json_output=False)
    except ValueError as e:
        return {**base, "error": str(e)}

    identities = payload.get("identities") or {}
    user = identities.get("user") or {}
    bot = identities.get("bot") or {}
    scopes = str(user.get("scope") or "").split()
    if user.get("available") or user.get("status") == "ready":
        identity, identity_name = "user", str(user.get("userName") or "")
        open_id = str(user.get("openId") or "")
    elif bot.get("available") or bot.get("status") == "ready":
        identity, identity_name = "bot", str(bot.get("userName")
                                              or bot.get("name") or "")
        open_id = str(bot.get("openId") or "")
    else:
        identity = identity_name = open_id = ""
    scope_set = set(scopes)
    missing = [s for s in _REQUIRED_SCOPES if s not in scope_set]
    reviewing = bool(missing) and _recently_authed(lark_dir)
    return {"bound": True, "identity": identity,
            "identity_name": identity_name, "open_id": open_id,
            "scopes": scopes, "missing_scopes": missing,
            "reviewing": reviewing, "config_dir": str(lark_dir)}


def _mark_auth_done(emp_no: str) -> None:
    """授权完成打点（审核中判定的依据；失败静默——状态增强不阻断主流程）。"""
    import contextlib
    import datetime as _dt

    f = _user_lark_dir(emp_no) / "last_auth.json"
    with contextlib.suppress(Exception):
        f.write_text(json.dumps(
            {"at": _dt.datetime.now(_dt.UTC).isoformat()},
            ensure_ascii=False), encoding="utf-8")


def _recently_authed(lark_dir: Path, within_minutes: int = 30) -> bool:
    """30 分钟内完成过授权（last_auth.json 时间戳）。"""
    import datetime as _dt

    f = Path(lark_dir) / "last_auth.json"
    if not f.is_file():
        return False
    try:
        at = _dt.datetime.fromisoformat(
            json.loads(f.read_text(encoding="utf-8"))["at"])
        return (_dt.datetime.now(_dt.UTC)
                - at).total_seconds() < within_minutes * 60
    except Exception:
        return False


def do_login(emp_no: str, scope: str = "") -> dict:
    """两阶段飞书授权。

    Phase1: 返回 verification_url + device_code，用户需打开该 URL 完成授权
    Phase2: 自动检测授权完成状态

    Args:
        emp_no: 用户工号
        scope: 可选，指定授权 scope 范围

    Returns:
        Phase1: {"phase": "waiting", "verification_url": str, "device_code": str}
        Phase2: {"phase": "completed", "identity": str, "open_id": str, "identity_name": str}
        Error:  {"phase": "error", "error": str}
    """
    with _user_lock(emp_no):
        # 配置前置：全新隔离目录无 config.json 时从本机导入（否则 auth login 报 not_configured）
        _ensure_config(emp_no)
        args = ["auth", "login", "--no-wait", "--json"]
        if scope:
            args += ["--scope", scope]
        else:
            args += ["--domain", "all"]  # 未指定范围时请求全部域（lark-shared：login 必须指定范围）
        try:
            payload = _run_lark(emp_no, args, json_output=False)
        except ValueError as e:
            return {"phase": "error", "error": str(e)}
        data = payload.get("data") or payload
        verification_url = data.get("verification_url", data.get("url", ""))
        device_code = data.get("device_code", "")
        if not verification_url:
            # 可能已经登录成功（首次调用已授权）
            status = do_status(emp_no)
            if status.get("bound"):
                _mark_auth_done(emp_no)
                return {
                    "phase": "completed",
                    "identity": status.get("identity", ""),
                    "open_id": status.get("open_id", ""),
                    "identity_name": status.get("identity_name", ""),
                }
            return {"phase": "error", "error": "返回无 verification_url"}
        return {
            "phase": "waiting",
            "verification_url": verification_url,
            "device_code": device_code,
            "qr_data_uri": _make_qr_data_uri(verification_url),
        }


def do_login_complete(emp_no: str, device_code: str) -> dict:
    """device flow 收尾：用户扫码后以 device_code 完成授权（T-703 增补）。

    对应 lark-cli `auth login --device-code <code>`（poll 模式，CLI 阻塞轮询
    直到用户完成或超时）。返回：
      completed: 授权完成（token 已落盘隔离目录）
      pending:   用户尚未完成扫码，可稍后重试
      error:     其他失败
    """
    if not device_code:
        return {"phase": "error", "error": "device_code 必填"}
    with _user_lock(emp_no):
        try:
            payload = _run_lark(emp_no, ["auth", "login", "--device-code",
                                         device_code, "--json"],
                                timeout=15, json_output=False)
        except ValueError as e:
            text = str(e)
            # T-942 补丁：CLI poll 未完成时返回 ok:false（authorization_pending
            # / expired_token 等）→ 识别为 pending 而非 error（用户扫码中是正常态；
            # 误判 error 会让前端轮询链条无感中断）
            low = text.lower()
            if ("超时" in text or "timeout" in low or "pending" in low
                    or "authorization_pending" in low):
                return {"phase": "pending", "hint": "用户尚未完成授权，请稍后重试"}
            return {"phase": "error", "error": text[:300]}
        status = do_status(emp_no) if payload.get("ok") else {}
        if status.get("bound"):
            _mark_auth_done(emp_no)
            return {
                "phase": "completed",
                "identity": status.get("identity", ""),
                "open_id": status.get("open_id", ""),
                "identity_name": status.get("identity_name", ""),
            }
        return {"phase": "pending", "hint": "授权尚未完成，请稍后重试"}


def do_logout(emp_no: str) -> dict:
    """解绑当前用户的飞书 CLI 身份。"""
    import contextlib

    with _user_lock(emp_no):
        # 未登录状态也算成功
        with contextlib.suppress(ValueError):
            _run_lark(emp_no, ["auth", "logout", "--yes", "--json"], json_output=False)
        return {"ok": True}


# ══════════════════════════════════════════════════════════
# MCP 工具定义
# ══════════════════════════════════════════════════════════

lark_auth_status_tool = Tool(
    name="lark_auth_status",
    description="查询当前用户飞书 CLI 绑定状态（bound/unbound、身份 user|bot、open_id、"
                "scope 列表）。Agent 对话中用于判断飞书能力是否可用。",
    inputSchema={
        "type": "object",
        "properties": {},
    },
)

lark_auth_login_tool = Tool(
    name="lark_auth_login",
    description="飞书 CLI 两阶段授权。无 device_code：Phase1 返回 verification_url（用户需打开该链接"
                "完成飞书 OAuth 授权，附 qr_data_uri 二维码图片）+ device_code；"
                "传入 device_code：Phase2 完成授权（用户扫码后调用，返回 completed/pending）。",
    inputSchema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "可选：指定授权 scope（如 'docs:* base:*'），默认与现有 app 一致",
            },
            "device_code": {
                "type": "string",
                "description": "可选：Phase1 返回的 device_code；传入则执行 Phase2 完成授权（用户扫码后调用）",
            },
        },
    },
)

lark_auth_logout_tool = Tool(
    name="lark_auth_logout",
    description="解绑当前用户飞书 CLI 账号（清空隔离目录登录态）。解绑后需重新授权才能使用飞书工具。",
    inputSchema={
        "type": "object",
        "properties": {},
    },
)

TOOLS = [lark_auth_status_tool, lark_auth_login_tool, lark_auth_logout_tool]


async def handle(name: str, arguments: dict) -> list[TextContent]:
    """MCP 工具分发入口。"""
    try:
        from services.auth import current_emp_no as _get_emp_no
        emp_no = _get_emp_no()
    except Exception:
        # MCP server 独立模式（无 runtime 上下文）：从环境变量或默认取
        emp_no = os.environ.get("SG_LARK_EMP_NO", "")
    if not emp_no:
        return [TextContent(type="text", text=json.dumps({
            "error": "未获取到当前用户身份（emp_no 为空）",
            "hint": "请在 Agent 运行时中调用，或设置 SG_LARK_EMP_NO 环境变量",
        }, ensure_ascii=False))]

    try:
        if name == "lark_auth_status":
            result = do_status(emp_no)
        elif name == "lark_auth_login":
            device_code = arguments.get("device_code", "")
            if device_code:
                result = do_login_complete(emp_no, device_code)
            else:
                result = do_login(emp_no, arguments.get("scope", ""))
        elif name == "lark_auth_logout":
            result = do_logout(emp_no)
        else:
            return [TextContent(type="text", text=json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False))]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False, default=str))]
