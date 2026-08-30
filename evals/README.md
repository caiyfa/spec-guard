# evals/ — Agent 评测体系（T-980 通道 B + T-1042 Phase 0/通道 A）

> 依据：《[2026-08-20-第二轮-六点反馈判定-多系统与智能层.md](../docs/架构反馈升级/2026-08-20-第二轮-六点反馈判定-多系统与智能层.md)》§5
> （轨迹断言先行——确定性断言没穷尽前不上 LLM-as-judge）。
> 定位：智能层后续一切的地基——T-982 工具收敛将用本 eval 集对比收敛前后
> 工具选择轨迹；prompt / skills / 模型变更都应触发重跑。
>
> **T-1042 二期扩展**（依据《docs/SpecGuard-Agent评测体系-现状基线.md》§十五/§十六 +
> 知识库《2026-08-26-2037 评估架构体系设计》）：在通道 B（golden case 回放）之上补
> Phase 0 基线仪表盘（聚合已落盘信号出七指标）与通道 A（生产会话轨迹重放打分 +
> 真实会话反向导出 golden case）。三件套分工见下表。

## 三件套分工（T-980 → T-1042）

| 模块 | 通道/阶段 | 干什么 | 数据源 | 退出码 |
|------|-----------|--------|--------|--------|
| `harness.py` + `run_evals.py` | 通道 B | golden case 前瞻性回放断言（合成 prompt + 脚本 LLM） | `evals/cases/*.json` | 0/1（挂 CI） |
| `baseline.py` + `run_baseline.py` | Phase 0 | 聚合已落盘信号出七指标基线报告 | 会话 JSONL + metrics + audit 库 | 恒 0（只读报告） |
| `replay.py` + `run_replay.py` | 通道 A | 生产会话轨迹重放打分（不重跑只打分，五维信号） | 会话 JSONL | 恒 0（只读报告） |
| `export_case.py` | L1 样本层 | 真实会话 → golden case 反向导出（喂通道 B） | 会话 JSONL | — |

通道 B 是守门（前瞻），Phase 0 / 通道 A 是度量（回顾）；export_case 把生产会话
转成通道 B 的样本源，三者共享「工具结果成败判定」（`_RESULT_ERROR_PREFIXES`）。

## 一条命令

```powershell
# ── 通道 B（T-980）：golden case 回放门禁 ──
python evals/run_evals.py              # 全量（evals/cases/*.json）
python evals/run_evals.py --list       # 只列 case
python evals/run_evals.py evals/cases/001-list-scenarios.json   # 单个

# ── Phase 0（T-1042）：七指标基线仪表盘 ──
python evals/run_baseline.py --sessions-root <主库agent/sessions> --db <主库workbench.db>
python evals/run_baseline.py --limit 50 --no-write   # 快速试跑不落盘

# ── 通道 A（T-1042）：生产会话轨迹重放打分 ──
python evals/run_replay.py --sessions-root <主库agent/sessions>
python evals/run_replay.py --only-generate           # 只看「创建测试用例」会话
python evals/run_replay.py --trace <会话.jsonl>      # 单会话路径重放（§16.1 flow 图比对，着色 mermaid+差异表）
python evals/run_replay.py --trace-all               # 全部生成会话批量路径重放 → traces/index.md（按差异数降序）

# ── 反向导出（T-1042）：真实会话 → golden case ──
python evals/run_replay.py --export <会话.jsonl> --export-out evals/cases/GC-PROD-xxx.json
```

pytest 侧回归：`python -m pytest test_specstd/test_evals.py test_specstd/test_evals_baseline.py test_specstd/test_evals_replay.py test_specstd/test_evals_export.py -v`。

退出码：通道 B 0/1（可挂 CI / pre-push）；Phase 0 / 通道 A 恒 0（只读度量，不挂门禁）。

## 产物（`evals/results/`，不入 git）

| 文件 | 内容 |
|---|---|
| `metrics.jsonl` | 每 case 一行，**含工具维度**：`tools_sequence`（调用序列）/ `tool_success_rate` / `steps` / `turns` / `duration_ms` / `fused` / 断言计数与失败明细。append 累积，供跨版本对比（T-982 用） |
| `report.md` | 本次运行全量断言报告（overwrite） |
| `{EVAL-ID}.messages.json` | 失败 case 的完整消息链（只在失败时落盘，诊断用） |

## golden case 格式（`evals/cases/*.json`）

