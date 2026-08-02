"""参考信息 API：步骤类型 / 断言器 / 工号池角色 / 环境变量 / 上游变量 — 编辑器快速引用数据源"""

import os
import re
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth import require_role
from services.format_spec import generate_format_spec_md, get_next_scenario_id, validate_scenario_id

router = APIRouter(prefix="/api/reference", tags=["reference"])

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SYSTEMS_TDM = SG_ROOT / "systems" / "tdm"


# ── 步骤类型参考 ──────────────────────────────────────────

_STEP_TEMPLATES = [
    {
        "type": "select_emp",
        "desc": "工号池选号（自动 DB 校验）",
        "snippet": "- tool: {use: select_emp, with: {role: snapshot_rich}, save: emp}",
        "params": [
            {"name": "role", "required": True, "desc": "工号池角色名"},
            {"name": "save", "required": True, "desc": "变量保存名"},
            {"name": "exclusive", "required": False, "desc": "true = 独占租约（写型场景）"},
        ],
    },
    {
        "type": "fetch_permission",
        "desc": "抓取账号权限预言（hr-center）",
        "snippet": "- tool: {use: fetch_permission, with: {account: default}, save: scope}",
        "params": [
            {"name": "account", "required": True, "desc": "账号别名"},
            {"name": "resource_code", "required": False, "desc": "资源码（默认 env.resource_code）"},
            {"name": "save", "required": True, "desc": "变量保存名"},
        ],
    },
    {
        "type": "call",
        "desc": "HTTP 调用",
        "snippet": "- call:\n    as: default\n    method: GET\n    path: /api/employee/profile\n    params:\n      empNo: \"{{emp.no}}\"\n    save: resp",
        "params": [
            {"name": "as", "required": False, "desc": "账号别名（none=匿名）"},
            {"name": "method", "required": True, "desc": "GET/POST/PUT/DELETE"},
            {"name": "path", "required": True, "desc": "接口路径"},
            {"name": "params", "required": False, "desc": "Query 参数"},
            {"name": "json", "required": False, "desc": "JSON body"},
            {"name": "save", "required": True, "desc": "变量保存名"},
        ],
    },
    {
        "type": "oss_upload",
        "desc": "上传本地文件到 OSS",
        "snippet": "- tool: {use: oss_upload, with: {file: 'path/to/file.xlsx'}, save: upload}",
        "params": [
            {"name": "file", "required": True, "desc": "本地文件路径"},
            {"name": "tenant", "required": False, "desc": "租户 ID（默认 COREHR）"},
            {"name": "save", "required": True, "desc": "变量保存名"},
        ],
    },
    {
        "type": "oss_download",
        "desc": "从 OSS 下载文件",
        "snippet": "- tool: {use: oss_download, with: {ossKey: '{{upload.ossKey}}'}, save: download}",
        "params": [
            {"name": "ossKey", "required": True, "desc": "OSS 文件 key"},
            {"name": "output_dir", "required": False, "desc": "输出目录（默认 downloads）"},
            {"name": "save", "required": True, "desc": "变量保存名"},
        ],
    },
    {
        "type": "poll",
        "desc": "异步轮询（重复调用直至条件满足）",
        "snippet": "- poll:\n    call: {method: GET, path: /api/task/result}\n    until:\n      - json: {path: '$.data.status', eq: 'DONE'}\n    interval_ms: 2000\n    timeout_ms: 60000\n    save: result",
        "params": [
            {"name": "call", "required": True, "desc": "轮询调用（复用 call 语法）"},
            {"name": "until", "required": True, "desc": "退出条件（复用 verify 断言）"},
            {"name": "interval_ms", "required": False, "desc": "轮询间隔（默认 2000ms）"},
            {"name": "timeout_ms", "required": False, "desc": "超时时间（默认 60000ms）"},
            {"name": "on_timeout", "required": False, "desc": "fail（默认）| skip"},
            {"name": "save", "required": True, "desc": "变量保存名"},
        ],
    },
    {
        "type": "random",
        "desc": "随机数据生成（随机数/随机文本/随机池抓取/UUID）",
        "snippet": "- tool: {use: random, with: {type: number, min: 1, max: 100}, save: num}",
        "params": [
            {"name": "type", "required": True, "desc": "number/float/text/uuid/pick"},
            {"name": "min", "required": False, "desc": "最小值（number）"},
            {"name": "max", "required": False, "desc": "最大值（number）"},
            {"name": "pool", "required": False, "desc": "词库名（text）"},
            {"name": "suffix", "required": False, "desc": "加随机后缀（text）"},
            {"name": "items", "required": False, "desc": "自定义列表（pick）"},
            {"name": "save", "required": True, "desc": "变量保存名"},
        ],
    },
    {
        "type": "set_var",
        "desc": "变量设置",
        "snippet": "- tool: {use: set_var, with: {vars: {key: \"value\"}}}",
        "params": [{"name": "vars", "required": True, "desc": "变量字典"}],
    },
    {
        "type": "db_query",
        "desc": "只读 SQL 查询",
        "snippet": "- db_query: {sql: 'SELECT * FROM tdm_emp_employee WHERE emp_no = \"{{emp.no}}\"', save: rows, note: '查询员工'}",
        "params": [
            {"name": "sql", "required": True, "desc": "SELECT 语句"},
            {"name": "save", "required": True, "desc": "变量保存名"},
            {"name": "note", "required": False, "desc": "备注"},
        ],
    },
    {
        "type": "python",
        "desc": "Python 脚本（复杂逻辑逃生舱：ns 读写变量 / output 产出 / http+db 可用）",
        "snippet": "- python:\n    script: |\n      rows = ns['rows']\n      output = [r for r in rows if r['score'] is None]\n    save: null_rows",
        "params": [
            {"name": "script", "required": True, "desc": "脚本内容（或 file 引用外部文件）"},
            {"name": "save", "required": False, "desc": "取脚本 output 变量注入命名空间"},
        ],
    },
]


