# SpecGuard 飞书知识图谱设计 · 面试素材溯源

> 版本：v1.1 · 2026-08-14 ｜ 状态：已实施（一期全量交付：批次 A 纯新建 + 批次 B 接线/前端，1551 全量回归 + release_check PASS）
> 定位：把飞书材料（文档/会议纪要/群聊话题）作为新节点类型接入 graph_index 图谱，面试官 Agent 提问自带证据链；LLM 只做建议，人批量复核后落盘，图谱从确定性事实源派生。
> 关联：M02（需求面试引擎）、M03（材料包与信息包，G7 飞书拉取通道）、M10/M11（血缘链与图谱索引）、T-071（全景图谱 GraphPanorama）、T-073（血缘链挂链）、S2 飞书 CLI 能力背景文档。

---

## 1. 背景与目标

### 1.1 问题

面试官 Agent（M02）提问的素材（会议纪要/群聊讨论/PRD 文档）存在于飞书生态。S2 背景文档已验证「飞书 CLI 只读拉取」链路，但当前模式是**按需抓取**——对话中用户贴链接或 Agent 现场搜索，存在两个缺口：

1. **无关联沉淀**：材料与 FR/决策之间的关联靠人脑记忆，每次面试重新发现；
2. **群聊信息流丢失**：需求讨论群里的关键结论随消息流冲走，无法回溯到 FR。

### 1.2 目标

- 飞书材料（文档/妙记/群聊话题）成为图谱一等节点，与 FR/决策/场景同图关联；
- 面试官 Agent 提问时经 `trace_backward` 自然追溯到关联材料（证据链）；
- 工作台提供**双层视图**：全局网状图谱（GraphPanorama 扩展）+ 对话侧栏焦点子图。

### 1.3 非目标（YAGNI）

- 不做实时事件驱动图谱（二期再议事件监听常驻）；
- 不做全公司内容监听——仅用户显式授权的群/文档；
- 不做图片/音视频的图谱节点（图片走替身文本，见 §9）；
- 不引入 NetworkX 等独立图存储——复用 graph_index（SQLite 派生索引）。

---

## 2. 关键决策记录（设计评审结论）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 第一用户场景 | **面试素材溯源** | 面试官提问自带证据链，与 M02/M03/S2 直接衔接 |
| D2 | 建边策略 | **LLM 候选边（依据+置信度）→ 人批量复核 → 落盘派生** | LLM 不直接写图谱，符合确定性派生铁律与三道闸哲学 |
| D3 | 节点粒度 | **文档/纪要整份一节点；群聊按 LLM 话题聚合** | 单条消息节点会撑爆图谱；话题级兼顾规模与精度 |
| D4 | 渲染入口 | **双层视图**：全局网状页 + 对话侧栏焦点子图 | 概览导航与工作场景分离，一套数据两个视图 |
| D5 | 架构方案 | **扩展 graph_index 派生管线**（方案 A） | 复用现有图谱单一事实源；FR/场景/决策节点零重复 |
| D6 | 图片处理 | **占位符 + 替身文本**（imgmap 分离存储） | 兼容纯文本 LLM 基线；视觉模型可选增强；人工补写兜底 |

---

## 3. 架构总览（五层数据流）

```
┌─ 采集层 ── 一期：手动/定时拉取（复用 feishu_fetch 五工具，全只读）
│             原文快照 → .specflow/{emp}/feishu_pool/（材料池，跨面试复用）
│             图片默认不下载：正文留占位符 + imgmap 记 media_key（§9）
│             二期：lark-cli event consume 常驻 → NDJSON 事件日志（§10）
├─ 提炼层 ── LLM 作业（产出必须落盘 + 过确定性后处理才生效，§6）
│             话题聚类：群聊快照 → 候选话题（标题/摘要/消息区间）
│             建边建议：材料+话题 × FR 锚点表 → 候选边（依据+置信度）
├─ 闸门层 ── 前端「关联复核」面板：批量勾选 → 确认/拒绝（人拍板，§7）
│             确认 → 落 {ws}/.specguard/feishu/material_links.yaml（共享事实源）
│             同时：材料快照/话题摘要从私有区「提升」到共享区（§5.3）
├─ 派生层 ── graph_index.builder 新增飞书段（§4）
│             读共享区事实源 → feishu_doc/feishu_minutes/topic 节点 + mentions 边
│             事实源文件纳入 source_fingerprint（变更自动重建，零新机制）
└─ 呈现层 ── 双层视图（§8）
              全局：GraphPanorama 新增「网状」镜头（React Flow 力导向）
              侧栏：AgentChat 焦点子图（当前议题 FR 的 N 跳邻居）
              Agent：trace_backward 自然延伸（FR 向上追到话题/纪要，零新工具）
```

