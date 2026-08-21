"""版本化依赖（格式 2.0）：契约版本解析 / 期望匹配 / 契约指纹 / 基线管理 / T6 校验。

版本语义（Maven 风格简化）：
- 版本号 "MAJOR.MINOR"（"1" 等价 "1.0"）；0.x = 活跃 delta 快照期（SNAPSHOT 语义）
- 契约 = produces（资源+状态） + save 输出变量名 + doc.covers（FR 列表）
  + verify 断言逻辑（规范化摘要，ENG-T02/格式 2.8.0 起纳入指纹）
- 期望声明：`^X` 同主版本兼容；`X.Y` 精确锁定；省略 = 接受任意版本（lint 提示补全）

匹配判定：
- MATCH        期望满足
- MINOR_DRIFT  同主版本且实际 minor 高于精确期望（兼容增强，执行 + INFO）
- MAJOR_DRIFT  主版本不符 / 精确期望高于实际（契约漂移，DRIFT 或 strict 下 FAIL）

T6 校验（spec_validator 调用）：契约指纹变更但 version 未 bump → ERROR。
"""

import hashlib
import json
import os

MATCH = "match"
MINOR_DRIFT = "minor_drift"
MAJOR_DRIFT = "major_drift"

BASELINE_NAME = "contracts_baseline.json"


class VersionError(ValueError):
    pass


def parse_version(v):
    """"1.2" → (1, 2)；"1" → (1, 0)。非法格式抛 VersionError。"""
    s = str(v).strip()
    if not s:
        raise VersionError("版本号为空")
    parts = s.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        raise VersionError(f"版本号格式非法: {v!r}（应为 MAJOR.MINOR，如 0.1 / 1.2）")
    if len(parts) > 2:
        raise VersionError(f"版本号格式非法: {v!r}（仅支持 MAJOR.MINOR 两段）")
    return (major, minor)


def is_snapshot(version):
    """0.x = 快照期（活跃 delta，契约可变）"""
    return parse_version(version)[0] == 0


def match_expectation(expected, actual):
    """依赖期望 vs 实际版本的匹配判定（expected/actual 均为版本字符串）。

    expected 为 None/空 → MATCH（任意版本；调用方可另行 lint 提示）。
    """
    if expected is None or str(expected).strip() == "":
        return MATCH
    exp = str(expected).strip()
    amaj, amin = parse_version(actual)
    if exp.startswith("^"):
        emaj, _emin = parse_version(exp[1:])
        return MATCH if amaj == emaj else MAJOR_DRIFT
    emaj, emin = parse_version(exp)
    if (amaj, amin) == (emaj, emin):
        return MATCH
    if amaj == emaj and amin > emin:
        return MINOR_DRIFT
    return MAJOR_DRIFT


# ══════════════════════════════════════════════════════════
# 契约指纹
# ══════════════════════════════════════════════════════════

def _save_names_from_flow(flow):
    """从 flow 步骤提取 save 变量名（原语与 tool 信封同构：save 都在步骤体顶层）"""
    names = []
    for step in (flow or []):
        if isinstance(step, dict):
            for body in step.values():
                if isinstance(body, dict) and body.get("save"):
                    names.append(str(body["save"]))
    return names


def _produces_key(produces):
    return sorted(f"{p.get('resource')}:{p.get('state', '')}" for p in (produces or []))


# json 断言的操作符键（与 _assert_json_ops 支持集对齐 + absent 反向语义）
_JSON_ASSERT_OPS = ("eq", "ne", "contains", "len_eq", "len_gt", "not_null", "absent")


def _verify_key(verify):
    """verify 断言的规范化摘要（ENG-T02：改断言即改指纹，T6 可见）。

    不渲染插值（保留 {{}} 原文——指纹是静态契约，与运行期变量无关）。
    每条约言取类型键 + 规范化内容：
    - json:   path + 出现的操作符键及预期值
    - status: eq 原文
    - oracle: name + params
    - python: script 原文的 sha256-12（长脚本不撑大指纹源）
    """
    out = []
    for v in (verify or []):
        if not isinstance(v, dict) or not v:
            out.append(str(v))
            continue
        kind, body = next(iter(v.items()))
        if kind == "json" and isinstance(body, dict):
            ops = {op: body[op] for op in _JSON_ASSERT_OPS if op in body}
            out.append({"assert": "json", "path": body.get("path"), **ops})
        elif kind == "status" and isinstance(body, dict):
            out.append({"assert": "status", "eq": body.get("eq")})
        elif kind == "oracle" and isinstance(body, dict):
            out.append({"assert": "oracle", "name": body.get("name"),
                        "params": body.get("params", {})})
        elif kind == "python":
            script = body if isinstance(body, str) else body.get("script", "")
            out.append({"assert": "python",
                        "script_sha": hashlib.sha256(str(script).encode("utf-8")).hexdigest()[:12]})
        else:
            out.append({"assert": str(kind), "body": body})
    return out


def _fingerprint(produces, saves, covers, verify=None):
    contract = {
        "produces": _produces_key(produces),
        "saves": sorted(set(saves)),
        "covers": sorted(str(c) for c in (covers or [])),
        "verify": _verify_key(verify),
    }
    raw = json.dumps(contract, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def contract_fingerprint(scenario):
    """Scenario 对象 → 契约指纹"""
    return _fingerprint(scenario.produces, _save_names_from_flow(scenario.flow),
                        scenario.covers, scenario.verify)


def fingerprint_from_raw(raw):
    """raw YAML dict → 契约指纹（spec_validator T6 用，不依赖 Scenario 对象）"""
    doc = raw.get("doc") or {}
    return _fingerprint(raw.get("produces"), _save_names_from_flow(raw.get("flow")),
                        doc.get("covers"), raw.get("verify"))


# ══════════════════════════════════════════════════════════
# 契约基线（T6 比对基准，随 git 提交，跨机器一致）
# ══════════════════════════════════════════════════════════

def baseline_path(sg_root):
    return os.path.join(sg_root, BASELINE_NAME)


def load_baseline(sg_root):
    path = baseline_path(sg_root)
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_baseline(sg_root, baseline):
    path = baseline_path(sg_root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    return path


def build_baseline(scenarios):
    """由 Scenario 列表构建基线 dict：{id: {version, fingerprint}}"""
    return {
        s.id: {"version": str(s.version), "fingerprint": contract_fingerprint(s)}
        for s in scenarios
    }


def check_t6(scenario_id, fingerprint, version, baseline):
    """T6 校验：契约变更必须 bump 版本。

    返回 (level, message)；无违规返回 None。
    level ∈ ERROR（契约变版本未变）/ WARN（版本变契约未变=冗余 bump）/ INFO（新场景未入基线）
    """
    if scenario_id not in baseline:
        return ("INFO", f"{scenario_id}: 未在契约基线中（新场景需更新 contracts_baseline.json）")
    base = baseline[scenario_id]
    if base["fingerprint"] != fingerprint and base["version"] == str(version):
        return ("ERROR", f"{scenario_id}: 契约已变更但 version 未 bump（仍为 {version}），"
                         f"请 bump MAJOR/MINOR 或回退契约变更")
    if base["fingerprint"] == fingerprint and base["version"] != str(version):
        return ("WARN", f"{scenario_id}: version 已 bump（{base['version']} → {version}）"
                        f"但契约（produces/save/covers/verify）未变化——冗余 bump")
    return None
