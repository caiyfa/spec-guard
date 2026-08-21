/** api/schedules — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

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
  system: string;            // T-996 用例级过滤：空 = 全部系统
  scenario_pattern: string;  // T-996 用例级过滤：fnmatch 场景 pattern
  created_by: string;
  created_at: string;
}

export const notifyApi = {
  list: () =>
    request<{ configs: NotifyConfig[] }>('/notify/configs'),
  create: (body: { name: string; channel: string; webhook_url: string; secret?: string; mention_mobiles?: string; events?: string[]; enabled?: boolean; system?: string; scenario_pattern?: string }) =>
    request<NotifyConfig>('/notify/configs', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: string, body: { name: string; channel: string; webhook_url: string; secret?: string; mention_mobiles?: string; events?: string[]; enabled?: boolean; system?: string; scenario_pattern?: string }) =>
    request<NotifyConfig>(`/notify/configs/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/notify/configs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  test: (id: string, event?: string) =>
    request<{ ok: boolean; message: string }>(`/notify/configs/${encodeURIComponent(id)}/test`, { method: 'POST', body: JSON.stringify({ event: event || 'plan_failure' }) }),
};

