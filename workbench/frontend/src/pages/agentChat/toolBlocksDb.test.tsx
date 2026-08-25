import { describe, expect, test } from 'vitest';
import { parseDbEvidenceResult } from '../../components/SqlResultTable';

describe('parseDbEvidenceResult', () => {
  test('db_evidence JSON 解析为表格数据', () => {
    const out = parseDbEvidenceResult(JSON.stringify({ sql: 'SELECT 1', row_count: 2, rows: [{ x: 1 }, { x: 2 }] }));
    expect(out?.row_count).toBe(2);
  });
  test('非 JSON / 无 rows 回退 null', () => {
    expect(parseDbEvidenceResult('普通文本')).toBeNull();
    expect(parseDbEvidenceResult('{"foo":1}')).toBeNull();
  });
});
