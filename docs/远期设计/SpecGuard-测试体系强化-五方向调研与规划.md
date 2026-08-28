# SpecGuard 测试体系强化——五方向调研与规划

> 状态：待评审 · 2026-08-28
> 来源：2026-08-28 全方位测试强化调研（三路并行扫描：场景库盘点 / 引擎能力边界 / 项目自身测试基建）+《SpecGuard-Agent评测体系-现状基线》
> 定位：测试体系强化的总规划。方向一为已启动项（场景库质量管理页，见 §2）；方向三中的触发制储备拆出至灵感池（`docs/灵感/2026-08-28-引擎触发制能力缺口-命中真实场景再启动.md`）。

---

## 1. 背景与调研方法

目标：全方位强化 SpecGuard 的测试能力与测试资产质量。调研分三路：

1. **场景库盘点**：`scenarios/` 全量 101 个场景（9 个套件）的结构、covers 分布、断言深度、引擎能力使用矩阵。
2. **引擎能力边界**：`engine/` 已实现能力 vs 两批升级建议 / V3 待实施设计 / 远期总控储备的差距核对，产出 17 项能力缺口清单。
3. **项目自身测试基建**：`test_suites/`、`test_engine/`、`test_specstd/`、`test_workbench/`、前端 vitest、质量基线报告（`docs/质量基线/`）、门禁与 CI 现状。

结论汇总为五个强化方向，下面逐一展开。§7 给出优先级建议，§8 给出任务号建议。

---

## 2. 方向一：场景库质量（本批次启动）

### 2.1 现状数据（2026-08-28 实测）

场景库共 **101 个场景 / 9 个套件**，核心问题四个：

**① 覆盖追溯断裂**：仅 21/101（21%）场景带 `covers` 标签。

| 套件 | 场景数 | covers 现状 |
|------|--------|------------|
| employee/person-profile | 15 | 唯一健康套件：FR-001~FR-017 中 10 个有覆盖（FR-002/013/015 各 4 场景） |
| inventory/inventory-session | 5 | 3 个带 covers（FR-012） |
| system-settings/inventory-activity | 2 | 各带 1 个 covers |
| inventory/smart-tag/标签库维护 | **65（64%）** | 全部无 covers，_suite.yaml 无 spec_ref |
| system-settings/tag-library | 7 | 全部无 covers |
| evaluation/eval-360、inventory/grid-placement | 各 2 | 显式 `covers: []` |
| tmp/、权限测试/ | 3 | 临时/探针残留 |

连带问题：**FR 编号无模块命名空间**——inventory-session 的 FR-012 与 person-profile 的 FR-012 全局统计时混淆。

**② FR 空洞**：person-profile 的 FR-005/007/008/009/011 无任何场景；eval-360、grid-placement、tag-library 的 spec FR 完全无标签化覆盖。`query_coverage_gaps` 工具和 FR→场景覆盖证明目前只对 person-profile 一个套件成立。

**③ 断言深度两极分化**：
- 强：`EV-IMP-001`（3 张表行级 DB 校对：行数/NULL 语义/数值精度）、`PP-SNAP/PP-PERM` 系列（oracle 驱动：快照全等、权限矩阵过滤）、`IS-RVT-001`（API+DB 双通道状态机）。
- 弱：TL-RC 系列 65 个场景普遍只断言 `status 200 + 字段 not_null/is_array`，doc 层承诺的行为（如"按创建时间倒序"）未落实为断言；`HI-PERM-001` 是零断言探针，混在正式场景树。

**④ 卫生问题**：`scenarios/tmp/`（2 个临时 unit 场景）、`scenarios/权限测试/`（零断言探针）混入正式库；SS-TAG 编号跳号（缺 003）、套件内混入 TL-DTL-001、`0807-ACT-001-ok.yaml` 带 "-ok" 后缀、IS-PREP 缺 001。

**⑤ 引擎能力闲置**（场景侧不用，非引擎缺陷）：`shared` 依赖模式、`oss_download`、`resolve_account`（K-055 动态账号）、顶层 `resources:` 声明、python 步骤（仅 1 个探针）；oracle 深断言只活在 person-profile 一个套件。

### 2.2 强化动作

