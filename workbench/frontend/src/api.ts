/** SpecGuard Workbench API 客户端（多用户：token + 工作区注入） */

const BASE = '/api';

// ── 会话状态（token 存 localStorage，工作区选择存 localStorage）──
export const WORKSPACE_CHANGED_EVENT = 'sg-workspace-changed';

export const session = {
  getToken: () => localStorage.getItem('sg_token') || '',
  setToken: (t: string) => localStorage.setItem('sg_token', t),
  clearToken: () => localStorage.removeItem('sg_token'),
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

// X-SG-Workspace 值编码：HTTP header 仅允许 ISO-8859-1 字节，中文等工作区名必须
// encodeURIComponent 编码后才能入 header（后端 unquote 对称还原），否则 fetch 直接
// 抛 "String contains non-ISO-8859-1 code point"。无条件编码保证与后端解码无歧义。
export const encodeWorkspaceHeader = (ws: string): string => encodeURIComponent(ws);

// 鉴权请求包装器（带 token + 工作区头；页面内直用，替代裸 fetch）
export const apiRequest = request;

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
  if (ws) headers['X-SG-Workspace'] = encodeWorkspaceHeader(ws);
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
  if (ws) headers['X-SG-Workspace'] = encodeWorkspaceHeader(ws);
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
  role: 'admin' | 'tester' | 'viewer' | 'product';
  roles?: string[];  // v1.8 多角色集（RBAC：菜单授权按角色集并集）
  default_workspace: string;
  auth_mode: 'uac' | 'mock';
}

