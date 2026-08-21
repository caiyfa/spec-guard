"""通用 HTTP 客户端：Bearer 认证 + 401 自动重取重试 + 幂等重试 + 可选 X-Api-Version 版本头校验。

account 为 None 时不带 Authorization 头（用于"未登录"类场景）。

K-049：每次请求打印调用上下文（method/path/status/响应体 trace id）——
执行日志（pytest stdout → 工作台日志流）可直接拿到 ifelc-trace_id 排查 BUG。

ENG-T03：request(retry=...) 支持幂等重试（5xx/网络异常，固定退避，每次打 WARN 留痕）；
幂等性由调用方在 call 步骤声明（GET/HEAD/OPTIONS 默认 times=1，其他方法需显式
retry/idempotent），poll 步骤固定不重试（轮询本身就是重试语义）。
"""

import json
import re
import time

import requests

from engine.execution_record import truncate  # T-314：响应摘要与报告 body_excerpt 同源

VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+(?:-SNAPSHOT)?\([0-9a-f]{7,8}\)$')
# TDM 网关统一响应包装里的请求跟踪 ID（ifelc-trace_id / ifelc_trace_id 兼容）
_TRACE_ID_PATTERN = re.compile(r'ifelc[-_]trace[-_]id"\s*:\s*"([^"]+)"')


def _trace_id_of(resp):
    """提取请求跟踪 ID（K-049）：响应体 ifelc-trace_id（网关统一包装）优先，响应头兜底。

    响应体兼容 ifelc-trace_id / ifelc_trace_id / ifelc-trace-id 三种键形态；
    不设 Content-Type 门禁（网关个别接口返回 text/plain 包装的 JSON），
    仅扫前 4KB 控制大响应开销。
    """
    try:
        m = _TRACE_ID_PATTERN.search(resp.text[:4096])
        if m:
            return m.group(1)
    except Exception:
        pass
    for k, v in resp.headers.items():
        if "trace" in k.lower() and v:
            return str(v)
    return ""


def _excerpt(obj) -> str:
    """T-316：日志摘要（与报告 body_excerpt 同源 truncate）——数组方括号转圆括号。"""
    try:
        return json.dumps(truncate(obj), ensure_ascii=False).replace("[", "(").replace("]", ")")
    except Exception:
        return str(obj)[:200]


