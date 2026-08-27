"""草稿区三道闸 API（D1 补齐）：评审 → 格式校验 → 发布门禁 → 入库。

端点：
  GET    /api/drafts                        草稿列表（含解析出的场景 id/标题）
  GET    /api/drafts/modules                可入库的模块目录（scenarios/ 下）
  GET    /api/drafts/suggest-deps           全部草稿的依赖建议（K-046，dep_suggest 确定性引擎）
  GET    /api/drafts/{filename}             草稿内容
  PUT    /api/drafts/{filename}             保存草稿内容（K-046，写前 .bak 备份 + 审计；
                                            T-1027：+自动校验/②闸刷新/user_edit 版本链/会话编辑感知）
  POST   /api/drafts/{filename}/validate    格式校验（与 MCP validate 同一实现）
  POST   /api/drafts/{filename}/deps        草稿连线：文本外科手术加 depends_on（K-046）
  POST   /api/drafts/{filename}/trial-run   草稿试跑（K-046，与 MCP run_scenario 同一语义）
  POST   /api/drafts/{filename}/promote     入库：校验 → 移动 → 基线更新 → 发布门禁（失败回滚）
  POST   /api/drafts/{filename}/discard     废弃（移入 drafts/_trash/）
  POST   /api/drafts/reset                 重置草稿区状态（清空草稿/回收站/元数据/DB 记录）

安全约束（与架构 D5 一致）：
- 仅 drafts/ 目录可读可写；filename 禁止路径分隔符与 ..
- 入库目标限定 scenarios/ 下已存在模块目录
- 发布门禁 release_check.py 失败自动回滚，不产生半截入库
- K-046：编辑/连线/试跑只作用于 drafts/ 沙箱，入库仍必须走 promote 三道闸
"""

import json as _json
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from services.auth import require_role

router = APIRouter(prefix="/api/drafts", tags=["drafts"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from specstd.workspace import (  # noqa: E402
    can_read_private,
    drafts_dir,
    get_context_emp_no,
    get_workspace_root,
)


def _drafts_root() -> Path:
    """获取草稿目录（动态解析当前工作区 .specguard/drafts/，无工作区 → 400）。

    M2 修复：移除 SG_ROOT/drafts 全局共享回退——无激活工作区时草稿目录不可解析，
    此前任何用户回退同一全局目录会形成越权读（多用户迁移残留无归属隔离）。
    """
    try:
        d = drafts_dir()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=f"草稿目录不可用：{e}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_private_draft_scope():
    """M1：HTTP 路径草稿访问仅限本人私有区——无 emp 归属（共享区）确定性拒绝。

    can_read_private(owner="", ...) 恒 False：未认证/共享区不适用私有读取路径。
    正常认证请求 emp 恒非空（恒通过），此守卫为防御纵深：万一未来有绕过
    _authenticate 的调用路径，也不会落到共享区草稿。
    """
    emp = get_context_emp_no() or ""
    if not can_read_private(emp, emp, False):
        raise HTTPException(status_code=403,
                            detail="草稿私有区不可访问（无用户归属，请先选择工作区）")


def _scenarios_root() -> Path:
    """场景库目录（工作区 scenarios/ 存在则用，否则回退 SpecGuard 仓库 scenarios/）。

    K-016 修复：spec 工作区克隆通常没有 scenarios/（场景库在 SpecGuard 仓库根），
    与 services.draft_promote._scenarios_root 同一策略。
    """
    ws = get_workspace_root()
    if ws and (ws / "scenarios").is_dir():
        return ws / "scenarios"
    return SG_ROOT / "scenarios"


def _trash_dir() -> Path:
    """获取草稿回收站目录。"""
    return _drafts_root() / "_trash"


# ══════════════════════════════════════════════════════════
# 路径守卫
# ══════════════════════════════════════════════════════════

def _guard_filename(filename: str) -> Path:
    """校验草稿文件名并返回安全路径（越界/非法 → 400）。"""
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail=f"非法文件名: {filename}")
    if not filename.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail=f"仅支持 YAML 草稿: {filename}")
    return _drafts_root() / filename


