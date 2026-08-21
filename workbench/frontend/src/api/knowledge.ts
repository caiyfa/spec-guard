/** api/knowledge — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

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
