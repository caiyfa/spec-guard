# 2026-08-25 主库验收 sess-db-aux：辅助会话三缺陷（白名单缺域/页签装配/守卫误判）

> 任务号：sess-db-aux 主库验收（合并 8a1728d，修复 2f7fd13 / 0303bff / 9860e05）

## 现象

DB 证据面板与辅助会话功能主库验收（端到端 8 步）时发现三处缺陷：

1. **辅助会话无 write_draft 工具**：SQL 助手收到「write_draft 落盘」指令后诚实回复「本会话没有该工具」——产出物区/引用回流链路整体断裂。
2. **purpose 页签刷新/SPA 跳回后整体消失**：从 DB 面板点「交给 SQL 助手」跳回 /agent 后，右侧 purpose 页签（sql_aux/deps/history）不渲染、页签未激活、sessionStorage 中转消息滞留未消费。
3. **只读守卫误判注释头 SQL**：LLM 落盘的 SQL 带 `-- 注释头`，`_ALLOWED_RE` 不匹配前导注释 → 误判「非查询语句」400。

## 证据链

- 缺陷 1：`agent/purposes/sql_assistant.md` `domains: [run, spec, scenario]` 缺 `draft`；`mcp_server/tools/draft_writer.py` write 声明 `domain="draft"`；`domain_tools()` 只纳入命中域。辅助会话实测可用工具清单无 draft（会话 20260825_213412_efa092d9）。
- 缺陷 2：`AgentChat.tsx` 恢复 effect `messages.length > 0 提前 return`（SPA 内导航不触发 restoreSession）+ `SidePanel.tsx` 回落 guard 在 purposes 未就绪时把 activeTab 重置为 todos。Browser 复验实测：跳回后 purposes=[]、8 秒采样页签不在 DOM。
- 缺陷 3：`sg_core/db_access.py` 原 `_ALLOWED_RE.match(sql)` 不剥前导注释；/db-console?sql= 自动执行注释头 SQL 复现 400。

## 根因（哪个环节缺失）

1. **设计遗漏**：设计文档 §C1 写用途 domains 时漏了「产出物落盘依赖的 draft 域」——提示词硬约束（必须 write_draft）与工具白名单自相矛盾。**教训：用途定义的 domains 必须与提示词承诺的工具能力逐条对照**（防御：test_aux_session.test_sql_assistant_purpose_has_draft_domain 回归断言）。
2. **既有缺陷暴露**（T-932 purpose 页签引入即存在）：purposes 只在「新建会话/发送拦截」路径拉取，恢复路径不拉；本分支的「跳回激活」场景使其显性化。修复：_store 缓存 purposes（跨导航）+ restoreSession 补拉 + 激活前竞态防护 + pending 消费挪到 WS onopen。
3. **守卫过严**：`_ALLOWED_RE` 从头匹配未考虑 SQL 注释头。修复：剥前导注释（--/# 行、/* */ 块）后判定动词；危险子句/多语句检查保守对全文（不误放）。

## 修复（含提交号）

- `2f7fd13`：sql_assistant 补 draft 域 + 回归断言（test_aux_session）
- `9860e05`：purposes 装配修复（sessionStore.ts +purposes 缓存、AgentChat restoreSession 补拉 + 挂载 effect 竞态防护、SqlAuxPanel pending 改 WS onopen 消费）
- `0303bff`：守卫剥前导注释 + 3 条守卫用例（test_db_access）

复验：复验 B（落盘+引用回流）✅、复验 C（SPA 跳回激活+自动发送+pending 消费）✅、回归全绿（后端 71+红线 48 零修改、前端 119+tsc 0）、release_check PASS、已推远端。

## 预防（可执行检查清单）

- [ ] 新增/修改 purpose 定义时：提示词里承诺的每个工具能力，用 `resolve_tools([], ['tester'], purpose_domains=...)` 跑一次确认在列（本条进 test_aux_session 同款断言模式）
- [ ] 页面「跳回激活页签」类功能：必须覆盖 SPA 跳回路径（_store 恢复路径）的验收，不能只验整页刷新
- [ ] 守卫类判定写正则时：考虑输入的常见变体（注释头/前导空白/大小写），拒绝文案保留原文（排障可对照）
- [ ] 依赖「挂载 effect + 异步数据」的联动：异步就绪前不得设置会被回落 guard 消费的状态

## 追加（2026-08-26 用户实测发现）：缺陷 4——辅助会话混入新会话选择卡片

- **现象**：SQL 助手与产品工作台/测试工作台并列出现在新会话用途选择卡片（应只在主会话右侧面板作为页签派生）
- **根因**：用途体系缺「仅派生」语义——visible_purposes 只按角色过滤，roles 全角色的 sql_assistant 自然进选择卡片（设计语义层缺口）
- **修复**（7d2cde4）：PurposeDef 加 `spawn_only` 标记——visible_purposes 过滤 + REST/WS 建会话拦截 403 + 回归断言（test_purpose.py）；spawn 派生路径不受影响（15 passed）
- **预防追加**：新增用途时先定位语义——「用户工作台（可选卡）」还是「辅助会话（spawn_only）」，两者互斥；选错语义比缺功能更难被测试发现（功能都正常，只是出现位置错了）
