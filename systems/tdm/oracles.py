"""TDM 专属断言器（oracle）：API 响应 vs DB 真值的校对。

- profile_matches_db    当前模式 basicInfo ↔ tdm_emp_employee
- snapshot_matches_db   切片模式各模块 ↔ tdm_snap_profile JSON 字段
- dhr_fallback_matches  DHR 降级 basicInfo ↔ dhr_employee 最新分区

签名约定：fn(params, rctx, ns, record)，失败抛 AssertionError（消息含证据）。
响应取值：ns[params["of"]]，默认 "resp"（场景中被测响应的统一 save 名）。
"""

# ProfileVO 模块字段 ↔ tdm_snap_profile JSON 字段映射（参考文档）。
# 严格/宽松比对分组以 oracle_snapshot_frozen 函数内的定义为准（避免双处维护漂移）。
MODULE_MAP = {
    "basicInfo": "basic_info",
    "workInternal": "work_internal",
    "workExternal": "work_external",
    "education": "education",
    "attendance": "attendance",
    "otherInfo": "other_info",
    "capability": "cap_data",
    "gridPlacement": "grid_data",
    "personEval": "eval_data",
    "eval360Detail": "eval_360_data",
    "eval360Primary": "eval360_primary",   # SIT 实际列名无第二下划线
    "reserve": "reserve_data",
    "annualPerf": "annual_perf",
    "expTags": "exp_tags",
}


# ── 深度比较工具 ─────────────────────────────────────────

def _norm(v):
    """叶子值归一化：数字字符串与数字语义等价（雪花 ID 等 Long 字段在 API 响应中
    按公司惯例序列化为字符串防止 JS 精度丢失，DB 快照 JSON 中为原始数字）。"""
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s)
        except (ValueError, TypeError):
            pass
        try:
            return float(s)
        except (ValueError, TypeError):
            pass
    return v


def _diff_paths(a, b, path="$", limit=8):
    """返回 a(响应) 与 b(DB) 的差异路径列表"""
    diffs = []
    if len(diffs) >= limit:
        return diffs
    if a is None and b is None:
        return diffs
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            diffs.extend(_diff_paths(a.get(k), b.get(k), f"{path}.{k}", limit - len(diffs)))
            if len(diffs) >= limit:
                break
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: 长度 响应={len(a)} DB={len(b)}")
            return diffs
        for i, (x, y) in enumerate(zip(a, b)):
            diffs.extend(_diff_paths(x, y, f"{path}[{i}]", limit - len(diffs)))
            if len(diffs) >= limit:
                break
        return diffs
    if _norm(a) != _norm(b):
        diffs.append(f"{path}: 响应={a!r} DB={b!r}")
    return diffs


def _resp_data(params, ns):
    target_name = params.get("of", "resp")
    resp = ns.get(target_name)
    if resp is None:
        raise AssertionError(f"断言器找不到响应变量: {target_name}")
    payload = resp.get("json") or {}
    data = payload.get("data")
    if not isinstance(data, (dict, list)):
        raise AssertionError(
            f"响应 data 不是对象（实际 {type(data).__name__}: {str(data)[:100]}），"
            f"status={payload.get('status')}, message={payload.get('message')}"
            f"——通常为权限拒绝或业务错误响应")
    return data


def _queries(rctx):
    return rctx.registry.get_provider("queries")


# ── 断言器 ───────────────────────────────────────────────

def oracle_profile_matches_db(params, rctx, ns, record):
    """当前模式 basicInfo 与 tdm_emp_employee 当前行比对（白名单字段）"""
    data = _resp_data(params, ns)
    basic = data.get("basicInfo") or {}
    emp_no = basic.get("empNo")
    if not emp_no:
        raise AssertionError("响应 basicInfo.empNo 为空，无法与 DB 比对")
    row = _queries(rctx).get_employee(emp_no)
    if not row:
        raise AssertionError(f"tdm_emp_employee 无记录: {emp_no}")

    field_map = {"empNo": "emp_no", "empName": "emp_name",
                 "corpCode": "corp_code", "groupLevel": "group_level"}
    mismatches = []
    for vo_field, db_field in field_map.items():
        actual, expected = basic.get(vo_field), row.get(db_field)
        if actual != expected:
            mismatches.append(f"{vo_field}: 响应={actual!r} DB={expected!r}")
    record.db_traces.append({
        "purpose": "profile_matches_db: basicInfo ↔ tdm_emp_employee",
        "emp_no": emp_no, "compared_fields": list(field_map),
        "mismatches": mismatches,
    })
    if mismatches:
        raise AssertionError("basicInfo 与员工表不一致: " + "；".join(mismatches))


