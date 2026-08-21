# evals/ — Agent 评测体系（T-980）

> 依据：《[2026-08-20-第二轮-六点反馈判定-多系统与智能层.md](../docs/架构反馈升级/2026-08-20-第二轮-六点反馈判定-多系统与智能层.md)》§5
> （轨迹断言先行——确定性断言没穷尽前不上 LLM-as-judge）。
> 定位：智能层后续一切的地基——T-982 工具收敛将用本 eval 集对比收敛前后
> 工具选择轨迹；prompt / skills / 模型变更都应触发重跑。

## 一条命令

```powershell
python evals/run_evals.py              # 全量（evals/cases/*.json）
python evals/run_evals.py --list       # 只列 case
python evals/run_evals.py evals/cases/001-list-scenarios.json   # 单个
```

退出码 0/1（可挂 CI / pre-push）。pytest 侧回归：`python -m pytest test_specstd/test_evals.py -v`。

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
