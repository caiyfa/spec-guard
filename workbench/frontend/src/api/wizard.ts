/** api/wizard — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request, uploadFile, uploadFiles } from './core';

// ── K-046：依赖建议 / 草稿试跑 ──
export interface DepSuggestion {
  consumer: string;
  consumer_title: string;
  consumer_is_draft?: boolean;
  dep_id: string;
  dep_title: string;
  dep_version: string;
  reason: string;
  confidence: 'high' | 'medium';
  kind: 'cross_ref' | 'var_match';
}

export interface DepSuggestResult {
  ok: boolean;
  suggestions: DepSuggestion[];
  unresolved: Record<string, string[]>;
  graph_error?: string;  // T-104：建图失败（环预检失效）显式提示
}

export interface TrialRunRecord {
  scenario_id: string;
  verdict: string;
  duration_ms?: number;
  error?: string;
  reason?: string;
}

export interface TrialRunResult {
  ok: boolean;
  run_id?: string;   // 试跑任务号（agent_ 前缀；失败时发给 Agent 可排查：日志/断言差异/DB 证据）
  target?: string;
  verdict?: string;
  env?: string;
  records?: TrialRunRecord[];
  report_dir?: string;
  error?: string;
  reason?: string;
}

// ── 场景创建向导（G2-1）──
// K-013：info_pack 条目化（sha=内容指纹，commit=git 工作区 HEAD，added_at=添加时间）
export interface InfoPackEntry {
  path: string;
  sha: string;
  commit: string;
  added_at: string;
}

export interface PackFreshnessFile {
  path: string;
  status: 'fresh' | 'stale' | 'missing';
  stored_sha: string;
  current_sha: string;
}

export interface InfoPackFreshness {
  files: PackFreshnessFile[];
  base_commit: string;
  head_commit: string;
  stale_count: number;
  has_commit?: boolean;
  inside_stale: string[];      // git diff：信息包内已变更
  outside_changes: string[];   // git diff：信息包外相关变更/新增
  error?: string;
}

export interface ScenarioMeta {
  id: string;
  name: string;
  module: string;
  workspace: string;
  info_pack: InfoPackEntry[];
  status: string;
  created_at: string;
  updated_at: string;
}

export const scenarioApi = {
  create: (body: { name: string; module?: string }) =>
    request<ScenarioMeta>('/scenarios/create', { method: 'POST', body: JSON.stringify(body) }),
  getMeta: (id: string) =>
    request<ScenarioMeta>(`/scenarios/${encodeURIComponent(id)}/meta`),
  updateInfoPack: (id: string, files: string[]) =>
    request<ScenarioMeta>(`/scenarios/${encodeURIComponent(id)}/info-pack`, {
      method: 'PUT',
      body: JSON.stringify({ files }),
    }),
  listMeta: () =>
    request<{ metas: ScenarioMeta[] }>('/scenarios/meta-list'),
  uploadInfoPackFile: (id: string, file: File) =>
    uploadFile<ScenarioMeta>(`/scenarios/${encodeURIComponent(id)}/info-pack/upload`, file),
  // K-034：聊天框上传附件 → 自动创建信息包（多文件一次成一个包）
  autoCreateInfoPack: (files: File[], name = '') =>
    uploadFiles<ScenarioMeta>('/scenarios/info-pack/auto-create', files, name ? { name } : undefined),
  infoPackFreshness: (id: string) =>
    request<InfoPackFreshness>(`/scenarios/${encodeURIComponent(id)}/info-pack/freshness`),
};