def oracle_snapshot_frozen(params, rctx, ns, record):
    """切片模式状态型字段与 tdm_snap_profile JSON 比对（FR-002 快照冻结验证）。

    严格组：workExternal/education/attendance/otherInfo——fromSnapshot 直接反序列化，
            无运行时覆盖逻辑，必须与快照全等。
    宽松组：basicInfo——companyAge 旧格式转换 / isHighPotential 实时补充 / FR-009/010
            DHR 状态字段覆盖属预期，差异仅记录。
    已知覆盖：workInternal/annualPerf 被 supplementDhrTimeSeriesData 实时查询覆盖，
            不等于快照——报告差异不判负。
    产品预期：eval360Detail 已废弃不展示（360 信息由 eval360Primary 承载，
            能力明细不展示）——正向断言响应为 null，防止未来代码变动意外复活。
    """
    data = _resp_data(params, ns)
    basic = data.get("basicInfo") or {}
    emp_no = basic.get("empNo")
    if not emp_no:
        raise AssertionError("响应 basicInfo.empNo 为空，无法与 DB 比对")

    queries = _queries(rctx)
    activity_id = params.get("activity_id")
    if activity_id is None:
        emp_var = ns.get("emp") or {}
        activity_id = emp_var.get("activity_id")
    if activity_id:
        snapshot = queries.get_snapshot(emp_no, activity_id)
    else:
        snapshot = queries.get_latest_snapshot(emp_no)
    if not snapshot:
        raise AssertionError(f"tdm_snap_profile 无快照: emp_no={emp_no}, activity_id={activity_id}")

    snap_json = queries.parse_snapshot_json(snapshot)
    strict_modules = {"workExternal": "work_external", "education": "education",
                      "attendance": "attendance", "otherInfo": "other_info"}
    known_covered = {"workInternal": "work_internal", "annualPerf": "annual_perf"}
    strict_diffs, covered_diffs, basic_diffs = [], [], []
    for vo_field, snap_field in strict_modules.items():
        actual, expected = data.get(vo_field), snap_json.get(snap_field)
        if actual is None and expected is None:
            continue
        strict_diffs.extend(_diff_paths(actual, expected, f"$.{vo_field}"))
    for vo_field, snap_field in known_covered.items():
        actual, expected = data.get(vo_field), snap_json.get(snap_field)
        if actual is None and expected is None:
            continue
        covered_diffs.extend(_diff_paths(actual, expected, f"$.{vo_field}")[:3])
    # basicInfo 宽松比对（快照 basic_info 为对象）
    snap_basic = snap_json.get("basic_info") or {}
    if isinstance(snap_basic, dict):
        basic_diffs = _diff_paths(basic, snap_basic, "$.basicInfo")
    # 产品预期：eval360Detail 已废弃不展示（360 信息由 eval360Primary 承载），
    # 快照 eval_360_data 有值时响应仍必须为 null——正向断言防止未来代码变动意外复活
    eval360_expect_empty = snap_json.get("eval_360_data") is not None
    eval360_violation = None
    if eval360_expect_empty and data.get("eval360Detail") is not None:
        eval360_violation = (
            f"响应 eval360Detail 非空（{type(data.get('eval360Detail')).__name__}），"
            "违反产品决策（eval360Detail 已废弃，360 信息由 eval360Primary 承载）")

    record.db_traces.append({
        "purpose": "snapshot_frozen: 状态型字段 ↔ tdm_snap_profile JSON",
        "emp_no": emp_no, "snapshot_id": snapshot.get("id"),
        "snapshot_type": snapshot.get("snapshot_type"),
        "activity_id": snapshot.get("activity_id"),
        "strict_mismatches": strict_diffs,
        "known_covered_diffs": covered_diffs,
        "basic_loose_diffs": basic_diffs[:6],
        "eval360Detail_expect_empty": eval360_expect_empty,
        "eval360Detail_violation": eval360_violation,
    })
    if eval360_violation:
        raise AssertionError(eval360_violation)
    if strict_diffs:
        raise AssertionError(
            f"切片响应状态型字段与快照 JSON 不一致（{len(strict_diffs)} 处）: "
            + "；".join(strict_diffs[:5]))


