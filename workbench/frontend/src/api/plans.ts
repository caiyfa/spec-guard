/** api/plans — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import type { RunSummary } from './runs';

// ── 测试计划 ──
export interface ImportPreviewFile {
  path: string; module: string;
  valid: boolean; errors: string[]; frs: string[]; size: number;
}
export interface ImportPreview {
  ok: boolean; delta: string;
  proposal: { name: string; description: string };
  files: ImportPreviewFile[];
  frs: string[];
  matched_scenarios: { id: string; title: string; covers: string[] }[];
  unmatched_frs: string[];
  summary: {
    total_files: number;
    valid_count: number; error_count: number;
    total_frs: number; matched_scenarios: number;
  };
}
export interface RunQueueItem {
  id: number; emp_no: string; scope: string; target: string;
  env: string; plan_id: string; workspace: string;
  status: 'queued' | 'running';
  created_at: string; started_at: string;
}

export interface RunStatus {
  status: string; run_id: string; plan_id: string;
  is_running: boolean; is_paused: boolean;
  paused_at: string; breakpoints: string[];
  completed_scenarios: string[]; pending_scenarios: string[];
  current_emp_no?: string; current_workspace?: string;
  queue?: RunQueueItem[];
}

export interface TestPlan {
  id: string;
  name: string;
  description: string;
  env: string;
  filter: { scenarios?: string[]; tags?: string[]; modules?: string[] };
  tags: string[];
  scenario_count: number;
  resolved_scenarios?: string[];
  breakpoints?: string[];
  source_delta?: string;
  created_at: string;
  updated_at: string;
}

export const plansApi = {
  list: () => request<TestPlan[]>('/plans'),
  get: (id: string) => request<TestPlan>(`/plans/${id}`),
  save: (id: string, data: Partial<TestPlan>) =>
    request<TestPlan>(`/plans/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`/plans/${id}`, { method: 'DELETE' }),
  run: (id: string) =>
    request<{ ok: boolean; run_id: string; scenario_count: number }>(`/plans/${id}/run`, { method: 'POST' }),
  import: (deltaCode: string) =>
    request<{ ok: boolean; plan: TestPlan & { import_result?: { total_frs: number; matched_scenarios: number; unmatched_frs: string[] } } }>(
      `/plans/import/${deltaCode}`, { method: 'POST' }),
  importPreview: (deltaCode: string) =>
    request<ImportPreview>(`/plans/import-preview/${deltaCode}`),
  importConfirm: (deltaCode: string, selectedFiles: string[]) =>
    request<{ ok: boolean; imported_count: number; matched_scenarios: number }>(
      `/plans/import-confirm/${deltaCode}`,
      { method: 'POST', body: JSON.stringify({ selected_files: selectedFiles }) },
    ),
  history: (id: string, limit = 20) =>
    request<RunSummary[]>(`/plans/${id}/history?limit=${limit}`),
};