```jsonc
{
  "id": "EVAL-003",                  // 唯一 ID（report/metrics 外键）
  "name": "draft-write-validate",    // 短名（报告展示）
  "description": "…",                // 这个 case 在守什么行为
  "task_prompt": "…",                // 任务 prompt（user 消息）
  "max_turns": 8,                    // runtime 熔断上限（默认 8）
  "allow_leftover": false,           // 测熔断行为的 case 才设 true（见下）

  // 脚本化 LLM：按序回放的 assistant 响应——脚本本身就是 golden 期望：
  // 耗尽（轨迹比预期长）或剩余（提前熔断/取消）默认都判失败
  "llm_script": [
    { "role": "assistant", "content": "", "tool_calls": [
      { "id": "c1", "type": "function",
        "function": { "name": "spec(action=read)", "arguments": { "path": "…" } } }  // arguments 可写对象
    ]},
    { "role": "assistant", "content": "最终答复（无 tool_calls 即停）" }
  ],

  // 工具结果 mock：只 mock 声明过的工具（替换 runtime._tool_map 条目，
  // 白名单/参数解析/截断等 runtime 链路全真）；未声明的走真实实现
  "tool_mocks": {
    "spec(action=read)": { "json": { "content": "…" } },        // JSON 结果
    "draft(action=write)": { "text": "ok" },                     // 纯文本结果
    "some_tool": [                                       // 多次调用按序取，末个重复
      { "json": { "code": 1 } }, { "error": "boom" }     // error=抛异常
    ]
  },

  // 断言（顺序即报告顺序）
  "expect": [
    { "type": "tool_sequence", "expect": ["spec(action=read)", "draft(action=write)", "validate"],
      "ignore": ["todo_write"] },                        // 精确序列（可忽略 meta 工具）
    { "type": "tools_required", "expect": ["validate"] }, // 子集：这些必须调过（「调没调指定工具」）
    { "type": "tools_forbidden", "expect": ["draft(action=promote)"] }, // 这些不许调
    { "type": "tool_result", "tool": "validate",
      "jsonpath": "$.verdict", "equals": "PASS" },       // jsonpath + equals/min/contains
    { "type": "artifact_validate",                        // 产物断言：复用 validator
      "source_tool": "draft(action=write)", "content_key": "content",
      "expect_verdict": "PASS", "max_error": 0 }         // 校验写型工具参数里的产物原文
  ]
}
```

## 断言语义（全部确定性）

| type | 回答的问题 |
|---|---|
| `tool_sequence` | 工具调用顺序是否正确（LLM 是否按正确工作流编排） |
| `tools_required` | **调没调指定工具**（用户手测的第一个问题） |
| `tools_forbidden` | 有没有碰不该碰的工具（越权/绕闸） |
| `tool_result` | 工具结果是否正确（jsonpath 定位 + equals/min/contains） |
| `artifact_validate` | 产物是否合格——`validate_scenario_content` 与 MCP validate 工具、promote 发布门禁同源，不新建评估器 |
| （内建）`script_usage` | 轨迹长度是否符合脚本（耗尽/剩余均判失败；测熔断设 `allow_leftover: true`） |

工具调用成败（`tool_success_rate`）按 runtime 错误出口前缀判定
（`错误：` / `[越权拒绝]` / `未知工具:` / `工具执行异常:` / `[SIDE_EFFECT_VIOLATION]` / `[拒绝]`），
非启发式。

## 离线确定性

评测进程内隔离工作区（SG_WORKSPACE 环境变量 / 注册表 active / contextvar 全部清空），
validate 的 COVERS 校验等行为按「无激活工作区」确定性回放，不随宿主漂移；
case 只允许使用离线可用的真实工具（`scenario(action=list)` / `validate` / `query_registry` 等纯读）
或声明 mock。**禁止在 case 里调用联网/DB 工具**（worktree 纪律：只跑离线测试）。

评测期中和的副作用通道：审计落库（workbench.db）、纯读指纹扫描（rglob 工作区克隆）——
与轨迹断言正交，就地 patch，不影响真实链路语义。

## 如何加 case（EDD 原则）

1. 从 feedback 台账 / 真实会话（`python -m agent.inspect <sid>`）里找一个「Agent 行为对/错」
   的具体片段，提炼任务 prompt + 期望工具轨迹；
2. 复制最接近的现有 case 改写；先让断言失败（红），再确认断言语义正确后转绿；
3. 命名 `{序号}-{行为slug}.json`，ID 用 `EVAL-{序号}` 递增，勿复用已删 case 的 ID
   （metrics.jsonl 按时间累积，ID 是跨版本对比的键）。

## 与 T-964 / T-982 的关系

- **T-964**（clarity 假分数清理）在主库进行：specflow 五维评分复用是 T-980 的后续，
  clarity 占位分数清完才谈评分维度入 eval——本目录 v1 只做轨迹与 validator 断言。
