// T-1035：场景库质量看板页——挂载拉数/三态/页签与筛选持久化/行展开。
// API 走 vi.mock 子模块（同 DbConsole.test 模式），组件只验渲染与交互契约。

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import ScenarioQuality from './ScenarioQuality';
import { scenarioQualityApi } from '../api/scenarioQuality';
import type { QualityOverview } from '../api/scenarioQuality';

vi.mock('../api/scenarioQuality', () => ({
  scenarioQualityApi: { overview: vi.fn() },
}));

const mockOverview = vi.mocked(scenarioQualityApi.overview);

const OVERVIEW: QualityOverview = {
  generated_at: '2026-08-28T10:00:00',
  root: 'D:\\scenarios',
  anchors_available: true,
  totals: {
    scenarios: 2, suites: 1, covers_tagged: 1, covers_rate: 50.0,
    grades: { deep: 1, medium: 0, shallow: 1, 'no-verify': 0 },
    issues: { 'missing-covers': 1, shallow: 1 },
    scenarios_with_issues: 1,
    anchors_total: 2, anchors_covered: 1, fr_gaps: 1,
  },
  suites: [{
    key: 'suiteA', feature: '特性A', module: 'm1', spec_ref: 'specs/m1/spec.md',
    spec_version: 'V1', scenarios: 2, covers_tagged: 1, covers_rate: 50.0,
    grades: { deep: 1, medium: 0, shallow: 1, 'no-verify': 0 }, scenarios_with_issues: 1,
  }],
  capability_matrix: {
    steps: { db_query: 1, call: 1 }, tools: {}, oracles: {},
    depends: { shared: 0, exclusive: 0 },
  },
  scenarios: [
    {
      id: 'DEEP-001', title: '深断言场景', suite: 'suiteA', module: 'm1',
      path: 'suiteA/DEEP-001.yaml', covers: ['FR-001'], invalid_covers: [],
      dimensions: ['state'], priority: 'P1', tags: [],
      verify_count: 2, evidence: ['db_proof', 'http_ok', 'json_field'],
      grade: 'deep', issues: [], steps: { db_query: 1 }, tools: [], oracles: [], depends_on: [],
    },
    {
      id: 'SHALLOW-001', title: '浅断言场景', suite: 'suiteA', module: 'm1',
      path: 'suiteA/SHALLOW-001.yaml', covers: [], invalid_covers: [],
      dimensions: [], priority: 'P1', tags: [],
      verify_count: 1, evidence: ['http_ok'],
      grade: 'shallow', issues: ['missing-covers', 'shallow'],
      steps: { call: 1 }, tools: [], oracles: [], depends_on: [],
    },
  ],
};

beforeEach(() => { localStorage.clear(); });
afterEach(cleanup);

function renderPage() {
  return render(<MemoryRouter><ScenarioQuality /></MemoryRouter>);
}

describe('ScenarioQuality 场景库质量看板', () => {
  it('挂载后渲染统计卡与套件表', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('场景总数')).toBeTruthy());
    expect(screen.getByText('特性A')).toBeTruthy();           // 套件行
    expect(screen.getByText('specs/m1/spec.md @V1')).toBeTruthy();
    expect(screen.getAllByText('50%').length).toBeGreaterThan(0);     // covers 率（统计卡+套件行）
    expect(screen.getByText('缺口 1')).toBeTruthy();                 // FR 覆盖卡（anchors_available）
  });

  it('错误路径显示红色横幅，不白屏', async () => {
    mockOverview.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    await waitFor(() => expect(screen.getByText(/加载场景库质量失败：boom/)).toBeTruthy());
  });

  it('页签切换持久化 localStorage，明细页展示场景行', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 场景明细'));
    expect(localStorage.getItem('sg_sq_tab')).toBe('scenarios');
    expect(screen.getByText('DEEP-001')).toBeTruthy();
    expect(screen.getByText('SHALLOW-001')).toBeTruthy();
    expect(screen.getAllByText('缺 covers').length).toBeGreaterThan(0);  // 问题徽标（筛选下拉同名 option 共存）
  });

  it('评级筛选收窄明细行，行展开显示路径与证据', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 场景明细'));

    fireEvent.change(screen.getByTitle('按评级筛选'), { target: { value: 'shallow' } });
    expect(screen.queryByText('DEEP-001')).toBeNull();
    expect(screen.getByText('SHALLOW-001')).toBeTruthy();
    expect(JSON.parse(localStorage.getItem('sg_sq_filters') || '{}').grade).toBe('shallow');

    fireEvent.click(screen.getByText('SHALLOW-001'));
    expect(screen.getByText(/suiteA\/SHALLOW-001\.yaml/)).toBeTruthy();
  });

  it('套件行点击跳转到该套件的明细筛选', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('特性A'));
    expect(localStorage.getItem('sg_sq_tab')).toBe('scenarios');
    expect(JSON.parse(localStorage.getItem('sg_sq_filters') || '{}').suite).toBe('suiteA');
  });
});
