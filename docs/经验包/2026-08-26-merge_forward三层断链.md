# merge_forward（合并转发）消息三层断链

> 任务号：T-1016 ｜ 修复提交：7471f8a ｜ 验收合并：8321de2（master）
> 发现日期：2026-08-26 ｜ 契约样本：群 4d7f814d 落盘 JSONL（om_x100b67b4563770b4b4aadb072d42884）

## 现象

飞书群聊中「合并转发」消息（msg_type=merge_forward）在 SpecGuard 全链路三层断链：

1. **存储层**：`normalize_pull_message` 无 merge_forward 分支，内嵌图 key 不提取（`image_keys` 恒空）——外层 message_id 配对下载失去依据，内嵌图片不可拉取；
2. **md 派生视图**：`render_md_from_jsonl` 直出 `[merge_forward消息]` 占位——聚类、agent 上下文对转发内容完全不可见；
3. **前端渲染**：`MessageBody` 无 merge_forward 分支，走默认原文路径，用户看到 `<forwarded_messages>` 原始文本裸奔（图片显示为 img key 字符串）。

## 证据链

- 存量落盘（2026-08-26 上午同步，旧代码）：`{workspace}/.specflow/feishu_pool/chats/4d7f814d/20260821.jsonl` 中 `om_x100b67b4563770b4b4aadb072d42884` 行 `image_keys` 为空，content 为 `<forwarded_messages>` 原文；同日 `20260821.md` 首行为 `[15:43] 蔡云飞: [merge_forward消息]` 占位。
- 契约实测（2026-08-26，pull 通道原样 content）：merge_forward content 为 `<forwarded_messages>` 包裹文本，内层每条消息 `"[ISOts+08:00] 发送人:"` 头行 + 4 空格缩进内容行；内嵌图**两种占位混排**——`![Image](key)`（post 风格）与 `[Image: key]`（image 消息风格）。快照钉死在 `test_specstd/feishu_cli_contract.py` `MERGE_FORWARD_MESSAGE` / `MERGE_FORWARD_IMAGE_KEYS`。

## 根因

新 msg_type（merge_forward）只被 pull 通道原样落盘归档，消费链路三层（normalize 提取 / render_md 派生视图 / 前端 MessageBody 渲染）均未识别——典型的「存储先有、消费后补」分层遗漏（实现层）。

## 修复（7471f8a，三层同修）

1. **存储层** `specflow/feishu_pool/chat_store.py`：
   - `extract_image_keys_from_forward()`：两种占位正则混排提取，按文本出现顺序；
   - `parse_forwarded_messages()`：内层消息结构化 `[{ts, sender, text}]`（`<p>` 剥离、多行 join、非包裹内容返回 `[]` 兜底）；
   - `normalize_pull_message` 补 merge_forward 分支提取 `image_keys`（content 原样保留）；`render_md_from_jsonl` 补单行内联展开（`[合并转发] 发送人: 内容 [图片#N]；…`，line_ids 一对一约束不破，图片占位与 image/post 共享 imgmap 序号池）。
2. **前端** `ChatMessageView.tsx`：
   - `parseForwardedMessages()` 与后端同构解析；
   - `useChatMedia` 兜底：存量 JSONL 行无 `image_keys` 时从 content 解析（外层 message_id 配对下载，验收实测 104KB 成功）；
   - `MessageBody` merge_forward 分支：引用块 + 子消息列表（发送人配色 + 时间 + 内容 + 内嵌图缩略图点击放大），解析失败兜底原文。
3. **TDD**：后端 3 测试（normalize 提取 / parse 结构化 / render_md 内联）+ 前端 3 测试（解析纯函数），契约快照基于真实落盘数据。

验收（2026-08-26，合并 8321de2 后）：存量兼容（旧数据兜底渲染 + 4 图缩略图）/ 新同步（image_keys 4 个 + md 内联展开 + imgmap #1~#4）/ 回归（普通消息无变化）三检查点全过。

## 预防

- [ ] 新 msg_type 接入需**三层同查**：normalize 提取（含媒体 key）→ render_md 派生视图 → 前端 MessageBody 渲染，任何一层缺位即产生「存储可见、消费失明」断链；
- [ ] 新 msg_type 契约快照必先进 `test_specstd/feishu_cli_contract.py`（真实落盘原样，勿按消费代码反推形状——同 T-948/T-955b 教训）；
- [ ] 内嵌媒体配对 key 一律用**外层 message_id**（飞书 im 通道下载按消息配对）；
- [ ] 转发内嵌图占位有多种形态（post 风格 `![](key)` / image 风格 `[Image: key]`），正则提取按「两种混排」设计并测两种各出现；
- [ ] 存量数据兜底：渲染层消费 `image_keys` 时保留「无字段则从 content 现解析」路径，避免强制重同步才能修复显示。