| # | 动作 | 说明 | 状态 |
|---|------|------|------|
| 1 | **场景库质量管理页** | 工作台新增只读看板：全局统计 + 套件聚合 + 场景级断言深度/问题标记，质量一屏可见 | **本批次启动（wt/scenario-quality）** |
| 2 | 补 covers | 存量 80 个场景，Agent 批量起草 + 人工过闸；同步解决 smart-tag/tag-library 套件缺 spec_ref 问题 | 待启动 |
| 3 | FR 空洞补缺 | person-profile FR-005/007/008/009/011 优先；依赖 delta/Spec 侧确认这些 FR 的现状语义 | 待启动 |
| 4 | 浅断言深化 | TL-RC 系列 doc 承诺逐条落成断言，公共校验逻辑下沉为可复用 oracle | 待启动 |
| 5 | 卫生清理 | tmp/ 与探针场景移出正式树或补齐断言转正；编号/命名规整 | 待启动 |
| 6 | FR 命名空间 | covers 引用与统计按模块隔离（方案需与 specstd 锚点层对齐评审） | 待评审 |

---

## 3. 方向二：负向/权限/异常场景族

**① 权限负向矩阵（成本最低、解锁最快）**：唯一前置是配置缺口——`systems/tdm/config/env.sit.yaml:41` 的 restricted 受限账号仍为 `TODO_AD/TODO_EMPNO` 占位。配上真实受限账号后，现成基建（`precheck_permission` 预检 + `permission_filtered`/`vm_filtered` oracle + `PP-PERM-004` 的条件 SKIP 语义）即可支撑一整族场景：越权访问拒绝、数据脱敏、菜单/字段可见性、行级数据隔离。

**② 异常路径场景族（当前为零）**：
- 错误码语义：参数非法 / 资源不存在 / 状态冲突的显式拒绝断言（`extract_evidence` 已能识别 http_error/body_error_code/error_message 证据，`negative` 维度词表已就位——T-981 基建等场景落地）。
- 边界值：分页上限、超长文本、特殊字符、空值。
- 并发/幂等：重复提交、状态竞态（引擎 `retry`/`idempotent` 已备好地基）。

**③ 数据驱动参数化**：若异常/边界场景批量铺开，将首次真正撞上 T-504（Scenario Outline）需求——届时按冻结层评审流程动语法层，现在不做。

---

## 4. 方向三：引擎能力缺口（仅 3 项有真实业务驱动）

逐一核对两批升级建议、V3 待实施设计、灵感库、远期总控后，17 项缺口中**只有 3 项有真实场景实证驱动**：

| # | 缺口 | 业务驱动 | 实施建议 |
|---|------|----------|----------|
| 1 | **U-5 文件本体断言**（下载 xlsx 的 sheet/单元格校验） | 导入导出类场景校验止步于 API 响应；`oss_download` 注册后零使用是直接证据 | 放系统适配层（`systems/tdm`）做，引擎零改动；原升级建议即此口径 |
| 2 | **T-503 DB 轮询**（poll 仅接受 HTTP call 体） | "状态只在库里、无 HTTP 状态接口"的异步任务测不了 | 维持总控储备触发制：首个真实场景出现时启动 |
| 3 | **受限账号配置** | 权限负向矩阵前置（见方向三①） | 配置补齐，非引擎改动 |

其余 14 项（并行执行、produces/consumes 状态接力、参数化、租约早收、session 启动自检、断言表达力边角等）维持触发制储备，已沉淀至灵感池：`docs/灵感/2026-08-28-引擎触发制能力缺口-命中真实场景再启动.md`。**现在做属于过度建设**。

---

## 5. 方向四：项目自身测试基建

SpecGuard 作为测试工具，自身测试地基比预期薄弱（2026-08-14 质量基线 + 当日复核）：

| # | 问题 | 现状 | 强化动作 |
|---|------|------|----------|
| 1 | **门禁太窄** | pre-push 只守 release_check + engine 离线测试；前端 vitest（23 文件 142 用例全绿）、test_workbench（66 用例）、evals 评测（退出码已设计成 0/1 可挂 CI）均未挂任何钩子 | 三者挂进 lefthook pre-push，纯配置活 |
| 2 | **引擎覆盖率低洼** | engine 整体 46%；`report_writer.py` 8%、`token_provider.py` 20%、`scenario_loader.py` 26%、`scenario_runner.py` 38%——全是核心路径 | 按低洼清单补单测（test_engine/），offline 可跑 |
| 3 | **前端大面积裸奔** | 33/35 页面无测试；唯一 hooks 文件 useRunStream.ts 无测；26/29 api 模块无测 | 随 Boy Scout Rule 顺手补 + 核心页面（Scenarios/RunControl/DagEditor）优先 |
| 4 | **test_specstd 94 个存量 error** | 全套件跑报错、单文件全绿——套件内隔离污染（已知与 FeishuWatcher._schedule_chat_proofread 闭包任务无法被 apscheduler 序列化相关），导致 1971 个用例进不了门禁 | 二分定位污染源修复 → 全套件挂门禁 |
| 5 | **无远端 CI** | 质量保障完全依赖本地 lefthook pre-push | 评估 gitee 流水线或保持本地门禁+纪律（总控人拍板） |

