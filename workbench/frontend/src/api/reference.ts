/** api/reference — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import type { EnvEntry, SystemInfo } from './workspace';

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

