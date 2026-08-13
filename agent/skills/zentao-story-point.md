---
name: zentao-story-point
description: 禅道故事创建与故事点评估（起草 delta 时创建禅道故事 → 冻结 spec FR 拆解 → 故事点 + 置信度）
version: 1.1.0
author: platform-team
depends_tools: [read_spec, list_spec_files, query_registry]
trigger: 起草 Delta 时新建 FR / 冻结 spec 创建禅道故事后 / 手动请求评估
tools: [sf_list_external_refs, sf_read_draft, sf_check_p0_gate]
keywords: [故事点, 评估, 禅道, story point, estimate, 创建故事, 蜗牛]
---

# 禅道故事创建与故事点评估 skill（M06 G7，T-054）

## 阶段一：创建禅道故事草案（delta 起草时）

起草 Delta Spec 的新增 FR 时，同步生成禅道故事草案（不直接写禅道——铁律：Agent 只建议）：

1. 每条 ADDED 的 FR 对应一个禅道故事
2. 使用 `sf_suggest_story_draft` 工具：
   - title = FR 标题（如 "perfConditions 组间连接符"）
   - spec = FR 完整描述（系统 SHALL ... 段全文）+ 场景验证
   - source_refs = [{type: "fr_anchor", ref: "FR-{功能}-{迭代}-{流水号}"}]
3. 工具返回 draft_id（draft 态，不触禅道）
4. **人在禅道页签确认后**，禅道侧创建故事并返回 ZT-STORY-xxx
5. 故事创建后，使用 `sf_register_external_ref` 登记关联：
   `type=zt_story, ref=ZT-STORY-xxx, linked_type=fr_anchor, linked=FR-{功能}-{迭代}-{流水号}`
6. 同时在 delta-spec 的 `**禅道**：[Story #N]` 行填入故事 ID

MODIFIED/REMOVED 的 FR 若涉及新禅道故事也按同样方式处理。

## 过往故事关联（delta 起草时）

对已有禅道故事的需求变更，通过 `sf_list_external_refs` 查现有引用：

1. `sf_list_external_refs(ref_type="zt_story", linked_type="fr_anchor")` 查已有 FR 关联
2. 若某 FR 变更涉及既有禅道故事，用 `sf_register_external_ref` 补充关联
3. 关联关系记录后，后续 `sf_list_external_refs(linked_type="fr_anchor", linked="FR-person-profile-0817-001")`
   即可查到该 FR 关联的全部外部资产

## 阶段二：故事点评估（冻结 spec 后）

### 输入

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
