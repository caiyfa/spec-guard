# 任务链 C：轻量 Provider 分支

> 优先级：**P1**（用户确认为刚需）
> 并行性：⚠️ 依赖 B-1（异步基座），B-1 完成后启动
> 预计工期：1 周（轻量方案，非完整抽象层）
> 文档依赖：[总览](./00-总览与任务链编排.md)、[任务链 B-1](./02a-任务链B1-异步化改造.md)（异步基座 + StreamEvent 契约）
> 修正说明：**C 大幅收缩**。初版做完整 Provider 抽象层（3 周），修正为**轻量分支方案**（1 周）——只抽象出 provider 特化函数，用简单的 `if provider_type` 分支，而非完整的 Protocol + Registry。完整抽象层推迟到有 3+ 供应商需求时再做。

---

## 一、目标

打破 SpecGuard 对「OpenAI 兼容协议」的硬依赖，支持非 OpenAI 兼容的供应商（如 Anthropic）。

**轻量方案**（不做完整抽象层）：
1. **C-1**：抽象出 provider 特化函数（`_build_body`、`_parse_chunk`），用 `if provider_type` 分支
2. **C-2**：支持 Anthropic Messages API（轻量分支，非完整 Provider 类）
3. **C-3**：mode ↔ model 绑定（DB 表 + 前端下拉，替代初版的"模型路由"）

**不做**（避免过度设计）：
- ❌ 完整 Provider Protocol + Registry（3+ 供应商时再做）
- ❌ 模型路由（ModelRouter 类，伪需求——用户手动选 mode 即可）
- ❌ 静态模型目录（models_catalog.py，DB 配置已够用）

---

## 二、轻量方案设计

### 核心思路

保持 `LLMClient` 单类，但把 `_build_body` 和 `_parse_chunk` 抽象为 provider 特化函数：

```python
# agent/llm_client.py 改造

class LLMClient:
    def __init__(self, ..., provider_type: str = "openai_compat"):
        self.provider_type = provider_type  # 新增：供应商类型
        # ... 原有初始化

    def _build_body(self, messages, tools, stream=False, options=None) -> dict:
        """按 provider_type 分支构建请求体。"""
        if self.provider_type == "anthropic":
            return self._build_anthropic_body(messages, tools, stream, options)
        else:  # openai_compat（默认，含 DeepSeek/通义/Kimi 等）
            return self._build_openai_body(messages, tools, stream, options)

    def _parse_chunk(self, chunk: dict) -> list[StreamEvent]:
        """按 provider_type 分支解析流式响应。"""
        if self.provider_type == "anthropic":
            return self._parse_anthropic_chunk(chunk)
        else:
            return self._parse_openai_chunk(chunk)

    def _build_openai_body(self, messages, tools, stream, options) -> dict:
        """OpenAI 兼容协议的请求体（现状，含 DeepSeek 特化）。"""
        # 现状逻辑（B-1 已实现）
        ...

    def _build_anthropic_body(self, messages, tools, stream, options) -> dict:
        """Anthropic Messages API 的请求体。"""
        # 分离 system 消息（Anthropic 用单独 system 参数）
        system_content = ""
        conv_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_content += m.get("content", "") + "\n"
            else:
                conv_messages.append(self._convert_to_anthropic_message(m))

        body = {
            "model": self.model,
            "system": system_content.strip() or None,
            "messages": conv_messages,
            "max_tokens": self.max_output_tokens or 4096,
            "stream": stream,
        }

        # 思考能力（thinking.budget_tokens）
        if options and options.get("thinking_budget"):
            body["thinking"] = {"type": "enabled", "budget_tokens": options["thinking_budget"]}

        # 工具（Anthropic 格式与 OpenAI 不同）
        if tools:
            body["tools"] = [self._convert_to_anthropic_tool(t) for t in tools]

        return body

    def _convert_to_anthropic_message(self, m: dict) -> dict:
        """OpenAI 消息 → Anthropic 消息格式。"""
        role = m.get("role")
        content = m.get("content")
        if role == "tool":
            return {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id"),
                    "content": content,
                }],
            }
        elif role == "assistant" and m.get("tool_calls"):
            blocks = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    input_args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    input_args = {}
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id"),
                    "name": fn.get("name"),
                    "input": input_args,
                })
            return {"role": "assistant", "content": blocks}
        else:
            return {"role": role, "content": content or ""}

    def _convert_to_anthropic_tool(self, tool: dict) -> dict:
        """OpenAI tool → Anthropic tool 格式。"""
        fn = tool.get("function", {})
        return {
            "name": fn.get("name"),
            "description": fn.get("description"),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        }

    def _parse_anthropic_chunk(self, chunk: dict) -> list[StreamEvent]:
        """解析 Anthropic event-stream 事件。"""
        # Anthropic 用 event: xxx + data: {...} 格式
        # 详见 B-1 的 _parse_chunk，但解析逻辑不同
        ...
```

### `chat_stream` 的 provider_type 分支

