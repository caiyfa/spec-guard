// TagRegistryModal.tsx — 标签词表管理（tag-taxonomy：标签爆炸收口的人工闸门）。
// 待收录区（pending：LLM/人工新词自动登记）→ 收录 / 归并到主标签 / 丢弃；
// 已收录区（active）→ 别名展示 + 设域（一级域，标签栏分组依据；可新建域）。
// 操作即时写 _tags.yaml（人工动作落 _tags_history.jsonl），成功后 onChanged
// 由父层重拉词表。卡片上已落的原始关键词不改写——展示层按别名归一。

import { useEffect, useState } from 'react';
import { feishuPoolApi, type FeishuTagRegistry } from '../api';

export default function TagRegistryModal({ registry, onClose, onChanged }: {
  registry: FeishuTagRegistry | null;
  onClose: () => void;
  onChanged: () => void;                // 任一操作成功 → 父层重拉词表
}) {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState('');
  const [filter, setFilter] = useState('');
  const [mergeTo, setMergeTo] = useState<Record<string, string>>({});

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  const tags = registry?.tags || {};
  const domains = Object.keys(registry?.domains || {}).sort();
  const q = filter.trim().toLowerCase();
  const matchQ = (name: string, aliases: string[]) =>
    !q || name.toLowerCase().includes(q)
    || aliases.some(a => a.toLowerCase().includes(q));

  const pending = Object.entries(tags)
    .filter(([, e]) => e.status === 'pending')
    .filter(([n, e]) => matchQ(n, e.aliases || []))
    .sort((a, b) => a[0].localeCompare(b[0]));
  const active = Object.entries(tags)
    .filter(([, e]) => e.status === 'active')
    .filter(([n, e]) => matchQ(n, e.aliases || []))
    .sort((a, b) => (a[1].domain || '￿').localeCompare(b[1].domain || '￿')
      || a[0].localeCompare(b[0]));
  const activeNames = Object.keys(tags)
    .filter(n => tags[n].status === 'active').sort();

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setErr('');
    try { await fn(); onChanged(); }
    catch (e: any) { setErr(e.message || '操作失败'); }
    finally { setBusy(''); }
  };

  const input = 'bg-surface-3 border border-border rounded px-1.5 py-0.5 text-fs-body text-gray-200 outline-none focus:border-info';
  const act = 'px-1.5 py-0.5 rounded border border-border text-fs-aux text-gray-400 hover:border-gray-500 disabled:opacity-40 shrink-0';

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8"
      onClick={onClose}>
      <div className="w-[720px] max-w-[94vw] border border-border rounded-lg p-4 bg-surface-2"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-fs-body font-semibold">标签词表管理</span>
          <span className="text-fs-aux text-gray-600">
            待收录 {Object.values(tags).filter(t => t.status === 'pending').length} ·
            已收录 {activeNames.length} · 域 {domains.length}
          </span>
          <input className={`${input} ml-auto w-44`} value={filter}
            placeholder="过滤标签/别名…"
            onChange={e => setFilter(e.target.value)} />
          <button className="text-gray-500 hover:text-gray-300" onClick={onClose}>✕</button>
        </div>
        <div className="text-fs-aux text-gray-600 mb-2">
          词表作用于后续 AI 分类（prompt 复用清单）与标签栏归并展示；话题卡上已落的原始关键词不改写。
        </div>
        {err && <div className="mb-2 px-3 py-2 rounded bg-fail/12 text-fail text-fs-body">{err}</div>}
        {!registry ? (
          <div className="text-fs-body text-gray-500 text-center py-6">词表加载失败——关闭后重试</div>
        ) : Object.keys(tags).length === 0 ? (
          <div className="text-fs-body text-gray-500 text-center py-6">
            词表为空——AI 分类产生的新词会自动进入待收录区
          </div>
        ) : (
          <>
            {/* 待收录区：新词闸门（收录转正 / 归并为别名 / 丢弃噪音） */}
            <div className="text-fs-body text-gray-400 mb-1">
              待收录（pending，{pending.length}）
            </div>
            <div className="max-h-48 overflow-auto border border-border rounded bg-surface-3/40 p-1.5 mb-3">
              {pending.length === 0 ? (
                <div className="text-fs-body text-gray-600 px-1 py-1">无待收录词</div>
              ) : pending.map(([name]) => (
                <div key={name} className="flex items-center gap-1.5 px-1 py-1">
                  <span className="text-fs-body text-gray-300 min-w-0 truncate">{name}</span>
                  <span className="ml-auto flex items-center gap-1 shrink-0">
                    <button className={act} disabled={busy === name}
                      title="收录为正式标签（进入 prompt 复用清单）"
                      onClick={() => run(name, () => feishuPoolApi.promoteTag(name))}>
                      收录
                    </button>
                    <input className={`${input} w-32`} list="tag-active-names"
                      placeholder="归并到主标签…"
                      value={mergeTo[name] || ''}
                      onChange={e => setMergeTo(prev => ({ ...prev, [name]: e.target.value }))} />
                    <button className={act}
                      disabled={busy === name || !(mergeTo[name] || '').trim()}
                      title="该词变为主标签的别名（历史与存量话题卡按别名归一展示）"
                      onClick={() => run(name, () =>
                        feishuPoolApi.mergeTag(name, (mergeTo[name] || '').trim()))}>
                      归并
                    </button>
                    <button className={`${act} hover:text-fail`} disabled={busy === name}
                      title="丢弃噪音词（话题卡原词保留，词表不再跟踪）"
                      onClick={() => run(name, () => feishuPoolApi.dropTag(name))}>
                      丢弃
                    </button>
                  </span>
                </div>
              ))}
            </div>
            {/* 已收录区：别名展示 + 设域（datalist 可输新域名，失焦/回车提交） */}
            <div className="text-fs-body text-gray-400 mb-1">
              已收录（active，{active.length}）
            </div>
            <div className="max-h-64 overflow-auto border border-border rounded bg-surface-3/40 p-1.5">
              {active.length === 0 ? (
                <div className="text-fs-body text-gray-600 px-1 py-1">无已收录标签</div>
              ) : active.map(([name, e]) => (
                <div key={name} className="flex items-center gap-1.5 px-1 py-1">
                  <span className="text-fs-body text-gray-200 shrink-0">{name}</span>
                  {(e.aliases || []).length > 0 && (
                    <span className="text-fs-aux text-gray-600 truncate"
                      title={`别名：${(e.aliases || []).join('、')}`}>
                      ← {(e.aliases || []).join('、')}
                    </span>
                  )}
                  <span className="ml-auto flex items-center gap-1 shrink-0">
                    <input className={`${input} w-28`} list="tag-domain-names"
                      key={`${name}:${e.domain}`}
                      defaultValue={e.domain || ''}
                      placeholder="域（未分组）"
                      title="一级域：标签栏按域分组；输入新域名即建档，清空=未分组，回车/失焦生效"
                      onKeyDown={ev => { if (ev.key === 'Enter') (ev.target as HTMLInputElement).blur(); }}
                      onBlur={ev => {
                        const v = ev.target.value.trim();
                        if (v !== (e.domain || '')) {
                          run(`d:${name}`, () => feishuPoolApi.setTagDomain(name, v));
                        }
                      }} />
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
        {/* datalist 数据源 */}
        <datalist id="tag-active-names">
          {activeNames.map(n => <option key={n} value={n} />)}
        </datalist>
        <datalist id="tag-domain-names">
          {domains.map(d => <option key={d} value={d} />)}
        </datalist>
      </div>
    </div>
  );
}
