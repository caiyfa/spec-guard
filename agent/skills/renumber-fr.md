---
name: renumber-fr
description: delta 文档 FR 编号重排（撞号修复/旧编号升级为 FR-{功能}-{迭代}-{流水}，含替换点定位、写回、残留自检全动线）
version: 1.0.0
author: platform-team
depends_tools: [list_spec_files, read_spec, search_spec_files, parse_fr_id, write_delta_doc]
trigger: 用户要求 FR 编号重排/替换/升级、delta 与基线撞号修复、旧连续编号 FR-xxx 迁移为新格式
keywords: [编号重排, 撞号, FR替换, 编号升级, renumber, FR迁移, 编号冲突, 重编号]
---
## FR 编号重排技能

### 编号规则（硬约束，违反必被门禁拦）

- 新格式：`FR-{功能}-{迭代}-{流水}`（如 `FR-person-profile-0817-001`）——全局唯一、永久保留
- 功能=模块目录名（`specs/{模块}/{功能}/` 第二级，可含 `-`，同前缀子模块共存无歧义）
- 迭代=delta 代号（`changes/{代号}/` 目录名；**禁止含 `-`**，字母/数字/下划线开头、可含 `.`）
- 流水=恒 3 位数字（001 起按模块内顺序分配）
- **基线既有 FR（FR-001 等）一律不动**——合并回基线后不变更、不重编号（编号即溯源）

### 核心流程

1. **盘点结构**：`list_spec_files(subdir="changes")` 确认目标 delta 的文件清单
   （delta-specs/*.md + 统筹层 spec.md/delta-spec.md/api-delta.yaml/design.md）
2. **定位替换点**：对每个待替换旧编号执行
   `search_spec_files(pattern="FR-009", subdir="changes/{代号}")`——
   返回全部命中文件+行号（标识符边界匹配，FR-009 不会误中 FR-0099）；
   **禁止只读单文件就动手**——同编号可能在统筹层多文件出现且分属不同模块
3. **FIXED 判定**（逐条实测，勿凭印象）：`read_spec(specs/{模块}/{功能}/spec.md, anchor="FR-xxx")`
   查基线 §4——编号已存在 → 保留原编号（FIXED 是对基线的修正）；基线不存在 → 换新编号
4. **生成并验证新编号**：分配后逐条 `parse_fr_id(fr_id="FR-{功能}-{迭代}-{流水}")`——
   ok=false 时按 error/hint 修正（功能未注册/迭代代号非法/形态错误）
5. **写回**：`write_delta_doc(delta_id, filename, content=替换后全文)`——
   自动 .bak 备份 + 写后 conformance 校验（关注返回的 validation.verdict）
6. **残留自检**：对全部旧编号再跑 `search_spec_files`——应只剩白名单命中
   （基线既有编号在统筹层的合法引用，如 performanceLogicMode 的 FR-027）；
   统筹层同号分属不同模块时逐行核对所属模块，**禁止批量替换**
7. **收尾报告**：列出映射表（旧→新）、保留白名单、validation 结果；
   禅道锚点关联（sf_list_external_refs 查旧编号引用）需同步更新为人工确认项

### 注意

- 替换覆盖全形态：标题（### ADDED: FR-xxx）、正文（**FR-xxx**：）、交叉引用（FR-xxx 补充）、
  Changelog 行、api.yaml 变更要点——search_spec_files 的命中清单就是替换清单
- `[delta:代号]` 标记保留不动；MODIFIED 条目保持全量描述
- 工具报错不得绕过式自愈：conformance 返回 REJECT 时按 findings 修正，不改校验器
