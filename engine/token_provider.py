"""SSO Token 提供者：账密 → access_token（集团 SSO 通用）。

契约提炼自 scripts/sso_token_demo.py：
  POST {sso_domain}/api/v3/signin
  Headers: x-authing-app-id
  Body: {"connection": "PASSWORD", "passwordPayload": {"account": a, "password": p}}
  Response: data.access_token 即业务可用 JWT

设计要点（对齐 docs/自动化测试Token获取方案.md §5.3）：
- 按账号缓存 {account: (token, exp)}，剩余有效期 < 5 分钟时重新 signin
- 失败指数退避 1s/2s/4s，最多 3 次，附 Authing message
- 401 时由 HttpClient 调 invalidate() 失效缓存后重取
"""

import base64
import json
import time

import requests


class TokenError(Exception):
    pass


def parse_jwt(token):
    """解析 JWT payload，失败返回 None"""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part).decode("utf-8"))
    except Exception:
        return None


class TokenProvider:
    REFRESH_MARGIN_SECONDS = 300   # 剩余有效期 < 5min 重新获取
    MAX_RETRIES = 3

    def __init__(self, sso_domain, app_id, password, interval=0.2):
        self.sso_domain = sso_domain.rstrip("/")
        self.app_id = app_id
        self.password = password
        self.interval = interval          # 批量换取时账号间隔（节流）
        self._cache = {}                  # account -> (token, exp)
        self._last_signin_at = 0.0

    def get_token(self, account):
        """获取指定账号的 token（裸 token，不带 Bearer 前缀）"""
        cached = self._cache.get(account)
        if cached:
            token, exp = cached
            if exp and exp - int(time.time()) > self.REFRESH_MARGIN_SECONDS:
                return token
        return self._signin(account)

    def invalidate(self, account):
        self._cache.pop(account, None)

    def _signin(self, account):
        # 节流：两次 signin 间隔 >= interval（参照 fe-switch refreshAllTokens）
        elapsed = time.time() - self._last_signin_at
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)

        url = f"{self.sso_domain}/api/v3/signin"
        body = {"connection": "PASSWORD",
                "passwordPayload": {"account": account, "password": self.password}}
        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            self._last_signin_at = time.time()
            try:
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json",
                             "x-authing-app-id": self.app_id},
                    json=body, timeout=15)
                data = resp.json()
                if resp.status_code == 200 and data.get("statusCode") == 200 \
                        and data.get("data", {}).get("access_token"):
                    token = data["data"]["access_token"]
                    payload = parse_jwt(token) or {}
                    self._cache[account] = (token, payload.get("exp"))
                    return token
                message = str(data.get("message") or "")
                last_err = (f"HTTP {resp.status_code}, statusCode={data.get('statusCode')}, "
                            f"message={data.get('message')}")
                # 触发 Authing 风控（图形验证码/MFA/锁定）时不重试：
                # 重试无法绕过且会加深风控，立即报明文原因
                if "验证码" in message or "MFA" in message.upper() or "锁定" in message:
                    raise TokenError(
                        f"账号 {account} 触发 Authing 安全策略: {message}。"
                        f"处理方式：等待风控冷却后重跑，或先在浏览器手工登录一次该账号解除")
            except requests.RequestException as e:
                last_err = f"请求异常: {e}"
            if attempt < self.MAX_RETRIES:
                time.sleep(2 ** (attempt - 1))   # 1s / 2s / 4s
        raise TokenError(f"账号 {account} 登录失败（{self.MAX_RETRIES} 次）: {last_err}")
