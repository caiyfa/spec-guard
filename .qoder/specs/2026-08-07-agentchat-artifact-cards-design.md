# AgentChat 会话产物卡片与排版呼吸感优化 — 设计文档

- 日期：2026-08-07
- 状态：已获用户确认（交互形式 + 排版力度两档关键决策）
- 触发会话：`20260807_134456_04b38595`（工号 90024166 / 工作区 tdm）
- 涉及文件：`workbench/frontend/src/pages/AgentChat.tsx`（主）、`workbench/frontend/src/components/FileViewer.tsx`（复用，不改）

---

## 1. 背景与问题

会话 `20260807_134456_04b38595` 暴露三类体验问题：

1. **产出文件无法从对话流预览**：Agent 两次 `write_draft`（`0807-ACT-001.yaml`、`SG-ENGINE-IDENTITY-REQ.md`），对话流中只有折叠工具组里的一行摘要（「write_draft · ✅ · 已写入草稿…」），用户必须手动切到右侧「草稿产物」页签才能查看文件。
2. **大段 markdown 以源码框展示**：Agent 将需求文档全文以 ` ```markdown ` 代码块贴在回复中（4900 字符），被 `pre` 渲染为黑底等宽滚动框（`max-h-80`），标题/表格全是源码，无法直接阅读排版效果。
3. **会话内容无间距、抓不到重点**：消息间距 `mb-2`（8px）、段落 `my-1`（4px）、标题层级扁平（h1=`text-base` / h2=`text-sm` / h3=`text-xs`），assistant 消息无任何容器与用户气泡区分，长对话糊成一片。

## 2. 决策记录（用户已选定）

| 决策点 | 选项 | 结果 |
|--------|------|------|
| 大段 md 内容呈现 | 文件卡片取代源码框 / 代码框加预览切换 / 两者结合 | **文件卡片取代源码框** |
| 排版疏密档位 | 轻度 / 中度 / 显著 | **中度**（轮次分段 + 标题层级拉开 + assistant 轻量容器） |
| 实现策略 | A 统一产物卡片 / B 工具块内嵌按钮 / C 文本末尾产物区 | **A 统一产物卡片** |

## 3. 已有基建（复用，不新增依赖）

- `openFileViewer(path, kind)`（AgentChat.tsx:2022）：右侧面板 fileTabs 页签预览，幂等激活；面板收起时自动展开、宽度自动 ≥460。
- `FileViewer`（components/FileViewer.tsx）：.md → react-markdown + mermaid + 大纲导航；.yaml → 语法高亮 + 结构大纲；办公文档保真预览。
- `sessionDrafts`（AgentChat.tsx:1473）：已从 messages 扫描 `write_draft` 提取文件名列表（`undo_draft` 会移除）。
- `MD_COMPONENTS` / `MarkdownText`（AgentChat.tsx:118/155）：对话内 react-markdown 渲染管线。
- `groupMessages`（AgentChat.tsx:215）：扁平消息 → 分组项（user / assistant-text / tool-group / step-complete）。

## 4. 设计

### 4.1 ArtifactCard 组件（新增，AgentChat.tsx 内）

对话流中统一的可点击产物卡片。

**Props**：

```ts
interface ArtifactCardProps {
  title: string;            // md 首个 `#`/`##` 标题；fallback 文件名
  fileName?: string;        // 已落盘文件名（匹配到 write_draft 时存在，用于卡片标注）
  path?: string;            // 传给 openFileViewer 的标识：kind='draft' 时为文件名（draftsApi.read 按文件名取），kind='file' 时为工作区相对路径
  kind?: 'file' | 'draft';  // openFileViewer 的 kind
  content?: string;         // 未落盘内容（点击走 openContentViewer）
  meta: string;             // 元信息行：「42 行 · 3.8 KB · Markdown」
}
```

**视觉**：`border border-border bg-surface-2/40 rounded-lg px-3 py-2`，整卡可点击，hover `border-info/40`；左侧 📄 图标，中间标题（`text-sm text-gray-200`）+ 元信息（`text-[10px] text-gray-500`），右侧「预览 ›」（`text-xs text-info/70`）。

**点击行为**：
- 有 `path` → `openFileViewer(path, kind ?? 'draft')`（现有机制，右侧页签打开 FileViewer）。
- 仅 `content`（未落盘 md 代码块）→ 新增 `openContentViewer(title, content)`：构造虚拟 FileTab `{ path: 'memo:{title}.md', kind: 'file', content, loading: false }` 直接注入 fileTabs，跳过文件读取；FileViewer 按扩展名 `.md` 走 MarkdownViewer 渲染。关闭页签走现有 `closeFileTab`（按 path 过滤，天然兼容）。

### 4.2 挂载点一：write_draft 产物卡片（需求 1）

`groupMessages` 处理 assistant 消息的 `tool_calls` 时，检测 `write_draft`：
- 解析 `args.filename`（预览标识）与对应 tool 结果 JSON 的 `size`（元信息）；工具结果中的完整路径仅展示用，`draftsApi.read` 按文件名取内容。
- 在**该工具组之后**插入新分组项 `{ type: 'artifact', artifacts: [{ title, fileName, path: filename, kind: 'draft', meta }] }`。
- 渲染位置独立于折叠工具组——工具组收起时产物卡片仍常驻可见（yaml 类无文本对应的产物唯一入口）。
- `GroupedItem` 增加 `type: 'artifact'` 与 `artifacts?: ArtifactInfo[]` 字段；`renderGrouped` 增加对应分支（`mb-3`）。

### 4.3 挂载点二：大段 markdown 代码块卡片化（需求 2）

`MD_COMPONENTS.pre` 增强：
- 判定条件：子节点 `code` 的 className 含 `language-markdown` 或 `language-md`，且内容**非空行数 ≥ 8**。
- 满足 → 渲染 `ArtifactCard`：
  - `content` = 代码块全文；`title` 取内容首个 markdown 标题文本（正则 `^#{1,3}\s+(.+)$` 首个匹配，fallback「Markdown 文档」）。
  - 内容 trim 后与本会话任一 `write_draft` 的 `args.content` trim 相等 → 视为已落盘：卡片标注该文件名，点击 `openFileViewer(filename, 'draft')` 开草稿预览；否则点击 `openContentViewer` 开内容预览。
  - 匹配所需数据：从 `messages` 派生 `Map<contentTrim, filename>`（`useMemo`，与 sessionDrafts 同一扫描逻辑），通过 React context 或 props 传入 MarkdownText。
