import { afterEach, describe, expect, test } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
afterEach(cleanup);
import { ToastContainer, toast } from './Toast';

describe('Toast（T-1044 U1：单例容器·B 形态纸条）', () => {
  test('toast.ok/fail/info 推入即渲染（图形符 + 文案）', async () => {
    render(<ToastContainer />);
    await act(async () => { toast.ok('校验通过'); });
    await act(async () => { toast.fail('入库失败'); });
    expect(screen.getByText('校验通过')).toBeTruthy();
    expect(screen.getByText('入库失败')).toBeTruthy();
    const container = screen.getByTestId('toast-container');
    expect(container.querySelectorAll('svg').length).toBeGreaterThanOrEqual(2);
  });

  test('手动关闭移除对应纸条', async () => {
    render(<ToastContainer />);
    await act(async () => { toast.info('后台同步中'); });
    expect(screen.getByText('后台同步中')).toBeTruthy();
    const closeBtns = screen.getAllByLabelText('关闭');
    await act(async () => { closeBtns[closeBtns.length - 1].click(); });
    expect(screen.queryByText('后台同步中')).toBeNull();
  });
});
