---
name: feishu-chat
description: 读取飞书群聊/私聊记录。定位群用 `im +chat-search --query`（唯一正确命令，勿拼成 +search/+search-chat）；
  拉消息用 `im +chat-messages-list --chat-id`；按内容检索用 `im +messages-search --query`（勿拼成 +message-search）。
  找不到目标群时用 `im +chat-list --sort active_time` 列最近群并展示给用户确认。全部经 lark_execute 执行，先 load_skill 取正文。
version: 1.0.0
author: platform-team
depends_tools: [lark_execute, lark_auth_status, lark_auth_login]
trigger: 用户要求读取群聊/聊天记录、查看某个群/某个人的讨论内容、按关键词找聊天消息时
keywords: [群聊, 聊天记录, 群消息, 讨论记录, 聊天内容, 消息记录, im, 找群]
---
## 飞书群聊记录读取技能

你是 SpecGuard 与飞书 IM 的只读桥接者。用户要「读取群聊记录 / 看某群讨论了什么 / 找聊天里提到 XX 的内容」时，
经 `lark_execute` 执行 lark-cli 的 im 域只读命令（全部无副作用，不触发 confirm_write）。

### 动线一：关键字搜索定位群（首选，唯一正解）

**任何「找群 / 搜索群 / 定位群」意图，第一步必须是关键字搜索**——
`+chat-search` 已实测可用，一次即命中目标群（如搜「人才发展」返回含目标群的 5 个候选）。
**禁止因怕失败而改用 +chat-list 翻页**。

- `lark_execute` command=`"im +chat-search"` args=`["--query", "群名关键词", "--format", "json"]`
- **命令名必须是 `+chat-search`**（不是 +search / +search-chat / chats search）
- 返回 chats 数组取 `chat_id`（oc_xxx）；支持群名+成员名模糊匹配（拼音/前缀）
- **搜索结果必须展示给用户**：表格列出「群名 | chat_id」，唯一命中直接确认并继续；
  多个候选时请用户指认目标群——不要静默取第一个，也不要只报「已找到」不给列表
- 搜索无结果时，换更短的关键词（取群名核心词，如「人才发展运维沟通」→「人才发展」）重试 1-2 次，
  不要直接放弃；仍无结果才进入「浏览模式」

### 动线二：浏览模式——列最近群聊给用户（仅限兜底）

**仅当**关键字搜索穷尽（缩短关键词重试 2 次仍无果）或用户明确要「列出我的群」时，
才用**最近活跃排序**的列表兜底，并**展示给用户**：

- `lark_execute` command=`"im +chat-list"` args=`["--sort", "active_time", "--page-size", "20", "--format", "json"]`
- **必须 `--sort active_time`**（默认按创建时间升序，会翻到天荒地老）；单页最大 20-100
- **每页都要把群列表展示给用户**：表格列出「群名 | chat_id | 是否外部群」，不要只报「继续翻页」
- **连续翻页上限 3 页**：3 页未命中目标群，停下来把已翻到的群名清单亮给用户，
  请用户指认目标群（或补充群名关键词），**禁止无界翻页**

### 动线三：拉取会话消息（读记录）

- `lark_execute` command=`"im +chat-messages-list"` args=`["--chat-id", "oc_xxx", "--page-size", "50", "--format", "json"]`
- 可叠加时间窗：`["--start", "2026-08-01", "--end", "2026-08-12"]`（ISO8601 或 YYYY-MM-DD）
- 排序：`--order asc/desc`（默认 desc，仅按时间）；单页最大 50 条，完整记录加 `--page-all`
- 私聊：用 `--user-id ou_xxx` 自动解析 p2p chat_id（**仅 --as user**）

### 动线四：跨会话关键词检索（按内容找消息）

- `lark_execute` command=`"im +messages-search"` args=`["--query", "关键词", "--format", "json"]`
- **命令名必须是 `+messages-search`**（不是 +message-search / messages search）
- 可叠加 `--chat-id` / `--sender ou_xxx` / `--chat-type group|p2p` / `--start` / `--end` / `--is-at-me` 收窄
- 检索类意图（如「找群里的某条讨论」）优先走本动线，不要先拉全量再本地过滤

### 边界与权限

- **只读铁律**：三个动线全部是只读命令；若命令含写操作关键词（+create/+update/+delete 等），
  lark_execute 会要求 confirm_write=true——群聊读取场景一律不应出现
- **身份**：默认 `--as user`；bot 身份不可枚举/读取 p2p 私聊（隐私保护，会被拒绝或降级为仅群聊）
- **未授权引导**：报 not_configured/permission_denied 时，先 `lark_auth_status` 查绑定状态；
  unbound 则调 `lark_auth_login`（Phase1 返回 verification_url + qr_data_uri + device_code），
  把**二维码图片**（`![授权二维码]({qr_data_uri})`）和**授权链接**一起展示给用户；
  用户扫码后调 `lark_auth_login(device_code=xxx)`（Phase2）完成授权，无需用户改文件
- **权限不足**：bound 但报 permission_denied 时提示用户补授权
  （读消息需 `im:chat:read` + `im:message:readonly`；关键词检索需 `search:message`），不静默降级
- **结果截断**：lark_execute 返回上限 50k 字符；量大时缩小时间窗/加过滤，不一次拉全
- **调用形式**：command 与 args 分离传参（禁止 shell 拼接），如 command=`"im +chat-messages-list"`、args=`["--chat-id", "oc_xxx"]`