---

## 4. 图谱数据模型扩展

### 4.1 新增节点类型（graph_index/store.py NODE_TYPES 追加 3 个）

| 节点类型 | id 规范 | stage | attrs | source_ref |
|---|---|---|---|---|
| `feishu_doc` | `fd:{doc_token}` | req | url / sha / fetched_at / source(listen\|fetch) | 共享区快照文件 |
| `feishu_minutes` | `fm:{minute_token}` | req | url / sha / meeting_id / title | 共享区快照文件 |
| `topic` | `tp:{chat_sha8}-{yyyymmdd}-{seq}` | req | summary / message_count / window / participants_count | topics.yaml 行区间 |

**ID 确定性**：fd/fm 用飞书 token（天然唯一稳定）；tp 由话题归并规则保证（§6.3）——图谱从 topics.yaml 文件派生而非重跑 LLM，「删库重建同图」由文件保证。

### 4.2 新增边类型

`mentions`（材料/话题 → FR 或 decision），attrs：

```json
{"confidence": 0.86, "evidence": "纪要 §2 明确提到『全景档案导出按平台过滤』",
 "confirmed_by": "caiyunfei", "confirmed_at": "2026-08-13T10:00:00"}
```

不复用 `references` 的原因：references 是人工登记的强引用（禅道 story 类）；mentions 是「内容提及」语义、带 LLM 置信度留痕——backlink 报表可区分两类。

### 4.3 确定性纪律

- builder 派生段只读共享区三个事实源文件，**绝不直接消费 LLM 产出**；
- 三文件全部纳入 `compute_source_fingerprint`（变更 → stale → ensure_fresh 自动重建）；
- 排序写入与同图重建铁律不变（飞书段同样全排序）。

---

## 5. 落盘结构（私有/共享双区）

### 5.1 目录布局

```
.specflow/{emp}/                              # 用户私有区（随用户）
├── feishu_pool/                              # 材料池：拉取快照
│   ├── docs/fd-{token}.md                    # 文档 markdown（图片留占位符）
│   ├── docs/fd-{token}.imgmap.json           # 图片替身文本映射（§9）
│   ├── minutes/fm-{token}.json               # 妙记 detail JSON
│   └── chats/{chat_sha8}/{yyyymmdd}.md       # 群聊快照（群×天）
├── feishu_events/                            # 二期：事件原始日志 NDJSON（永不出私有区）
└── feishu_watch.yaml                         # 同步/监听配置（本人显式授权范围，§11）

{workspace}/.specguard/feishu/                # 工作区共享区（随工作区，人确认后提升）
├── topics.yaml                               # 话题事实源（摘要级，已脱敏）
├── material_links.yaml                       # 关联边事实源（含 LLM 依据+置信度留痕）
└── materials/                                # 提升后的材料快照副本（图谱 source_ref 只指这里）
    ├── fd-{token}.md
    └── fm-{token}.json
```

### 5.2 事实源文件格式

`material_links.yaml`：

```yaml
version: 1
links:
  - src: tp:3f9a2c-0807-01
    dst: FR-person-profile-0817-001
    edge: mentions
    confidence: 0.86            # LLM 原始置信度（留痕，不参与派生逻辑）
    evidence: "纪要 §2 明确提到『全景档案导出按平台过滤』"
    status: confirmed           # confirmed | rejected（rejected 防重复建议）
    confirmed_by: caiyunfei
    confirmed_at: 2026-08-13T10:00:00
```

`topics.yaml`：

```yaml
version: 1
topics:
  - id: tp:3f9a2c-0807-01
    title: 全景档案导出权限过滤讨论
    summary: 产品确认结果侧按 corpCode+groupLevel 过滤无权限平台行……
    chat_sha8: 3f9a2c           # 群 id 脱敏（sha 截断，原始 chat_id 只在私有区）
    window: ["2026-08-07T14:00", "2026-08-07T15:30"]
    message_count: 23
    participants_count: 4
    source: chats/3f9a2c/20260807.md   # 指针（仅材料属主私有区可解析）
```

