/** api/audit — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';


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