- **T-982**（工具收敛）：合并/削减工具前后各跑一次 `python evals/run_evals.py`，
  对比 `metrics.jsonl` 的 `tools_sequence` 与断言通过率——「收敛是否伤正确性」由数据回答。

---

## Phase 0 七指标基线（T-1042，§十五.5）

`run_baseline.py` 聚合**已落盘**三类信号，产出七指标——后续一切改进的对照原点：

| # | 指标 | 信号源 | 主库 2026-08-30 实测（274 生产会话） |
|---|------|--------|--------------------------------------|
| 1 | 工具调用成功率 | 会话 tool 行结果前缀 | 92.61% |
| 2 | 越权拒绝率（denied-whitelist） | `sf_mcp_call_audit` verdict | 2.04% |
| 3 | 熔断率 | 会话 `[FUSE]` system 行 | 5.84% |
| 4 | 三闸通过率 | `audit_log` 三闸事件 | 占位（口径待确认） |
| 5 | validate 一次通过率 | validate 结果 verdict | 43.24%（37 可评分） |
| 6 | 纠正触发率 | user 消息纠正关键词 | 5.47% |
| 7 | 每任务 token（均值/p50/p95） | metrics total_tokens | 388k / 163k / 1.9M |

口径说明：① smoke 隔离区（T-1041）按路径标 `__smoke__` 排除出生产基线（单列）；
② purpose 空 = T-010 体系（2026-08-10）前历史会话，标 `legacy(no-purpose)` 非解析失败；
③ 审计库混有测试/探针工具（`nonexistent_*`/`switch_mode`），解读时剔除；
④ 任一无足够数据给 `None` 并注明 reason，不造假数字（T-964 教训）。

## 通道 A 五维信号（T-1042，§十六）

`run_replay.py` 对生产会话**不重跑只打分**，按 §16.2 generate-scenario 轨迹基线比对：
D2 多轮轨迹（阶段覆盖/序列合理/禁用工具）、D3 任务终局（validate 通过/写草稿达成）、
D5 安全护栏（白名单拒绝/纯读副作用/熔断）、D1 工具选择、D4 效率成本。
LLM-judge 主观维度（诚实性/SKIP 语义）留 Phase 3 不做。主库实测：306 会话识别
28 个生成会话，D2 阶段覆盖 74.4%、序列合理率 56.25%（暴露过半会话写草稿前未先
校验/读需求——正是通道 A 要度量的行为问题）。

## 路径重放：flow 图逐节点比对（T-1042，evals/flowpath.py）

聚合指标回答「总体怎么样」，路径重放回答「**这个会话具体哪步跑偏**」——把 §16.1
flow 图编码为可执行 golden flow（12 阶段，必选/可选 + 两条硬顺序约束：
读需求<写草稿、校验<写草稿），对单会话逐节点比对：

- **四态判定**：in_order 顺序正确（🟩）/ out_of_order 乱序（🟨）/ missing 缺失必需（🟥）/
  skipped 跳过可选（⬜ 虚线）；差异句带步号证据（「写草稿（第 2 步）先于 validate 校验（第 3 步）」）
- **计划外工具**：基线外旁支单列（benign 元工具剔除）——旁支不等于违规，但精力去向可见
- **产出**：着色 mermaid 路径图 + 差异明细表（`--trace` 单会话打印；`--trace-all` 批量
  落盘 `traces/{sid}.md` + 索引按差异数降序，最跑偏的排最前）
- **工具名归一**：三种调用形态（助记 `spec(action=read)` / legacy `read_spec` /
  T-982 后新形态 基名+`arguments.action`）统一归一到（基名, action）再比对——
  新旧会话同一基线可比；主库实测生成会话识别 28→38（修复新形态漏识别）

主库 38 个生成会话批量重放实证：差异数 0~5 分布，头部会话缺 5 个必需阶段；
教材级会话（20260727_193934）全绿 0 差异——好路径与跑偏路径在同一基线下立判。

## 反向导出（T-1042，L1 样本层）

`export_case.py` 把真实会话 JSONL 转成 golden case：`llm_script`←assistant 序列、
`tool_mocks`←tool 结果（legacy 工具名经 `tool_meta.legacy_owner` 归一合并基名+action，
旧会话也能在当前 runtime 回放）。**导出即起点**：轨迹未必正确，须人工评审
（删错误步骤/收紧 expect/标注 verdict）后才入 `evals/cases/`——EDD 问题驱动补 case
的入口，不是自动转 gold（case 只增不改）。
