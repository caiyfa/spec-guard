import { createContext } from 'react';
import type { GateCard } from '../../api';

// ── 产物预览上下文（会话级：draft 内容匹配 + 预览回调，注入 MarkdownText 渲染树）──
export interface ArtifactCtxValue {
  onPreviewDraft: (fileName: string) => void;
  onPreviewContent: (title: string, content: string) => void;
  matchDraft: (contentTrim: string) => string | undefined;
}
export const ArtifactCtx = createContext<ArtifactCtxValue | null>(null);

// GateDock 二期/三期：对话流内嵌闸门卡片的交互回调（帮我按钮 = L1 引导直发对话）
export interface GateDockCtxValue {
  onAskAgent: (card: GateCard) => void;
  onError: (msg: string) => void;
}
export const GateDockCtx = createContext<GateDockCtxValue | null>(null);

// 辅助助手（T-1031 定位升级，原 SQL 助手）↔ 主会话的会话内桥。
// SqlAuxPanel 埋在 SidePanel 深处，props 要穿 SidePanel——沿用 GateDockCtx 的 context 注入模式。
export interface SqlAuxBridgeValue {
  register: (fn: (text: string) => void) => void;  // SqlAuxPanel 上报 send（AgentChat 存 ref）
  openDbPanel: (sql: string) => void;               // 产出物「▶ DB 面板」：会话内嵌打开（非跳页）
  /** T-1031 焦点提供者——发送时取主界面当前活动文件页签（file/draft），无则 null；
   *  后端据此给辅助会话注入 <viewing_context> 查看指针。 */
  getViewing?: () => { path: string; kind: 'file' | 'draft' } | null;
}
export const SqlAuxBridgeCtx = createContext<SqlAuxBridgeValue | null>(null);
