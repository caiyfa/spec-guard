"""hr-center 权限预言机：实时推导用户三维权限范围，作为权限断言的预期真相源。

契约（对齐 Java 侧）：
- 接口：POST {hr_center_base}/api/permission/auth/data-info
- 请求：{empNo, resourceCode, domainSource: "hr"}
- 响应：BusinessResult 包装，data 为角色权限列表，每项含
  corpCodeType/corpCodes、groupLevelType/groupLevels、verticalManagerType/verticalManagers
- 合并语义（对齐 DataPermissionService.mergePermissionScope）：
  任一角色某维度 xxxType=ALL → 该维度 ALL；全部 PART → codes 并集去重
- fail-secure：接口异常/无权限（400001 等错误响应）→ 空 scope（has_any()=False）
"""

from dataclasses import dataclass, field


@dataclass
class PermissionScope:
    corp_all: bool = False
    corp_codes: set = field(default_factory=set)
    level_all: bool = False
    levels: set = field(default_factory=set)
    vm_all: bool = False
    vm_codes: set = field(default_factory=set)
    raw_status: str = ""          # data-info 响应的业务码（诊断用）
    raw_message: str = ""

    def has_any(self):
        return (self.corp_all or bool(self.corp_codes)
                or self.level_all or bool(self.levels)
                or self.vm_all or bool(self.vm_codes))

    def allows_corp(self, code):
        return self.corp_all or code in self.corp_codes

    def allows_level(self, level):
        return self.level_all or level in self.levels

    def allows_vm(self, vm):
        return self.vm_all or vm in self.vm_codes

    def summary(self):
        def fmt(all_flag, codes):
            return "ALL" if all_flag else (sorted(codes) if codes else "∅")
        return (f"corpCode={fmt(self.corp_all, self.corp_codes)}, "
                f"groupLevel={fmt(self.level_all, self.levels)}, "
                f"verticalManager={fmt(self.vm_all, self.vm_codes)}")


class HrCenterOracle:
    def __init__(self, hr_center_base, token_provider):
        self.base = hr_center_base.rstrip("/")
        self.token_provider = token_provider

    def fetch_scope(self, emp_no, resource_code="TDM_SNAPSHOT_ARCHIVE",
                    domain_source="hr", account=None):
        """实时查询指定用户在指定资源下的三维权限范围。

        account: 调 data-info 时使用的登录账号别名对应的 token；
                 为 None 时使用 rctx 默认 token（调用方保证）。
        """
        import requests
        token = self.token_provider.get_token(account) if account else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = requests.post(
                f"{self.base}/api/permission/auth/data-info",
                headers=headers, timeout=15,
                json={"empNo": emp_no, "resourceCode": resource_code,
                      "domainSource": domain_source})
            payload = resp.json()
        except Exception as e:
            scope = PermissionScope(raw_status="exception", raw_message=str(e))
            return scope

        status = str(payload.get("status", ""))
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            # 无权限（400001 等）或异常 → fail-secure 空 scope
            return PermissionScope(raw_status=status,
                                   raw_message=str(payload.get("message", "")))

        scope = PermissionScope(raw_status=status)
        for role in data:
            if not isinstance(role, dict):
                continue
            if role.get("corpCodeType") == "ALL":
                scope.corp_all = True
            scope.corp_codes |= set(role.get("corpCodes") or [])
            if role.get("groupLevelType") == "ALL":
                scope.level_all = True
            scope.levels |= set(role.get("groupLevels") or [])
            if role.get("verticalManagerType") == "ALL":
                scope.vm_all = True
            scope.vm_codes |= set(role.get("verticalManagers") or [])
        return scope
