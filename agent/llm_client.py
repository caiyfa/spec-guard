"""agent.llm_client — 企业大模型网关客户端（OpenAI 兼容 + 计量 + 缓存 + 退避重试）。

配置（环境变量）：
    SG_LLM_BASE_URL  — 网关地址（如 https://api.example.com）
    SG_LLM_API_KEY   — API 密钥
    SG_LLM_MODEL     — 模型名称（默认 gpt-4o）

未配置时返回 mock 响应，支持离线测试 runtime。
"""

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx


class LLMClient:
    """OpenAI 兼容的大模型客户端。"""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        self.base_url = base_url or os.environ.get("SG_LLM_BASE_URL", "")
        self.api_key = api_key or os.environ.get("SG_LLM_API_KEY", "")
        self.model = model or os.environ.get("SG_LLM_MODEL", "gpt-4o")
        self._client: Optional[httpx.Client] = httpx.Client(timeout=120) if self.base_url else None
        self._metrics_file: Optional[Path] = None
        self._system_prompt_hash: Optional[str] = None
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_tokens = 0

    @property
    def is_mock(self) -> bool:
        return not self.base_url

    def chat(self, messages: list[dict], tools: list[dict] = None,
             temperature: float = 0.7) -> tuple[dict, dict]:
        """调用 LLM，返回 (message, usage)。

        message: {"role": "assistant", "content": "...", "tool_calls": [...]}
        usage: {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
        """
        # system prompt 缓存检测（无论是否 mock）
        self._check_cache(messages)

        if self.is_mock:
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            self._record_metrics(usage)
            return self._mock_chat(messages, tools), usage

        # 退避重试（最多 4 次：初始 + 3 次重试）
        last_err = None
        for attempt in range(4):
            try:
                data = self._call_api(messages, tools, temperature)
                usage = data.get("usage", {})
                self._record_metrics(usage)
                message = data["choices"][0]["message"]
                return message, usage
            except httpx.HTTPStatusError as e:
                last_err = e
                if e.response.status_code >= 500 and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError) as e:
                last_err = e
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise

        raise RuntimeError(f"LLM 调用失败（已重试 3 次）: {last_err}")

    def _call_api(self, messages: list[dict], tools: list[dict], temperature: float) -> dict:
        """调用 OpenAI 兼容 API。"""
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        resp = self._client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    def _check_cache(self, messages: list[dict]):
        """检测 system prompt 是否变化（缓存命中/未命中）。"""
        system_msg = next((m for m in messages if m.get("role") == "system"), None)
        if system_msg and isinstance(system_msg.get("content"), str):
            h = hashlib.sha256(system_msg["content"].encode("utf-8")).hexdigest()[:12]
            if h == self._system_prompt_hash:
                self._cache_hits += 1
            else:
                self._cache_misses += 1
                self._system_prompt_hash = h

    def _record_metrics(self, usage: dict):
        """记录计量数据到 JSONL。"""
        self._total_tokens += usage.get("total_tokens", 0)
        if self._metrics_file:
            entry = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "model": self.model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
            }
            self._metrics_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._metrics_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _mock_chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Mock 响应（无网关时用于测试 runtime）。"""
        user_msg = next((m for m in messages if m.get("role") == "user"), {})
        content = str(user_msg.get("content", ""))[:200]
        return {
            "role": "assistant",
            "content": f"[MOCK] 未配置 SG_LLM_BASE_URL。收到请求: {content[:80]}...",
        }

    def set_metrics_file(self, path: Path):
        self._metrics_file = path

    def get_stats(self) -> dict:
        """返回计量统计。"""
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_tokens": self._total_tokens,
            "is_mock": self.is_mock,
            "model": self.model,
        }
