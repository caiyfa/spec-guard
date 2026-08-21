/** api/settings — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

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

