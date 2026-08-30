---
name: generate-scenario
description: 从需求文档生成 SpecGuard 测试场景 YAML
version: 1.2.0
author: platform-team
depends_tools: [info_pack(action=read), spec(action=read), scenario(action=next_id), query_registry, scenario(action=list), scenario(action=read), validate, draft(action=write), scenario(action=suggest_deps), flow(action=status)]
trigger: 用户需要创建新的测试场景、从 Spec 文件生成用例、或使用场景创建向导时
keywords: [生成, 创建, 新建, 新场景, 写个场景, 写场景, 写一个, 用例生成, 生成测试, 场景 YAML, 场景草稿, 覆盖这个需求]
---
## 场景生成技能

### 核心流程

> **进度自检（T-1042）**：可随时调用 `flow` 工具（纯读）查看 golden flow 基线与
> 当前会话实际走径的逐节点比对（顺序正确/乱序/缺失/跳过 + 跑偏点带步号证据）——
> 怀疑漏了步骤或被纠正提示命中时，先自查再继续。自检仅供参考：如属用户明确
> 要求的路径，向用户说明即可，无需强行对齐基线。

1. **读取需求**：使用 `info_pack(action=read)`（如有 scenario_id）或 `spec(action=read)` 读取需求文档（spec(action=read) 支持 `anchor=FR-xxx`/`section=章节` 参数只取关键章节，省 token）
2. **获取 ID**：使用 `scenario(action=next_id)` 获取下一个可用场景 ID
3. **查询注册表**：使用 `query_registry` 确认可用的 tool 和 oracle；场景会用到 `service:` /
   `requires.env` 声明的环境键（如 `*_base`、资源码）时，用 `query_registry(type=env)` 实时查
   当前环境配置（凭据已打码）确认键已存在——**历史试跑报告只反映报告时刻的状态，禁止拿它
   断言当前 env 缺配置**；查不到键再向用户报告，不凭推测下 BLOCKER 结论
4. **参考已有场景（分类定位）**：使用 `scenario(action=list)`（返回含 `summary` 分类摘要：按模块/
   标签聚合计数）——**先看 summary 定位同模块同类参照**（如生成 TL- 系列先看
   by_module 里标签库维护模块的存量），再用 `scenario(action=read)` 读 1-2 个同类场景的结构
5. **生成 YAML**：按照格式规范生成场景 YAML
6. **校验**：使用 `validate` 工具校验生成的 YAML
7. **写入草稿**：校验通过后使用 `draft(action=write)` 写入 drafts/ 目录
8. **依赖建议（必做）**：写完草稿后**必须**调用 `scenario(action=suggest_deps)`（drafts_only=true 或带
   scenario_id）获取确定性依赖建议——草稿出现 `{{上游ID.*}}` 跨场景引用而未声明
   depends_on、或与库内场景存在变量供需关系时，scenario(action=suggest_deps) 会给出建议边与理由；
   **把建议的 depends_on 写入草稿后重新 validate 复核**（草稿阶段带上依赖 = 入库即成图，
   DAG 编排不需要再手工补边；拒绝建议时向用户说明原因，不静默丢弃）

### 交互式生成流程（必须遵守）

**重要**：生成必须与用户交互，不能一次性生成所有场景。按以下步骤进行：

1. **第一步：分析需求并规划**
   - 读取基础信息包（info_pack(action=read)）和需求文档（spec(action=read)）——**关注文件标头的
     [已变更]/[已删除] 标记**（K-013）：标记表示文件在加入信息包后被修改，请基于当前
     最新内容生成，并提醒用户哪些文件已变化、建议更新信息包基线
   - 查询可用工具（query_registry）和已有场景（scenario(action=list)）
   - 分析需求，列出计划生成的场景清单（包含场景 ID、标题、覆盖的 FR）
   - **停止并等待用户确认** — 输出清单后不调用任何工具，等待用户回复
2. **第 1.5 步：DAG 拓扑设计（≥2 个场景时必做，K-021）**——单场景可跳过；多场景先设计
   依赖拓扑并请用户确认：① 划分 prep 与消费场景（tags 标记 prep、声明 produces）② 逐场景
   声明 depends_on（推荐 `{id, version: ^X}`；写型消费用 `mode: exclusive`）③ 声明变量契约
   （上游 save → 下游 `{{上游ID.xxx}}` 引用路径）④ 输出拓扑设计表请用户确认
   （详细编排流程见 dag-orchestration 技能）⑤ 生成期间每完成一批用 **scenario(action=check_dag)**
   （include_drafts=true）预演：无环、无悬空依赖（T4）、无 DRIFT 才继续
   （已入库场景的依赖边用 scenario(action=edit) 编排）⑥ 生成后补边用 scenario(action=suggest_deps)（K-046）
