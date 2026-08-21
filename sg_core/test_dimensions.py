"""test_dimensions — 测试类型学：doc.dimensions 受控词表 + 维度↔断言模式映射（T-981）。

定位：把测试设计意图显式化为机器可聚合的受控标注——
  - doc.dimensions 声明本场景的测试维度（受控词表 1~3 个），是覆盖面板按维度
    聚合、发现「全是正向、没有边界/负向」类测试设计盲区的基础；
  - 维度↔断言模式映射是**测试设计自检**（WARN 级，非硬门禁）：声明了维度但
    verify 没有对应断言证据时给出提示，防止「标注与断言两张皮」。

词表与映射是格式规范（sg_core/format_spec.py §1.2）的机器同源——
规范文档表格与本模块常量一一对应（test_dimensions 测试做漂移守护）。

纯函数零依赖：输入场景 raw dict（yaml.safe_load 结果），输出 findings 列表，
mcp_server validator 与工作台 spec_validator 双路复用。
"""

from __future__ import annotations

# ── 受控词表（与 format_spec §1.2「doc 层选填字段」表格一一对应）──
DIMENSIONS: dict[str, str] = {
    "happy-path": "正向主流程：典型输入下的预期行为",
    "negative": "负向异常：非法输入/错误状态被显式拒绝",
    "boundary": "边界值：空值/特殊值/极限值的处理正确性",
    "permission": "权限过滤：数据权限裁剪与越权拒绝",
    "security": "安全认证：认证拒绝与 fail-secure 不泄露",
    "state": "状态一致性：DB/快照/状态流转的持久层校对",
    "isolation": "数据隔离：行级/多主体对照（正常与异常并存）",
    "regression": "回归防护：历史缺陷复现防护（标注语义，不进映射检查）",
}

# ── 断言证据模式（extract_evidence 从 verify/flow 确定性提取）──
# http_ok        status 断言 eq < 400（成功响应）
# http_error     status 断言 eq ≥ 400（显式 HTTP 拒绝）
# body_error_code 统一包装协议错误码：json 断言 path ∈ {$.status, $.code, ...} 且 eq ≠ 200/0
# error_message  json 断言 path 含 message/error*/failCount（错误消息证据）
# absent         json absent: true（不泄露/不存在证据）
# json_field     任意 json 断言
# oracle         任意 oracle 断言（DB 校对断言器）
# db_proof       oracle 断言，或 json 断言 of 指向 db_query 的 save（持久层证据）
# python         python 脚本断言

# 成功语义的包装协议返回码（body_error_code 判定时排除）
_OK_BODY_CODES = {"200", "0", "ok", "success", "true", "none", ""}

# 包装协议错误码常见路径（统一返回体 {status, message, data}）
_ERROR_CODE_PATHS = {"$.status", "$.code", "$.data.status", "$.data.code"}

_ERROR_MSG_KEYS = ("message", "errormsg", "error", "failcount")

# ── 维度↔断言证据映射（任一证据命中即通过；regression 不映射）──
DIMENSION_EVIDENCE: dict[str, tuple[frozenset, str]] = {
    "happy-path": (
        frozenset({"http_ok", "json_field", "db_proof"}),
        "正向场景应断言成功响应（status 2xx / 响应体字段）",
    ),
    "negative": (
        frozenset({"http_error", "body_error_code", "error_message"}),
        "负向场景应断言显式拒绝信号（HTTP 4xx/5xx、包装协议错误码 $.status≠200、"
        "错误消息或 failCount）",
    ),
    "boundary": (
        frozenset({"json_field", "db_proof", "python"}),
        "边界场景应显式断言边界值的处理结果（响应字段或 DB 证据）",
    ),
    "permission": (
        frozenset({"oracle", "absent", "http_error", "body_error_code"}),
        "权限场景应给出过滤/拒绝证据（DB 校对 oracle、absent 不泄露、"
        "HTTP 4xx 或包装协议错误码）",
    ),
    "security": (
        frozenset({"http_error", "body_error_code", "absent"}),
        "安全场景应断言拒绝与不泄露（HTTP 4xx / 包装协议错误码 / absent）",
    ),
    "state": (
        frozenset({"db_proof"}),
        "状态一致性场景应有持久层证据（oracle 断言器或 db_query 派生 json 断言）",
    ),
    "isolation": (
        frozenset({"db_proof", "absent"}),
        "隔离场景应有对照证据（db_query 派生断言比对正常/异常行，或 absent 证明不越界）",
    ),
}


