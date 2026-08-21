// TopicCard.tsx — 话题卡片（T-950 增强版）：
// 状态徽标（draft/confirmed/rejected）+ confirm/reject + 编辑
// （title/summary/keywords + AI 原稿对照）+ 重生成 + 历史抽屉（多用户留痕）。
// 409 乐观锁冲突：提示「已被他人编辑」并刷新（服务端拒绝静默覆盖）。

import { useEffect, useState } from 'react';
import {
  feishuPoolApi,
  type FeishuTopic,
  type FeishuTopicHistoryItem,
} from '../api';
import ModelSetupModal from './ModelSetupModal';

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  draft: { label: '待确认', cls: 'bg-amber-500/15 text-amber-400' },
  confirmed: { label: '已确认', cls: 'bg-green-500/15 text-green-400' },
  rejected: { label: '已拒绝', cls: 'bg-gray-600/30 text-gray-500 line-through' },
};

// T-991：五分类徽标（chat 闲聊默认过滤——工作台开关控制，卡片侧只如实呈现）
const CATEGORY_BADGE: Record<string, { label: string; cls: string }> = {
  chat: { label: '闲聊', cls: 'bg-gray-600/30 text-gray-500' },
  routine: { label: '沟通', cls: 'bg-sky-500/15 text-sky-400' },
  requirement: { label: '需求', cls: 'bg-amber-500/15 text-amber-300' },
  test: { label: '测试', cls: 'bg-blue-500/15 text-blue-400' },
  solution: { label: '方案', cls: 'bg-violet-500/15 text-violet-400' },
};

// T-991：优先级徽标（初值信号推导，人工可改）
const PRIORITY_BADGE: Record<string, { label: string; cls: string }> = {
  high: { label: '高优', cls: 'text-red-400' },
  normal: { label: '中', cls: 'text-gray-500' },
  low: { label: '低', cls: 'text-gray-600' },
};

const ACTION_LABEL: Record<string, string> = {
  create: '自动聚类生成', cluster: '系统聚类修订', draft: '生成分段草案',
  commit: '人工提交', edit: '人工编辑', regen: '重新生成',
  confirm: '确认', reject: '拒绝', reopen: '重新打开',
};