def _guard_module(module: str) -> Path:
    """校验入库模块目录（必须在 scenarios/ 之内；K-017：不存在时自动创建）。"""
    if not module or ".." in module or module.startswith(("/", "\\")):
        raise HTTPException(status_code=400, detail=f"非法模块路径: {module}")
    scenarios_root = _scenarios_root()
    target = (scenarios_root / module).resolve()
    try:
        target.relative_to(scenarios_root.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"模块路径越界: {module}")
    if not target.is_dir():
        # K-017：自动创建模块目录（而非报「模块目录不存在」）
        target.mkdir(parents=True, exist_ok=True)
    return target


# ══════════════════════════════════════════════════════════
# 草稿列表 / 读取
# ══════════════════════════════════════════════════════════

@router.get("", dependencies=[Depends(require_role("admin", "tester", "product"))])
def list_drafts():
    """列出草稿区全部 YAML 草稿（按修改时间倒序，含作者归属）。

    M1/M2：viewer 不可读（无 Agent 能力）；草稿访问仅限本人私有区。
    """
    # 作者元数据（draft_writer 写入）
    _ensure_private_draft_scope()
    drafts_root = _drafts_root()
    meta_path = drafts_root / "_meta.json"
    meta = {}
    if meta_path.is_file():
        try:
            import json as _json
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    drafts = []
    # K-013：场景关联的新鲜度缓存（同一 source_meta 只查一次）
    _freshness_cache: dict = {}

    def _stale_of(source_meta_id: str) -> bool:
        if not source_meta_id:
            return False
        if source_meta_id not in _freshness_cache:
            try:
                from services import info_pack_freshness
                _freshness_cache[source_meta_id] = (
                    info_pack_freshness.check_freshness(source_meta_id).get("stale_count", 0) > 0
                )
            except Exception:
                _freshness_cache[source_meta_id] = False
        return _freshness_cache[source_meta_id]

    if drafts_root.is_dir():
        # T-061：三闸状态快照（一次查询全部草稿）
        try:
            from services import draft_gates
            gates_map = {g["draft_id"]: g for g in draft_gates.list_gates()}
        except Exception:
            gates_map = {}
        for f in sorted(drafts_root.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
            sid, title = "", ""
            try:
                raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                sid = str(raw.get("id", ""))
                title = str(raw.get("title", ""))
            except Exception:
                pass
            meta_entry = meta.get(f.name) or {}
            source_meta = meta_entry.get("scenario_id", "")  # K-013: SG-META 关联（注意与 YAML 的 id 字段区分）
            gate = gates_map.get(f.name) or {}
            drafts.append({
                "filename": f.name,
                "scenario_id": sid,
                "title": title,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                "author": meta_entry.get("author", ""),
                "source_meta": source_meta,
                "stale": _stale_of(source_meta),
                "source_files": meta_entry.get("source_files", []),
                "gates": {"g1": gate.get("gate1_status", "pending"),
                           "g2": gate.get("gate2_status", "pending"),
                           "g3": gate.get("gate3_status", "blocked")},
                "source_delta": gate.get("source_delta", ""),
            })
    return {"drafts": drafts}


@router.get("/modules", dependencies=[Depends(require_role("admin", "tester", "product"))])
def list_modules():
    """列出 scenarios/ 下的模块目录（promote 目标选择）。"""
    scenarios_root = _scenarios_root()
    modules = []
    if scenarios_root.is_dir():
        for d in sorted(scenarios_root.rglob("*")):
            if d.is_dir() and any(c.suffix == ".yaml" for c in d.iterdir() if c.is_file()):
                modules.append(str(d.relative_to(scenarios_root)).replace("\\", "/"))
    return {"modules": modules}


@router.get("/suggest-deps", dependencies=[Depends(require_role("admin", "tester", "product"))])
def suggest_draft_deps():
    """全部草稿的依赖建议（K-046：dep_suggest 确定性引擎，纯读）。

    扫描草稿 + 场景库的 {{...}} 插值 needs 侧，匹配 save 生产者，
    返回建议边（含理由/置信度）；已声明/传递依赖、自依赖、会成环的自动剔除。
    """
    from services import dep_suggest
    return dep_suggest.suggest_deps(_scenarios_root(), _drafts_root(), drafts_only=True)


@router.get("/activity", dependencies=[Depends(require_role("admin", "tester", "product"))])
def list_draft_activity():
    """T-1020：草稿活动摘要（product_activity 流水 → 面板 DB 化数据源）。

    返回当前 emp+workspace 每份草稿的最新活动：来源会话/版本号/累计版本数/
    最新动作/时间——草稿产物页跨会话接管展示依据。
    """
    from sg_core import product_activity as pa
    from specstd.workspace import get_context_workspace

    ws = get_context_workspace() or ""
    emp = get_context_emp_no() or ""
    if not ws:
        raise HTTPException(status_code=400, detail="工作区上下文缺失")
    try:
        rows = pa.latest_by_workspace(ws)
    except Exception:
        rows = []  # 旧库无表/DB 不可用 → 空活动（面板退化为纯文件列表）
    items = []
    for r in rows:
        if emp and r.get("emp_no") and r["emp_no"] != emp:
            continue  # 草稿物理隔离在各自 emp 私有区，活动跟人走
        path = r["product_path"]
        items.append({
            "filename": path.split("/", 1)[1] if path.startswith("drafts/") else path,
            "action": r["action"], "session_id": r["session_id"],
            "version_no": r["version_no"], "versions": r["versions"],
            "size": r.get("size", 0), "updated_at": r["created_at"],
        })
    return {"activity": items}


@router.get("/{filename}/versions", dependencies=[Depends(require_role("admin", "tester", "product"))])
def draft_versions(filename: str):
    """T-1020：单份草稿版本链（活动流水正序，含内容摘录）。"""
    from sg_core import product_activity as pa
    from specstd.workspace import get_context_workspace

    _guard_filename(filename)  # 路径守卫复用（含私有区校验语义）
    ws = get_context_workspace() or ""
    if not ws:
        raise HTTPException(status_code=400, detail="工作区上下文缺失")
    try:
        chain = pa.version_chain(ws, f"drafts/{filename}")
    except Exception:
        chain = []
    return {"versions": [{
        "version_no": v["version_no"], "action": v["action"],
        "session_id": v["session_id"], "emp_no": v["emp_no"],
        "size": v.get("size", 0), "sha": v.get("sha", ""),
        "excerpt": (v.get("content") or "")[:200],
        "created_at": v["created_at"],
    } for v in chain]}


@router.get("/{filename}", dependencies=[Depends(require_role("admin", "tester", "product"))])
def read_draft(filename: str):
    """读取单个草稿内容（含解析出的场景 ID 与依赖关系）。

    M1/M2：viewer 不可读；草稿访问仅限本人私有区。
    """
    _ensure_private_draft_scope()
    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    content = path.read_text(encoding="utf-8")
    depends_on = []
    try:
        raw = yaml.safe_load(content) or {}
        deps = raw.get("depends_on", [])
        if deps:
            depends_on = [d["id"] if isinstance(d, dict) else str(d) for d in deps]
    except Exception:
        pass
    return {"filename": filename, "content": content, "depends_on": depends_on}


# ══════════════════════════════════════════════════════════
# K-046：草稿微调 / 连线 / 试跑（沙箱内操作，不入库、不触发基线重建）
# ══════════════════════════════════════════════════════════

class DraftSaveBody(BaseModel):
    content: str
    session_id: str = ""   # T-1027 F2：关联对话会话——提供时保存后向该会话注入编辑感知


def _update_meta(filename: str) -> None:
    """更新 _meta.json 的 updated_at（保留既有 author/scenario_id 关联）。"""
    import json as _json
    meta_path = _drafts_root() / "_meta.json"
    meta = {}
    if meta_path.is_file():
        try:
            meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    entry = meta.get(filename) or {}
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    meta[filename] = entry
    meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


@router.put("/{filename}", dependencies=[Depends(require_role("admin", "tester"))])
def save_draft(filename: str, body: DraftSaveBody):
    """保存草稿内容（K-046：评审期可微调，不再只有「作废」一条路）。

    写前自动 .bak 备份（对齐 draft_writer patch 惯例，undo 可恢复）；
    仅写 drafts/ 沙箱——入库仍必须走 promote 三道闸。
    T-1027 F2：保存成功后确定性自动格式校验 + ②闸刷新 + user_edit 进活动
    流水版本链；body.session_id 提供时向该会话注入「面板编辑感知」（system 行，
    LLM 可见前端不渲染；run 进行中暂存 pending 由 WS 开跑前排空）。
    """
    from services import user_store
    from services.auth import current_emp_no

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    # 基本可解析性检查（完整格式校验交给 validate 闸，此处只防明显写坏）
    try:
        yaml.safe_load(body.content)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"YAML 解析失败，未写入: {e}")
    old_text = path.read_text(encoding="utf-8")
    shutil.copy2(str(path), str(path) + ".bak")
    path.write_text(body.content, encoding="utf-8")
    _update_meta(filename)
    user_store.audit(current_emp_no(), "edit_draft", f"编辑草稿 {filename}")
    # K-xxx：草稿台账投影（scenario_id/title 从 YAML 解析；author 取 _meta.json）
    try:
        from services import ledger_store
        raw = yaml.safe_load(body.content) or {}
        meta_entry = {}
        _meta_path = _drafts_root() / "_meta.json"
        if _meta_path.is_file():
            try:
                meta_entry = (_json.loads(_meta_path.read_text(encoding="utf-8")) or {}).get(filename) or {}
            except Exception:
                meta_entry = {}
        ledger_store.upsert_draft(
            filename,
            scenario_id=str(raw.get("id", "")),
            title=str(raw.get("title", "")),
            status="draft",
            author=str(meta_entry.get("author", "")),
        )
    except Exception:
        pass

    # ── T-1027 F2：保存后自动校验 + ②闸刷新 + 活动流水 + 对话感知 ──
    # 与 MCP 写路径（draft_writer 六 handler）对齐：REST 人工编辑同样进版本链，
    # 否则「用户改了 v3 → Agent overwrite 记成 v2」的版本叙事失真。
    from mcp_server.tools.validator import validate_scenario_content
    from specstd.workspace import get_context_workspace
    try:
        report = validate_scenario_content(body.content)
    except Exception as e:  # 校验器自身异常不阻断保存，诚实降级 ERROR 报告
        report = {"verdict": "ERROR",
                  "findings": [{"level": "ERROR", "rule": "INTERNAL",
                                "message": f"校验器异常: {e}"}]}
    gate2_status = ""
    try:
        from services import draft_gates
        gate2_status = draft_gates.run_gate2(filename)["gate2_status"]
    except Exception:
        pass  # 无三闸记录/闸执行失败不阻塞保存——卡面展示旧状态
    version_no = None
    try:
        from sg_core import product_activity as pa
        row = pa.record_activity(f"drafts/{filename}", "user_edit",
                                 session_id=body.session_id or "",
                                 emp_no=current_emp_no(),
                                 workspace=get_context_workspace() or "",
                                 content=body.content)
        version_no = (row or {}).get("version_no")
    except Exception:
        pass  # 版本链缺库不影响主流程（文件本身已落盘）

    percept = {"mode": "off"}   # off=无关联会话 / appended=已注入 / pending=运行中暂存
    if body.session_id.strip():
        sid = body.session_id.strip()
        try:
            from services.panel_edit_feedback import build_edit_note, inject_edit_note

            from routers.agent import _run_in_progress, _sessions_dir
            emp = current_emp_no()
            ws_name = get_context_workspace() or ""
            # 全文读取指引的工作区相对路径（spec(action="read") 第一解析根为工作区根；
            # 解析不出时诚实省略该行，不给 Agent 不可执行的路径）
            ws_root = get_workspace_root()
            read_path = ""
            if ws_root:
                try:
                    read_path = str(path.resolve().relative_to(ws_root.resolve())).replace("\\", "/")
                except (ValueError, OSError):
                    read_path = ""
            note = build_edit_note(filename, old_text, body.content, report,
                                   read_path=read_path, version_no=version_no)
            percept = inject_edit_note(
                _sessions_dir(emp), ws_name, sid, note,
                busy=bool(_run_in_progress(sid)))
        except ValueError:
            percept = {"mode": "off", "reason": "invalid_session_id"}
        except Exception:
            percept = {"mode": "off", "reason": "error"}   # 感知失败不回滚保存

    return {"ok": True, "filename": filename,
            "validate": report, "gate2_status": gate2_status or None,
            "version_no": version_no, "percept": percept}


