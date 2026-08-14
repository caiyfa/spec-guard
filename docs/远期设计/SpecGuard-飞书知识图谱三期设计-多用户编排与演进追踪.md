# SpecGuard 飞书知识图谱三期设计 · 多用户编排与演进追踪

> 版本：v1.1 · 2026-08-14 ｜ 状态：已实施（三期全量交付：T-924~T-929 ✅，1618 全量回归 + release_check PASS）
> 定位：在二期「单用户事件监听 + 视觉转述 + 自动焦点 + 文档轮询」基础上，解除单用户边界（多用户监听编排）、采集升级直写模式（秒级实时）、补话题演进链与入包最后一公里。
> 关联：一期设计（v1.1 已实施 T-910~T-916 ✅）；二期设计（v1.1 已实施 T-917~T-923 ✅）；总控文档 §4.9。

---

## 1. 背景与范围

### 1.1 二期已落地（回顾）

- FeishuWatcher 常驻监听（单用户守卫三态）；3 路 consume 托管（IM bot + minutes/vc user）；5min 节流重拉；关 stdin 优雅停；退避重启；catch-up + 文档日级轮询。
- 图片视觉转述（增量自动+存量手动）；消息锚点自动焦点。

### 1.2 三期范围（四功能块）

| # | 功能块 | 解决的缺口 |
|---|---|---|
| F5 | **多用户监听编排** | 二期单用户边界：>1 用户配置 watch 即整体不启动 |
| F6 | **事件直写 + 校对重拉** | 5min 节流重拉实时性不足；直写达秒级 |
| F7 | **话题演进追踪** | 话题按天隔离（chat-day-seq），跨天讨论断链 |
| F8 | **确认材料自动入包** | 复核确认到入包还需人工二次操作（最后一公里） |

### 1.3 非目标

- 消息撤回/编辑的事件级处理（**实测约束**：lark-cli 事件目录 IM 12 事件中无撤回/编辑事件——由 F6 每日校对重拉天然兜底，不做单独机制）；
- docs 域事件（等 lark-cli 扩展）；
- 话题状态独立字段（「已入需求」由 mentions 边派生可得，免存储）。

---

## 2. 关键决策记录（设计评审结论）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D5 | 直写与重拉关系 | **直写为主 + 重拉校对** | 事件内容直写快照（秒级）；catch-up + 每日全量重拉覆盖校对（修正漂移，含撤回/编辑——重拉后快照与飞书侧一致） |
| D6 | 入包闸门语义 | **确认时可选入包（默认不勾）** | 复核确认弹层加「同时入包 IV-xxx」勾选——确认关联+入包两动作一次人拍板，不绕 M03 闸门铁律 |
| D7 | 多用户启停 | **配置驱动启停 + 常驻不回收** | 保存 watch 配置即启动、删除/解绑即停；35 人×3 路轻量子进程可承受；行为可预期优于闲置回收的丢事件风险 |
| D8 | 跨天话题归并 | **LLM 判延续**（continues: 旧话题 id） | 聚类 prompt 注入近 7 天同群话题清单，语义判定最准；规则判定误并/漏并率高 |

---

## 3. F5 多用户监听编排

### 3.1 架构

```
WatcherRegistry（workbench 后端进程内单例）
  ├─ watchers: {emp: FeishuWatcher}     内存注册表
  ├─ 状态落盘 {ws}/.specguard/feishu/watchers.json
  │   （emp / event_keys / started_at / event_count / last_event_at——管理可查）
  ├─ 启动触发：PUT /api/feishu-pool/watch 保存配置
  │   → lark-cli token 校验（USERPROFILE 注入该用户目录）
  │   → 通过则拉起该用户 3 路 consume；已在跑则跳过（幂等）
  ├─ 停止触发：删除 watch 配置 / 解绑飞书 → 优雅停（关 stdin）
  ├─ 常驻不回收；软上限 50 用户（超出 WARN 拒绝新启动）
  └─ 后端 shutdown → 全部优雅停
```

### 3.2 与二期守卫的关系

二期 `resolve_watch_user` 单用户守卫（>1 告警不启动）**退役**，改为 `resolve_watch_users`（复数）遍历全部「watch 配置 + token 有效」用户；后端 startup 时按注册表全量拉起（服务重启恢复）。

### 3.3 USERPROFILE 隔离

每用户 consume 子进程注入 `USERPROFILE={SG_ROOT}/.lark-cli/{emp}/`（T-701 实测机制），token/配置/缓存零串扰；事件重拉落池落该用户 `.specflow/{emp}/` 私有区（现状路径不变）。

---

## 4. F6 事件直写 + 校对重拉

### 4.1 直写路径（主）

