import { useState } from 'react';
import type { ToolItem } from './types';
import { isToolError, tryParseJson } from './utils';
import { SqlResultTable, parseDbEvidenceResult } from '../../components/SqlResultTable';

/** 长文本截断 + 展开/收起 */
function TruncText({ text, limit = 120, className = 'text-gray-400' }: { text: string; limit?: number; className?: string }) {
  const [open, setOpen] = useState(false);
  if (text.length <= limit) return <span className={`${className} break-all`}>{text}</span>;
  return (
    <span className={`${className} break-all`}>
      {open ? text : text.slice(0, limit) + '…'}
      <button onClick={(e) => { e.stopPropagation(); setOpen(!open); }} className="text-info/80 hover:text-info ml-1">
        {open ? '收起' : '展开'}
      </button>
    </span>
  );
}

/** 单个值渲染（标量/对象自适应） */
function SmartValue({ value }: { value: any }) {
  if (value === null || value === undefined) return <span className="text-gray-600">null</span>;
  if (typeof value === 'boolean') return <span className={value ? 'text-pass' : 'text-fail'}>{String(value)}</span>;
  if (typeof value === 'number') return <span className="text-warn/80">{String(value)}</span>;
  if (typeof value === 'object') return <TruncText text={JSON.stringify(value, null, 0)} limit={150} />;
  return <TruncText text={String(value)} />;
}

/** JSON 对象 → 键值行；非 JSON → 原文截断 */
function KeyValueView({ text }: { text: string }) {
  const parsed = tryParseJson(text);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
    const entries = Object.entries(parsed);
    if (entries.length === 0) return <span className="text-gray-600">{'{}'}</span>;
    return (
      <div className="space-y-0.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex gap-1.5 items-start">
            <span className="text-info/70 flex-shrink-0">{k}:</span>
            <SmartValue value={v} />
          </div>
        ))}
      </div>
    );
  }
  if (Array.isArray(parsed)) {
    return (
      <div className="space-y-0.5">
        <div className="text-gray-500">数组 · 共 {parsed.length} 项</div>
        {parsed.slice(0, 3).map((item, i) => (
          <div key={i} className="text-gray-500 truncate">{JSON.stringify(item)?.slice(0, 120)}</div>
        ))}
        {parsed.length > 3 && <div className="text-gray-600">…</div>}
      </div>
    );
  }
  return <TruncText text={text} limit={300} />;
}

/** 结果渲染：validate 报告特渲（verdict + findings），其余走键值/文本 */
function ResultView({ result }: { result: string }) {
  const parsed = tryParseJson(result);
  if (parsed && typeof parsed === 'object' && !Array.isArray(parsed) && 'verdict' in parsed) {
    const findings = Array.isArray(parsed.findings) ? parsed.findings : [];
    return (
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <span className={parsed.verdict === 'PASS' ? 'text-pass font-medium' : 'text-fail font-medium'}>
            {parsed.verdict}
          </span>
          {parsed.scenario && <span className="text-gray-500">{parsed.scenario}</span>}
          {parsed.summary && (
            <span className="text-gray-600">error {parsed.summary.error ?? 0} / warn {parsed.summary.warn ?? 0}</span>
          )}
        </div>
        {findings.length > 0 && (
          <div className="space-y-0.5">
            {findings.slice(0, 5).map((f: any, i: number) => (
              <div key={i} className={f.level === 'ERROR' ? 'text-fail' : 'text-gray-500'}>
                [{f.level}·{f.rule}] <TruncText text={String(f.message ?? '')} limit={150} />
              </div>
            ))}
            {findings.length > 5 && <div className="text-gray-600">…共 {findings.length} 条</div>}
          </div>
        )}
      </div>
    );
  }
  return <KeyValueView text={result} />;
}

