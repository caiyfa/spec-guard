# AgentChat 多轮会话导航增强：置顶栏 + 用户消息定位图标列

## Summary

多轮会话场景下，Agent 回复很长时用户容易丢失「当前请求是什么」「之前问过什么」。本设计两项增强：
① 对话区顶部**置顶栏**——始终展示最近一条用户消息，可手动收起，新消息到达自动恢复；
② 对话区消息列表**左侧迷你地图图标列**——每条用户消息一个圆点，hover 放大 + 悬浮预览内容，点击滚动定位 + 短暂高亮。

仅改动 `workbench/frontend/src/pages/AgentChat.tsx`（约 +120 行，遵循 TruncText / ToolGroupBlock 内联组件惯例）。

---

## Part 1: 顶部置顶栏（PinnedBar）

- **位置**：顶部信息栏与消息列表之间（消息列表容器上方），`flex-shrink-0`，不挤压消息区
- **数据**：`messages` 中最后一个 `role === 'user'` 的消息，内容经 `stripRefBlock` 剥离引用块
- **展示**：单行 `truncate`，前缀 📌 图标，半透明背景（`bg-info/5 border border-info/20`），视觉轻于正式消息
- **行为**：
  - 右侧 `×` 按钮手动收起 → 本地 state `pinnedDismissed = true`
  - **新用户消息到达时自动重新展开**（`pinnedDismissed` 在检测到新的用户消息时重置为 false）——保证「最近一条」永远可见
  - 无用户消息时不渲染（空会话 / 纯系统消息）
- **流式期间**：`streamingText` 流式回复不改变置顶内容（置顶的是用户消息，不随 assistant 流式变化）

## Part 2: 左侧迷你地图图标列（UserMsgRail）

- **位置**：消息列表容器内左侧 `absolute` 覆盖（`left-1 w-3`），不占布局、不遮挡消息；容器需挂 ref（复用为定位与滚动计算基准）
- **数据**：从 `grouped` 过滤 `type === 'user'` 派生（`useMemo`），每条含 `content`（stripRefBlock 后）、`references`、`grouped` 中的索引
- **显示条件**：用户消息 ≥2 条时才渲染（1 条时无定位意义；置顶栏不受此限制）
- **图标映射（比例映射）**：
  - 用户消息渲染时给外层 div 加 `data-user-idx={userIdx}` 标记
  - 图标 `top = msg.offsetTop / container.scrollHeight × container.clientHeight`
  - 监听容器 `scroll` + `resize`（rAF 节流）实时重算
  - 图标最小间距 8px，超容量时跳过中间项（保留首尾 + 最近）
- **交互**：
  - 平时：4px 圆点 `bg-gray-600`；当前视口内消息对应圆点高亮为 `bg-info`
  - **hover**：圆点 `scale-150` 过渡放大 + 右侧悬浮卡片（`absolute`、`max-w-64`、内容 `line-clamp-2` 截断 + 省略号、附「#N」序号）；鼠标挪走悬浮层立即消失
  - **点击**：定位该消息 `scrollIntoView` + 消息行短暂高亮（`ring-1 ring-info bg-info/10`，1.5s 后自动淡出，`highlightIdx` state 控制）

## Part 3: 数据流与边界

- 置顶消息与图标列数据均从现有 `messages` / `grouped` 派生，无新接口、无后端改动
- 会话切换 / `/new` / `/clear` 时重置：`pinnedDismissed`、`highlightIdx`、图标列
- 聚焦模式（`focusMode`）与右侧面板收起（`sideCollapsed`）不影响本功能（均在对话区内）
- 性能：scroll 监听 rAF 节流；图标列纯 CSS transform，无布局抖动

## 涉及文件

| 文件 | 改动 |
|------|------|
| `workbench/frontend/src/pages/AgentChat.tsx` | 新增 PinnedBar 置顶栏 + UserMsgRail 图标列（内联组件）+ `pinnedDismissed` / `highlightIdx` 状态 + 消息容器 ref + scroll/resize 监听 |

## 验证

1. `cd workbench/frontend && npm run build`（tsc 严格模式编译通过）
2. 浏览器实测多轮会话（≥2 条用户消息）场景：
   - 置顶栏显示最近一条用户消息；发送新消息后置顶内容更新；× 收起后新消息到达自动恢复
   - 图标列：hover 放大 + 悬浮预览（截断 2 行）；挪走消失；点击定位 + 高亮闪烁；滚动时圆点位置跟随比例刷新
   - 空会话不显示置顶栏与图标列

## Assumptions

- 置顶栏与图标列均为纯前端交互增强，不涉及后端/WS 协议改动
- 悬浮预览内容与置顶栏内容均为 `stripRefBlock` 后的纯文本（引用块已在右侧引用面板呈现）
- 「最近一条用户消息」以 `messages` 数组顺序为准（最后出现的 user 消息）
