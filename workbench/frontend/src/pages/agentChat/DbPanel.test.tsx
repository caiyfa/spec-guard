/** DbPanel（内嵌 DB 证据面板）单测：initialSql 回填自动执行 / 交给 SQL 助手直发回调 / 关闭回调。 */
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
import { DbPanel } from './DbPanel';
import { dbApi } from '../../api/db';

// jsdom 无 Monaco 运行时——编辑器等价替换为 textarea（交互契约不变）
vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: any) => (
    <textarea data-testid="sql-editor" value={value} onChange={(e) => onChange?.(e.target.value)} />
  ),
}));

vi.mock('../../api/db', () => ({
  dbApi: {
    schemas: vi.fn().mockResolvedValue({ schemas: [
      { name: 'default', is_default: true, alive: true },
      { name: 'biz', is_default: false, alive: true },
    ], default: 'default' }),
    query: vi.fn().mockResolvedValue({
      rows: [{ x: 1 }], row_count: 1, truncated: false,
      elapsed_ms: 2, sql_rendered: 'SELECT 1', total_ms: 5,
    }),
  },
}));

// vitest 未配 globals/setupFiles——RTL 无自动清理，手动 cleanup 防跨用例 DOM 累积；
// localStorage（草稿/schema/历史）同步清空，避免跨用例状态串扰
afterEach(() => {
  cleanup();
  localStorage.clear();
});

const renderPanel = (props: Partial<Parameters<typeof DbPanel>[0]> = {}) =>
  render(<DbPanel initialSql="" onClose={() => {}} onHandToAux={() => {}} {...props} />);

describe('DbPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  test('挂载拉取 schema 清单并默认选中 default', async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByText('default')).toBeTruthy());
    expect(screen.getByText('biz')).toBeTruthy();
  });

  test('initialSql 回填并自动执行（左栏「▶ DB 面板」联动契约）', async () => {
    renderPanel({ initialSql: 'SELECT COUNT(*) FROM tdm_inventory_session' });
    await waitFor(() => expect(dbApi.query).toHaveBeenCalledWith(
      expect.objectContaining({ sql: 'SELECT COUNT(*) FROM tdm_inventory_session' })));
    await waitFor(() => expect(screen.getByText('1 行')).toBeTruthy());
  });

  test('「交给 SQL 助手」直发 onHandToAux 回调（不走 sessionStorage 跳页中转）', async () => {
    const onHandToAux = vi.fn();
    renderPanel({ onHandToAux });
    await waitFor(() => screen.getByText('default'));
    fireEvent.change(screen.getByTestId('sql-editor'), { target: { value: 'SELECT 2' } });
    fireEvent.click(screen.getByTitle(/把当前 SQL 发给左栏 SQL 助手/));
    expect(onHandToAux).toHaveBeenCalledWith('SELECT 2');
    // 旧通道断言：不经 sessionStorage 中转
    expect(sessionStorage.getItem('sg_sql_aux_send')).toBeNull();
  });

  test('关闭按钮触发 onClose（退出 SQL 探索模式）', async () => {
    const onClose = vi.fn();
    renderPanel({ onClose });
    fireEvent.click(screen.getByTitle('关闭 DB 面板，返回主会话'));
    expect(onClose).toHaveBeenCalled();
  });

  test('守卫拒绝显示错误（不白屏）', async () => {
    (dbApi.query as any).mockRejectedValueOnce(new Error('只读守卫拒绝非查询语句: DELETE'));
    renderPanel({ initialSql: 'DELETE FROM x' });
    await waitFor(() => expect(screen.getByText(/只读守卫拒绝/)).toBeTruthy());
  });
});
