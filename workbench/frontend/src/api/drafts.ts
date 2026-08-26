/** api/drafts — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import type { DepSuggestResult, TrialRunResult } from './wizard';

// ── 草稿区三道闸（D1）──
export interface DraftItem {
  filename: string;
  scenario_id: string;
  title: string;
  size: number;
  modified: string;
  author?: string;
  source_meta?: string;  // K-013: 来源场景元数据 ID（SG-META-xxxx）
  stale?: boolean;       // K-013: 其信息包存在已变更/已删除文件
  source_files: string[]; // A+B: 生成时依赖的文件清单
  gates?: { g1: string; g2: string; g3: string };  // T-061: 三闸状态（pending/approved/rejected / pass/fail / blocked/pass/fail）
  source_delta?: string;  // T-061: 挂链 delta
}

export interface ValidateFinding {
  level: string;
  rule: string;
  message: string;
  scenario?: string;
  hint?: string;
}

export interface ValidateReport {
  verdict: string;
  scenario?: string;
  findings: ValidateFinding[];
  summary?: { error: number; warn: number };
}

/** 入库前 ID 冲突预检结果（K-xxx：草稿 ID 在场景库的既有位置；file_missing=草稿文件已不存在） */
export interface DraftConflictResult {
  ok: boolean;
  existing: { id: string; path: string; module: string } | null;
  count: number;
  file_missing?: boolean;
}

export const draftsApi = {
  list: () => request<{ drafts: DraftItem[] }>('/drafts'),
  modules: () => request<{ modules: string[] }>('/drafts/modules'),
  read: (filename: string) =>
    request<{ filename: string; content: string; depends_on: string[] }>(`/drafts/${encodeURIComponent(filename)}`),
  update: (filename: string, content: string) =>
    request<{ ok: boolean }>(`/drafts/${encodeURIComponent(filename)}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  suggestDeps: () => request<DepSuggestResult>('/drafts/suggest-deps'),
  addDep: (filename: string, depId: string, mode = 'shared') =>
    request<{ ok: boolean; consumer: string; dep_id: string }>(`/drafts/${encodeURIComponent(filename)}/deps`, {
      method: 'POST',
      body: JSON.stringify({ dep_id: depId, mode }),
    }),
  trialRun: (filename: string) =>
    request<TrialRunResult>(`/drafts/${encodeURIComponent(filename)}/trial-run`, { method: 'POST' }),
  validate: (filename: string) =>
    request<ValidateReport>(`/drafts/${encodeURIComponent(filename)}/validate`, { method: 'POST' }),
  conflict: (filename: string) =>
    request<DraftConflictResult>(`/drafts/${encodeURIComponent(filename)}/conflict`),
  promote: (filename: string, module: string, replace = false) =>
    request<any>(`/drafts/${encodeURIComponent(filename)}/promote`, {
      method: 'POST',
      body: JSON.stringify({ module, replace }),
    }),
  // T-061：第①闸人工评审（人拍板，留痕 reviewer+ts）
  review: (filename: string, decision: 'approved' | 'rejected', comment = '') =>
    request<any>(`/drafts/${encodeURIComponent(filename)}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, comment }),
    }),
  // T-061：重跑第②闸（格式校验自动先跑，修改后重新校验）
  revalidate: (filename: string) =>
    request<{ ok: boolean; gate2_status: string; gate2_report: ValidateReport }>(
      `/drafts/${encodeURIComponent(filename)}/revalidate`, { method: 'POST' }),
  discard: (filename: string) =>
    request<{ ok: boolean; trashed_to: string }>(`/drafts/${encodeURIComponent(filename)}/discard`, { method: 'POST' }),
};

