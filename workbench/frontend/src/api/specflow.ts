/** api/specflow — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request, uploadFile } from './core';

// ── 需求侧 specflow（S3/S4 前端缺口补丁 T-058/T-059：材料管理 + 评分与冻结）──
export interface InterviewItem {
  iv_id: string;
  title: string;
  status: string;
  session_id?: string;
  opened_at?: string;
}

export interface MaterialItem {
  mid: string;
  iv_id: string;
  filename: string;
  fmt: string;
  status: string;
  sha256_12: string;
  parse_error?: string;
  pack_included?: number;
  created_at?: string;
}

export interface MaterialTopic {
  tid: string;
  material_id?: string;
  title: string;
  summary?: string;
  confirmed: number;
}

export interface ScoreItem {
  id: number;
  dimension: string;
  score: number;
  source: string;
  evidence: string;
  status: string;
  spec_sha?: string;
}

export interface GateState {
  gate: string;
  status: string;
  confirmed?: boolean;
  verdict?: string;
  findings?: { rule: string; level: string; message: string }[];
  degraded?: boolean;
  errors?: string[];
}

// ── 对话操作台（GateDock 一期：只读汇总；操作仍走原有 REST 人拍板）──
export interface GateCard {
  kind: 'topic_confirm' | 'material_include' | 'score_confirm' | 'freeze_gates' | 'zentao_story';
  level: 'L1' | 'L2' | 'L3';  // 分档接管：L2 永远人拍板；L3 可逆低危可代执行
  title: string;
  summary: string;
  ref_id: string;
  payload: any;
}

export interface GateDockResp {
  interview: { iv_id: string; title: string; status: string; target_delta?: string } | null;
  cards: GateCard[];
}

export const specflowApi = {
  // 面试列表（下拉数据源）
  listInterviews: (status = '') =>
    request<{ interviews: InterviewItem[] }>(`/specflow/interviews${status ? `?status=${status}` : ''}`),
  // 材料（T-058）
  uploadMaterial: (iv_id: string, file: File) =>
    uploadFile<{ material: MaterialItem }>(`/specflow/interviews/${iv_id}/materials`, file),
  listMaterials: (iv_id: string, status = '') =>
    request<{ materials: MaterialItem[] }>(`/specflow/interviews/${iv_id}/materials${status ? `?status=${status}` : ''}`),
  previewMaterial: (mid: string) =>   // T-933：材料页签摘要（解析文本优先，截 20000 字）
    request<{ material_id: string; source: string; text: string; fmt?: string }>(`/specflow/materials/${mid}/preview`),
  listTopics: (mid: string, confirmedOnly = false) =>
    request<{ topics: MaterialTopic[] }>(`/specflow/materials/${mid}/topics?confirmed_only=${confirmedOnly}`),
  confirmTopic: (mid: string, tid: string, confirmed: boolean) =>
    request<{ topic: MaterialTopic }>(`/specflow/materials/${mid}/topics/${tid}/confirm`, { method: 'POST', body: JSON.stringify({ confirmed }) }),
  includeMaterial: (iv_id: string, mid: string, included: boolean) =>
    request<{ material: MaterialItem }>(`/specflow/interviews/${iv_id}/materials/${mid}/include`, { method: 'POST', body: JSON.stringify({ included }) }),
  readPack: (iv_id: string) =>
    request<{ pack: any }>(`/specflow/interviews/${iv_id}/pack`),
  reassemblePack: (iv_id: string) =>
    request<{ pack: any }>(`/specflow/interviews/${iv_id}/pack/reassemble`, { method: 'POST' }),
  // 对话操作台汇总（GateDock 一期，纯读）：按会话/面试聚合待办闸门卡片
  gateDock: (params: { session_id?: string; interview_id?: string }) => {
    const q = new URLSearchParams();
    if (params.session_id) q.set('session_id', params.session_id);
    if (params.interview_id) q.set('interview_id', params.interview_id);
    return request<GateDockResp>(`/specflow/gate-dock?${q.toString()}`);
  },
  // 评分（T-059）
  listScores: (iv_id: string) =>
    request<{ scores: ScoreItem[] }>(`/specflow/decisions/scores?interview_id=${encodeURIComponent(iv_id)}`),
  evaluateScores: (iv_id: string, spec_text = '') =>
    request<{ scores: ScoreItem[] }>('/specflow/decisions/scores/evaluate', { method: 'POST', body: JSON.stringify({ interview_id: iv_id, spec_text }) }),
  confirmScore: (score_id: number, verdict: 'confirm' | 'reject') =>
    request<{ score: ScoreItem }>(`/specflow/decisions/scores/${score_id}/confirm`, { method: 'POST', body: JSON.stringify({ verdict }) }),
  // 冻结三闸（T-059）
  gate1Confirm: (delta_id: string, interview_id = '') =>
    request<GateState>(`/specflow/freeze/changes/${delta_id}/gates/1-product-confirm`, { method: 'POST', body: JSON.stringify({ interview_id }) }),
  gate2Conformance: (delta_id: string, spec_text = '') =>
    request<GateState>(`/specflow/freeze/changes/${delta_id}/gates/2-conformance`, { method: 'POST', body: JSON.stringify({ spec_text }) }),
  checkGates: (delta_id: string, interview_id = '') =>
    request<{ freeze_allowed: boolean; gates: Record<string, GateState> }>(`/specflow/freeze/changes/${delta_id}/gates?interview_id=${encodeURIComponent(interview_id)}`),
  freezeDelta: (delta_id: string, interview_id = '') =>
    request<{ ok: boolean; error?: string; freeze?: any }>(`/specflow/freeze/changes/${delta_id}/freeze`, { method: 'POST', body: JSON.stringify({ interview_id }) }),
};