export default function TopicCard({ topic: t, draft, selected, onSelect, onRefresh,
                                     relatedCount, onOpenRelations }: {
  topic: FeishuTopic;
  draft?: boolean;             // 介入工作区草案段（未提交，仅展示）
  selected?: boolean;
  onSelect?: () => void;
  onRefresh: () => void;
  relatedCount?: number;       // T-993：跨群关联数（relates_to 边连通方）
  onOpenRelations?: () => void;  // T-993：打开关联抽屉（并排多群证据）
}) {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(t.title);
  const [draftSummary, setDraftSummary] = useState(t.summary);
  const [draftKeywords, setDraftKeywords] = useState((t.keywords || []).join('，'));
  // T-991：分类/优先级编辑态（空串=不改，沿用现值）
  const [draftCategory, setDraftCategory] = useState(t.category || '');
  const [draftPriority, setDraftPriority] = useState(t.priority || '');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [history, setHistory] = useState<FeishuTopicHistoryItem[] | null>(null);
  // T-954：模型缺失就地配置弹层（regen 未配置时不报错踢人）
  const [modelSetup, setModelSetup] = useState(false);

  useEffect(() => {
    setDraftTitle(t.title);
    setDraftSummary(t.summary);
    setDraftKeywords((t.keywords || []).join('，'));
    setDraftCategory(t.category || '');
    setDraftPriority(t.priority || '');
  }, [t.title, t.summary, t.keywords, t.category, t.priority]);

  const saveEdit = async () => {
    setBusy('edit'); setErr('');
    try {
      const kws = draftKeywords.split(/[，,]/).map(s => s.trim()).filter(Boolean);
      await feishuPoolApi.editTopicCard(t.id, draftTitle, draftSummary, kws, t.rev,
        draftCategory, draftPriority);
      setEditing(false);
      onRefresh();
    } catch (e: any) {
      // 409（已被他人编辑）/ 其他错误都如实提示；卡片刷新后 rev 对齐可重试
      setErr(e.message);
      onRefresh();
    } finally { setBusy(''); }
  };

  const regen = async () => {
    setBusy('regen'); setErr('');
    try {
      await feishuPoolApi.regenTopicCard(t.id);
      onRefresh();
    } catch (e: any) {
      if (/未配置 text 模型/.test(String(e?.message || ''))) {
        setModelSetup(true);            // T-954：弹层就地配置，保存后自动重试
      } else {
        setErr(e.message);
      }
    } finally { setBusy(''); }
  };

  const flip = async (kind: 'confirm' | 'reject') => {
    setBusy(kind); setErr('');
    try {
      await (kind === 'confirm'
        ? feishuPoolApi.confirmTopic(t.id)
        : feishuPoolApi.rejectTopic(t.id));
      onRefresh();
    } catch (e: any) { setErr(e.message); } finally { setBusy(''); }
  };

  const loadHistory = async () => {
    if (history !== null) { setHistory(null); return; }
    try {
      const r = await feishuPoolApi.topicHistory(t.id);
      setHistory(r.items || []);
    } catch (e: any) { setErr(e.message); }
  };

  const input = 'bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info';
  const status = t.status || 'draft';
  const badge = STATUS_BADGE[status] || STATUS_BADGE.draft;
  const origin = t.agent_origin;
  // AI 原稿对照：人工当前值 vs agent 原稿（差异字段标 amber——R8 的查看入口）
  const diff = (cur: string, orig?: string) =>
    orig !== undefined && orig !== cur;

  return (
    <div className="min-w-0 w-full text-xs"
      onClick={onSelect}>
      <div className="flex items-center gap-2 flex-wrap">
        {editing ? (
          <input className={`${input} flex-1 min-w-[120px]`}
            value={draftTitle} onChange={e => setDraftTitle(e.target.value)} />
        ) : (
          <span className={`font-medium ${selected ? 'text-info' : 'text-gray-200'}`}>
            {t.title}
          </span>
        )}
        {!draft && (
          <span className={`px-1.5 py-0.5 rounded text-[10px] shrink-0 ${badge.cls}`}>
            {badge.label}
          </span>
        )}
        {t.category && (
          <span className={`px-1.5 py-0.5 rounded text-[10px] shrink-0 ${(CATEGORY_BADGE[t.category] || CATEGORY_BADGE.routine).cls}`}>
            {(CATEGORY_BADGE[t.category] || CATEGORY_BADGE.routine).label}
          </span>
        )}
        {t.priority && t.priority !== 'normal' && (
          <span className={`text-[10px] shrink-0 ${(PRIORITY_BADGE[t.priority] || PRIORITY_BADGE.normal).cls}`}
            title={`优先级：${t.priority}（信号推导初值，可编辑）`}>
            {(PRIORITY_BADGE[t.priority] || PRIORITY_BADGE.normal).label}
          </span>
        )}
        {!draft && (relatedCount || 0) > 0 && (
          <button className="text-[10px] shrink-0 text-emerald-400 hover:underline"
            title="跨群关联（点击查看多群证据并排）"
            onClick={e => { e.stopPropagation(); onOpenRelations?.(); }}>
            🔗 {(relatedCount || 0) + 1} 群
          </button>
        )}
        {t.continues && <span className="text-[10px] text-amber-400">⤺ 延续</span>}
        <span className="ml-auto flex items-center gap-2 text-[10px] text-gray-500">
          {t.message_count} 条 · {t.participants_count} 人
          {t.rev !== undefined && t.rev > 1 && <span title="乐观锁版本">v{t.rev}</span>}
        </span>
      </div>
      {editing ? (
        <>
          <textarea className={`${input} w-full mt-1`} rows={2}
            value={draftSummary} onChange={e => setDraftSummary(e.target.value)} />
          <input className={`${input} w-full mt-1`} placeholder="关键词（逗号分隔，2~5 个）"
            value={draftKeywords} onChange={e => setDraftKeywords(e.target.value)} />
          <div className="flex gap-2 mt-1">
            <select className={`${input} flex-1`} value={draftCategory}
              onChange={e => setDraftCategory(e.target.value)}
              title="话题分类（五分类；空=不改）">
              <option value="">分类：不改</option>
              <option value="chat">闲聊</option>
              <option value="routine">沟通</option>
              <option value="requirement">需求</option>
              <option value="test">测试</option>
              <option value="solution">方案</option>
            </select>
            <select className={`${input} flex-1`} value={draftPriority}
              onChange={e => setDraftPriority(e.target.value)}
              title="优先级（信号推导初值，可人工改；空=不改）">
              <option value="">优先级：不改</option>
              <option value="high">高</option>
              <option value="normal">中</option>
              <option value="low">低</option>
            </select>
          </div>
          {origin && (
            <div className="mt-1 p-1.5 rounded bg-surface-3/60 border border-border/50">
              <div className="text-[10px] text-gray-500 mb-0.5">
                AI 原稿对照（人工修改处标黄，生成优化依据）：
              </div>
              <div className={`text-[10px] ${diff(draftTitle, origin.title) ? 'text-amber-300' : 'text-gray-500'}`}>
                题目：{origin.title}
              </div>
              <div className={`text-[10px] ${diff(draftSummary, origin.summary) ? 'text-amber-300' : 'text-gray-500'}`}>
                摘要：{origin.summary}
              </div>
              <div className="text-[10px] text-gray-600">
                {origin.model && `模型 ${origin.model} · `}生成于 {origin.generated_at || '—'}
                {origin.prompt_version && ` · ${origin.prompt_version}`}
              </div>
            </div>
          )}
        </>
      ) : (
        <>
          <p className={`mt-1 ${status === 'rejected' ? 'text-gray-600' : 'text-gray-400'}`}>
            {t.summary}
          </p>
          {(t.keywords || []).length > 0 && (
            <div className="flex gap-1 flex-wrap mt-1">
              {t.keywords.map(k => (
                <span key={k} className="px-1.5 py-0.5 rounded bg-surface-3 border border-border text-[10px] text-gray-400">
                  {k}
                </span>
              ))}
            </div>
          )}
          {/* T-992：功能模块（FR 锚点派生，拍板②——非自由字段；留空不显示） */}
          {(t.modules || []).length > 0 && (
            <div className="flex gap-1 flex-wrap mt-1">
              {t.modules.map(m => (
                <span key={m} className="px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-[10px] text-emerald-400"
                  title="功能模块：由已确认的话题→FR 关联边派生（FR 模块目录）">
                  🏷 {m}
                </span>
              ))}
            </div>
          )}
        </>
      )}
      {(t.last_edited_by?.name || t.author?.name) && (
        <div className="text-[10px] text-gray-600 mt-1">
          {t.author?.name ? `创建：${t.author.name}` : ''}
          {t.last_edited_by?.name ? ` · 最后编辑：${t.last_edited_by.name}` : ''}
        </div>
      )}
      {err && <div className="text-[10px] text-red-400 mt-1">{err}</div>}
      {!draft && (
        <div className="flex items-center gap-2 mt-1 text-[10px]">
          {editing ? (
            <>
              <button className="text-info hover:underline" onClick={saveEdit}
                disabled={busy === 'edit'}>
                {busy === 'edit' ? '保存中…' : '保存'}
              </button>
              <button className="text-gray-500 hover:underline"
                onClick={() => setEditing(false)}>取消</button>
            </>
          ) : (
            <>
              <button className="text-info hover:underline"
                onClick={() => setEditing(true)}>编辑</button>
              <button className="text-info hover:underline" onClick={regen}
                disabled={busy === 'regen'}>
                {busy === 'regen' ? '生成中…' : '重新生成'}
              </button>
              {status !== 'confirmed' && (
                <button className="text-green-400 hover:underline" onClick={() => flip('confirm')}
                  disabled={busy === 'confirm'}>
                  {busy === 'confirm' ? '确认中…' : '✓ 确认'}
                </button>
              )}
              {status !== 'rejected' && (
                <button className="text-red-400 hover:underline" onClick={() => flip('reject')}
                  disabled={busy === 'reject'}>
                  {busy === 'reject' ? '…' : '✕ 拒绝'}
                </button>
              )}
              <button className="text-gray-500 hover:underline" onClick={loadHistory}>
                {history !== null ? '收起历史' : '历史'}
              </button>
            </>
          )}
        </div>
      )}
      {history !== null && (
        <div className="mt-1.5 border-t border-border pt-1.5 max-h-44 overflow-auto">
          {history.length === 0 ? (
            <div className="text-[10px] text-gray-600">暂无历史记录</div>
          ) : history.map((h, i) => (
            <div key={i} className="text-[10px] text-gray-500 leading-relaxed">
              <span className="text-gray-400">{h.at.slice(5, 16)}</span>
              {' · '}
              <span className={h.editor?.emp ? 'text-gray-400' : 'text-gray-600'}>
                {h.editor?.name || '系统'}
              </span>
              {' '}{ACTION_LABEL[h.action] || h.action}
              {h.changes && Object.entries(h.changes).map(([field, ch]) => (
                <span key={field} className="text-gray-600">
                  {' '}{field}: {shortVal(ch.from)} → {shortVal(ch.to)}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
      {/* T-954：模型缺失就地配置弹层（保存后自动重试 regen） */}
      {modelSetup && (
        <ModelSetupModal purpose="text"
          onClose={() => setModelSetup(false)}
          onConfigured={() => { setModelSetup(false); void regen(); }} />
      )}
    </div>
  );
}

function shortVal(v: any): string {
  if (v === null || v === undefined) return '∅';
  if (typeof v === 'string') return v.length > 16 ? `${v.slice(0, 16)}…` : v;
  if (Array.isArray(v)) return `[${v.length}项]`;
  if (typeof v === 'object' && 'title' in v) return `原稿(${v.title})`;
  return String(v);
}
