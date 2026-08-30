import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, render, screen, waitFor, act } from '@testing-library/react';

afterEach(cleanup);

/** agentApi 打桩（面板数据源：flow-trace 轮询） */
const getFlowTraceMock = vi.fn();
vi.mock('../../api', () => ({
  agentApi: { getFlowTrace: (...a: unknown[]) => getFlowTraceMock(...a) },
}));

// mermaid 动态导入打桩（MermaidBlock 内部消费；jsdom 下避免真实渲染）
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (_id: string, _code: string) => ({ svg: '<svg data-testsvg="1"/>' })),
  },
}));

import { FlowPanel } from './FlowPanel';

const TRACE = {
  available: true,
  session_id: 's1',
  flow_id: 'generate-scenario',
  flow_title: '创建测试用例 golden flow',
  is_generate: true,
  n_tool_calls: 3,
  current_stage: { key: 'write_draft', label: '写草稿', first_step: 2 },
  stages: [
    { key: 'read_requirement', label: '读需求', required: true, status: 'in_order', first_step: 1, times: 2, tools: ['spec'], note: '', fails: 0 },
    { key: 'get_id', label: '取场景 ID', required: true, status: 'missing', first_step: null, times: 0, tools: [], note: 'scenario(action=next_id)', fails: 0 },
    { key: 'write_draft', label: '写草稿', required: true, status: 'out_of_order', first_step: 2, times: 1, tools: ['draft'], note: '', fails: 1 },
    { key: 'promote', label: '入库 promote', required: false, status: 'skipped', first_step: null, times: 0, tools: [], note: '用户确认后', fails: 0 },
  ],
  deviations: ['缺失必需阶段「取场景 ID」——scenario(action=next_id)', '「写草稿」（第 2 步）先于「validate 校验」（第 3 步）——违反基线顺序'],
  extras: ['spec(sync)×2'],
  n_missing: 1,
  n_out_of_order: 1,
  mermaid: ['flowchart TD', '    S1["1. 取技能正文 ✓"]:::hit', '    classDef hit fill:#d4edda'].join('\n'),
  mermaid_focused: ['flowchart TD', '    S3("3. 写草稿<br/>第2步 ✓"):::hit', '    class S3 current'].join('\n'),
  generated_at: '2026-08-30T10:00:00',
};

beforeEach(() => {
  getFlowTraceMock.mockReset();
  getFlowTraceMock.mockResolvedValue(TRACE);
});

test('渲染阶段四态 + 跑偏点 + 计划外', async () => {
  render(<FlowPanel sessionId="s1" />);
  await waitFor(() => expect(screen.getByTestId('flow-panel')).toBeTruthy());
  // 四个阶段都在（含缺失/乱序/跳过）
  expect(screen.getByText('1. 读需求')).toBeTruthy();
  expect(screen.getByText('2. 取场景 ID')).toBeTruthy();
  expect(screen.getByText('4. 入库 promote')).toBeTruthy();
  // 跑偏徽标与跑偏点证据
  expect(screen.getByText('跑偏 2')).toBeTruthy();
  expect(screen.getByText(/缺失必需阶段「取场景 ID」/)).toBeTruthy();
  expect(screen.getByText(/先于/)).toBeTruthy();
  // 计划外旁支
  expect(screen.getByText(/spec\(sync\)×2/)).toBeTruthy();

  // 图形视图容器（MermaidBlock 渲染 golden flow 着色路径图；jsdom 下 mock mermaid）
  await waitFor(() => expect(screen.getByTestId('flow-graph')).toBeTruthy());
});

test('非生成会话诚实标注（基线仅供参考）', async () => {
  getFlowTraceMock.mockResolvedValue({ ...TRACE, is_generate: false });
  render(<FlowPanel sessionId="s2" />);
  await waitFor(() => expect(screen.getByText(/非生成会话/)).toBeTruthy());
});

test('available=false 降级提示（evals 不可用诚实呈现）', async () => {
  getFlowTraceMock.mockResolvedValue({ available: false, reason: 'evals 模块加载失败: x' });
  render(<FlowPanel sessionId="s3" />);
  await waitFor(() => expect(screen.getByText(/当前无法给出路径重放/)).toBeTruthy());
  expect(screen.getByText(/evals 模块加载失败/)).toBeTruthy();
});

test('请求失败显示错误 + 重试；重试成功恢复', async () => {
  getFlowTraceMock.mockRejectedValueOnce(new Error('网络断开'));
  const { rerender } = render(<FlowPanel sessionId="s4" />);
  await waitFor(() => expect(screen.getByText(/路径重放失败/)).toBeTruthy());
  expect(screen.getByText(/网络断开/)).toBeTruthy();
  getFlowTraceMock.mockResolvedValue(TRACE);
  rerender(<FlowPanel sessionId="s4" />);
  await act(async () => {
    (screen.getByText('重试') as HTMLButtonElement).click();
  });
  await waitFor(() => expect(screen.getByTestId('flow-panel')).toBeTruthy());
});

test('无会话时空态；会话切换重新拉取', async () => {
  const { rerender } = render(<FlowPanel sessionId="" />);
  expect(screen.getByText(/暂无会话/)).toBeTruthy();
  rerender(<FlowPanel sessionId="s5" />);
  await waitFor(() => expect(getFlowTraceMock).toHaveBeenCalledWith('s5'));
});

test('当前阶段显示 + 聚焦/全图切换（选择持久化）', async () => {
  localStorage.removeItem('sg_flow_view');
  render(<FlowPanel sessionId="s6" />);
  await waitFor(() => expect(screen.getByTestId('flow-panel')).toBeTruthy());
  // 头部当前阶段高亮
  expect(screen.getByText(/当前/)).toBeTruthy();
  expect(screen.getByText('写草稿（第2步）')).toBeTruthy();
  // 默认聚焦档；切换全图后持久化
  const focusBtn = screen.getByText('◎ 聚焦') as HTMLButtonElement;
  const fullBtn = screen.getByText('⛶ 全图') as HTMLButtonElement;
  expect(focusBtn.className).toContain('bg-info/20');
  await act(async () => { fullBtn.click(); });
  expect(localStorage.getItem('sg_flow_view')).toBe('full');
  expect(fullBtn.className).toContain('bg-info/20');
  await act(async () => { focusBtn.click(); });
  expect(localStorage.getItem('sg_flow_view')).toBe('focus');
});

test('⚠ 定位按钮：问题节点计数与循环进度', async () => {
  render(<FlowPanel sessionId="s7" />);
  await waitFor(() => expect(screen.getByTestId('flow-locate')).toBeTruthy());
  // issues = 取场景 ID（缺失必需）+ 写草稿（乱序+⚠fail）= 2
  const btn = screen.getByTestId('flow-locate') as HTMLButtonElement;
  expect(btn.textContent).toContain('1/2');
  await act(async () => { btn.click(); });
  expect(btn.textContent).toContain('2/2');
});
