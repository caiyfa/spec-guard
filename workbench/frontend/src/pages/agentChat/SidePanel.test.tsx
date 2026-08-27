import { expect, test, vi, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

// vitest 未开 globals，RTL 自动 cleanup 不生效——显式挂，防 DOM 跨测试累积误匹配
afterEach(cleanup);

// 重型子面板打桩（仅 activeTab 命中才渲染，但 import 链会拉起——斩断 api 依赖保持用例离线）
vi.mock('../GateDockPanel', () => ({ default: () => <div>gates-stub</div> }));
vi.mock('../Skills', () => ({ default: () => <div>skills-stub</div> }));
vi.mock('../SpecValidation', () => ({ default: () => <div>spec-stub</div> }));
vi.mock('../Knowledge', () => ({ default: () => <div>knowledge-stub</div> }));
vi.mock('../../components/FocusGraph', () => ({ FocusGraphTab: () => <div>focus-stub</div> }));

import { SidePanel } from './SidePanel';
import type { DocReadItem } from '../../components/ReadingPanel';
import type { DocWriteItem } from './types';

const readItem = (key: string): DocReadItem => ({
  key, tool: 'read_spec', ref: key, path: key, turn: 1, size: 10,
  excerpt: '', label: `查阅 ${key}`, thinking: '', hunks: [], reads: 1,
});

const writeItem = (key: string): DocWriteItem => ({
  key, tool: 'write_spec', ref: key, path: key, turn: 1, size: 10,
  excerpt: '', label: `更新 ${key}`, thinking: '', verdict: null,
  findings: [], hunks: [], writes: 1,
});

const baseProps = {
  ctxUsage: null, planItems: [], structuredTodos: [], loading: false, messages: [],
  ctxLimit: 100, stats: null, scenarioMeta: null, onUpdateMeta: vi.fn(), onError: vi.fn(),
  references: [], onViewFile: vi.fn(), fileTabs: [], activeTab: 'todos',
  onSelectTab: vi.fn(), onCloseTab: vi.fn(), width: 360,
  draftFiles: [], readingFeed: [] as DocReadItem[], onOpenDocRead: vi.fn(),
  writingFeed: [] as DocWriteItem[], onOpenDocWrite: vi.fn(), onOpenDiff: vi.fn(),
  sessionId: 's1', workspace: 'tdm', onCiteToMain: vi.fn(),
  purposePanels: ['deps', 'history'],  // 专用低频签（依赖图/提交历史）进装配
};

const openMenu = () => fireEvent.click(screen.getByTitle('更多面板（低频页签聚合）'));

test('T-1026 高频签常驻页签条，七个低频签不进条', () => {
  render(<SidePanel {...baseProps} />);
  expect(screen.getByText('📋 待办')).toBeTruthy();
  expect(screen.getByText('📝 草稿产物')).toBeTruthy();
  expect(screen.getByText('🛠 技能')).toBeTruthy();
  for (const low of ['🎛 操作台', '📖 阅读', '✏️ 更新足迹', '📏 合规', '🧠 知识', '🕸 依赖图', '📜 提交历史']) {
    expect(screen.queryByText(low)).toBeNull();
  }
});

test('T-1026 「更多」打开卡片网格：含全部低频签 + 足迹计数徽标', () => {
  render(<SidePanel {...baseProps}
    readingFeed={[readItem('a.md'), readItem('b.md')]}
    writingFeed={[writeItem('c.md')]} />);
  openMenu();
  expect(screen.getByTestId('more-panels-menu')).toBeTruthy();
  expect(screen.getByText('打开面板')).toBeTruthy();
  for (const name of ['操作台', '阅读', '更新足迹', '合规', '知识', '依赖图', '提交历史']) {
    expect(screen.getByText(name)).toBeTruthy();
  }
  expect(screen.getByText('2')).toBeTruthy();   // 阅读足迹徽标
  expect(screen.getByText('1')).toBeTruthy();   // 更新足迹徽标
});

test('T-1026 点卡片 → 回调 onSelectTab 并收起菜单', () => {
  const onSelectTab = vi.fn();
  render(<SidePanel {...baseProps} onSelectTab={onSelectTab} />);
  openMenu();
  fireEvent.click(screen.getByText('合规'));
  expect(onSelectTab).toHaveBeenCalledWith('spec');
  expect(screen.queryByTestId('more-panels-menu')).toBeNull();
});

test('T-1026 Escape 关闭菜单；再次「更多」可重开', () => {
  render(<SidePanel {...baseProps} />);
  openMenu();
  expect(screen.getByTestId('more-panels-menu')).toBeTruthy();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByTestId('more-panels-menu')).toBeNull();
  openMenu();
  expect(screen.getByTestId('more-panels-menu')).toBeTruthy();
});

test('T-1026 活动低频签暂显条内（含计数），内容区渲染对应面板', () => {
  render(<SidePanel {...baseProps} activeTab="reading"
    readingFeed={[readItem('a.md'), readItem('b.md'), readItem('c.md')]} />);
  expect(screen.getByText('📖 阅读(3)')).toBeTruthy();   // 暂显签
  expect(screen.getByTitle('更多面板（低频页签聚合）').className).toContain('text-info');
  expect(screen.getByText('查阅 a.md')).toBeTruthy();   // ReadingPanel 就地渲染足迹卡片
});

test('T-1026 外点菜单区域 → 收起', () => {
  render(<SidePanel {...baseProps} />);
  openMenu();
  expect(screen.getByTestId('more-panels-menu')).toBeTruthy();
  fireEvent.mouseDown(document.body);
  expect(screen.queryByTestId('more-panels-menu')).toBeNull();
});
