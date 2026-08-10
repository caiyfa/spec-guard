# 任务链 E：Skills 简化合并

> 优先级：**P2（降级，修正版）**
> 并行性：✅ 完全独立，核心功能完成后启动
> 预计工期：2 天（简化方案）
> 文档依赖：[总览](./00-总览与任务链编排.md)
> 修正说明：**E 降级到 P2 且大幅简化**。初版做完整的选择器 + 预算管理（4-5 天），修正为**简化方案**（2 天）：
> 1. 当前仅 3 个 skill，全量注入即可，**按需注入在 skill ≥ 5 时才启用**
> 2. **skills 和 mode 的职责合并**——初版发现两者存在重复（都是给 LLM 的流程指令），修正后 skill 保留「领域知识」，mode 保留「行为约束」

---

## 一、目标

解决 skills 和 mode 的职责重叠问题，并在 skill 数量增多时启用按需注入。

**简化方案**：
1. **E-1**：合并 skills 和 mode 的职责（skill = 领域知识，mode = 行为约束）
2. **E-2**：skill 数量 < 5 时全量注入（现状不变），≥ 5 时才启用按需注入（开关）
3. **E-3**：优化现有 3 个 skill 的内容（去除与 mode 重复的部分）

---

## 二、现状问题（修正版分析）

### skills 和 mode 的职责重叠

- **mode 的 `prompt_fragment`**（generate.md 正文）：给 LLM 的流程指令（"读取基础信息包 → 生成草稿"）
- **skill 的正文**（generate-scenario.md 正文）：也是给 LLM 的流程指令（"提取 FR/AC 锚点 → 生成场景"）

**重复**：生成场景的流程，在 mode 的 prompt_fragment 里写一遍，在 skill 里又写一遍。

### 真正的 token 瓶颈

- skills 只占 system prompt 的 10-20%（3 个 skill，正文总长 3-5K token）
- format_spec + AGENTS.md 占 60-80%（已由任务链 G 解决）
- **skills 的按需注入是过早优化**（skill 数量少，收益小）

---

## 三、子任务 E-1：skills 和 mode 的职责合并

### 设计方案

**职责划分**：
- **mode 的 `prompt_fragment`**：当前模式的**行为约束**（工具白名单、禁止事项、当前模式的特殊要求）
- **skill 的正文**：**可复用的领域知识**（FR 锚点规则、flow 编写规范、oracle 使用说明）

**示例**（generate-scenario.md 优化后）：

```markdown
<!-- agent/skills/generate-scenario.md -->
---
name: generate-scenario
description: 场景生成的领域知识（FR 锚点、flow 规范、covers 关联）
trigger: [生成, 创建, 场景, scenario]
---

## FR 锚点规则

- covers 中的 FR ID 必须在 spec.md 中存在
- FR ID 格式：`FR-{模块}-{编号}`
- 用 read_spec 工具验证 FR 存在性

## flow 编写规范

- 步骤按执行顺序排列
- 每步必须有 tool 或 oracle
- 变量插值用 `{{a.b.c}}` 点号路径

## verify 断言规范

- 断言器必须已注册（用 query_registry 查询）
- DB 断言需只读（SELECT-only）
```

**对比**（generate.md mode 的 prompt_fragment 优化后）：

```markdown
<!-- agent/modes/generate.md -->
---
tools: [read_spec, query_registry, validate, write_draft, next_scenario_id]
---

## 当前模式：场景生成

**行为约束**：
- 只能使用白名单工具（见 tools）
- 生成后必须调用 validate 校验
- 校验通过后写入 drafts/，禁止直接写 scenarios/
- 发现信息不足时主动提问，不编造

**流程参考**：见 generate-scenario skill（领域知识）
```

### 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `agent/skills/generate-scenario.md` | 重构为「领域知识」（去除与 mode 重复的流程指令） |
| 2 | `agent/skills/validate-conformance.md` | 同上 |
| 3 | `agent/skills/debug-failure.md` | 同上 |
| 4 | `agent/modes/generate.md` | 优化为「行为约束」（去除与 skill 重复的流程指令） |
| 5 | `agent/modes/debug.md` | 同上 |
| 6 | `agent/modes/analyze.md` | 同上 |
| 7 | `agent/modes/chat.md` | 同上 |

---

## 四、子任务 E-2：按需注入开关（skill ≥ 5 时启用）

### 设计方案

```python
# agent/runtime.py build_system_prompt 改造

SKILL_COUNT_THRESHOLD = 5  # skill 数量达到此值才启用按需注入

def build_system_prompt(..., mode: str = "", user_message: str = "", ...):
    ...
    # Skills 注入
    all_skills = list_skills()
    if len(all_skills) < SKILL_COUNT_THRESHOLD:
        # skill 少，全量注入（现状不变）
        skills_xml = build_skills_xml()
    else:
        # skill 多，按需注入（启用选择器）
        from agent.skill_selector import select_skills, build_skills_xml_budgeted
        active, index = select_skills(all_skills, user_message, mode)
        skills_xml = build_skills_xml_budgeted(active, index, budget_tokens=2000)

    if skills_xml:
        prompt += f"\n\n## 可用技能\n\n{skills_xml}"
    return prompt
```

**skill 选择器**（skill ≥ 5 时才实现，简化版）：

```python
# agent/skill_selector.py（新建，仅在 skill ≥ 5 时启用）

def select_skills(all_skills, user_message, mode_name, max_active=2):
    """按需选择 skills（零 LLM 调用，关键词匹配）。"""
    # 按 mode 强关联 + trigger 关键词匹配
    # 详见初版设计，此处简化
    ...
```

### 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `agent/runtime.py` | `build_system_prompt` 按 skill 数量选择全量/按需注入 |
| 2 | `agent/skill_selector.py` | **新建**（仅在 skill ≥ 5 时启用，简化版选择器） |

---

## 五、子任务 E-3：现有 3 个 skill 的内容优化

### 优化原则

- 去除与 mode 重复的流程指令
- 保留「领域知识」（FR 锚点规则、flow 规范、oracle 说明）
- 每个 skill 正文控制在 500-1000 token（精简）

### 改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `agent/skills/generate-scenario.md` | 精简为领域知识（FR 锚点 + flow 规范 + covers 关联） |
| 2 | `agent/skills/validate-conformance.md` | 精简为领域知识（校验规则 + 错误处理） |
| 3 | `agent/skills/debug-failure.md` | 精简为领域知识（失败归因方法 + 常见错误模式） |

---

## 六、验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | skills 和 mode 的职责清晰（skill=领域知识，mode=行为约束） | 检查文件内容无重复 |
| 2 | skill 数量 < 5 时全量注入（现状不变） | 检查 system prompt |
| 3 | skill 数量 ≥ 5 时按需注入（启用选择器） | 构造 6 个 skill 测试 |
| 4 | 现有 3 个 skill 优化后，正文精简（无与 mode 重复的流程指令） | 检查文件 |
| 5 | 现有功能（mock 模式、真实 LLM）回归全绿 | `pytest` |

---

## 七、任务链 E 整体验收门禁

- [ ] skills 和 mode 的职责合并完成（无重复）
- [ ] skill 数量 < 5 时全量注入，≥ 5 时按需注入
- [ ] 现有 3 个 skill 优化为领域知识
- [ ] 现有功能回归全绿
- [ ] `pytest test_specstd -v` 全绿

---

_任务链 E 文档结束（修正版，P2 降级 + 简化方案）。_
