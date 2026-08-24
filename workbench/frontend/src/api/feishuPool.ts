/** api/feishuPool — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import { encodeWorkspaceHeader, session } from './core';
import type { LarkLoginResult, LarkStatus } from './lark';

// ── 飞书话题（原飞书材料池，T-1003 改名；飞书知识图谱一期 T-912/T-915）──
export interface FeishuWatchUser {
  open_id: string;
  name?: string;
  scopes: string[];   // 'group_sender' | 'minutes' | 'docs'
}

// T-990：群类型标签枚举（与后端 feishu_sync_service._CHAT_KINDS 对齐）
export const FEISHU_CHAT_KINDS = ['测试', '产研', '用户', '项目', '运维', '迭代'] as const;
export type FeishuChatKind = typeof FEISHU_CHAT_KINDS[number];

export interface FeishuWatch {
  chats: { chat_id: string; name?: string; kind?: string; topic_days?: number }[];
  docs: { token: string; url?: string; owner_open_id?: string; title?: string }[];
  users: FeishuWatchUser[];
  minutes_days: number;
  chat_days: number;
  chat_sync_minutes?: number;   // T-952：定时同步间隔（0=关，分钟）
  // T-1008：事件直写驱动的自动话题分类双阈值（0=各自关闭）
  topic_auto_count?: number;    // 单群积累 N 条新消息即触发
  topic_auto_minutes?: number;  // 未达条数但距上次分类 M 分钟且有新消息也触发
}

// T-1008：PUT /watch 返回的监听启停三态（started=新拉起 / reloaded=运行中热更新 /
// skipped=未拉起（身份或服务未就绪）/ failed=拉起异常），供保存后诚实提示
export type FeishuWatcherState = 'started' | 'reloaded' | 'skipped' | 'failed';

export interface FeishuChatItem {
  chat_id: string; name: string; chat_mode: string; peer_open_id?: string;
}
export interface FeishuUserItem {
  open_id: string; name: string; email: string; department: string;
}
export interface FeishuUserDocItem {
  token: string; title: string; url: string; doc_type: string;
  owner_id: string; owner_name: string;
}
export interface FeishuResolvedDoc {
  token: string; title?: string; url?: string;
  doc_type?: string; owner_open_id?: string;
}
export interface FeishuMaterialImage {
  placeholder: string; media_key?: string; caption?: string;
  caption_by?: string; status?: string; error?: string;
}
export interface FeishuMaterialContent {
  ok: boolean; file: string; type: string; content: string;
  raw?: string; images: FeishuMaterialImage[]; error?: string;
}

export interface FeishuReviewItem {
  src: string;
  dst: string;
  confidence: number;
  evidence: string;
  valid: boolean;
  status: 'pending' | 'confirmed' | 'rejected';
  suggested_by: string;
  suggested_at: string;
}

// ── 图谱焦点子图（飞书知识图谱一期 T-915）──
export interface FocusGraphNode {
  id: string;
  node_type: string;
  stage: string;
  title: string;
  attrs: Record<string, any>;
  source_ref?: { file: string; line_range: [number, number] } | null;
}

export interface FocusGraphEdge {
  src: string;
  dst: string;
  edge_type: string;
  attrs: Record<string, any>;
}

export interface FocusGraphResp {
  root: string;
  depth: number;
  nodes: FocusGraphNode[];
  edges: FocusGraphEdge[];
}

export interface NetworkViewResp {
  truncated: boolean;
  total_nodes: number;
  nodes: FocusGraphNode[];
  edges: FocusGraphEdge[];
}

// blob 直取请求头（token + 工作区头）：图片/附件字节需 fetch blob 渲染，
// 不能走 request()；工作区头缺失时后端 contextvar 无激活工作区 → 500（T-956）
function blobHeaders(): Record<string, string> {
  const token = session.getToken();
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const ws = session.getWorkspace();
  if (ws) headers['X-SG-Workspace'] = encodeWorkspaceHeader(ws);
  return headers;
}

export const feishuPoolApi = {
  getWatch: () => request<FeishuWatch>('/feishu-pool/watch'),
  putWatch: (cfg: FeishuWatch) =>
    request<FeishuWatch & { watcher?: FeishuWatcherState }>(
      '/feishu-pool/watch', { method: 'PUT', body: JSON.stringify(cfg) }),
  syncNow: (chatId = '') =>
    request<{ docs: number; minutes: number; chats: number;
              chats_empty?: number; days_pulled?: number; errors: string[] }>(
      '/feishu-pool/sync', { method: 'POST',
        body: JSON.stringify(chatId ? { chat_id: chatId } : {}) }),
  reviewQueue: (scope: 'mine' | 'shared' = 'mine') =>
    request<{ items: FeishuReviewItem[]; scope: string }>(
      `/feishu-pool/review-queue?scope=${scope}`),
  confirm: (pairs: [string, string][], scope: 'mine' | 'shared' = 'mine') =>
    request<{ confirmed: number; skipped: number;
              suggest_ivs?: { iv_id: string; title: string }[] }>(
      '/feishu-pool/review/confirm', { method: 'POST', body: JSON.stringify({ pairs, scope }) }),
  reject: (pairs: [string, string][], scope: 'mine' | 'shared' = 'mine') =>
    request<{ rejected: number; skipped: number }>(
      '/feishu-pool/review/reject', { method: 'POST', body: JSON.stringify({ pairs, scope }) }),
  transcribe: () =>
    request<{ status: string; reason?: string; done: number; failed: number; total: number }>(
      '/feishu-pool/transcribe', { method: 'POST' }),
  // ── T-929 话题总览页 ──
  poolMaterials: () =>
    request<{ items: FeishuPoolMaterial[] }>('/feishu-pool/materials'),
  poolTopics: () =>
    request<{ candidates: FeishuTopic[]; confirmed: FeishuTopic[];
              cross_suggestions: CrossChatCandidate[] }>('/feishu-pool/topics'),
  // ── T-947：话题人工介入工作区（T-951c：draft 支持 days 多日窗口） ──
  listTopicDrafts: () =>
    request<{ items: Record<string, FeishuTopicDraft[]> }>('/feishu-pool/topics/drafts'),
  draftTopics: (chat_sha8: string, days: string[]) =>
    request<{ items: FeishuTopicDraft[] }>('/feishu-pool/topics/draft', {
      method: 'POST', body: JSON.stringify({ chat_sha8, days }) }),
  // T-1002：按勾选原文消息生成话题（extra_context 作为附加上下文拼入 LLM 输入；
  // title/summary/keywords 留空=LLM 生成——与重新 AI 分类同一份生成逻辑）
  composeTopic: (p: { chatSha8: string; days: string[]; messageIds: string[];
                      title?: string; summary?: string; keywords?: string[];
                      extraContext?: string }) =>
    request<FeishuTopicDraft>('/feishu-pool/topics/compose', {
      method: 'POST', body: JSON.stringify({
        chat_sha8: p.chatSha8, days: p.days, message_ids: p.messageIds,
        title: p.title || '', summary: p.summary || '',
        keywords: p.keywords || [], extra_context: p.extraContext || '' }) }),
  commitTopics: (chat_sha8: string, day: string, picked: FeishuTopicDraft[],
                 days?: string[]) =>
    request<{ items: FeishuTopic[] }>('/feishu-pool/topics/commit', {
      method: 'POST', body: JSON.stringify({ chat_sha8, day, days: days || [], picked }) }),
  // T-1001：参数对象形态（字段多，位置参不可维护）；messageIds/window/days
  // 仅手动重关联时传（不传=不改——后端 None 语义）。
  editTopicCard: (p: {
    id: string; title?: string; summary?: string; keywords?: string[];
    baseRev?: number; category?: string; priority?: string;
    messageIds?: string[]; window?: string[]; days?: string[];
  }) =>
    request<FeishuTopic>('/feishu-pool/topics/card', {
      method: 'PUT', body: JSON.stringify({
        id: p.id, title: p.title || '', summary: p.summary || '',
        keywords: p.keywords || [], base_rev: p.baseRev,
        category: p.category || '', priority: p.priority || '',
        message_ids: p.messageIds ?? null,
        window: p.messageIds ? (p.window || []) : [],
        days: p.messageIds ? (p.days || []) : [],
      }) }),
  regenTopicCard: (id: string) =>
    request<FeishuTopic>('/feishu-pool/topics/regen', {
      method: 'POST', body: JSON.stringify({ id }) }),
  // T-949：状态翻转（confirm 提升图谱 / reject 移除）
  confirmTopic: (id: string) =>
    request<FeishuTopic>('/feishu-pool/topics/confirm', {
      method: 'POST', body: JSON.stringify({ id }) }),
  rejectTopic: (id: string) =>
    request<FeishuTopic>('/feishu-pool/topics/reject', {
      method: 'POST', body: JSON.stringify({ id }) }),
  // T-948：编辑历史（多用户协作留痕，倒序）
  topicHistory: (id: string) =>
    request<{ items: FeishuTopicHistoryItem[] }>(
      `/feishu-pool/topics/history?topic_id=${encodeURIComponent(id)}`),
  // ── tag-taxonomy：标签词表（归并/收录/设域/丢弃）──
  tagRegistry: () =>
    request<FeishuTagRegistry>('/feishu-pool/tags'),
  mergeTag: (source: string, target: string) =>
    request<{ ok: boolean }>('/feishu-pool/tags/merge', {
      method: 'POST', body: JSON.stringify({ source, target }) }),
  promoteTag: (name: string) =>
    request<{ ok: boolean }>('/feishu-pool/tags/promote', {
      method: 'POST', body: JSON.stringify({ name }) }),
  dropTag: (name: string) =>
    request<{ ok: boolean }>('/feishu-pool/tags/drop', {
      method: 'POST', body: JSON.stringify({ name }) }),
  setTagDomain: (name: string, domain: string) =>
    request<{ ok: boolean }>('/feishu-pool/tags/domain', {
      method: 'POST', body: JSON.stringify({ name, domain }) }),
  // T-993：跨群关联——确认/忽略（忽略写 rejected 防重复推荐）+ 关联边清单 + LLM 精筛
  relateTopics: (a: string, b: string, confirmed: boolean) =>
    request<{ a: string; b: string; status: string }>('/feishu-pool/topics/relate', {
      method: 'POST', body: JSON.stringify({ a, b, confirmed }) }),
  topicRelations: () =>
    request<{ items: TopicRelation[] }>('/feishu-pool/topics/relations'),
  crossRefine: () =>
    request<{ items: CrossChatCandidate[]; cached: boolean; unrefined: boolean }>(
      '/feishu-pool/topics/cross-refine', { method: 'POST' }),
  // T-948：群聊消息 JSONL 事实源（时间轴渲染与精确高亮）
  chatMessages: (sha8: string, day: string) =>
    request<{ items: FeishuChatMessage[]; file: string }>(
      `/feishu-pool/chat-messages?sha8=${encodeURIComponent(sha8)}`
      + `&day=${encodeURIComponent(day)}`),
  watcherStatus: () =>
    request<{ running: boolean; count: number;
             watchers: { emp: string; started_at: string; events_received: number;
                         last_event_at: string }[] }>('/feishu-pool/watcher-status'),
  updateCaption: (material: string, placeholder: string, caption: string) =>
    request('/feishu-pool/caption', { method: 'POST',
      body: JSON.stringify({ material, placeholder, caption }) }),
  // ── 选择器数据源（同步设置弹层）──
  listChats: (limit = 0) =>
    request<{ items: FeishuChatItem[]; errors: string[]; stale?: boolean }>(
      `/feishu-pool/chats${limit > 0 ? `?limit=${limit}` : ''}`),
  searchUsers: (query: string) =>
    request<{ items: FeishuUserItem[]; errors: string[] }>(
      `/feishu-pool/users?query=${encodeURIComponent(query)}`),
  searchUserDocs: (openId: string, query = '') =>
    request<{ items: FeishuUserDocItem[]; errors: string[] }>(
      `/feishu-pool/user-docs?open_id=${encodeURIComponent(openId)}`
      + `&query=${encodeURIComponent(query)}`),
searchDocs: (query: string) =>
  request<{ items: FeishuUserDocItem[]; errors: string[] }>(
    `/feishu-pool/docs-search?query=${encodeURIComponent(query)}`),
// T-942：授权闭环（挂 feishu-pool 前缀登录即可——settings 路径被菜单 RBAC 拦且未挂载）
authStatus: () => request<LarkStatus>('/feishu-pool/auth/status'),
authLogin: (scope = '') => request<LarkLoginResult>('/feishu-pool/auth/login', {
  method: 'POST', body: JSON.stringify({ scope }),
}),
authComplete: (deviceCode: string) => request<LarkLoginResult>('/feishu-pool/auth/complete', {
  method: 'POST', body: JSON.stringify({ device_code: deviceCode }),
}),
resolveDoc: (input: string) =>
  request<{ ok: boolean; items?: FeishuResolvedDoc[]; error?: string }>(
    `/feishu-pool/resolve-doc?input=${encodeURIComponent(input)}`),
materialContent: (file: string) =>
  request<FeishuMaterialContent>(
    `/feishu-pool/material-content?file=${encodeURIComponent(file)}`),
// 图片字节需 Authorization header（<img src> 无法携带）——fetch blob → objectURL 渲染
fetchMaterialImageBlob: async (imgmapFile: string, ph: string): Promise<Blob> => {
  const r = await fetch(
    `/api/feishu-pool/material-image?file=${encodeURIComponent(imgmapFile)}`
    + `&ph=${encodeURIComponent(ph)}`, { headers: blobHeaders() });
  if (!r.ok) throw new Error(`图片加载失败（${r.status}）`);
  return r.blob();
},
// T-952/955b：聊天图片按 (message_id, media_key) 直取（时间轴富渲染；im 通道）
fetchChatImageBlob: async (messageId: string, mediaKey: string): Promise<Blob> => {
  const r = await fetch(
    `/api/feishu-pool/chat-image?message_id=${encodeURIComponent(messageId)}`
    + `&media_key=${encodeURIComponent(mediaKey)}`, { headers: blobHeaders() });
  if (!r.ok) throw new Error(`图片加载失败（${r.status}）`);
  return r.blob();
},
// T-955：聊天附件下载（消息附件可打开）
fetchChatFileBlob: async (messageId: string, fileKey: string,
                          name: string): Promise<Blob> => {
  const r = await fetch(
    `/api/feishu-pool/chat-file?message_id=${encodeURIComponent(messageId)}`
    + `&file_key=${encodeURIComponent(fileKey)}`
    + `&name=${encodeURIComponent(name)}`, { headers: blobHeaders() });
  if (!r.ok) throw new Error(`附件下载失败（${r.status}）`);
  return r.blob();
},
};

export interface FeishuPoolMaterial {
  id: string;
  type: 'feishu_doc' | 'feishu_minutes' | 'chat';
  file: string;
  title?: string;
  summary?: string;
  sha: string;
  size: number;
  mtime: number;
  source_url?: string;      // T-940：飞书原文直链（meta sidecar；存量空串降级）
  owner_open_id?: string;   // T-940：产出人（按监听用户筛选）
  owner_name?: string;
  perm?: {                   // T-949：飞书权限元数据（缺失时保守仅 owner 可见）
    pulled_at?: string | null;
    public?: boolean;
    member_users?: string[];
    member_chats?: string[];
    error?: string;
  };
}

// T-948：agent 原稿（人工编辑永不触碰；编辑对照/生成优化数据基础）
interface FeishuTopicOrigin {
  title: string;
  summary: string;
  keywords: string[];
  model?: string;
  generated_at?: string;
  prompt_version?: string;
}

// T-991：话题五分类（chat 闲聊默认过滤可开关——拍板③）/ 优先级（信号推导初值，人工可改）
export type FeishuTopicCategory = 'chat' | 'routine' | 'requirement' | 'test' | 'solution';
export type FeishuTopicPriority = 'high' | 'normal' | 'low';

export interface FeishuTopic {
  id: string;
  title: string;
  summary: string;
  chat_sha8: string;
  window: [string, string];
  message_count: number;
  participants_count: number;
  source: string;
  continues?: string;
  keywords?: string[];        // T-948：话题关键词（LLM 生成 + 用户可编辑）
  message_ids?: string[];     // T-948：精确消息锚定（高亮集合）
  days?: string[];            // T-951c：跨日卡窗口（regen/展示用；单日卡不携带）
  status?: 'draft' | 'confirmed' | 'rejected';   // T-949：状态制
  author?: { emp: string; name: string };
  rev?: number;               // T-948：乐观锁版本号
  agent_origin?: FeishuTopicOrigin;
  last_edited_by?: { emp: string; name: string };
  last_edited_at?: string;
  category?: FeishuTopicCategory;       // T-991：五分类（存量卡默认 routine）
  priority?: FeishuTopicPriority;       // T-991：high|normal|low（初值信号推导）
  modules?: string[];           // T-992：FR 锚点派生（已确认 mentions 边→模块目录；
                                // 响应时计算不落库，关联不到 FR 留空——拍板②）
}

export type FeishuTopicDraft = Omit<FeishuTopic, 'id'>;

// tag-taxonomy：标签词表（_tags.yaml；别名归并 + 状态制 active/pending +
// domain 一级域——话题标签爆炸收口，详见 specflow/feishu_pool/tag_registry.py）
export interface FeishuTagEntry {
  aliases: string[];
  domain: string;                 // 一级域（''=未分组）
  status: 'active' | 'pending';
  source?: string;                // llm | human
  created_at?: string;
}
export interface FeishuTagRegistry {
  version: number;
  tags: Record<string, FeishuTagEntry>;
  domains: Record<string, { status: string; created_at?: string }>;
}

// T-993：跨群关联（relates_to 边——只推荐不合并，人确认后生效）
export interface TopicRelation {
  src: string;                 // tp id（规范化小 id 在前）
  dst: string;
  confirmed_by?: string;
  confirmed_at?: string;
}

export interface CrossChatCandidate {
  src: string;                 // tp id
  dst: string;
  score: number;               // 确定性预筛分（0~1）
  reasons: string[];
  refined?: boolean;           // LLM 精筛是否落注（false=未经模型复核）
  llm_same?: boolean;
  llm_confidence?: number;
  llm_reason?: string;
}

// T-948：群聊消息 JSONL 事实源行（/chat-messages；时间轴渲染与精确高亮）
export interface FeishuChatMessage {
  message_id: string;
  position?: string;
  sender_id?: string;
  sender_name?: string;
  ts: string;                 // ISO：2026-08-19T14:07:00
  msg_type: string;
  content: string;
  image_key?: string;         // image 消息：单图 key
  image_keys?: string[];      // T-952：post 内嵌图（可多张）
  file_key?: string;          // T-952：file 消息
  file_name?: string;
  origin?: 'pull' | 'event';
}

// T-948：编辑历史行（/topics/history；多用户协作留痕）
export interface FeishuTopicHistoryItem {
  at: string;
  topic_id: string;
  editor: { emp: string; name: string };
  action: string;             // create/cluster/draft/commit/edit/regen/confirm/reject/reopen
  base_rev?: number;
  changes?: Record<string, { from: any; to: any }>;
}

