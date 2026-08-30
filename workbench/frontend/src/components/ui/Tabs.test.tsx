import { afterEach, describe, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
afterEach(cleanup);
import { Tabs } from './Tabs';

describe('Tabs（T-1044 U1：唯一下划线页签·B 形态）', () => {
  const items = [
    { id: 'runs', label: '执行记录', count: 15 },
    { id: 'fails', label: '失败台账', count: 3 },
    { id: 'cov', label: '覆盖率' },
  ];

  test('渲染页签与计数丸（选中签计数用 info 淡填）', () => {
    render(<Tabs items={items} activeId="runs" onChange={() => {}} />);
    expect(screen.getByRole('tablist')).toBeTruthy();
    const active = screen.getByRole('tab', { name: /执行记录/ });
    expect(active.getAttribute('aria-selected')).toBe('true');
    expect(active.className).toContain('border-gray-100');  // B：墨色下划线
    expect(screen.getByText('15').className).toContain('bg-info/12');
    expect(screen.getByText('3').className).toContain('bg-gray-600/15');
  });

  test('count 为 0/缺省不渲染计数丸', () => {
    render(<Tabs items={[{ id: 'a', label: '甲', count: 0 }, { id: 'b', label: '乙' }]} activeId="a" onChange={() => {}} />);
    expect(screen.queryByText('0')).toBeNull();
  });

  test('点击触发 onChange（切换选中）', () => {
    const fn = vi.fn();
    render(<Tabs items={items} activeId="runs" onChange={fn} />);
    fireEvent.click(screen.getByRole('tab', { name: /覆盖率/ }));
    expect(fn).toHaveBeenCalledWith('cov');
  });

  test('closable 文件签：✕ 触发 onClose 且不冒泡选中', () => {
    const change = vi.fn(), close = vi.fn();
    render(<Tabs items={[{ id: 'file:a.yaml', label: '📄 a.yaml', closable: true, onClose: close }]}
      activeId="file:a.yaml" onChange={change} />);
    fireEvent.click(screen.getByLabelText(/关闭/));
    expect(close).toHaveBeenCalledTimes(1);
    expect(change).not.toHaveBeenCalled();
  });
});
