// TopicCard.tsx — 话题列表行（T-950 卡片；T-1001 F2 从泳道色卡平铺改为
// 紧凑列表行——话题多时配合搜索/排序快速定位；F3 编辑迁出到弹框
// TopicEditModal：原文与话题内容并排、支持手动重关联）。
// 状态徽标（draft/confirmed/rejected）+ confirm/reject + 重新生成 +
// 历史展开（多用户留痕）。409 乐观锁冲突：提示「已被他人编辑」并刷新。
// T-1001 追修：hover 联动退役（总控人拍板）——原文定位改「⌖ 定位原文」
// 按钮显式触发（入库卡与草案段一致），不再鼠标挪上即高亮时间轴。

import { useState } from 'react';
import {
  feishuPoolApi,
  type FeishuTopic,
  type FeishuTopicHistoryItem,
  type FeishuTopicMaterialRef,
} from '../api';
import type { TagIndex } from './topicList';
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

// 行 meta 用时间：window 首末取 MM-DD HH:MM（跨日显示区间）
function fmtWindow(t: FeishuTopic): string {
  const s = String(t.window?.[0] || '');
  const e = String(t.window?.[1] || '');
  if (!s) return '';
  if (!e || e.slice(0, 10) === s.slice(0, 10)) return s.slice(5, 16);
  return `${s.slice(5, 16)}~${e.slice(5, 16)}`;
}

export default function TopicCard({ topic: t, draft, selected, onRefresh,
                                     relatedCount, onOpenRelations, onEdit, onLocate,
                                     tagIdx, onOpenMaterial }: {
  topic: FeishuTopic;
  draft?: boolean;             // 介入工作区草案段（未提交，仅展示）
  selected?: boolean;
  onRefresh: () => void;
  relatedCount?: number;       // T-993：跨群关联数（relates_to 边连通方）
  onOpenRelations?: () => void;  // T-993：打开关联抽屉（并排多群证据）
  onEdit?: () => void;         // T-1001：打开编辑弹框（左原文右话题并排+重关联）
  onLocate?: () => void;       // T-1001 追修：定位原文（显式按钮，取代 hover 联动）
  tagIdx?: TagIndex;           // tag-taxonomy T2：关键词芯片 tooltip 携带域归属
  onOpenMaterial?: (m: FeishuTopicMaterialRef) => void;  // T-1014：关联材料点击（页面层详情弹层）
}) {
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');
  const [history, setHistory] = useState<FeishuTopicHistoryItem[] | null>(null);
  // T-954：模型缺失就地配置弹层（regen 未配置时不报错踢人）
  const [modelSetup, setModelSetup] = useState(false);

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

  const status = t.status || 'draft';
  const badge = STATUS_BADGE[status] || STATUS_BADGE.draft;
  const time = fmtWindow(t);

  return (
    <div className={`min-w-0 w-full text-xs rounded-lg border p-2 transition-colors
      ${selected ? 'border-info/60 bg-info/10' : 'border-border bg-surface-3 hover:border-gray-500'}
      ${status === 'rejected' ? 'opacity-50' : ''}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`font-medium truncate ${selected ? 'text-info' : 'text-gray-200'}`}
          title={t.title}>
          {t.title}
        </span>
        {!draft && (
          <span className={`px-1.5 py-0.5 rounded text-[10px] shrink-0 ${badge.cls}`}>
            {badge.label}
          </span>
        )}
        {draft && (
          <span className="px-1.5 py-0.5 rounded text-[10px] shrink-0 bg-info/10 text-info">
            草案
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
        <span className="ml-auto flex items-center gap-2 text-[10px] text-gray-500 shrink-0">
          {time && <span>{time}</span>}
          <span>{t.message_count} 条 · {t.participants_count} 人</span>
          {t.rev !== undefined && t.rev > 1 && <span title="乐观锁版本">v{t.rev}</span>}
        </span>
      </div>
      <p className={`mt-1 truncate ${status === 'rejected' ? 'text-gray-600' : 'text-gray-400'}`}
        title={t.summary}>
        {t.summary}
      </p>
      {((t.keywords || []).length > 0 || (t.modules || []).length > 0) && (
        <div className="flex gap-1 flex-wrap mt-1">
          {(t.keywords || []).slice(0, 4).map(k => {
            // tag-taxonomy T2：芯片 tooltip 携带域（未分组/未登记只显标签名）
            const dom = tagIdx?.domainOf(k) || '';
            return (
              <span key={k}
                className="px-1.5 py-0.5 rounded bg-surface-3 border border-border text-[10px] text-gray-400"
                title={dom ? `标签 ${k} · 域：${dom}` : k}>
                {k}
              </span>
            );
          })}
          {(t.keywords || []).length > 4 && (
            <span className="text-[10px] text-gray-600">+{t.keywords!.length - 4}</span>
          )}
          {/* T-992：功能模块（FR 锚点派生，拍板②——非自由字段；留空不显示） */}
          {(t.modules || []).map(m => (
            <span key={m} className="px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/30 text-[10px] text-emerald-400"
              title="功能模块：由已确认的话题→FR 关联边派生（FR 模块目录）">
              🏷 {m}
            </span>
          ))}
        </div>
      )}
      {/* T-1014：关联材料（已确认 references 边；点击查看原文快照） */}
      {(t.materials || []).length > 0 && (
        <div className="flex gap-1 flex-wrap mt-1">
          {(t.materials || []).map(m => (
            <button key={m.id}
              onClick={e => { e.stopPropagation(); onOpenMaterial?.(m); }}
              className="px-1.5 py-0.5 rounded bg-sky-500/10 border border-sky-500/30 text-[10px] text-sky-400 hover:bg-sky-500/20"
              title={`关联材料（人工确认）——点击查看原文快照\n${m.file}`}>
              {m.type === 'feishu_doc' ? '📄' : '🎙'} {m.title || m.id}
            </button>
          ))}
        </div>
      )}
      {(t.last_edited_by?.name || t.author?.name) && (
        <div className="text-[10px] text-gray-600 mt-1">
          {t.author?.name ? `创建：${t.author.name}` : ''}
          {t.last_edited_by?.name ? ` · 最后编辑：${t.last_edited_by.name}` : ''}
        </div>
      )}
      {err && <div className="text-[10px] text-red-400 mt-1">{err}</div>}
      {onLocate && (
        <div className="flex items-center gap-2 mt-1 text-[10px]">
          <button className={`${selected ? 'text-info underline' : 'text-info hover:underline'}`}
            onClick={onLocate}
            title={selected ? '取消定位（时间轴高亮与滚动定位解除）'
              : '在时间轴中高亮并滚动到本话题关联的原文消息'}>
            ⌖ {selected ? '取消定位' : '定位原文'}
          </button>
        </div>
      )}
      {!draft && (
        <div className="flex items-center gap-2 mt-1 text-[10px]">
          {onEdit && (
            <button className="text-info hover:underline" onClick={onEdit}
              title="弹框编辑：左原文右话题并排，可修正 AI 关联错的原文">
              编辑
            </button>
          )}
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
