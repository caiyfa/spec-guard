import { afterEach, describe, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
afterEach(cleanup);
import { StateView } from './StateView';

describe('StateView（T-1044 U1：三态分离·B 形态）', () => {
  test('loading = shimmer 骨架条（非文字占位）', () => {
    render(<StateView loading skeletonRows={4} />);
    const el = screen.getByTestId('stateview-loading');
    expect(el.getAttribute('aria-label')).toBe('加载中…');
    expect(el.querySelectorAll('.skeleton-bar').length).toBe(4);
  });

  test('error = fail 徽章 + 原因 + 重试回调', () => {
    const fn = vi.fn();
    render(<StateView error="网络不可达" onRetry={fn} />);
    expect(screen.getByText('加载失败')).toBeTruthy();
    expect(screen.getByText('网络不可达')).toBeTruthy();
    fireEvent.click(screen.getByText('重试'));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('empty = 图形 + 衬线标题 + 描述 + CTA', () => {
    const fn = vi.fn();
    render(<StateView empty emptyTitle="该模块还没有场景用例" emptyDesc="从需求信息包生成第一个草稿"
      emptyCta={{ label: '生成场景', onClick: fn }} />);
    const el = screen.getByTestId('stateview-empty');
    expect(el.querySelector('.font-display')).toBeTruthy();  // B：衬线标题
    expect(screen.getByText('该模块还没有场景用例')).toBeTruthy();
    fireEvent.click(screen.getByText('生成场景'));
    expect(fn).toHaveBeenCalledTimes(1);
  });

  test('优先级 loading > error > empty；全部缺省渲染 null', () => {
    render(<StateView loading error="x" empty />);
    expect(screen.queryByTestId('stateview-error')).toBeNull();
    const { container } = render(<StateView />);
    expect(container.innerHTML).toBe('');
  });
});
