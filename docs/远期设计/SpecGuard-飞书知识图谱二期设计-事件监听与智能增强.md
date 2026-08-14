# SpecGuard 飞书知识图谱二期设计 · 事件监听与智能增强

> 版本：v1.0 · 2026-08-14 ｜ 状态：设计待审（未经实施）
> 定位：在一期「手动/定时拉取 + 人工复核 + 图谱派生」基础上，把采集层升级为**事件驱动常驻监听**，并补齐图片视觉转述与对话内自动焦点两个智能增强。
> 关联：一期设计《SpecGuard-飞书知识图谱设计-面试素材溯源.md》（v1.1 已实施，T-910~T-916 ✅）；lark-event 技能（25 事件实测）；总控文档 §4.9。

---

## 1. 背景与范围

### 1.1 一期已落地（回顾）

- 材料池三通道只读拉取（手动「立即同步」）；LLM 话题聚类/建边建议（三重防幻觉）；人工批量复核闸门；graph_index 飞书三节点（feishu_doc/feishu_minutes/topic）+ mentions 边派生；双层视图（网状镜头 + 焦点子图）。
- 全量 1551 用例 + release_check PASS。

### 1.2 一期遗留的四个缺口（= 二期范围）

| # | 缺口 | 二期功能块 |
|---|---|---|
| 1 | 采集靠手动/定时，新消息/新纪要不能实时入池 | **F1 事件监听常驻** |
| 2 | 图片只有占位符，无 vision 模型时替身文本为空 | **F2 图片视觉转述** |
| 3 | 焦点子图需手动输入节点 ID | **F3 消息锚点自动焦点** |
| 4 | CLI 事件目录无 docs 域，文档更新无实时通道 | **F4 文档更新轮询补位** |

### 1.3 非目标（三期及以后）

- 多用户监听编排（二期单用户验证；N 用户 × M 事件的进程注册表/回收三期再议）；
- 事件内容直接落盘双路径（撤回/编辑事件处理）；
- docs 域事件（等 lark-cli 扩展；轮询补位已是够用解）。

---

## 2. 关键决策记录（设计评审结论）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 事件→材料转化 | **事件触发重拉**（5min 节流合并） | 材料池格式与手动同步完全一致，单一代码路径；事件负载与拉取格式不一致的双路径归一被消除 |
| D2 | 监听编排 | **先单用户验证** | 恰好 1 个「watch+token 有效」用户才启动；多用户进程膨胀与回收三期再议 |
| D3 | 视觉转述时机 | **增量后台自动转 + 存量面板手动转** | 新入池图片异步转述（复核时已就绪）；历史图片复核面板手动触发，成本可控 |
| D4 | 自动焦点来源 | **消息锚点检测** | 正则提取最近消息最后提及的锚点（FR/tp/fd/fm），全会话通用，不绑面试官上下文 |

---

## 3. F1 事件监听常驻

### 3.1 架构

```
workbench 后端 startup → FeishuWatcher 启动（复刻 scheduler 进程内托管先例）
  ├─ 单用户守卫（§3.2）
  ├─ 拉起 3 个 consume 子进程（共享 lark-cli bus daemon）：
  │   im.message.receive_v1      --as bot   （群聊消息；bot 已入群为前提）
  │   minutes.minute.generated_v1 --as user （妙记生成）
  │   vc.note.generated_v1       --as user （纪要 note 生成）
  ├─ 事件循环：stdout NDJSON → 分类 → 节流合并（§3.3）→ 重拉落池 → 异步聚类/建议
  ├─ catch-up：启动时先跑一次 sync_all（补离线窗口）
  └─ 崩溃恢复与优雅停（§3.4）；shutdown 时 SIGTERM
```

### 3.2 单用户守卫

扫描 `{SG_ROOT}/.lark-cli/{emp_no}/` 配置目录（T-701 多用户隔离机制）：
- 恰好 1 个用户满足「feishu_watch.yaml 存在且 lark-cli token 有效」→ 以该用户身份启动；
- 0 个 → 静默不启动（未配置属正常态）；
- >1 个 → WARN 日志告警不启动（二期边界：多用户编排未实现，不猜测取舍）。

### 3.3 子进程纪律（lark-event 契约）

| 契约 | 落实 |
|---|---|
| stdin EOF = 优雅退出 | `stdin=PIPE` 保持打开不关闭（Windows 无 `tail -f /dev/null`，PIPE 持有即保活） |
| 就绪检测 | 先阻塞读 stderr 至 `[event] ready event_key=<key>` 出现，再开始读 stdout；不用 sleep 猜 |
| 禁 kill -9 | minutes/vc 类 key 退出时 OAPI 退订——kill -9 泄漏服务端订阅；关闭只走 SIGTERM |
| 一进程一 key | 3 个 key = 3 个子进程（故障隔离、独立 jq/filter） |
| 退出码 | 0（limit/timeout/signal）= 正常；非 0 → 崩溃恢复流程 |

