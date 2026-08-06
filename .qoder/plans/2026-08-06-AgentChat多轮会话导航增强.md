# AgentChat 多轮会话导航增强 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AgentChat 多轮会话场景下新增顶部置顶栏（最近一条用户消息，可收起、新消息自动恢复）+ 消息列表左侧迷你地图图标列（hover 放大+悬浮预览、点击定位+高亮）。

**Architecture:** 纯前端改动，仅改 `workbench/frontend/src/pages/AgentChat.tsx` 一个文件。置顶栏为消息列表容器外的 `flex-shrink-0` 条；图标列绝对定位覆盖在消息容器内左侧，图标位置按消息相对容器的位置比例映射，监听容器 scroll + window resize（rAF 节流）重算。数据全部从现有 `messages` / `grouped` 派生，无后端改动。

**Tech Stack:** React 19 + TypeScript 严格模式 + Tailwind CSS 3.4（line-clamp 为核心工具类）。无前端测试框架，验证 = `npm run build`（tsc -b）+ 浏览器实测。

**Spec:** `.qoder/specs/AgentChat_多轮会话导航增强_置顶栏_与_用户消息定位图标列.md`

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `workbench/frontend/src/pages/AgentChat.tsx` | 全部改动：新增状态（`pinnedDismissed`/`highlightIdx`/`hoverUserIdx`/`railPos`）、数据派生（`userMsgs`/`lastUserMsg`）、置顶栏渲染、图标列渲染、消息容器 ref + 滚动重算 effect、定位与高亮逻辑 |

---

### Task 1: 状态声明与数据派生

**Files:**
- Modify: `workbench/frontend/src/pages/AgentChat.tsx`（状态区：`messagesEndRef` 声明附近，约 L1467）

- [ ] **Step 1: 新增状态与 refs**

在 `const messagesEndRef = useRef<HTMLDivElement>(null);` 之后追加：

```tsx
// ── 多轮会话导航（置顶栏 + 用户消息定位图标列）──
const msgBoxRef = useRef<HTMLDivElement>(null);            // 消息列表滚动容器
const [pinnedDismissed, setPinnedDismissed] = useState(false);  // 置顶栏手动收起
const [highlightIdx, setHighlightIdx] = useState<number | null>(null);  // 定位高亮的 user 消息 groupIdx
const [hoverUserIdx, setHoverUserIdx] = useState<number | null>(null);  // hover 悬浮的 user 消息 groupIdx
const [railPos, setRailPos] = useState<{ idx: number; top: number; inView: boolean }[]>([]);  // 图标列位置
const highlightTimerRef = useRef<number | null>(null);     // 高亮淡出定时器
const lastPinnedRef = useRef('');                          // 上一次置顶的用户消息内容（自动恢复判定）
```

- [ ] **Step 2: 新增数据派生（置顶消息 + 图标列数据）**

在 `const grouped = useMemo(() => groupMessages(messages), [messages]);` 之后追加：

```tsx
// ── 多轮会话导航：置顶最近一条用户消息 + 左侧定位图标列 ──
const userMsgs = useMemo(() => {
  const out: { groupIdx: number; content: string }[] = [];
  grouped.forEach((g, i) => {
    if (g.type === 'user') out.push({ groupIdx: i, content: stripRefBlock(g.content || '') });
  });
  return out;
}, [grouped]);

const lastUserMsg = useMemo(() => {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return messages[i];
  }
  return null;
}, [messages]);
const pinnedText = lastUserMsg ? stripRefBlock(lastUserMsg.content || '') : '';
```

- [ ] **Step 3: 新增图标位置计算函数**

在 `renderGrouped` 定义之前追加：

```tsx
// 图标列比例映射：消息相对容器位置 → 图标 top（px），并标记是否在视口内
const computeRail = useCallback(() => {
  const box = msgBoxRef.current;
  if (!box || userMsgs.length === 0) { setRailPos([]); return; }
  const boxTop = box.getBoundingClientRect().top;
  const h = Math.max(box.clientHeight - 16, 1);
  const positions = userMsgs.map((u, i) => {
    const el = box.querySelector<HTMLElement>(`[data-user-idx="${u.groupIdx}"]`);
    if (!el) return { idx: u.groupIdx, top: 0, inView: false };
    const relTop = el.getBoundingClientRect().top - boxTop + box.scrollTop;
    const top = Math.min(Math.max((relTop / Math.max(box.scrollHeight, 1)) * h, 0), h);
    const inView = relTop >= box.scrollTop - 4 && relTop <= box.scrollTop + box.clientHeight + 4;
    return { idx: u.groupIdx, top, inView };
  });
  // 最小间距 8px：从后往前贪心保留（保最近），再反转为从上到下
  const kept: typeof positions = [];
  for (let i = positions.length - 1; i >= 0; i--) {
    const prev = kept[kept.length - 1];
    if (!prev || prev.top - positions[i].top >= 8) kept.push(positions[i]);
  }
  kept.reverse();
  setRailPos(kept);
}, [userMsgs]);
```

