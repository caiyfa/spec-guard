"""TDM 专属步骤处理器：select_emp / fetch_permission / oss_upload / oss_download。

格式 2.0：以上能力以 tool 信封调用（`- tool: {use: select_emp, with: {...}, save: x}`），
元数据在模块导入时注册到 engine.tool_registry（供 format_spec 与 workbench 消费）。
"""

import os

import requests

from engine.execution_record import StepTrace
from engine.scenario_runner import SkipScenario, render
from engine.tool_registry import register_tool
from systems.tdm.hr_center_oracle import HrCenterOracle

# ══════════════════════════════════════════════════════════
# tool 元数据注册（模块导入时生效；handler 绑定见文件底部 register_steps）
# ══════════════════════════════════════════════════════════

register_tool(
    "select_emp",
    desc="工号池选号（按角色筛选候选工号，执行前 DB 校验；独占模式跳过已租出工号）",
    args={
        "role": "工号角色（必填，如 snapshot_rich / no_snapshot_tdm / dhr_only）",
        "exclusive": "独占租约（bool，写型场景防互踩）",
    },
    outputs=["no", "role", "activity_id", "session_id", "snapshot_type"],
    system="tdm",
)

register_tool(
    "fetch_permission",
    desc="权限预言（抓取账号三维权限范围 corp/level/vm，作为权限断言的预期真相源）",
    args={
        "account": "账号别名（默认 default，须在 env accounts 配置 emp_no）",
        "resource_code": "资源码（可选，默认取 env.resource_code）",
    },
    outputs=["corp_all", "corp_codes", "level_all", "levels", "vm_all", "vm_codes", "has_any"],
    system="tdm",
)

register_tool(
    "oss_upload",
    desc="上传本地文件到 OSS（multipart），返回 ossKey 供后续 API 调用",
    args={
        "file": "本地文件路径（必填，相对项目根目录或绝对路径）",
        "tenant": "租户（默认 COREHR）",
        "public": "是否公开（bool，默认 false=私有）",
    },
    outputs=["ossKey", "fileName", "fileSize"],
    system="tdm",
)

register_tool(
    "oss_download",
    desc="从 OSS 下载文件（预签名 URL），返回本地文件路径",
    args={
        "ossKey": "OSS 文件 key（必填，支持 {{var}} 插值）",
        "output_dir": "下载目录（默认 downloads）",
    },
    outputs=["file_path", "file_size", "ossKey", "fileName"],
    system="tdm",
)

register_tool(
    "resolve_account",
    desc="动态账号解析（K-055：按资源码从权限体系找真实账号，权限表初筛 + data-info 复核，"
         "替代静态 accounts 配置；无候选时 SKIP）",
    args={
        "resource_code": "资源码（可选，默认取 env.resource_code）",
        "corp_code": "要求平台在权限范围内（可选）",
        "role_code": "限定角色 code（可选）",
    },
    outputs=["emp_no", "ad", "emp_name", "role_code"],
    system="tdm",
)

register_tool(
    "precheck_permission",
    desc="资源码权限预检（K-055：场景首步使用；账号无权限时立即 SKIP，替代跑到一半 FAIL）",
    args={
        "account": "账号别名（默认 default）",
        "resource_code": "资源码（可选，默认取 env.resource_code）",
        "corp_code": "要求平台在权限范围内（可选）",
    },
    outputs=["corp_all", "corp_codes", "level_all", "levels", "vm_all", "vm_codes", "has_any"],
    system="tdm",
)


def make_select_emp(pool, queries):
    def step_select_emp(body, rctx, ns, record):
        role = body["role"]
        exclusive = bool(body.get("exclusive"))
        # 独占模式：跳过已被租约的候选工号，防止多个写型场景操作同一人互相踩踏
        exclude = rctx.leases.leased_keys("emp_no") if exclusive else None
        emp = pool.select(role, exclude=exclude)          # 不满足时抛 SkipScenario
        if exclusive:
            holder = f"{record.scenario_id}#{record.instance_no}"
            rctx.leases.acquire("emp_no", emp["no"], holder=holder)
        record.given["emp_pool"] = (
            f"角色 {role} → 选中 {emp['no']}"
            + ("（独占租约）" if exclusive else "")
            + (f"（校验値 {emp['check_value']}）" if emp.get("check_value") is not None else "（免校验）"))

        # 附带该人员快照上下文：优先 RESULT 快照（字段完整，切片查询用）；
        # 无 RESULT 时退最新快照。无快照角色（no_snapshot_tdm/dhr_only）为 None
        snapshot = None
        if queries:
            snapshot = queries.get_latest_snapshot_by_type(emp["no"], "RESULT") \
                or queries.get_latest_snapshot(emp["no"])
        result = {"no": emp["no"], "role": role, "exclusive": exclusive}
        if snapshot:
            result["activity_id"] = snapshot.get("activity_id")
            result["session_id"] = snapshot.get("session_id")
            result["snapshot_type"] = snapshot.get("snapshot_type")
            record.given["emp_pool"] += (
                f"，快照活动 {result['activity_id']}（{result['snapshot_type']}）")

        record.db_traces.append({
            "purpose": f"工号池角色校验: {role}",
            "result": {k: v for k, v in result.items()},
        })
        record.steps.append(StepTrace(
            type="select_emp",
            note=f"工号池角色 {role} → {emp['no']}"
                 + ("（独占租约）" if exclusive else "")))
        return result
    return step_select_emp


