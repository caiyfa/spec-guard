/** api/scenarios — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import type { DepSuggestResult } from './wizard';

// ── 场景管理 ──
export interface Scenario {
  id: string;
  title: string;
  version: string;
  priority: string;
  tags: string[];
  depends_on: { id: string; mode: string; version?: string | null; optional?: boolean }[];
  produces: { resource: string; state: string }[];
  has_teardown: boolean;
  category: 'producer' | 'modifier' | 'query' | 'validator';
  covers: string[];
  module: string;
  path: string;
  updated_at?: string;  // T-320：场景最后更新时间（YAML mtime，'YYYY-MM-DD HH:MM'）
}

export interface DagEdge {
  id: string; source: string; target: string; animated: boolean; label: string;
  status?: 'match' | 'minor_drift' | 'major_drift' | 'orphan';
  expected?: string | null;
  actual?: string | null;
}

export interface DagData {
  nodes: { id: string; data: Record<string, unknown> }[];
  edges: DagEdge[];
}

export interface DriftItem {
  consumer: string; id: string; expected: string | null;
  actual: string | null; status: string; optional: boolean;
}

export const scenariosApi = {
  list: () => request<Scenario[]>('/scenarios'),
  dag: () => request<DagData>('/scenarios/dag'),
  validate: () => request<{ ok: boolean; cycles: string[][] }>('/scenarios/validate'),
  drift: () => request<{ items: DriftItem[]; orphans: Record<string, string[]>; cycles: string[][] }>('/scenarios/drift'),
  get: (id: string) => request<{ id: string; content: string }>(`/scenarios/${id}`),
  save: (id: string, content: string) =>
    request<{ ok: boolean }>(`/scenarios/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  editDep: (id: string, body: { action: 'add' | 'remove'; dep_id: string; mode?: 'shared' | 'exclusive'; note?: string }) =>
    request<{ ok: boolean }>(`/scenarios/${id}/deps`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  suggestDeps: (id: string) =>
    request<DepSuggestResult>(`/scenarios/${encodeURIComponent(id)}/suggest-deps`),
};