### 5.3 私有 → 共享提升规则

- 复核确认一条边时：涉及的材料快照复制进共享区 `materials/`，话题摘要写入共享区 `topics.yaml`；
- 图谱节点 source_ref **只指共享区文件**，保证同工作区所有用户可定位；
- 原始群聊快照、事件日志、imgmap 中的 media_key **永远留在私有区**——不进图谱、不被其他用户读取；
- 拒绝（rejected）的记录写共享区 `material_links.yaml`（`status: rejected`）——防重复建议需工作区级生效；builder 派生时过滤，rejected 边不进图谱。（v1.1 实施修订：原为「只留私有区」，实施中发现防重复建议须跨用户可见）

### 5.4 删除语义

- 工作区删除 → 共享区（图谱+确认事实源）随之失效；
- 用户离开 → 私有区（原始快照/监听配置）随之清理，已确认的共享事实保留；
- graph_index.db 删除 → 无所谓，指纹失配自动重建（派生物）。

---

## 6. LLM 作业管线（提炼层）

### 6.1 两个离线作业

| 作业 | 输入 | 产出 | 触发 |
|---|---|---|---|
| 话题聚类 | 群聊快照 `chats/{chat_sha8}/{yyyymmdd}.md` | 候选话题（title/summary/消息区间/参与人数） | 新快照入库自动排队 + 手动「整理」按钮 |
| 建边建议 | 材料正文+话题摘要 × FR 锚点表（specstd.anchors 全量） | 候选边（fr_id/confidence/evidence 原文摘录） | 话题确认后 + 新材料入池后 |

LLM 输入 = 正文 + 图片替身文本拼装（§9），对纯文本模型透明。

### 6.2 防幻觉确定性后处理（机器版硬约束）

1. 建议的 `fr_id` 必须存在于 anchors 扫描结果——不存在直接丢弃，不进复核队列；
2. `evidence` 必须是材料/话题原文的**子串**（可机校验）——找不到标记 `invalid`，展示但不可确认；
3. 已 rejected 的 (src, dst) 对不再重复建议。

### 6.3 话题 id 稳定性（增量归并）

LLM 聚类两次结果可能不同，id 稳定性由**文件归并规则**保证：

- 新候选话题与 topics.yaml 已有话题比对：时间窗重叠 + 标题相似 → 沿用旧 id，追加消息区间与摘要修订；
- 全新话题 → `tp:{chat_sha8}-{yyyymmdd}-{当日最大seq+1}`；
- 图谱派生只读文件——重建不需要 LLM 复现。

---

## 7. 复核 UI（闸门层）

工作台新增「关联复核」面板（挂材料包页签）：

- **表格行**：材料/话题（类型徽标+标题）→ 建议 FR（id+title）｜置信度条｜依据（展开显示原文摘录，含图片替身文本）｜确认/拒绝；
- **批量操作**：置信度阈值过滤（如 ≥80% 全选）、批量确认、批量拒绝；
- **确认动作**：写 material_links.yaml + 提升共享区 → 指纹变化自动重建图谱；
- **拒绝动作**：私有区落 `status: rejected` 留痕；
- **权限**：只能复核**本人拉取**的材料（私有区属主）；确认前对他人不可见。

---

## 8. 双层渲染（呈现层）

| 视图 | 位置 | 数据接口 | 交互 |
|---|---|---|---|
| 全局网状 | GraphPanorama 新增第 4 镜头「网状」 | `/api/graph/panorama` 扩展 `?lens=network` 返回全量节点+边 | React Flow + 力导向布局；飞书节点新色系；mentions 边虚线；点击节点 → 右侧详情+backlink+source_ref 跳转 |
| 焦点子图 | AgentChat 对话侧栏 | 新端点 `GET /api/graph/focus?node_id=FR-xxx&depth=2`（BFS N 跳，复用 trace 遍历骨架） | 面试官开议题即显该 FR 关联材料/话题/决策；点材料节点弹摘要预览 |

**性能护栏**：全局网状 >500 节点默认退回 L0 聚合态（模块级节点），点击展开再力导向。

---

## 9. 图片处理（替身文本方案）

