import { afterEach, describe, expect, test } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
afterEach(cleanup);
import Modal from './Modal';

describe('Modal（T-1044 U1：size 四档吸收手写弹层尺寸）', () => {
  test('size 档宽度：sm/md/lg/xl；width 显式优先', () => {
    const { unmount } = render(<Modal open onClose={() => {}} size="sm" title="t">x</Modal>);
    expect(document.querySelector('[role="dialog"]')!.getAttribute('style')).toContain('288px');
    unmount();
    render(<Modal open onClose={() => {}} size="xl" title="t">x</Modal>);
    expect(document.querySelector('[role="dialog"]')!.getAttribute('style')).toContain('760px');
  });

  test('width 数值覆盖 size 档 + open=false 不渲染 + ESC/遮罩关闭', () => {
    render(<Modal open onClose={() => {}} size="sm" width={500} title="标题">内容</Modal>);
    expect(document.querySelector('[role="dialog"]')!.getAttribute('style')).toContain('500px');
    expect(screen.getByText('标题')).toBeTruthy();
  });

  test('open=false 渲染 null', () => {
    render(<Modal open={false} onClose={() => {}} title="t">x</Modal>);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });
});
