/** api/spec — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── Spec 校验 ──
export interface DeltaInfo { id: string; has_proposal: boolean; has_specs: boolean; has_modules: boolean; has_yaml_testcases: boolean }
export interface SpecFinding { level: string; vid: string; message: string; scenario?: string }
export interface SpecValidationResult {
  verdict: string; delta: string; mode: string;
  findings: SpecFinding[];
  summary: { error: number; warn: number; info?: number };
  raw_output?: string; report_path?: string;
}
export interface TestCaseValidationResult {
  verdict: string; total_scenarios: number;
  findings: SpecFinding[];
  summary: { error: number; warn: number };
}

export const specApi = {
  deltas: () => request<{ current: string; deltas: DeltaInfo[] }>('/spec/deltas'),
  validate: (delta: string, mode: string) =>
    request<SpecValidationResult>('/spec/validate', {
      method: 'POST', body: JSON.stringify({ delta, mode }),
    }),
  report: (path: string) => request<{ path: string; content: string }>(`/spec/report?path=${encodeURIComponent(path)}`),
  validateTestCases: () => request<TestCaseValidationResult>('/spec/validate-testcases'),
  pushBranch: () =>
    request<{ ok: boolean; output?: string; error?: string; note?: string; ahead?: number; commits?: string[] }>('/spec/push', { method: 'POST' }),
};

// ── rebase 中断界面化恢复 ──
export const rebaseApi = {
  status: () =>
    request<{ ok: boolean; in_progress: boolean; state: string; onto: string; conflicts: { path: string; segments: number }[] }>('/spec/rebase/status'),
  conflict: (path: string) =>
    request<{ ok: boolean; path: string; segments: { ours: string; theirs: string }[] }>(`/spec/rebase/conflict?path=${encodeURIComponent(path)}`),
  resolve: (path: string, resolution: 'ours' | 'theirs' | 'smart' | 'custom', mergedContent = '') =>
    request<{ ok: boolean; path: string; resolution: string; remaining: string[] }>('/spec/rebase/resolve', {
      method: 'POST', body: JSON.stringify({ path, resolution, merged_content: mergedContent }),
    }),
  abort: () =>
    request<{ ok: boolean; note?: string }>('/spec/rebase/abort', { method: 'POST' }),
  continue: () =>
    request<{ ok: boolean; note?: string; output?: string }>('/spec/rebase/continue', { method: 'POST' }),
};

