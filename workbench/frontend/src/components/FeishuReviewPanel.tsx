// 飞书关联复核面板（飞书知识图谱一期 T-915）：
// LLM 候选边（依据+置信度）→ 人批量复核 → 共享区事实源 → 图谱派生。
// 同步范围即授权范围（watch 配置 = 显式授权载体）。

import { useCallback, useEffect, useMemo, useState } from 'react';
import { feishuPoolApi, type FeishuReviewItem } from '../api';
import FeishuWatchSettings from './FeishuWatchSettings';

const TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  'fd:': { label: '文档', cls: 'bg-sky-500/15 text-sky-400' },
  'fm:': { label: '妙记', cls: 'bg-violet-500/15 text-violet-400' },
  'tp:': { label: '话题', cls: 'bg-warn/12 text-warn' },
};

function badgeOf(src: string) {
  const key = Object.keys(TYPE_BADGE).find(k => src.startsWith(k));
  return key ? TYPE_BADGE[key] : { label: '材料', cls: 'bg-gray-500/15 text-gray-400' };
}

function confColor(c: number) {
  if (c >= 0.8) return 'bg-pass';
  if (c >= 0.6) return 'bg-warn';
  return 'bg-gray-500';
}

export default function FeishuReviewPanel() {
  const [items, setItems] = useState<FeishuReviewItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [threshold, setThreshold] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  // T-991：复核队列范围（mine=我的私有队列默认 / shared=共享队列——多人协作
  // 互相复核；体验基线①持久化，进入恢复上次选择）
  const [scope, setScope] = useState<'mine' | 'shared'>(() => {
    try {
      return localStorage.getItem('sg-review-scope') === 'shared' ? 'shared' : 'mine';
    } catch { return 'mine'; }
  });
  // T-927：确认后可选入包（默认不勾，人拍板不绕闸门）
  const [ivPrompt, setIvPrompt] = useState<{ iv_id: string; title: string }[]>([]);
  const [ivChecked, setIvChecked] = useState<Set<string>>(new Set());

  const keyOf = (it: FeishuReviewItem) => `${it.src}||${it.dst}`;

  useEffect(() => {
    try { localStorage.setItem('sg-review-scope', scope); } catch { /* 忽略 */ }
  }, [scope]);

  const load = useCallback(async () => {
    try {
      const { items } = await feishuPoolApi.reviewQueue(scope);
      setItems(items);
      setSelected(new Set());
    } catch (e: any) { setError(e.message); }
  }, [scope]);

  useEffect(() => { setError(''); void load(); }, [load]);

  const visible = useMemo(
    () => items.filter(i => i.status === 'pending' && i.confidence >= threshold),
    [items, threshold]);

  const selectable = visible.filter(i => i.valid);
  const allChecked = selectable.length > 0
    && selectable.every(i => selected.has(keyOf(i)));

  const toggleAll = () => {
    setSelected(allChecked
      ? new Set()
      : new Set(selectable.map(keyOf)));
  };

  const toggleOne = (k: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k); else next.add(k);
      return next;
    });
  };

  const pairsOf = (set: Set<string>): [string, string][] =>
    [...set].map(k => k.split('||') as [string, string]);

  const handleSync = async () => {
    setBusy('sync'); setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.syncNow();
      setNotice(`同步完成：文档 ${r.docs} / 妙记 ${r.minutes} / 群聊 ${r.chats}`
        + (r.errors.length ? `；${r.errors.length} 条失败（诚实呈现）` : ''));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const handleTranscribe = async () => {
    setBusy('transcribe'); setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.transcribe();
      setNotice(r.status === 'skipped'
        ? `已跳过：${r.reason || '未配置 vision 模型'}`
        : `图片转述完成：${r.done} 成功 / ${r.failed} 失败 / 共 ${r.total}`);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const handleBatch = async (action: 'confirm' | 'reject') => {
    if (selected.size === 0) return;
    setBusy(action); setError(''); setNotice('');
    try {
      const r: { confirmed?: number; rejected?: number; skipped: number } =
        action === 'confirm'
          ? await feishuPoolApi.confirm(pairsOf(selected), scope)
          : await feishuPoolApi.reject(pairsOf(selected), scope);
      const n = action === 'confirm' ? (r.confirmed ?? 0) : (r.rejected ?? 0);
      setNotice(`${action === 'confirm' ? '确认' : '拒绝'} ${n} 条`
        + (r.skipped ? `，跳过 ${r.skipped} 条（invalid/不存在）` : '')
        + (action === 'confirm' ? '，已提升共享区等待图谱重建' : '，已留痕防重复建议'));
      // T-927：确认成功且有关联面试 → 弹层询问可选入包
      if (action === 'confirm' && (r as any).suggest_ivs?.length) {
        setIvPrompt((r as any).suggest_ivs);
        setIvChecked(new Set());
      }
      await load();
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const card = 'bg-surface-2 border border-border rounded-lg p-4 mb-4';
  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const th = 'text-left text-fs-body text-gray-500 font-normal px-2 py-1 border-b border-border';
  const td = 'px-2 py-1.5 text-fs-body text-gray-300 border-b border-border/50 align-top';

  return (
    <div className={card}>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-fs-lead font-semibold">🔗 关联复核（飞书材料 → FR）</h2>
        <div className="flex items-center gap-2">
          {/* T-991：队列范围切换（默认我的；共享=多人协作互相复核建边建议） */}
          <select className="bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-300 outline-none focus:border-info"
            value={scope}
            onChange={e => setScope(e.target.value as 'mine' | 'shared')}
            title="我的=仅本人同步产生的建议（默认）；共享=工作区共享队列（多人协作可互相复核）">
            <option value="mine">我的队列</option>
            <option value="shared">共享队列</option>
          </select>
          <button className={btn} onClick={handleSync} disabled={busy === 'sync'}>
            {busy === 'sync' ? '同步中…' : '立即同步'}
          </button>
          <button className={btn} onClick={handleTranscribe} disabled={busy === 'transcribe'}>
            {busy === 'transcribe' ? '转述中…' : '🖼 转述图片'}
          </button>
          <FeishuWatchSettings />
        </div>
      </div>
      {error && <div className="mb-2 px-3 py-2 rounded bg-fail/12 text-fail text-fs-body">{error}</div>}
      {notice && <div className="mb-2 px-3 py-2 rounded bg-pass/12 text-pass text-fs-body">{notice}</div>}

      <div className="flex items-center gap-3 mb-2 text-fs-body text-gray-500">
        <span>置信度过滤：</span>
        {[{ v: 0, l: '全部' }, { v: 0.6, l: '≥60%' }, { v: 0.8, l: '≥80%' }].map(o => (
          <button key={o.v}
            className={`px-2 py-0.5 rounded ${threshold === o.v ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-400'}`}
            onClick={() => setThreshold(o.v)}>{o.l}</button>
        ))}
        <span className="ml-auto">待复核 {visible.length} 条 · 已选 {selected.size} 条</span>
        <button className={btn} onClick={toggleAll} disabled={selectable.length === 0}>
          {allChecked ? '取消全选' : '全选可见'}
        </button>
        <button className={btn} disabled={selected.size === 0 || busy !== ''}
          onClick={() => handleBatch('confirm')}>批量确认</button>
        <button className={`${btn} !bg-fail/15 !text-fail hover:!bg-fail/25`}
          disabled={selected.size === 0 || busy !== ''}
          onClick={() => handleBatch('reject')}>批量拒绝</button>
      </div>

      {visible.length === 0 ? (
        <div className="text-fs-body text-gray-500">
          暂无待复核建议——先「同步设置」配置授权范围并「立即同步」，LLM 建边建议将出现在这里
        </div>
      ) : (
        <table className="w-full">
          <thead>
            <tr>
              <th className={th}></th><th className={th}>来源</th><th className={th}>建议 FR</th>
              <th className={th}>置信度</th><th className={th}>依据（原文摘录）</th>
            </tr>
          </thead>
          <tbody>
            {visible.map(it => {
              const k = keyOf(it);
              const badge = badgeOf(it.src);
              return (
                <tr key={k} className={it.valid ? '' : 'opacity-60'}>
                  <td className={td}>
                    <input type="checkbox" disabled={!it.valid}
                      checked={selected.has(k)} onChange={() => toggleOne(k)} />
                  </td>
                  <td className={td}>
                    <span className={`inline-block px-1.5 py-0.5 rounded text-fs-aux mr-1.5 ${badge.cls}`}>
                      {badge.label}
                    </span>
                    <code className="text-fs-body">{it.src}</code>
                  </td>
                  <td className={td}><code className="text-fs-body">{it.dst}</code></td>
                  <td className={td}>
                    <div className="flex items-center gap-1.5">
                      <div className="w-14 h-1.5 rounded bg-surface-3 overflow-hidden">
                        <div className={`h-full ${confColor(it.confidence)}`}
                          style={{ width: `${Math.round(it.confidence * 100)}%` }} />
                      </div>
                      <span className="text-fs-body text-gray-400">
                        {Math.round(it.confidence * 100)}%
                      </span>
                    </div>
                  </td>
                  <td className={td}>
                    <span className={it.valid ? 'text-gray-300' : 'text-fail'}>
                      {it.evidence || '（无依据）'}
                    </span>
                    {!it.valid && (
                      <span className="ml-1 text-fs-aux text-fail">invalid·不可确认</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* T-927：确认后可选入包弹层（默认不勾，人拍板不绕闸门） */}
      {ivPrompt.length > 0 && (
        <div className="mb-3 border border-info/40 rounded-lg p-3 bg-info/5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-fs-body font-semibold text-info">同时入包以下面试信息包？（默认不入包）</h3>
            <button className="text-gray-500 hover:text-gray-300 text-fs-body" onClick={() => setIvPrompt([])}>✕</button>
          </div>
          <div className="space-y-1 mb-2">
            {ivPrompt.map(iv => (
              <label key={iv.iv_id} className="flex items-center gap-2 text-fs-body text-gray-300">
                <input type="checkbox"
                  checked={ivChecked.has(iv.iv_id)}
                  onChange={() => setIvChecked(prev => {
                    const next = new Set(prev);
                    if (next.has(iv.iv_id)) next.delete(iv.iv_id); else next.add(iv.iv_id);
                    return next;
                  })} />
                <span>{iv.iv_id} · {iv.title}</span>
              </label>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <button className={btn} disabled={ivChecked.size === 0}
              onClick={() => {
                setNotice(`已记录入包意向（${ivChecked.size} 个面试）——请在材料管理页完成入包动作（飞书材料登记为 MAT 后可入包）`);
                setIvPrompt([]);
              }}>确认入包意向</button>
            <button className={btn} onClick={() => setIvPrompt([])}>跳过</button>
          </div>
          <div className="mt-1.5 text-fs-aux text-gray-500">
            入包走 M03 原有人拍板端点；飞书材料需先在材料管理登记为 MAT 后才可入包
          </div>
        </div>
      )}
    </div>
  );
}
