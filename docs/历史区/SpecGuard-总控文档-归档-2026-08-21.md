# SpecGuard 总控文档 · 归档（2026-08-21 第二轮瘦身）

> 来源：总控文档 v1.30 归档瘦身（2026-08-21，sess-arch-breakdown，总控人指令）。
> 内容：v1.23~v1.28 决策记录、§4.8 GateDock（全部完成）、§4.9 飞书知识图谱（全部完成 T-910~T-930）、§4.10 已完成任务（T-931/T-932/T-937~T-952/T-955）、已完成会话注册（sess-gatedock-dev/sess-feishu-graph）、§6 非基准行历史登记。
> 第一轮归档（v1.1~v1.22 及打磨期/升级期主线）见《SpecGuard-总控文档-归档-2026-08-13.md》。

---

## 一、版本决策记录（v1.23~v1.28）

> **v1.28 决策（2026-08-17，sess-agentchat-material，总控人指令）**：两件事——① §4.9 补登 T-930「监听选择器+可读层」已 ✅（aefd802 后端 / e4633a2 前端 / b1d15ff 文档）：watch v2 用户维度（open_id+scopes：group_sender/minutes/docs）+ 群聊/用户/用户文档三选择器端点（CLI --filter owner_ids 实测不生效→应用侧过滤定案）+ 直写授权校验（修复全量落池隐患）+ 材料列表标题/摘要可读层 + 同步设置共享组件（入口移入材料池页）；② 新增 §4.10「AgentChat 材料工作流与 purpose 面板装配」支线（T-931~T-936，依据《远期设计/SpecGuard-AgentChat材料工作流与purpose面板装配专项设计.md》）——对话内材料上传+引用进面试上下文（read_material 工具）+ purposes.panels 消费（页签注册表通用/专用分层装配，解决选方向面板不变+防膨胀）；MaterialsPanel 瘦身为储备 T-936。
>
> **v1.27 决策（2026-08-14，sess-feishu-graph，总控人指令）**：§4.9 飞书知识图谱支线三期任务登记（T-924~T-929，依据《三期设计-多用户编排与演进追踪》+《三期实施计划》）——多用户监听编排（WatcherRegistry 配置驱动启停+软上限+状态落盘，二期单用户守卫退役）+ IM 事件直写（秒级，每日校对重拉兜底撤回/编辑）+ 话题演进链（LLM 判延续 continues→evolves 边）+ 确认可选入包（默认不勾不绕人拍板）。二期 T-917~T-923 已 ✅（6301847）。
>
> **v1.26 决策（2026-08-14，sess-feishu-graph，总控人指令）**：§4.9 飞书知识图谱支线二期任务登记（T-917~T-923，依据《二期设计-事件监听与智能增强》+《二期实施计划》）——采集层升级事件驱动常驻监听（FeishuWatcher 托管 3 路 consume，单用户守卫三态/5min 节流重拉/关 stdin 优雅停/退避重启）+ 视觉转述（增量自动+存量手动）+ 消息锚点自动焦点 + 文档日级轮询补位。一期 T-910~T-916 已 ✅（bb7d3d8）。**收口（2026-08-14）**：二期 T-917~T-923 全量交付（7580fc3 watcher / 5119dbe 接线 / 7189fd0 转述 / fddc272 自动焦点 / d3a6ea4 轮询）；全量 1564 绿 + release_check PASS + 前端 build 通过。
>
> **v1.25 决策（2026-08-14，sess-feishu-graph，总控人指令）**：新增 §4.9「飞书知识图谱（面试素材溯源）」支线（T-910~T-916，依据《远期设计/SpecGuard-飞书知识图谱设计-面试素材溯源.md》+《upgrade-plans/2026-08-13-飞书知识图谱一期实施计划.md》）——飞书材料（文档/妙记/群聊话题）经「拉取落池→LLM建议→人工复核→图谱派生」接入 graph_index，面试官 trace_backward 自带证据链。铁律：LLM 不写图谱（建议→人拍板→落盘事实源→确定性派生）；私有/共享双区隔离（未确认材料永不出私有区）；与 GateDock 并行采批次 A（纯新建）/批次 B（改现有代码）分拆防撞。批次 A ✅（commit 11220d3：12 新建文件 26 用例，全量 1409 绿）；T-913 派生段 ✅ 待 commit。**收口（2026-08-14）**：T-910~T-916 全量交付——批次 B 五笔 commit（af7fada 派生段+登记 / 1c89d14 接线 / 3e32e89 复核面板 / 98612da 焦点子图 / 0871641 网状镜头）；全量 1551 绿 + release_check PASS + 前端 build 通过；一期收口待笔 e2e+文档随本登记提交。
>
> **v1.24 决策（2026-08-13，sess-gatedock-dev，总控人指令）**：§4.8 GateDock 二期（T-901）+ 三期（T-902）全量交付——① MCP 只读工具 `gate_dock_status`（runtime 注入 `_session_id` 特权参数，RBAC 分级纯读）+ 前端 `gate-card`/`gate-exec` 围栏渲染（AgentChat 消息流内嵌可操作卡片，复用 GateCardView 组件）+ skills 推卡话术（gate-dock-guide.md，L1/L2/L3 分档接管）；② L3 代执行白名单硬编码（material_include/material_exclude/topic_confirm 三可逆低危 action），GateExecCard 用户确认才执行，白名单外确定性拒绝；③ 测试 MCP 6 例 + 全量 1399 全绿 + 前端 build + release_check PASS。
>
> **v1.23 决策（2026-08-13，sess-gatedock-dev，总控人指令）**：① **历史归档瘦身**——v1.1~v1.22 决策记录、打磨期（§4.1 四轮）、升级期已完成任务（S0~S8 主线/P-A 支路/引擎补点/知识体系/瘦身块）、历史会话注册与文件登记留痕，归档至《历史区/SpecGuard-总控文档-归档-2026-08-13.md》；总控文档仅保留活跃任务（进行中/未认领/储备）+ §6 登记中行与各文件最新基准行；② **新增 §4.8「对话操作台 GateDock」支线**（T-900~T-902，依据《远期设计/SpecGuard-对话操作台设计-GateDock.md》）：T-900 一期 ✅ 已完成（本会话交付，commit 23a4c60），T-901/T-902 未认领、与全部主线并行。
>

---

## 二、§4.8 对话操作台 GateDock（全部完成）

