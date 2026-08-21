"""系统包管理面 API（T-973 分级动态注册）。

分级接入（08-21 用户拍板）：
  ① config/template 级：注册/编辑/启停即时生效（写 manifest/env/assertions 落盘
     + 失效 live_registry 缓存，不重启后端）
  ② code 级：extensions.py 上传落「待评审」；admin 评审通过（绑定 sha256 留痕）
     后 reload 热加载——评审闸不可绕（文件任何改动使指纹失配自动回到未评审态）

端点（写操作全部 admin）：
  GET  /api/systems                        目录（登录即可，工作区注册下拉共用）
  GET  /api/systems/{name}                 详情（含评审闸状态）
  POST /api/systems                        注册系统（写 manifest + 首个 env yaml）
  PUT  /api/systems/{name}/manifest        编辑 manifest（display/tier/enabled/desc）
  PUT  /api/systems/{name}/env-config      写 config/env.{env}.yaml
  PUT  /api/systems/{name}/assertions      写 assertions.yaml（注册期确定性校验）
  POST /api/systems/{name}/extensions      上传 extensions.py（语法校验，落待评审）
  POST /api/systems/{name}/review          评审通过（sha256 留痕）
  POST /api/systems/{name}/reload          热重建（失效缓存 + 预热装配）
"""

import sys
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/systems", tags=["systems"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

from services import (
    systems_catalog,  # noqa: E402
    user_store,  # noqa: E402
)
from services.auth import CurrentUser, get_current_user, require_role  # noqa: E402

from engine import system_package  # noqa: E402


def _audit(user: CurrentUser, action: str, target: str, detail: str = ""):
    import contextlib
    with contextlib.suppress(Exception):
        user_store.audit(user.emp_no, action, target, detail)  # 审计失败不阻断管理操作


def _invalidate_and_warm(system: str, warm: bool = True) -> dict:
    """写操作后即时生效：失效该系统缓存（可选预热装配）。"""
    from mcp_server.tools.live_registry import invalidate_live_registry
    invalidate_live_registry(system)
    if not warm:
        return {"warmed": False}
    # 预热：强制装配一次（评审通过的 extensions 此刻加载；format_spec tool 目录随之可见）
    from mcp_server.tools.live_registry import get_live_registry
    reg = get_live_registry(system)
    if reg is None:
        return {"warmed": False, "error": "装配失败（见后端日志）"}
    return {"warmed": True, "oracles": len(reg.oracles), "steps": len(reg.step_handlers)}


# ── 读 ──────────────────────────────────────────────

@router.get("")
def list_systems(user: CurrentUser = Depends(get_current_user)):
    """系统目录（含 tier/启停/评审闸状态）。"""
    return {"systems": systems_catalog.list_systems()}


@router.get("/{name}")
def get_system(name: str, user: CurrentUser = Depends(get_current_user)):
    detail = systems_catalog.get_system_detail(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"系统不存在: {name}")
    return detail


# ── 注册（config/template 级即时生效） ──────────────────────

class SystemCreateBody(BaseModel):
    name: str
    display_name: str = ""
    tier: str = "config"            # config | template | code
    description: str = ""
    env_name: str = "sit"
    env_yaml: str = ""              # 首个环境配置原文（YAML）


@router.post("", dependencies=[Depends(require_role("admin"))])
def create_system(body: SystemCreateBody, admin: CurrentUser = Depends(require_role("admin"))):
    """注册系统包（manifest + 首个 env yaml 落盘，即时生效不重启）。"""
    if not systems_catalog.SYSTEM_NAME_RE.match(body.name or ""):
        raise HTTPException(status_code=400, detail=f"系统标识非法: {body.name}")
    if body.tier not in system_package.VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier 非法: {body.tier}（{system_package.VALID_TIERS}）")
    if body.env_yaml:
        try:
            parsed = yaml.safe_load(body.env_yaml)
            if not isinstance(parsed, dict):
                raise ValueError("必须是 YAML 对象")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"env_yaml 语法错误: {e}") from e

    from engine.system_package import systems_root
    target = systems_root() / body.name
    if target.exists():
        raise HTTPException(status_code=409, detail=f"系统已存在: {body.name}")
    # 动态注册的系统一律 layout=extensions（代码能力走 extensions.py 评审闸；
    # 仓内 package 布局只能随 git 诞生，UI 不创建）
    manifest = {
        "name": body.name,
        "display_name": body.display_name or body.name,
        "tier": body.tier,
        "layout": "extensions",
        "enabled": True,
        "description": body.description,
    }
    if body.env_yaml:
        cfg_dir = target / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / f"env.{body.env_name}.yaml").write_text(body.env_yaml, encoding="utf-8")
    system_package.save_manifest(body.name, manifest)
    _audit(admin, "system_create", body.name, f"tier={body.tier}")
    result = _invalidate_and_warm(body.name, warm=False)
    return {"ok": True, "system": body.name, **result}


class ManifestBody(BaseModel):
    display_name: str | None = None
    tier: str | None = None
    enabled: bool | None = None
    description: str | None = None


@router.put("/{name}/manifest", dependencies=[Depends(require_role("admin"))])
def update_manifest(name: str, body: ManifestBody,
                    admin: CurrentUser = Depends(require_role("admin"))):
    """编辑 manifest（启停/改名/升降级 tier）。评审留痕（review 段）不可经此改。"""
    manifest = system_package.load_manifest(name)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"系统 manifest 不存在: {name}")
    if body.tier is not None and body.tier not in system_package.VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"tier 非法: {body.tier}")
    for k in ("display_name", "tier", "enabled", "description"):
        v = getattr(body, k)
        if v is not None:
            manifest[k] = v
    system_package.save_manifest(name, manifest)
    _audit(admin, "system_manifest_update", name,
           f"tier={manifest.get('tier')} enabled={manifest.get('enabled')}")
    result = _invalidate_and_warm(name, warm=False)
    return {"ok": True, **result}