- [ ] **Step 4: 编译验证**

Run: `cd workbench/frontend && npx tsc -b --noEmit`
Expected: 无类型错误（此时新状态/派生未使用，可能报 unused 警告——tsc 若报未使用变量错误则先继续 Task 2 接入后再验证）

---

### Task 2: 顶部置顶栏（PinnedBar）

**Files:**
- Modify: `workbench/frontend/src/pages/AgentChat.tsx`（消息列表容器前，约 L2161）

- [ ] **Step 1: 在消息列表容器上方渲染置顶栏**

在 `{/* 消息列表 — 统一背景 */}` 注释行之前插入：

```tsx
{/* 多轮会话导航：最近一条用户消息置顶（可收起，新消息到达自动恢复） */}
{lastUserMsg && !pinnedDismissed && (
  <div className="flex-shrink-0 mx-4 mt-2 px-3 py-1.5 rounded-lg bg-info/5 border border-info/20 flex items-center gap-2 text-xs">
    <span className="text-info flex-shrink-0">📌</span>
    <span className="flex-1 truncate text-gray-300" title={pinnedText}>{pinnedText}</span>
    <button onClick={() => setPinnedDismissed(true)} title="收起置顶"
      className="text-gray-500 hover:text-info flex-shrink-0 px-1 rounded hover:bg-surface-3">✕</button>
  </div>
)}
```

- [ ] **Step 2: 新用户消息到达自动恢复 + 空会话重置**

在现有的 `useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, turnInfo, streamingText]);` 之后追加：

```tsx
// 置顶栏自动恢复：新用户消息到达时重新展开；会话清空/切换时重置高亮
useEffect(() => {
  const cur = lastUserMsg?.content || '';
  if (cur && cur !== lastPinnedRef.current) {
    lastPinnedRef.current = cur;
    setPinnedDismissed(false);
  }
  if (!cur && lastPinnedRef.current) {
    lastPinnedRef.current = '';
    setPinnedDismissed(false);
  }
  setHighlightIdx(null);
}, [lastUserMsg]);
```

- [ ] **Step 3: 编译验证**

Run: `cd workbench/frontend && npx tsc -b --noEmit`
Expected: 无类型错误

---

### Task 3: 左侧迷你地图图标列（UserMsgRail）

**Files:**
- Modify: `workbench/frontend/src/pages/AgentChat.tsx`（消息列表容器）

- [ ] **Step 1: 消息列表容器挂 ref + relative**

将：

```tsx
{/* 消息列表 — 统一背景 */}
<div className="flex-1 overflow-y-auto px-4 py-3">
```

改为：

```tsx
{/* 消息列表 — 统一背景 */}
<div ref={msgBoxRef} className="relative flex-1 overflow-y-auto px-4 py-3">
```

- [ ] **Step 2: 用户消息行加 data-user-idx 标记与高亮 class**

将 `renderGrouped` 中 user 分支改为：