# 切片结果字段的 (activityId, corpCode) 提取——expTags 为分组嵌套结构
def _extract_result_keys(module, items):
    """返回 [(activityId, corpCode), ...]；expTags 展开 data[] 子数组"""
    keys = []
    if not isinstance(items, list):
        return keys
    if module == "expTags":
        for group in items:
            if isinstance(group, dict) and isinstance(group.get("data"), list):
                for item in group["data"]:
                    if isinstance(item, dict):
                        keys.append((item.get("activityId"), item.get("corpCode")))
        return keys
    for item in items:
        if isinstance(item, dict):
            keys.append((item.get("activityId"), item.get("corpCode")))
    return keys


# 盘点结果字段（时点过滤断言范围）；eval360Detail 见 snapshot_frozen known-issue
TIME_FILTERED_MODULES = ["capability", "gridPlacement", "personEval",
                         "reserve", "expTags", "eval360Primary"]


def oracle_result_time_filtered(params, rctx, ns, record):
    """切片结果字段时点过滤验证（FR-020/FR-021 PLF-02 语义）。

    切片与全局模式的 supplementGlobalResults 共用同一套 Collector + COMPLETED 过滤，
    切片额外叠加 inventory_date ≤ 当前活动过滤。断言：
    1. 数据同源：切片每模块记录的 (activityId, corpCode) 集合 ⊆ 全局模式响应
    2. 时点正确：切片所有记录的 activity.inventory_date ≤ 当前活动 inventory_date
    需场景先执行全局模式 call 并 save 为 global_var（默认 resp_global）。
    """
    data = _resp_data(params, ns)
    global_var = params.get("global_var", "resp_global")
    global_body = ns.get(global_var)
    global_data = (global_body.get("json") or {}).get("data") if isinstance(global_body, dict) else None
    if not isinstance(global_data, dict):
        raise AssertionError(
            f"未找到全局模式响应变量 '{global_var}'（场景需先执行不带 activityId 的 call 并 save: {global_var}）")

    emp_var = ns.get("emp") or {}
    activity_id = params.get("activity_id") or emp_var.get("activity_id")
    queries = _queries(rctx)
    current_inv_date = queries.get_activity_inventory_date(activity_id) if activity_id else None

    problems, module_stats = [], {}
    all_act_ids = set()
    for module in TIME_FILTERED_MODULES:
        slice_keys = _extract_result_keys(module, data.get(module))
        global_keys = set(_extract_result_keys(module, global_data.get(module)))
        for act_id, _ in slice_keys:
            if act_id is not None:
                all_act_ids.add(act_id)
        not_in_global = [k for k in slice_keys if k not in global_keys]
        if not_in_global:
            problems.append(
                f"{module}: {len(not_in_global)} 条切片记录不在全局模式结果中"
                f"（示例: {not_in_global[:2]}）——数据不同源或过滤逻辑不一致")
        module_stats[module] = {"slice": len(slice_keys), "global": len(global_keys),
                                "not_in_global": len(not_in_global)}

    # 时点过滤：切片所有活动 inventory_date ≤ 当前活动 inventory_date
    date_violations = []
    if current_inv_date is not None and all_act_ids:
        dates = queries.get_activity_inventory_dates(all_act_ids)
        for act_id in all_act_ids:
            item_date = dates.get(act_id)
            if item_date is not None and item_date > current_inv_date:
                date_violations.append(
                    f"活动 {act_id} inventory_date={item_date} > 当前活动 {activity_id} 的 {current_inv_date}")
        if date_violations:
            problems.append(f"时点过滤失效（{len(date_violations)} 条）: " + "；".join(date_violations[:3]))

    record.db_traces.append({
        "purpose": "result_time_filtered: 切片结果 ⊆ 全局 + inventory_date 时点过滤",
        "activity_id": activity_id, "current_inventory_date": str(current_inv_date),
        "module_stats": module_stats, "date_violations": date_violations,
        "problems": problems,
    })
    if problems:
        raise AssertionError(f"切片结果字段时点/同源校验失败: {'；'.join(problems[:4])}")


