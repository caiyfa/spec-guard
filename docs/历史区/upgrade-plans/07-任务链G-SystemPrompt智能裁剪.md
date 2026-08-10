# 任务链 G：system prompt 智能裁剪

> 优先级：**P0（新增，修正版）**
> 并行性：✅ 完全独立，可与任务链 A/F-1 并行启动
> 预计工期：2-3 天
> 文档依赖：[总览](./00-总览与任务链编排.md)
> 修正说明：**这是修正版新增的 P0 任务链**。初版误判了 token 瓶颈——真正的大头是 format_spec + AGENTS.md（占 system prompt 60-80%），而非 skills（占 10-20%）。本链解决根本问题，比 A-2（compaction）更上游。

---

## 一、目标

解决 system prompt 体积过大的根本问题：当前全量注入 format_spec（冻结语法 + tool 目录）+ AGENTS.md 全量原文，单 system prompt 3-8K token，长对话下迅速撑爆上下文窗口。

**改造方向**：
1. **G-1**：format_spec 按 mode 分章节注入（generate 注入 flow/verify 章节，debug 注入断言章节）
2. **G-2**：AGENTS.md 摘要注入（可配置级别，硬约束保留完整，示例/说明压缩）

**预期收益**：system prompt 体积减少 40-60%，直接降低每轮 LLM 调用的 input token 成本，延缓 compaction 触发。

---

## 二、现状分析

### 当前 system prompt 构成（`runtime.py:build_system_prompt`）

```
1. format_spec（冻结语法 + tool 目录）      ← 约 3000-5000 token（全量）
2. AGENTS.md 全量原文                      ← 约 2000-4000 token（全量）
3. mode prompt_fragment                    ← 约 300-500 token
4. scenario_context（基础信息包）          ← 可变
5. skills XML（全量）                      ← 约 1000-5000 token
```

**总计**：单 system prompt 约 6000-18000 token，长对话（12 轮）下 system prompt 重复发送 12 次，成本高昂。

**关键洞察**：format_spec 和 AGENTS.md 是**全量注入**的，但不同 mode 只需要其中一部分：
- generate mode 需要「flow/verify 编写规范」+「工具目录」
- debug mode 需要「断言规范」+「错误处理」
- analyze mode 只需要「格式概览」

### format_spec 结构（`workbench/backend/services/format_spec.py`）

format_spec 生成的 markdown 分章节（约 8 章），每章有明确标题。可通过章节解析做按需注入。

### AGENTS.md 结构

含硬约束（Never/Ask First/Always）+ 示例 + 工作流编排。**硬约束必须完整保留**，示例/说明可压缩。

---

## 三、子任务 G-1：format_spec 按 mode 分章节注入

### 设计方案

#### 1. format_spec 章节解析

```python
# workbench/backend/services/format_spec.py 新增

from typing import Optional


def generate_format_spec_by_section(section: str = "all") -> str:
    """按章节生成 format_spec（非全量）。

    section 取值：
      - "all"：全量（现状，向后兼容）
      - "flow"：仅 flow 编写规范 + 工具目录
      - "verify"：仅 verify 断言规范
      - "overview"：格式概览（目录 + 关键概念，最简）
    """
    full_md = generate_format_spec_md()  # 现有全量生成
    if section == "all":
        return full_md

    # 按 markdown 章节解析（假设章节以 "## " 开头）
    sections = _parse_sections(full_md)
    return sections.get(section, full_md)


def _parse_sections(md: str) -> dict[str, str]:
    """解析 markdown 为章节目录（按 ## 标题切分）。"""
    sections = {"overview": []}
    current = "overview"
    for line in md.split("\n"):
        if line.startswith("## "):
            current = line[3:].strip().lower()
            # 标准化章节名（如 "## Flow 编写规范" → "flow"）
            for key in ["flow", "verify", "overview", "tool"]:
                if key in current:
                    current = key
                    break
            sections.setdefault(current, [])
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}
```

#### 2. mode → format_spec 章节映射

```python
# agent/runtime.py 新增

MODE_FORMAT_SPEC_SECTION: dict[str, str] = {
    "generate": "flow",      # 生成模式：flow 编写 + 工具目录
    "debug": "verify",       # 调试模式：verify 断言
    "analyze": "overview",   # 分析模式：格式概览
    "chat": "overview",      # 对话模式：概览即可
}


def build_system_prompt(..., mode: str = "", ...):
    # 原：format_spec_text = generate_format_spec_md()（全量）
    # 新：按 mode 选章节
    section = MODE_FORMAT_SPEC_SECTION.get(mode, "all")
    format_spec_text = generate_format_spec_by_section(section)
    ...
```

### 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `workbench/backend/services/format_spec.py` | 新增 `generate_format_spec_by_section` + `_parse_sections` |
| 2 | `agent/runtime.py` | `build_system_prompt` 按 mode 选 format_spec 章节 |