class DraftDepBody(BaseModel):
    dep_id: str
    mode: str = "shared"


@router.post("/{filename}/deps", dependencies=[Depends(require_role("admin", "tester"))])
def add_draft_dep(filename: str, body: DraftDepBody):
    """草稿连线（K-046）：deps_editor 文本外科手术加 depends_on，与库内场景同一语义。

    守卫：自依赖拒绝、dep 目标必须存在（库内场景或另一草稿）、环预检（草稿并入图）。
    """
    from services import dep_suggest, deps_editor, user_store
    from services.auth import current_emp_no

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    if body.mode not in ("shared", "exclusive"):
        raise HTTPException(status_code=400, detail=f"mode 非法: {body.mode}")

    nodes = dep_suggest.scan_nodes(_scenarios_root(), _drafts_root())
    by_id = {n.id: n for n in nodes}
    try:
        consumer_raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"草稿 YAML 解析失败: {e}")
    consumer_id = str(consumer_raw.get("id", "") or "")
    if not consumer_id:
        raise HTTPException(status_code=422, detail="草稿缺少 id 字段，无法连线")
    if body.dep_id == consumer_id:
        raise HTTPException(status_code=400, detail="不允许自依赖")
    dep = by_id.get(body.dep_id)
    if not dep:
        raise HTTPException(status_code=404, detail=f"依赖目标不存在: {body.dep_id}")

    # 环预检：草稿并入图后，consumer 若在 dep 的依赖闭包中则成环
    graph = dep_suggest._build_graph(_scenarios_root(), _drafts_root())
    if graph and consumer_id in graph.by_id and body.dep_id in graph.by_id:
        try:
            if consumer_id in graph.closure(body.dep_id):
                raise HTTPException(status_code=409,
                                    detail=f"会形成循环依赖: {consumer_id} → {body.dep_id} → … → {consumer_id}")
        except HTTPException:
            raise
        except Exception:
            pass

    shutil.copy2(str(path), str(path) + ".bak")
    try:
        deps_editor.add_dep(str(path), body.dep_id, body.mode, dep.version or "0.1")
    except deps_editor.DepsEditError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _update_meta(filename)
    user_store.audit(current_emp_no(), "edit_draft_dep",
                     f"草稿 {filename}({consumer_id}) 加依赖 {body.dep_id}({body.mode})")
    return {"ok": True, "consumer": consumer_id, "dep_id": body.dep_id, "mode": body.mode}