### 3.4 节流合并与重拉

- 事件入内存队列，按目标 key（chat_id / minute_token）聚合；
- **5 分钟滑动窗口**：窗口内同 key 多事件只触发一次重拉（防消息风暴）；
- 重拉复用一期 `feishu_sync_service.sync_chat(chat_id, 当日)` / `sync_minutes()`——单一代码路径；
- 落池后异步触发：`topic_cluster.cluster_chat_snapshots`（新快照日）+ `link_suggest`（新材料/话题）→ 候选入复核队列；
- 全过程写 watcher 日志（事件计数/节流合并数/重拉成败）供排障。

### 3.5 崩溃恢复与优雅停

- 子进程非零退出 → 指数退避重启（1s→2s→4s→…上限 5min）；连续 5 次失败 → 停摆 + ERROR 日志（不静默自愈，告警等人介入）；
- 后端 shutdown → 先 SIGTERM 全部子进程（等 ≤10s 退出）→ 超时再 terminate；绝不 kill -9；
- 启动 catch-up：`sync_all` 全通道一次（补服务离线期间的变化；幂等——快照覆盖写）。

---

## 4. F2 图片视觉转述

### 4.1 配置

- `model_configs` 表加 vision 模型条目（设置页配置，如 model_id=`vision`）；`LLMClient(model_id="vision")` 实例化；
- **未配置 → 全链路跳过**（transcribe 返回 skipped，一期行为不变，不报错不阻塞）。

### 4.2 转述管线

```
imgmap status=pending 条目
  → 按 media_key 下载（docs +media-download / im +messages-resources-download，只读）
  → 临时文件 → base64 → vision LLM（「用 ≤60 字描述这张图的业务内容」）
  → captions.update_caption(by="vision_llm", status="done") 回填
  → 下载失败/模型失败 → status="failed" + error 字段（诚实呈现，可手动改）
```

### 4.3 双触发

| 触发 | 场景 | 入口 |
|---|---|---|
| 增量后台自动转 | 新入池材料（sync_all / 事件重拉落池后） | 落池钩子异步排队（仅近 7 天快照的 pending） |
| 存量手动转 | 历史材料 pending 积压 | 复核面板「🖼 转述图片」按钮 → `POST /api/feishu-pool/transcribe`（扫当前用户全部 pending） |

临时文件落盘 `.specflow/{emp}/feishu_pool/_tmp/`（转述后删除；media_key 不出私有区铁律不变）。

---

## 5. F3 消息锚点自动焦点

- FocusGraphTab 增强：接收会话最近消息列表（props 注入），正则提取锚点：
  `(FR-[A-Za-z0-9_-]+|AC-\d+|tp:[\w-]+|fd:\w+|fm:\w+)`
- 取**最后提及**的锚点自动 `setNodeId` 渲染；手动输入仍可覆盖（手动优先于自动）；
- 无锚点时保持空态提示（一期行为）；
- 纯函数 `extract_last_anchor(messages)` 独立可测。

---

## 6. F4 文档更新轮询补位

- CLI 事件目录无 docs 域（一期实测）→ scheduler 加每日定时任务：对有 watch 配置的用户执行「文档增量同步」——`drive +search --edited-since 1d --doc-types docx` 发现近 1 天编辑文档 ∩ watch.docs 授权清单 → 重拉落池；
- 与 watcher 互补：事件管 IM/纪要实时级，轮询管文档日级新鲜度；
- 一期「立即同步」手动通道保留不变。

---

## 7. 测试策略

| 层 | 测试 |
|---|---|
| watcher 单用户守卫 | 0/1/N 用户三态（假 .lark-cli 目录 + 假 watch 配置） |
| watcher 子进程 | mock 子进程（假 stderr ready 行 + 假 stdout NDJSON 流）：节流合并（同窗多事件一次重拉）、重拉调 sync_chat 断言、非零退出退避重启、SIGTERM 优雅停 |
| 转述 | mock vision LLM + mock 下载：pending→done 回填；无 vision 配置 skipped；下载失败→failed |
| 锚点检测 | extract_last_anchor 纯函数：多锚点取最后、无锚点空、四前缀识别 |
| 文档轮询 | mock drive +search：交集过滤（仅授权清单内文档落池） |
| e2e | 事件 NDJSON → 节流 → 重拉 → 聚类 → 建议入复核队列（全 mock 贯通） |

---

## 8. 关联文档

- 一期设计（已实施）：docs/远期设计/SpecGuard-飞书知识图谱设计-面试素材溯源.md
- 一期实施计划：docs/upgrade-plans/2026-08-13-飞书知识图谱一期实施计划.md
- lark-event 技能契约：.qoder/skills/lark-event/SKILL.md（子进程纪律/事件目录）
- 飞书 CLI 多用户隔离：总控文档 §4.6（T-701 USERPROFILE 注入）
