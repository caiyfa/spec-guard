/** api/attribution — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── T-063：失败归因（证据包 / 定性建议 / SPQ 台账）──
export interface EvidencePack {
  scenario_id: string;
  run_id: string;
  flow_digest: string;
  response_snapshot: { status: number | null; body_excerpt: string; assertion_failed: string };
  db_snapshots: any[];
  env_fingerprint: { env: string; started_at: string; gateway: string };
  collected_by: string;
  note: string;
}
export interface AttributeResult {
  run_id: string;
  scenario_id: string;
  evidence: EvidencePack;
  suggestion: { kind: string; rationale: string };
  honesty_review: { required: boolean; conclusion: string; rule?: string };
  note: string;
}
export interface SpqEntry {
  spq_id: string;
  title: string;
  status: string;
  run_id?: string;
  scenario_id?: string;
  fr_refs?: string[];
  suggestion_kind?: string;
  decided_kind?: string;
  decided_by?: string;
  decided_at?: string;
  linkage_warnings?: string[];
  info_pack_synced?: string[];
  created_at: string;
}
export const attributionApi = {
  attribute: (runId: string, scenarioId: string) =>
    request<AttributeResult>(`/runs/${encodeURIComponent(runId)}/attribute`, {
      method: 'POST', body: JSON.stringify({ scenario_id: scenarioId }),
    }),
  evidence: (runId: string, scenarioId: string) =>
    request<EvidencePack>(`/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(scenarioId)}`),
  spqList: (status = '') =>
    request<{ entries: SpqEntry[] }>(`/feedback/spq${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  spqCreate: (body: { title: string; run_id?: string; scenario_id?: string; fr_refs?: string[]; suggestion_kind?: string; decided_kind: string; comment?: string }) =>
    request<SpqEntry>('/feedback/spq', { method: 'POST', body: JSON.stringify(body) }),
  spqPatch: (spqId: string, status: string, note = '') =>
    request<SpqEntry>(`/feedback/spq/${encodeURIComponent(spqId)}`, {
      method: 'PATCH', body: JSON.stringify({ status, note }),
    }),
  spqSyncInfoPack: (spqId: string, ivId: string) =>
    request<{ added: boolean; spq_id: string; iv_id: string }>(
      `/feedback/spq/${encodeURIComponent(spqId)}/sync-info-pack`, {
        method: 'POST', body: JSON.stringify({ iv_id: ivId }),
      }),
};

