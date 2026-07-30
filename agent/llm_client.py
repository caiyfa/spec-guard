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
from typing import Callable, Optional

import httpx


class _StreamUnavailable(Exception):
    """流式请求在建连/状态码阶段失败（未产出任何 delta）——安全回退非流式。"""


class _StreamFailedMidway(Exception):
    """流式已产出部分 delta 后中断——回退非流式拿完整结果（前端以最终消息为准）。"""


class LLMClient:
    """OpenAI 兼容的大模型客户端。"""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = "",
                 timeout: float = 120, temperature: float = 0.7, model_id: str = ""):
        # 优先使用 model_id → 显式传入参数 → DB 默认模型 → 旧 llm_config → 环境变量
        db_cfg = self._load_db_config(model_id) if model_id else self._load_db_config()
        self.base_url = base_url or db_cfg.get("base_url") or os.environ.get("SG_LLM_BASE_URL", "")
        self.api_key = api_key or db_cfg.get("api_key") or os.environ.get("SG_LLM_API_KEY", "")
        self.model = model or db_cfg.get("model") or os.environ.get("SG_LLM_MODEL", "gpt-4o")
        self.timeout = float(db_cfg.get("timeout", "120")) if not timeout else timeout
        self.temperature = float(db_cfg.get("temperature", "0.7")) if temperature == 0.7 else temperature
        # 模型能力 & 思考选项
        self.max_context_tokens = int(db_cfg.get("max_context_tokens") or 0)
        self.max_output_tokens = int(db_cfg.get("max_output_tokens") or 0)
        self.thinking_enabled = db_cfg.get("thinking_enabled", "false").lower() == "true"
        self.reasoning_effort = db_cfg.get("reasoning_effort") or ""
        self._client: Optional[httpx.Client] = httpx.Client(timeout=self.timeout) if self.base_url else None
        self._metrics_file: Optional[Path] = None
        self._system_prompt_hash: Optional[str] = None
        self._cache_hits = 0
        self._cache_misses = 0
        self._total_tokens = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._elapsed_time = 0.0

    @staticmethod
    def _load_db_config(model_id: str = "") -> dict[str, str]:
        """尝试从 workbench DB 加载 LLM 配置（失败时静默返回空 dict）。
        
        优先级：model_id 指定模型 → model_configs 默认模型 → llm_config 旧表 → 环境变量
        """
        try:
            import sys
            from pathlib import Path
            backend_dir = Path(__file__).resolve().parent.parent / "workbench" / "backend"
            if str(backend_dir) not in sys.path:
                sys.path.insert(0, str(backend_dir))
            # 优先从 model_configs 表加载
            try:
                from services import model_config
                if model_id:
                    m = model_config.get_model(model_id)
                else:
                    m = model_config.get_default_model()
                if m:
                    return {
                        "base_url": m.get("base_url", ""),
                        "api_key": m.get("api_key", ""),
                        "model": m.get("model", ""),
                        "timeout": m.get("timeout", "120"),
                        "temperature": m.get("temperature", "0.7"),
                        "max_context_tokens": m.get("max_context_tokens", ""),
                        "max_output_tokens": m.get("max_output_tokens", ""),
                        "thinking_enabled": m.get("thinking_enabled", "false"),
                        "reasoning_effort": m.get("reasoning_effort", ""),
                    }
            except Exception:
                pass
            # 回退到旧 llm_config 表
            from services import llm_config
            return llm_config.resolve_config()
        except Exception:
            return {}

    def reload(self):
        """热加载：从 DB 配置重新初始化连接参数（无需重启进程）。"""
        db_cfg = self._load_db_config()
        new_base_url = db_cfg.get("base_url") or os.environ.get("SG_LLM_BASE_URL", "")
        new_api_key = db_cfg.get("api_key") or os.environ.get("SG_LLM_API_KEY", "")
        new_model = db_cfg.get("model") or os.environ.get("SG_LLM_MODEL", "gpt-4o")
        new_timeout = float(db_cfg.get("timeout", "120"))
        new_thinking = db_cfg.get("thinking_enabled", "false").lower() == "true"
        new_reasoning = db_cfg.get("reasoning_effort") or ""

        changed = (
            new_base_url != self.base_url
            or new_api_key != self.api_key
            or new_model != self.model
            or new_timeout != self.timeout
            or new_thinking != self.thinking_enabled
            or new_reasoning != self.reasoning_effort
        )

        if changed:
            # 关闭旧连接
            if self._client:
                self._client.close()
            self.base_url = new_base_url
            self.api_key = new_api_key
            self.model = new_model
            self.timeout = new_timeout
            self.max_context_tokens = int(db_cfg.get("max_context_tokens") or 0)
            self.max_output_tokens = int(db_cfg.get("max_output_tokens") or 0)
            self.thinking_enabled = new_thinking
            self.reasoning_effort = new_reasoning
            self._client = httpx.Client(timeout=self.timeout) if self.base_url else None
        return changed

    @property
    def is_mock(self) -> bool:
        return not self.base_url

    def chat(self, messages: list[dict], tools: list[dict] = None,
             temperature: float = 0.7,
             on_delta: Optional[Callable[[str], None]] = None) -> tuple[dict, dict]:
        """调用 LLM，返回 (message, usage)。

        message: {"role": "assistant", "content": "...", "tool_calls": [...]}
        usage: {"prompt_tokens": N, "completion_tokens": N, "total_tokens": N}
        on_delta: 提供时启用 SSE 流式（K-012），每个 content 增量回调一次；
                  流式失败自动回退非流式（结果以最终 message 为准）。
        """
        # system prompt 缓存检测（无论是否 mock）
        self._check_cache(messages)

        t0 = time.time()

        if self.is_mock:
            usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            self._record_metrics(usage)
            self._elapsed_time += time.time() - t0
            return self._mock_chat(messages, tools), usage

        # 退避重试（最多 4 次：初始 + 3 次重试）
        last_err = None
        for attempt in range(4):
            try:
                if on_delta is not None:
                    try:
                        data = self._call_api_stream(messages, tools, temperature, on_delta)
                    except (_StreamUnavailable, _StreamFailedMidway):
                        # 流式不可用/中断 → 同次尝试内回退非流式（不消耗重试次数）
                        data = self._call_api(messages, tools, temperature)
                else:
                    data = self._call_api(messages, tools, temperature)
                usage = data.get("usage", {})
                self._record_metrics(usage)
                self._elapsed_time += time.time() - t0
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

    def _build_body(self, messages: list[dict], tools: list[dict], temperature: float) -> dict:
        """构造请求体（流式/非流式共用）。"""
        # 关键修复：strip reasoning_content（DeepSeek 返回但不接受回传，导致 400）
        # K-013：strip references（@引用结构化清单，持久化用但不属于 OpenAI 消息格式）
        clean_messages = []
        for m in messages:
            clean_m = {k: v for k, v in m.items() if k not in ("reasoning_content", "references")}
            clean_messages.append(clean_m)

        body = {
            "model": self.model,
            "messages": clean_messages,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        # 输出 token 限制
        if self.max_output_tokens > 0:
            body["max_tokens"] = self.max_output_tokens

        # 思考/推理选项（DeepSeek-R1 / OpenAI o1 等模型）
        if self.thinking_enabled:
            # DeepSeek 风格：thinking.type = "enabled"
            body["thinking"] = {"type": "enabled"}
            # OpenAI 风格：reasoning_effort（如果有值）
            if self.reasoning_effort:
                body["reasoning_effort"] = self.reasoning_effort
        return body

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _call_api(self, messages: list[dict], tools: list[dict], temperature: float) -> dict:
        """调用 OpenAI 兼容 API（支持 thinking/reasoning 高级选项）。"""
        body = self._build_body(messages, tools, temperature)
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        resp = self._client.post(url, json=body, headers=self._headers())
        if resp.status_code != 200:
            # 捕获错误响应体，用于调试
            error_detail = resp.text[:500] if resp.text else ""
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}: {error_detail}",
                request=resp.request,
                response=resp,
            )
        return resp.json()

    def _call_api_stream(self, messages: list[dict], tools: list[dict],
                         temperature: float,
                         on_delta: Callable[[str], None]) -> dict:
        """SSE 流式调用（K-012）：逐 delta 回调 content，tool_calls 按 index 增量累积。

        返回结构与非流式 _call_api 同构：{"choices": [{"message": ...}], "usage": {...}}。
        失败语义：未产出 delta 前失败 → _StreamUnavailable（可回退）；
                  已产出 delta 后中断 → _StreamFailedMidway（回退非流式取完整结果）。
        """
        body = self._build_body(messages, tools, temperature)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"

        content_parts: list[str] = []
        tool_calls_acc: dict[int, dict] = {}
        usage: dict = {}
        produced = False

        try:
            with self._client.stream("POST", url, json=body, headers=self._headers()) as resp:
                if resp.status_code != 200:
                    raise _StreamUnavailable(f"HTTP {resp.status_code}")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        usage = chunk["usage"]
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        piece = delta.get("content")
                        if piece:
                            produced = True
                            content_parts.append(piece)
                            on_delta(piece)
                        # reasoning_content（DeepSeek 思考流）不转发，保持与原有行为一致
                        for tc in delta.get("tool_calls") or []:
                            idx = tc.get("index", 0)
                            acc = tool_calls_acc.setdefault(idx, {
                                "id": "", "type": "function",
                                "function": {"name": "", "arguments": ""},
                            })
                            if tc.get("id"):
                                acc["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                acc["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                acc["function"]["arguments"] += fn["arguments"]
        except _StreamUnavailable:
            raise
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError,
                httpx.RemoteProtocolError, httpx.ConnectTimeout) as e:
            if produced:
                raise _StreamFailedMidway(str(e))
            raise _StreamUnavailable(str(e))

        message: dict = {"role": "assistant", "content": "".join(content_parts)}
        if tool_calls_acc:
            message["tool_calls"] = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
        return {"choices": [{"message": message}], "usage": usage}

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
        self._prompt_tokens += usage.get("prompt_tokens", 0)
        self._completion_tokens += usage.get("completion_tokens", 0)
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
        tps = self._total_tokens / self._elapsed_time if self._elapsed_time > 0 else 0
        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "total_tokens": self._total_tokens,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "elapsed_time": round(self._elapsed_time, 2),
            "tps": round(tps, 1),
            "is_mock": self.is_mock,
            "model": self.model,
        }