`im.message.receive_v1` 事件负载自带 `sender_id/create_time/content`（纯文本已解码，lark-event 契约）→ 直接渲染 `[HH:MM] 发送人: 内容` **追加** `chats/{chat_sha8}/{yyyymmdd}.md`：

- 直写函数 `pool_store.append_chat_lines(emp_base, chat_id, day, lines)`：追加模式打开，幂等由 event_id 去重表（`.specflow/{emp}/feishu_pool/_seen_events.json`，TTL 7 天滚动）；
- 发送人显示名：事件负载只有 open_id——经 `im` 成员信息缓存（`.specflow/{emp}/feishu_pool/_senders.json`，open_id→name 首见时 `contact` 解析缓存，失败用 open_id 尾 6 位）；
- 图片消息：事件 content 为占位 → 写 `[图片#N]` 占位 + imgmap 追加（沿用一期语义）。

### 4.2 校对重拉（兜底）

- watcher 启动 catch-up（二期已有）+ **每日 03:00 全量校对**：对 watch.chats 全部群 `sync_chat` 覆盖重写当日快照——撤回/编辑/直写丢漏全部与飞书侧对齐；
- 节流重拉路径保留：分钟/纪要事件仍走「触发重拉」（minutes/vc 内容重，直写无收益）。

### 4.3 边界

- 直写仅限 IM 文本/图片占位；撤回/编辑无事件（CLI 目录不支持）→ 由校对重拉兜底，**不做单独撤回标记机制**；
- 直写与重拉写同一文件：校对重拉是覆盖写（ sync_chat 全文重写），直写是追加——校对后当日快照以飞书侧为准，确定性可重建。

---

## 5. F7 话题演进追踪

### 5.1 LLM 判延续

`topic_cluster` 聚类 prompt 增强：注入**近 7 天同群已有话题清单**（id/title/window/summary 截断 80 字）→ LLM 输出话题时若判定是延续，附加 `continues: <旧话题id>`。

### 5.2 演进链落盘与派生

- 候选话题/共享区 topics.yaml 条目加 `continues` 字段（可选）；
- graph_index 新增边类型 **`evolves`**：topic → topic（src=新话题，dst=旧话题）——builder 派生段读取 continues 建边（两端均须已存在）；
- 网状镜头/焦点子图可见演进链（evolves 边样式：点线灰色）；`trace` 的 `_TRACE_UP_SIDE` 加 evolves=src（演进向上游追溯）。

### 5.3 归并纪律

- continues 只建链不合体（新旧话题各自保留节点——演进历史可见）；
- LLM 给的 continues 必须存在于已有话题清单（防幻觉校验，同 mentions 的锚点校验口径），否则丢弃该字段（话题本体保留）。

---

## 6. F8 确认材料自动入包

### 6.1 后端

复核确认端点响应增强：确认成功后检查 dst FR 是否落在**进行中面试**的议题范围（sf_interviews 状态=进行中 ∩ 议题 fr_hints/target_delta 关联）→ 响应带 `suggest_ivs: [{iv_id, title}]`。

### 6.2 前端

复核面板「批量确认」后若响应含 suggest_ivs → 弹层列出「同时入包以下面试信息包？」复选框（**默认不勾**）→ 用户勾选并点确认 → 调 materials include REST（pack_included=1，走 M03 原有闸门端点，不新增写通道）。

### 6.3 闸门语义

不勾 = 行为与一/二期完全一致；勾选 = 确认关联 + 入包两动作一次人拍板。**不新增自动入包路径**，M03「人拍板入包」铁律不动。

---

## 7. 测试策略

| 层 | 测试 |
|---|---|
| F5 注册表 | 多用户启停（配置保存→拉起、删除→停）、幂等、软上限拒绝、watchers.json 落盘字段 |
| F6 直写 | 事件→append_chat_lines 追加格式正确；event_id 去重（重复事件不双写）；发送人缓存解析/兜底；校对重拉覆盖写 |
| F7 演进 | prompt 注入话题清单断言；continues 有效→evolves 边派生；continues 幻觉 id→丢弃保留本体 |
| F8 入包 | confirm 响应带 suggest_ivs（FR 在面试范围）；不在范围→空；默认不勾零副作用 |
| e2e | 多用户事件→直写→校对→聚类（含 continues）→复核确认→可选入包（全 mock） |

---

## 8. 关联文档

- 一期/二期设计与实施计划：docs/远期设计/ + docs/upgrade-plans/（T-910~T-923）
- lark-event 事件目录实测：25 事件（IM 12 无撤回/编辑事件）
- M03 材料包闸门：specflow/materials/store.py（pack_included 人拍板）
