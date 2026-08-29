import { test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router';
import AgentChat from '../AgentChat';
import { _store } from './sessionStore';

/**
 * T-1040 行为钉：SPA 跨侧菜单导航必须触发重挂载与分侧交换（无 key 即红）。
 *
 * 复现主库验收实锤场景：/agent ↔ /agent-product 同类型组件无 key 时 React 复用
 * 实例，挂载期逻辑（ensureSideStore 分侧交换/深链消费/会话恢复）整体旁路——
 * 表现为跨侧消息串扰。本钉用真实 AgentChat + MemoryRouter 模拟侧边栏跨侧切换，
 * 断言消息区随侧交换。路由装配与 App.tsx 保持同构（互异 key + fixedPurpose）。
 *
 * API 全栈打桩：分侧断言不依赖网络；WS 用哑类（onopen 不触发，停留在 connecting）。
 */
vi.mock('../../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../../api')>();
  const P = () => Promise.resolve({});
  const fnAll = () => new Proxy({}, { get: () => vi.fn(P) });
  return {
    ...mod,
    session: { getToken: () => 't', getWorkspace: () => 'tdm', setToken: vi.fn(), clearToken: vi.fn() },
    agentApi: {
      listPurposes: vi.fn(() => Promise.resolve({
        purposes: [
          { id: 'test_workbench', title: '测试工作台', icon: '🧪', color: 'test', chips: [], description: '', panels: ['deps', 'history', 'sql_aux'] },
          { id: 'requirement_interview', title: '产品工作台', icon: '🧭', color: 'req', chips: [], description: '', panels: ['pack', 'focus', 'materials'] },
        ],
      })),
      listSessions: vi.fn(P), getSession: vi.fn(P), batchArchive: vi.fn(P), cancelSession: vi.fn(P),
      exportSession: vi.fn(P), spawnSession: vi.fn(P), createSession: vi.fn(P), patchSession: vi.fn(P),
      clearSessionMessages: vi.fn(P),
    },
    authApi: { me: vi.fn(() => Promise.resolve({ emp_no: '90024166', name: '验收', role: 'admin', roles: ['admin'], auth_mode: 'mock', default_workspace: 'tdm' })) },
    modelApi: { list: vi.fn(P) },
    scenarioApi: { getMeta: vi.fn(P) },
    workspaceApi: { readFile: vi.fn(P) },
    draftsApi: { read: vi.fn(P), update: vi.fn(P) },
    specflowApi: fnAll(),
  };
});

class FakeWS {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = 3;
  onopen = null; onclose = null; onerror = null; onmessage = null;
  close() {} send() {}
}
vi.stubGlobal('WebSocket', FakeWS);
// jsdom 未实现 scrollIntoView（AgentChat 消息滚动 useEffect 用到）
Element.prototype.scrollIntoView = vi.fn();

// 与 App.tsx 双对话路由同构的装配（key 必须互异——本钉与静态钉 agentRouteSplit.test.ts 双保险）
function DualChatRoutes() {
  const nav = useNavigate();
  return (
    <>
      <Routes>
        <Route path="/agent" element={<AgentChat key="agent-test" fixedPurpose="test_workbench" />} />
        <Route path="/agent-product" element={<AgentChat key="agent-product" fixedPurpose="requirement_interview" />} />
      </Routes>
      <button onClick={() => { _store.side === 'test' ? nav('/agent-product') : nav('/agent'); }}>switch-side</button>
    </>
  );
}

const MARKER = 'TEST-SIDE-MARKER-跨侧串扰钉';

beforeEach(() => {
  cleanup();
  _store.side = 'test';
  _store.sides = {};
  _store.buffer = [];
  _store.messages = [{ role: 'user', content: MARKER }];
  _store.loading = false;
  _store.sessionId = 'SID-TEST-BEHAVIOR';
  _store.sessionTitle = '测试侧会话';
  _store.stats = null;
  _store.turnInfo = '';
  _store.error = '';
  _store.planItems = [];
  _store.ctxUsage = null;
  _store.readingFeed = [];
  _store.writingFeed = [];
  localStorage.clear();
});

test('T-1040 行为钉：SPA 切到产品侧消息区交换为空态，切回测试侧快照恢复', async () => {
  render(<MemoryRouter initialEntries={['/agent']}><DualChatRoutes /></MemoryRouter>);

  // 初始：测试侧渲染预置消息（MARKER 出现在消息气泡+置顶栏多处，用计数断言）
  expect((await screen.findAllByText(MARKER)).length).toBeGreaterThanOrEqual(1);
  expect(_store.side).toBe('test');

  // SPA 切到产品侧（模拟侧边栏点「产品对话」）——key 互异 → 重挂载 → 分侧交换
  fireEvent.click(screen.getByText('switch-side'));
  await vi.waitFor(() => expect(_store.side).toBe('product'));
  expect(screen.queryAllByText(MARKER)).toHaveLength(0);   // 测试侧消息不得串入产品侧
  expect(_store.messages).toEqual([]);                     // 产品侧快照为空
  expect(_store.sides.test.sessionId).toBe('SID-TEST-BEHAVIOR');  // 测试侧完整 stash

  // SPA 切回测试侧——分侧交换还原
  fireEvent.click(screen.getByText('switch-side'));
  await vi.waitFor(() => expect(_store.side).toBe('test'));
  expect((await screen.findAllByText(MARKER)).length).toBeGreaterThanOrEqual(1);  // 快照恢复
  expect(_store.sides.product).toBeTruthy();
});
