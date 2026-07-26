"""通用 HTTP 客户端：Bearer 认证 + 401 自动重取重试 + 可选 X-Api-Version 版本头校验。

account 为 None 时不带 Authorization 头（用于"未登录"类场景）。
"""

import re

import requests

VERSION_PATTERN = re.compile(r'^\d+\.\d+\.\d+(?:-SNAPSHOT)?\([0-9a-f]{7,8}\)$')


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

    def as_user(self, account):
        """返回切换身份的新客户端（共享 session 池无必要，认证头不同）"""
        return HttpClient(self.base_url, self.token_provider, account, self.check_version)

    # ── 请求 ─────────────────────────────────────────────
    def request(self, method, path, params=None, json_body=None, files=None,
                data=None, headers=None, cookies=None, raise_on_error=True, timeout=30):
        """发起请求。返回 requests.Response（调用方自行取 status_code/json）

        headers/cookies：Apifox 风格自定义头与 Cookie（KV dict，已在步骤层完成插值）。
        合并顺序：Authorization 先置，自定义 headers 后合并——允许负向测试显式覆盖认证头。
        """
        resp = self._do(method, path, params, json_body, files, data, timeout,
                        headers=headers, cookies=cookies)
        # 401 自动失效缓存并重取重试一次（仅带账号的客户端）
        if resp.status_code == 401 and self.account and self.token_provider:
            self.token_provider.invalidate(self.account)
            resp = self._do(method, path, params, json_body, files, data, timeout,
                            headers=headers, cookies=cookies)
        if self.check_version:
            self._check_version_header(resp, path)
        if raise_on_error and resp.status_code >= 400:
            raise ApiError(resp.status_code, self._safe_json(resp))
        return resp

    def get(self, path, params=None, **kw):
        return self.request("GET", path, params=params, **kw)

    def post(self, path, json_body=None, **kw):
        return self.request("POST", path, json_body=json_body, **kw)

    # ── 内部 ─────────────────────────────────────────────
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
