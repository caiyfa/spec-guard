"""TDM 账号权限探针（T-1039）——试跑前「按权限解析账号」的适配包钩子。

职责单一：给定候选工号 × 资源码矩阵，实时查询 hr-center data-info 的三维
权限（corp/level/vm），返回逐项 {has_any, summary, status}。**不做策略**
（选谁、全码匹配规则属于工作台 account_resolution 通用层）；纯读不落盘，
探针仅调 hr-center 查询接口 + SSO 登录（统一密码，凭据走自有回退链）。

供 workbench services.account_resolution 经 importlib 动态发现——适配包
契约：本模块存在 = 系统支持权限探针；不存在则上层诚实报「该系统不支持」。
"""

import requests

from engine.bootstrap import build_token_provider
from engine.token_provider import TokenError
from systems.tdm.hr_center_oracle import HrCenterOracle

_PROBE_TIMEOUT = 10


def _probe_caller_alias(env_config):
    """选探针调用方账号（仅作 data-info 的 Authorization，不影响被查工号）。"""
    accounts = env_config.get("accounts") or {}
    for alias in ("default",):
        cfg = accounts.get(alias)
        if isinstance(cfg, dict) and cfg.get("ad"):
            return alias
    for alias, cfg in accounts.items():
        if isinstance(cfg, dict) and cfg.get("ad"):
            return alias
    return ""


def probe(env_config, emp_nos, resource_codes):
    """工号 × 资源码权限矩阵探针。

    返回 {"results": {emp_no: {code: {"has_any": bool, "summary": str,
    "status": str}}}, "errors": [str], "probe_account": 别名}。
    单项失败诚实记 error 不中断其余探针（网络/登录失败如实透出）。
    """
    caller = _probe_caller_alias(env_config)
    if not caller:
        return {"results": {}, "errors": ["env accounts 无可用用户账号（均缺 ad）"],
                "probe_account": ""}
    try:
        tp = build_token_provider(env_config)
        caller_ad = (env_config["accounts"][caller].get("ad")
                     if isinstance(env_config["accounts"][caller], dict) else caller)
        tp.get_token(caller_ad)  # 提前登录一次：密码缺失/风控在此诚实报错
        oracle = HrCenterOracle(env_config.get("hr_center_base", ""), tp)
    except TokenError as e:
        return {"results": {}, "errors": [f"SSO 登录失败（{caller}）: {e}"],
                "probe_account": caller}
    except Exception as e:  # 配置缺 hr_center_base 等——诚实透出
        return {"results": {}, "errors": [f"探针装配失败: {type(e).__name__}: {e}"],
                "probe_account": caller}

    results, errors = {}, []
    for emp_no in emp_nos:
        row = {}
        for code in resource_codes:
            try:
                scope = oracle.fetch_scope(emp_no, code, account=caller_ad)
                if scope.raw_status == "exception":
                    row[code] = {"has_any": False, "summary": "",
                                 "status": f"exception: {scope.raw_message[:120]}"}
                    errors.append(f"探针异常 {emp_no} × {code}: {scope.raw_message[:160]}")
                else:
                    row[code] = {"has_any": scope.has_any(), "summary": scope.summary(),
                                 "status": scope.raw_status}
            except TokenError as e:
                # token 失效重登可能再次走 _signin——风控/密码问题诚实记入该格，不 500
                row[code] = {"has_any": False, "summary": "", "status": f"TokenError: {str(e)[:100]}"}
                errors.append(f"SSO 登录失败 {emp_no} × {code}: {str(e)[:160]}")
            except requests.RequestException as e:
                row[code] = {"has_any": False, "summary": "",
                             "status": f"exception: {e}"}
                errors.append(f"探针请求失败 {emp_no} × {code}: {e}")
        results[emp_no] = row
    return {"results": results, "errors": errors, "probe_account": caller}
