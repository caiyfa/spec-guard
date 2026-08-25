import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SqlResultTable } from './SqlResultTable';

describe('SqlResultTable', () => {
  test('渲染列头与行（首行键序）', () => {
    render(<SqlResultTable rows={[{ emp_no: '90024713', name: '张三' }, { emp_no: '90024714', name: '李四' }]} />);
    expect(screen.getByText('emp_no')).toBeTruthy();
    expect(screen.getByText('张三')).toBeTruthy();
    expect(screen.getByText('李四')).toBeTruthy();
  });

  test('空 rows 显示空态', () => {
    render(<SqlResultTable rows={[]} />);
    expect(screen.getByText(/0 行/)).toBeTruthy();
  });

  test('truncated=true 显示截断提示', () => {
    render(<SqlResultTable rows={[{ x: 1 }]} truncated />);
    expect(screen.getByText(/已截断/)).toBeTruthy();
  });

  test('超长单元格省略（title 可看全文）', () => {
    const long = 'a'.repeat(200);
    render(<SqlResultTable rows={[{ col: long }]} />);
    const cell = screen.getByTitle(long);
    expect(cell.className).toContain('truncate');
  });
});
