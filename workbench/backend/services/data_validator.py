"""data_validator — 数据制造产物专属校验器（M08 §4.3 / §9 G2，T-062）。

数据制造 Agent 的产物闸门（三闸②之外的专属闸）：三要素硬拒——
  ① 实例完整性：provides 必含 activity；session 必挂 activity；members 引用
     emp-pool 时角色必须存在于 systems/{system}/config/emp-pool.yaml
  ② 调度合法性：isolation ∈ {shared, exclusive}；cleanup 必须为 teardown 或显式回收
  ③ 版本期望可仲裁：depends_on 的 version 期望必须可解析（versioning.parse_version）；
     兼容域（^0 等）仲裁由引擎 dependency_graph 在调度期执行

纯函数（零副作用）；无 data_contract 块 = 普通场景 → WARN 不阻断。
只读引用适配包资产（emp-pool.yaml），引擎零改动（铁律 5）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SG_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(SG_ROOT) not in sys.path:
    sys.path.insert(0, str(SG_ROOT))

VALID_ISOLATION = ("shared", "exclusive")
VALID_CLEANUP = ("teardown", "explicit")


def _find_pool() -> dict:
    """读取适配包 emp-pool.yaml（只读；读不到返回空结构——校验降级为跳过池检查）。"""
    from specstd.workspace import resolve_system
    system = resolve_system()
    pool_file = SG_ROOT / "systems" / system / "config" / "emp-pool.yaml"
    try:
        import yaml
        raw = yaml.safe_load(pool_file.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def validate_data_contract(raw: dict, pool: dict | None = None) -> dict:
    """数据契约校验（纯函数）。

    Args:
        raw: 场景 YAML 解析结果（含 data_contract 块）
        pool: emp-pool 结构（缺省从适配包读取；测试可注入）

    Returns:
        {verdict: PASS|FAIL|WARN, findings: [{level, rule, message}]}
    """
    findings = []
    contract = raw.get("data_contract")
    if not contract:
        return {"verdict": "PASS", "findings": [{
            "level": "WARN", "rule": "DATA_CONTRACT",
            "message": "非数据制造场景（无 data_contract 块），跳过数据校验"}]}

    provides = contract.get("provides") or {}
    if not isinstance(provides, dict):
        return {"verdict": "FAIL", "findings": [{
            "level": "ERROR", "rule": "DATA_CONTRACT",
            "message": "provides 必须是映射（含 activity 等实例拓扑）"}]}

    # ① 实例完整性
    if "activity" not in provides:
        findings.append({
            "level": "ERROR", "rule": "INSTANCE_INTEGRITY",
            "message": "provides 缺少 activity——数据制造实例必须产出活动（会话/人员/快照的挂载点）"})
    session = provides.get("session")
    if session is not None and "activity" not in provides:
        findings.append({
            "level": "ERROR", "rule": "INSTANCE_INTEGRITY",
            "message": "session 必须挂 activity（会话是活动下的一层实例）"})

    members = provides.get("members")
    if isinstance(members, dict):
        if members.get("from") == "emp-pool":
            pool_data = pool if pool is not None else _find_pool()
            roles = (pool_data.get("roles") or {}) if isinstance(pool_data, dict) else {}
            role = members.get("role", "")
            if role and role not in roles:
                findings.append({
                    "level": "ERROR", "rule": "POOL_EXISTS",
                    "message": f"members 引用 emp-pool 角色 '{role}' 不存在"
                               f"（已定义: {sorted(roles)}）——请在 systems/{_system_name()}/config/emp-pool.yaml 确认"})
        elif members.get("from") not in (None, "", "emp-pool"):
            findings.append({
                "level": "ERROR", "rule": "POOL_EXISTS",
                "message": f"members.from 非法: {members.get('from')}（仅支持 emp-pool）"})

    # ② 调度合法性
    isolation = contract.get("isolation")
    if isolation not in VALID_ISOLATION:
        findings.append({
            "level": "ERROR", "rule": "ISOLATION",
            "message": f"isolation 非法: {isolation!r}（允许: {VALID_ISOLATION}）"})
    cleanup = contract.get("cleanup")
    if cleanup not in VALID_CLEANUP:
        findings.append({
            "level": "ERROR", "rule": "CLEANUP",
            "message": f"cleanup 非法: {cleanup!r}（允许: {VALID_CLEANUP}，独占实例必须 teardown 回收）"})

    # ③ 版本期望可仲裁（引擎 match_expectation 口径：^X caret 或 X.Y 精确）
    #    只校验可解析性——兼容域仲裁由引擎 dependency_graph 在调度期执行
    for dep in raw.get("depends_on") or []:
        if not isinstance(dep, dict):
            continue
        expect = str(dep.get("version") or "").strip()
        if not expect:
            continue  # 未声明版本期望 → T7 WARN（引擎语义），不阻断
        try:
            from engine.versioning import parse_version, VersionError
            if expect.startswith("^"):
                parse_version(expect[1:])   # caret 兼容域：^0 / ^1 均合法
            else:
                parse_version(expect)       # 精确锁定：0.1 / 1.2
        except VersionError as e:
            findings.append({
                "level": "ERROR", "rule": "VERSION_ARBITRATION",
                "message": f"依赖 {dep.get('id', '?')} 版本期望不可仲裁: {e}"})

    errors = [f for f in findings if f["level"] == "ERROR"]
    return {
        "verdict": "FAIL" if errors else "PASS",
        "findings": findings,
    }


def _system_name() -> str:
    from specstd.workspace import resolve_system
    return resolve_system()