def oracle_dhr_fallback_matches(params, rctx, ns, record):
    """DHR 降级路径 basicInfo 与 dhr_employee 最新分区比对（核心字段）"""
    data = _resp_data(params, ns)
    basic = data.get("basicInfo") or {}
    emp_no = basic.get("empNo")
    if not emp_no:
        raise AssertionError("响应 basicInfo.empNo 为空，无法与 DHR 比对")
    row = _queries(rctx).get_dhr_employee(emp_no)
    if not row:
        raise AssertionError(f"dhr_employee 最新分区无记录: {emp_no}")

    mismatches = []
    for vo_field, db_field in {"empNo": "emp_no", "empName": "emp_name"}.items():
        actual, expected = basic.get(vo_field), row.get(db_field)
        if actual != expected:
            mismatches.append(f"{vo_field}: 响应={actual!r} DHR={expected!r}")
    record.db_traces.append({
        "purpose": "dhr_fallback_matches: basicInfo ↔ dhr_employee(最新分区)",
        "emp_no": emp_no, "mismatches": mismatches,
    })
    if mismatches:
        raise AssertionError("DHR 降级 basicInfo 与 DHR 源表不一致: " + "；".join(mismatches))


def oracle_trend_sorted_desc(params, rctx, ns, record):
    """trend 接口响应数组按 inventoryDate 降序（FR：全量返回不分页，降序）"""
    data = _resp_data(params, ns)
    if not isinstance(data, list):
        raise AssertionError(f"trend 响应 data 不是数组: {type(data).__name__}")
    dates = [item.get("inventoryDate") for item in data if isinstance(item, dict)]
    non_null = [d for d in dates if d]
    violations = []
    for i in range(len(non_null) - 1):
        if str(non_null[i]) < str(non_null[i + 1]):
            violations.append(f"[{i}]={non_null[i]} < [{i+1}]={non_null[i+1]}")
    record.db_traces.append({
        "purpose": "trend_sorted_desc: inventoryDate 降序校验",
        "items": len(data), "dates": non_null[:10], "violations": violations,
    })
    if violations:
        raise AssertionError(f"trend 未按 inventoryDate 降序: {'；'.join(violations)}")


# FR-006：盘点结果类字段（7 个）需注入 inv* 上下文；annual_perf 明确不注入
INV_INJECT_MODULES = ["capability", "gridPlacement", "personEval",
                      "eval360Primary", "reserve"]


def oracle_inv_context_injected(params, rctx, ns, record):
    """盘点结果类记录含 invActivityId/invCorpCode（FR-006），annualPerf 不注入。

    模块为空数组/null 时跳过该模块（无法验证注入，属数据缺失而非注入缺失）。
    """
    data = _resp_data(params, ns)
    problems, checked, skipped = [], [], []
    for module in INV_INJECT_MODULES:
        records = data.get(module)
        if not records:
            skipped.append(module)
            continue
        if not isinstance(records, list):
            records = [records]
        for i, item in enumerate(records):
            if not isinstance(item, dict):
                continue
            checked.append(f"{module}[{i}]")
            if item.get("invActivityId") is None:
                problems.append(f"{module}[{i}].invActivityId 缺失")
            if item.get("invCorpCode") is None:
                problems.append(f"{module}[{i}].invCorpCode 缺失")
    # annualPerf 反向校验：不应包含 inv* 字段
    annual = data.get("annualPerf")
    if isinstance(annual, list):
        for i, item in enumerate(annual):
            if isinstance(item, dict) and ("invActivityId" in item or "invCorpCode" in item):
                problems.append(f"annualPerf[{i}] 不应注入 inv* 上下文")
    record.db_traces.append({
        "purpose": "inv_context_injected: FR-006 上下文注入校验",
        "checked": checked, "skipped_empty_modules": skipped, "problems": problems,
    })
    if not checked and not skipped:
        raise AssertionError("响应中无任何盘点结果数据，无法验证 inv* 注入")
    if problems:
        raise AssertionError(f"inv* 上下文注入校验失败: {'；'.join(problems[:5])}")


# FR-013：盘点结果类 7 字段（corpCode 过滤范围）
RESULT_FIELDS = ["capability", "gridPlacement", "personEval", "eval360Detail",
                 "reserve", "expTags", "eval360Primary"]


def _load_scope(params, ns):
    """从场景变量取权限预言（fetch_permission 步骤的返回值）"""
    scope_name = params.get("scope", "scope")
    scope = ns.get(scope_name)
    if scope is None:
        raise AssertionError(
            f"未找到权限预言变量 '{scope_name}'（需先执行 fetch_permission 步骤并 save: {scope_name}）")
    return scope


