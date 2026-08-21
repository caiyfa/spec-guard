/** api/zentao — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── 禅道集成（S5：建故事/提BUG/草案/锚点）──
export interface ZentaoJob {
  job_id: string;
  kind: string;
  status: string;
  zt_ref?: string;
  attempt: number;
  duplicate?: boolean;
  payload?: any;
  created_at?: string;
  finished_at?: string;
}

export interface StoryDraft {
  id: number;
  title: string;
  spec: string;
  source_refs: { type: string; ref?: string; url?: string; note?: string }[];
  status: string;
  session_id?: string;
  created_by?: string;
  created_at?: string;
  zt_story?: string;
}

export interface ExternalRef {
  id: number;
  type: string;
  ref: string;
  ref_url?: string;
  linked_type: string;
  linked: string;
  note?: string;
  registered_by?: string;
  created_at?: string;
}

export interface EstimateRecord {
  id: number;
  delta_id: string;
  zt_story?: string;
  breakdown: { item: string; points: number }[];
  points: number;
  confidence: number;
  ref_list: { estimate_id: number; delta_id: string; points: number }[];
  status: string;
  confirmed_by?: string;
  created_at?: string;
}

export const zentaoApi = {
  frozenDeltas: () => request<{ deltas: { delta_id: string; frozen: boolean }[] }>('/zentao/frozen-deltas'),
  createStory: (delta_id: string, title?: string) =>
    request<{ job: ZentaoJob }>('/zentao/stories', { method: 'POST', body: JSON.stringify({ delta_id, title }) }),
  createStoryFromDraft: (draft_id: number) =>
    request<{ job: ZentaoJob }>('/zentao/stories/from-draft', { method: 'POST', body: JSON.stringify({ draft_id }) }),
  listStoryDrafts: (status = '') =>
    request<{ drafts: StoryDraft[] }>(`/zentao/story-drafts${status ? `?status=${status}` : ''}`),
  cancelStoryDraft: (draft_id: number) =>
    request<{ ok: boolean }>(`/zentao/story-drafts/${draft_id}/cancel`, { method: 'POST' }),
  estimatePoints: (story_id: string, delta_id: string) =>
    request<{ estimate: EstimateRecord }>(`/zentao/stories/${story_id}/estimate-points`, { method: 'POST', body: JSON.stringify({ delta_id }) }),
  writebackPoints: (story_id: string, estimate_id: number) =>
    request<{ job: ZentaoJob }>(`/zentao/stories/${story_id}/writeback-points`, { method: 'POST', body: JSON.stringify({ estimate_id }) }),
  confirmEstimate: (estimate_id: number, verdict: 'confirm' | 'reject') =>
    request<{ estimate: EstimateRecord }>(`/zentao/estimates/${estimate_id}/confirm`, { method: 'POST', body: JSON.stringify({ verdict }) }),
  listEstimates: (delta_id = '', status = '') =>
    request<{ estimates: EstimateRecord[] }>(`/zentao/estimates?delta_id=${encodeURIComponent(delta_id)}${status ? `&status=${status}` : ''}`),
  createBugFromRun: (run_id: string, scenario_id: string, severity: number, title?: string, spq_id?: string, story_id?: string) =>
    request<{ job: ZentaoJob }>('/zentao/bugs/from-run', { method: 'POST', body: JSON.stringify({ run_id, scenario_id, severity, title, spq_id, story_id }) }),
  createBugManual: (title: string, steps: string, severity: number, story_id?: string, fr_ref?: string) =>
    request<{ job: ZentaoJob }>('/zentao/bugs/manual', { method: 'POST', body: JSON.stringify({ title, steps, severity, story_id, fr_ref }) }),
  pollBug: (bug_id: string) =>
    request<{ bug_id: string; status: string; title: string; regression_suggested: boolean; message: string }>(`/zentao/bugs/${bug_id}/poll`),
  getJob: (job_id: string) => request<{ job: ZentaoJob }>(`/zentao/jobs/${job_id}`),
  listJobs: (status = '') =>
    request<{ jobs: ZentaoJob[] }>(`/zentao/jobs${status ? `?status=${status}` : ''}`),
  listRefs: (linked_type = '', linked = '') =>
    request<{ refs: ExternalRef[] }>(`/zentao/refs?linked_type=${encodeURIComponent(linked_type)}${linked ? `&linked=${encodeURIComponent(linked)}` : ''}`),
  registerRef: (type: string, ref: string, linked_type: string, linked: string, note?: string, ref_url?: string) =>
    request<{ ref: ExternalRef }>('/zentao/refs', { method: 'POST', body: JSON.stringify({ type, ref, linked_type, linked, note, ref_url }) }),
  reconcile: () => request<{ fixed: string[] }>('/zentao/jobs/reconcile', { method: 'POST' }),
};