飞书材料中图片普遍（报错截图/表结构/设计稿），而部署环境 LLM 不保证多模态——**图片从不直接进入 LLM 上下文，由替身文本替代**：

### 9.1 机制

- 采集入池：图片**默认不下载**，正文留占位符 `[图片#N]`，配套 `{material}.imgmap.json` 记录 media_key；
- 图片转述（可选异步作业）：配置了视觉模型时下载图片 → 生成 caption → 回填 imgmap（`caption_by: vision_llm`）；未配置则跳过，不阻塞管线；
- 人工兜底：复核 UI 展示原图（按需下载本地缓存），复核人可手改/补写 caption（`caption_by: manual`）；
- LLM 作业输入 = 正文 + 替身文本拼装（`[图片#2: 系统架构图：……]`）。

### 9.2 imgmap 格式

```json
{
  "图片#2": {
    "media_key": "img_v3_xxx",
    "caption": "系统架构图：AgentChat → 图谱服务 → SQLite……",
    "caption_by": "vision_llm",
    "status": "done"
  }
}
```

### 9.3 为什么 imgmap 与原文分离

1. 原文快照保持「拉取时刻冻结」可复算（sha256_12 不被回填污染）；
2. caption 是派生物，允许重生成/人工修正而不动原文；
3. imgmap 不进图谱、不出私有区（原图媒体 key 属敏感引用）。

---

## 10. 监听服务分期

### 一期（本设计实施范围）：手动/定时拉取

- `feishu_watch.yaml` 配置同步范围（群列表/文档列表/时间窗）——**即显式授权载体**，前端勾选写入；
- scheduler 定时拉取（复用 workbench scheduler）+ 「立即同步」按钮；
- 事件监听能力已实测（lark-cli event list 25 事件：IM 12 / VC 7 / minutes 1 等），一期不接入常驻。

### 二期（增强，不在本设计）：事件监听常驻

- `lark-cli event consume` 子进程托管（FastAPI 生命周期管理：stdin 保活防 EOF 退出、SIGTERM 优雅停、禁 kill -9 防订阅泄漏、崩溃重启 + `minutes +search`/`drive +search` catch-up 补拉离线窗口）；
- 事件落 `feishu_events/`（私有区）→ 触发增量聚类；
- **已知能力缺口**：CLI 事件目录无 docs/drive 域（文档/多维表格更新无事件），二期仍靠轮询补位或扩展 lark-cli。

---

## 11. 授权与隐私边界

| 边界 | 规则 |
|---|---|
| 显式授权 | `feishu_watch.yaml` 由用户前端勾选群/文档后写入；OAuth scope 走 lark-shared split-flow；bot 进群本身即授权动作 |
| 身份边界 | 拉取内容一律 `--as user`；事件监听二期 IM 走 bot（入群才可收）、minutes/vc 走 user（参与者视角）——非全量监听 |
| 私有/共享 | 未确认材料永在私有区；复核确认 = 提升共享的唯一闸门 |
| 飞书侧只读红线 | 采集层全部只读命令，绝不写飞书资源（沿用 S2 背景文档铁律） |

---

## 12. 测试策略

| 层 | 测试 |
|---|---|
| 派生确定性 | test_specstd 新增：构造 topics.yaml/material_links.yaml fixture → build_index → 逐条断言节点/边一致；删库重建同图 |
| 提升规则 | 复核确认后私有→共享复制成功、source_ref 只指共享区、rejected 不进共享区 |
| 指纹保鲜 | 三事实源文件任一变更 → status stale=true → ensure_fresh 自动重建 |
| 防幻觉后处理 | 伪造 fr_id 被丢弃；evidence 非原文子串标 invalid 不可确认；已拒绝建议不重复出现 |
| LLM 管线 | mock LLM 产出测管线流转，不做内容断言 |
| 前端 | 复核面板批量确认写盘；焦点子图按 node_id 渲染 N 跳邻居 |

---

## 13. 关联文档

- S2 飞书 CLI 能力背景：docs/远期设计/SpecGuard-飞书CLI能力背景-S2面试材料获取.md
- M02 需求面试引擎 / M03 材料包与信息包 / M04 决策台账：docs/远期设计/specguard-module-design/
- M10/M11 血缘链与图谱索引：graph_index/ 包 + docs/远期设计/ 对应模块设计
- 全景图谱前端：workbench/frontend/src/pages/GraphPanorama.tsx（T-071）
