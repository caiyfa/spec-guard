import { describe, expect, test, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';
import { MemoryRouter } from 'react-router';
import { DbConsole } from './DbConsole';
import { dbApi } from '../api/db';

// jsdom 无 Monaco 运行时——编辑器等价替换为 textarea（交互契约不变）
vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: any) => (
    <textarea data-testid="sql-editor" value={value} onChange={(e) => onChange?.(e.target.value)} />
  ),
}));

vi.mock('../api/db', () => ({
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

// vitest 未配 globals/setupFiles——RTL 无自动清理，手动 cleanup 防跨用例 DOM 累积
afterEach(cleanup);

const renderPage = () => render(<MemoryRouter><DbConsole /></MemoryRouter>);

describe('DbConsole', () => {
  beforeEach(() => vi.clearAllMocks());

  test('挂载拉取 schema 清单并默认选中 default', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('default')).toBeTruthy());
    expect(screen.getByText('biz')).toBeTruthy();
  });

  test('执行查询渲染结果表格', async () => {
    renderPage();
    await waitFor(() => screen.getByText('default'));
    fireEvent.click(screen.getByTitle('执行 (Ctrl+Enter)'));
    await waitFor(() => expect(screen.getByText('1 行')).toBeTruthy());
    expect(dbApi.query).toHaveBeenCalled();
  });

  test('守卫拒绝显示错误（不白屏）', async () => {
    (dbApi.query as any).mockRejectedValueOnce(new Error('只读守卫拒绝非查询语句: DELETE'));
    renderPage();
    await waitFor(() => screen.getByText('default'));
    fireEvent.click(screen.getByTitle('执行 (Ctrl+Enter)'));
    await waitFor(() => expect(screen.getByText(/只读守卫拒绝/)).toBeTruthy());
  });

  test('只读提示常驻（共享只读账号须知）', () => {
    renderPage();
    expect(screen.getByText(/只读查询/)).toBeTruthy();
  });
});