// ── 单个工具调用块（可折叠，一行式） ──
function ToolCallBlock({ tool }: { tool: ToolItem }) {
  const [expanded, setExpanded] = useState(false);
  const hasResult = tool.result !== undefined;
  const isError = hasResult && isToolError(tool.result!);
  // 结果摘要：取首个非空行（截断），内联在头部行——工具点固定一行，不再独占两行
  const resultPreview = hasResult
    ? (tool.result!.split('\n').map(l => l.trim()).find(l => l && !l.startsWith('{') && !l.startsWith('[')) || tool.result!).substring(0, 60)
    : '';

  return (
    <div className="border border-border rounded text-fs-body">
      {/* 工具头部 - 始终可见（状态 + 名称 + 结果摘要同一行） */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2 py-1 hover:bg-surface-3 transition-colors text-left"
        title={hasResult ? (isError ? '执行失败，点击查看详情' : '执行成功，点击查看详情') : '执行中…'}
      >
        <span className="text-gray-600 text-fs-aux">{expanded ? '▼' : '▶'}</span>
        <span className="text-warn/80 font-mono">🔧</span>
        <span className="text-gray-400 font-mono">{tool.name}</span>
        {hasResult && (
          <span className={isError ? 'text-fail' : 'text-pass/70'}>
            {isError ? '❌' : '✅'}
          </span>
        )}
        {!hasResult && <span className="text-warn/50 animate-pulse">⏳</span>}
        {/* 结果摘要内联（代替原第二行预览） */}
        {hasResult && resultPreview && (
          <span className={`flex-1 truncate text-fs-aux ${isError ? 'text-fail/80' : 'text-gray-500'}`}>{resultPreview}</span>
        )}
      </button>
      {/* 展开内容（K-024：键值化友好渲染，不再直接甩原始 JSON） */}
      {expanded && (
        <div className="px-2 pb-2 space-y-1.5">
          <div>
            <div className="text-gray-600 text-fs-aux mb-0.5">参数</div>
            <div className="text-fs-body bg-black/30 rounded p-1.5 overflow-x-auto max-h-60">
              <KeyValueView text={tool.args} />
            </div>
          </div>
          {hasResult && (
            <div>
              <div className="text-gray-600 text-fs-aux mb-0.5">结果</div>
              <div className={`text-fs-body bg-black/30 rounded p-1.5 overflow-x-auto max-h-72 ${isError ? 'text-fail' : ''}`}>
                {(() => {
                  // G3：attribution(db_evidence) 结果含 rows → 表格化（设计 2026-08-25 §A5）
                  const dbData = tool.name === 'attribution' ? parseDbEvidenceResult(tool.result!) : null;
                  return dbData
                    ? <SqlResultTable rows={dbData.rows} row_count={dbData.row_count} />
                    : <ResultView result={tool.result!} />;
                })()}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 工具组块（按工具名自描述分组，整体可折叠） ──
export function ToolGroupBlock({ tools, stepLabel }: { tools: ToolItem[]; stepLabel?: string }) {
  const [groupExpanded, setGroupExpanded] = useState(false);
  const allDone = tools.every(t => t.result !== undefined);
  const hasError = tools.some(t => t.result && isToolError(t.result));
  const successCount = tools.filter(t => t.result && !isToolError(t.result)).length;
  // 工具名自描述：从组内工具自身取名称，不依赖外部映射表
  const uniqueNames = [...new Set(tools.map(t => t.name))];
  const toolLabel = uniqueNames.length === 1
    ? uniqueNames[0]
    : uniqueNames.length <= 3
      ? uniqueNames.join(' · ')
      : `${uniqueNames.slice(0, 2).join(' · ')} +${uniqueNames.length - 2}`;

  return (
    <div className="mb-3">
      {/* 工具组标题栏（可折叠整个组） */}
      <button
        onClick={() => setGroupExpanded(!groupExpanded)}
        className="w-full flex items-center gap-2 px-2 py-1 text-fs-body text-gray-500 hover:text-gray-300 transition-colors text-left"
      >
        <span className="text-fs-aux">{groupExpanded ? '▼' : '▶'}</span>
        <span className="text-gray-400 font-mono">{toolLabel}</span>
        {stepLabel && stepLabel !== toolLabel && (
          <span className="text-fs-aux text-gray-600">· {stepLabel}</span>
        )}
        <span className="text-fs-aux text-gray-600">
          {allDone ? `${successCount}/${tools.length} 工具` : `${tools.length} 工具 执行中…`}
        </span>
        {allDone && (
          <span className={hasError ? 'text-fail text-fs-aux' : 'text-pass/70 text-fs-aux'}>
            {hasError ? '⚠️' : '✅'}
          </span>
        )}
        {!allDone && <span className="text-warn/50 text-fs-aux animate-pulse">⏳</span>}
      </button>
      {/* 展开时显示各工具调用（思考文本已在组外独立展示，K-024） */}
      {groupExpanded && (
        <div className="space-y-1 ml-2">
          {tools.map((tool, ti) => (
            <ToolCallBlock key={ti} tool={tool} />
          ))}
        </div>
      )}
    </div>
  );
}
