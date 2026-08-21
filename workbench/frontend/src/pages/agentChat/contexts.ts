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
