# Agent 路径自检与纠正提示设计（T-1042 三期：图在看、提示不打断）

> 2026-08-30 sess-agent-eval 起草，用户对话拍板认可边界。**状态：已实施**（同日
> 完工，行为钉 6 条 + 一致性钉 + 端点/工具测试 16 例全绿；AGENTS/README 工具计数
> 24→25、ALL_TOOLS 41→42 断言同步）。
> 前置：《docs/SpecGuard-Agent评测体系-现状基线.md》（a1ecc25）§十六轨迹基线 +
> T-1042 二期路径重放（evals/flowpath + 🧭 面板，25d64b7/04b70cd）+
> 知识库《2026-08-26-2037 评估架构体系设计》五层架构（repo 副本：
> docs/远期设计/SpecGuard-Agent评测体系-评估架构设计-20260826.md）。

## 一、边界裁决（本文档的第一决策）

用户问题：agent 执行时能否看到扫描内容、检查体系发现跑偏能否自动打断纠正？
这是不是把编排做成了 Dify 式工作流？

**裁决：图在看（测量与提示），不图在跑（执行与打断）。**

| | Dify 式编排 | 本设计 |
|---|---|---|
| 谁执行图 | 引擎执行，LLM 填节点 | agent 自由行走，无人执行图 |
| 偏离图时 | 流程中止/重路由 | 评测报告一行字（离线）或一句话提示（在线 nudge） |
| 确定性所在 | 执行路径 | 只在测量与判定 |
| 失败语义 | 流程失败 | 产物过不了三闸 |

理由（对话论证的沉淀）：

1. **薄 Harness 宪法**：基线 §一「不在代码里写死工作流」。runtime 路径监视器
   若有打断权 = 藏在 runtime 里的第二个工作流引擎，为两套大脑付钱。
2. **golden flow 是描述性模型**：从真实会话+技能提炼，含软顺序/条件阶段/交互门；
   监视器无法区分「违规」与「用户明确要求跳过」，误报打断比漏报跑偏更贵
   （烧 token=D4 恶化、烧信任）。
3. **确定性护栏已在正确的层**：越权/纯读副作用/external-write/熔断在工具与
   闸门层强制（白名单/三闸/指纹）。全流程只设 2 条硬顺序约束（读需求<写草稿、
   校验<写草稿）——评测都不敢多设的约束，不值得建打断机。
4. **时效性**：技能 30s TTL 热加载、工具合并演进；flow 定义靠 build_flow --check
   门禁追平。评测里定义滞后=报告失真；runtime 里=行为腐蚀。
5. **正确的定性**：Dify 是「图在跑」，这里是「图在看」。SpecGuard 对被测系统
   立论「契约驱动」——本设计把同一思想用到 agent 自身：golden flow=agent 工作方式
   的契约，评测体系=agent 的测试套件，🧭 面板=测试报告。概念自洽，不是范畴错误。

## 二、Goodhart 风险与缓解（必读）

agent 持续可见路径评价后可能「优化监视器而非服务用户」（为消 nudge 调 validate
而非真校验）。缓解：

- nudge 文案框定为「技能流程提醒」+ 明示「用户明确要求的跳过，向用户说明即可，
  无需补做」——把裁量权还给 agent 与用户；
- 每会话至多触发一次（整会话去重，非每类一次）——首次提示后 agent 已知纪律，
  重复唠叨即 Goodhart 温床；
- 产物质量由三闸把守（D3 硬指标）：糊弄 nudge 也过不了闸——评测层兜底；
- nudge 可观测（落会话 JSONL）：评测层测「触发→是否纠正」构成新的 EDD 指标，
  若纠正率低或误报高，回滚或收窄触发面有数据依据。

## 三、落地机制

### 阶段 2：agent 自检工具（纯工具层，零 runtime 改动）

`flow` 工具（mcp_server/tools/flow_status.py，domain=meta 全 purpose 常驻、
side_effect=none 纯读）：读取当前会话已落盘行（runtime_scope.sessions_dir/sid，
runtime 每轮增量 save）→ scan_rows → trace_scan → 返回阶段四态清单 + 跑偏点 +
计划外旁支的紧凑文本。无会话上下文（MCP stdio 直连）/会话未落盘（首轮中）时
诚实降级提示。技能 generate-scenario 正文加一句「可随时调用 flow 自检路径进度」
（v1.1.0→1.2.0）。