@router.get("/steps")
def ref_steps():
    """可用步骤类型清单"""
    return _STEP_TEMPLATES


@router.get("/tools")
def ref_tools():
    """tool 目录（引擎注册表动态生成：名称/说明/参数/产出变量）"""
    from services.format_spec import get_tool_catalog
    return get_tool_catalog()


# ── 断言器参考 ────────────────────────────────────────────

_ORACLE_TEMPLATES = [
    {"name": "profile_matches_db", "desc": "basicInfo ↔ tdm_emp_employee", "snippet": "- oracle: profile_matches_db"},
    {"name": "snapshot_frozen", "desc": "状态型字段 ↔ 快照 JSON 严格比对", "snippet": "- oracle: snapshot_frozen"},
    {"name": "result_time_filtered", "desc": "切片结果时点过滤校验", "snippet": "- oracle: result_time_filtered"},
    {"name": "dhr_fallback_matches", "desc": "DHR 降级 basicInfo ↔ dhr_employee", "snippet": "- oracle: dhr_fallback_matches"},
    {"name": "permission_filtered", "desc": "corpCode 三维权限过滤（FR-013/015）", "snippet": "- oracle: permission_filtered"},
    {"name": "vm_filtered", "desc": "verticalManager 维度过滤（FR-016/017）", "snippet": "- oracle: vm_filtered"},
    {"name": "inv_context_injected", "desc": "inv* 上下文注入（FR-006）", "snippet": "- oracle: inv_context_injected"},
    {"name": "trend_sorted_desc", "desc": "trend 接口按 inventoryDate 降序", "snippet": "- oracle: trend_sorted_desc"},
]


@router.get("/oracles")
def ref_oracles():
    """可用断言器清单"""
    return _ORACLE_TEMPLATES


# ── 工号池角色 ────────────────────────────────────────────


