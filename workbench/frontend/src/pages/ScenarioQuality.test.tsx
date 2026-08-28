// T-1035 v2：测试用例管理页——挂载拉数/三态/页签与筛选持久化/详情弹层（结构化编辑）/试跑对话框。
// 重件一律 mock：ScenarioFormEditor/TrialRunDetailModal 用 stub，api 子模块与 useRunStream 用 vi.mock。

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import ScenarioQuality from './ScenarioQuality';
import { scenarioQualityApi } from '../api/scenarioQuality';
import { scenariosApi } from '../api/scenarios';
import { runsApi } from '../api/runs';
import type { QualityOverview } from '../api/scenarioQuality';

vi.mock('../api/scenarioQuality', () => ({
  scenarioQualityApi: { overview: vi.fn() },
}));
vi.mock('../api/scenarios', () => ({
  scenariosApi: { get: vi.fn(), save: vi.fn() },
}));
vi.mock('../api/reference', () => ({
  referenceApi: {
    empRoles: vi.fn().mockResolvedValue([]), oracles: vi.fn().mockResolvedValue([]),
    envVars: vi.fn().mockResolvedValue([]), upstreamVars: vi.fn().mockResolvedValue([]),
  },
}));
vi.mock('../api/runs', () => ({
  runsApi: {
    trigger: vi.fn(),
    accounts: vi.fn().mockResolvedValue({ accounts: {}, env: 'sit' }),
    preflight: vi.fn(),
  },
}));
vi.mock('../components/ScenarioFormEditor', () => ({
  default: ({ scenarioId }: any) => <div data-testid="form-editor">{scenarioId}</div>,
}));
vi.mock('../components/TrialRunDetailModal', () => ({
  TrialRunDetailModal: ({ trial }: any) => <div data-testid="trial-report">{trial.run_id}</div>,
}));
vi.mock('../hooks/useRunStream', () => ({
  useRunStream: () => ({ events: [], connected: true, running: false, clear: vi.fn() }),
}));

const mockOverview = vi.mocked(scenarioQualityApi.overview);
const mockGet = vi.mocked(scenariosApi.get);
const mockTrigger = vi.mocked(runsApi.trigger);
const mockPreflight = vi.mocked(runsApi.preflight);

const ROW_BASE = {
  module: 'm1', invalid_covers: [], dimensions: [], priority: 'P1', tags: [],
  steps: { call: 1 }, tools: [], oracles: [], depends_on: [],
};

const OVERVIEW: QualityOverview = {
  generated_at: '2026-08-28T10:00:00',
  root: 'D:\\scenarios',
  anchors_available: true,
  totals: {
    scenarios: 3, suites: 1, covers_tagged: 2, covers_rate: 66.7,
    grades: { deep: 2, medium: 0, shallow: 1, 'no-verify': 0 },
    issues: { 'missing-covers': 1, shallow: 1 },
    scenarios_with_issues: 1,
    anchors_total: 2, anchors_covered: 2, fr_gaps: 0,
  },
  suites: [{
    key: 'suiteA', feature: '特性A', module: 'm1', spec_ref: 'specs/m1/spec.md',
    spec_version: 'V1', scenarios: 3, covers_tagged: 2, covers_rate: 66.7,
    grades: { deep: 2, medium: 0, shallow: 1, 'no-verify': 0 }, scenarios_with_issues: 1,
  }],
  capability_matrix: {
    steps: { call: 3 }, tools: {}, oracles: {},
    depends: { shared: 1, exclusive: 0 },
  },
  scenarios: [
    {
      ...ROW_BASE, id: 'DEEP-001', title: '深断言场景', suite: 'suiteA',
      path: 'suiteA/DEEP-001.yaml', covers: ['FR-001'],
      covers_detail: [{ fr: 'FR-001', valid: true, title: '查询功能', module: 'module1/feature1' }],
      verify_count: 2, evidence: ['db_proof', 'http_ok'], grade: 'deep', issues: [],
      doc_summary: { given: '库里有一行数据', when: '查询并断言', then: '返回一行' },
    },
    {
      ...ROW_BASE, id: 'SHALLOW-001', title: '浅断言场景', suite: 'suiteA',
      path: 'suiteA/SHALLOW-001.yaml', covers: [], covers_detail: [],
      verify_count: 1, evidence: ['http_ok'], grade: 'shallow', issues: ['missing-covers', 'shallow'],
      doc_summary: { given: '', when: '', then: '' },
    },
    {
      ...ROW_BASE, id: 'DOWN-001', title: '下游消费场景', suite: 'suiteA',
      path: 'suiteA/DOWN-001.yaml', covers: ['FR-002'],
      covers_detail: [{ fr: 'FR-002', valid: true, title: '创建功能', module: 'module1/feature1' }],
      verify_count: 1, evidence: ['http_ok', 'json_field'], grade: 'deep', issues: [],
      doc_summary: { given: '', when: '', then: '' },
      depends_on: [{ id: 'DEEP-001', mode: 'shared' }],
    },
  ],
};

const PREFLIGHT = {
  missing_accounts: [{ account: 'platformNoCorp', scenarios: ['DEEP-001'] }],
  missing_env: [], unresolved_upstream: [], unresolved_templates_gaps: [],
  missing_files: [], unknown_file_refs: [], unknown_file_refs_gaps: [],
  accounts: [], env_keys: [], upstream_refs: [], has_gaps: true,
};

beforeEach(() => {
  vi.clearAllMocks();   // 清调用历史（不清实现）——否则 mock.calls[0] 串到上一用例
  localStorage.clear();
  mockOverview.mockResolvedValue(OVERVIEW);
  mockGet.mockResolvedValue({ id: 'DEEP-001', content: 'id: DEEP-001\n' });
  mockPreflight.mockResolvedValue(PREFLIGHT as any);
  mockTrigger.mockResolvedValue({ ok: true, run_id: 'EX-abcd1234' });
});
afterEach(cleanup);

