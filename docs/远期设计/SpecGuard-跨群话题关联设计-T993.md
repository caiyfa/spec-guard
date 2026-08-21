# SpecGuard 跨群话题关联设计（T-993）

- 日期：2026-08-21
- 状态：设计稿（待总控人评审后动工——施工单硬性前置）
- 任务：T-993（§4.11 M-D 链末位，依赖 T-992 ✅ + 本设计评审）
- 上游：T-991 schema v3（category/priority）；T-992 建边建议生产接线 + 模块 FR 派生

---

## 1. 背景与问题

同一主题的讨论天然跨群发生：产研群聊方案、测试群跟进 bug、用户群反馈现象、项目群同步进展。
现状话题卡按「群 × 天」聚类（id = `tp:{chat_sha8}-{day}-{seq}`），同一主题散落多张卡：

1. 无聚合视角——想看"这个需求各群都聊了什么"要人工逐群翻；
2. 无关联发现——跨群的同主题卡之间没有任何语义连接；
3. 证据割裂——面试/归因时同一主题的多群证据无法并排呈现。

## 2. 现状与约束（实测）

- **id 稳定铁律**：图谱从文件派生而非重跑 LLM，`_topics.yaml` 的卡 id 以
  `tp:{chat_sha8}-{day}-{seq}` 锚定单群单日；`_merge_one` 仅同群归并。
- **卡字段**：`chat_sha8` 单值；`continues` 单值（同群演进链，builder 派生 evolves 边）。
- **事实源**：`material_links.yaml`（facts.py）存 confirmed/rejected 边，
  `is_rejected` 防重复建议；builder 仅消费 confirmed。
- **图谱边**：mentions（材料→FR）/ evolves（话题演进）/ contains / covers 等，
  均经 `upsert_edge`；material_links 的 mentions 边要求 src/dst 均为已存在节点。
- **复核队列**（T-991 起支持 mine/shared）：语义是"材料→FR 建边建议"，
  confirm 会触发 `_promote_material`（提升语义）。

## 3. 关键决策

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 关联形态 | **relates_to 边，不合并卡、不加聚合字段**（对施工单"source_chats 聚合"预设的修正） | ①不破坏 id 稳定铁律（改 id 方案=全量卡迁移+图谱重build）；②单群卡仍是各群忠实记录，合并卡必然丢群上下文；③"聚合"由视图层做——relates_to 边的连通分量天然支持 ≥2 群扩展；④自动合并被施工单明令禁止（只推荐不自动合并），人工合并卡成本高且不可逆 |
| D2 | 关联存储 | 复用 `material_links.yaml`：`edge="relates_to"`，src/dst 均为 `tp:` id | 事实源单一（confirmed/rejected 留痕、防重复建议机制全部白得）；builder 加一种边类型即可，不新增文件 |
| D3 | 推荐算法 | **两段式：确定性预筛（零 LLM）+ LLM 精筛（可选）** | 预筛纯读可高频：跨群 + 时间窗 ≤7 天 + 标题相似 ≥0.5 或 keywords 交集 ≥1 + category 同类且非 chat；LLM 精筛对候选对判"是否同一主题"（text 模型缺失时诚实降级只用确定性分，展示"未经模型复核"标注） |
| D4 | 推荐呈现与确认 | **话题工作台内推荐位**（跨群推荐卡：两张卡并排对照 + 关联/忽略），不复用 FR 复核队列 | FR 队列 confirm 触发材料提升语义，与卡-卡关联不适配；且跨群推荐需要看卡上下文才能判断，工作台是唯一有该上下文的地方；忽略写 rejected 边（复用防重复推荐机制） |
| D5 | 触发时机 | 确定性预筛随 `list_pool_topics` 即时计算（纯读零成本）；LLM 精筛由前端"复核推荐"按钮按需触发，结果进程内缓存（TTL 5min，不落盘） | 推荐不是事实，不进事实源；人确认的 relates_to 边才是事实 |
| D6 | 图谱消费 | builder 派生 `relates_to` 边（tp↔tp，confirmed 且两端节点存在） | 与 mentions 同模式；断链不建边（诚实） |
| D7 | 前端视图 | 卡上「🔗 N 群」徽标 + 关联抽屉（并排各群卡：标题/摘要/群名·类型/时间，点击跳该群该日原文）；闲聊（chat 类）不参与关联 | 并排=多群证据视图的最小实现；TopicWorkspace 已有群/日路由能力，跳转零新页面 |

