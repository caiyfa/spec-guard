/** SpecGuard Workbench API 客户端 */

const BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── 场景管理 ──
export interface Scenario {
  id: string;
  title: string;
  version: string;
  priority: string;
  tags: string[];
  depends_on: { id: string; mode: string; version?: string | null; optional?: boolean }[];
  produces: { resource: string; state: string }[];
  has_teardown: boolean;
  category: 'producer' | 'modifier' | 'query' | 'validator';
  covers: string[];
  module: string;
  path: string;
}

export interface DagEdge {
  id: string; source: string; target: string; animated: boolean; label: string;
  status?: 'match' | 'minor_drift' | 'major_drift' | 'orphan';
  expected?: string | null;
  actual?: string | null;
}

export interface DagData {
  nodes: { id: string; data: Record<string, unknown> }[];
  edges: DagEdge[];
}

export interface DriftItem {
  consumer: string; id: string; expected: string | null;
  actual: string | null; status: string; optional: boolean;
}

export const scenariosApi = {
  list: () => request<Scenario[]>('/scenarios'),
  dag: () => request<DagData>('/scenarios/dag'),
  validate: () => request<{ ok: boolean; cycles: string[][] }>('/scenarios/validate'),
  drift: () => request<{ items: DriftItem[]; orphans: Record<string, string[]> }>('/scenarios/drift'),
  get: (id: string) => request<{ id: string; content: string }>(`/scenarios/${id}`),
  save: (id: string, content: string) =>
    request<{ ok: boolean }>(`/scenarios/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  editDep: (id: string, body: { action: 'add' | 'remove'; dep_id: string; mode?: 'shared' | 'exclusive' }) =>
    request<{ ok: boolean }>(`/scenarios/${id}/deps`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
};

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

export const runsApi = {
  trigger: (scope: string, target = '', env = 'sit', breakpoints: string[] = []) =>
    request<{ ok: boolean; run_id: string }>('/runs/trigger', {
      method: 'POST',
      body: JSON.stringify({ scope, target, env, breakpoints }),
    }),
  abort: () => request<{ ok: boolean }>('/runs/abort', { method: 'POST' }),
  resume: () => request<{ ok: boolean }>('/runs/resume', { method: 'POST' }),
  status: () => request<RunStatus>('/runs/status'),
  history: (limit = 20) => request<RunSummary[]>(`/runs/history?limit=${limit}`),
  get: (runId: string) => request<Record<string, unknown>>(`/runs/${runId}`),
};

// ── 测试计划 ──
export interface ImportPreviewFile {
  path: string; module: string; test_type: string;
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
    total_files: number; unit_count: number; scenario_count: number;
    valid_count: number; error_count: number;
    total_frs: number; matched_scenarios: number;
  };
}
export interface RunStatus {
  status: string; run_id: string; plan_id: string;
  is_running: boolean; is_paused: boolean;
  paused_at: string; breakpoints: string[];
  completed_scenarios: string[]; pending_scenarios: string[];
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
  workingCopies: (planId: string) =>
    request<{ filename: string; source: string; size: number }[]>(`/plans/${planId}/working-copies`),
  history: (id: string, limit = 20) =>
    request<RunSummary[]>(`/plans/${id}/history?limit=${limit}`),
};

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
};

// ── 参考信息（编辑器快速引用） ──
export interface StepRef { type: string; desc: string; snippet: string; params: { name: string; required: boolean; desc: string }[] }
export interface OracleRef { name: string; desc: string; snippet: string }
export interface EmpRole { name: string; description: string; candidate_count: number; has_check: boolean }
export interface EnvVar { path: string; desc: string; example: string }
export interface UpstreamVar { scenario_id: string; title: string; saves: string[]; usage: string[] }
export interface ScenarioDetail {
  id: string;
  title: string;
  given: string;
  saves: { name: string; step_type: string }[];
  produces: { resource: string; state: string }[];
}

export const referenceApi = {
  steps: () => request<StepRef[]>('/reference/steps'),
  oracles: () => request<OracleRef[]>('/reference/oracles'),
  empRoles: () => request<EmpRole[]>('/reference/emp-roles'),
  envVars: () => request<EnvVar[]>('/reference/env-vars'),
  upstreamVars: (id: string) => request<UpstreamVar[]>(`/reference/upstream-vars/${id}`),
  scenarioDetail: (id: string) => request<ScenarioDetail>(`/reference/scenario-detail/${id}`),
  yamlFormatSpec: () => request<Record<string, unknown>>('/reference/yaml-format-spec'),
  yamlFormatSpecMd: () => request<{ content: string }>('/reference/yaml-format-spec-md'),
  nextId: (prefix: string, type: string) =>
    request<{ next_id: string; next_num: number; existing: string[]; total: number }>(
      `/reference/next-id?prefix=${prefix}&type=${type}`),
  validateId: (id: string) =>
    request<{ id: string; unique: boolean; conflicts: string[] }>(`/reference/validate-id/${id}`),
  envConfig: () => request<{ raw: string; parsed: Record<string, unknown> }>('/reference/env-config'),
  saveEnvConfig: (raw: string) =>
    request<{ ok: boolean }>('/reference/env-config', {
      method: 'PUT',
      body: JSON.stringify({ raw }),
    }),
  testDb: () => request<{ ok: boolean; message?: string; error?: string }>('/reference/test-db', { method: 'POST' }),
};