def step_fetch_permission(body, rctx, ns, record):
    """抓取账号在指定资源下的三维权限范围（hr-center data-info），作为权限断言的预期真相源。

    用法：{fetch_permission: {account: default, resource_code: TDM_SNAPSHOT_ARCHIVE, save: scope}}
    返回：{corp_all, corp_codes, level_all, levels, vm_all, vm_codes, has_any}
    """
    alias = body.get("account", "default")
    info = rctx.account_info(alias)
    if not info:
        raise SkipScenario(f"账号别名 '{alias}' 未在环境配置 accounts 中定义")
    if not info.get("emp_no"):
        raise SkipScenario(f"账号 '{alias}' 未配置 emp_no（accounts.{alias}.emp_no），无法抓取权限预言")
    resource_code = render(body["resource_code"], ns) if body.get("resource_code") \
        else rctx.shared_ns.get("env", {}).get("resource_code", "TDM_SNAPSHOT_ARCHIVE")

    if getattr(rctx, "_hr_oracle", None) is None:
        rctx._hr_oracle = HrCenterOracle(rctx.env["hr_center_base"], rctx.token_provider)
    scope = rctx._hr_oracle.fetch_scope(info["emp_no"], resource_code, account=info["ad"])

    # 预言机基础设施故障（网络异常/超时）不能伪装成“无权限”：
    # 否则 permission_filtered 会走 fail-secure 分支把健康后端误判 FAIL
    if scope.raw_status == "exception":
        raise SkipScenario(
            f"权限预言机调用异常（hr-center 不可达）: {scope.raw_message[:200]}"
            "——属环境问题而非产品缺陷，场景 SKIP")

    record.given["account"] = f"{alias}（AD: {info['ad']}，工号: {info['emp_no']}）"
    record.oracle_traces.append({
        "purpose": f"权限预言: {alias}/{info['emp_no']} @ {resource_code}",
        "scope": scope.summary(),
        "raw_status": scope.raw_status, "raw_message": scope.raw_message,
    })
    record.steps.append(StepTrace(
        type="fetch_permission",
        note=f"权限预言 {alias}@{resource_code} → {scope.summary()}"))
    return {
        "corp_all": scope.corp_all, "corp_codes": sorted(scope.corp_codes),
        "level_all": scope.level_all, "levels": sorted(scope.levels),
        "vm_all": scope.vm_all, "vm_codes": sorted(scope.vm_codes),
        "has_any": scope.has_any(),
    }


