/** 只读 SQL 结果表格（设计 2026-08-25 §A5）——三处复用：
 * AgentChat db_evidence 工具块（G3）/ DB 面板结果区（A3）/ SqlAuxPanel 试跑结果（C2）。 */
export interface SqlResultData {
  rows: Record<string, unknown>[];
  row_count?: number;
  truncated?: boolean;
}

export function SqlResultTable({ rows, truncated, row_count }: SqlResultData & { truncated?: boolean; row_count?: number }) {
  const count = row_count ?? rows.length;
  if (!rows.length) {
    return <div className="text-xs text-gray-500 py-2">{count} 行（无数据）</div>;
  }
  const columns = Object.keys(rows[0]);
  return (
    <div className="text-xs">
      <div className="flex items-center gap-2 mb-1 text-gray-500">
        <span>{count} 行</span>
        {truncated && <span className="text-yellow-500/80">（结果超上限，已截断）</span>}
      </div>
      <div className="overflow-x-auto max-h-72 border border-border rounded">
        <table className="min-w-full">
          <thead>
            <tr className="bg-surface-3 text-left">
              {columns.map(c => (
                <th key={c} className="px-2 py-1 font-mono text-gray-400 whitespace-nowrap">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-border/50">
                {columns.map(c => (
                  <td key={c} className="px-2 py-0.5 font-mono text-gray-300 truncate max-w-[240px]"
                      title={String(r[c] ?? '')}>
                    {String(r[c] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 从工具结果文本解析 db_evidence 输出（含 rows 数组的 JSON）——解析失败返回 null（调用方回退纯文本）。 */
export function parseDbEvidenceResult(text: string): SqlResultData | null {
  try {
    const obj = JSON.parse(text);
    if (obj && Array.isArray(obj.rows)) {
      return { rows: obj.rows, row_count: obj.row_count ?? obj.rows.length };
    }
  } catch { /* 回退纯文本 */ }
  return null;
}
