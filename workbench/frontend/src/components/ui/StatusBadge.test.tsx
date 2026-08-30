import { afterEach, describe, expect, test } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
afterEach(cleanup);
import { StatusBadge, STATUS_GLYPHS } from './StatusBadge';

describe('StatusBadge（T-1044 U1：六状态唯一徽章·B 形态）', () => {
  test('六状态渲染：变量淡填类 + 图形符 + 文案', () => {
    render(<>
      <StatusBadge status="pass" label="PASS" />
      <StatusBadge status="fail" label="FAIL" />
      <StatusBadge status="skip" label="SKIP" />
      <StatusBadge status="blocked" label="BLOCKED" />
      <StatusBadge status="warn" label="WARN" />
      <StatusBadge status="info" label="INFO" />
    </>);
    expect(screen.getByText('PASS').className).toContain('bg-pass/12');
    expect(screen.getByText('PASS').className).toContain('text-pass');
    expect(screen.getByText('FAIL').className).toContain('bg-fail/12');
    expect(screen.getByText('SKIP').className).toContain('bg-skip/12');
    expect(screen.getByText('BLOCKED').className).toContain('bg-blocked/12');
    expect(screen.getByText('WARN').className).toContain('bg-warn/12');
    expect(screen.getByText('INFO').className).toContain('bg-info/12');
  });

  test('图形符是 SVG（状态退出 emoji），六状态各有定义', () => {
    const { container } = render(<StatusBadge status="pass" label="P" />);
    expect(container.querySelector('svg')).toBeTruthy();
    expect(Object.keys(STATUS_GLYPHS).sort()).toEqual(
      ['blocked', 'fail', 'info', 'neutral', 'pass', 'skip', 'warn'].sort());
  });

  test('neutral 态（未运行）+ sm 尺寸档 + title', () => {
    render(<StatusBadge status="neutral" label="未运行" size="sm" title="提示" />);
    const el = screen.getByTitle('提示');
    expect(el.className).toContain('bg-gray-600/15');
    expect(el.className).toContain('text-fs-micro');
  });
});
