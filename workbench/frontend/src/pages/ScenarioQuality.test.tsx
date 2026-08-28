// T-1035：测试用例管理页——挂载拉数/三态/页签与筛选持久化/展开看真实内容。
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
      path: 'suiteA/DEEP-001.yaml', covers: ['FR-001'],
      covers_detail: [{ fr: 'FR-001', valid: true, title: '查询功能', module: 'module1/feature1' }],
      invalid_covers: [], dimensions: ['state'], priority: 'P1', tags: [],
      verify_count: 2, evidence: ['db_proof', 'http_ok', 'json_field'],
      grade: 'deep', issues: [],
      doc_summary: { given: '库里有一行数据', when: '查询并断言', then: '返回一行' },
      flow_summary: ['DB 查询 SELECT 1 → 存 rows'],
      verify_summary: ['HTTP 状态 = 200', '响应字段 $.rows len_eq 1（断言对象 rows）'],
      steps: { db_query: 1 }, tools: [], oracles: [], depends_on: [],
    },
    {
      id: 'SHALLOW-001', title: '浅断言场景', suite: 'suiteA', module: 'm1',
      path: 'suiteA/SHALLOW-001.yaml', covers: [], covers_detail: [],
      invalid_covers: [], dimensions: [], priority: 'P1', tags: [],
      verify_count: 1, evidence: ['http_ok'],
      grade: 'shallow', issues: ['missing-covers', 'shallow'],
      doc_summary: { given: '', when: '', then: '' },
      flow_summary: ['调用 GET /api/x'],
      verify_summary: ['HTTP 状态 = 200'],
      steps: { call: 1 }, tools: [], oracles: [], depends_on: [],
    },
  ],
};

beforeEach(() => { localStorage.clear(); });
afterEach(cleanup);

function renderPage() {
  return render(<MemoryRouter><ScenarioQuality /></MemoryRouter>);
}

describe('ScenarioQuality 测试用例管理页', () => {
  it('挂载后渲染统计卡与套件表', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('用例总数')).toBeTruthy());
    expect(screen.getByText('特性A')).toBeTruthy();           // 套件行
    expect(screen.getByText('specs/m1/spec.md @V1')).toBeTruthy();
    expect(screen.getAllByText('50%').length).toBeGreaterThan(0);     // 需求关联率（统计卡+套件行）
    expect(screen.getByText('缺口 1')).toBeTruthy();                 // 需求覆盖卡（anchors_available）
  });

  it('错误路径显示红色横幅，不白屏', async () => {
    mockOverview.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    await waitFor(() => expect(screen.getByText(/加载用例库失败：boom/)).toBeTruthy());
  });

  it('页签切换持久化 localStorage，明细页展示用例行与关联需求列', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 用例明细'));
    expect(localStorage.getItem('sg_sq_tab')).toBe('scenarios');
    expect(screen.getByText('DEEP-001')).toBeTruthy();
    expect(screen.getByText('SHALLOW-001')).toBeTruthy();
    expect(screen.getByText('关联需求')).toBeTruthy();                 // 列名中文
    expect(screen.getByTitle('FR-001：查询功能（module1/feature1）')).toBeTruthy();  // FR 悬浮见标题
    expect(screen.getAllByText('缺关联需求').length).toBeGreaterThan(0);  // 待完善徽标（筛选下拉同名 option 共存）
  });

  it('评级筛选收窄明细行，展开显示业务语义/步骤/断言与人话证据', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 用例明细'));

    fireEvent.change(screen.getByTitle('按评级筛选'), { target: { value: 'shallow' } });
    expect(screen.queryByText('DEEP-001')).toBeNull();
    expect(screen.getByText('SHALLOW-001')).toBeTruthy();
    expect(JSON.parse(localStorage.getItem('sg_sq_filters') || '{}').grade).toBe('shallow');

    fireEvent.click(screen.getByText('SHALLOW-001'));
    expect(screen.getByText(/suiteA\/SHALLOW-001\.yaml/)).toBeTruthy();
    expect(screen.getByText(/调用 GET \/api\/x/)).toBeTruthy();      // 执行步骤一行式
    expect(screen.getByText(/HTTP 状态 = 200/)).toBeTruthy();        // 验证断言一行式
    expect(screen.getByText('成功状态')).toBeTruthy();               // 断言证据人话芯片
  });

  it('深断言用例展开显示 doc 语义与 DB 证据芯片', async () => {
    mockOverview.mockResolvedValue(OVERVIEW);
    renderPage();
    await waitFor(() => expect(screen.getByText('特性A')).toBeTruthy());
    fireEvent.click(screen.getByText('📄 用例明细'));
    fireEvent.click(screen.getByText('DEEP-001'));
    expect(screen.getByText(/给定：库里有一行数据/)).toBeTruthy();   // 业务语义
    expect(screen.getByText(/DB 查询 SELECT 1/)).toBeTruthy();
    expect(screen.getByText(/响应字段 \$\.rows len_eq 1/)).toBeTruthy();
    expect(screen.getByText('持久层证据')).toBeTruthy();
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
