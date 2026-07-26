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
)

register_tool(
    "fetch_permission",
    desc="权限预言（抓取账号三维权限范围 corp/level/vm，作为权限断言的预期真相源）",
    args={
        "account": "账号别名（默认 default，须在 env accounts 配置 emp_no）",
        "resource_code": "资源码（可选，默认取 env.resource_code）",
    },
    outputs=["corp_all", "corp_codes", "level_all", "levels", "vm_all", "vm_codes", "has_any"],
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
)

register_tool(
    "oss_download",
    desc="从 OSS 下载文件（预签名 URL），返回本地文件路径",
    args={
        "ossKey": "OSS 文件 key（必填，支持 {{var}} 插值）",
        "output_dir": "下载目录（默认 downloads）",
    },
    outputs=["file_path", "file_size", "ossKey", "fileName"],
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