> 定位：材料管理/评分冻结/禅道集成三个人拍板面板的单条拍板动作收进 AgentChat「🎛 操作台」页签（GateCard 统一组件），菜单面板降级保留为管理/审计视图。
> 硬边界：**不新增 MCP 写工具**（禅道写铁律 1 不动）；**分档接管**——L1 引导全量兜底 / L2 预填（评分/冻结/禅道写永远人拍板）/ L3 代执行仅可逆白名单（材料入包/移出、议题确认），白名单扩缩比照冻结层评审。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-900 | GD-一期 | 操作台页签 + 只读汇总端点 + 分档卡片 | workbench 前后端（gate_dock_service / specflow_gate_dock / GateDockPanel / AgentChat SidePanel） | gate-dock 纯读汇总（session_id 经 sf_interviews 反查面试上下文）+ 五类卡片（议题确认/材料入包/评分确认/冻结三闸/禅道建故事）人拍板按钮直调原有 REST + 「🤖 帮我」L1 引导；菜单三面板零回退；测试 11 例 + release_check PASS | — | 已完成 | sess-gatedock-dev | P0 ✅ 2026-08-13（commit 23a4c60）：GET /api/specflow/gate-dock（纯读零写副作用，session_id/interview_id 双入参，未绑定面试返回空态）+ GateDockPanel（L3 档可逆卡绿色标签、L2 档人拍板黄色标签）+ AgentChat 操作台页签 + askAgentGuide（复用 askAgentFix 直发模式）；test_gate_dock.py 11 例全绿 + 63 回归 + 前端 build + release_check 全 PASS |
| T-901 | GD-二期 | 对话流主动推卡 + L2 参数预填 | AgentChat（gate-card 围栏渲染）+ mcp_server/tools/gate_dock + agent/runtime + agent/skills | MCP 只读工具 `gate_dock_status`（runtime 注入 `_session_id` 特权参数，RBAC 纯读分级）+ 前端 `language-gate-card` 围栏拦截渲染（复用 GateCardView 组件，操作台与消息内嵌共用）+ skills 推卡话术（gate-dock-guide.md，推卡时机表 + L1/L2 分档接管）+ requirement_interview 白名单加 gate_dock_status | T-900 | 已完成 | sess-gatedock-dev | P1 ✅ 2026-08-13：gate_dock_status MCP 工具（纯读零写副作用，side_effect 默认 none）+ runtime._execute_tool 注入 `_session_id`（下划线前缀防伪造）+ _RBAC_READONLY_TOOLS 加 gate_dock_status + server.py 注册 + AgentChat PreBlock gate-card 围栏拦截（GateDockCtx Provider）+ GateCardView 抽组件（GateDockPanel 瘦容器复用）+ gate-dock-guide.md skills（推卡时机表 + 围栏格式 + 分档话术）；test_gate_dock MCP 6 例 + 全量 1399 全绿 + 前端 build + release_check PASS |
| T-902 | GD-三期 | L3 白名单代执行 | GateCardView（GateExecCard）+ AgentChat gate-exec 围栏 | 白名单硬编码前端常量 `GATE_EXEC_ACTIONS`（material_include/material_exclude/topic_confirm，均可逆低危）+ `language-gate-exec` 围栏渲染 GateExecCard（确认/忽略双按钮，用户点「确认执行」才以用户身份调原 REST，RBAC 兜底）；白名单外 action 确定性拒绝（黄框提示）；评分/冻结/禅道写**永远停 L2** | T-901 | 已完成 | sess-gatedock-dev | P2 ✅ 2026-08-13：GateExecCard 组件（白名单校验→确认卡→执行→结果回显）+ GATE_EXEC_ACTIONS 三 action 硬编码（扩缩需评审）+ AgentChat PreBlock gate-exec 围栏拦截；白名单外 action 黄框拦截提示；与 T-901 共用同一前端 build + 测试 + release_check 验证批次 |


---

## 三、§4.9 飞书知识图谱（全部完成，T-910~T-930）

> 定位：飞书材料（文档/妙记/群聊话题）成为 graph_index 一等节点——LLM 出候选边（依据+置信度）→ 人批量复核 → 落盘事实源 → 确定性派生；面试官 trace_backward 自带素材证据链；双层视图（全景网状镜头 + AgentChat 焦点子图）。
> 硬边界：① LLM 不写图谱（只出建议，人拍板落盘才生效）；② 私有/共享双区隔离（未确认材料/原始群聊快照永不出 .specflow/{emp} 私有区）；③ 飞书侧只读红线；④ 图片走替身文本（imgmap 分离，纯文本模型透明）。