@router.post("/{filename}/trial-run", dependencies=[Depends(require_role("admin", "tester"))])
async def trial_run_draft(filename: str):
    """草稿试跑（K-046：与 MCP run_scenario 同一语义的 HTTP 化薄封装）。

    草稿并入依赖图 → in-process run_single 按闭包执行（真实环境联网调用）。
    未入库先验证，豁免 covers 闸（草稿可能尚未锚定 FR）；报告落 .specguard/reports/。
    """
    import asyncio

    from services import user_store
    from services.auth import current_emp_no

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")

    from mcp_server.tools.scenario_tools import _handle_run_scenario
    # MCP handler 返回 TextContent 列表；复用确保两套入口同一语义（asyncio.to_thread 透传工作区 contextvar）。
    # 2026-08-26 修复：handler 是同步函数，此前误包 asyncio.run() 必抛 TypeError——
    # 试跑结果永远到不了前端（恒 500 Internal Server Error）；同步 handler 直接 to_thread 调用。
    # 任何未预期异常返回结构化错误 JSON（不再裸 500，前端可见具体异常信息）。
    try:
        contents = await asyncio.to_thread(_handle_run_scenario, {"draft": filename})
        try:
            result = _json.loads(contents[0].text)
        except Exception:
            result = {"ok": False, "error": contents[0].text if contents else "未知错误"}
    except Exception as e:
        result = {"ok": False, "error": f"试跑执行异常: {type(e).__name__}: {e}"}
    if result.get("error", "").startswith("错误："):
        raise HTTPException(status_code=400, detail=result["error"])
    try:
        user_store.audit(current_emp_no(), "trial_run_draft",
                         f"试跑草稿 {filename} → {result.get('verdict', '?')}")
    except Exception:
        pass  # 审计失败不吞试跑结果
    return result


