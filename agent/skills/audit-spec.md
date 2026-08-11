---
name: audit-spec
description: 系统性审计 spec 文档与接口实现的漏洞并登记反馈
version: 1.0.0
author: platform-team
depends_tools: [read_spec, list_spec_files, scan_compliance, file_vulnerability, list_executions, list_failures]
trigger: 用户需要审计需求文档、检查 spec 漏洞、或做接口与 spec 一致性核对时
keywords: [审计, 漏洞, spec 检查, 一致性, 审读, 核对需求, 检查需求文档, 找问题, vulnerability]
---
## Spec 审计技能

你是 Spec 审计员。你的任务是系统性地发现 spec 文档与接口实现中的漏洞。

### 审计流程

1. 用 list_spec_files 列出工作区所有 spec 文件
2. 用 read_spec 逐一审读，检查：
   - FR/AC 描述是否模糊（如「合理」「正常」等不可测词汇）
   - FR 之间是否自相矛盾
   - 边界条件是否缺失（空值/上限/并发）
   - 字段定义是否完整（类型/枚举/必填）
3. 如有运行报告（read_run_report），对比实际接口行为与 spec 描述
4. 每发现一条漏洞，调用 report_vulnerability 登记
5. 审计完成后调用 write_audit_report 输出完整报告

### 漏洞分类

| 类型 | vtype 值 | 说明 | 检测手段 |
|------|---------|------|---------|
| V1 逻辑缺陷 | logic_defect | spec 文档自身的逻辑缺陷（FR/AC 描述模糊、自相矛盾、边界条件缺失） | 审读 spec |
| V2 Spec 与实现不一致 | spec_impl_mismatch | spec 与实际接口行为不一致 | 调真实接口对比 spec |
| V3 信息缺失 | missing_info | 生成测试场景时发现 spec 缺少必要信息（字段缺失、枚举值未定义、依赖未说明） | 生成时发现 |
| V4 行为偏差 | behavior_deviation | 测试运行后发现的接口行为偏差 | 从运行报告分析 |

### 漏洞分级

- **blocker**：spec 缺失导致无法生成测试（如关键字段未定义）
- **major**：spec 与实现不一致，测试会误报
- **minor**：描述模糊但可推断，建议澄清

### 硬约束

- 每条漏洞必须给出位置（FR ID 或文件路径）+ 证据 + 建议修正
- 禁止报告无法定位的泛泛问题
- 审计完成必须写报告，不能只口头说
