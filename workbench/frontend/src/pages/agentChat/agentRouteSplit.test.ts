import { test, expect } from 'vitest';
// vite 原生 ?raw 导入源码文本（前端 tsconfig 无 node types，不能用 node:fs）
import appSrc from '../../App.tsx?raw';

/**
 * T-1040 回归钉：双对话路由必须带互异 key 强制重挂载（源码钉，无 key 即红）。
 *
 * App.tsx 的路由是内联 JSX（无路由配置导出），行为钉需 mock AgentChat 全套
 * API/WS 成本过高，故采源码钉（与后端 T-1033「AST 剥 docstring 源码钉」同形态）。
 * 根因背景：React 对同位置同类型组件复用实例——无 key 时 /agent ↔ /agent-product
 * SPA 切换不重挂载，分侧交换（ensureSideStore）/深链 ?session= 消费/上次会话恢复
 * 三处挂载期逻辑整体旁路（2026-08-29 主库验收实锤：跨侧消息串扰 + 会话不恢复）。
 * 共享 WS 存于模块级 _store.ws（不在分侧字段内），重挂载只采纳连接不断连。
 */
test('T-1040 回归钉：/agent 与 /agent-product 的 AgentChat 元素带互异 key + 正确 fixedPurpose', () => {
  // 注意 JSX 结构：element={<AgentChat attrs />}——AgentChat 自闭合 /> 在前，
  // element 属性闭合 } 在后（attrs 后跟 />}\ />）
  const routeRe = /<Route path="(\/agent(?:-product)?)" element={<AgentChat ([^>]*?)\/>\} \/>/g;
  const found = new Map<string, string>();
  for (const m of appSrc.matchAll(routeRe)) {
    found.set(m[1], m[2]);
  }
  expect([...found.keys()].sort()).toEqual(['/agent', '/agent-product']);

  const keys: string[] = [];
  for (const [path, attrs] of found) {
    const k = attrs.match(/key="([^"]+)"/);
    expect(k, `${path} 的 AgentChat 元素缺 key——SPA 菜单切换将不重挂载，分侧隔离失效`).toBeTruthy();
    keys.push(k![1]);
    const p = attrs.match(/fixedPurpose="([^"]+)"/);
    expect(p, `${path} 应注入固定用途`).toBeTruthy();
    expect(p![1]).toBe(path === '/agent' ? 'test_workbench' : 'requirement_interview');
  }
  expect(new Set(keys).size, '两条路由 key 必须互异（否则复用实例不重挂载）').toBe(2);
});
