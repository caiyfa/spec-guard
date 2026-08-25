import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import StepFormCard from './StepFormCard';
import { dbApi } from '../api/db';

vi.mock('../api/db', () => ({
  dbApi: {
    query: vi.fn().mockResolvedValue({
      rows: [{ x: 1 }], row_count: 1, truncated: false,
      elapsed_ms: 2, sql_rendered: 'SELECT 1', total_ms: 5,
    }),
  },
}));
// VariablePopover 依赖会话上下文，与本交互无关——置空
vi.mock('./VariablePopover', () => ({ default: () => null }));

afterEach(cleanup);

const baseProps = {
  step: { type: 'db_query', body: { sql: 'SELECT 1' } },
  index: 0,
  empRoles: [], accounts: [], localVars: [], upstreamVars: [], envVars: [],
  onChange: vi.fn(), onRemove: vi.fn(), onMoveUp: vi.fn(), onMoveDown: vi.fn(),
};

describe('StepFormCard db_query 试跑', () => {
  beforeEach(() => vi.clearAllMocks());

  test('展开后有试跑按钮，点击执行并渲染结果表格', async () => {
    render(<StepFormCard {...baseProps} />);
    fireEvent.click(screen.getByText('SQL'));  // 折叠头展开卡片
    fireEvent.click(screen.getByText('▶ 试跑'));
    await waitFor(() => expect(dbApi.query).toHaveBeenCalledWith({ sql: 'SELECT 1', schema: undefined, vars: {} }));
    await waitFor(() => expect(screen.getByText('1 行')).toBeTruthy());
  });

  test('试跑失败显示错误（插值缺变量诚实提示）', async () => {
    (dbApi.query as any).mockRejectedValueOnce(new Error('SQL 插值失败: 变量未定义: emp.no'));
    render(<StepFormCard {...baseProps} />);
    fireEvent.click(screen.getByText('SQL'));
    fireEvent.click(screen.getByText('▶ 试跑'));
    await waitFor(() => expect(screen.getByText(/变量未定义/)).toBeTruthy());
  });
});
