/** api/agent — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

// T-1042: 路径重放结果（golden flow 基线 vs 会话实际走径）
export interface FlowTraceStage {
  key: string;
  label: string;
  required: boolean;
  status: 'in_order' | 'out_of_order' | 'missing' | 'skipped';
  first_step: number | null;
  times: number;
  tools: string[];
  note: string;
  fails?: number;   // 问题调用次数（⚠N 角标，定位错误节点清单来源）
}
export interface FlowTraceResult {
  available: boolean;
  reason?: string;
  session_id?: string;
  flow_id?: string;
  flow_title?: string;
  flow_source?: string;
  is_generate?: boolean;
  n_tool_calls?: number;
  total_tokens?: number;
  purpose?: string;
  workspace?: string;
  current_stage?: { key: string; label: string; first_step: number | null } | null;
  stages?: FlowTraceStage[];
  deviations?: string[];
  extras?: string[];
  n_missing?: number;
  n_out_of_order?: number;
  mermaid?: string;
  mermaid_focused?: string | null;   // 聚焦子图（当前阶段±邻域，其余折叠）
  generated_at?: string;
  owner?: string;
  resolved_workspace?: string;
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
  // T-1021: run_in_progress/run_baseline_len 供前端 attach 续传（截断基线去重 + 续上实时流）
  getSession: (id: string, workspace = '') =>
    request<{ session_id: string; messages: any[]; reading_feed?: any[]; writing_feed?: any[]; run_in_progress?: boolean; run_baseline_len?: number }>(`/agent/sessions/${id}${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  // T-1042: 路径重放——golden flow 基线 vs 会话实际走径（对话进行中轮询即实时跑偏态）
  getFlowTrace: (id: string, workspace = '') =>
    request<FlowTraceResult>(`/agent/sessions/${id}/flow-trace${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  exportSession: (id: string, workspace = '') =>
    request<any>(`/agent/sessions/${id}/export${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`),
  // T-402: 取消会话当前运行（真打断）
  cancelSession: (sessionId: string) =>
    request<{ ok: boolean; session_id: string; message: string }>(`/agent/cancel/${sessionId}`, { method: 'POST' }),
  // 辅助会话派生（设计 2026-08-25 §B3，幂等：同父同 purpose 复用未归档 aux）
  spawnSession: (body: { parent_session_id: string; purpose: string; workspace?: string }) =>
    request<{ ok: boolean; session_id: string; created: boolean }>('/agent/sessions/spawn', { method: 'POST', body: JSON.stringify(body) }),
  // 清空会话消息（辅助会话长对话瘦身；meta 保留 + last_parent_fp 重置，下轮重注父快照）
  clearSessionMessages: (id: string, workspace = '') =>
    request<{ ok: boolean; session_id: string }>(`/agent/sessions/${id}/clear${workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''}`, { method: 'POST' }),
};

