/** api/core — T-997 自 api.ts 按域拆分（行为零变化纯重构） */

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

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
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