## 4. 分块设计

### F1 推荐引擎（specflow/feishu_pool/cross_chat.py 新建）

```python
def suggest_cross_chat_relations(topics: list[dict],
                                 rejected: set[tuple[str, str]]) -> list[dict]:
    """确定性预筛：跨群卡两两配对 → 候选关联（纯读零 LLM）。

    条件全满足才入选：
    - 两卡 chat_sha8 不同（跨群）
    - category 相同且非 chat（闲聊跨群关联无意义）
    - 时间窗重叠或间距 ≤7 天
    - 标题 SequenceMatcher 相似 ≥0.5 或 keywords 交集 ≥1
    - (src, dst) 未被 rejected（防重复推荐，键规范化小 id 在前）
    返回 [{src, dst, score, reasons}]（score=相似度+keywords 交集加权）。
    """

def refine_with_llm(candidates: list[dict], topics_by_id: dict, llm) -> list[dict]:
    """LLM 精筛（可选）：逐候选对判同一主题，附 confidence/reason；
    模型异常诚实降级返回原候选（标注 unrefined=True）。"""
```

### F2 确认与留痕（复用 facts + 路由新端点）

- `POST /api/feishu-pool/topics/relate`：body {a, b, confirmed}——confirmed=true
  写 `facts.append_link(edge="relates_to", status="confirmed")`；false 写 rejected
  （防重复推荐留痕）。两端 id 必须存在于话题库（404 校验）。
- `GET /api/feishu-pool/topics/relations`：返回全部 confirmed relates_to 边
  （供前端徽标与关联抽屉；也可并入 list_pool_topics 响应，取独立端点避免
  主清单响应膨胀）。

### F3 图谱与前端

- builder：material_links 消费段加 relates_to 分支（tp↔tp，两端存在才建边）。
- TopicWorkspace：卡列表加载后请求 relations；卡渲染「🔗 N 群」徽标；
  徽标点击开关联抽屉（并排卡 + 跳原文）；顶栏加「跨群推荐」入口
  （预筛结果 + 可选 LLM 精筛 + 关联/忽略操作）。

## 5. 任务拆解

| 块 | 内容 | 主要文件 |
|---|---|---|
| F1 | 推荐引擎（预筛+LLM 精筛） | specflow/feishu_pool/cross_chat.py（新）+ 测试 |
| F2 | relate/relations 端点 + facts 边 | routers/feishu_pool.py + facts.py（零改动，复用 append_link） |
| F3 | builder relates_to 边 + 前端徽标/抽屉/推荐位 | graph_index/builder.py + TopicWorkspace.tsx + api.ts |

## 6. 测试策略

- cross_chat 预筛：跨群配对命中/同群排除/chat 排除/时间窗外排除/rejected 排除/
  连通分量（A-B、B-C → A 的关联视图含 C）；
- relate 端点：确认写边、忽略写 rejected、未知 id 404、relates_to 不触发材料提升；
- builder：relates_to 边派生 + 断链（端点卡不存在）不建边；
- LLM 精筛：mock 响应过滤/异常降级 unrefined；
- 前端 build + lint 零新增。

## 7. 非目标与边界

- 不自动合并卡、不改 tp id 方案、不加 source_chats 聚合字段（D1）。
- 不做 N>2 的"超级话题"实体——连通分量在视图层表达。
- 闲聊（chat 类）不参与跨群关联；routine 类参与（跨群排期沟通有对照价值）。
- 不改引擎冻结层/specstd 规范层；无三同步义务。
