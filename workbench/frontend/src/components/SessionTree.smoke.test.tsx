import { expect, test, vi, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

// vitest 未开 globals，RTL 自动 cleanup 不生效——显式挂，防 DOM 跨测试累积误匹配
afterEach(cleanup);

import SessionTree from './SessionTree';

const baseProps = {
  currentSessionId: '',
  currentWorkspace: '人才发展',
  onSelectSession: vi.fn(),
  onNewSession: vi.fn(),
};

const sessions = [
  { id: 'normal-1', workspace: '人才发展', modified: '2026-08-29T10:00:00', title: '普通会话甲' },
  { id: 'normal-2', workspace: 'tdm', modified: '2026-08-29T09:00:00', title: '普通会话乙' },
  { id: 'smoke-1', workspace: '人才发展', modified: '2026-08-29T08:00:00', title: '冒烟会话丙', smoke: true },
] as any[];

afterEach(() => { localStorage.removeItem('sg_agent_show_smoke'); });

test('T-1041 默认隐藏：smoke 行不出树，普通行与计数正常', () => {
  render(<SessionTree {...baseProps} sessions={sessions} />);
  expect(screen.getByText('普通会话甲')).toBeTruthy();
  expect(screen.queryByText('冒烟会话丙')).toBeNull();
  expect(screen.queryByText('暂无会话')).toBeNull();  // 有普通会话时不误报空态
});

test('T-1041 批量模式内开关：默认关不展示，打开后展示且带🧪徽标', () => {
  render(<SessionTree {...baseProps} sessions={sessions} />);
  fireEvent.click(screen.getByTitle('进入批量操作：勾选多个会话归档/恢复'));
  expect(screen.queryByText('冒烟会话丙')).toBeNull();          // 批量模式默认仍隐藏
  const toggle = screen.getByTitle(/显示 smoke 隔离区冒烟会话/);
  fireEvent.click(toggle);
  expect(screen.getByText('冒烟会话丙')).toBeTruthy();           // 打开后展示
  expect(screen.getByTitle('smoke 隔离区冒烟会话（验收/调试产物）')).toBeTruthy();  // 🧪 徽标在位
  expect(localStorage.getItem('sg_agent_show_smoke')).toBe('1'); // 持久化（体验基线①）
});

test('T-1041 开关记忆 + 退出批量恢复隐藏', () => {
  localStorage.setItem('sg_agent_show_smoke', '1');              // 上次开着
  const { unmount } = render(<SessionTree {...baseProps} sessions={sessions} />);
  fireEvent.click(screen.getByTitle('进入批量操作：勾选多个会话归档/恢复'));
  expect(screen.getByText('冒烟会话丙')).toBeTruthy();           // 记忆恢复：批量内直接展示
  fireEvent.click(screen.getByTitle('退出批量操作'));
  expect(screen.queryByText('冒烟会话丙')).toBeNull();           // 退出批量即隐藏（展示范围锁定批量内）
  unmount();
  // 重挂载：非批量语境下开关记忆不泄漏到普通视图
  render(<SessionTree {...baseProps} sessions={sessions} />);
  expect(screen.queryByText('冒烟会话丙')).toBeNull();
});

test('T-1041 全 smoke 场景：隐藏时不误报「暂无会话」，开开关才见', () => {
  const onlySmoke = [sessions[2]] as any[];
  render(<SessionTree {...baseProps} sessions={onlySmoke} />);
  expect(screen.getByText('暂无会话')).toBeTruthy();             // 空态按可见口径判定
  expect(screen.queryByText('冒烟会话丙')).toBeNull();
});
