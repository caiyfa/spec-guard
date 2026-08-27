import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

// vitest 未开 globals，RTL 自动 cleanup 不生效——显式挂，防 DOM 跨测试累积误匹配
afterEach(cleanup);

/** draftsApi 打桩（面板数据源：草稿列表 / 模块 / 依赖建议 / ID 冲突预检） */
const listMock = vi.fn();
const modulesMock = vi.fn();
const suggestDepsMock = vi.fn();
const conflictMock = vi.fn();
vi.mock('../../api', () => ({
  draftsApi: {
    list: (...a: unknown[]) => listMock(...a),
    modules: (...a: unknown[]) => modulesMock(...a),
    suggestDeps: (...a: unknown[]) => suggestDepsMock(...a),
    conflict: (...a: unknown[]) => conflictMock(...a),
    validate: vi.fn(),
    trialRun: vi.fn(),
    promote: vi.fn(),
    discard: vi.fn(),
    review: vi.fn(),
  },
}));

import { DraftArtifactsPanel } from './DraftArtifactsPanel';

/** 场景库命中（ID 已存在于 scenarios/，如昨日入库的旧版） */
const CONFLICT_HIT = {
  ok: true,
  existing: { id: 'HI-PERM-001', path: 'scenarios/权限测试/HI-PERM-001.yaml', module: '权限测试' },
  count: 1,
};

/** 草稿列表条目（三闸快照：评审已过 + 校验已过） */
const DRAFT_META = {
  filename: 'HI-PERM-001.yaml',
  scenario_id: 'HI-PERM-001',
  title: 'default 账号 PART-gl 基线主路 → 接口 total == DB COUNT',
  size: 4823,
  modified: '2026-08-27T10:10:52',
  gates: { g1: 'approved', g2: 'pass' },
};

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
}

const renderPanel = () =>
  render(
    <MemoryRouter>
      <DraftArtifactsPanel draftFiles={['HI-PERM-001.yaml']} onViewFile={() => {}} onError={() => {}} />
    </MemoryRouter>,
  );

beforeEach(() => {
  vi.clearAllMocks();
  modulesMock.mockResolvedValue({ modules: ['权限测试'] });
  suggestDepsMock.mockResolvedValue({ suggestions: [] });
});

test('草稿区有新版 + 库内有同 ID 旧版：列表延迟返回也不得误判为已入库——草稿态按钮齐全且不打冲突预检', async () => {
  // 复现挂载竞态：conflict 预检即时返回命中，草稿列表延迟返回（此时草稿仍在列表内）
  conflictMock.mockResolvedValue(CONFLICT_HIT);
  const listD = deferred<{ drafts: unknown[] }>();
  listMock.mockImplementation(() => listD.promise);

  renderPanel();
  // 等待面板进入某个确定态（旧实现此处已渲染成「已在场景库」；新实现显示检测中）
  await waitFor(() =>
    expect(screen.getByText(/已在场景库|检测草稿去向…/)).toBeTruthy(),
  );

  await act(async () => {
    listD.resolve({ drafts: [DRAFT_META] });
  });

  // 草稿在列表内 → 必须按草稿态渲染：标题 + 校验/试跑/入库按钮
  await waitFor(() => expect(screen.getByText(/PART-gl 基线主路/)).toBeTruthy());
  expect(screen.queryByText(/已在场景库/)).toBeNull();
  expect(screen.queryByText('🕸 DAG 编排')).toBeNull();
  expect(screen.getByText('校验')).toBeTruthy();
  expect(screen.getByText('▶ 试跑')).toBeTruthy();
  expect(screen.getByText('⬆ 入库')).toBeTruthy();
  // 草稿在列表内 → 去向判定（冲突预检）根本不需要发生
  expect(conflictMock).not.toHaveBeenCalled();
});

test('草稿确实不在列表（昨日已入库移走）+ 库内命中 → 已入库态：绿字 + DAG 编排按钮', async () => {
  listMock.mockResolvedValue({ drafts: [] });
  conflictMock.mockResolvedValue(CONFLICT_HIT);

  renderPanel();
  await waitFor(() => expect(screen.getByText(/已在场景库/)).toBeTruthy());
  expect(screen.getByText('🕸 DAG 编排')).toBeTruthy();
  expect(conflictMock).toHaveBeenCalled();
});

test('草稿不在列表且库内未命中 → 已删除态提示', async () => {
  listMock.mockResolvedValue({ drafts: [] });
  conflictMock.mockResolvedValue({ ok: true, existing: null, count: 0 });

  renderPanel();
  await waitFor(() => expect(screen.getByText(/草稿已不存在/)).toBeTruthy());
});
