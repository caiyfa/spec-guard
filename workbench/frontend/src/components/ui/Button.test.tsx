import { describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Button } from './Button';

describe('Button（T-1044 U1：三档·B 形态）', () => {
  test('primary = 墨色实心（bg-gray-100/text-surface-2），非 info 蓝', () => {
    render(<Button variant="primary">确认入库</Button>);
    const el = screen.getByText('确认入库');
    expect(el.className).toContain('bg-gray-100');
    expect(el.className).toContain('text-surface-2');
    expect(el.className).not.toContain('bg-info');
  });

  test('ghost 默认档 + danger 统一软红', () => {
    render(<>
      <Button>重新校验</Button>
      <Button variant="danger">废弃草稿</Button>
    </>);
    expect(screen.getByText('重新校验').className).toContain('border-border');
    const danger = screen.getByText('废弃草稿');
    expect(danger.className).toContain('bg-fail/12');
    expect(danger.className).toContain('border-fail/35');
  });

  test('sm 尺寸 + disabled + 点击回调 + icon 槽', () => {
    const fn = vi.fn();
    render(<>
      <Button size="sm" onClick={fn}>小号</Button>
      <Button disabled>禁用</Button>
      <Button icon={<svg data-testid="ic" />}>带图标</Button>
    </>);
    expect(screen.getByText('小号').className).toContain('text-fs-aux');
    fireEvent.click(screen.getByText('小号'));
    expect(fn).toHaveBeenCalledTimes(1);
    expect((screen.getByText('禁用') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId('ic')).toBeTruthy();
  });
});