function renderPage(role = 'tester') {
  return render(<MemoryRouter><ScenarioQuality role={role} /></MemoryRouter>);
}

async function openDetail(id: string) {
  await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
  fireEvent.click(screen.getByText('📄 用例明细'));
  fireEvent.click(screen.getByText(id));
  await waitFor(() => expect(screen.getByTestId('form-editor')).toBeTruthy());
}

describe('ScenarioQuality 测试用例管理页', () => {
  it('挂载后渲染统计卡与套件表', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('用例总数')).toBeTruthy());
    expect(screen.getByText('特性A')).toBeTruthy();
    expect(screen.getByText('specs/m1/spec.md @V1')).toBeTruthy();
    expect(screen.getAllByText('66.7%').length).toBeGreaterThan(0);
    expect(screen.getByText('缺口 0')).toBeTruthy();
  });

  it('错误路径显示红色横幅，不白屏', async () => {
    mockOverview.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    await waitFor(() => expect(screen.getByText(/加载用例库失败：boom/)).toBeTruthy());
  });

  it('页签切换持久化，明细页展示用例行与关联需求列', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 用例明细'));
    expect(localStorage.getItem('sg_sq_tab')).toBe('scenarios');
    expect(screen.getByText('DEEP-001')).toBeTruthy();
    expect(screen.getByText('关联需求')).toBeTruthy();
    expect(screen.getByTitle('FR-001：查询功能（module1/feature1）')).toBeTruthy();
    expect(screen.getAllByText('缺关联需求').length).toBeGreaterThan(0);
  });

  it('评级筛选收窄明细行并持久化', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 用例明细'));
    fireEvent.change(screen.getByTitle('按评级筛选'), { target: { value: 'shallow' } });
    expect(screen.queryByText('DEEP-001')).toBeNull();
    expect(screen.getByText('SHALLOW-001')).toBeTruthy();
    expect(JSON.parse(localStorage.getItem('sg_sq_filters') || '{}').grade).toBe('shallow');
  });

  it('套件行点击跳转到该套件的明细筛选', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('特性A'));
    expect(localStorage.getItem('sg_sq_tab')).toBe('scenarios');
    expect(JSON.parse(localStorage.getItem('sg_sq_filters') || '{}').suite).toBe('suiteA');
  });

  it('行点击打开详情弹层：拉原文进结构化编辑器，tester 见试跑按钮', async () => {
    renderPage('tester');
    await openDetail('DEEP-001');
    expect(mockGet).toHaveBeenCalledWith('DEEP-001');
    expect(screen.getByTestId('form-editor').textContent).toBe('DEEP-001');
    expect(screen.getByText(/给定：库里有一行数据/)).toBeTruthy();   // doc 语义速览
    expect(screen.getByText('▶ 试跑')).toBeTruthy();
  });

  it('product 角色详情弹层无试跑按钮（只读）', async () => {
    renderPage('product');
    await openDetail('DEEP-001');
    expect(screen.queryByText('▶ 试跑')).toBeNull();
  });

  it('试跑对话框：预检缺口渲染输入框，上下链路展开 target，overrides 透传', async () => {
    renderPage('tester');
    await openDetail('DEEP-001');
    fireEvent.click(screen.getByText('▶ 试跑'));

    // 预检缺口输入框（T-312 同款）
    const input = await screen.findByPlaceholderText('输入 AD 账号（或 ad:工号）替代配置');
    fireEvent.change(input, { target: { value: 'AD001' } });

    // 选「上下链路一起跑」→ target 含下游 DOWN-001
    fireEvent.click(screen.getByRole('radio', { name: /上下链路一起跑/ }));
    fireEvent.click(screen.getByText('▶ 开始试跑（联网执行）'));

    await waitFor(() => expect(mockTrigger).toHaveBeenCalled());
    const [scope, target, , , , overrides] = mockTrigger.mock.calls[0] as any[];
    expect(scope).toBe('scenario');
    expect(target).toBe('DEEP-001 or DOWN-001');
    expect(overrides).toEqual([{ kind: 'account', name: 'platformNoCorp', value: 'AD001' }]);
    expect(await screen.findByText('EX-abcd1234')).toBeTruthy();
  });

  it('试跑对话框：默认范围仅本用例（上游由引擎连带），trigger target 为单 id', async () => {
    renderPage('tester');
    await openDetail('DEEP-001');
    fireEvent.click(screen.getByText('▶ 试跑'));
    await screen.findByText(/执行环境/);
    fireEvent.click(screen.getByText('▶ 开始试跑（联网执行）'));
    await waitFor(() => expect(mockTrigger).toHaveBeenCalled());
    expect((mockTrigger.mock.calls[0] as any[])[1]).toBe('DEEP-001');
  });

  it('全库锚点失效时试跑面板预警并禁用开始按钮（covers 前置闸事前可见）', async () => {
    mockOverview.mockResolvedValue({
      ...OVERVIEW,
      totals: { ...OVERVIEW.totals, issues: { ...OVERVIEW.totals.issues, 'invalid-covers': 25 } },
    });
    renderPage('tester');
    await openDetail('DEEP-001');
    fireEvent.click(screen.getByText('▶ 试跑'));

    expect(screen.getByText(/covers 前置闸将拦截本次触发/)).toBeTruthy();
    expect(screen.getByText(/切换到与用例库同世代的工作区/)).toBeTruthy();
    const btn = screen.getByText('▶ 开始试跑（联网执行）') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(mockTrigger).not.toHaveBeenCalled();
  });
});