3. **第 1.6 步：权限预检与账号策略（K-055，涉及权限/写操作的场景必做）**
   - 权限敏感场景首步加预检：`tool: {use: precheck_permission, with: {resource_code: X, corp_code?: Y}}`
     ——账号无权限时场景首步即 SKIP（诚实语义），而不是跑到一半 FAIL
   - 需要特定权限账号时优先动态解析：`tool: {use: resolve_account, with: {resource_code: X, corp_code?: Y}, save: acct}`
     ——从权限体系实时找有权限的真实工号（权限表+data-info 复核），不要硬编码工号
   - 跨服务调用用 service 字段：`call: {service: hr_center, ...}`——服务段由 env 的
     `{service}_base` 提供，场景只写服务内相对路径
   - 参数驱动接口可用 `as: internal`（免 Authing 风控）；业务写接口必须用真实用户账号
4. **第二步：逐个生成场景**——用户确认后，**一次只生成一个场景**：
   用 scenario(action=next_id) 获取 ID → 生成 YAML → validate 校验 → draft(action=write) 写入草稿
   （**带上 scenario_id 参数**关联当前场景元数据）→ **告知用户该场景已完成，询问是否
   继续生成下一个** — 停止并等待用户回复
5. **第三步：全部完成后总结**——输出 Markdown 格式的总结报告
6. **第 3.5 步：执行验证（用户要求「跑一下/试试/验证」时，K-021）**——validate 只查格式，
   真实行为必须 run：先 scenario(action=check_dag) 确认拓扑 → scenario(action=run) 试执行（draft 参数跑草稿；
   会真实调用目标环境，先告知用户）→ PASS 进入入库；FAIL 用 attribution(action=report) 归因并修复后
   重跑，连续 2 次修不好 → 停止并向用户报告
7. **第四步：入库（需用户明确确认）**——用户说「确认入库」「入库」等指令后：
   **多份草稿用 draft(action=promote_batch) 批量入库**（一次基线更新+一次门禁；逐份会重复跑全量门禁）；
   单份用 draft(action=promote)；module 参数按场景 ID 前缀归属；批量部分成功时如实汇报 skipped 清单；
   promote 自带格式闸与发布门禁，失败会回滚——把失败原因如实告知用户；
   入库前用户未确认时禁止主动入库

### 格式要点

- `doc.covers` 中的 FR ID 必须在工作区 spec.md 中存在
- `flow` 中的 tool 名称必须已注册
- `verify` 中的 oracle 名称必须已注册
- 字段命名：集合字段用 `List` 结尾，字段一律驼峰
- **插值只允许四种形态**（{{random:6}} 等 Apifox 语法 SpecGuard 不支持，运行期必
  「变量未定义」——validate 会报 UNKNOWN_TPL ERROR）：
  ```yaml
  {{fn.uuid_short}}            # ① fn.* 内置函数：fn.timestamp / fn.date / fn.uuid_short
  {{env.resource_code}}        # ② env.* 环境键（或 env.vars.* 子键）
  {{IS-PREP-001.session.json.data.id}}  # ③ {{上游场景ID.*}}（须已在 depends_on）
  {{resp.json.data.id}}        # ④ 本场景 save 变量 / set_var vars 裸名
  ```
  需要随机唯一后缀用 `{{fn.uuid_short}}`；需要随机数先 `random` 步骤
  （`- random: {type: number, min: 1, max: 100, save: n}`）再 `{{n}}` 引用
- **call 请求体一律用 `json:` 键**（2.1.0 起）：`json: {tagName: x}`；`body:` 是 2.1.0 前
  废弃键，引擎只认 `json:/form:/urlencoded:/raw:/file:`（body_type 推断），写 `body:` 会
  静默丢请求体（validate 会报 BODY_KEY WARN——生成后务必 validate 确认无此告警）
- 生成后必须 `validate` 自检：UNKNOWN_TPL（未知插值）与 BODY_KEY（body: 键）均为
  ERROR/WARN 级硬伤，有则修正后再入库
- **声明执行依赖（格式 2.3.0 起，预检扫描数据源）**：在机器读层加 `requires` 段，声明
  flow/verify 用到的账号别名、环境键与跨场景变量引用（缺失 → 执行前预检弹窗预警）：
  ```yaml
  requires:
    accounts: [platformNoCorp]      # flow as:/fetch_permission 引用的账号别名
    env: [resource_code]            # {{env.*}} 引用的环境键（vars.xxx 子键用点号）
    upstream: [IS-PREP-001]         # {{上游ID.*}} 变量来源场景（须已在 depends_on）
  ```
  `accounts` 别名必须是目标环境 `env.{env}.yaml` 的 `accounts` 段已定义的真实 AD 账号；
  拿不准环境有没有该账号时，向用户确认或参考环境配置页。requires 不进契约指纹，
  增删无需 bump version；未声明时预检扫描器会从 flow 文本静态兜底提取。