- 不满足（小段 md、其他语言）→ 保持现有源码框不变。
- 去重语义：已落盘的 md 代码块卡片与 4.2 的产物卡片指向同一文件，是同一份内容的两个入口（文本内位置锚点 + 时间线产物记录），`openFileViewer` 幂等激活同一页签，不构成冗余困扰。

### 4.4 排版呼吸感（中度档，MD_COMPONENTS + renderGrouped）

| 元素 | 现状 | 调整为 |
|------|------|--------|
| 用户轮次（renderGrouped user） | `mb-2` | `mt-4 mb-2`（首条除外），轮次间视觉分段 |
| assistant 文本 | `mb-2 px-1 py-1` 无容器 | `mb-3 ml-1 border-l-2 border-border/50 pl-3 py-0.5` 轻左边框区分角色 |
| thought 思考文本 | `mb-1.5` | `mb-2`（维持轻量样式） |
| tool-group / step-complete / artifact | `mb-2` | `mb-3` |
| h1 | `text-base mt-2 mb-1` | `text-lg font-bold text-gray-100 mt-4 mb-2` |
| h2 | `text-sm mt-2 mb-1` | `text-base font-semibold text-gray-100 mt-3.5 mb-1.5 pb-1 border-b border-border/40` |
| h3 | `text-xs mt-1.5 mb-0.5` | `text-sm font-semibold text-gray-200 mt-3 mb-1` |
| h4 | `text-xs mt-1 mb-0.5` | `text-xs font-semibold text-gray-300 mt-2 mb-1` |
| p | `my-1 leading-relaxed` | `my-2 leading-7` |
| ul / ol | `my-1 space-y-0.5` | `my-2 space-y-1` |
| table 容器 / 单元格 | `my-1` / `px-1.5 py-0.5` | `my-2.5` / `px-2.5 py-1` |
| pre / blockquote | `my-1 p-2` / `my-1 pl-2` | `my-2.5 p-3` / `my-2.5 pl-3` |
| hr | `my-1` | `my-3` |

流式气泡（streamingText）与正式 assistant 文本共用同一容器样式，保证流式→定稿视觉无跳变。

## 5. 明确不做（YAGNI）

- yaml / 其他语言代码块不卡片化（场景 YAML 用户需看源码细节；落盘 YAML 已由 4.2 覆盖预览入口）。
- 非空行 < 8 的小段 md 保持源码框。
- 右侧预览机制（fileTabs / FileViewer / 面板宽度逻辑）本身不改。
- 不新增前端依赖；不引入 modal 预览（统一走右侧页签）。
- assistant 文本中的文件路径纯文本不转可点击链接（误判风险，产物卡片已覆盖主路径）。

## 6. 测试与验证

1. `cd workbench/frontend && npx tsc --noEmit` 零错误；`npm run build` 通过。
2. 打开会话 `20260807_134456_04b38595` 实测：
   - 0807-ACT-001.yaml：工具组后出现产物卡片 → 点击右侧 yaml 高亮预览。
   - SG-ENGINE-IDENTITY-REQ.md：文本内 md 代码块变为卡片（匹配落盘，标注文件名）→ 点击右侧 MarkdownViewer 渲染预览。
   - 排版目检：轮次分段、标题层级、表格/代码块间距符合中度档。
3. 新会话回归：小段 md / yaml 代码块仍为源码框；`undo_draft` 后产物卡片不再出现（sessionDrafts 同源逻辑）。

## 6.5 实现期修正（浏览器实测发现）

**问题**：后端 `routers/drafts.py` `_guard_filename` 仅放行 `.yaml/.yml`，而 `write_draft` 允许写 `.md`——产物卡片对 `.md` 文件调 `draftsApi.read` 被 400 拒绝。

**决策（前端规避，不改后端语义边界）**：非 yaml 产物卡片携带 `args.content` 会话快照，点击走 `openContentViewer`（memo: 虚拟页签）而非 draftsApi；yaml 产物保持 draftsApi 路径（读磁盘最新内容）。`ArtifactInfo` 增加 `formatLabel` 字段（无 fileName 的内容卡片显示「Markdown」标签）。

**残留（既有缺陷，未修）**：右侧「草稿产物」面板对 `.md` 草稿的 `GET /drafts/{file}/conflict` 冲突检查仍 400（后端守卫同源问题），面板内 .md 的「查看」按钮同理。待用户决策：后端只读端点对 .md 放行，或 MCP write_draft 收紧为仅 yaml。

## 7. 风险

- **内容匹配成本**：`Map<contentTrim, filename>` 按会话级消息数构建，体量小（本会话 122 条 assistant 消息），O(n) 可忽略。
- **pre 判定误伤**：仅 `language-markdown/md` + ≥8 行触发，YAML/日志等源码框不受影响。
- **虚拟 FileTab 与真实文件同名**：`memo:` 前缀与文件路径命名空间隔离，`closeFileTab` 按 path 精确匹配，无冲突。