| 任务ID | 阶段 | 任务 | 模块 | 产出/验收要点 | 依赖 | 状态 | 会话ID | 备注 |
|---|---|---|---|---|---|---|---|---|
| T-910 | 图谱-地基 | 材料池落盘 + 事实源读写 | specflow/feishu_pool（paths/pool_store/facts） | 私有区三通道快照（fd/fm/群×天）+ sha256-12 指纹 + imgmap 分离；共享区 topics.yaml/material_links.yaml 排序写入幂等覆盖；6 用例 | — | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 11220d3） |
| T-911 | 图谱-提炼 | LLM 话题聚类 + 建边建议 + 替身文本 | specflow/feishu_pool（topic_cluster/link_suggest/captions） | 话题增量归并保 id 稳定（图谱不依赖 LLM 复现）；三重防幻觉（锚点存在性/evidence 子串/rejected 过滤）；替身文本拼装纯文本模型透明；10 用例 | T-910 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 11220d3） |
| T-912 | 图谱-采集闸门 | 拉取入库 + 复核服务 | lark_cli + feishu_sync_service + feishu_review_service + routers/feishu_pool | watch 配置即显式授权载体；三通道只读拉取（错误诚实入 errors）；复核队列 emp 隔离；确认提升共享区/拒绝工作区留痕；invalid 不可确认；10 用例 | T-911 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 11220d3；路由文件新建未挂 main.py，挂载在 T-914） |
| T-913 | 图谱-派生 | graph_index 飞书派生段 | graph_index store/builder/service | feishu_doc/feishu_minutes/topic 节点 + mentions 边（仅 confirmed、断链不建边）；共享区事实源纳入 source_fingerprint；backlink 增 mentioned_by；3 用例 + 删库重建一致性回归全绿 | T-912 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（32 用例全绿，待 commit） |
| T-914 | 图谱-接线 | main.py 挂路由 + feishu_fetch 复用切换 | workbench main.py + mcp_server/tools/feishu_fetch.py | feishu_pool 路由挂载（watch/sync/复核五端点生效）；feishu_fetch 改 import specflow.feishu_pool.lark_cli（29 用例回归） | T-912/T-913 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（commit 1c89d14：main.py import+include_router 挂载；feishu_fetch 内联封装删除改 import；test_non_win_command_prefix 等 2 例 patch 目标随迁移修正；44 用例全绿） |
| T-915 | 图谱-呈现 | 复核面板 + 双层视图前端 | MaterialsPanel/api.ts/AgentChat/GraphPanorama + graph.py（focus/network） | 材料页签关联复核面板（置信度条+批量确认/拒绝）；/api/graph/focus N 跳子图 + AgentChat 侧栏；全景第 4 镜头网状（elkjs 力导向零新增依赖，500 节点护栏） | T-913 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（三笔：3e32e89 复核面板 FeishuReviewPanel + api.ts；98612da focus_subgraph 端点 + AgentChat「◎ 图谱」页签 FocusGraph；0871641 network_view + elk force 网状镜头 NetworkGraph + GraphPanorama 第 4 镜头；35 图谱用例全绿 + 前端 build 通过） |
| T-916 | 图谱-收口 | e2e 贯通 + 发布门禁 | 全链路 | mock e2e（同步→聚类→建议→确认→建图→子图）；真实环境面试官链路验证；全量回归 + release_check 全 PASS；设计文档状态已实施 | T-915 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14：test_e2e_pipeline 六段贯通（mock lark/LLM：同步→聚类→建议→确认→build_index→focus_subgraph 含 fd/tp 节点与 mentions 边）；全量 1551 用例全绿 + release_check 全 PASS；设计文档 v1.1 已实施（§5.3 rejected 口径修订为共享区留痕） |
| T-917 | 图谱二期-监听 | watcher 骨架（单用户守卫） | services/specflow/feishu_watcher.py | 扫描 .lark-cli/{emp}×watch 配置×token 有效；0 静默/1 启动/>1 告警不启动（二期单用户边界）；3 用例 | T-916 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（7580fc3：守卫三态 3 用例） |
| T-918 | 图谱二期-监听 | watcher 核心（节流/恢复/优雅停） | feishu_watcher.py | 3 路 consume 托管（IM bot+minutes/vc user）；stdin PIPE 保活+stderr ready 阻塞就绪；5min 节流合并→复用一期 sync 重拉；指数退避重启（连续 5 次停摆告警）；关 stdin 优雅停禁 kill -9；3 用例 | T-917 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（随 7580fc3 入库：节流合并/优雅停/退避重启 3 用例） |
| T-919 | 图谱二期-接线 | main.py 挂载 watcher | workbench/backend/main.py | startup 启动（守卫静默跳过）+ shutdown 优雅停；start/stop_background 幂等；import 冒烟 | T-918 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（5119dbe：251 routes + 幂等 2 用例） |
| T-920 | 图谱二期-转述 | 图片视觉转述实装 | captions.py + feishu_pool 路由 + FeishuReviewPanel | vision model_id 未配置全链路跳过；增量落池自动转+存量面板手动转；下载/模型失败落 failed 诚实呈现；3 用例 + 前端 build | T-916 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（7189fd0：transcribe_images 实装 + POST /transcribe + 面板🖼按钮） |
| T-921 | 图谱二期-焦点 | 消息锚点自动焦点 | utils/focusAnchor.ts + FocusGraph/AgentChat | 最近消息最后提及锚点（FR/AC/tp/fd/fm）自动渲染；手动输入优先可覆盖；tsc build 通过 | T-916 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（fddc272：extractLastAnchor 纯函数 + FocusGraphTab messages 接线） |
| T-922 | 图谱二期-轮询 | 文档日级轮询补位 | feishu_sync_service.sync_recent_docs + watcher 挂 job | drive +search --edited-since 1d ∩ watch.docs 授权清单交集落池（未授权不进池）；APScheduler 每日 job 不落 jobs 表；1 用例 | T-919 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（d3a6ea4：交集过滤用例 + watcher cron 挂载） |
| T-923 | 图谱二期-收口 | e2e + 发布门禁 | 全链路 | 事件 NDJSON→节流→重拉→聚类→建议入队全 mock 贯通；全量回归 + release_check PASS；设计 v1.1 已实施 | T-918/T-920/T-921/T-922 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14：test_e2e_event_to_review_queue 贯通（事件→节流一次重拉→落池→聚类→建议 pending 入队）；全量 1564 绿 + release_check PASS；设计 v1.1 |
| T-924 | 图谱三期-编排 | 多用户监听注册表 | feishu_watcher.py + feishu_pool 路由 | WatcherRegistry（{emp: watcher} 内存表+watchers.json 落盘）；配置驱动启停（保存 watch 拉起/删除停）；软上限 50 告警；二期单用户守卫退役为 resolve_watch_users；4 用例 | T-923 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（f3b4315：注册表 4 用例 + PUT watch 联动 + 注册表常驻创建） |
| T-925 | 图谱三期-直写 | IM 事件直写+校对重拉 | pool_store（append_chat_lines/去重/发送人缓存）+ watcher 分流 | IM 事件内容直写快照（秒级，event_id 去重 7 天 TTL）；发送人 open_id→名缓存（失败尾 6 位）；每日 03:00 全量校对覆盖（撤回/编辑/丢漏对齐飞书侧）；minutes/vc 保持节流重拉；3 用例 | T-924 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14（b306be1：直写 4 用例 + throttle 用例改直写语义；APScheduler 闭包 job 教训→模块级 chat_proofread_job） |
| T-926 | 图谱三期-演进 | 话题跨天演进链 | topic_cluster + facts + graph_index（store/builder/service） | 聚类 prompt 注入近 7 天同群话题清单，LLM 判延续出 continues；防幻觉校验（continues 须在清单）；graph_index 加 evolves 边+trace 上游追溯；3 用例 | T-923 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（23241d6：evolves 上游方向 dst 修正，55 用例） |
| T-927 | 图谱三期-入包 | 确认可选入包 | feishu_review_service + FeishuReviewPanel + api.ts | confirm 响应带 suggest_ivs（FR∈进行中面试议题范围）；前端弹层勾选默认不勾；勾选=确认+入包两动作一次人拍板（走 M03 原端点不新增写通道）；2 用例 + build | T-923 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（169dd76：_find_active_ivs_for_fr + 弹层默认不勾） |
| T-928 | 图谱三期-收口 | e2e + 发布门禁 | 全链路 | 多用户事件→直写→校对→聚类（continues）→确认（suggest_ivs）全 mock 贯通；全量回归+release_check PASS；设计 v1.1 | T-924~T-927/T-929 | 已完成 | sess-feishu-graph | P0 ✅ 2026-08-14：test_p3_e2e_pipeline 贯通（多用户注册表→直写→continues→evolves+mentions 同图→suggest_ivs）；全量 1618 绿 + release_check PASS |
| T-929 | 图谱三期-总览页 | 飞书材料池总览页（2026-08-14 用户指示并入） | FeishuPool.tsx + feishu_pool 路由（3 只读端点+caption 更新）+ rbac_store 菜单种子 + api.ts | 状态卡条（watcher 运行/事件数/最近事件）+ 三页签：材料池清单（sha/mtime/预览）·话题清单（候选/已确认/continues 链）·图片（pending/failed + caption 手改保存）；3 端点用例 + build | T-924 | 已完成 | sess-feishu-graph | P1 ✅ 2026-08-14（e409c82：三页签 + watcher 状态卡 + menu-feishu-pool 种子/迁移） |
| T-930 | 图谱三期后-监听选择器 | 监听选择器+材料可读层（2026-08-17 用户验收反馈） | feishu_sync_service/watcher/feishu_pool 路由 + FeishuWatchSettings 共享组件 + FeishuPool/FeishuReviewPanel + api.ts + docs/superpowers | watch v2 用户维度（users[].open_id+scopes 枚举归一化）；群聊/用户/用户文档三选择器端点（docs +search --filter owner_ids 实测不生效→应用侧 owner 过滤，空 query 可用）；直写授权校验（chat ∈ watch.chats + group_sender 发送人过滤仅直写，修复全量落池隐患）；用户妙记/文档每日 08:00 轮询 job（模块级函数）；材料列表 title/summary 可读层（minutes title+artifacts.summary/docs 首行标题/chats 群名+首行）；同步设置抽共享组件入口入材料池页；11 用例 + build + release_check PASS | T-924/T-929 | 已完成 | sess-agentchat-material | P0 ✅ 2026-08-17（aefd802 后端 / e4633a2 前端 / b1d15ff 设计+计划；docs/superpowers/specs+plans 落盘；用户复验收口） |


---

## 四、§4.10 已完成任务（T-931/T-932/T-937~T-952/T-955）