### 测试设计方法（dimensions，生成前必做维度思考）

生成场景不是「把需求翻译成一次成功调用」——每个场景必须有明确的测试设计意图，
并用 `doc.dimensions` 受控词表标注（覆盖面板按维度聚合，全是 happy-path 的模块
会被一眼看出盲区）。生成一批场景时按下表做**维度搭配**，不要全堆正向：

| 维度 | 什么时候标 | 断言要点（validate 的 T10 自检依据） |
|------|-----------|--------------------------------------|
| `happy-path` | 典型输入的预期行为、prep 数据准备 | status 2xx + 响应体字段断言 |
| `negative` | 非法输入/错误状态被显式拒绝 | status ≥400，或包装协议错误码（`$.status`≠200），或错误消息/failCount 断言 |
| `boundary` | 空值/特殊值/极限值（"-"、0、NULL、越界） | 边界结果的显式 json/DB 断言（不是「不报错就算过」） |
| `permission` | 数据权限裁剪、受限账号、越权访问 | 权限 oracle / `absent: true` / 拒绝错误码 |
| `security` | 未登录、fail-secure 不泄露 | 拒绝证据 + 不泄露证据（absent） |
| `state` | DB 字段比对、快照冻结、状态机流转 | oracle 断言器或 db_query 派生 json 断言 |
| `isolation` | 行级/多主体对照（正常与异常并存） | db_query 对照断言（正常行 vs 异常行） |
| `regression` | 历史 bug 复现防护 | 标注语义为主，配合 doc.related_bug 溯源 |

测试设计方法对应关系：**等价类划分** → 每个有效/无效等价类至少一个场景
（happy-path + negative 搭配）；**边界值分析** → 对数值范围、必填可选、空/特殊字符
必出 boundary 场景；**场景法** → 主流程 happy-path、备选/异常流程 negative/state；
**错误推测** → 凭经验补权限、安全、隔离维度场景。标注 1~3 个维度/场景，
validate 会对「声明维度但 verify 无对应证据」报 DIM_MAP WARN（测试设计自检）。

### 硬约束

1. 场景 YAML 必须符合格式规范；doc.covers 中的 FR ID 必须在当前工作区的 spec.md 中存在
2. flow 中的 tool / verify 中的 oracle 名称必须已注册
3. 生成后必须调用 validate 工具校验，通过后用 draft(action=write) 写入 drafts/ 目录
4. 禁止编造不存在的 FR ID、tool 名称或 oracle 名称
5. **禁止连续生成多个场景** — 每个场景完成后必须暂停，等用户确认
6. **doc.covers 必填**（1 个起步）——covers 是场景↔Spec 的强制锚点，覆盖分析、DAG 编排、
   delta 导入计划全部依赖它；无 covers 的场景等于断了溯源
7. **doc.dimensions 必填**（受控词表 1~3 个）——测试维度是覆盖面板的聚合依据；
   词表外值 validate 报 ERROR，缺失报 WARN；维度必须与 verify 断言证据一致（见上节映射表）

### 工具报错处理（K-020，必须遵守）

每次工具报错都可能关系到场景是否建立在真实的 spec 基础上，**禁止忽视、禁止绕过式自愈**：

1. **禁止通过删除必需字段来消除报错**——尤其是 covers、verify 断言、flow 步骤。
   删除 covers 让 validate 从 REJECT 变 PASS，不等于场景变合规，等于切断溯源
2. validate 报 ANCHOR 错误时：先用 spec(action=read) 亲自核实该 FR 是否在 spec.md 中
   （可用 anchor=FR-xxx 参数只取该锚点章节，省 token）
   - 若 FR 确实不存在 → 改用一个真实存在的 FR（引用核实出处）
   - 若 FR 明明存在 → 属于校验器误报，**停止生成并向用户报告**，等待指示；
     支持的锚点格式：`### FR-xxx: 标题` 或 `- **FR-xxx**：` 列表定义
3. 任何工具连续报错 2 次仍未解决 → 停止当前生成，向用户说明报错内容与已尝试的方案
4. 报错及处理方式必须在回复中如实告知用户，不得静默消化

### 信息不足时

- 主动向用户提问，明确缺失的信息
- 用户确认补充文件后，使用 `info_pack(action=add)` 将文件加入基础信息包
- 使用 `info_pack(action=read)` 重新读取更新后的文件