```tsx
if (item.type === 'user') {
  return (
    <div key={idx} data-user-idx={idx}
      className={`mb-2 flex justify-end transition-all duration-500 ${highlightIdx === idx ? 'ring-1 ring-info bg-info/10 rounded-lg' : ''}`}>
      <div className="max-w-[80%] rounded-lg rounded-br-sm px-3 py-1.5 text-sm bg-info/10 text-info/90 border border-info/20">
        {item.references && item.references.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-1">
            {item.references.map((r, i) => (
              <span key={i} className="text-[9px] px-1 py-0.5 rounded bg-info/15 border border-info/30 font-mono text-info/80">
                {r.type === 'info_pack' ? '📦' : r.type === 'draft' ? '📝' : '📄'} {r.label || r.path}
              </span>
            ))}
          </div>
        )}
        {stripRefBlock(item.content || '')}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: 在消息列表容器内渲染图标列（容器内部最后，messagesEndRef 之前）**

在 `{grouped.map(renderGrouped)}` 之后追加：

```tsx
{/* 多轮会话导航：用户消息快速定位图标列（≥2 条时显示；hover 放大+悬浮预览，点击定位） */}
{userMsgs.length >= 2 && (
  <div className="absolute left-1 top-0 bottom-0 w-3 z-10">
    {railPos.map(p => {
      const seq = userMsgs.findIndex(u => u.groupIdx === p.idx) + 1;
      const um = userMsgs.find(u => u.groupIdx === p.idx);
      return (
        <div key={p.idx} className="absolute left-0" style={{ top: p.top, transform: 'translateY(-50%)' }}>
          <button
            onClick={() => handleJumpToUser(p.idx)}
            onMouseEnter={() => setHoverUserIdx(p.idx)}
            onMouseLeave={() => setHoverUserIdx(null)}
            title="定位到该用户消息"
            className={`block h-1.5 w-1.5 rounded-full transition-all duration-150 ${p.inView ? 'bg-info' : 'bg-gray-600'} ${hoverUserIdx === p.idx ? 'scale-[2.2] bg-info shadow-[0_0_6px_rgba(59,130,246,0.8)]' : ''}`}
          />
          {hoverUserIdx === p.idx && um && (
            <div className="absolute left-4 top-1/2 -translate-y-1/2 z-20 w-64 bg-surface-2 border border-border rounded-lg shadow-xl p-2 pointer-events-none">
              <div className="text-[9px] text-gray-500 mb-1">用户消息 #{seq}</div>
              <div className="text-xs text-gray-300 line-clamp-2 break-all">{um.content}</div>
            </div>
          )}
        </div>
      );
    })}
  </div>
)}
```

- [ ] **Step 4: 新增滚动/resize 监听与定位跳转函数**

在 `computeRail` 定义之后追加：

```tsx
// 图标列：滚动/resize 时重算（rAF 节流）
useEffect(() => {
  const box = msgBoxRef.current;
  if (!box) return;
  let raf = 0;
  const onResizeScroll = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; computeRail(); });
  };
  box.addEventListener('scroll', onResizeScroll, { passive: true });
  window.addEventListener('resize', onResizeScroll);
  computeRail();
  return () => {
    box.removeEventListener('scroll', onResizeScroll);
    window.removeEventListener('resize', onResizeScroll);
    if (raf) cancelAnimationFrame(raf);
  };
}, [computeRail]);
```

在 `const handleJumpToUser = ...` 尚未定义处（`renderGrouped` 之前）追加：

```tsx
// 点击图标 → 滚动定位 + 1.5s 高亮闪烁后淡出
const handleJumpToUser = (groupIdx: number) => {
  const box = msgBoxRef.current;
  const el = box?.querySelector<HTMLElement>(`[data-user-idx="${groupIdx}"]`);
  if (!box || !el) return;
  const relTop = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  box.scrollTo({ top: Math.max(relTop - 8, 0), behavior: 'smooth' });
  setHighlightIdx(groupIdx);
  if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current);
  highlightTimerRef.current = window.setTimeout(() => setHighlightIdx(null), 1500);
};
```

- [ ] **Step 5: 组件卸载清理高亮定时器**

在组件 return 之前（现有 effects 区域）追加：

```tsx
useEffect(() => () => {
  if (highlightTimerRef.current) window.clearTimeout(highlightTimerRef.current);
}, []);
```

- [ ] **Step 6: 编译验证**

Run: `cd workbench/frontend && npx tsc -b --noEmit`
Expected: 无类型错误

---

### Task 4: 构建与浏览器实测

- [ ] **Step 1: 完整构建**

Run: `cd workbench/frontend && npm run build`
Expected: `tsc -b` 与 `vite build` 均通过，产物写入 `dist/`

- [ ] **Step 2: 浏览器实测（多轮会话 ≥2 条用户消息）**

Run: `pwsh start-workbench.ps1 -NoBrowser` 启动开发环境，浏览器打开 AgentChat 页面，逐项验证：

1. 发送 ≥2 条用户消息后：顶部置顶栏显示最近一条用户消息（📌 + 单行截断）
2. 发送新消息 → 置顶栏内容更新为新消息；点击 ✕ 收起 → 再发新消息 → 自动重新展开
3. 消息列表左侧出现图标列（小圆点）：hover 圆点 → 放大为 info 色 + 右侧悬浮卡片显示「用户消息 #N + 内容（2 行截断）」；鼠标挪走 → 悬浮立即消失
4. 点击圆点 → 消息列表平滑滚动定位到该消息 + 该消息行高亮闪烁（ring + 背景）→ 1.5s 后淡出
5. 滚动消息列表 → 圆点位置按比例实时刷新；当前视口内的消息对应圆点为 info 色，其余灰色
6. 空会话 / 单条用户消息：不显示置顶栏与图标列
7. `/new`、`/clear`、切换会话后：置顶栏/图标列/高亮状态全部重置

- [ ] **Step 3: 完成确认**

Expected: 全部 7 项验证通过；如有偏差回到对应 Task 修复后重跑
