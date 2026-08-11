---
name: zentao-story-point
description: 禅道故事点评估（冻结 spec FR 拆解 → 故事点 + 置信度）
trigger: 冻结 spec 创建禅道故事后 / 手动请求评估
tools: [sf_list_external_refs, sf_read_draft, sf_check_p0_gate]
keywords: [故事点, 评估, 禅道, story point, estimate]
---

# 禅道故事点评估 skill（M06 G7，T-054）

## 输入

冻结 delta（delta-spec.md + delta.manifest.yaml）的 FR 操作集拆解
（ADDED / MODIFIED / REMOVED，来自 manifest operations）。

## 处理

1. **按操作拆条目并逐条估点**（经验基线，可调）：
   - ADDED 2 点 / MODIFIED 2 点 / REMOVED 1 点
   - MODIFIED 带决策引用 → 级联影响面 +1
2. **参照历史故事校准**：`sf_list_external_refs` 查同模块 zt_story；
   已确认评估记录（`GET /api/zentao/estimates?status=confirmed`）作为参照
   （如 A-02-Δ=8 / A-01=3 类）。
3. **输出总点数 + 置信度**：拆解条目数、历史参照覆盖率共同决定
   （0.5 基础 + 条目校准 + 历史参照加成，cap 0.95）。

## 输出

`sf_storypoint_estimates(status=suggested)` + 终端汇报
（拆解条目 / 总点数 / 置信度 / 参照清单）。

## 红线（铁律 1：Agent 只建议，人拍板）

- 评估永远是建议：estimate 恒 suggested 出生，**不计入任何闸门/总分**；
- 回写禅道必须产品确认：`POST /api/zentao/stories/{id}/writeback-points`
  （仅 product 角色，MCP 不可达）；
- 评估不触禅道写接口：只读参照 + 本地落建议，禅道侧点数不变直到回写。
