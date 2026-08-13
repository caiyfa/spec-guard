"""lark_cli.py — lark-cli 子进程封装（飞书知识图谱一期 T4）。

与 mcp_server/tools/feishu_fetch.py 内联实现同源（_LARK_TIMEOUT/_lark_command/
_run_lark 原样迁移）。批次 A 只新建本文件；feishu_fetch.py 改为 import 复用的
统一化动作在批次 B 进行（避免与 GateDock 并行支线冲突）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

_LARK_TIMEOUT = 90  # 秒（会议链路多跳，放宽）


def _lark_command() -> list[str]:
    """返回 lark-cli 可执行命令前缀（Windows 需经 cmd /c 执行 .cmd 包装）。"""
    if sys.platform == "win32":
        full = shutil.which("lark-cli") or "lark-cli"
        return ["cmd", "/c", full]
    return ["lark-cli"]


def _run_lark(args: list[str], timeout: int = _LARK_TIMEOUT) -> dict:
    """执行 lark-cli 并解析 JSON 输出。

    Raises:
        ValueError: 认证未就绪/网络失败/输出非 JSON/命令超时（确定性错误）
    """
    cmd = _lark_command() + args + ["--format", "json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", check=False)
    except subprocess.TimeoutExpired:
        raise ValueError(f"lark-cli 调用超时（>{timeout}s）: {' '.join(args[:3])}")
    except OSError as e:
        raise ValueError(f"lark-cli 不可用: {e}（请确认已安装 npm 全局 lark-cli）")

    text = (proc.stdout or "") + (proc.stderr or "")
    # 认证未就绪（auth status ready 是调用前置）
    if "not logged in" in text or "登录" in text and "请先" in text:
        raise ValueError("飞书认证未就绪：请先执行 lark-cli auth login 完成 user 身份授权")
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        raise ValueError(f"lark-cli 输出非 JSON（rc={proc.returncode}）: {text[:300]}")
    if not payload.get("ok"):
        raise ValueError(f"lark-cli 调用失败: {text[:300]}")
    return payload


# 公开别名（新代码统一用 run_lark；_run_lark 保留与 feishu_fetch.py 同源命名）
run_lark = _run_lark
