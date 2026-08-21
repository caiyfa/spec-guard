/** api/systems — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// ── T-996：系统包管理页（T-973 后端 /api/systems 9 端点的前端面）──
export interface ExtensionGate {
  present: boolean;
  sha256: string;
  approved_sha256: string;
  approved_by: string;
  approved_at: string;
  loadable: boolean;
  reason: string;
}

export interface SystemEntry {
  name: string;
  display_name: string;
  tier: string;           // config | template | code
  tier_label: string;
  enabled: boolean;
  description: string;
  dynamic: boolean;
  envs: string[];
  default_env: string;
  accounts: string[];
  extensions_review: ExtensionGate;
  package_dir?: string;
}

export const systemsApi = {
  list: () => request<{ systems: SystemEntry[] }>('/systems'),
  detail: (name: string) => request<SystemEntry>(`/systems/${encodeURIComponent(name)}`),
  create: (body: { name: string; display_name?: string; tier?: string; description?: string; env_name?: string; env_yaml?: string }) =>
    request<{ ok: boolean; system: string }>('/systems', { method: 'POST', body: JSON.stringify(body) }),
  updateManifest: (name: string, body: { display_name?: string; tier?: string; enabled?: boolean; description?: string }) =>
    request<{ ok: boolean }>(`/systems/${encodeURIComponent(name)}/manifest`, { method: 'PUT', body: JSON.stringify(body) }),
  writeEnv: (name: string, envName: string, raw: string) =>
    request<{ ok: boolean }>(`/systems/${encodeURIComponent(name)}/env-config`, { method: 'PUT', body: JSON.stringify({ env_name: envName, raw }) }),
  writeAssertions: (name: string, raw: string) =>
    request<{ ok: boolean; registered: string[] }>(`/systems/${encodeURIComponent(name)}/assertions`, { method: 'PUT', body: JSON.stringify({ raw }) }),
  uploadExtensions: (name: string, content: string) =>
    request<{ ok: boolean; status: string; reason: string }>(`/systems/${encodeURIComponent(name)}/extensions`, { method: 'POST', body: JSON.stringify({ content }) }),
  review: (name: string) =>
    request<{ ok: boolean }>(`/systems/${encodeURIComponent(name)}/review`, { method: 'POST', body: '{}' }),
  reload: (name: string) =>
    request<{ ok: boolean; gate: ExtensionGate }>(`/systems/${encodeURIComponent(name)}/reload`, { method: 'POST', body: '{}' }),
};
