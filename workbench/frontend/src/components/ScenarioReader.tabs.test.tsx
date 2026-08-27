/** T-1027 F3：ScenarioReader 区块分页签测试（装配/空区块隐藏/持久化/失效回退）。 */
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

// 锚点原文接口打桩（分签装配只关心芯片数量，原文内容本用例不展开）
const anchorRefsMock = vi.fn().mockResolvedValue({
  refs: [
    { id: 'FR-005', found: false },
    { id: 'AC-005', found: false },
  ],
});
vi.mock('../api/workspace', () => ({
  workspaceApi: {
    anchorRefs: (...a: unknown[]) => anchorRefsMock(...a),
    readFile: vi.fn(),
  },
}));

import ScenarioReader from './ScenarioReader';

afterEach(cleanup);

/** 完整场景（五区块全有） */
const FULL_DOC = {
  id: 'HI-PERM-002',
  version: 1,
  priority: 'P0',
  title: 'corp=PART 主路',
  tags: ['permission'],
  doc: {
    given: 'SIT 环境', when: '调用接口', then: 'HTTP 200',
    note: '关键决策备注',
    covers: ['FR-005'], related_ac: ['AC-005'],
  },
  requires: { accounts: ['default'] },
  depends_on: ['UP-001'],
  flow: [
    { step: 'call', name: 's1', args: { path: '/api/x' } },
    { step: 'call', name: 's2', args: { path: '/api/y' } },
  ],
  verify: [{ jsonpath: '$.status', equals: '200' }],
};

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

test('装配五个区块签，空区块不出签', async () => {
  const { container } = render(<ScenarioReader data={{ ...FULL_DOC }} />);
  // 五签齐装配（计数后缀用前缀正则匹配）
  await screen.findByTitle(/^业务语义/);
  for (const label of ['关联需求', '执行步骤', '验证断言', '依赖与产出']) {
    expect(screen.getByTitle(new RegExp(`^${label}`))).toBeTruthy();
  }
  // 切到关联需求签：anchorRefs 返回 found=false → 两枚芯片以文本「未找到」呈现
  fireEvent.click(screen.getByTitle(/^关联需求/));
  expect((await screen.findAllByText('未找到')).length).toBe(2);
  // 去掉 verify 区块 → 对应签消失
  const noVerify = JSON.parse(JSON.stringify(FULL_DOC));
  delete noVerify.verify;
  cleanup();
  render(<ScenarioReader data={noVerify} />);
  expect(screen.queryByTitle(/^验证断言/)).toBeNull();
  expect(container).toBeTruthy();
});

test('点击切换分签且持久化到 localStorage，计数徽标上签', async () => {
  render(<ScenarioReader data={{ ...FULL_DOC }} />);
  await screen.findByTitle(/^业务语义/);
  fireEvent.click(screen.getByTitle(/^执行步骤/));
  expect(localStorage.getItem('sg_scenario_reader_tab')).toBe('flow');
  // 步骤计数徽标
  expect(screen.getByTitle(/^执行步骤/).textContent).toContain('2');
});

test('持久化值对本文档失效时回退首个可用签（不空白不报错）', async () => {
  localStorage.setItem('sg_scenario_reader_tab', 'tail');
  const doc = JSON.parse(JSON.stringify(FULL_DOC));
  delete doc.requires;
  delete doc.depends_on;
  render(<ScenarioReader data={doc} />);
  await screen.findByText('Given');
  // tail 不可用 → 回退 semantic：Given/When/Then 内容在屏
  expect(screen.getByText('When')).toBeTruthy();
});

test('单区块文档不出页签条（直接展示唯一区块）', async () => {
  render(<ScenarioReader data={{
    id: 'MIN-001',
    doc: { given: 'G', when: 'W', then: 'T' },
  }} />);
  await screen.findByText('G');
  expect(screen.queryByTitle('关联需求')).toBeNull();
});