def step_resolve_account(body, rctx, ns, record):
    """动态账号解析（K-055）：按资源码从权限体系找真实账号，替代静态 accounts 配置。

    用法：{resolve_account: {resource_code: VIEW_TELENT_SEARCH, corp_code?: 1002, role_code?: TDM_ADMIN, save: acct}}
    流程：
      ① DB 权限表找候选工号（role_account_result ⨝ role_account ⨝ role_page，确定性）
      ② data-info API 复核（internal token——参数驱动接口无需 Authing，阶段 0 已验证）
      ③ 输出 {emp_no, ad, emp_name, role_code} 注入 ns；无候选 → SKIP（诚实语义）
    适用：EX-4cba827f 类「需要特定权限账号但静态池未配置」的场景。
    """
    resource_code = render(body["resource_code"], ns) if body.get("resource_code") \
        else rctx.shared_ns.get("env", {}).get("resource_code", "TDM_SNAPSHOT_ARCHIVE")
    corp_code = render(body["corp_code"], ns) if body.get("corp_code") else ""
    role_code = render(body["role_code"], ns) if body.get("role_code") else ""

    db = rctx.dbs.get("default") or rctx.db
    if db is None:
        raise SkipScenario("resolve_account 需要 DB（权限表查询），当前环境 DB 不可用")

    # ① 权限表找候选：绑定了该资源码的角色账户对应的工号
    sql = (
        "SELECT DISTINCT parr.emp_no, parr.username, parr.emp_name, pra.role_code "
        "FROM permission_role_account_result parr "
        "INNER JOIN permission_role_account pra ON parr.role_account_id = pra.id "
        "INNER JOIN permission_role_page prp ON pra.role_code = prp.role_code "
        "WHERE prp.resource_code = %s AND parr.deleted = 0 AND pra.deleted = 0 AND prp.deleted = 0"
    )
    params = [resource_code]
    if role_code:
        sql += " AND pra.role_code = %s"
        params.append(role_code)
    sql += " LIMIT 50"
    candidates = db.query(sql, params)
    if not candidates:
        raise SkipScenario(
            f"权限体系中找不到绑定资源码 {resource_code} 的账号"
            f"{'（限定角色 ' + role_code + '）' if role_code else ''}——请检查资源码或权限配置")

    # ② data-info 复核（internal token 优先：无身份服务凭证即可调参数驱动接口）
    if getattr(rctx, "_hr_oracle", None) is None:
        rctx._hr_oracle = HrCenterOracle(rctx.env["hr_center_base"], rctx.token_provider)
    verify_account = (rctx.token_provider.INTERNAL_ACCOUNT
                      if getattr(rctx.token_provider, "_internal_cfg", None) else None)
    rejected = []
    for cand in candidates:
        scope = rctx._hr_oracle.fetch_scope(cand["emp_no"], resource_code,
                                            account=verify_account or cand["username"])
        if scope.raw_status == "exception":
            continue  # 单个候选复核异常不阻断，试下一个
        if not scope.has_any():
            rejected.append(f"{cand['emp_no']}(无权限)")
            continue
        if corp_code and not scope.corp_all and corp_code not in scope.corp_codes:
            rejected.append(f"{cand['emp_no']}(平台 {corp_code} 不在权限范围 {sorted(scope.corp_codes)})")
            continue
        result = {
            "emp_no": cand["emp_no"],
            "ad": cand["username"] or cand["emp_no"],
            "emp_name": cand.get("emp_name", ""),
            "role_code": cand["role_code"],
        }
        record.steps.append(StepTrace(
            type="resolve_account",
            note=f"动态解析 {resource_code} → {result['emp_no']}({result['emp_name']}, {result['role_code']})"))
        return result

    raise SkipScenario(
        f"资源码 {resource_code} 的 {len(candidates)} 个候选账号均未通过复核"
        f"{'（要求平台 ' + corp_code + '）' if corp_code else ''}: {'; '.join(rejected[:3])}")


def step_precheck_permission(body, rctx, ns, record):
    """资源码权限预检（K-055）：账号对资源码无任何权限 → 首步即 SKIP（替代跑到一半 FAIL）。

    用法（场景首步）：{precheck_permission: {account: default, resource_code: TDM_INV_ACTIVITY}}
    corp_code 可选：同时要求指定平台在权限范围内。
    """
    result = step_fetch_permission(body, rctx, ns, record)
    if not result["has_any"]:
        alias = body.get("account", "default")
        info = rctx.account_info(alias) or {}
        raise SkipScenario(
            f"账号 {alias}（{info.get('emp_no', '?')}）对资源码 "
            f"{body.get('resource_code') or rctx.shared_ns.get('env', {}).get('resource_code')} "
            "无任何数据权限——预检不通过，场景 SKIP（诚实语义：账号配置缺口非产品缺陷）")
    corp_code = render(body["corp_code"], ns) if body.get("corp_code") else ""
    if corp_code and not result["corp_all"] and corp_code not in result["corp_codes"]:
        raise SkipScenario(
            f"账号对平台 {corp_code} 无权限（权限范围: {result['corp_codes']}）——预检不通过，场景 SKIP")
    print(f"[SpecGuard] 权限预检通过: {body.get('account', 'default')} @ "
          f"{body.get('resource_code') or rctx.shared_ns.get('env', {}).get('resource_code')}"
          f"（corp_all={result['corp_all']}, corps={result['corp_codes'][:5]}）", flush=True)
    return result