| T-931 | 装配-对齐 | purposes panels 值对齐真实页签 id | agent/purposes/*.md + test_purpose.py | 两 purpose md panels 改 [pack,focus,materials]/[deps,history]（旧值入储备注释）；loader 解析+端点透出断言 | — | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-17（42c851a：test_panels_values_align_tab_registry 用例 + 102 绿） |
| T-932 | 装配-前端 | SidePanel 页签注册表 + purpose 装配 | AgentChat.tsx | TAB_REGISTRY 通用/专用分层；选测试方向 pack/focus/materials 隐藏、deps/history 保留；未声明 panels 仅通用集（兼容）；活动页签被隐藏回落待办；build | T-931 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-17（42c851a：SIDE_TABS 注册表 + purposePanels prop + 隐藏回落 useEffect；materials 页签随 T-933 补注册表行即生效；顺手修复 test_reference_envs patch 点——多系统改造后保存走 _env_file/_SYSTEMS_ROOT，旧 SYSTEMS_TDM patch 失效曾致真实 env.sit.yaml 被覆盖，已 git checkout 恢复+patch 点迁移+mtime 守卫验证） |
| T-937 | 体验修复 | 同步设置体验：弹层秒开+去 ID 手填+链接解析 | 同步设置前后端 | 依据《superpowers/specs/2026-08-18-同步设置体验修复-design.md》：①弹层立即渲染+数据并行填充；②list_my_chats 60s TTL 缓存；③群聊/文档手填 textarea 删除（失败重试/裸 token 透传兼容）；④文档用户下拉改搜索框+快捷标签；⑤resolve-doc 端点（docx 本地解析/wiki node-get 取 obj_token+title；实测定案：非 wiki 文档 node-get 404 需分流） | T-930 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（17 绿含 9 新用例；真实 wiki 链接端到端验证 obj_token+title 返回；release_check PASS；前端 build/oxlint 0 error） |
| T-938 | 体验修复 | 群聊列表后台预热：弹层打开秒出 | watcher + lark_cli + sync 服务 | ①chats_warmup_job（interval 5min + 启动即预热）；②list_my_chats 改 stale-while-revalidate（有缓存立即返，过期返旧值+stale 标记+后台刷新线程）；③_run_lark 加可选 emp 参数（USERPROFILE=.lark-cli/{emp} 注入，修多用户身份共享隐患） | T-937 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（78 绿含 5 新用例；真实环境实测：首次 CLI 6.2s→缓存命中 0.0000s/stale 0.0004s+后台刷新闭环；release_check PASS；顺手修 lark_cli B904×3+watcher SIM105+测试文件 E741/F401×2/I001×2） |
| T-939 | 体验修复 | 材料原文查看+图片直出：点材料看原文，图片内嵌展示 | 材料池前后端 | ①GET /material-content（docs/chats 原文，minutes 可读化+raw；附 imgmap）；②GET /material-image 代理（media_key→docs +media-download 复用 captions._download_image +磁盘缓存）；③前端详情弹层 react-markdown 渲染+[图片#N]替换内嵌图；④「图片替身」页签重构「图片描述」卡片流（缩略图+状态+描述编辑），删手输 stem/占位符编辑器；文案人话化（替身文本→图片描述） | T-938 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（27 绿含 7 新用例 + 补丁 1c90b83：list_pool_materials 的 file 改带目录前缀相对路径——裸文件名致详情弹层全部报非法路径，用户实测反馈 5 分钟闭环；TestClient 端到端冒烟全通；前端 build+oxlint 0 error；顺手修 feishu_pool I001×3+B904） |
| T-940 | 体验修复 | 监听用户视图+材料按人切换+飞书原文直链 | 材料池前后端 | ①落盘 meta sidecar（fd/fm-*.meta.json：owner_open_id/owner_name/source_url/title；owner 由 sync 调用方已知，minutes +search 实测无结构化 owner_id 仅 meta_data.app_link）；②list_pool_materials 返 source_url/owner；③前端监听范围卡（watch users×scopes/授权群/文档数+就近维护入口）；④材料清单按监听用户下拉筛选（产出物归人，群聊不归人）；⑤行内主行动「飞书原文↗」外链，本地快照降为次要（用户不信任 JSON 快照真实性） | T-939 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（76 绿含 4 新用例：meta sidecar/单 owner 落盘/list 返 meta+sidecar 不当材料；前端 build+oxlint 0 error；release_check PASS；存量材料无 meta 诚实降级空串，重新同步即有归属） |
| T-941 | 体验修复 | 同步设置去重+授权错误人话化+文档搜索解耦 | 同步设置前后端 | ①删监听范围卡内同步设置入口（T-940 误加，嵌套致弹层变小窗；只留右上唯一入口）；②missing_scope 错误识别包装（人话前缀+透传修复命令，实测缺 contactuser:search）；③新增全局文档名搜索 search_docs/docs-search 端点（不过滤 owner，与按用户检索两条独立路径+粘贴链接解析共存） | T-940 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（80 绿含 4 新用例：全局搜不过滤 owner/空 query 短路/missing_scope 包装/选择器 errors 人话化；build+oxlint 0 error；release_check PASS；注：群聊/用户加载失败根因是飞书 token 缺 scope，需按错误内 hint 重新授权——代码侧已人话化透传） |
| T-942 | 体验修复 | 授权闭环接入同步设置弹层（用户接触不到服务器） | 同步设置前端 + 错误文案 | 复用既有链路（lark_binding REST 五端点/larkApi/LarkAuth do_login 两阶段+segno 二维码）：①弹层内嵌授权块——未绑定→「绑定飞书」/缺权限→「重新授权（--domain all 全域）」；②弹层内展示二维码+链接+3s 轮询 complete→完成后自动重载群聊；③_friendly_lark_error 文案改指向弹层内操作（不再让用户去部署机执行命令） | T-941 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（补丁链：d88dff9 按钮渲染兑底；6d15c70 根因修——settings/lark 端点被菜单 RBAC 拦 403 且 router 从未挂载 main→ auth 三端点迁 feishu-pool 前缀；1ff3805 完成检测三轮修——轮询改递归 setTimeout（setInterval 3s×complete 阻塞 15s 堆积请求）+「我已完成授权」手动检测按钮（checkAuthOnce 共用）+ CLI pending 语义识别（authorization_pending 不再误判 error）；313e8b5 顺手修 lark_auth 存量 lint B904×3+SIM105；端到端验证 login 真实返回 url+二维码） |
| T-943 | 体验修复 | 授权审核状态可感知（首次授权部分 scope 需管理员审核） | lark_auth + 同步设置前端 | 实测定案：auth status 真实结构 identities.user.scope 为空格分隔字符串（旧 do_status 读不存在的 data.scopes→身份/scopes 恒空，顺手修）；①_REQUIRED_SCOPES 九项清单（contactuser:search/im:chat:read/docs/minutes/wiki/drive）→ status 返 missing_scopes；②授权完成打点 last_auth.json，30 分钟内仍缺→reviewing=True（审核中）；③前端三态：绿点正常/黄点「N 项权限管理员审核中+审核通过后点此刷新」/黄点缺权限+重新授权 | T-942 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（50 绿含 4 新用例；补丁 886155b：用户问「群聊和查人是否都在审核」→实测仅 contactuser:search 缺失（审核中），群聊等 8 项已生效；群聊空列表真凶是 CLI 1.0.85 双 bug——--types 逗号多值报错→拆两次调用、响应字段 data.chats 非 items→兼容解析，真实环境 400 群成功拉出） |
| T-944 | 体验修复 | 同步设置分 tab+群聊快速加载（先 10 群秒出+本地搜索+去单聊） | 同步设置前后端 | ①弹层分三 tab（授权群聊/监听用户/监听文档，计数徽标；授权块/保存栏常显）；②群聊先加载最近活跃 10 群（/chats?limit=N 快速路径单页不翻页不碰缓存，实测 0.93s vs 全量 5.66s），前端后台双请求全量补齐；③群名前端本地搜索（全量到后覆盖全部，未到时提示「拉取全部」）；④单聊不显示不拉取（全量耗时减半，T-938 的 p2p 置灰方案退役） | T-943 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（54 绿含 quick-limit 用例；build+oxlint 0 error；实测 0.93s/10群 vs 5.66s/200群；顺带 .gitignore 补 .specflow/ 9561901） |
| T-945 | 链路闭环 | 同步后自动聚类生成候选话题（为 Agent 对话供上下文） | sync 服务 + watcher | 用户实锄链路断点：群聊落池✅→聚类❌（cluster_chat_snapshots 生产零调用→话题恒 0）→复核✅→图谱✅→Agent 消费部分✅；修复：①sync_all 尾部+每日校对 job 后异步触发 maybe_cluster_async（daemon 线程，text 模型未配置诚实跳过与 vision 同模式，异常吞掉记日志）；②同步完成提示「话题生成中」 | T-944 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（71 绿含 4 新用例：无模型跳过/有模型调用/异常吞掉/sync_all 触发；Agent 侧 read_material 工具仍为 T-934 储备） |
| T-946 | 链路闭环 | 话题分阶段生成+时效窗口+按群配置+原文关联审核 | topic_cluster + sync 设置 + 话题页 | 用户需求四点：分片（按群×天逐文件单 LLM 调用本就分片）+时效（default_days 近 N 天过期不提取，库 0=不限兼容，业务默认 7 控 LLM 成本）+按群区分（watch.chats[].topic_days，0=关闭；同步设置勾选行「话题 N 天」输入，保存携带回显）+原文关联（话题卡片「查看原文」展开：拉快照全文按 window 起止 HH:MM 切消息片段，审核直接对照原始记录；source+window 字段一期已备） | T-945 | 已完成 | sess-agentchat-material | P1 ✅ 2026-08-18（80 绿含 3 新用例：窗口过滤/显式关闭/per-chat 覆盖 default；build+oxlint 0 error；顺手修 _next_seq SIM105） |
| T-947 | 流程增强 | 话题人工介入工作流（自动直出保留+介入口子） | topic_cluster + 话题页（待开发） | 用户最终决策：自动直出保留（T-945 链路不变），新增三阶段介入工作区作为修正路径——①原文先行（选群×天拉原文左侧展示）②LLM 只出分段草案（_topic_drafts.yaml，不动候选）③勾选接受段→生成卡片覆盖该群该天旧候选；单卡编辑（title/summary）与重生成（id 稳定）；详见《upgrade-plans/2026-08-18-T947-话题人工介入工作流-开发任务.md》（自包含，新会话可直接开发） | T-946 | 已完成 | sess-t947-dev→验收 sess-agentchat-material | P1 ✅ 2026-08-18（开发 2bd0326 feature/T-947；验收五项全过：106 绿含 5 新 TDD 用例、E2E 冒烟 draft→commit覆盖→edit部分改→regen id稳定、无模型 400 不 500、build+oxlint 0 error、release_check PASS） |
| T-948 | 存储重构 | 话题存储重构与协作加工·一期（存储+话题模型，T-949 共享化/T-950 前端工作台待开） | chat_store(新)+topic_cluster+sync+watcher+路由 | 根因驱动：群聊快照全量 0 字节（data.items vs data.messages 四处契约漂移，经验包已登记）；设计拍板五决策（JSONL 事实源+md 派生/按天拉取 chat_days 窗口补拉/话题 schema v2 状态制/agent_origin 原稿保存/乐观锁+编辑历史）；详见《upgrade-plans/2026-08-19-T948-话题存储重构与协作加工-设计文档.md》 | T-947 | 已完成 | sess-t948-dev | P1 ✅ 2026-08-19（feature/T-948；契约快照 fixture 纪律 feishu_cli_contract.py；test_specstd 1564 绿+engine 183 绿+release_check PASS；新增 chat_store JSONL 幂等合并/md 派生/imgmap、_topics.yaml 状态制+keywords/author/rev/agent_origin+历史 JSONL、/topics/history\|confirm\|reject + /chat-messages 端点、聚类 pv2 msg_lines→message_ids） |
| T-949 | 共享化 | 材料池全通道共享（方案 A）+飞书权限可见性 | sync/watcher/topic_cluster/路由/lark_auth/facts | T-948 设计 D2 拍板：material_base 参数化（快照/话题库/历史落 {ws}/.specflow 共享区，watch/草案留私有）；docs/minutes 权限元数据拉取（drive +member-list/get-setting 落 perm meta，missing_scope 实测容忍不阻断）；可见性过滤（chat 全员/owner/perm 用户群授权/public，perm 缺失保守仅 owner）；confirm/reject 联动 facts 图谱；存量迁移 migrate_legacy_pool（sync 前幂等）；_REQUIRED_SCOPES 补 2 个权限 scope（用户需重新扫码授权） | T-948 | 已完成 | sess-t948-dev | P1 ✅ 2026-08-19（feature/T-948；test_specstd 1581 绿+engine 183 绿+release_check PASS；新增 test_feishu_t949_shared 15 用例；AGENTS.md 授权语义升级登记；遗留：前端材料列表 perm 徽标/补授权引导在 T-950） |
| T-950 | 前端工作台 | 话题工作台重构（双栏+泳道色卡+状态制交互） | TopicWorkspace/TopicCard(新组件)+FeishuPool+api | 设计 §6 全量落地：①双栏工作台（左消息时间轴 JSONL 精确渲染+右话题泳道色卡，window 重叠分 lane 色相环取色，hover/点击联动高亮 message_ids 优先/window 兑底+滚动定位）；②TopicCard 增强（状态徽标/✓确认/✕拒绝/编辑含 AI 原稿对照差异标黄/重生成/历史抽屉多用户留痕/409 提示后刷新）；③候选双列表退役→单卡片流+状态筛选；④材料列表 perm 缺失「需补授权」徽标；⑤空态修复（原文加载中 vs 快照为空区分） | T-949 | 已完成 | sess-t948-dev | P1 ✅ 2026-08-19（feature/T-950 提交 45e3c2f；FeishuPool 812→瘦身组件化 3 新文件；tsc 0 错+build 成功+oxlint 8 errors 基线持平零新增+vitest 12 绿+knip 新增项清零） |
| T-951 | 补丁包 | 用户实测反馈四项：模型接入/布局收敛/MiniMax 兕底/跨天话题 | TopicWorkspace/TopicCard/api/llm_client/model_config/topic_cluster | ①话题页签单一双栏（卡片流并入工作台右栏+状态筛选 chips，页签不再分上下两层）；②MiniMax-M3 接入：OpenAI 兼容端点零适配直配（base_url=https://api.minimaxi.com），LLMClient 出口 _strip_think_tags 兕底（M3 thinking 默认开启混入 think 标签）；③模型用途别名（get_model text/vision 按 name 回退——设置页建模型 name 填 text/vision 即绑定，修「设置页模型永远无法命中用途链路」缺口）；④T-951c 跨天话题：介入工作台多日窗口（日期下拉近3/7天=最近 N 个有快照日；_load_window_source 多日 JSONL 拼接行带 MM-DD 前缀，msg_lines 跨日锚定，window 取真实 ts，卡片 days 字段；commit 清理窗口内各日旧卡；regen 跨日拼接重提炼；prompt 明确「跨天延续讨论聚为同一话题段」） | T-950 | 已完成 | sess-t948-dev | P1 ✅ 2026-08-19（4 提交至 b2a6bbd；test_specstd 1589 绿含 4 新多日用例；tsc 0 错+build 成功+oxlint 基线持平；自动聚类链路保持按天分片控成本，跨天聚合走介入口） |
| T-952 | 体验收敛 | 聊天真实内容渲染+单群更新+定时同步+多模态透明化（图片tab退役） | chat_store/sync/watcher/路由/TopicWorkspace/FeishuPool/FeishuWatchSettings | 用户反馈四点：①post/file 消息渲染真实内容（实测契约：post=markdown 文本+![Image](key) 内嵌多图，file=<file key name/> 自描述——normalize 提取 image_keys/file_name，MessageBody 富渲染：post 文本+内嵌图缩略+转述 caption、file 文件卡、image 图；图片按 media_key 直取端点 /chat-image 与 imgmap 解耦）；②单群更新（sync_all chat_id 过滤+工作台「↻更新本群」按钮秒级反馈）；③定时同步可配置（watch.chat_sync_minutes，watcher interval job，同步设置弹层输入框，0=关保留每日校对）；④多模态技术对用户透明（同步后自动触发图片转述 maybe_transcribe_async，图片描述独立 tab 退役——caption 融入时间轴展示，转述是技术侧实现细节不应作为用户操作面） | T-951 | 已完成 | sess-t948-dev | P1 ✅ 2026-08-19（4 提交至 bd10c30；契约固化 POST_MESSAGE/FILE_MESSAGE；test_specstd 1598 绿+release_check PASS；tsc 0 错+build 成功+oxlint 基线；遗留：caption 内联编辑入口后续补——当前展示已有，编辑暂经详情弹层） |
| T-955 | 排版打磨 | 消息时间轴排版五项优化（用户实测反馈） | TopicWorkspace/MessageBody/api/feishu_sync_service/路由 | ①两行制排版（头行「昵称·时间」+正文独立行，昵称按 sender 哈希稳定配色 IM 惯例）；②时间格式 MM-DD HH:MM（去 ISO T）；③图片三态（加载中/失败/成功，失败显式红框提示不再永「加载中」；成功可点击新标签大图）；④附件可下载（im +messages-resources-download，fetch_chat_file 磁盘缓存，GET /chat-file 附件流，卡片点击即下载）；⑤长操作耗时提示（busy 时 elapsed 秒数实时刷新：「分类中… 12s」） | T-954 | 已完成 | sess-t948-dev | P1 ✅ 2026-08-19（提交 46a8933；tsc 0+build 成功+oxlint 基线+test 44 绿+release_check PASS） |

---

## 五、已完成会话注册（原 §5）

| 会话ID | 角色/方向 | 认领任务ID | 开工时间 | 备注 |
|---|---|---|---|---|
| sess-gatedock-dev | GateDock 对话操作台施工 + 总控 v1.23/v1.24 归档编排 | T-900 + T-901 + T-902 + 归档瘦身 | 2026-08-13 | T-900 一期 ✅（commit 23a4c60）→ T-901 二期 ✅ + T-902 三期 ✅（MCP 工具 + 围栏渲染 + 白名单代执行 + skills 话术）；总控 v1.23 归档瘦身 + v1.24 二三期完成收口 |
| sess-feishu-graph | 飞书知识图谱施工（面试素材溯源） | T-910 ~ T-923（一/二期✅）→ T-924 ~ T-929（三期✅） | 2026-08-14 | 一期批次 A/B + 二期事件监听/转述/自动焦点/轮询全量收口；三期多用户编排/直写/演进链/入包收口 |

---

## 六、§6 非基准行历史登记（各文件仅留最新基准行于主表）

| 文件路径 | 会话ID | 登记时间 | 修改前hash | 修改后hash | 状态 | 备注 |
|---|---|---|---|---|---|---|
| workbench/backend/services/specflow/feishu_sync_service.py | sess-agentchat-material | 2026-08-18 | 8fcc290f8e23 | 570ed4eb2caf | 已完成 | T-937：resolve_doc_link + list_my_chats TTL 缓存；顺手修两处存量 I001 import 排序 |
| workbench/backend/routers/feishu_pool.py | sess-agentchat-material | 2026-08-18 | 53b96f440edc | 5d8bb8b8d5a5 | 已完成 | T-937：GET /resolve-doc 端点 |
| workbench/frontend/src/components/FeishuWatchSettings.tsx | sess-agentchat-material | 2026-08-18 | ba9f1dd39ca0 | 7feaa6ece80e | 已完成 | T-937：弹层秒开+去手填+链接解析+下拉搜索化 |
| workbench/frontend/src/api.ts | sess-agentchat-material | 2026-08-18 | f6024828da85 | d22167b6cef3 | 已完成 | T-937：resolveDoc API + docs title 字段 |
| test_specstd/test_feishu_pool_page.py | sess-agentchat-material | 2026-08-18 | 2af36733d7ad | 936e000972fb | 已完成 | T-937：resolve_doc_link 6 用例 + 缓存 3 用例 |
| specflow/feishu_pool/lark_cli.py | sess-agentchat-material | 2026-08-18 | b5e07a19d065 | a67dae7f0b01 | 已完成 | T-938：_run_lark 可选 emp 参数（USERPROFILE 身份隔离）；顺手修 B904×3 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-agentchat-material | 2026-08-18 | 570ed4eb2caf | 226f15899c58 | 已完成 | T-938：list_my_chats stale-while-revalidate + _fetch/_refresh 拆分 |
| workbench/backend/services/specflow/feishu_watcher.py | sess-agentchat-material | 2026-08-18 | fb247c9969ad | 4b99f053c4fb | 已完成 | T-938：chats_warmup_job + _schedule_chats_warmup（interval 5min + next_run_time 即首跑）；顺手修 SIM105 |
| test_specstd/test_feishu_pool_page.py | sess-agentchat-material | 2026-08-18 | 936e000972fb | 0f16922ca25e | 已完成 | T-938：stale/explicit emp/_lark_env 三用例；存量 fake 签名补 emp 参数 |
| test_specstd/test_feishu_watcher.py | sess-agentchat-material | 2026-08-18 | 22f75c2a9d7a | a9fb78a59f71 | 已完成 | T-938：预热 job 两用例 + 存量 5 处 patch 行补齐；顺手修 E741/F401×2/I001×2 |
| workbench/backend/routers/feishu_pool.py | sess-agentchat-material | 2026-08-18 | 5d8bb8b8d5a5 | 40e037f28d0b | 已完成 | T-939：material-content / material-image 两端点；顺手修 I001×3+B904 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-agentchat-material | 2026-08-18 | 226f15899c58 | 595418c95a5d | 已完成 | T-939：read_material_content + fetch_material_image（白名单防穿越+磁盘缓存）；补丁：list file 带目录前缀 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-agentchat-material | 2026-08-18 | af74fd466c3d | deb3bdf32820 | 已完成 | T-939：详情弹层（react-markdown+图片内嵌）+图片描述卡片流重构 |
| workbench/frontend/src/api.ts | sess-agentchat-material | 2026-08-18 | d22167b6cef3 | 8a7f1c06d487 | 已完成 | T-939：materialContent + fetchMaterialImageBlob（blob→objectURL，鉴权 header 兼容） |
| test_specstd/test_feishu_pool_page.py | sess-agentchat-material | 2026-08-18 | 0f16922ca25e | 9672a0e19890 | 已完成 | T-939：内容三类型/防穿越/图片代理缓存与拒绝 7 用例 + file 带前缀断言 |
| specflow/feishu_pool/pool_store.py | sess-agentchat-material | 2026-08-18 | 790dbc7da652 | 0140c955233b | 已完成 | T-940：save_*_snapshot 可选 meta 参数落 sidecar；顺手修 E402 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-agentchat-material | 2026-08-18 | 595418c95a5d | df9c340433a2 | 已完成 | T-940：sync 调用点传 owner/source_url + list 返 meta + sidecar 不当材料 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-agentchat-material | 2026-08-18 | deb3bdf32820 | be32778b10c8 | 已完成 | T-940：监听范围卡+用户标签点选筛选+飞书原文外链+快照弹层外链 |
| workbench/frontend/src/api.ts | sess-agentchat-material | 2026-08-18 | 8a7f1c06d487 | 802519233d80 | 已完成 | T-940：FeishuPoolMaterial 加 source_url/owner 字段 |
| test_specstd/test_feishu_pool.py | sess-agentchat-material | 2026-08-18 | 22dda037a006 | 2e926058115e | 已完成 | T-940：meta sidecar 落盘用例；顺手修 E741 |
| test_specstd/test_feishu_pool_page.py | sess-agentchat-material | 2026-08-18 | 9672a0e19890 | 988569618cc5 | 已完成 | T-940：单 owner 落盘/_sync_user_docs owner/list 返 meta 三用例 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-agentchat-material | 2026-08-18 | df9c340433a2 | 44b382926c5b | 已完成 | T-941：search_docs 全局搜 + _friendly_lark_error + _parse_doc_results 统一解析 |
| workbench/backend/routers/feishu_pool.py | sess-agentchat-material | 2026-08-18 | 40e037f28d0b | 8853ae1dbc66 | 已完成 | T-941：GET /docs-search 端点 |
| workbench/frontend/src/components/FeishuWatchSettings.tsx | sess-agentchat-material | 2026-08-18 | 7feaa6ece80e | 96a59ec09b85 | 已完成 | T-941：文档区三独立路径（按名搜置顶/按用户/粘链接）+ mergeDocResults 统一 |
| workbench/frontend/src/pages/FeishuPool.tsx | sess-agentchat-material | 2026-08-18 | be32778b10c8 | 15c0d0a59e54 | 已完成 | T-941：删监听范围卡内同步设置入口（提示文案指向右上） |
| workbench/frontend/src/api.ts | sess-agentchat-material | 2026-08-18 | 802519233d80 | c49a2bfbf364 | 已完成 | T-941：searchDocs API |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-agentchat-material | 2026-08-18 | 44b382926c5b | 5cf53f3982ed | 已完成 | T-942：_friendly_lark_error 文案指向弹层内授权操作+未绑定分支 |
| specflow/feishu_pool/topic_cluster.py | sess-t947-dev | 2026-08-18 | — | 6a50a881d804 | 已完成 | T-947：draft_chat_segments/list_drafts/commit_drafts/edit_candidate/regen_candidate（草案文件_topic_drafts.yaml） |
| workbench/backend/routers/feishu_pool.py | sess-t947-dev | 2026-08-18 | — | 19919545ea61 | 已完成 | T-947：topics/drafts\|draft\|commit\|card\|regen 五端点（无模型 400/缺资源 404） |
| workbench/frontend/src/api.ts | sess-t947-dev | 2026-08-18 | — | 4a810ce7a3d9 | 已完成 | T-947：介入工作区 5 API + FeishuTopicDraft 类型 |
| test_specstd/test_feishu_topic_cluster.py | sess-t947-dev | 2026-08-18 | — | a474d1bdce55 | 已完成 | T-947：5 新 TDD 用例（草案不写候选/同天覆盖/勾选替换/部分编辑/id 稳定重生成） |
| agent/purposes/requirement_interview.md | sess-agentchat-material | 2026-08-17 | — | d27cfa18e450 | 已完成 | T-931：panels 对齐真实页签 id（[pack,focus,materials]，旧值入储备注释） |
| agent/purposes/test_workbench.md | sess-agentchat-material | 2026-08-17 | — | 6c1652b5f242 | 已完成 | T-931：panels 对齐（[deps,history]） |
| test_specstd/test_purpose.py | sess-agentchat-material | 2026-08-17 | — | 4f973acdac98 | 已完成 | T-931：panels 值断言用例 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-agentchat-material | 2026-08-17 | — | 961c92ee762c | 已完成 | T-932：SIDE_TABS 页签注册表 + purposePanels 装配 + 隐藏回落 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-s05-dev | 2026-08-07 | b9c44f504ab1 | a8899625b861 | 已完成 | T-511：WS doc_read case + readingFeed state（_store 跨导航保持）+ 阅读页签接线 + openFileViewer hunks/fallback 透传 + openDocRead；顺带修复预存构建红（React.memo UMD→memo import、删除 hint 死代码） |
| test_specstd/test_feishu_fetch.py | sess-s2.5-dev | 2026-08-11 | NEW | 6717fdf9231c | 已完成 | T-025/T-026 测试 19 例（agenda/链路分支/权限块/subprocess 封装） |
| mcp_server/tools/feishu_fetch.py | sess-s5-dev | 2026-08-11 | e02940f0973f | 12f62fd0d601 | 已完成 | T-057：+feishu_doc_read/feishu_base_query（lark-cli 纯读，权限结构化提示） |
| agent/runtime.py | sess-s5-dev | 2026-08-11 | 4e8fb4f0bbe9 | b31bb4e2bb2c | 已完成 | T-057：product 只读集 +3 工具（feishu_doc_read/base_query/sf_suggest_story_draft） |
| agent/purposes/requirement_interview.md | sess-s3-dev | 2026-08-11 | 47b8bc180367 | d87717aa7964 | 已完成 | 白名单加 specflow_pack 5 工具 + info_pack 三件套（14→22 工具） |
| graph_index/store.py | sess-pa-dev | 2026-08-11 | NEW | b9dce4a2f1ab | 已完成 | T-070：SQLite 存储（nodes/edges/index_meta + 类型枚举 + 谱系阶段映射） |
| graph_index/builder.py | sess-pa-dev | 2026-08-11 | NEW | 4d2f139c4bc9 | 已完成 | T-070/T-073：确定性派生（两遍扫描建 depends_on 边；锚点行号 source_ref；T-073 挂链节点 interview/decision/external_ref 读 workbench.db） |
| graph_index/service.py | sess-pa-dev | 2026-08-11 | NEW | fbe14900172e | 已完成 | T-070/T-073：查询服务（status/rebuild/保鲜/L0/L1/L2/backlink/健康分）+ 谱系 trace BFS（流方向逐边映射） |
| workbench/backend/routers/graph.py | sess-pa-dev | 2026-08-11 | NEW | c783a17626dc | 已完成 | T-070/T-072：graph 路由（status/panorama L0-L2/backlink/source 受控前缀/snapshots/diff/rebuild） |
| workbench/backend/main.py | sess-pa-dev | 2026-08-11 | 2a040f72b8b4 | d012bf97b127 | 已完成 | T-070~T-074：注册 graph/lineage 路由（与 S6 data_fab/coverage 追加式共存） |
| test_specstd/test_graph_index.py | sess-pa-dev | 2026-08-11 | NEW | 4a8fc17fea97 | 已完成 | T-070/T-072/T-073/T-074：测试 29 例（构建/source_ref/确定性/指纹/三层视图/backlink/快照 diff/血缘 trace/断链规则/红线） |
| workbench/frontend/src/App.tsx | sess-pa-dev | 2026-08-11 | c732bde8efe5 | c17d99d6317e | 已完成 | T-071/T-073：菜单+路由（全景图谱/血缘链，总览组） |
| workbench/frontend/src/pages/GraphPanorama.tsx | sess-pa-dev | 2026-08-11 | NEW | efdd4366e5ce | 已完成 | T-071/T-072：三层下钻 + 三镜头 + backlink + 里程碑时间轴/diff + 📍 源头定位行高亮 |
| workbench/frontend/src/api.ts | sess-engine-t502 | 2026-08-11 | 31f0f87cb42f | 34f217a4e478 | 已完成 | T-502：PreflightResult/PreflightScenario 扩展 file_refs/missing_files/unknown_file_refs(_gaps) |
| mcp_server/server.py | sess-lark-dev | 2026-08-11 | 5176e99713cc | | 登记中 | T-701/T-702：TOOL_MODULES 注册 lark_auth + lark_run |
| workbench/backend/main.py | sess-lark-dev | 2026-08-11 | 3bbd4741ac30 | | 登记中 | T-703：include_router lark_binding |
| workbench/frontend/src/api.ts | sess-lark-dev | 2026-08-11 | 886a405dcca0 | | 登记中 | T-703：larkApi 类型+方法 |
| agent/purposes/requirement_interview.md | sess-lark-dev | 2026-08-11 | 1cb823842e19 | | 登记中 | T-702：白名单加 lark_auth_* 3 + lark_execute |
| mcp_server/server.py | sess-s8-dev | 2026-08-11 | d7ee368841d9 | a418eebb1325 | 已完成 | 并发提交事故修复：3092367 合并提交的 server.py 丢失 open/lark 挂载（mods 仅含 knowledge），重新追加挂载（open 五模块 + lark_auth/lark_run，追加式）；工具数恢复 84 |
| test_specstd/test_mcp_server.py | sess-s8-dev | 2026-08-11 | 25c97e028453 | 366756de0725 | 已完成 | 验收修复：工具数 84→83（read_run_report 去重） |
| docs/远期设计/SpecGuard-总控文档.md | sess-s8-dev | 2026-08-11 | 52bc0e4a082d | 5cd365e9b502 | 已完成 | v1.22 自身登记（补二）：全量验收修复登记——read_run_report 去重 + lark 分级 draft；修改后hash = 登记中形态指纹 5cd365e9b502（v1.3 约定） |
| docs/远期设计/SpecGuard-总控文档.md | sess-gatedock-dev | 2026-08-13 | 252391d90885 | 29b6ad154684 | 已完成 | v1.23 自身登记：历史归档瘦身（版本决策/§4.1/§4.2 已完成/§4.3 完成行/§4.4/§4.5/§5 历史/§6 历史入归档文件）+ §4.8 GateDock 支线（T-900 ✅ / T-901 / T-902）+ §5 注册；修改后hash 29b6ad154684 |
| workbench/frontend/src/pages/AgentChat.tsx | sess-gatedock-dev | 2026-08-13 | — | be39793869bc | 已完成 | T-901/T-902：GateDockCtx Provider + PreBlock gate-card/gate-exec 围栏拦截 |
| docs/远期设计/SpecGuard-总控文档.md | sess-gatedock-dev | 2026-08-13 | 29b6ad154684 | 52e1245a26e4 | 已完成 | v1.24 自身登记：T-901/T-902 已完成收口 + §5 更新 + §6 新增 10 文件登记 |
| specflow/feishu_pool/captions.py | sess-feishu-graph | 2026-08-14 | NEW | 583595de91d0 | 已完成 | T-911：替身文本拼装 |
| workbench/backend/services/specflow/feishu_sync_service.py | sess-feishu-graph | 2026-08-14 | NEW | 373d714a93ea | 已完成 | T-912：三通道拉取入库 |
| workbench/backend/routers/feishu_pool.py | sess-feishu-graph | 2026-08-14 | NEW | abcfaebaf464 | 已完成 | T-912：REST 五端点（挂载在 T-914） |
| test_specstd/test_feishu_sync.py | sess-feishu-graph | 2026-08-14 | NEW | e404fa02465b | 已完成 | T-912 用例 |
| graph_index/service.py | sess-feishu-graph | 2026-08-14 | afcfcf7c2414 | c40a9db4c14d | 已完成 | T-913：backlink mentioned_by |
| test_specstd/test_graph_index.py | sess-feishu-graph | 2026-08-14 | 176c77d59602 | 304b8c38f5ce | 已完成 | T-913：TestFeishuNodes 3 例 |
| workbench/backend/main.py | sess-feishu-graph | 2026-08-14 | — | 8ba9c7bcf36d | 已完成 | T-914：feishu_pool 路由挂载（1c89d14） |
| workbench/frontend/src/api.ts | sess-feishu-graph | 2026-08-14 | — | 8cb1e087ccf1 | 已完成 | T-915：feishuPoolApi+graphApi.focus/network（3e32e89/98612da/0871641） |
| workbench/frontend/src/components/FeishuReviewPanel.tsx | sess-feishu-graph | 2026-08-14 | NEW | c82e85045496 | 已完成 | T-915：关联复核面板（3e32e89） |
| workbench/frontend/src/components/FocusGraph.tsx | sess-feishu-graph | 2026-08-14 | NEW | 776bd858f98a | 已完成 | T-915：焦点子图组件（98612da） |
| workbench/frontend/src/pages/AgentChat.tsx | sess-feishu-graph | 2026-08-14 | — | 484db7dccb0e | 已完成 | T-915：「◎ 图谱」页签（98612da） |
| test_specstd/test_feishu_sync.py | sess-feishu-graph | 2026-08-14 | — | 233703329b5c | 已完成 | T-916：e2e 贯通（收口笔） |
| docs/远期设计/SpecGuard-总控文档.md | sess-feishu-graph | 2026-08-14 | 918a20f96c61 | 4e09855feb68 | 已完成 | v1.25：§4.9 任务块+§5 会话+§6 登记+收口状态 |
| docs/远期设计/SpecGuard-总控文档.md | sess-feishu-graph | 2026-08-14 | 58b09aab4c31 | 4130088d3b1e | 已完成 | v1.26：二期任务登记 |

### 6.1 陈年「登记中」未回填行（2026-08-21 清理）

> sess-lark-dev（T-701~T-703，2026-08-11）登记后未回填修改后hash、未改状态。2026-08-21 核实：登记文件已全部落地入库（lark_auth/lark_run/lark_binding/LarkBinding.tsx/两份设计计划文档均存在，.gitignore 已含 .lark-cli/；「绑定飞书」入口后续经 T-942 演进为同步设置弹层内嵌授权块，App.tsx 独立路由未保留）。此行是 T-701~T-703 状态对账（T-998）的佐证：任务实已交付、总控状态滞后。

| 文件路径 | 会话ID | 登记时间 | 修改前hash | 修改后hash | 状态 | 备注 |
|---|---|---|---|---|---|---|
| mcp_server/tools/lark_auth.py | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-701：MCP 3 工具（lark_auth_status/login/logout）+ RPEST 共用底层函数 |
| mcp_server/tools/lark_run.py | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-702：lark_execute 通用执行器（白名单/写保护/审计） |
| .gitignore | sess-lark-dev | 2026-08-11 | a9c6c2c5be38 | | 登记中 | T-701：补充 .lark-cli/ |
| workbench/backend/routers/lark_binding.py | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-703：REST 端点 4 个（status/login/logout/scopes） |
| workbench/frontend/src/App.tsx | sess-lark-dev | 2026-08-11 | b43a13ab3d15 | | 登记中 | T-703：菜单「绑定飞书」+ 路由 /lark-binding |
| workbench/frontend/src/pages/LarkBinding.tsx | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-703：绑定页 UI（状态卡片/scope 清单/绑定引导） |
| docs/远期设计/SpecGuard-飞书CLI集成设计-T701-T703.md | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-701~T-703 设计文档 |
| docs/远期设计/SpecGuard-飞书CLI集成计划-T701-T703.md | sess-lark-dev | 2026-08-11 | NEW | | 登记中 | T-701~T-703 实施计划 |
