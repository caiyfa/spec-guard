import { afterEach, describe, expect, test } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
afterEach(cleanup);
import { DraftGateBadges, gateBadgeProps } from './DraftGateBadges';

describe('DraftGateBadges（T-1044 U2：三闸徽章组唯一事实源）', () => {
  test('全过态：①已评审 ②校验✓ ③门禁✓ 全 pass', () => {
    render(<DraftGateBadges gates={{ g1: 'approved', g2: 'pass', g3: 'pass' }} />);
    expect(screen.getByText('① 已评审').className).toContain('bg-pass/12');
    expect(screen.getByText('② 校验✓').className).toContain('bg-pass/12');
    expect(screen.getByText('③ 门禁✓').className).toContain('bg-pass/12');
  });

  test('混合态：驳回 fail / 校验败 fail / 未跑 neutral；gates 缺省三 neutral', () => {
    render(<DraftGateBadges gates={{ g1: 'rejected', g2: 'fail' }} />);
    expect(screen.getByText('① 已驳回').className).toContain('bg-fail/12');
    expect(screen.getByText('② 校验✗').className).toContain('bg-fail/12');
    expect(screen.getByText('③ 门禁⏸').className).toContain('bg-gray-600/15');
    expect(gateBadgeProps(undefined).map(b => b.status)).toEqual(['warn', 'neutral', 'neutral']);
  });

  test('sm 尺寸档（列表行）', () => {
    render(<DraftGateBadges gates={{ g1: 'approved' }} size="sm" />);
    expect(screen.getByText('① 已评审').className).toContain('text-fs-micro');
  });
});