def oracle_permission_filtered(params, rctx, ns, record):
    """盘点结果 corpCode 过滤校验（FR-013/014/015）。

    - scope.has_any=False（无任何权限）→ 7 个盘点结果字段必须全空（fail-secure）
    - 否则每条结果记录：corpCode 为 null（非盘点数据，保留）或 ∈ scope.corp_codes（corp_all 时全通过）
    """
    scope = _load_scope(params, ns)
    data = _resp_data(params, ns)
    problems, checked, retained_null = [], [], 0

    if not scope["has_any"]:
        for f in RESULT_FIELDS:
            val = data.get(f)
            if val:
                problems.append(f"{f} 非空（无任何权限时应 fail-secure 清空）")
        record.oracle_traces.append({
            "purpose": "permission_filtered: 无权限 fail-secure 校验",
            "scope": scope, "problems": problems,
        })
        if problems:
            raise AssertionError(f"无权限时盘点结果未清空: {'；'.join(problems)}")
        return

    corp_all, corp_codes = scope["corp_all"], set(scope["corp_codes"])
    for f in RESULT_FIELDS:
        items = data.get(f)
        if not items:
            continue
        if not isinstance(items, list):
            items = [items]
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            cc = item.get("corpCode")
            if cc is None:
                retained_null += 1
                continue
            checked.append(f"{f}[{i}].corpCode={cc}")
            if not corp_all and cc not in corp_codes:
                problems.append(
                    f"{f}[{i}].corpCode={cc} 不在权限范围 "
                    f"{'ALL' if corp_all else sorted(corp_codes)}")
    record.oracle_traces.append({
        "purpose": "permission_filtered: 盘点结果 corpCode 过滤校验",
        "scope": scope, "checked": checked,
        "retained_corpcode_null": retained_null, "problems": problems,
    })
    if problems:
        raise AssertionError(
            f"盘点结果存在越权记录（{len(problems)} 条）: {'；'.join(problems[:5])}")


def oracle_vm_filtered(params, rctx, ns, record):
    """verticalManager 维度过滤校验（FR-016/017）。

    人员 use_vertical_manager=Y 且用户 vm 权限不覆盖其 vertical_manager 值时：
    - 7 个盘点结果字段必须全空（fail-secure）
    - basicInfo 等非盘点字段保留
    人员未启用纵向校验（无记录或 use_vertical_manager!=Y）→ 记录 trace 直接通过。
    """
    scope = _load_scope(params, ns)
    data = _resp_data(params, ns)
    basic = data.get("basicInfo") or {}
    emp_no = basic.get("empNo")
    if not emp_no:
        raise AssertionError("响应 basicInfo.empNo 为空，无法校验 vm 维度")

    vm_rec = _queries(rctx).get_vertical_manager_record(emp_no)
    if not vm_rec:
        record.oracle_traces.append({
            "purpose": "vm_filtered",
            "note": f"{emp_no} 无 use_vertical_manager=Y 记录，不触发纵向权限校验",
        })
        return

    vm_value = vm_rec.get("vertical_manager")
    covered = scope["vm_all"] or (vm_value in set(scope["vm_codes"]))
    problems = []
    if not covered:
        for f in RESULT_FIELDS:
            if data.get(f):
                problems.append(f"{f} 非空（vm={vm_value} 不在用户 vm 权限范围时应清空）")
        if not basic:
            problems.append("basicInfo 应保留（非盘点数据）但为空")
    record.oracle_traces.append({
        "purpose": "vm_filtered: verticalManager 维度校验",
        "emp_no": emp_no, "vertical_manager": vm_value,
        "user_vm_scope": {"vm_all": scope["vm_all"], "vm_codes": scope["vm_codes"]},
        "covered": covered, "problems": problems,
    })
    if problems:
        raise AssertionError(
            f"vm 权限不覆盖（人员 vm={vm_value}）时盘点结果未清空: {'；'.join(problems[:5])}")


def register_oracles(registry):
    registry.oracle("profile_matches_db", oracle_profile_matches_db)
    registry.oracle("snapshot_matches_db", oracle_snapshot_frozen)  # 兼容旧名
    registry.oracle("snapshot_frozen", oracle_snapshot_frozen)
    registry.oracle("result_time_filtered", oracle_result_time_filtered)
    registry.oracle("dhr_fallback_matches", oracle_dhr_fallback_matches)
    registry.oracle("trend_sorted_desc", oracle_trend_sorted_desc)
    registry.oracle("inv_context_injected", oracle_inv_context_injected)
    registry.oracle("permission_filtered", oracle_permission_filtered)
    registry.oracle("vm_filtered", oracle_vm_filtered)