class EnvConfigBody(BaseModel):
    env_name: str = "sit"
    raw: str


@router.put("/{name}/env-config", dependencies=[Depends(require_role("admin"))])
def write_env_config(name: str, body: EnvConfigBody,
                     admin: CurrentUser = Depends(require_role("admin"))):
    """写 config/env.{env}.yaml（即时生效）。"""
    systems_catalog.validate_system(name)
    try:
        parsed = yaml.safe_load(body.raw)
        if not isinstance(parsed, dict):
            raise ValueError("必须是 YAML 对象")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML 语法错误: {e}") from e
    cfg_dir = system_package.package_dir(name) / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / f"env.{body.env_name}.yaml").write_text(body.raw, encoding="utf-8")
    _audit(admin, "system_env_update", name, f"env={body.env_name}")
    return {"ok": True, "env": body.env_name}


class AssertionsBody(BaseModel):
    raw: str


@router.put("/{name}/assertions", dependencies=[Depends(require_role("admin"))])
def write_assertions(name: str, body: AssertionsBody,
                     admin: CurrentUser = Depends(require_role("admin"))):
    """写 assertions.yaml——注册期确定性校验（SELECT-only + 无分号 + schema_match 可解析）。"""
    systems_catalog.validate_system(name)
    try:
        parsed = yaml.safe_load(body.raw) or {}
        if not isinstance(parsed, dict):
            raise ValueError("必须是 YAML 对象")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YAML 语法错误: {e}") from e
    # 确定性校验：写入后在临时 Registry 上试注册，失败还原旧文件
    from engine.registry import Registry
    assertions_path = system_package.package_dir(name) / "assertions.yaml"
    backup = assertions_path.read_bytes() if assertions_path.exists() else None
    assertions_path.write_text(body.raw, encoding="utf-8")
    try:
        names = system_package.register_assertions(Registry(), name)
    except Exception as e:
        if backup is not None:
            assertions_path.write_bytes(backup)
        else:
            assertions_path.unlink()
        raise HTTPException(status_code=400, detail=f"断言模板校验失败: {e}") from e
    _audit(admin, "system_assertions_update", name, f"{len(names)} 条模板断言")
    warm = _invalidate_and_warm(name, warm=False)
    return {"ok": True, "registered": names, **warm}


class ExtensionsBody(BaseModel):
    content: str


@router.post("/{name}/extensions", dependencies=[Depends(require_role("admin"))])
def upload_extensions(name: str, body: ExtensionsBody,
                      admin: CurrentUser = Depends(require_role("admin"))):
    """上传 extensions.py——语法校验后落盘，状态=待评审（不加载）。"""
    systems_catalog.validate_system(name)
    try:
        compile(body.content, f"{name}/extensions.py", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400,
                            detail=f"extensions.py 语法错误: 行{e.lineno} {e.msg}") from e
    ext_path = system_package.package_dir(name) / "extensions.py"
    ext_path.write_text(body.content, encoding="utf-8")
    # 新文件指纹必然与旧评审记录失配——显式清空评审段（诚实状态：待评审）
    manifest = system_package.load_manifest(name)
    if manifest and manifest.get("review"):
        manifest.pop("review")
        if manifest.get("tier", "config") != "code":
            manifest["tier"] = "code"   # 上传代码 = 声明代码型
        manifest["layout"] = "extensions"
        system_package.save_manifest(name, manifest)
    gate = system_package.extension_gate_status(name)
    _audit(admin, "system_extensions_upload", name, f"sha256={gate['sha256'][:12]}…")
    from mcp_server.tools.live_registry import invalidate_live_registry
    invalidate_live_registry(name)
    return {"ok": True, "status": "pending_review", "sha256": gate["sha256"],
            "reason": gate["reason"]}


@router.post("/{name}/review", dependencies=[Depends(require_role("admin"))])
def review_extensions(name: str, admin: CurrentUser = Depends(require_role("admin"))):
    """评审通过 extensions.py——绑定当前文件 sha256 留痕（谁审的+何时+指纹）。

    闸语义：此后文件任何改动使指纹失配，加载自动失效（不需要撤销动作）。
    """
    systems_catalog.validate_system(name)
    gate = system_package.extension_gate_status(name)
    if not gate["present"]:
        raise HTTPException(status_code=404, detail=f"extensions.py 不存在: {name}")
    manifest = system_package.load_manifest(name)
    manifest["review"] = {
        "approved_by": admin.emp_no,
        "approved_at": datetime.now().isoformat(timespec="seconds"),
        "sha256": gate["sha256"],
    }
    manifest["tier"] = "code"
    manifest["layout"] = "extensions"
    system_package.save_manifest(name, manifest)
    _audit(admin, "system_extensions_review", name,
           f"approved sha256={gate['sha256'][:12]}…")
    result = _invalidate_and_warm(name)
    return {"ok": True, "review": manifest["review"], **result}


@router.post("/{name}/reload", dependencies=[Depends(require_role("admin"))])
def reload_system(name: str, admin: CurrentUser = Depends(require_role("admin"))):
    """热重建系统装配（失效缓存 + 预热；评审通过的 extensions 此刻加载）。"""
    systems_catalog.validate_system(name)
    _audit(admin, "system_reload", name)
    result = _invalidate_and_warm(name)
    gate = system_package.extension_gate_status(name)
    return {"ok": True, "gate": gate, **result}
