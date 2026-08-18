import { test, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import Home from './Home';
import { greeting, onlyPublicMenus } from '../utils/home';
import type { CurrentUser, NavGroup } from '../api';

const user: CurrentUser = {
  emp_no: '90000001', name: '张三', role: 'tester',
  roles: ['tester'], default_workspace: '', auth_mode: 'mock',
};

const publicTree: NavGroup[] = [
  { label: 'Agent', icon: '🤖', items: [{ to: '/agent', label: '对话' }] },
];
const fullTree: NavGroup[] = [
  { label: '总览', icon: '📊', items: [{ to: '/dashboard', label: '仪表盘' }] },
  { label: 'Agent', icon: '🤖', items: [{ to: '/agent', label: '对话' }] },
  { label: '空分组', icon: '🧪', items: [] },
];

function renderHome(props: Partial<Parameters<typeof Home>[0]> = {}) {
  return render(
    <MemoryRouter>
      <Home user={user} navTree={fullTree} navLoaded navError={false} onRetryNav={() => {}} {...props} />
    </MemoryRouter>
  );
}

// ── 时段问候 ──
test('greeting 各时段分支', () => {
  expect(greeting(7)).toBe('早上好');
  expect(greeting(12)).toBe('中午好');
  expect(greeting(15)).toBe('下午好');
  expect(greeting(20)).toBe('晚上好');
  expect(greeting(2)).toBe('深夜好');
});

// ── 零权限判定 ──
test('onlyPublicMenus：仅公开菜单 true / 含授权菜单 false / 空树 false', () => {
  expect(onlyPublicMenus(publicTree)).toBe(true);
  expect(onlyPublicMenus(fullTree)).toBe(false);
  expect(onlyPublicMenus([])).toBe(false);
});

// ── Hero 渲染 ──
test('Hero 显示问候+姓名+主 CTA 指向 /agent', () => {
  const { container } = renderHome();
  expect(container.textContent).toContain('张三');
  expect(container.textContent).toContain('开始 Agent 对话');
  expect(container.querySelector('a[href="/agent"]')).not.toBeNull();
});

// ── 提示条显隐 ──
test('仅公开菜单时出现提示条，有授权菜单时不出现', () => {
  const zero = renderHome({ navTree: publicTree });
  expect(zero.container.textContent).toContain('暂未开通功能菜单');
  zero.unmount();
  const full = renderHome({ navTree: fullTree });
  expect(full.container.textContent).not.toContain('暂未开通功能菜单');
});

// ── 卡片渲染与空分组过滤 ──
test('卡片按 navTree 渲染分组与菜单项，空分组不渲染', () => {
  const { container } = renderHome();
  expect(container.textContent).toContain('总览');
  expect(container.textContent).toContain('仪表盘');
  expect(container.querySelector('a[href="/dashboard"]')).not.toBeNull();
  expect(container.textContent).not.toContain('空分组');
});

// ── navError 重试 ──
test('navError 时显示加载失败与重试，点击触发 onRetryNav', () => {
  const onRetryNav = vi.fn();
  const { container } = renderHome({ navError: true, onRetryNav });
  expect(container.textContent).toContain('菜单加载失败');
  fireEvent.click(container.querySelector('button')!);
  expect(onRetryNav).toHaveBeenCalledTimes(1);
});