# ══════════════════════════════════════════════════════════
# 三道闸：① 格式校验 ② 发布门禁 ③ 入库
# ══════════════════════════════════════════════════════════

@router.post("/{filename}/validate", dependencies=[Depends(require_role("admin", "tester"))])
def validate_draft(filename: str):
    """格式校验（format + covers + 注册表引用，与 MCP validate 同一实现）。"""
    from mcp_server.tools.validator import validate_scenario_content

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    return validate_scenario_content(path.read_text(encoding="utf-8"))


class PromoteBody(BaseModel):
    module: str          # 目标模块目录（相对 scenarios/，如 employee/person-profile）
    skip_gate: bool = False  # 仅调试用途跳过发布门禁（默认 False，正常入库必须过门禁）
    replace: bool = False    # T-313：覆盖同名场景（Agent 更新已有场景；原文件备份+失败回滚）


class ReviewBody(BaseModel):
    decision: str        # approved / rejected
    comment: str = ""    # 评审意见（留痕）


@router.post("/{filename}/review", dependencies=[Depends(require_role("admin", "tester"))])
def review_draft(filename: str, body: ReviewBody):
    """第①闸人工评审（T-061）：人拍板 approved/rejected，留痕 reviewer+ts。

    gate2 未 pass 时 approved 被拒（②失败打回，①不生效）。
    """
    from services import draft_gates, user_store
    from services.auth import current_emp_no

    try:
        gate = draft_gates.review_draft(
            filename, body.decision, reviewer=current_emp_no(),
            comment=body.comment)
    except draft_gates.GateError as e:
        status = 400 if e.code in ("invalid_state", "missing_reviewer", "gate2_not_pass") else 404
        raise HTTPException(status_code=status, detail=str(e))
    try:
        user_store.audit(current_emp_no(), "review_draft",
                         f"草稿 {filename} 评审{body.decision}")
    except Exception:
        pass
    return {"ok": True, "filename": filename, "gates": {
        "g1": gate["gate1_status"], "g2": gate["gate2_status"],
        "g3": gate["gate3_status"],
        "gate1_reviewer": gate.get("gate1_reviewer", ""),
        "gate1_ts": gate.get("gate1_ts", ""),
    }}