@router.get("/emp-roles")
def ref_emp_roles():
    """工号池角色清单（从 emp-pool.yaml 动态读取）"""
    pool_file = SYSTEMS_TDM / "config" / "emp-pool.yaml"
    if not pool_file.is_file():
        return []
    with open(pool_file, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    roles = []
    for name, cfg in (raw.get("roles") or {}).items():
        roles.append({
            "name": name,
            "description": cfg.get("description", ""),
            "candidate_count": len(cfg.get("candidates") or []),
            "has_check": cfg.get("check") is not None,
        })
    return roles


# ── 环境变量参考 ──────────────────────────────────────────


@router.get("/env-vars")
def ref_env_vars():
    """环境变量/插值参考"""
    return [
        {"path": "env.resource_code", "desc": "默认资源码（env.sit.yaml default_resource_code）", "example": "VIEW_TELENT_SEARCH"},
        {"path": "emp.no", "desc": "工号池选中的工号（select_emp 产出）", "example": "90024713"},
        {"path": "emp.role", "desc": "工号池角色名", "example": "snapshot_rich"},
        {"path": "emp.activity_id", "desc": "快照活动 ID", "example": "1936"},
        {"path": "emp.session_id", "desc": "快照会话 ID", "example": "2011"},
        {"path": "emp.snapshot_type", "desc": "快照类型（RESULT/LOCK）", "example": "RESULT"},
        {"path": "resp.status", "desc": "HTTP 响应状态码", "example": "200"},
        {"path": "resp.json", "desc": "HTTP 响应 JSON body", "example": "{...}"},
        {"path": "scope.corp_codes", "desc": "账号权限范围 corpCode 列表", "example": "[\"C012\"]"},
        {"path": "scope.has_any", "desc": "是否有任何权限", "example": "true"},
        {"path": "{{上游场景ID.save变量.字段}}", "desc": "跨场景引用上游变量", "example": "{{PP-PREP-001.emp.no}}"},
    ]


# ── 环境配置读写 ──────────────────────────────────────────

_ENV_GLOB = "env.*.yaml"


def _env_file(env: str) -> Path:
    """按环境名定位配置：systems/{system}/config/env.{env}.yaml（默认 sit）。"""
    name = (env or "sit").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise HTTPException(status_code=400, detail=f"环境名非法: {env}")
    return SYSTEMS_TDM / "config" / f"env.{name}.yaml"


@router.get("/envs")
def list_envs():
    """T-306：可用环境列表（扫描 systems/{system}/config/env.*.yaml）。

    独立环境配置菜单的数据源——环境信息不再只有 sit 一份。
    """
    files = sorted((SYSTEMS_TDM / "config").glob(_ENV_GLOB))
    envs = [{"name": f.stem[len("env."):], "path": str(f)} for f in files]
    return {"system": "tdm", "envs": envs,
            "current": envs[0]["name"] if envs else "sit"}


@router.get("/env-config")
def get_env_config(env: str = "sit"):
    """读取环境配置（返回 YAML 原文 + 解析后的结构化数据；env 默认 sit 向后兼容）"""
    env_file = _env_file(env)
    if not env_file.is_file():
        return {"raw": "", "parsed": {}, "env": env, "exists": False}
    with open(env_file, "r", encoding="utf-8") as f:
        raw = f.read()
    parsed = yaml.safe_load(raw) or {}
    return {"raw": raw, "parsed": parsed, "env": env, "exists": True}


class EnvConfigBody(BaseModel):
    raw: str


@router.put("/env-config", dependencies=[Depends(require_role("admin"))])
def save_env_config(body: EnvConfigBody, env: str = "sit"):
    """保存环境配置（校验 YAML 语法后写入；env 默认 sit 向后兼容）"""
    try:
        parsed = yaml.safe_load(body.raw)
    except yaml.YAMLError as e:
        return {"ok": False, "error": f"YAML 语法错误: {e}"}
    if not isinstance(parsed, dict):
        return {"ok": False, "error": "配置必须是 YAML 对象"}
    env_file = _env_file(env)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as f:
        f.write(body.raw)
    return {"ok": True, "env": env}


@router.post("/test-db", dependencies=[Depends(require_role("admin"))])
def test_db_connection(env: str = "sit"):
    """测试数据库连接（读取 env.{env}.yaml + devops 凭据回退）"""
    env_file = _env_file(env)
    if not env_file.is_file():
        return {"ok": False, "error": f"env.{env}.yaml 不存在"}
    with open(env_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    db = cfg.get("db") or {}
    if not db.get("host") or not db.get("user"):
        return {"ok": False, "error": "db.host 或 db.user 未配置"}

    # 密码回退：YAML → 环境变量 → devops .env.devops（与引擎 config.py 一致）
    password = db.get("password", "")
    if not password or password.startswith("${"):
        import os as _os
        password = _os.environ.get("SG_DB_PASSWORD", "")
    if not password:
        devops_env = _os.path.expanduser(r"~\.qoder\skills\devops\scripts\.env.devops")
        if _os.path.isfile(devops_env):
            with open(devops_env, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DB_PASSWORD="):
                        password = line.split("=", 1)[1].strip()
                        break

    try:
        import pymysql
        conn = pymysql.connect(
            host=db["host"],
            port=int(db.get("port", 3306)),
            user=db["user"],
            password=password,
            database=db.get("name", "hr_center"),
            charset=db.get("charset", "utf8mb4"),
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        return {"ok": True, "message": f"连接成功: {db['user']}@{db['host']}:{db.get('port', 3306)}/{db.get('name', 'hr_center')}"}
    except Exception as e:
        return {"ok": False, "error": f"连接失败: {type(e).__name__}: {e}"}


# ── YAML 格式规范（供 Agent 生成合规测试用例） ──────────────


@router.get("/yaml-format-spec-md")
def ref_yaml_format_spec_md():
    """导出完整的 YAML 格式规范 Markdown 文档（供 Agent 生成合规 test-case）"""
    return {"content": generate_format_spec_md()}


@router.get("/next-id")
def ref_next_id(prefix: str = "", type: str = ""):
    """获取下一可用场景 ID（保证唯一性）"""
    if not prefix or not type:
        return {"error": "需要 prefix 和 type 参数（如 ?prefix=PP&type=RC）"}
    return get_next_scenario_id(prefix, type)


@router.get("/validate-id/{scenario_id}")
def ref_validate_id(scenario_id: str):
    """校验场景 ID 是否唯一"""
    return validate_scenario_id(scenario_id)


@router.get("/yaml-format-spec")
def ref_yaml_format_spec():
    """导出 SpecGuard 对各类 YAML 文件的格式要求"""
    return {
        "scenario_yaml": {
            "description": "场景测试 YAML 格式（scenarios/**/*.yaml）",
            "required_fields": {
                "id": "场景唯一标识（如 PP-RC-001），全局唯一",
                "title": "场景标题",
                "flow": "执行步骤列表（至少一个 flow 或 verify）",
            },
            "optional_fields": {
                "test_type": "unit | scenario（缺省为 scenario）",
                "priority": "P0 | P1 | P2",
                "tags": "[resolver, permission, snapshot, security, prep]",
                "depends_on": "[场景ID 或 {id, mode: shared|exclusive}]",
                "produces": "[{resource, state}] 产出资源声明",
                "teardown": "清理步骤（与 flow 同语法）",
                "verify": "断言列表",
                "doc": "{given, when, then, covers: [FR-xxx]}",
            },
            "step_types": {
                "select_emp": "{role, save, exclusive?} 工号池选号",
                "fetch_permission": "{account, resource_code?, save} 权限预言",
                "call": "{as, method, path, params?, json?, save} HTTP 调用",
                "set_var": "{vars: {k: v}} 变量设置",
                "db_query": "{sql, save, note?} 只读 SQL",
            },
            "verify_types": {
                "status": "{of?, eq} HTTP 状态码断言",
                "json": "{of?, path, eq|ne|not_null|contains|len_gt|absent} JSONPath 断言",
                "oracle": "断言器名称（snapshot_frozen 等 8 个）",
            },
            "variable_syntax": "{{save名.字段}} 或 {{上游场景ID.save名.字段}}",
        },
        "plan_yaml": {
            "description": "测试计划 YAML 格式（plans/*.yaml）",
            "required_fields": {
                "id": "计划唯一标识",
                "name": "计划名称",
            },
            "optional_fields": {
                "description": "计划描述",
                "env": "sit | uat",
                "filter": "{scenarios: [], tags: [], modules: []} 场景过滤",
                "breakpoints": "[场景ID] 断点列表（执行到该场景前暂停）",
                "source_delta": "来源 delta 代号",
            },
        },
        "emp_pool_yaml": {
            "description": "工号池 YAML 格式（systems/tdm/config/emp-pool.yaml）",
            "structure": {
                "roles": "{角色名: {description, candidates: [工号], check: {sql, min}}}",
            },
        },
        "env_yaml": {
            "description": "环境配置 YAML 格式（systems/tdm/config/env.sit.yaml）",
            "structure": {
                "tdm_base": "TDM 网关地址",
                "hr_center_base": "权限中台地址",
                "default_resource_code": "权限资源码",
                "accounts": "{别名: {ad, emp_no}} 账号池",
                "db": "{host, port, user, password, name} 数据库",
                "sso": "{domain, app_id, password} SSO 配置",
            },
        },
        "validation_rules": {
            "T1": "YAML 可解析，有 id + flow/verify",
            "T2": "test_type 必须为 unit/scenario",
            "T3": "unit 类型必须有 output/produces 或 save 声明",
            "T4": "depends_on 引用必须指向已存在的场景 ID",
            "T5": "scenario 类型无 depends_on 且非 prep 标签 → 疑似孤例（WARN）",
        },
    }


# ── 单场景产出详情（供依赖选择时展示） ──────────────────────


def _extract_scenario_detail(scenario_id: str) -> dict | None:
    """提取单个场景的产出详情：title/doc/saves/produces"""
    scenarios_dir = SG_ROOT / "scenarios"
    for dirpath, _dirs, filenames in os.walk(scenarios_dir):
        for fn in filenames:
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if raw.get("id") != scenario_id:
                continue
            # 提取 flow 中的 save 变量
            saves = []
            for step in (raw.get("flow") or []):
                if isinstance(step, dict):
                    for step_type, body in step.items():
                        if isinstance(body, dict) and body.get("save"):
                            saves.append({
                                "name": body["save"],
                                "step_type": step_type,
                            })
            # 提取 produces 声明
            produces = raw.get("produces") or []
            doc = raw.get("doc") or {}
            return {
                "id": scenario_id,
                "title": raw.get("title", ""),
                "given": doc.get("given", ""),
                "saves": saves,
                "produces": produces,
            }
    return None


@router.get("/scenario-detail/{scenario_id}")
def ref_scenario_detail(scenario_id: str):
    """单场景产出详情（依赖选择时展示上游能提供的变量）"""
    detail = _extract_scenario_detail(scenario_id)
    if detail is None:
        return {"id": scenario_id, "title": "", "given": "", "saves": [], "produces": []}
    return detail


# ── 上游场景变量参考 ──────────────────────────────────────


@router.get("/upstream-vars/{scenario_id}")
def ref_upstream_vars(scenario_id: str):
    """某场景依赖的上游场景产出的可用变量"""
    scenarios_dir = SG_ROOT / "scenarios"
    for dirpath, _dirs, filenames in os.walk(scenarios_dir):
        for fn in filenames:
            if not fn.endswith((".yaml", ".yml")) or fn.startswith("_"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if raw.get("id") != scenario_id:
                continue
            deps = raw.get("depends_on") or []
            result = []
            for d in deps:
                dep_id = d if isinstance(d, str) else d.get("id", "")
                # 找上游场景的 save 变量
                for dp2, _d2, fns2 in os.walk(scenarios_dir):
                    for fn2 in fns2:
                        if not fn2.endswith((".yaml", ".yml")) or fn2.startswith("_"):
                            continue
                        path2 = os.path.join(dp2, fn2)
                        with open(path2, "r", encoding="utf-8") as f2:
                            raw2 = yaml.safe_load(f2) or {}
                        if raw2.get("id") != dep_id:
                            continue
                        saves = []
                        for step in (raw2.get("flow") or []):
                            if isinstance(step, dict):
                                for _st, body in step.items():
                                    if isinstance(body, dict) and body.get("save"):
                                        saves.append(body["save"])
                        result.append({
                            "scenario_id": dep_id,
                            "title": raw2.get("title", ""),
                            "saves": saves,
                            "usage": [f"{{{{{dep_id}.{s}}}}}" for s in saves],
                        })
            return result
    return []
