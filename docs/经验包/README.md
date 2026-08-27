# 问题修复经验包

> SpecGuard 排障闭环的知识沉淀：每个「具体问题 → 根因 → 修复 → 预防」独立一文件，
> 本 README 是**入口与协议**（AGENTS.md 指向此处）。
> 建立：2026-08-02 ｜ 首个案例：EX-8200eada（变量未定义 · 权限缺失）

---

## 协议（排障闭环后登记）

> 经验包分两类：**类型一·事故类**（单点排障闭环，走下方五段模板）；**类型二·模式扫描类**
> （跨任务的问题代码模式提炼，结构为「来源依据→问题形态→扫描命令→通过标准→实测基线」，
> 供全库定期扫描与评审新代码对照，首份见索引 2026-08-23 M 系列行）。

1. **命名**：`{日期}-{任务号}-{现象摘要}.md`（如 `2026-08-02-EX-8200eada-变量未定义-权限缺失.md`）
2. **模板**：每个经验包固定五段——
   - **现象**：任务号 / 错误消息 / 用户看到的表象
   - **证据链**：output.log / run.json / 响应体 / 失败索引 等关键摘录（附位置）
   - **根因**：哪个环节缺失（环境 / 场景 / 引擎 / 配置），一句话结论
   - **修复**：代码 / 场景 / 环境动作（附提交号）
   - **预防**：检查清单 / 约定 / 相关任务号
3. **登记**：新增经验包后，在本 README 索引表追加一行，并在 AGENTS.md「问题修复经验包」入口章节确认指向不变（入口永远指向本 README）
4. **原则**：写「可复现的事实」不写推测；根因必须是证据链支持的结论；预防要可执行

## 索引

