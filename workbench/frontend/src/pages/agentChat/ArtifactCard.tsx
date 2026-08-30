import { useContext } from 'react';
import { ArtifactCtx } from './contexts';
import { extLabelOf, fmtSize } from './utils';
import type { ArtifactInfo } from './types';

// ── 产物卡片（对话流内统一的可点击文件/文档入口，点击在右侧页签预览）──
export function ArtifactCard({ artifact }: { artifact: ArtifactInfo }) {
  const ctx = useContext(ArtifactCtx);
  const metaParts = [
    artifact.fileName && artifact.fileName !== artifact.title ? artifact.fileName : '',
    artifact.lines !== undefined ? `${artifact.lines} 行` : '',
    fmtSize(artifact.size),
    extLabelOf(artifact.fileName) || artifact.formatLabel || '',
  ].filter(Boolean);
  // draftsApi 仅支持 yaml 草稿：非 yaml 产物带 content 走 memo 内容预览
  const isYamlDraft = !!artifact.fileName && /\.ya?ml$/i.test(artifact.fileName);
  return (
    <button
      onClick={() => {
        if (!ctx) return;
        if (isYamlDraft) ctx.onPreviewDraft(artifact.fileName!);
        else if (artifact.content) ctx.onPreviewContent(artifact.title, artifact.content);
        else if (artifact.fileName) ctx.onPreviewDraft(artifact.fileName);
      }}
      title={artifact.fileName ? `预览草稿 ${artifact.fileName}` : '预览文档'}
      className="w-full flex items-center gap-2.5 border border-border bg-surface-2/40 rounded-lg px-3 py-2 hover:border-info/40 hover:bg-surface-2/70 transition-colors text-left group"
    >
      <span className="text-fs-title flex-shrink-0">📄</span>
      <span className="flex-1 min-w-0">
        <span className="block text-fs-lead text-gray-200 truncate">{artifact.title}</span>
        <span className="block text-fs-aux text-gray-500 truncate">{metaParts.join(' · ')}</span>
      </span>
      <span className="text-fs-body text-info/70 flex-shrink-0 group-hover:text-info">预览 ›</span>
    </button>
  );
}
