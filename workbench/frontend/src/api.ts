/** SpecGuard Workbench API 客户端（多用户：token + 工作区注入） */

const BASE = '/api';

// ── 会话状态（token 存 sessionStorage，工作区选择存 localStorage）──
export const WORKSPACE_CHANGED_EVENT = 'sg-workspace-changed';

export const session = {
  getToken: () => sessionStorage.getItem('sg_token') || '',
  setToken: (t: string) => sessionStorage.setItem('sg_token', t),
  clearToken: () => sessionStorage.removeItem('sg_token'),
  getWorkspace: () => localStorage.getItem('sg_workspace') || '',
  setWorkspace: (w: string) => {
    localStorage.setItem('sg_workspace', w);
    // K-009：广播切换事件，已挂载页面（如工作区中心）可监听并自动重载
    window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGED_EVENT, { detail: w }));
  },
};

/** 401 统一处理：清 token 并强制回登录页 */
function handleUnauthorized() {
  session.clearToken();
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login';
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = session.getToken();
  const ws = session.getWorkspace();
  // 坏 token 预检：HTTP header 仅支持 ASCII，非 ASCII token（如中文工号签发的 mock-token）
  // 会让 fetch 直接抛 TypeError。此处等同 401 处理：清 token 跳登录页，用户可自助恢复。
  if (token && !/^[\x20-\x7E]+$/.test(token)) {
    handleUnauthorized();
    throw new Error('会话 token 非法，请重新登录');
  }
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (ws) headers['X-SG-Workspace'] = ws;
  const res = await fetch(`${BASE}${path}`, { headers, ...options });
  if (res.status === 401) {
    handleUnauthorized();
    throw new Error('未登录或登录已过期');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const d: unknown = err.detail;
    // detail 可能是字符串或结构化对象（如 422 的 {message, findings}）
    const msg = typeof d === 'string' ? d
      : (d && typeof d === 'object' && 'message' in d ? String((d as any).message) : JSON.stringify(d));
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── 文件上传（FormData：Content-Type 由浏览器带 boundary，不能预设 JSON）──
export async function uploadFile<T>(path: string, file: File): Promise<T> {
  return uploadFiles<T>(path, [file]);
}

// 多文件上传（字段名 files，可附表单字段 fields）
export async function uploadFiles<T>(path: string, files: File[], fields?: Record<string, string>): Promise<T> {
  const token = session.getToken();
  const ws = session.getWorkspace();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (ws) headers['X-SG-Workspace'] = ws;
  const fd = new FormData();
  for (const f of files) fd.append(files.length > 1 ? 'files' : 'file', f);
  if (fields) for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  const res = await fetch(`${BASE}${path}`, { method: 'POST', headers, body: fd });
  if (res.status === 401) {
    handleUnauthorized();
    throw new Error('未登录或登录已过期');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(String(err.detail || `HTTP ${res.status}`));
  }
  return res.json();
}

// ── 认证 ──
export interface CurrentUser {
  emp_no: string;
  name: string;
  role: 'admin' | 'tester' | 'viewer';
  default_workspace: string;
  auth_mode: 'uac' | 'mock';
}

export const authApi = {
  config: () => request<{ auth_mode: string; uac_base: string; uac_logout_url: string }>('/auth/config'),
  me: () => request<CurrentUser>('/auth/me'),
  mockLogin: (emp_no: string, name = '') =>
    request<{ ok: boolean; token: string; user: any }>('/auth/mock-login', {
      method: 'POST',
      body: JSON.stringify({ emp_no, name }),
    }),
  logout: () => request<{ ok: boolean; uac_logout_url: string }>('/auth/logout', { method: 'POST' }),
};

// ── 用户与授权管理（admin）──
export interface UserItem {
  emp_no: string;
  name: string;
  role: string;
  default_workspace: string;
  created_at: string;
  last_login_at: string;
}

export interface GrantItem {
  id: number;
  workspace_name: string;
  emp_no: string;
  granted_by: string;
  created_at: string;
}

export const usersApi = {
  list: () => request<{ users: UserItem[] }>('/users'),
  setRole: (emp_no: string, role: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    }),
  grants: () => request<{ grants: GrantItem[] }>('/users/grants'),
  grant: (emp_no: string, workspace_name: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/grants`, {
      method: 'POST',
      body: JSON.stringify({ workspace_name }),
    }),
  revoke: (emp_no: string, workspace_name: string) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/grants/${encodeURIComponent(workspace_name)}`, {
      method: 'DELETE',
    }),
  setDefaultWorkspace: (workspace_name: string) =>
    request<{ ok: boolean; default_workspace: string }>('/users/me/default-workspace', {
      method: 'PUT',
      body: JSON.stringify({ workspace_name }),
    }),
  auditLog: (limit = 100) => request<{ entries: any[] }>(`/users/audit-log?limit=${limit}`),
};

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
    request<{ ok: boolean; run_id?: string; queued?: boolean; queue_id?: number; position?: number }>('/runs/trigger', {
      method: 'POST',
      body: JSON.stringify({ scope, target, env, breakpoints }),
    }),
  abort: () => request<{ ok: boolean }>('/runs/abort', { method: 'POST' }),
  resume: () => request<{ ok: boolean }>('/runs/resume', { method: 'POST' }),
  status: () => request<RunStatus>('/runs/status'),
  cancelQueued: (itemId: number) =>
    request<{ ok: boolean }>(`/runs/queue/${itemId}`, { method: 'DELETE' }),
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
export interface RunQueueItem {
  id: number; emp_no: string; scope: string; target: string;
  env: string; plan_id: string; workspace: string;
  status: 'queued' | 'running';
  created_at: string; started_at: string;
}

export interface RunStatus {
  status: string; run_id: string; plan_id: string;
  is_running: boolean; is_paused: boolean;
  paused_at: string; breakpoints: string[];
  completed_scenarios: string[]; pending_scenarios: string[];
  current_emp_no?: string; current_workspace?: string;
  queue?: RunQueueItem[];
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

// ── 工作区管理 ──
export interface WorkspaceInfo {
  name: string;
  system: string;
  source: { type: string; path?: string; url?: string; branch?: string; local_path?: string };
  last_commit: string;
}

export const workspaceApi = {
  list: () => request<{ workspaces: WorkspaceInfo[]; active: string; my_default?: string }>('/workspace/list'),
  getActive: () => request<{ active: WorkspaceInfo | null }>('/workspace/active'),
  registerLocal: (body: { name: string; path: string; system: string; activate?: boolean }) =>
    request<any>('/workspace/register-local', { method: 'POST', body: JSON.stringify(body) }),
  registerGit: (body: { name: string; url: string; system: string; branch?: string }) =>
    request<any>('/workspace/register-git', { method: 'POST', body: JSON.stringify(body) }),
  activate: (name: string) =>
    request<{ ok: boolean; active: string }>('/workspace/activate', { method: 'POST', body: JSON.stringify({ name }) }),
  unregister: (name: string) =>
    request<{ ok: boolean }>(`/workspace/${name}`, { method: 'DELETE' }),
  conformance: (name?: string) =>
    request<any>('/workspace/conformance', { method: 'POST', body: JSON.stringify({ name: name || '' }) }),
  pull: (name: string) =>
    request<{ ok: boolean; old_commit?: string; new_commit?: string; changed?: boolean; report?: any; error?: string }>(
      '/workspace/pull', { method: 'POST', body: JSON.stringify({ name }) }),
  specFiles: (subdir?: string) =>
    request<{ files: any[]; workspace: string }>(`/workspace/spec-files${subdir ? `?subdir=${subdir}` : ''}`),
  readFile: (path: string) =>
    request<{ path: string; content: string; format?: 'raw' | 'markdown' | 'text' }>(`/workspace/read-file?path=${encodeURIComponent(path)}`),
  // K-036：原始字节（base64）——办公文档保真预览（SheetJS/mammoth/pdf blob）需要原文件
  readFileRaw: (path: string) =>
    request<{ path: string; raw_base64: string; format: string }>(`/workspace/read-file?path=${encodeURIComponent(path)}&raw=true`),
  fileHash: (path: string) =>
    request<{ path: string; sha: string }>(`/workspace/file-hash?path=${encodeURIComponent(path)}`),
  search: (q: string) =>
    request<{ results: { path: string; match_type: string; line?: number; preview: string; size: number }[]; query: string }>(`/workspace/search?q=${encodeURIComponent(q)}`),
};

// ── Agent 对话 ──
export interface AgentMode {
  name: string;
  tools: string[];
  description: string;
  prompt_fragment: string;
}

export interface AgentSkill {
  name: string;
  description: string;
  trigger: string;
  content: string;
}

export const agentApi = {
  listSessions: (workspace = '') =>
    request<{ sessions: any[] }>(`/agent/sessions${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  getSession: (id: string, workspace = '') =>
    request<{ session_id: string; messages: any[] }>(`/agent/sessions/${id}${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  exportSession: (id: string, workspace = '') =>
    request<any>(`/agent/sessions/${id}/export${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  chat: (body: { message: string; session_id?: string; max_turns?: number; workspace?: string; mode?: string; scenario_id?: string }) =>
    request<any>('/agent/chat', { method: 'POST', body: JSON.stringify(body) }),
  getModes: () =>
    request<{ modes: AgentMode[] }>('/agent/modes'),
  getSkills: () =>
    request<{ skills: AgentSkill[] }>('/agent/skills'),
};

// ── LLM 配置（G1-1）──
export interface LLMConfig {
  base_url: string;
  api_key: string;
  model: string;
  timeout: string;
  temperature: string;
  // 模型能力限制
  max_context_tokens: string;
  max_output_tokens: string;
  // 思考/推理选项
  thinking_enabled: string;
  reasoning_effort: string;
}

export const settingsApi = {
  getLLMConfig: () =>
    request<{ config: LLMConfig; db_config: Record<string, string>; env_controlled: Record<string, boolean> }>('/settings/llm-config'),
  saveLLMConfig: (config: LLMConfig) =>
    request<{ ok: boolean; config: LLMConfig; db_config: Record<string, string>; probe: { ok: boolean; message: string } | null }>('/settings/llm-config', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  probeLLM: (body: { base_url: string; api_key: string; model: string; timeout?: number }) =>
    request<{ ok: boolean; message: string }>('/settings/llm-config/probe', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  // K-007: spec 签名基线自动更新开关
  getAuditBaseline: () =>
    request<{ auto_update: boolean }>('/settings/audit-baseline'),
  setAuditBaseline: (autoUpdate: boolean) =>
    request<{ ok: boolean; auto_update: boolean }>('/settings/audit-baseline', {
      method: 'POST',
      body: JSON.stringify({ auto_update: autoUpdate }),
    }),
};

// ── 多模型配置 ──
export interface ModelConfig {
  id: string;
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  timeout: string;
  temperature: string;
  max_context_tokens: string;
  max_output_tokens: string;
  thinking_enabled: string;
  reasoning_effort: string;
  is_default: boolean;
  created_at?: string;
  updated_at?: string;
}

export const modelApi = {
  list: () => request<{ models: ModelConfig[] }>('/settings/models'),
  create: (data: Omit<ModelConfig, 'id' | 'is_default' | 'created_at' | 'updated_at'>) =>
    request<ModelConfig>('/settings/models', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Omit<ModelConfig, 'id' | 'is_default' | 'created_at' | 'updated_at'>) =>
    request<ModelConfig>(`/settings/models/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  delete: (id: string) => request<{ ok: boolean }>(`/settings/models/${id}`, { method: 'DELETE' }),
  setDefault: (id: string) => request<ModelConfig>(`/settings/models/${id}/default`, { method: 'POST' }),
  probe: (id: string, data?: { base_url?: string; api_key?: string; model?: string }) =>
    request<{ ok: boolean; message: string }>(`/settings/models/${id}/probe`, { method: 'POST', body: JSON.stringify(data || {}) }),
};

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

export const draftsApi = {
  list: () => request<{ drafts: DraftItem[] }>('/drafts'),
  modules: () => request<{ modules: string[] }>('/drafts/modules'),
  read: (filename: string) =>
    request<{ filename: string; content: string }>(`/drafts/${encodeURIComponent(filename)}`),
  validate: (filename: string) =>
    request<ValidateReport>(`/drafts/${encodeURIComponent(filename)}/validate`, { method: 'POST' }),
  promote: (filename: string, module: string) =>
    request<any>(`/drafts/${encodeURIComponent(filename)}/promote`, {
      method: 'POST',
      body: JSON.stringify({ module }),
    }),
  discard: (filename: string) =>
    request<{ ok: boolean; trashed_to: string }>(`/drafts/${encodeURIComponent(filename)}/discard`, { method: 'POST' }),
};

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

// ── 定时任务调度（I-2/I-3）──
export interface ScheduledJob {
  id: string;
  name: string;
  plan_id: string;
  workspace: string;
  cron: string;
  notify_config_id: string;
  enabled: boolean;
  created_by: string;
  created_at: string;
  last_run_at: string;
  last_run_status: string;
  last_run_id: string;
}

export const schedulesApi = {
  list: () =>
    request<{ jobs: ScheduledJob[] }>('/schedules'),
  create: (body: { name: string; plan_id: string; cron: string; notify_config_id?: string; enabled?: boolean }) =>
    request<ScheduledJob>('/schedules', { method: 'POST', body: JSON.stringify(body) }),
  get: (id: string) =>
    request<ScheduledJob>(`/schedules/${encodeURIComponent(id)}`),
  update: (id: string, body: { name?: string; plan_id?: string; cron?: string; notify_config_id?: string; enabled?: boolean }) =>
    request<ScheduledJob>(`/schedules/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/schedules/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  run: (id: string) =>
    request<{ run_id: string; status: string; results: any[] }>(`/schedules/${encodeURIComponent(id)}/run`, { method: 'POST' }),
  listPlans: () =>
    request<{ plans: { id: string; name: string; scenario_count: number }[] }>('/schedules/plans/list'),
};

// ── 通知配置（J-3）──
export interface NotifyConfig {
  id: string;
  name: string;
  channel: string;  // dingtalk / feishu
  webhook_url: string;  // 脱敏
  secret: string;  // 脱敏
  mention_mobiles: string;
  events: string[];
  enabled: boolean;
  created_by: string;
  created_at: string;
}

export const notifyApi = {
  list: () =>
    request<{ configs: NotifyConfig[] }>('/notify/configs'),
  create: (body: { name: string; channel: string; webhook_url: string; secret?: string; mention_mobiles?: string; events?: string[]; enabled?: boolean }) =>
    request<NotifyConfig>('/notify/configs', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: string, body: { name: string; channel: string; webhook_url: string; secret?: string; mention_mobiles?: string; events?: string[]; enabled?: boolean }) =>
    request<NotifyConfig>(`/notify/configs/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/notify/configs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  test: (id: string, event?: string) =>
    request<{ ok: boolean; message: string }>(`/notify/configs/${encodeURIComponent(id)}/test`, { method: 'POST', body: JSON.stringify({ event: event || 'plan_failure' }) }),
};