class ApiError(Exception):
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class HttpClient:
    def __init__(self, base_url, token_provider=None, account=None, check_version=False):
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.account = account
        self.check_version = check_version
        self.session = requests.Session()

    # ── 请求 ─────────────────────────────────────────────
    def request(self, method, path, params=None, json_body=None, files=None,
                data=None, headers=None, cookies=None, raise_on_error=True, timeout=30,
                retry=None):
        """发起请求。返回 requests.Response（调用方自行取 status_code/json）

        headers/cookies：Apifox 风格自定义头与 Cookie（KV dict，已在步骤层完成插值）。
        合并顺序：Authorization 先置，自定义 headers 后合并——允许负向测试显式覆盖认证头。

        retry（ENG-T03）：{"times": N, "backoff": 秒（默认 1.0）, "on_status": [500,502,503,504]}
        - 网络异常（ConnectionError/Timeout）总是可重试（请求未必到达服务端，
          幂等性由调用方在 call 步骤声明担保）；
        - 响应状态命中 on_status 才重试；4xx（除 401 刷新逻辑）永不重试；
        - 401 刷新优先于 retry（不消耗 times）；每次重试打 WARN 日志（诚实语义：
          抖动必须留痕，排障时需要知道发生过重试）。
        """
        _t0 = time.time()
        # T-316：调用前信息打印——账号/method/path/params/请求体/自定义头（不含 Authorization）。
        # 此前请求参数只在报告，执行日志看不到「发了什么」（EX-a4360d1f）。
        # 方括号转圆括号——防 runner._parse_line 把 [XX-XXX] 误判为场景 ID。
        req_parts = [f"调用 {method} {path}"]
        if self.account:
            req_parts.append(f"账号={self.account}")
        if params:
            req_parts.append(f"params={_excerpt(params)}")
        if json_body is not None:
            req_parts.append(f"body={_excerpt(json_body)}")
        if data is not None:
            req_parts.append(f"data={_excerpt(data) if isinstance(data, (str, dict, list)) else '(文件流)'}")
        custom_hdrs = {str(k): str(v) for k, v in (headers or {}).items()
                       if str(k).lower() != "authorization"}
        if custom_hdrs:
            req_parts.append(f"headers={_excerpt(custom_hdrs)}")
        print(f"[SpecGuard] {' | '.join(req_parts)}", flush=True)
        retry_cfg = self._normalize_retry(retry)
        retries_left = retry_cfg["times"] if retry_cfg else 0
        retry_no = 0
        refreshed = False
        while True:
            try:
                resp = self._do(method, path, params, json_body, files, data, timeout,
                                headers=headers, cookies=cookies)
            except (requests.ConnectionError, requests.Timeout) as e:
                if retries_left > 0:
                    retries_left -= 1
                    retry_no += 1
                    print(f"[SpecGuard] WARN 重试第 {retry_no} 次（网络异常 {type(e).__name__}，"
                          f"退避 {retry_cfg['backoff']}s）: {method} {path}", flush=True)
                    time.sleep(retry_cfg["backoff"])
                    continue
                raise
            # 401 自动失效缓存并重取重试一次（仅带账号的客户端；不消耗 retry 次数）
            if resp.status_code == 401 and self.account and self.token_provider and not refreshed:
                self.token_provider.invalidate(self.account)
                refreshed = True
                continue
            if retries_left > 0 and resp.status_code in retry_cfg["on_status"]:
                retries_left -= 1
                retry_no += 1
                print(f"[SpecGuard] WARN 重试第 {retry_no} 次（HTTP {resp.status_code}，"
                      f"退避 {retry_cfg['backoff']}s）: {method} {path}", flush=True)
                time.sleep(retry_cfg["backoff"])
                continue
            break
        if self.check_version:
            self._check_version_header(resp, path)
        # T-314：调用锚点带完整执行现场——状态 + 耗时 + 响应体摘要 + trace。
        # 此前只有「METHOD path → status | trace」，请求/响应体详情只在 run.json，
        # 执行日志与报告对不上（EX-a78498c3）。摘要与报告 body_excerpt 同源（truncate）；
        # 数组方括号转圆括号——防 runner._parse_line 把 [XX-XXX] 误判为场景 ID。
        elapsed = int((time.time() - _t0) * 1000)
        trace = _trace_id_of(resp)
        excerpt = ""
        try:
            body = self._safe_json(resp)
            if body is not None:
                excerpt = json.dumps(truncate(body), ensure_ascii=False)
                excerpt = excerpt.replace("[", "(").replace("]", ")")
        except Exception:
            pass
        print(f"[SpecGuard] {method} {path} → {resp.status_code} | {elapsed}ms"
              + (f" | body={excerpt}" if excerpt else "")
              + (f" | trace={trace}" if trace else ""), flush=True)
        if raise_on_error and resp.status_code >= 400:
            raise ApiError(resp.status_code, self._safe_json(resp))
        return resp

    def get(self, path, params=None, **kw):
        return self.request("GET", path, params=params, **kw)

    def post(self, path, json_body=None, **kw):
        return self.request("POST", path, json_body=json_body, **kw)

    # ── 内部 ─────────────────────────────────────────────
    @staticmethod
    def _normalize_retry(retry):
        """retry 配置归一化（ENG-T03）：None/空 → None（不重试，完全向后兼容）。"""
        if not retry:
            return None
        try:
            times = int(retry.get("times", 1))
            backoff = float(retry.get("backoff", 1.0))
        except (TypeError, ValueError) as e:
            raise ValueError(f"retry 配置非法（times 应为非负整数、backoff 应为秒数）: {retry!r}") from e
        if times < 0 or backoff < 0:
            raise ValueError(f"retry 配置非法（times/backoff 不得为负）: {retry!r}")
        return {
            "times": times,
            "backoff": backoff,
            "on_status": {int(s) for s in retry.get("on_status", (500, 502, 503, 504))},
        }

    def _do(self, method, path, params, json_body, files, data, timeout,
            headers=None, cookies=None):
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        req_headers = {}
        if self.account and self.token_provider:
            req_headers["Authorization"] = f"Bearer {self.token_provider.get_token(self.account)}"
        if headers:
            req_headers.update({str(k): str(v) for k, v in headers.items()})
        if files:
            return self.session.request(method, url, params=params, files=files,
                                        data=data or {}, headers=req_headers,
                                        cookies=cookies, timeout=timeout)
        if json_body is not None and "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/json"
        return self.session.request(method, url, params=params, json=json_body,
                                    data=data, headers=req_headers,
                                    cookies=cookies, timeout=timeout)

    def _check_version_header(self, resp, path):
        if resp.status_code >= 400:
            return
        if "/api/" not in path:
            return
        version = resp.headers.get("X-Api-Version")
        if version is None:
            raise AssertionError(f"X-Api-Version header missing on {resp.request.method} {path}")
        if not VERSION_PATTERN.match(version):
            raise AssertionError(f"X-Api-Version format mismatch: '{version}' on {resp.request.method} {path}")

    @staticmethod
    def _safe_json(resp):
        try:
            return resp.json()
        except Exception:
            return resp.text
