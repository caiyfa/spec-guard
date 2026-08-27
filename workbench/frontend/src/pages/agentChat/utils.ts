import type { ChatMessage } from './types';

/** K-013/T-1031：消息展示前剥离后端注入块——<references>（@引用注入）、
 * <parent_context> 与 [parent_context] 单行降级形态（辅助会话父快照）、
 * <viewing_context>（查看指针）、<knowledge_refs>（知识 nudge，落盘进 user 消息尾部）。
 * 五者均为「LLM 可见、UI 不显示」的通道载荷；全局替换不限定位置。 */
export function stripRefBlock(content: string): string {
  return (content || '')
    .replace(/<references>[\s\S]*?<\/references>\s*/g, '')
    .replace(/<parent_context>[\s\S]*?<\/parent_context>\s*/g, '')
    .replace(/\[parent_context\][^\n]*\n?/g, '')
    .replace(/<viewing_context>[\s\S]*?<\/viewing_context>\s*/g, '')
    .replace(/<knowledge_refs>[\s\S]*?<\/knowledge_refs>\s*/g, '')
    .trimEnd();
}

/** T-1031 查看指针解析（验收缺陷 A 修复）：辅助面板发送时用户必然已切走活动侧签，
 * 只认「当前活动」会让 focus 恒空。口径改为——优先当前活动的 file: 页签，
 * 其次记忆中最近活动过的 file: 页签（lastFileTab），页签已关闭则视为无焦点。
 * kind 字面量与 SqlAuxPanel.ViewingFocus 对齐（'file' | 'draft'）。 */
export function resolveViewingFocus(
  activeTab: string,
  lastFileTab: string,
  fileTabs: ReadonlyArray<{ path: string; kind?: 'file' | 'draft' }>,
): { path: string; kind: 'file' | 'draft' } | null {
  const wanted = activeTab.startsWith('file:') ? activeTab : lastFileTab;
  if (!wanted || !wanted.startsWith('file:')) return null;
  const path = wanted.slice('file:'.length);
  const hit = fileTabs.find(t => t.path === path);
  if (!hit) return null;
  const kind: 'file' | 'draft' = hit.kind === 'draft' ? 'draft' : 'file';
  return { path: hit.path, kind };
}

// ── 按角色估算 token 分布（参考 opencode 的 chars/4 方法） ──
export function calcCtxBreakdown(messages: ChatMessage[], actualPromptTokens: number): Record<string, number> {
  const est: Record<string, number> = { system: 0, user: 0, assistant: 0, tool: 0 };
  for (const msg of messages) {
    const role = msg.role in est ? msg.role : 'system';
    const content = msg.content || '';
    const toolArgs = (msg.tool_calls || []).reduce((s, tc) => s + (tc.function.arguments || '').length, 0);
    est[role] += Math.ceil((content.length + toolArgs) / 4);
  }
  const total = Object.values(est).reduce((a, b) => a + b, 0);
  if (total > 0 && actualPromptTokens > 0) {
    const scale = actualPromptTokens / total;
    for (const k in est) est[k] = Math.round(est[k] * scale);
  }
  return est;
}

export const fmtSize = (n?: number) => n === undefined ? '' : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`;

/** md 文本首个标题（产物卡片主标题用） */
export function firstMdTitle(text: string): string | null {
  const m = /^#{1,3}\s+(.+)$/m.exec(text);
  return m ? m[1].replace(/[#*`[\]]/g, '').trim() : null;
}

/** 扩展名 → 格式标签 */
export function extLabelOf(name?: string): string {
  if (!name) return '';
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase();
  if (ext === '.yaml' || ext === '.yml') return 'YAML';
  if (ext === '.md' || ext === '.markdown') return 'Markdown';
  return ext.replace('.', '').toUpperCase();
}

// ── 提取 <plan> 标签 ──
export function extractPlan(content: string): string[] | null {
  const match = content.match(/<plan>([\s\S]*?)<\/plan>/);
  if (!match) return null;
  return match[1].split('\n').map(l => l.trim()).filter(l => l);
}

// ── 去除 <plan> 标签后的内容 ──
export function stripPlan(content: string): string {
  return content.replace(/<plan>[\s\S]*?<\/plan>/g, '').trim();
}

// ── K-024：工具参数/结果的友好渲染 ──
export function tryParseJson(text: string): any {
  try { return JSON.parse(text); } catch { return undefined; }
}

/**
 * 工具结果语义判错：解析 JSON 后按协议字段判定，避免「"error": 0 计数键」被文本匹配误判为失败。
 * 判定顺序：顶层 ok 字段 → 顶层 verdict 字段（REJECT/ERROR 才算错）→ 顶层 error 值非空 →
 * 非 JSON 对象（纯文本/数组/解析失败）保留启发式兜底（含 ERROR / ❌）。
 */
export function isToolError(result: string): boolean {
  const parsed = tryParseJson(result);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    if ('ok' in parsed) return parsed.ok !== true;
    if ('verdict' in parsed) return parsed.verdict === 'REJECT' || parsed.verdict === 'ERROR';
    if ('error' in parsed) return Boolean(parsed.error);
    return false;
  }
  return result.includes('ERROR') || result.includes('❌');
}

/** 辅助会话不出现在会话树（设计 2026-08-25 §B5）。 */
export function filterTreeSessions<T extends { kind?: string }>(sessions: T[]): T[] {
  return sessions.filter(s => (s as any).kind !== 'aux');
}
