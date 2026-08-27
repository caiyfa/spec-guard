# SpecGuard 话题携带文档材料设计（T-1027）

> 立项缘起（2026-08-27 总控人与会话排查确认）：现状下「群聊里分享过的云文档/妙记/文件」在话题生成链路中近乎不可见——话题只能基于文字消息生成。用户拍板：**话题需要能有文档类的内容，不能指望什么消息都以文字的形式发到群里。**
> 定位：事实层补齐（聊天中客观分享过什么材料），与 T-1015 references（判断层：人工确认的话题↔材料语义关联）正交互补。

---

## 1. 背景与问题

话题卡由群聊快照聚类而来，但消息进入 LLM prompt 前要经过渲染层；渲染层对非纯文本消息的处理有三处口径，一处比一处激进：

| 链路 | 处理方式 | 后果 |
|---|---|---|
| 日级聚类视图 `chat_store.render_md_from_jsonl` | text/post 内容原样保留；file 渲染 `[文件] 文件名`；image 变图片占位；**其余 msg_type 一律 `[interactive消息]` 式占位**（chat_store.py else 分支） | 卡片式分享的云文档/妙记标题+链接**全灭**；text/post 里粘贴的裸链接能进 prompt |
| 多日窗口 `_load_window_source`、勾选归纳 `compose_topic_from_messages` | **只保留 text 原文**，其余一律 `[{mtype}消息]` | 连 post 富文本里的链接、文件名都不可见 |
| 聚类 prompt 与卡片 schema | 无「文档要引用」指令，输出字段（title/summary/keywords/msg_lines…）无承载结构 | 即使链接进了 prompt 也只是被 summary 概括提一句，不落结构化关联 |

材料池侧 docs/minutes 快照是**独立通道**落池的（watch.docs 授权清单轮询 + 按监听用户搜妙记），跟群里谁分享过毫无关系——池里有快照 ≠ 话题知道它相关。

另有一点常被误读：**JSONL 事实源没丢数据**——`normalize_pull_message` 对未识别的消息类型同样把 content 原样存盘。丢真发生在派生视图（md）这一层，这也是本设计只动视图与派生逻辑、不动存储契约的原因之一。

## 2. 现状与约束（实测）

1. 全仓（specflow / workbench services / mcp_server / agent）对飞书域链接**零确定性提取**：无 `feishu.cn` 相关正则，无 doc-token 解析。
2. 已钉案契约（`test_specstd/test_feishu_chat_store.py._CLI_SNAPSHOT` 及 T-952/T-1016 实测注释）：text / post（markdown 化、内嵌图 `![Image](key)`）/ file（`<file key name/>` 自描述标签）/ image（`[Image: {key}]`）/ merge_forward（`<forwarded_messages>` 包裹）五种形状。
3. **契约缺口**：「云文档分享到群」「妙记分享卡片」「post 内超链接锚文本形状」在 lark-cli 实测快照中均未钉案。按仓库纪律禁止按代码期望造字段——T-1028 开工第一件事就是实测补契约夹具。
4. 一行一消息铁律：md 视图行号 ↔ line_ids ↔ message_ids 一一对应，是 LLM msg_lines 锚定与前端时间轴回放的地基；任何渲染扩展不得破坏。
5. T-1015 references 边存 `material_links.yaml`（confirmed/rejected 留痕），预筛条件为时间窗±7天 + 标题相似/关键词命中——它回答「这材料跟话题相关吗」，不回答「群里分享过它吗」。
6. 快照直拉通道现成：`sync_doc(token)` / minutes detail 按 token 单条可拉（权限不足时 lark CLI 报错诚实上抛）；perm meta 可见性语义照 AGENTS.md 2026-08-19 决策执行。

## 3. 关键决策

- **D1 渲染保真降级制**：所有消息类型在 md 视图必须渲染出至少一行人类可读内容——已知类型升级（卡片类 → `[云文档] 标题`/`[妙记] 标题`式一行）；未知类型不再纯占位，改为 `[未知:{type}] content 截断摘要`。一行一消息铁律不动。
- **D2 链接提取走确定性正则，不进 LLM 层**：飞书域 URL/doc-token 提取在 JSONL 行级完成（零幻觉、可离线测试、随撤回刷新重算）。域与路径枚举以实测契约为准收缩，非飞书域名一律不收，防误吸外部链接。
- **D3 话题卡新增事实性字段 `shared_materials`**（区别于 references 判断边）：由话题关联的 message_ids ∩ 提取结果确定性推导，落卡形如 `{kind, token?, url, title?, message_id, snapshot_ref}`（snapshot_ref = 对应 fd-*/fm-* 快照 id 或 null）。cluster/draft/compose/regen 四路同源推导；edit_candidate 改 message_ids 时重算；读侧 setdefault 兼容存量卡。
- **D4 缺失快照即时补拉，失败诚实降级**（待拍板①）：命中 token 在池内无快照时默认调 sync_doc/sync_minutes 单条补拉（多用户语义=共享材料区，拉成功全员可见，符合工作区级授权设计）；权限不足/网络失败 → 保留 snapshot_ref=null 的引用记录并在前端标注「未同步」，**绝不静默丢链接、也不报错打断聚类主流程**。
- **D5 双轨并存、展示合一**：shared_materials（事实）与 references（确认）分开存储与推导，前端 chips 复用同一组件、用「事实/已确认」徽标区分；图谱 builder 是否为事实字段建边本期不做（YAGNI）。