def _as_int(v) -> int | None:
    """status eq 值归一（int / 数字字符串），不可解析返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _is_error_code_assertion(path: str, body: dict) -> bool:
    """统一包装协议错误码断言：path 是返回体状态码字段且 eq 非成功码。"""
    norm = path.replace(" ", "").replace("'", "").replace('"', "")
    if norm not in _ERROR_CODE_PATHS or "eq" not in body:
        return False
    return str(body.get("eq")).strip().lower() not in _OK_BODY_CODES


def extract_evidence(raw: dict) -> set[str]:
    """从场景 raw YAML 提取断言证据特征集（确定性，纯读）。"""
    evidence: set[str] = set()
    flow = raw.get("flow") or []
    verify = raw.get("verify") or []

    db_saves = set()
    for step in flow:
        if isinstance(step, dict) and isinstance(step.get("db_query"), dict):
            save = step["db_query"].get("save")
            if save:
                db_saves.add(save)

    for item in verify:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if isinstance(status, dict):
            code = _as_int(status.get("eq"))
            if code is not None:
                evidence.add("http_ok" if code < 400 else "http_error")
        body = item.get("json")
        if isinstance(body, dict):
            evidence.add("json_field")
            path = str(body.get("path", "") or "")
            if body.get("absent") is True:
                evidence.add("absent")
            if body.get("of") and body.get("of") in db_saves:
                evidence.add("db_proof")
            if _is_error_code_assertion(path, body):
                evidence.add("body_error_code")
            pl = path.lower()
            if any(k in pl for k in _ERROR_MSG_KEYS) and any(
                    op in body for op in ("contains", "eq", "ne", "len_gt")):
                evidence.add("error_message")
        if "oracle" in item:
            evidence.add("oracle")
            evidence.add("db_proof")
        if "python" in item:
            evidence.add("python")
    return evidence


def check_dimensions(raw: dict) -> list[dict]:
    """维度校验：词表合法性（ERROR）+ 缺失提示（WARN）+ 维度↔断言映射自检（WARN）。

    返回 findings：[{"level", "rule", "scenario", "message"}]，rule ∈
    DIM_VOCAB / DIM_MISSING / DIM_MAP（validator 与 spec_validator 各自映射键名）。
    """
    sid = str(raw.get("id", "(unknown)"))
    doc = raw.get("doc") or {}
    dims = doc.get("dimensions")

    if dims is None:
        return [{
            "level": "WARN", "rule": "DIM_MISSING", "scenario": sid,
            "message": "缺少 doc.dimensions（测试维度）——维度是覆盖面板按测试设计聚合、"
                       "发现「全是正向、缺少边界/负向」类盲区的基础。请从受控词表标注 1~3 个："
                       + " / ".join(DIMENSIONS),
        }]

    if not isinstance(dims, list) or not dims or any(not isinstance(d, str) for d in dims):
        return [{
            "level": "ERROR", "rule": "DIM_VOCAB", "scenario": sid,
            "message": f"doc.dimensions 必须是非空字符串数组（实际 {dims!r}）——"
                       "受控词表见 format_spec §1.2 doc 层选填字段",
        }]

    findings: list[dict] = []
    unknown = sorted({d for d in dims if d not in DIMENSIONS})
    if unknown:
        import difflib
        hints = []
        for d in unknown:
            close = difflib.get_close_matches(d, list(DIMENSIONS), n=1, cutoff=0.5)
            hints.append(f"{d}（相近: {close[0]}）" if close else d)
        findings.append({
            "level": "ERROR", "rule": "DIM_VOCAB", "scenario": sid,
            "message": f"doc.dimensions 含词表外维度: {', '.join(hints)}——"
                       f"受控词表：{' / '.join(DIMENSIONS)}（format_spec §1.2）",
        })

    evidence = extract_evidence(raw)
    for d in dict.fromkeys(dims):  # 去重保序
        if d not in DIMENSION_EVIDENCE:
            continue  # regression：标注语义，不做映射检查
        accepted, hint = DIMENSION_EVIDENCE[d]
        if evidence.isdisjoint(accepted):
            findings.append({
                "level": "WARN", "rule": "DIM_MAP", "scenario": sid,
                "message": f"声明维度 {d}（{DIMENSIONS[d]}）但 verify 未见对应断言证据——"
                           f"{hint}。测试设计自检：证据确实充分（如纯数据准备场景）可忽略，"
                           "否则建议补对应断言或调整维度标注",
            })
    return findings
