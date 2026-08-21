/** api/coverage — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── T-060：覆盖缺口（三态聚合 / backlink / 生成下一批）──
export interface CoverageLaneItem {
  fr: string;
  name: string;
  module: string;
  reason?: string;
  source_delta?: string;
  draft_id?: string;
  scenario_id?: string;
  gates?: { g1: string; g2: string; g3: string };
  scenarios?: string[];
}
export interface CoverageDimensionStat {
  dimension: string;
  label: string;
  count: number;
  scenarios: string[];
  frs: string[];
}
export interface CoverageGaps {
  module: string;
  fr_total: number;
  lanes: {
    gap: CoverageLaneItem[];
    draft: CoverageLaneItem[];
    covered: CoverageLaneItem[];
  };
  suggested_order: string[];
  dimensions?: { lanes: CoverageDimensionStat[]; unassigned: string[] };
  fingerprint: string;
}
export interface CoverageBacklink {
  fr: string;
  exists: boolean;
  title?: string;
  module?: string;
  scenarios: { id: string; module: string }[];
  drafts: { draft_id: string; scenario_id: string; source_delta: string }[];
  recent_runs: { run_id: string; verdict: string; finished_at: string }[];
  deltas: string[];
}
export const coverageApi = {
  gaps: (module = '') =>
    request<CoverageGaps>(`/coverage/gaps${module ? `?module=${encodeURIComponent(module)}` : ''}`),
  backlink: (frId: string) =>
    request<CoverageBacklink>(`/coverage/backlink/${encodeURIComponent(frId)}`),
  nextBatch: (frs: string[], sourceDelta = '') =>
    request<{ batch_id: string; produced: { fr: string; draft_id: string; scenario_id: string }[]; rejected: { fr: string; reason: string }[]; note: string }>(
      '/coverage/next-batch', { method: 'POST', body: JSON.stringify({ frs, source_delta: sourceDelta }) }),
};

