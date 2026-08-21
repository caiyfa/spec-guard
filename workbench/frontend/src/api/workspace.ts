/** api/workspace — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';

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

