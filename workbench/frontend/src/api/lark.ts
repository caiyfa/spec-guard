/** api/lark — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

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