def step_oss_upload(body, rctx, ns, record):
    """上传本地文件到 OSS，返回 ossKey（供后续 API 调用使用）。

    用法：{oss_upload: {file: "path/to/file.xlsx", save: upload, tenant?: COREHR, public?: false}}
    返回：{ossKey, fileName, fileSize}
    """
    file_path = render(body.get("file", ""), ns)
    if not file_path:
        raise SkipScenario("oss_upload 缺少 file 参数（本地文件路径）")
    # 相对路径解析：相对于项目根目录
    if not os.path.isabs(file_path):
        file_path = os.path.join(os.getcwd(), file_path)
    if not os.path.isfile(file_path):
        raise SkipScenario(f"文件不存在: {file_path}")

    tenant = body.get("tenant", "COREHR")
    is_private = not body.get("public", False)
    oss_base = rctx.env.get("oss_base", "")
    if not oss_base:
        raise SkipScenario("环境配置缺少 oss_base（请在 env.sit.yaml 添加 OSS 附件服务地址）")

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    # multipart 上传
    url = f"{oss_base}/api/oss/upload"
    with open(file_path, "rb") as f:
        resp = requests.post(
            url,
            files={"file": (file_name, f, "application/octet-stream")},
            data={
                "tenantId": tenant,
                "noNameKeyFlag": "false",
                "isPrivate": str(is_private).lower(),
            },
            timeout=60,
        )

    if resp.status_code != 200:
        raise SkipScenario(f"OSS 上传失败（HTTP {resp.status_code}）: {resp.text[:200]}")

    resp_json = resp.json()
    if resp_json.get("code") != 200 and resp_json.get("status") != 200:
        raise SkipScenario(f"OSS 上传返回错误: {resp_json.get("message", resp_json.get("msg", str(resp_json)[:200]))}")

    oss_key = resp_json.get("data", {}).get("ossKey", "") or resp_json.get("data", "")
    if isinstance(oss_key, dict):
        oss_key = oss_key.get("ossKey", "")
    if not oss_key:
        raise SkipScenario(f"OSS 上传返回无 ossKey: {str(resp_json)[:200]}")

    record.given["oss_upload"] = f"{file_name}（{file_size} bytes）→ {oss_key}"
    record.steps.append(StepTrace(
        type="oss_upload",
        note=f"上传 {file_name}（{file_size}B）→ {oss_key}",
        duration_ms=0,
    ))
    return {"ossKey": oss_key, "fileName": file_name, "fileSize": file_size}


def step_oss_download(body, rctx, ns, record):
    """从 OSS 下载文件（通过预签名 URL），返回本地文件路径。

    用法：{oss_download: {ossKey: "{{upload.ossKey}}", save: download, output_dir?: "downloads"}}
    返回：{file_path, file_size, ossKey}
    """
    oss_key = render(body.get("ossKey", ""), ns)
    if not oss_key:
        raise SkipScenario("oss_download 缺少 ossKey 参数")

    download_base = rctx.env.get("oss_download_base", rctx.env.get("oss_base", ""))
    if not download_base:
        raise SkipScenario("环境配置缺少 oss_download_base")

    # 获取预签名下载 URL
    url = f"{download_base}/api/oss/file/download-url/batch"
    resp = requests.post(
        url,
        json={"fileKeys": [oss_key], "appendFileName": True},
        timeout=30,
    )
    if resp.status_code != 200:
        raise SkipScenario(f"OSS 获取下载链接失败（HTTP {resp.status_code}）: {resp.text[:200]}")

    resp_json = resp.json()
    data = resp_json.get("data", {})
    if isinstance(data, list) and data:
        download_url = data[0].get("downloadUrl", "") or data[0].get("url", "")
    elif isinstance(data, dict):
        urls = data.get(oss_key, {})
        download_url = urls.get("downloadUrl", "") or urls.get("url", "") if isinstance(urls, dict) else str(urls)
    else:
        download_url = ""
    if not download_url:
        raise SkipScenario(f"OSS 未返回下载链接: {str(resp_json)[:200]}")

    # 下载文件
    output_dir = body.get("output_dir", "downloads")
    os.makedirs(output_dir, exist_ok=True)
    file_name = oss_key.split("/")[-1] if "/" in oss_key else oss_key
    file_path = os.path.join(output_dir, file_name)

    dl_resp = requests.get(download_url, timeout=60, stream=True)
    if dl_resp.status_code != 200:
        raise SkipScenario(f"OSS 下载文件失败（HTTP {dl_resp.status_code}）")

    with open(file_path, "wb") as f:
        for chunk in dl_resp.iter_content(chunk_size=8192):
            f.write(chunk)

    file_size = os.path.getsize(file_path)
    record.given["oss_download"] = f"{oss_key} → {file_path}（{file_size} bytes）"
    record.steps.append(StepTrace(
        type="oss_download",
        note=f"下载 {oss_key} → {file_path}（{file_size}B）",
        duration_ms=0,
    ))
    return {"file_path": file_path, "file_size": file_size, "ossKey": oss_key, "fileName": file_name}


def register_steps(registry, env_config, pool, queries):
    registry.step("select_emp", make_select_emp(pool, queries))
    registry.step("fetch_permission", step_fetch_permission)
    registry.step("oss_upload", step_oss_upload)
    registry.step("oss_download", step_oss_download)
    registry.step("resolve_account", step_resolve_account)
    registry.step("precheck_permission", step_precheck_permission)
