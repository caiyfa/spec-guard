/** DraftGateBadges — T-1044 U2 P1：草稿三闸状态徽章组（消灭 Drafts 列表行与操作栏两份复制）。
 *
 *  三闸语义（D1/T-061）：①人工评审 → ②格式校验 → ③发布门禁，缺一不入库。
 *  表达走 StatusBadge 原语（B 淡填徽章 + 图形符），不再手写 rounded 色块。
 */
import { StatusBadge, type BadgeStatus } from '../components/ui/StatusBadge';

export interface DraftGates {
  g1?: string;  // approved | rejected | pending
  g2?: string;  // pass | fail | 其他=未跑
  g3?: string;  // pass | fail | 其他=未跑
}

export function gateBadgeProps(gates?: DraftGates): { status: BadgeStatus; label: string }[] {
  const g1 = gates?.g1, g2 = gates?.g2, g3 = gates?.g3;
  return [
    g1 === 'approved' ? { status: 'pass', label: '① 已评审' }
      : g1 === 'rejected' ? { status: 'fail', label: '① 已驳回' }
        : { status: 'warn', label: '① 待评审' },
    g2 === 'pass' ? { status: 'pass', label: '② 校验✓' }
      : g2 === 'fail' ? { status: 'fail', label: '② 校验✗' }
        : { status: 'neutral', label: '② 待校验' },
    g3 === 'pass' ? { status: 'pass', label: '③ 门禁✓' }
      : g3 === 'fail' ? { status: 'fail', label: '③ 门禁✗' }
        : { status: 'neutral', label: '③ 门禁⏸' },
  ];
}

export function DraftGateBadges({ gates, size = 'md', className = '' }: {
  gates?: DraftGates;
  size?: 'sm' | 'md';
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1 flex-wrap ${className}`} data-testid="draft-gate-badges">
      {gateBadgeProps(gates).map(b => (
        <StatusBadge key={b.label} status={b.status} label={b.label} size={size} />
      ))}
    </span>
  );
}
