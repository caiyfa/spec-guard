/** api/runs — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import type { RunStatus } from './plans';

// ── 执行控制 ──
export interface RunStats {
  pass: number;
  fail: number;
  skip: number;
  blocked: number;
  total: number;
  warnings: number;
}

export interface RunSummary {
  run_id: string;
  env: string;
  system: string;
  started_at: string;
  finished_at: string;
  stats: RunStats;
  leases: Record<string, Record<string, string>>;
}

// T-311：执行前依赖预检结果（runs/preflight）
export interface PreflightGap {
  key?: string;        // missing_env
  account?: string;    // missing_accounts
  ref?: string;        // unresolved_upstream
  tpl?: string;        // unresolved_templates_gaps（T-318）
  file?: string;       // missing_files / unknown_file_refs_gaps（T-502）
  scenarios: string[];
}
export interface PreflightScenario {
  id: string;
  accounts: string[];
  env_keys: string[];
  upstream_refs: string[];
  unresolved_templates: string[];
  file_refs: string[];          // T-502：with.file 引用（含插值）
  missing_files: string[];      // T-502：仓库缺陷——已提交但文件不存在
  unknown_file_refs: string[];  // T-502：含插值路径，静态不可判
  missing_accounts: string[];
  missing_env: string[];
  unresolved_upstream: string[];
  has_gaps: boolean;
}
export interface PreflightResult {
  env: string;
  system: string;
  selected: string[];
  scenario_count: number;
  scenarios: PreflightScenario[];
  accounts: string[];
  env_keys: string[];
  upstream_refs: string[];
  unresolved_templates: string[];
  file_refs: string[];                    // T-502
  missing_accounts: PreflightGap[];
  missing_env: PreflightGap[];
  unresolved_upstream: PreflightGap[];
  unresolved_templates_gaps: PreflightGap[];
  missing_files: PreflightGap[];          // T-502：预检阻断（仓库缺陷，无覆盖输入）
  unknown_file_refs: string[];            // T-502：插值路径集合
  unknown_file_refs_gaps: PreflightGap[]; // T-502：插值路径分组
  has_gaps: boolean;
  error?: string;
}

export const runsApi = {
  trigger: (scope: string, target = '', env = 'sit', breakpoints: string[] = [],
            light?: { prepOnly?: boolean; skipUpstreamVerify?: boolean; accountOverride?: string },
            overrides: { kind: string; name: string; value: string }[] = []) =>
    request<{ ok: boolean; run_id?: string; queued?: boolean; queue_id?: number; position?: number }>('/runs/trigger', {
      method: 'POST',
      body: JSON.stringify({
        scope, target, env, breakpoints,
        prep_only: !!light?.prepOnly,
        skip_upstream_verify: !!light?.skipUpstreamVerify,
        account_override: light?.accountOverride || '',
        overrides,  // T-312：预检弹窗输入的变量覆盖（账号/env 键）
      }),
    }),
  accounts: () => request<{ accounts: Record<string, { ad: string; emp_no: string; type: string }>; env: string }>('/runs/accounts'),
  // T-311：执行前依赖预检（确认弹窗前静态比对账号/env 键/跨场景引用）
  preflight: (scenarios: string[], env?: string) =>
    request<PreflightResult>(`/runs/preflight?scenarios=${encodeURIComponent(scenarios.join(','))}${env ? `&env=${encodeURIComponent(env)}` : ''}`),
  log: (runId: string, tail = 500) =>
    request<{ run_id: string; total_lines: number; log: string }>(`/runs/${encodeURIComponent(runId)}/log?tail=${tail}`),
  context: (runId: string) =>
    request<{ run_id: string; context: Record<string, unknown> | null; hint?: string }>(`/runs/${encodeURIComponent(runId)}/context`),
  abort: () => request<{ ok: boolean }>('/runs/abort', { method: 'POST' }),
  resume: () => request<{ ok: boolean }>('/runs/resume', { method: 'POST' }),
  status: () => request<RunStatus>('/runs/status'),
  cancelQueued: (itemId: number) =>
    request<{ ok: boolean }>(`/runs/queue/${itemId}`, { method: 'DELETE' }),
  history: (limit = 20) => request<RunSummary[]>(`/runs/history?limit=${limit}`),
  // T-121：失败索引台账（K-052）——History 页「场景 × 任务号 × 原因」查询
  failures: (scenarioId = '', limit = 10) =>
    request<FailureEntry[]>(`/runs/failures?scenario_id=${encodeURIComponent(scenarioId)}&limit=${limit}`),
  get: (runId: string) => request<Record<string, unknown>>(`/runs/${runId}`),
  // 单场景 case 详情（设计 2026-08-25 §A4 入口②；case_file 相对 run 目录，如 cases/PP-RC-001.json）
  getCase: (runId: string, caseFile: string) =>
    request<Record<string, any>>(`/runs/${runId}/cases/${caseFile}`),
};

export interface FailureEntry {
  run_id: string;
  scenario_id: string;
  verdict: string;
  category: string;
  message: string;
  env: string;
  finished_at: string;
  log: string;
}