## 4. 分块设计

### F1 数据层（specflow/feishu_pool/chat_store.py）

1. **契约实测先行**：造含「云文档分享卡片 / 妙记卡片 / text 裸链接 / post 超链接 / merge_forward 嵌套链接」的真实消息样本（lark-cli pull 快照），扩进 `_CLI_SNAPSHOT` 式夹具，钉死真实 msg_type/content 形状后才动渲染代码。
2. **`render_row_body(row)` 共享函数**：把现有 render_md_from_jsonl 的类型分派逻辑抽成单消息行渲染函数，供三处调用——日级 md 视图、`_load_window_source`、`compose_topic_from_messages`——消除「日级保真 / 人工链路只留 text」的口径漂移。
3. **extract_feishu_links(content) -> list[dict]**：正则提取 `{kind, token, url, title?}`；对 post/merge_forward/text 通吃；title 从卡片文本或链接锚文本尽力提取，缺失允许为空。
4. 渲染组装时在行尾附加提示片段（如 `→ 📄 盘点方案`），LLM 无需理解 URL 即可感知文档存在；结构化 refs 走 JSONL 行级 API 给 F2 用。

### F2 话题装配与联动（topic_cluster.py + workbench 服务层）

1. `derive_shared_materials(message_rows) -> list[dict]`：给定话题关联的消息行集合，确定性产出 shared_materials。四路接线：cluster_chat_snapshots / draft_chat_segments / compose_topic_from_messages / regen_candidate；edit_candidate 整体替换 message_ids 时重算、窗口不变则跳过。
2. 快照匹配与补拉（服务层，非聚类内部）：token 匹配池内 fd-*/fm-* meta（docs sidecar 有 source_url/token；minutes token 即 fm id）；缺失走 D4 补拉钩子（异步化避免阻塞聚类响应，落卡时 snapshot_ref 允许晚到回填——简单实现为先同步单条、超时 5s 降级 null，实施时拍板）。
3. `list_pool_topics` 响应透出 shared_materials（含快照 in-pool 标志），复用 T-1015 material-content 详情端点看正文。

### F3 召回与前端

1. **agent 召回**：topic_digest 摘要注入与 topic query read 返回带上 shared_materials（📄/🎙 + 标题 + 是否已同步），让「群里那份方案文档」成为 agent 可口述、可展开的事实（T-1011 四路召回的自然延伸）。
2. **前端**：TopicCard 在 keywords 行下方挂 shared 材料 chips（与 T-1015 推荐区同组件渲染，徽标区分事实/确认）；时间轴 ChatMessageView / ChatDetailView 把文档类消息行渲染成芯片而非占位符；ComposeTopicModal 勾选列表同步受益于 F1 行渲染。

## 5. 任务拆解

| 任务 | 内容 | 依赖 |
|---|---|---|
| T-1027 | 本任务：立项设计稿 + 总控登记（本会话交付，评审通过后放开施工块） | — |
| T-1028 | F1 数据层：契约实测夹具入 test_feishu_chat_store + render_row_body 收敛三处口径 + extract_feishu_links（TDD 离线全绿为门禁） | T-1027 |
| T-1029 | F2 装配联动：四路 shared_materials 推导 + regen/edit 重算守卫 + 缺失快照补拉（D4 拍板落地）+ list_pool_topics 透出 | T-1028 |
| T-1030 | F3 召回与前端：digest/read 携带 + TopicCard chips + 时间轴/详情弹层文档行渲染 + vitest | T-1029 |

## 6. 测试策略

- **契约夹具**（T-1028 前置）：真实 CLI 消息样本固化，测试禁止手写期望形状之外的伪字段（同 _CLI_SNAPSHOT 纪律）。
- chat_store 单测（离线）：五已知类型 + 卡片类型渲染行格式、一行一消息不破（line_ids 数量==行数）、链接提取边界（非飞书域不收/撤回行为/空 content/合并转发嵌套）。
- topic_cluster 单测：四路推导结果一致；edit 改 message_ids 重算、不改不重算；存量卡无字段读取兼容。
- 服务层单测：token→快照命中映射；补拉失败降级路径（mock lark 失败 → snapshot_ref=null 且主流程不断）。
- 前端 vitest：chips 渲染/徽标区分/空态不占位。
- 门禁照旧：test_specstd 全量 + engine_modes + vitest + build + release_check PASS。

## 7. 非目标与边界

- 不做链接正文进 prompt 的自动全文注入（材料正文消费走既有 docs 快照/妙记 artifacts/captions 转述链路，防 prompt 爆炸）。
- 不做从聊天事实自动建图谱边、不做跨系统（禅道等）链接识别——本期只认飞书自有文档体系。
- file 消息维持「文件名」级事实（二进制解析不在范围）。
- 不改 format_spec、不触碰 engine/specstd 冻结层——全部改动限于 specflow.feishu_pool + workbench 前后端。

## 8. 待拍板决策点

1. **D4 补拉策略**：推荐「即时单条补拉 + 失败诚实降级仅记引用」（本设计默认按此写）；备选保守「只记不拉」，缺权限场景体验差一些但零额外 API 消耗。
2. **chips 归组**：shared_materials 与 references 前端是否合并一组 chips（推荐合并渲染+徽标区分）还是分两行展示。
3. **图谱建边**：事实字段是否将来建 references 类边进 graph_index（本期 YAGNI，待 agent 召回价值验证后再议）。