export const authApi = {
  config: () => request<{ auth_mode: string; uac_base: string; sso_base: string; sso_app_id: string; uac_logout_url: string }>('/auth/config'),
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
  roles: string[];  // v1.8 多角色集
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
  setRoles: (emp_no: string, roles: string[]) =>
    request<{ ok: boolean }>(`/users/${encodeURIComponent(emp_no)}/role`, {
      method: 'PUT',
      body: JSON.stringify({ roles }),
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

// ── 菜单 / 角色 RBAC ──
export interface NavMenuItem {
  to: string;
  label: string;
  end?: boolean;
}
export interface NavGroup {
  label: string;
  icon: string;
  items: NavMenuItem[];
}
export interface MenuRecord {
  menu_key: string;
  label: string;
  icon: string;
  path: string;
  parent_key: string;
  sort: number;
  visible: boolean;
  is_system: boolean;
  is_public: boolean;  // 公开菜单：登录即用，无需授权（首页对话）
}
export interface RoleRecord {
  role_key: string;
  label: string;
  is_builtin: boolean;
  sort: number;
}

export const menusApi = {
  me: () => request<{ groups: NavGroup[] }>('/menus/me'),
  list: () => request<{ menus: MenuRecord[] }>('/menus'),
  create: (body: Partial<MenuRecord>) =>
    request<{ ok: boolean }>('/menus', { method: 'POST', body: JSON.stringify(body) }),
  update: (menu_key: string, body: Partial<MenuRecord>) =>
    request<{ ok: boolean }>(`/menus/${encodeURIComponent(menu_key)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  remove: (menu_key: string) =>
    request<{ ok: boolean }>(`/menus/${encodeURIComponent(menu_key)}`, { method: 'DELETE' }),
};

export const rolesApi = {
  list: () => request<{ roles: RoleRecord[] }>('/roles'),
  create: (role_key: string, label: string, sort = 0) =>
    request<{ ok: boolean }>('/roles', {
      method: 'POST',
      body: JSON.stringify({ role_key, label, sort }),
    }),
  update: (role_key: string, label: string, sort = 0) =>
    request<{ ok: boolean }>(`/roles/${encodeURIComponent(role_key)}`, {
      method: 'PUT',
      body: JSON.stringify({ label, sort }),
    }),
  remove: (role_key: string) =>
    request<{ ok: boolean }>(`/roles/${encodeURIComponent(role_key)}`, { method: 'DELETE' }),
  getMenus: (role_key: string) =>
    request<{ menu_keys: string[] }>(`/roles/${encodeURIComponent(role_key)}/menus`),
  setMenus: (role_key: string, menu_keys: string[]) =>
    request<{ ok: boolean }>(`/roles/${encodeURIComponent(role_key)}/menus`, {
      method: 'PUT',
      body: JSON.stringify({ menu_keys }),
    }),
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
  updated_at?: string;  // T-320：场景最后更新时间（YAML mtime，'YYYY-MM-DD HH:MM'）
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
  drift: () => request<{ items: DriftItem[]; orphans: Record<string, string[]>; cycles: string[][] }>('/scenarios/drift'),
  get: (id: string) => request<{ id: string; content: string }>(`/scenarios/${id}`),
  save: (id: string, content: string) =>
    request<{ ok: boolean }>(`/scenarios/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  editDep: (id: string, body: { action: 'add' | 'remove'; dep_id: string; mode?: 'shared' | 'exclusive'; note?: string }) =>
    request<{ ok: boolean }>(`/scenarios/${id}/deps`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  suggestDeps: (id: string) =>
    request<DepSuggestResult>(`/scenarios/${encodeURIComponent(id)}/suggest-deps`),
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

// ── 测试计划 ──
export interface ImportPreviewFile {
  path: string; module: string;
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
    total_files: number;
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
  yamlFormatSpecMd: () => request<{ content: string }>('/reference/yaml-format-spec-md'),
  // T-306/T-309：环境配置独立菜单——环境列表（全系统 + 共享通用层）+ 按系统/环境/配置层读写
  envs: () =>
    request<{ system: string; envs: EnvEntry[]; shared_envs: EnvEntry[]; current: string; systems: SystemInfo[] }>('/reference/envs'),
  envConfig: (env = 'sit', scope: 'system' | 'shared' = 'system', system = 'tdm') =>
    request<{ raw: string; parsed: Record<string, unknown>; env: string; scope: string; system: string; exists: boolean }>(
      `/reference/env-config?env=${encodeURIComponent(env)}&scope=${scope}&system=${encodeURIComponent(system)}`),
  saveEnvConfig: (raw: string, env = 'sit', scope: 'system' | 'shared' = 'system', system = 'tdm') =>
    request<{ ok: boolean; env: string; scope: string; system: string }>(`/reference/env-config?env=${encodeURIComponent(env)}&scope=${scope}&system=${encodeURIComponent(system)}`, {
      method: 'PUT',
      body: JSON.stringify({ raw }),
    }),
  testDb: (env = 'sit', system = 'tdm') =>
    request<{ ok: boolean; message?: string; error?: string }>(`/reference/test-db?env=${encodeURIComponent(env)}&system=${encodeURIComponent(system)}`, { method: 'POST' }),
};

// ── 工作区管理 ──
export interface EnvEntry {
  name: string;
  path: string;
}

export interface WorkspaceInfo {
  name: string;
  system: string;
  source: { type: string; path?: string; url?: string; branch?: string; local_path?: string };
  last_commit: string;
}

export interface SystemInfo {
  name: string;
  envs: string[];
  default_env: string;
  accounts: string[];
}

export const workspaceApi = {
  list: () => request<{ workspaces: WorkspaceInfo[]; active: string; my_default?: string }>('/workspace/list'),
  systems: () => request<{ systems: SystemInfo[] }>('/workspace/systems'),
  registerLocal: (body: { name: string; path: string; system: string; activate?: boolean }) =>
    request<any>('/workspace/register-local', { method: 'POST', body: JSON.stringify(body) }),
  registerGit: (body: { name: string; url: string; system: string; branch?: string; clone_dir?: string }) =>
    request<any>('/workspace/register-git', { method: 'POST', body: JSON.stringify(body) }),
  browseDir: (path: string) =>
    request<{ ok: boolean; current: string; parent: string | null; entries: { name: string; path: string }[]; error?: string }>(
      `/workspace/browse-dir?path=${encodeURIComponent(path)}`),
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
  gitLog: (limit = 100) =>
    request<GitLogResponse>(`/workspace/git-log?limit=${limit}`),
};

// ── git log（SourceTree 风格提交历史页）──
export interface GitFileChange {
  status: string; // A|M|D|R
  path: string;
}

export interface GitCommit {
  sha: string;
  short_sha: string;
  author: string;
  email: string;
  date: string;
  parents: string[];
  message: string;
  files: GitFileChange[];
}

export interface GitLogResponse {
  ok: boolean;
  workspace: string;
  branch: string;
  url?: string;
  commits: GitCommit[];
  local_head: string;
  remote_known: boolean;
  remote_head: string;
  synced: boolean;
  error?: string;
  ahead?: number;      // 相对上游分支领先提交数（待推送）
  behind?: number;     // 相对上游分支落后提交数（待拉取）
  unpushed?: GitCommit[];  // 未推送提交列表（@{u}..HEAD，分叉状态下可靠）
  rebase_in_progress?: boolean;  // rebase 中断中（冲突未解决，推送被拦截）
}

// ── Agent 对话 ──
export const agentApi = {
  // T-012: 当前用户可见用途清单（角色集合并集过滤）
  listPurposes: () =>
    request<{ purposes: { id: string; title: string; icon: string; color: string; chips: string[]; description: string; panels: string[] }[] }>('/agent/purposes'),
  // T-010: 创建会话（唯一可写 purpose 的入口，purpose 创建即锁定）
  createSession: (body: { purpose: string; workspace?: string; title?: string }) =>
    request<{ ok: boolean; session_id: string; session: any }>('/agent/sessions', { method: 'POST', body: JSON.stringify(body) }),
  // T-010: 改标题/归档；请求体含 purpose 一律 409
  patchSession: (id: string, body: { title?: string; archived?: boolean }, workspace = '') =>
    request<{ ok: boolean; session_id: string }>(`/agent/sessions/${id}${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`, { method: 'PATCH', body: JSON.stringify(body) }),
  listSessions: (workspace = '', purpose = '', includeArchived = false) =>
    request<{ sessions: any[] }>(`/agent/sessions${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}${purpose ? `${workspace ? '&' : '?'}purpose=${encodeURIComponent(purpose)}` : ''}${includeArchived ? `${workspace || purpose ? '&' : '?'}include_archived=1` : ''}`),
  // T-010 扩展：批量归档/恢复（只处理本人会话）
  batchArchive: (ids: string[], archived: boolean, workspace = '') =>
    request<{ ok: boolean; processed: number; skipped: string[]; archived: boolean }>(`/agent/sessions/batch-archive${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`, { method: 'POST', body: JSON.stringify({ session_ids: ids, archived }) }),
  getSession: (id: string, workspace = '') =>
    request<{ session_id: string; messages: any[]; reading_feed?: any[]; writing_feed?: any[] }>(`/agent/sessions/${id}${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  exportSession: (id: string, workspace = '') =>
    request<any>(`/agent/sessions/${id}/export${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  // T-402: 取消会话当前运行（真打断）
  cancelSession: (sessionId: string) =>
    request<{ ok: boolean; session_id: string; message: string }>(`/agent/cancel/${sessionId}`, { method: 'POST' }),
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
  // K-007: spec 签名基线自动更新开关
  getAuditBaseline: () =>
    request<{ auto_update: boolean }>('/settings/audit-baseline'),
  // T-204: 执行看门狗超时（秒，0=禁用）
  getRunTimeout: () =>
    request<{ timeout_sec: number; source: string }>('/settings/run-timeout'),
  setRunTimeout: (timeoutSec: number) =>
    request<{ ok: boolean; timeout_sec: number }>('/settings/run-timeout', {
      method: 'POST',
      body: JSON.stringify({ timeout_sec: timeoutSec }),
    }),
  setAuditBaseline: (autoUpdate: boolean) =>
    request<{ ok: boolean; auto_update: boolean }>('/settings/audit-baseline', {
      method: 'POST',
      body: JSON.stringify({ auto_update: autoUpdate }),
    }),
  // S0.6: git 配置（多用户隔离，token 加密存储）
  getGitConfig: () =>
    request<{ name: string; email: string; has_token: boolean }>('/settings/git-config'),
  saveGitConfig: (body: { name: string; email: string; token: string }) =>
    request<{ ok: boolean; has_token: boolean }>('/settings/git-config', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
};

// ── 多模型配置 ──
export interface ModelConfig {
  id: string;
  name: string;
  base_url: string;
  api_key: string; // 列表接口返回脱敏值；has_api_key 表示是否已配置
  has_api_key?: boolean;
  model: string;
  timeout: string;
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
export interface CoverageGaps {
  module: string;
  fr_total: number;
  lanes: {
    gap: CoverageLaneItem[];
    draft: CoverageLaneItem[];
    covered: CoverageLaneItem[];
  };
  suggested_order: string[];
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

// ── K-xxx：单元测试生命周期监控（台账聚合） ──
export interface LifecycleItem {
  id: string;
  title: string;
  status: 'in_library' | 'draft_pending' | 'draft_updating' | 'discarded' | 'unknown';
  status_label: string;
  draft_status: string;
  draft_filename: string;
  module: string;
  version: string;
  tags: string[];
  covers: string[];
  file_path: string;
  updated_at: string;
  run_count: number;
  fail_count: number;
  last_run_id: string;
  last_verdict: string;
  last_run_at: string;
  recent_verdicts: string[];
  closed_loops: number;
  last_failure: { category: string; message: string; run_id: string; at: string } | null;
}

export interface LifecycleSummary {
  total: number;
  in_library: number;
  draft_pending: number;
  draft_updating: number;
  discarded: number;
  recent_failed_7d: number;
  closed_loops: number;
}

export interface LifecycleTimelineEvent {
  at: string;
  type: string;
  label: string;
  verdict?: string;
  detail?: string;
  run_id?: string;
}

export interface LifecycleDetail {
  id: string;
  title: string;
  module: string;
  version: string;
  file_path: string;
  status: string;
  status_label: string;
  draft_status: string;
  draft_filename: string;
  timeline: LifecycleTimelineEvent[];
  runs: { run_id: string; scenario_id: string; verdict: string; duration_ms: number; category: string; message: string; finished_at: string }[];
}

export const lifecycleApi = {
  list: () => request<{ summary: LifecycleSummary; items: LifecycleItem[] }>('/lifecycle/scenarios'),
  detail: (id: string) =>
    request<LifecycleDetail>(`/lifecycle/scenarios/${encodeURIComponent(id)}`),
};

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

// ══════════════════════════════════════════════════════════
// P-A 图谱（T-070/T-071，M11 §5.1）
// ══════════════════════════════════════════════════════════

export interface GraphStatus {
  fingerprint: string;
  source_fingerprint: string;
  stale: boolean;
  built_at: string | null;
}

export interface GraphNodeRef {
  file: string;
  line_range: number[];
}

export interface GraphNode {
  id: string;
  node_type: string;
  stage: string;
  title: string;
  module: string;
  feature: string;
  attrs: Record<string, any>;
  source_ref?: GraphNodeRef | null;
}

export interface GraphL0 {
  l0mods: Record<string, { name: string; fr_count: number; counts: number[] }>;
  l0edges: { a: string; b: string; w: number }[];
  lens?: string;
  era?: string;
}

export interface GraphL1Item {
  health: number | null;
  counts: number[];
  era: number;
  nCov: number;
  nGap: number;
}

export interface GraphL2Fr {
  id: string;
  t: string;
  era: number;
  modAt: string | null;
  goneAt: string | null;
  cov: 'ok' | 'gap';
  source_ref?: GraphNodeRef | null;
}

export interface GraphL2Scenario {
  id: string;
  title: string;
  covers: string[];
  source_ref?: GraphNodeRef | null;
}

export interface GraphL2 {
  frs: GraphL2Fr[];
  frEdges: string[][];
  scenarios: GraphL2Scenario[];
  era?: string;
}

export interface GraphBacklink {
  covered_by: string[];
  modified_by: string[];
  decided_by: string[];
  referenced_by: string[];
}

export interface GraphSourceFile {
  path: string;
  content: string;
  format: string;
  line: number;
  total_lines: number;
}

export interface GraphSnapshot {
  snapshot_id: string;
  label: string;
  trigger: string;
  created_at: string;
  source_fingerprint: string;
  nodes: number;
  edges: number;
}

export interface GraphDiff {
  from: string;
  to: string;
  added: number;
  removed: number;
  modified: number;
  edge_added: number;
  edge_removed: number;
  per_module: Record<string, { added: number; removed: number; modified: number }>;
  fingerprint_from: string;
  fingerprint_to: string;
  added_ids: string[];
  removed_ids: string[];
  modified_ids: string[];
}

export const graphApi = {
  status: () => request<GraphStatus>('/graph/status'),
  panoramaL0: (lens = 'map') => request<GraphL0>(`/graph/panorama?level=L0&lens=${lens}`),
  panoramaL1: (module: string, lens = 'map') =>
    request<Record<string, GraphL1Item>>(`/graph/panorama/${encodeURIComponent(module)}?lens=${lens}`),
  panoramaL2: (module: string, feature: string) =>
    request<GraphL2>(`/graph/panorama/${encodeURIComponent(module)}/${encodeURIComponent(feature)}`),
  backlink: (nodeId: string) =>
    request<{ node: GraphNode; backlink: GraphBacklink }>(`/graph/backlink/${encodeURIComponent(nodeId)}`),
  focus: (nodeId: string, depth = 2) =>
    request<FocusGraphResp>(`/graph/focus?node_id=${encodeURIComponent(nodeId)}&depth=${depth}`),
  network: () =>
    request<NetworkViewResp>('/graph/panorama?level=L0&lens=network'),
  rebuild: () => request<{ nodes: number; edges: number; source_fingerprint: string; built_at: string }>('/graph/rebuild', { method: 'POST' }),
  source: (file: string, line = 0) =>
    request<GraphSourceFile>(`/graph/source?file=${encodeURIComponent(file)}&line=${line}`),
  listSnapshots: () => request<{ snapshots: GraphSnapshot[] }>('/graph/snapshots'),
  createSnapshot: (label = '', trigger = 'manual') =>
    request<{ snapshot_id: string; nodes: number; edges: number; source_fingerprint: string }>(
      `/graph/snapshots?label=${encodeURIComponent(label)}&trigger=${encodeURIComponent(trigger)}`,
      { method: 'POST' }),
  diff: (fromSnapshot: string, toSnapshot = 'current') =>
    request<GraphDiff>(`/graph/diff?from_snapshot=${encodeURIComponent(fromSnapshot)}&to_snapshot=${encodeURIComponent(toSnapshot)}`),
};

// ══════════════════════════════════════════════════════════
// 血缘链（T-073，M10 §5.1）
// ══════════════════════════════════════════════════════════

export interface LineageNode {
  id: string;
  type: string;
  stage: string;
  title: string;
  status: string;
  external: boolean;
  url: string;
}

export interface LineageEdge {
  from: string;
  to: string;
  type: string;
}

export interface LineageTrace {
  path: LineageNode[];
  edges: LineageEdge[];
  truncated: boolean;
  root: string;
  direction: string;
}

export const lineageApi = {
  trace: (node: string, dir: 'up' | 'down' | 'both' = 'up', maxDepth = 8) =>
    request<LineageTrace>(`/lineage/trace?node=${encodeURIComponent(node)}&dir=${dir}&max_depth=${maxDepth}`),
  node: (nodeId: string) =>
    request<{ node: GraphNode; upstream: string[]; edges: { src: string; dst: string; edge_type: string; attrs: any }[] }>(
      `/lineage/node/${encodeURIComponent(nodeId)}`),
  check: (rebuild = false) =>
    request<{ warnings: { rule: string; node: string; node_type: string; message: string }[]; checked_at: string; graph_fingerprint: string }>(
      '/lineage/check', { method: rebuild ? 'POST' : 'GET' }),
};

// ── T-082：MCP 调用审计（admin-only）──
export interface AuditCall {
  id: number;
  emp_no: string;
  session_id: string;
  purpose: string;
  workspace: string;
  tool_name: string;
  side_effect: string;
  args_digest: string;
  result_digest: string;
  verdict: string;
  created_at: string;
}

export const auditApi = {
  list: (params?: { emp?: string; session?: string; tool?: string; limit?: number; offset?: number }) => {
    const q = new URLSearchParams();
    if (params?.emp) q.set('emp', params.emp);
    if (params?.session) q.set('session', params.session);
    if (params?.tool) q.set('tool', params.tool);
    if (params?.limit) q.set('limit', String(params.limit));
    if (params?.offset) q.set('offset', String(params.offset));
    const qs = q.toString();
    return request<{ calls: AuditCall[]; limit: number; offset: number }>(`/agent/audit${qs ? `?${qs}` : ''}`);
  },
  get: (id: number) => request<{ call: AuditCall }>(`/agent/audit/${id}`),
};

// ── T-080：Skill 注册表查询 ──
export interface SkillItem {
  name: string;
  version: string;
  description: string;
  author: string;
  depends_tools: string[];
  source: string;
}

export const skillsApi = {
  list: () => request<{ skills: SkillItem[] }>('/agent/skills'),
  get: (name: string) => request<{ skill: SkillItem }>(`/agent/skills/${encodeURIComponent(name)}`),
};

// ── T-703：飞书 CLI 绑定 ──
export interface LarkStatus {
  bound: boolean;
  identity: string;
  identity_name: string;
  open_id: string;
  scopes: string[];
  config_dir: string;
  error?: string;
  missing_scopes?: string[];   // T-943：必需 scope 缺失清单（材料池链路）
  reviewing?: boolean;          // T-943：刚授权仍缺 → 管理员审核中
}

export interface LarkLoginResult {
  phase: 'waiting' | 'completed' | 'error';
  verification_url?: string;
  qr_data_uri?: string;
  device_code?: string;
  identity?: string;
  open_id?: string;
  identity_name?: string;
  error?: string;
}

export const larkApi = {
  status: () => request<LarkStatus>('/settings/lark/status'),
  login: (scope = '') => request<LarkLoginResult>('/settings/lark/login', {
    method: 'POST',
    body: JSON.stringify({ scope }),
  }),
  complete: (deviceCode: string) => request<LarkLoginResult>('/settings/lark/complete', {
    method: 'POST',
    body: JSON.stringify({ device_code: deviceCode }),
  }),
  logout: () => request<{ ok: boolean }>('/settings/lark/logout', { method: 'POST' }),
  scopes: () => request<{ scopes: string[]; bound: boolean }>('/settings/lark/scopes'),
};

// ── T-509：知识维护页（词条 / 环境叙事 / 经验审核队列）──
export interface KnowledgeFinding {
  level: 'ERROR' | 'WARN';
  token?: string;
  kind?: string;
  message: string;
}

export interface GlossaryEntry {
  token: string;
  title: string;
  semantic: string;
  rules: string;
  data: string;
  refs: string;
  history: string;
  source: string;
  line: number;
}

export interface GlossaryData {
  path: string;
  text: string;
  entries: GlossaryEntry[];
  findings: KnowledgeFinding[];
}

export interface EnvNarrative {
  env: string;
  path: string;
  text: string;
  findings: KnowledgeFinding[];
}

export interface ExperienceItem {
  token: string;
  path: string;
  text: string;
  source: string;
  run_id?: string;
  scenario_id?: string;
  verdict?: string;
  hit_count?: number;
  rating?: string;
  corrected?: boolean;
  created_at?: string;
}

export const knowledgeApi = {
  glossary: () => request<GlossaryData>('/knowledge/glossary'),
  saveGlossary: (text: string) =>
    request<GlossaryData>('/knowledge/glossary', {
      method: 'PUT',
      body: JSON.stringify({ text }),
    }),
  envList: () => request<{ narratives: EnvNarrative[] }>('/knowledge/env'),
  envGet: (env: string) => request<EnvNarrative>(`/knowledge/env/${encodeURIComponent(env)}`),
  envSave: (env: string, text: string) =>
    request<{ saved: boolean; findings: KnowledgeFinding[]; message: string }>(
      `/knowledge/env/${encodeURIComponent(env)}`,
      { method: 'PUT', body: JSON.stringify({ text }) },
    ),
  experience: () => request<{ items: ExperienceItem[] }>('/knowledge/experience'),
  experienceRate: (token: string, rating: 'up' | 'down') =>
    request<{ ok: boolean; rating: string }>(`/knowledge/experience/${encodeURIComponent(token)}/rate`, {
      method: 'POST',
      body: JSON.stringify({ rating }),
    }),
};
// ── 飞书材料池（飞书知识图谱一期 T-912/T-915）──
export interface FeishuWatchUser {
  open_id: string;
  name?: string;
  scopes: string[];   // 'group_sender' | 'minutes' | 'docs'
}

// T-990：群类型标签枚举（与后端 feishu_sync_service._CHAT_KINDS 对齐）
export const FEISHU_CHAT_KINDS = ['测试', '产研', '用户', '项目', '运维', '迭代'] as const;
export type FeishuChatKind = typeof FEISHU_CHAT_KINDS[number];

export interface FeishuWatch {
  chats: { chat_id: string; name?: string; kind?: string; topic_days?: number }[];
  docs: { token: string; url?: string; owner_open_id?: string; title?: string }[];
  users: FeishuWatchUser[];
  minutes_days: number;
  chat_days: number;
  chat_sync_minutes?: number;   // T-952：定时同步间隔（0=关，分钟）
}

export interface FeishuChatItem {
  chat_id: string; name: string; chat_mode: string; peer_open_id?: string;
}
export interface FeishuUserItem {
  open_id: string; name: string; email: string; department: string;
}
export interface FeishuUserDocItem {
  token: string; title: string; url: string; doc_type: string;
  owner_id: string; owner_name: string;
}
export interface FeishuResolvedDoc {
  token: string; title?: string; url?: string;
  doc_type?: string; owner_open_id?: string;
}
export interface FeishuMaterialImage {
  placeholder: string; media_key?: string; caption?: string;
  caption_by?: string; status?: string; error?: string;
}
export interface FeishuMaterialContent {
  ok: boolean; file: string; type: string; content: string;
  raw?: string; images: FeishuMaterialImage[]; error?: string;
}

export interface FeishuReviewItem {
  src: string;
  dst: string;
  confidence: number;
  evidence: string;
  valid: boolean;
  status: 'pending' | 'confirmed' | 'rejected';
  suggested_by: string;
  suggested_at: string;
}

// ── 图谱焦点子图（飞书知识图谱一期 T-915）──
export interface FocusGraphNode {
  id: string;
  node_type: string;
  stage: string;
  title: string;
  attrs: Record<string, any>;
  source_ref?: { file: string; line_range: [number, number] } | null;
}

export interface FocusGraphEdge {
  src: string;
  dst: string;
  edge_type: string;
  attrs: Record<string, any>;
}

export interface FocusGraphResp {
  root: string;
  depth: number;
  nodes: FocusGraphNode[];
  edges: FocusGraphEdge[];
}

export interface NetworkViewResp {
  truncated: boolean;
  total_nodes: number;
  nodes: FocusGraphNode[];
  edges: FocusGraphEdge[];
}

// blob 直取请求头（token + 工作区头）：图片/附件字节需 fetch blob 渲染，
// 不能走 request()；工作区头缺失时后端 contextvar 无激活工作区 → 500（T-956）
function blobHeaders(): Record<string, string> {
  const token = session.getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const ws = session.getWorkspace();
  if (ws) headers['X-SG-Workspace'] = encodeWorkspaceHeader(ws);
  return headers;
}

export const feishuPoolApi = {
  getWatch: () => request<FeishuWatch>('/feishu-pool/watch'),
  putWatch: (cfg: FeishuWatch) =>
    request<FeishuWatch>('/feishu-pool/watch', { method: 'PUT', body: JSON.stringify(cfg) }),
  syncNow: (chatId = '') =>
    request<{ docs: number; minutes: number; chats: number;
              chats_empty?: number; days_pulled?: number; errors: string[] }>(
      '/feishu-pool/sync', { method: 'POST',
        body: JSON.stringify(chatId ? { chat_id: chatId } : {}) }),
  reviewQueue: () => request<{ items: FeishuReviewItem[] }>('/feishu-pool/review-queue'),
  confirm: (pairs: [string, string][]) =>
    request<{ confirmed: number; skipped: number;
              suggest_ivs?: { iv_id: string; title: string }[] }>(
      '/feishu-pool/review/confirm', { method: 'POST', body: JSON.stringify({ pairs }) }),
  reject: (pairs: [string, string][]) =>
    request<{ rejected: number; skipped: number }>(
      '/feishu-pool/review/reject', { method: 'POST', body: JSON.stringify({ pairs }) }),
  transcribe: () =>
    request<{ status: string; reason?: string; done: number; failed: number; total: number }>(
      '/feishu-pool/transcribe', { method: 'POST' }),
  // ── T-929 材料池总览页 ──
  poolMaterials: () =>
    request<{ items: FeishuPoolMaterial[] }>('/feishu-pool/materials'),
  poolTopics: () =>
    request<{ candidates: FeishuTopic[]; confirmed: FeishuTopic[] }>('/feishu-pool/topics'),
  // ── T-947：话题人工介入工作区（T-951c：draft 支持 days 多日窗口） ──
  listTopicDrafts: () =>
    request<{ items: Record<string, FeishuTopicDraft[]> }>('/feishu-pool/topics/drafts'),
  draftTopics: (chat_sha8: string, days: string[]) =>
    request<{ items: FeishuTopicDraft[] }>('/feishu-pool/topics/draft', {
      method: 'POST', body: JSON.stringify({ chat_sha8, days }) }),
  commitTopics: (chat_sha8: string, day: string, picked: FeishuTopicDraft[],
                 days?: string[]) =>
    request<{ items: FeishuTopic[] }>('/feishu-pool/topics/commit', {
      method: 'POST', body: JSON.stringify({ chat_sha8, day, days: days || [], picked }) }),
  editTopicCard: (id: string, title?: string, summary?: string,
                  keywords?: string[], baseRev?: number) =>
    request<FeishuTopic>('/feishu-pool/topics/card', {
      method: 'PUT', body: JSON.stringify({ id, title, summary, keywords, base_rev: baseRev }) }),
  regenTopicCard: (id: string) =>
    request<FeishuTopic>('/feishu-pool/topics/regen', {
      method: 'POST', body: JSON.stringify({ id }) }),
  // T-949：状态翻转（confirm 提升图谱 / reject 移除）
  confirmTopic: (id: string) =>
    request<FeishuTopic>('/feishu-pool/topics/confirm', {
      method: 'POST', body: JSON.stringify({ id }) }),
  rejectTopic: (id: string) =>
    request<FeishuTopic>('/feishu-pool/topics/reject', {
      method: 'POST', body: JSON.stringify({ id }) }),
  // T-948：编辑历史（多用户协作留痕，倒序）
  topicHistory: (id: string) =>
    request<{ items: FeishuTopicHistoryItem[] }>(
      `/feishu-pool/topics/history?topic_id=${encodeURIComponent(id)}`),
  // T-948：群聊消息 JSONL 事实源（时间轴渲染与精确高亮）
  chatMessages: (sha8: string, day: string) =>
    request<{ items: FeishuChatMessage[]; file: string }>(
      `/feishu-pool/chat-messages?sha8=${encodeURIComponent(sha8)}`
      + `&day=${encodeURIComponent(day)}`),
  watcherStatus: () =>
    request<{ running: boolean; count: number;
             watchers: { emp: string; started_at: string; events_received: number;
                         last_event_at: string }[] }>('/feishu-pool/watcher-status'),
  updateCaption: (material: string, placeholder: string, caption: string) =>
    request('/feishu-pool/caption', { method: 'POST',
      body: JSON.stringify({ material, placeholder, caption }) }),
  // ── 选择器数据源（同步设置弹层）──
  listChats: (limit = 0) =>
    request<{ items: FeishuChatItem[]; errors: string[]; stale?: boolean }>(
      `/feishu-pool/chats${limit > 0 ? `?limit=${limit}` : ''}`),
  searchUsers: (query: string) =>
    request<{ items: FeishuUserItem[]; errors: string[] }>(
      `/feishu-pool/users?query=${encodeURIComponent(query)}`),
  searchUserDocs: (openId: string, query = '') =>
    request<{ items: FeishuUserDocItem[]; errors: string[] }>(
      `/feishu-pool/user-docs?open_id=${encodeURIComponent(openId)}`
      + `&query=${encodeURIComponent(query)}`),
searchDocs: (query: string) =>
  request<{ items: FeishuUserDocItem[]; errors: string[] }>(
    `/feishu-pool/docs-search?query=${encodeURIComponent(query)}`),
// T-942：授权闭环（挂 feishu-pool 前缀登录即可——settings 路径被菜单 RBAC 拦且未挂载）
authStatus: () => request<LarkStatus>('/feishu-pool/auth/status'),
authLogin: (scope = '') => request<LarkLoginResult>('/feishu-pool/auth/login', {
  method: 'POST', body: JSON.stringify({ scope }),
}),
authComplete: (deviceCode: string) => request<LarkLoginResult>('/feishu-pool/auth/complete', {
  method: 'POST', body: JSON.stringify({ device_code: deviceCode }),
}),
resolveDoc: (input: string) =>
  request<{ ok: boolean; items?: FeishuResolvedDoc[]; error?: string }>(
    `/feishu-pool/resolve-doc?input=${encodeURIComponent(input)}`),
materialContent: (file: string) =>
  request<FeishuMaterialContent>(
    `/feishu-pool/material-content?file=${encodeURIComponent(file)}`),
// 图片字节需 Authorization header（<img src> 无法携带）——fetch blob → objectURL 渲染
fetchMaterialImageBlob: async (imgmapFile: string, ph: string): Promise<Blob> => {
  const r = await fetch(
    `/api/feishu-pool/material-image?file=${encodeURIComponent(imgmapFile)}`
    + `&ph=${encodeURIComponent(ph)}`, { headers: blobHeaders() });
  if (!r.ok) throw new Error(`图片加载失败（${r.status}）`);
  return r.blob();
},
// T-952/955b：聊天图片按 (message_id, media_key) 直取（时间轴富渲染；im 通道）
fetchChatImageBlob: async (messageId: string, mediaKey: string): Promise<Blob> => {
  const r = await fetch(
    `/api/feishu-pool/chat-image?message_id=${encodeURIComponent(messageId)}`
    + `&media_key=${encodeURIComponent(mediaKey)}`, { headers: blobHeaders() });
  if (!r.ok) throw new Error(`图片加载失败（${r.status}）`);
  return r.blob();
},
// T-955：聊天附件下载（消息附件可打开）
fetchChatFileBlob: async (messageId: string, fileKey: string,
                          name: string): Promise<Blob> => {
  const r = await fetch(
    `/api/feishu-pool/chat-file?message_id=${encodeURIComponent(messageId)}`
    + `&file_key=${encodeURIComponent(fileKey)}`
    + `&name=${encodeURIComponent(name)}`, { headers: blobHeaders() });
  if (!r.ok) throw new Error(`附件下载失败（${r.status}）`);
  return r.blob();
},
};

export interface FeishuPoolMaterial {
  id: string;
  type: 'feishu_doc' | 'feishu_minutes' | 'chat';
  file: string;
  title?: string;
  summary?: string;
  sha: string;
  size: number;
  mtime: number;
  source_url?: string;      // T-940：飞书原文直链（meta sidecar；存量空串降级）
  owner_open_id?: string;   // T-940：产出人（按监听用户筛选）
  owner_name?: string;
  perm?: {                   // T-949：飞书权限元数据（缺失时保守仅 owner 可见）
    pulled_at?: string | null;
    public?: boolean;
    member_users?: string[];
    member_chats?: string[];
    error?: string;
  };
}

// T-948：agent 原稿（人工编辑永不触碰；编辑对照/生成优化数据基础）
interface FeishuTopicOrigin {
  title: string;
  summary: string;
  keywords: string[];
  model?: string;
  generated_at?: string;
  prompt_version?: string;
}

export interface FeishuTopic {
  id: string;
  title: string;
  summary: string;
  chat_sha8: string;
  window: [string, string];
  message_count: number;
  participants_count: number;
  source: string;
  continues?: string;
  keywords?: string[];        // T-948：话题关键词（LLM 生成 + 用户可编辑）
  message_ids?: string[];     // T-948：精确消息锚定（高亮集合）
  days?: string[];            // T-951c：跨日卡窗口（regen/展示用；单日卡不携带）
  status?: 'draft' | 'confirmed' | 'rejected';   // T-949：状态制
  author?: { emp: string; name: string };
  rev?: number;               // T-948：乐观锁版本号
  agent_origin?: FeishuTopicOrigin;
  last_edited_by?: { emp: string; name: string };
  last_edited_at?: string;
}

export type FeishuTopicDraft = Omit<FeishuTopic, 'id'>;

// T-948：群聊消息 JSONL 事实源行（/chat-messages；时间轴渲染与精确高亮）
export interface FeishuChatMessage {
  message_id: string;
  position?: string;
  sender_id?: string;
  sender_name?: string;
  ts: string;                 // ISO：2026-08-19T14:07:00
  msg_type: string;
  content: string;
  image_key?: string;         // image 消息：单图 key
  image_keys?: string[];      // T-952：post 内嵌图（可多张）
  file_key?: string;          // T-952：file 消息
  file_name?: string;
  origin?: 'pull' | 'event';
}

// T-948：编辑历史行（/topics/history；多用户协作留痕）
export interface FeishuTopicHistoryItem {
  at: string;
  topic_id: string;
  editor: { emp: string; name: string };
  action: string;             // create/cluster/draft/commit/edit/regen/confirm/reject/reopen
  base_rev?: number;
  changes?: Record<string, { from: any; to: any }>;
}
