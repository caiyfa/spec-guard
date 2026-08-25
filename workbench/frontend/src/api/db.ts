/** api/db — DB 证据面板（设计 2026-08-25 §A2/A3） */
import { request } from './core';

export interface DbSchema { name: string; is_default: boolean; alive: boolean }
export interface DbQueryResult {
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  elapsed_ms: number;
  sql_rendered: string;
  total_ms: number;
}

export const dbApi = {
  schemas: () => request<{ schemas: DbSchema[]; default: string }>('/db/schemas'),
  query: (body: { sql: string; schema?: string; vars?: Record<string, unknown> }) =>
    request<DbQueryResult>('/db/query', { method: 'POST', body: JSON.stringify(body) }),
};