### 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | generate mode 时 format_spec 只含 flow 章节 + 工具目录 | 检查 system prompt 内容 |
| 2 | debug mode 时 format_spec 只含 verify 章节 | 检查 |
| 3 | 未指定 mode 或 mode 不在映射中时回退全量（向后兼容） | 不传 mode 验证 |
| 4 | format_spec 章节解析正确（不丢内容） | 单元测试 `_parse_sections` |
| 5 | system prompt 体积减少（generate mode 下减少 30%+） | 统计 token |

---

## 四、子任务 G-2：AGENTS.md 摘要注入

### 设计方案

#### 1. AGENTS.md 分级摘要

```python
# specstd/workspace.py 新增

def read_agents_md(level: str = "full") -> str:
    """读取 AGENTS.md，支持分级摘要。

    level 取值：
      - "full"：全量原文（现状）
      - "constraints"：仅硬约束（Never / Ask First / Always 章节）
      - "summary"：约束 + 工作流编排概览（无示例/详细说明）
    """
    full = _read_full_agents_md()  # 现有读取逻辑
    if level == "full":
        return full

    # 解析章节，提取硬约束
    return _extract_constraints(full, level)


def _extract_constraints(md: str, level: str) -> str:
    """从 AGENTS.md 提取硬约束章节。"""
    sections = {
        "## Never": [],
        "## Ask First": [],
        "## Always": [],
        "## Code Style": [],  # 硬约束部分
    }
    current = None
    for line in md.split("\n"):
        if line.startswith("## "):
            current = line.strip()
        if current in sections or (current and "Code Style" in current):
            sections.setdefault(current, []).append(line)

    result = ["# 工作区约束（摘要）\n"]
    for section, lines in sections.items():
        if lines:
            result.extend(lines)
            result.append("")
    return "\n".join(result)
```

#### 2. mode → AGENTS.md 级别映射

```python
# agent/runtime.py

MODE_AGENTS_MD_LEVEL: dict[str, str] = {
    "generate": "constraints",  # 生成模式：需要硬约束（covers 铁律等）
    "debug": "constraints",     # 调试模式：需要硬约束
    "analyze": "summary",       # 分析模式：概览即可
    "chat": "summary",          # 对话模式：概览
}


def build_system_prompt(..., mode: str = "", ...):
    # 原：agents_md = read_agents_md()（全量）
    # 新：
    level = MODE_AGENTS_MD_LEVEL.get(mode, "full")
    agents_md = read_agents_md(level)
    ...
```

### 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `specstd/workspace.py` | 新增 `read_agents_md(level)` + `_extract_constraints` |
| 2 | `agent/runtime.py` | `build_system_prompt` 按 mode 选 AGENTS.md 级别 |

### 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | generate mode 时 AGENTS.md 只含 Never/Ask First/Always 硬约束 | 检查 system prompt |
| 2 | chat mode 时 AGENTS.md 为摘要级别 | 检查 |
| 3 | 硬约束章节完整保留（不丢内容） | 对比 full 与 constraints 的约束章节 |
| 4 | system prompt 体积减少（generate mode 下减少 30%+） | 统计 token |

---

## 五、综合收益估算

### 改造前后 system prompt 体积对比

| mode | 改造前（全量） | 改造后（分章节+摘要） | 减少 |
|------|--------------|---------------------|------|
| generate | ~8000 token | ~3500 token | **~56%** |
| debug | ~8000 token | ~3000 token | **~63%** |
| analyze | ~8000 token | ~2000 token | **~75%** |
| chat | ~8000 token | ~1500 token | **~81%** |

**对长对话的影响**：12 轮对话下，仅 system prompt 重复发送就节省 5-10 万 token/会话。

---

## 六、任务链 G 整体验收门禁

- [ ] format_spec 按 mode 分章节注入（generate/debug/analyze 各自章节正确）
- [ ] AGENTS.md 按 mode 分级摘要（硬约束完整保留）
- [ ] 未指定 mode 时回退全量（向后兼容）
- [ ] system prompt 体积减少 40%+（generate mode 下）
- [ ] 现有功能（mock 模式、真实 LLM）回归全绿
- [ ] `pytest test_specstd -v` 全绿（含 format_spec 章节解析测试）

---

## 七、与任务链 A-2（compaction）的关系

**G 是 A-2 的上游**：
- A-2 解决「超窗口后如何压缩」
- G 解决「如何减少超窗口的可能性」（减小 system prompt）

**建议顺序**：G 和 A-2 都在 P0，**可并行做**（G 改 format_spec/workspace.py，A-2 改 compactor.py，文件不重叠）。G 完成后，A-2 的压缩阈值更从容。

---

_任务链 G 文档结束（新增，修正版）。_