### 阶段 3：纠正提示（非打断）+ 闸门级 WARN + EDD 指标

1. **sg_core/flow_nudge.py**（agent 与 evals 的共同事实源，方向都合法：
   agent→sg_core ✓ evals→sg_core ✓）：
   - `NUDGE_MARKER = "[flow-nudge]"`（落盘标记，评测识别用）
   - `draft_write_prereq_gaps(units) -> list[str]`：给「写草稿之前」的工具单元序列，
     返回缺失的硬前置（validate / read_requirement 两族）
   - `build_flow_nudge(missing) -> str`：一句话提示文案
   - 预置工具族与 evals/flows JSON 的 hard_order 是镜像关系——**一致性钉**：
     测试交叉校验 sg_core 预置族 ⊇ flow JSON hard_order 的 earlier 阶段工具集，
     flow 定义变更不跑 build_flow 同步即红。
2. **runtime nudge**（agent/runtime.py，挂在 T-508 知识 nudge 同一出口）：
   draft(action=write) 且 filename 以 .yaml 结尾（场景草稿；.sql 等其他草稿排除）
   且结果非拒绝类 → 对「本调用之前」的会话内工具单元序列算 gaps → 非空且
   **本会话历史无 NUDGE_MARKER**（整会话一次）→ 工具结果尾部追加提示
   （tool_msg 与 llm_messages 同步改写，与知识 nudge 同机制）。不改结果成败、
   不打断、不熔断。
3. **EDD 指标**：scan_rows 统计 nudge_fires（工具结果含 marker 计数）与
   nudge_corrected（首个 nudge 之后出现 validate 调用）；Phase 0 报告加
   「8_flow_nudge_fires」信息指标、replay 报告加 flow_discipline 维
   （fires/corrected_rate）。纠偏率长期低 → 触发面收窄或回滚的判据。

## 四、明确不做（负空间，评审时逐条对照）

- ❌ runtime 依路径软顺序打断/重路由/熔断（2 条硬顺序也不打断——走 nudge）
- ❌ 按 purpose 强制 flow 达标（flow 永远是参考，不是闸门；闸门只有三闸）
- ❌ 每轮自动把路径评价注入 agent 上下文（token 成本+唠叨+权威混乱）
- ❌ flow(action=status) 之外再造第二个路径自检入口
- ❌ LLM 判定跑偏（评测层 D2 全确定性；nudge 触发条件全确定性）

## 五、分层依赖（方向纪律）

```
sg_core/tool_units.py      工具名归一（助记/legacy/基名+action →（基名,action)）
                           ——自 evals.replay 下沉；evals 侧留转发（T-975 模式）
sg_core/flow_nudge.py      NUDGE_MARKER + 硬前置判定 + 文案（纯函数零依赖）
agent/runtime.py           nudge 出口（sg_core ✓）
mcp_server/tools/flow_status.py  flow 工具（evals 懒加载，缺失诚实降级——与
                           workbench services/flow_trace 同款先例）
evals/…                    评测消费（sg_core ✓）
```

evals.flowpath/workbench flow_trace 的 trace 核心暂不下沉（消费者仅评测+只读面）；
若后续 runtime 需要完整 trace 再做 sg_core 下沉（登记为后续事项）。

## 六、验收标准

1. 门禁：pytest（新增 flow_nudge/runtime nudge/flow 工具/基线指标测试全绿，
   存量 evals/agent 回归零破坏）/ ruff 新文件净 + agent.py 40=40 / release_check
   PASS（无新增模块级回边）/ 前端零改动（vitest/build 不涉）。
2. 行为钉：①写草稿前无 validate → 结果尾含 [flow-nudge]；②validate 在先 → 无
   nudge；③.sql 草稿 → 不触发；④第二次 draft write → 不再触发（整会话一次）；
   ⑤flow 工具在 test_workbench 白名单可见（domain=meta）；⑥无会话上下文诚实降级。
3. 文档：skill v1.2.0、AGENTS.md 工具计数 24→25、本设计文档状态落「已实施」。