```python
async def chat_stream(self, messages, tools=None) -> AsyncIterator[StreamEvent]:
    """按 provider_type 分流式调用。"""
    if self.provider_type == "anthropic":
        async for evt in self._chat_stream_anthropic(messages, tools):
            yield evt
    else:
        async for evt in self._chat_stream_openai(messages, tools):
            yield evt

async def _chat_stream_openai(self, messages, tools) -> AsyncIterator[StreamEvent]:
    """OpenAI 兼容协议的流式（B-1 已实现）。"""
    # B-1 的现有逻辑
    ...

async def _chat_stream_anthropic(self, messages, tools) -> AsyncIterator[StreamEvent]:
    """Anthropic 的流式（/v1/messages + event-stream）。"""
    client = await self._get_aclient()
    body = self._build_anthropic_body(messages, tools, stream=True)
    headers = {
        "x-api-key": self.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    url = f"{self.base_url.rstrip('/')}/v1/messages"

    accum_content = ""
    async with client.stream("POST", url, json=body, headers=headers) as resp:
        if resp.status_code != 200:
            err = await resp.aread()
            yield StreamEvent(type=EventType.ERROR,
                              error=f"HTTP {resp.status_code}: {err.decode()[:500]}")
            return

        current_event = ""
        async for line in resp.aiter_lines():
            if line.startswith("event: "):
                current_event = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                for evt in self._parse_anthropic_event(current_event, data, accum_content):
                    if evt.type == EventType.TEXT_DELTA:
                        accum_content += evt.content
                    yield evt
```

---

## 三、子任务 C-3：mode ↔ model 绑定（替代模型路由）

### 背景

初版的「模型路由」（C-4）是伪需求——用户手动选 mode 就够了，不需要系统自动选模型。修正为简单的「mode ↔ model 绑定」配置。

### 设计方案

#### DB 表扩展

```sql
-- model_configs 表新增 provider_type 字段
ALTER TABLE model_configs ADD COLUMN provider_type TEXT DEFAULT 'openai_compat';
-- provider_type: openai_compat | anthropic

-- 新增 mode ↔ model 绑定表
CREATE TABLE IF NOT EXISTS mode_model_config (
    mode TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

#### model_config.py 扩展

```python
def get_mode_model(mode: str) -> str | None:
    """获取 mode 绑定的 model_id。"""
    ...

def set_mode_model(mode: str, model_id: str):
    """设置 mode ↔ model 绑定。"""
    ...
```

#### runtime 集成

```python
# agent/runtime.py AgentRuntime.__init__

def __init__(self, llm: LLMClient, ..., mode_name: str = ""):
    ...
    # 按 mode 绑定切换模型（如果配置了）
    if mode_name:
        from services.model_config import get_mode_model
        bound_model_id = get_mode_model(mode_name)
        if bound_model_id:
            # 切换 LLMClient 的模型
            self.llm = LLMClient(model_id=bound_model_id)
```

#### 前端 Settings 页面

`workbench/frontend/src/pages/Settings.tsx` 新增：
- LLM 配置区块的「Provider 类型」下拉（openai_compat / anthropic）
- 「模式 ↔ 模型绑定」区块（每个 mode 一个下拉选 model）

### 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `workbench/backend/services/model_config.py` | 表结构演进 + `provider_type` 字段 + mode_model_config 表 + `get_mode_model` / `set_mode_model` |
| 2 | `workbench/backend/routers/settings.py` | API 支持新字段 |
| 3 | `workbench/frontend/src/pages/Settings.tsx` | 新增 Provider 类型下拉 + mode ↔ model 绑定区块 |
| 4 | `agent/runtime.py` | `AgentRuntime.__init__` 按 mode 绑定切换模型 |

---

## 四、改动清单汇总

| # | 文件 | 改动 |
|---|------|------|
| 1 | `agent/llm_client.py` | 新增 `provider_type` 参数；`_build_body` / `_parse_chunk` 抽象为 provider 特化；新增 `_build_anthropic_body` / `_parse_anthropic_chunk` / `_chat_stream_anthropic` |
| 2 | `workbench/backend/services/model_config.py` | 表结构演进 + mode ↔ model 绑定 |
| 3 | `workbench/backend/routers/settings.py` | API 支持 provider_type |
| 4 | `workbench/frontend/src/pages/Settings.tsx` | Provider 类型下拉 + mode 绑定区块 |
| 5 | `agent/runtime.py` | 按 mode 绑定切换模型 |

---

## 五、验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | 现有 OpenAI 兼容配置（无 provider_type）继续工作（默认 openai_compat） | 用现有配置发消息 |
| 2 | 配置 provider_type=anthropic 后，Claude 模型正常流式输出 | 配置 Anthropic API key 验证 |
| 3 | system 消息正确转为 Anthropic 的单独 system 参数 | mock 请求体检查 |
| 4 | 工具调用格式正确转换（OpenAI ↔ Anthropic） | 构造带工具的消息测试 |
| 5 | mode ↔ model 绑定工作（generate 绑定 Claude，debug 绑定 DeepSeek） | 配置绑定后切 mode 验证 |
| 6 | 前端 Settings 可配置 provider_type 和 mode 绑定 | UI 操作 |
| 7 | 现有功能（mock 模式、WS 流式、工具调用）回归全绿 | `pytest` |

---

## 六、风险与缓解

| 风险 | 缓解 |
|------|------|
| 轻量分支方案在供应商增多后需重构为完整抽象层 | 文档明确「3+ 供应商时升级为完整抽象层」；当前 2 个供应商够用 |
| Anthropic 原生支持增加维护成本 | 优先保证 OpenAI 兼容（覆盖国产主流），Anthropic 作为增强 |
| 现有配置迁移出问题 | `provider_type` 默认 openai_compat，老配置零改动可用 |

---

## 七、任务链 C 整体验收门禁

- [ ] OpenAI 兼容配置零改动可用
- [ ] Anthropic 原生支持可用（Claude 流式 + 工具调用）
- [ ] mode ↔ model 绑定工作
- [ ] 前端 Settings 可配置 provider_type 和绑定
- [ ] 现有功能回归全绿
- [ ] `pytest test_engine test_specstd -v` 全绿
- [ ] `python release_check.py` 通过

---

_任务链 C 文档结束（修正版，轻量分支方案）。_
