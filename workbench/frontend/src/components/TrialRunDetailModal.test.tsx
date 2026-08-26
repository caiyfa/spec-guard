import { expect, test, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

/** runsApi 打桩（Modal 数据源：run.json / cases/*.json / output.log） */
const getMock = vi.fn();
const getCaseMock = vi.fn();
const logMock = vi.fn();
vi.mock('../api', () => ({
  runsApi: {
    get: (...a: unknown[]) => getMock(...a),
    getCase: (...a: unknown[]) => getCaseMock(...a),
    log: (...a: unknown[]) => logMock(...a),
  },
}));

import { TrialRunDetailModal } from './TrialRunDetailModal';

const RUN_DOC = {
  run_id: 'EX-test01', env: 'sit', system: 'tdm',
  started_at: '2026-08-26T19:48:28', finished_at: '2026-08-26T19:48:31',
  stats: { pass: 0, fail: 1, skip: 0, blocked: 0, total: 1, warnings: 0 },
  cases: [{
    id: 'HI-PERM-002', title: 'ALL 全量基线', verdict: 'FAIL',
    duration_ms: 1859, file: 'cases/HI-PERM-002.json',
  }],
};

const CASE_DETAIL = {
  scenario_id: 'HI-PERM-002', verdict: 'FAIL', duration_ms: 1859,
  doc: { given: 'default 账号 corp=ALL', when: '调用 POST /api/history/inventory/query', then: 'HTTP 200 total == DB COUNT' },
  steps: [
    { type: 'fetch_permission', note: '权限预言 default@VIEW_HISTORY', duration_ms: 0 },
    { type: 'call', request: { as: 'default', method: 'POST', path: '/api/history/inventory/query' },
      response_status: 200, duration_ms: 337, trace_id: 'tr-abc', body_excerpt: { total: 55 } },
    { type: 'db_query', note: 'db_query → 1 行', duration_ms: 20 },
  ],
  db_traces: [{ purpose: 'db_query', sql: 'SELECT COUNT(*) AS total FROM tdm_snap_profile', rows: 1, excerpt: [{ total: 341 }] }],
  oracle_traces: [{ purpose: '权限预言', scope: 'corpCode=ALL, groupLevel=[5, 6]' }],
  assertions: [{ expr: 'total == db_total', passed: false, expected: 341, actual: 55 }],
  failure: { category: 'scenario_error', message: 'AssertionError: 接口 total=55 != DB COUNT=341' },
  saved_vars: { query_resp: { total: 55 } },
};

beforeEach(() => {
  vi.clearAllMocks();
  getMock.mockResolvedValue(RUN_DOC);
  getCaseMock.mockResolvedValue(CASE_DETAIL);
  logMock.mockResolvedValue({ run_id: 'EX-test01', total_lines: 2, log: '[SpecGuard] 试跑失败' });
});

test('失败试跑：概要徽章 + 任务号 + 默认展开的执行过程（步骤/DB/断言/失败归类）', async () => {
  render(<TrialRunDetailModal trial={{ ok: false, run_id: 'EX-test01', error: 'python 步骤脚本异常', env: 'sit' }} onClose={() => {}} />);
  // 概要：失败徽章 + 任务号
  expect(screen.getByText('✗ 试跑失败')).toBeTruthy();
  expect(screen.getByText('EX-test01')).toBeTruthy();
  await waitFor(() => expect(screen.getByText('SELECT COUNT(*) AS total FROM tdm_snap_profile')).toBeTruthy());
  // 用例卡默认展开（第一个非 PASS）：失败归类 + 原因
  expect(screen.getByText(/scenario_error/)).toBeTruthy();
  expect(screen.getByText(/AssertionError: 接口 total=55 != DB COUNT=341/)).toBeTruthy();
  // 执行过程：call 步骤（方法+路径+状态码）与 trace_id
  expect(screen.getByText('POST /api/history/inventory/query（default）')).toBeTruthy();
  expect(screen.getByText('trace: tr-abc')).toBeTruthy();
  // DB 校对结果表 + 断言明细（期望/实际）
  expect(screen.getByText('341')).toBeTruthy();
  expect(screen.getByText(/期望 341 · 实际 55/)).toBeTruthy();
  // 执行日志（折叠头部在场）
  expect(screen.getByText(/执行日志（2 行）/)).toBeTruthy();
});

test('通过试跑：绿色通过徽章，PASS 用例仍可展开查看', async () => {
  getMock.mockResolvedValue({
    ...RUN_DOC,
    stats: { pass: 1, fail: 0, skip: 0, blocked: 0, total: 1, warnings: 0 },
    cases: [{ id: 'HI-PERM-002', title: 'ALL 全量基线', verdict: 'PASS', duration_ms: 1859, file: 'cases/HI-PERM-002.json' }],
  });
  getCaseMock.mockResolvedValue({ ...CASE_DETAIL, verdict: 'PASS', failure: undefined, assertions: [{ expr: 'total == db_total', passed: true }] });
  render(<TrialRunDetailModal trial={{ ok: true, run_id: 'EX-test01', verdict: 'PASS', env: 'sit' }} onClose={() => {}} />);
  expect(screen.getByText('✓ 试跑通过')).toBeTruthy();
  // PASS 用例默认展开（仅一条）
  await waitFor(() => expect(screen.getByText('POST /api/history/inventory/query（default）')).toBeTruthy());
});

test('报告读取失败：显示兜底错误 + 试跑返回的错误文字', async () => {
  getMock.mockRejectedValue(new Error('运行 EX-x 不存在'));
  logMock.mockRejectedValue(new Error('no log'));
  render(<TrialRunDetailModal trial={{ ok: false, run_id: 'EX-x', error: '运行时装配失败' }} onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText(/报告读取失败：运行 EX-x 不存在/)).toBeTruthy());
  expect(screen.getByText('运行时装配失败')).toBeTruthy();
});