@router.post("/{filename}/revalidate", dependencies=[Depends(require_role("admin", "tester"))])
def revalidate_draft(filename: str):
    """重跑第②闸（T-061）：草稿修改后重新格式校验，报告逐项更新。"""
    from services import draft_gates, user_store
    from services.auth import current_emp_no

    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    try:
        gate = draft_gates.run_gate2(filename)
    except draft_gates.GateError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        user_store.audit(current_emp_no(), "revalidate_draft",
                         f"草稿 {filename} 重跑第②闸 → {gate['gate2_status']}")
    except Exception:
        pass
    return {"ok": True, "filename": filename,
            "gate2_status": gate["gate2_status"],
            "gate2_report": gate.get("gate2_report", {})}


@router.get("/{filename}/conflict", dependencies=[Depends(require_role("admin", "tester"))])
def draft_conflict(filename: str):
    """入库前 ID 冲突预检：草稿场景 ID 是否已存在于场景库（含既有位置/模块）。

    K-xxx：把「场景 id 重复」类失败前置为可执行提示——UI 入库弹窗打开时调用，
    冲突时自动选中既有模块并勾选覆盖。
    """
    from services import draft_promote
    try:
        return draft_promote.check_id_conflict(filename)
    except draft_promote.PromoteError as e:
        status = draft_promote.HTTP_STATUS.get(e.code, 500)
        raise HTTPException(status_code=status, detail=str(e))


