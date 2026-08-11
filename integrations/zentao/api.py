"""integrations/zentao/api.py — 禅道 REST 薄封装（httpx）。

与 devops skill 的 zentao_client 协议一致（v1/v2 端点、Token header 大小写
约定），供 services/zentao/client.py 进程内调用与 cli.py 命令行复用。

凭据由调用方传入（base_url/token），本层不读取任何配置——
凭据管理归 services/zentao/config.py（settings_store + 环境变量覆盖）。
"""

from __future__ import annotations

from typing import Optional

import httpx

DEFAULT_BASE_URL = "https://zentao.tdm.cn"


class ZenTaoAPIError(Exception):
    """禅道 API 错误（含状态码与端点，供作业表留档）。"""

    def __init__(self, status_code: int, message: str, endpoint: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.endpoint = endpoint


class ZenTaoClient:
    """禅道 REST 客户端（只读 + 写命令同包）。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, token: str = "",
                 timeout: float = 30.0):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_v1 = f"{self.base_url}/api.php/v1"
        self.api_v2 = f"{self.base_url}/api.php/v2"
        self.token = token or ""
        self.timeout = timeout

    def _headers(self, version: str = "v1") -> dict:
        if version == "v2":
            return {"token": self.token, "Content-Type": "application/json"}
        return {"Token": self.token, "Content-Type": "application/json"}

    def _get(self, url: str, params: dict | None = None,
             version: str = "v1") -> dict:
        resp = httpx.get(url, params=params, headers=self._headers(version),
                         timeout=self.timeout)
        if resp.status_code == 401:
            raise ZenTaoAPIError(401, "未授权——请检查 SG_ZENTAO_TOKEN 凭据", url)
        if resp.status_code == 403:
            raise ZenTaoAPIError(403, "权限不足——请检查禅道账号权限", url)
        if resp.status_code == 404:
            raise ZenTaoAPIError(404, "资源不存在——请检查 ID", url)
        if resp.status_code not in (200, 201):
            raise ZenTaoAPIError(resp.status_code, resp.text[:300], url)
        return resp.json()

    def _post(self, url: str, data: dict, version: str = "v1") -> dict:
        resp = httpx.post(url, json=data, headers=self._headers(version),
                          timeout=self.timeout)
        if resp.status_code == 401:
            raise ZenTaoAPIError(401, "未授权——请检查 SG_ZENTAO_TOKEN 凭据", url)
        if resp.status_code not in (200, 201):
            raise ZenTaoAPIError(resp.status_code, resp.text[:300], url)
        return resp.json()

    def _put(self, url: str, data: dict, version: str = "v1") -> dict:
        resp = httpx.put(url, json=data, headers=self._headers(version),
                         timeout=self.timeout)
        if resp.status_code == 401:
            raise ZenTaoAPIError(401, "未授权——请检查 SG_ZENTAO_TOKEN 凭据", url)
        if resp.status_code not in (200, 201):
            raise ZenTaoAPIError(resp.status_code, resp.text[:300], url)
        return resp.json()

    # ── 只读（面试引用/状态回查）──

    def story_get(self, story_id: str) -> dict:
        """GET /api.php/v1/stories/{id} — 需求详情。"""
        return self._get(f"{self.api_v1}/stories/{story_id}")

    def list_stories(self, product_id: int, page: int = 1, limit: int = 100,
                     status: str = "") -> dict:
        """GET /api.php/v1/products/{id}/stories — 需求列表。"""
        params = {"page": page, "limit": limit}
        if status:
            params["status"] = status
        return self._get(f"{self.api_v1}/products/{product_id}/stories",
                         params=params)

    def story_search(self, keyword: str, product_id: int,
                     status: str = "", limit: int = 100) -> list[dict]:
        """需求搜索（列表拉取后按标题/描述/验收过滤，只读）。"""
        page = 1
        found: list[dict] = []
        while page <= 5:
            data = self.list_stories(product_id, page=page, limit=limit,
                                     status=status)
            stories = (data or {}).get("stories") or []
            if not stories:
                break
            for s in stories:
                title = str(s.get("title") or "")
                spec = str(s.get("spec") or "")
                acceptance = str(s.get("acceptance") or "")
                if keyword and keyword in (title + spec + acceptance):
                    found.append(s)
            if len(stories) < limit:
                break
            page += 1
        return found

    def bug_get(self, bug_id: str) -> dict:
        """GET /api.php/v1/bugs/{id} — BUG 详情（状态回查）。"""
        return self._get(f"{self.api_v1}/bugs/{bug_id}")

    # ── 写（S5 出口，凭据校验在调用方）──

    def story_create(self, data: dict) -> dict:
        """POST /api.php/v1/stories — 创建需求。

        data 关键字段：product, title, spec, acceptance, pri, category,
        estimate, assignee 等（禅道 v1 协议）。
        """
        return self._post(f"{self.api_v1}/stories", data)

    def story_update(self, story_id: str, data: dict) -> dict:
        """PUT /api.php/v1/stories/{id} — 更新需求（故事点回写）。"""
        return self._put(f"{self.api_v1}/stories/{story_id}", data)

    def bug_create(self, data: dict) -> dict:
        """POST /api.php/v2/bugs — 创建 BUG（v2 协议，同 devops 实测）。"""
        return self._post(f"{self.api_v2}/bugs", data, version="v2")