| 日期 | 任务号 | 现象 | 根因（环节） | 修复 | 预防 |
|---|---|---|---|---|---|
| 2026-08-02 | [EX-8200eada](2026-08-02-EX-8200eada-变量未定义-权限缺失.md) | `变量未定义: activity.json.data.id` | SIT 权限体系 TDM_INV_ACTIVITY 资源码无绑定账号（环境） | 写型场景首步补 precheck_permission（2d969c4）；SIT 授权待环境侧 | 写型场景首步 precheck；环境交付 checklist 绑定写型资源码 |
| 2026-08-02 | [测试污染生产配置](2026-08-02-测试污染生产配置-monkeypatch双实例陷阱.md) | env.sit.yaml 被测试覆盖截断 | monkeypatch 双模块实例（sys.path 双路径导入，测试基建） | 同实例导入修复 + git checkout 恢复（4be2aee 前后） | 写盘测试验证模块同实例；跑完查 git status |
| 2026-08-12 | [pytest端到端测试污染真实会话目录](2026-08-12-pytest端到端测试污染真实会话目录.md) | 会话列表大量空会话（仅 meta 行无消息） | TestClient 测试未隔离 `SESSIONS_ROOT`/`DB_PATH`（测试基建） | fixture 补 monkeypatch 隔离 + 清理 374 个空会话；test_purpose/test_multiuser 65 绿、跑测后文件数零变化 | TestClient 测试三隔离标配；新增端到端测试前检查 fixture；跑完查会话目录文件数 |
| 2026-08-12 | [工作区被误注册为local型无法git更新](2026-08-12-8aca780f-工作区被误注册为local型无法git更新.md) | sync_workspace 报「不是 git 型，不支持拉取」 | 8-11 register-local 覆盖了 7-27 的 git 注册（配置层） | 修正 registry.yaml（type 改回 git + active=tdm + local_path 完整相对路径），pull 成功 6aa29e6→84f011c3 | 重注册前查 audit_log 确认类型；注册本地工作区禁止选 _clones/ 目录；修复时 local_path 用完整相对路径 |
| 2026-08-12 | [测试污染真实工作区注册表](2026-08-12-测试污染真实工作区注册表-register_local未隔离.md) | 会话工作区突然消失，registry.yaml 被清空（active/workspaces 均空） | register_local 测试未隔离 REGISTRY_PATH，fixture 依赖顺序错误致 monkeypatch 未生效，同名 tdm 覆盖真实条目后 teardown 删除（测试基建） | 无损重建 registry.yaml（复用 _clones/tdm 不重 clone）；repo/git_repo fixture 改依赖 db；验证 read_spec 恢复 | 注册类测试先隔离 REGISTRY_PATH 且 fixture 依赖顺序正确；测试工作区名禁用真实名；跑完查 registry.yaml |
| 2026-08-14 | [APScheduler闭包job不可序列化](2026-08-14-APScheduler闭包job不可序列化-startup炸94errors.md) | TestClient 全量 94 errors | add_job 传方法内闭包，APScheduler 无法序列化 callable（实现层） | chat_proofread_job 提升模块级函数（683e559） | add_job callable 必须模块级可导入；startup 挂载后必跑全量回归 |
| 2026-08-19 | [T-948群聊快照全量0字节](2026-08-19-T-948-群聊快照全量0字节-CLI契约漂移.md) | 人工介入区「原文加载中…」永续；8 个快照全 0 字节但同步报成功 | sync_chat 读 data.items 而实为 data.messages 等四处字段漂移 + 0 条仍写空文件计成功（实现+测试双缺口） | T-948 chat_store 重写（111ef29）：真实契约快照 fixture + 0 条不落盘 + chats_empty 诚实计数 | 跨进程消费方 mock 必须复用实测契约快照（feishu_cli_contract.py）；先实跑 --format json 再对代码；空结果显式呈现 |
| 2026-08-19 | [T-955b AI分类500与图片附件不可用](2026-08-19-T-955b-AI分类500与图片附件不可用-契约错位.md) | 重新AI分类500；图片全部加载失败；附件点击无响应；自动聚类产出恖为 0 | LLMClient.chat 返回 tuple 而聚类层按 dict 消费 + 图片下载臆造 docs --media-key flag（聊天图应走 im 通道）；mock 自证第三案 | _llm_content 适配层接入 cluster/draft/regen + fetch_image_by_key 改 (message_id, media_key) im 通道（真实 M3 验证产出 2 话题段） | LLM 消费统一经适配层不裸消费；CLI 先实测 --help；跨边界 mock 形状禁按消费代码反推 |
| 2026-08-20 | [git对象库清空-提交链丢失与分支ref消失](2026-08-20-git对象库清空-提交链丢失与分支ref消失.md) | `git status` 报 bad object HEAD；fsck missing blob×31；未推送提交链（T-948→T-955b）对象永久丢失 | `.git/objects` 被整体清空（触发机制不可考，reflog 已毁）+ 并行会话删分支 ref（环境/仓库基建） | fetch 拉回远端历史 + hash-object -w 重建暂存 blob + update-ref 重建分支 + write-tree 复活 cache-tree（36f8108 恢复性入库） | 提交即推（远端是唯一提交细节备份线）；fsck/count-objects 例行自检；四步恢复路径速查；多会话优先独立 worktree，破坏性 git 操作互斥 |
| 2026-08-23 | [话题列表搜索/排序看似未生效](2026-08-23-话题列表搜索排序看似未生效-同id双份key撞车.md) | 搜索「BUG」计数 18→4 但列表卡片不滤不排；9 话题渲染成 18 张 | 已确认话题双存（_topics.yaml + facts）致 candidates/confirmed 同 id 双份 + 列表 key 撞车撕裂渲染（实现层） | dedupeTopics 前端去重（与页头 byId 同口径）+ FeishuPool 去重收敛；同单落地标签筛选（collectKeywords+tags AND），vitest 83→92 | 拼接多数组进列表前必按 id 去重；计数与列表须消费同一派生数组；「控件不生效」先查 duplicate key；后端 confirmed 遗留重叠另立任务退役 |
| 2026-08-23 | [M系列代码升级-全库扫描检查单](2026-08-23-M系列代码升级-全库扫描检查单.md)（类型二·模式扫描类） | 非单点事故：M-A~M-F 升级（T-960~T-1000）16 类问题代码模式提炼 | 依赖装配（sys.path 回潮/反向 import/shim 打桩/Path 层数/私有名）+ 解耦凭据 + 测试校验口径 + 服务层卫生 + 前端验收 | 每条附扫描命令+通过标准+当日实测基线；附一键复扫整段 | 全库定期扫描/评审新代码先查此单；当日实测另抓出 3 项漂移待办（F1 sys.path 冗余×10 / F2 回边白名单缺 2 条 / F3 _shared SSO 明文默认密码待拍板） |
| 2026-08-24 | [T-1012 授权缺权限误报](2026-08-24-T-1012-授权缺权限误报-scope命名两源不一致.md) | 授权全部完成仍黄条「已绑定但缺 1 项权限」，重新授权无效 | _REQUIRED_SCOPES 首项照抄网关报错文本 contactuser:search，与 auth status 授权清单官方名 contact:user:search 字符串比对永不命中（实现层） | 改官方名（45a661e）+ TDD 回归用实测原始名钉死；真实工号 missing 归零 | 比对名单取值必须与比对对象同源（报错文本≠清单名）；「重新授权仍报缺」先持 token 直调 API 证伪；新 scope 先实跑 auth status 取原始名 |
| 2026-08-24 | [T-1011 specflow_dir空emp回退私有区](2026-08-24-T-1011-specflow_dir空emp回退私有区-共享话题库不可达.md) | 共享话题库有数据 agent 却答「话题库是空的」（验收 FAIL） | specflow_dir("") 空 emp 回退请求上下文工号恒解析私有区（目录解析层，同 T-014 reports_dir 事故形态） | specflow_dir 补 force_shared（镜像 specguard_dir）+召回层强制共享区+根因回归测试×4（修复前必红已反证） | 天然共享产物目录解析必须 force_shared=True；测试须覆盖「emp 上下文+生产解析路径」；T-949 存量面同根因波及另立任务 |
| 2026-08-24 | [MCP合并工具action参数名碰撞](2026-08-24-20260824_144100_41c23c7c-MCP合并工具action参数名碰撞.md) | spec(action=sync) 报「未知 action: 空」×3，拉取最新 spec 不可用；scenario(action=edit) 同根因潜伏 | T-982 合并层 pop 消费 action 后委派，而 legacy 工具 sync_workspace/edit_dependency 自带业务参数同名 action（工具收敛设计层，同名冲突未检查）；合并 schema 同名属性被挤掉且 dismiss 能力丢失 | ActionMeta.params 注入机制 + spec 拆 sync/dismiss 双 action + edit_dependency 参数 action→op 双读兼容 + 合并面回归测试×6（TDD 先红后绿） | 新增合并 action 必查 legacy schema 同名参数（固定语义 params 注入/多值语义改参名）；合并面必须有直连测试（legacy 通道不覆盖）；收敛收尾全库同名参数扫描 |
| 2026-08-24 | [spec同步返回体膨胀50KB](2026-08-24-20260824_153425_a3d53352-spec同步返回体膨胀50KB.md) | spec(action=sync) 同步成功但返回 50KB+ 被会话层截断，路径前缀大量重复 | pull() 无条件附带全量 conformance 报告 + ANCHOR 重复消息绝对路径全量拼接且 message/detail 双份存储（实现层，无体量预算；多模块工作区 28 处 FR-001 触发组合爆炸）；附带修 detail 嵌套 bug | 锚点消息相对化+前 5 截断 + detail.files 相对化 + add() 消嵌套 + pull 摘要化（10 样本+omitted+指路）；实测 50000+→13846（瘦身 72%） | 面向 Agent 的返回体要有体量预算（附带信息摘要化+指路）；message 短给人/detail 全量给程序不双存；遗留：FR 全局唯一规则与 TDM 多模块本地编号错配待拍板 |
| 2026-08-25 | [工具成功被误标失败-error计数键子串误判](2026-08-25-20260824_172320_84d21cfa-工具成功被误标失败-error计数键子串误判.md) | spec(action=sync) 返回 ok:true + verdict:PASS，AgentChat 仍显 ❌ 执行失败 | 前端状态判定对结果原文做子串匹配，summary 里 `"error": 0` 计数键名命中 `'"error"'` 被误读为有错（实现层，共 3 处：单工具块/组hasError/组计数） | utils.ts 新增 isToolError 语义判定（ok→verdict→error值→文本兜底）+ ToolBlocks 三处替换 + 回归测试×5（首条即原始返回体，先红后绿）；vitest 106 全绿 | 工具状态判定必须走协议语义字段禁止原文子串匹配；复用 isToolError 不另写；排障先读 sessions/*.jsonl 原文对照，勿凭 UI 表象推断 |
| 2026-08-25 | [上传附件模型看不到-引用注入链路四环全断](2026-08-25-20260824_172320_84d21cfa-上传附件模型看不到-引用注入链路四环全断.md) | 两批上传均落盘成功，模型两轮均称「没看到附件」，还拿工具描述示例 ID 读到无关旧包 | 附件传递链路偏离业界模式（直接注入 user message）：info_pack 引用只关联不注入 + runtime 续会话丢弃重建的 system prompt + 前端 stale closure 发旧 scenario_id + 示例 ID 恰好真实存在，四环全断（设计层） | 四处修复：引用内容直接注入 <references> 块（上传即关联+截断保护）+ 续会话替换首条 system + ws.send 用同步 sid + 示例 ID 改 SG-META-XXXX；TDD 6 新测试+1 存量语义更新，test_specstd 1850 绿 | 轮次级附件数据不进 system prompt；React setState 后同步取值用本地变量；工具 schema 示例禁用真实 ID；会话 JSONL 检索 ID 命中位置可区分「没注入」与「注入了没读」 |
| 2026-08-25 | [引用chip发送后不清空-每轮重复注入](2026-08-25-20260825_151821_3178914e-引用chip发送后不清空-每轮重复注入.md) | 上传附件后输入区 chip 常驻，每条 user 气泡都带附件 chip，后端每轮重复读取注入 | ChatInput doSend 发送成功只清输入框不清 references state（实现层单点遗漏），与「引用随当轮消费」设计语义冲突 | doSend 成功时 setInput+setReferences 同清（发送被拒保留）；tsc 通过，77080cf | 「随消息消费」型局部状态发送成功路径必须显式清空；chip 常驻先查 state 生命周期勿先疑后端；后端 _process_references 无幂等，多轮复用语义应后端 sha 去重 |
| 2026-08-25 | [sess-db-aux验收三缺陷-白名单缺域/页签装配/守卫误判](2026-08-25-sess-db-aux-辅助会话验收三缺陷.md) | 辅助会话无 write_draft 工具（产出物链路断裂）；跳回 /agent 后 purpose 页签整体消失；注释头 SQL 被守卫误判非查询 | ①sql_assistant domains 漏 draft 域（设计层：提示词承诺与白名单自相矛盾）②purposes 只在新建/发送路径拉取，恢复路径不拉（T-932 既有缺陷暴露）③守卫正则未剥前导注释 | 2f7fd13 补域+断言 / 9860e05 _store缓存purposes+恢复补拉+竞态防护 / 0303bff 剥注释+3用例；复验全过已推远端 | 用途 domains 必须与提示词承诺工具逐条对照（resolve_tools 断言钉死）；跳回激活类功能必验 SPA 跳回路径；守卫判定考虑注释头变体；异步就绪前不得设置会被回落 guard 消费的状态 |
| 2026-08-26 | [试跑恒500-asyncio.run包同步函数](2026-08-26-试跑恒500-asyncio-run包同步函数.md) | 草稿试跑必败，前端只有「Internal Server Error」无异常信息；Agent 对话对试跑失败完全失明 | HTTP 端点 asyncio.run 包同步 handler 必抛 TypeError（K-046 引入从未成功）+ 试跑落盘面五件套全缺（run.json/cases/output.log/索引/run_id，工具链层双缺口） | 端点去 asyncio.run+兜底结构化错误；试跑落盘对齐 plan_executor（Tee output.log+report_writer+双索引+run_id 回传）；前端展示任务号；TDD×5 先红后绿，release_check PASS（待提交） | asyncio.run 只包协程（同步 handler 走 to_thread）；新增执行入口对照落盘五件套自查；端点未捕获异常必须兜成结构化错误；验收断言报告目录非空 |
| 2026-08-26 | [agent_20260826_112426 python原语三连败+试跑报告读写错位](2026-08-26-agent_20260826_112426-python原语三连败-试跑报告读写错位.md) | HI-PERM-001 试跑 NameError→AttributeError→TypeError 三连败；Agent 调 attribution 排查反被报「运行报告不存在」 | 试跑落盘写私有区/attribution 读共享区（工具链层，同 T-014/T-1011 根因形态第三发）+ format_spec §1.13 python/http 文档缺口 + HttpClient 无 json= 别名；第二次失败实为 Agent 臆造 404 端点（非 ns 结构） | T-1016 run_dir 统一 reports_dir + spec_baseline 波及面 force_shared；T-1017 format_spec 2.15.0 §1.13/§1.13.1 补全（未采纳事故报告错误写法）；T-1018 错误消息附 ns 键清单；T-1019 json= 别名 | 工作区级共享产物目录解析一律 force_shared；emp 维度读写对必须测「写后同口径读」闭环；Agent 事故报告结论须与落盘 saved_vars 对账后再采纳 |
| 2026-08-27 | [HI-PERM-004 404假象与SystemExit击穿进程](2026-08-27-EX-b9c359ba-HI-PERM-004-404假象与SystemExit击穿进程.md) | 草稿卡片「Internal Server Error」+ 查看结果显示老版本 404 报告，用户误判服务路由未修好；今早两次试跑 output.log 停在「步骤 python」且无 run.json | 三层叠加：searchVo PART+空值被服务端 400001 拒绝 + python 误用点号扁平键读 call 产出 + 脚本 raise SystemExit 裸穿 except Exception（BaseException）崩掉运行进程，报告索引全缺致 UI 回退老报告（引擎层 T-1022 修复主体） | step_python 与 _run_verifies 断言脚本补 except SystemExit 包装为场景编写错误并指路 SkipScenario（TDD 双测试）；场景侧 searchVo/嵌套访问/SkipScenario 三处修订；format_spec 2.15.1 | python 脚本终止只用正常结束或 raise SkipScenario；读 call 产出只嵌套访问（ns['名']['json']）；跨服务调用用 call 步骤 service 声明；「显示老报告」先查任务号产物完整性再定修复有效性 |