@router.post("/{filename}/promote", dependencies=[Depends(require_role("admin", "tester"))])
def promote_draft(filename: str, body: PromoteBody):
    """入库：格式校验 PASS → 移入 scenarios/{module}/ → 更新契约基线 → 发布门禁。

    发布门禁失败自动回滚（文件移回 drafts/，基线还原）。
    T-313：replace=true 覆盖同名场景（更新已有场景的写入路径）。
    K-015：核心逻辑抽取至 services.draft_promote（MCP promote_draft 工具复用同一实现）。
    """
    from services import draft_promote
    from services.auth import current_emp_no
    try:
        return draft_promote.promote(filename, body.module, skip_gate=body.skip_gate,
                                     emp_no=current_emp_no(), replace=body.replace)
    except draft_promote.PromoteError as e:
        status = draft_promote.HTTP_STATUS.get(e.code, 500)
        raise HTTPException(status_code=status,
                            detail={"message": str(e), **(e.detail or {})} if e.detail else str(e))


@router.post("/{filename}/discard", dependencies=[Depends(require_role("admin", "tester"))])
def discard_draft(filename: str):
    """废弃草稿（移入 drafts/_trash/，可人工恢复）。"""
    path = _guard_filename(filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"草稿不存在: {filename}")
    trash = _trash_dir()
    trash.mkdir(parents=True, exist_ok=True)
    target = trash / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    shutil.move(str(path), str(target))
    # K-xxx：草稿台账状态 → 已废弃
    try:
        from services import ledger_store
        ledger_store.set_draft_status(filename, "discarded")
    except Exception:
        pass
    return {"ok": True, "trashed_to": str(target.relative_to(get_workspace_root() or SG_ROOT)).replace("\\", "/")}


@router.post("/reset", dependencies=[Depends(require_role("admin", "tester"))])
def reset_draft_area():
    """重置草稿区状态：清空草稿、回收站、元数据、DB 三闸与台账。

    操作范围（仅当前工作区私有草稿区）：
    - 删除 drafts/ 下所有 .yaml / .bak 文件
    - 清空 _trash/ 回收站
    - 重置 _meta.json 为空
    - 删除 sg_draft_gates 中当前工作区的记录
    - 删除 ledger_store drafts 表中当前工作区的记录
    """
    from services import draft_gates, ledger_store, user_store
    from services.auth import current_emp_no

    from specstd.workspace import get_active_workspace

    drafts_root = _drafts_root()
    ws = (get_active_workspace() or {}).get("name", "") if get_active_workspace else ""

    stats = {"yaml_deleted": 0, "bak_deleted": 0, "trash_deleted": 0}

    # 1. 删除 drafts/ 下所有 .yaml 和 .bak
    if drafts_root.is_dir():
        for f in list(drafts_root.glob("*.yaml")) + list(drafts_root.glob("*.yml")):
            f.unlink(missing_ok=True)
            stats["yaml_deleted"] += 1
        for f in list(drafts_root.glob("*.bak")):
            f.unlink(missing_ok=True)
            stats["bak_deleted"] += 1

        # 2. 清空 _meta.json
        meta_path = drafts_root / "_meta.json"
        if meta_path.is_file():
            meta_path.write_text("{}\n", encoding="utf-8")

        # 3. 清空 _trash/
        trash = drafts_root / "_trash"
        if trash.is_dir():
            for f in list(trash.glob("*")):
                if f.is_file():
                    f.unlink(missing_ok=True)
                    stats["trash_deleted"] += 1

    # 4. 删除 DB 三闸记录
    if ws:
        draft_gates.delete_workspace_gates(ws)

    # 5. 删除 DB 草稿台账
    if ws:
        ledger_store.clear_drafts(ws)

    user_store.audit(current_emp_no(), "reset_draft_area",
                     f"重置草稿区：{stats['yaml_deleted']} yaml, "
                     f"{stats['bak_deleted']} bak, {stats['trash_deleted']} trash")

    return {"ok": True, "workspace": ws, **stats}