---

## 6. 方向五：Agent 评测体系

现状基线已就绪：`docs/SpecGuard-Agent评测体系-现状基线.md`（2026-08-26 口径，未入库）已完整梳理评测挂钩点——会话 JSONL / 逐轮 metrics / 工具审计 SQLite / 执行报告 / doc_write verdict / 经验飞轮 corrected 事件等 12 类结构化信号**已经落盘，评测器无需重新埋点**。

切入点（基线文档 §15 已详述，此处只列骨架）：
1. 评测对象五层：单轮工具选择 / 多轮任务轨迹 / 任务终局质量（三闸确定性结果，天然免 judge）/ 效率成本 / 安全护栏。
2. Judge 策略：确定性校验器优先（validate/scan_compliance/release_check/三闸），LLM-as-judge 只补对话质量主观维度。
3. 数据集：生产会话抽样（export 端点）去敏做回归集；`failures/index.jsonl` + corrected 事件是天然负例集。
4. 离线通道：`evals/` harness 已存在（T-980 基建，轨迹断言 + MockLLM 回放），退出码 0/1 可直接挂门禁——**第一步就是把 evals 挂进 pre-push**（与方向四①合并实施）。
5. 基线指标先行：工具调用成功率、denied-whitelist 率、max_turns 熔断率、产物三闸通过率、validate 一次通过率、纠正关键词触发率、每任务 token 成本。

作为独立立项推进，评测基线文档可直接转任务书。

---

## 7. 优先级建议（三梯队）

| 梯队 | 内容 | 理由 |
|------|------|------|
| **第一梯队（投入小见效快）** | 方向三③受限账号配置（半天，解锁权限负向场景族）；方向四①门禁扩展（vitest/test_workbench/evals 挂 pre-push，纯配置） | 一个是"配账号解锁一类场景"，一个是"现成绿灯资产白捡门禁" |
| **第二梯队（核心资产增值）** | 方向一·场景库质量：管理页（本批次）→ 补 covers → FR 空洞补缺 → TL-RC 浅断言深化（量最大，适合 Agent 批量起草+人工过闸） | 场景库是 SpecGuard 的核心资产，covers 关联完整性是 DAG 编排前置铁律 |
| **第三梯队（按真实需求触发）** | 方向三①②（U-5/T-503 等真实场景撞上再做）；方向四②③④（覆盖率补洼、94 error 排障）；方向五评测体系独立立项 | 触发制储备不做过度建设；评测体系跟随基线文档转任务书 |

---

## 8. 任务号建议（待总控登记）

按总控 §4 规则（T-1000 起顺序递增；当前最大 T-1034；T-1027 撞号待裁决，新区段避开）：

| 建议任务号 | 内容 | 状态 |
|-----------|------|------|
| T-1035 | 场景库质量管理页（后端 /api/scenario-quality + 前端看板页） | 本批次启动（wt/scenario-quality） |
| T-1036 | 受限账号配置补齐 + 权限负向场景族首批 | 待认领 |
| T-1037 | 门禁扩展：vitest / test_workbench / evals 挂 pre-push | 待认领 |
| T-1038 | 场景库 covers 批量补齐（Agent 起草+人工过闸） | 待认领 |
| T-1039 | TL-RC 系列浅断言深化（doc 承诺→断言/oracle） | 待认领 |
| T-1040 | test_specstd 94 存量 error 排障 + 全套件挂门禁 | 待认领 |
| T-1041 | U-5 文件本体断言（xlsx 校验，systems/tdm 适配层） | 储备·触发制 |
| T-1042 | Agent 评测体系立项（基线文档转任务书） | 待总控拍板 |

> 注：新增任务按规则由总控人在总控 §4 追加；本表为建议稿。
