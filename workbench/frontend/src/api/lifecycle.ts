/** api/lifecycle — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── K-xxx：单元测试生命周期监控（台账聚合） ──
export interface LifecycleItem {
  id: string;
  title: string;
  status: 'in_library' | 'draft_pending' | 'draft_updating' | 'discarded' | 'unknown';
  status_label: string;
  draft_status: string;
  draft_filename: string;
  module: string;
  version: string;
  tags: string[];
  covers: string[];
  file_path: string;
  updated_at: string;
  run_count: number;
  fail_count: number;
  last_run_id: string;
  last_verdict: string;
  last_run_at: string;
  recent_verdicts: string[];
  closed_loops: number;
  last_failure: { category: string; message: string; run_id: string; at: string } | null;
}

export interface LifecycleSummary {
  total: number;
  in_library: number;
  draft_pending: number;
  draft_updating: number;
  discarded: number;
  recent_failed_7d: number;
  closed_loops: number;
}

export interface LifecycleTimelineEvent {
  at: string;
  type: string;
  label: string;
  verdict?: string;
  detail?: string;
  run_id?: string;
}

export interface LifecycleDetail {
  id: string;
  title: string;
  module: string;
  version: string;
  file_path: string;
  status: string;
  status_label: string;
  draft_status: string;
  draft_filename: string;
  timeline: LifecycleTimelineEvent[];
  runs: { run_id: string; scenario_id: string; verdict: string; duration_ms: number; category: string; message: string; finished_at: string }[];
}

export const lifecycleApi = {
  list: () => request<{ summary: LifecycleSummary; items: LifecycleItem[] }>('/lifecycle/scenarios'),
  detail: (id: string) =>
    request<LifecycleDetail>(`/lifecycle/scenarios/${encodeURIComponent(id)}`),
};

