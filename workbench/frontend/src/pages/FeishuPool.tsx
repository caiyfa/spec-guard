// 飞书材料池总览页（飞书知识图谱三期 T-929）：
// 状态卡条（watcher 运行/事件数/最近事件）+ 三页签：
// ① 材料池清单 ② 话题清单（候选/已确认/演进链） ③ 图片替身（pending/failed + caption 手改）

import { useCallback, useEffect, useState } from 'react';
import {
  feishuPoolApi,
  type FeishuPoolMaterial,
  type FeishuTopic,
} from '../api';
import FeishuWatchSettings from '../components/FeishuWatchSettings';

type Tab = 'materials' | 'topics' | 'images';

const TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  feishu_doc: { label: '文档', cls: 'bg-sky-500/15 text-sky-400' },
  feishu_minutes: { label: '妙记', cls: 'bg-violet-500/15 text-violet-400' },
  chat: { label: '群聊', cls: 'bg-amber-500/15 text-amber-400' },
};

function fmtTime(ts: number) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
}

export default function FeishuPool() {
  const [tab, setTab] = useState<Tab>('materials');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [watcher, setWatcher] = useState<any>(null);
  const [materials, setMaterials] = useState<FeishuPoolMaterial[]>([]);
  const [topics, setTopics] = useState<{ candidates: FeishuTopic[]; confirmed: FeishuTopic[] }>({ candidates: [], confirmed: [] });
  const [captionEdit, setCaptionEdit] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');

  const loadWatcher = useCallback(() => {
    feishuPoolApi.watcherStatus().then(setWatcher).catch(e => setError(String(e?.message || e)));
  }, []);
  const loadMaterials = useCallback(() => {
    feishuPoolApi.poolMaterials().then(r => setMaterials(r.items)).catch(e => setError(String(e?.message || e)));
  }, []);
  const loadTopics = useCallback(() => {
    feishuPoolApi.poolTopics().then(setTopics).catch(e => setError(String(e?.message || e)));
  }, []);

  useEffect(() => { loadWatcher(); loadMaterials(); loadTopics(); },
    [loadWatcher, loadMaterials, loadTopics]);

  const saveCaption = async (material: string, placeholder: string) => {
    const key = `${material}||${placeholder}`;
    const caption = (captionEdit[key] || '').trim();
    if (!caption) return;
    setBusy(key); setError(''); setNotice('');
    try {
      await feishuPoolApi.updateCaption(material, placeholder, caption);
      setNotice(`已保存 ${material} ${placeholder} 的替身文本（manual）`);
      setCaptionEdit(prev => ({ ...prev, [key]: '' }));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const syncNow = async () => {
    setBusy('sync'); setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.syncNow();
      setNotice(`同步完成：文档 ${r.docs} / 妙记 ${r.minutes} / 群聊 ${r.chats}`
        + (r.errors.length ? `；${r.errors.length} 条失败（诚实呈现）` : ''));
      loadMaterials(); loadTopics();
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const card = 'bg-surface-2 border border-border rounded-lg p-4 mb-4';
  const btn = 'px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const th = 'text-left text-[11px] text-gray-500 font-normal px-2 py-1 border-b border-border';
  const td = 'px-2 py-1.5 text-xs text-gray-300 border-b border-border/50 align-top';
  const tabBtn = (id: Tab, label: string) => (
    <button key={id} onClick={() => setTab(id)}
      className={`px-3 py-1.5 rounded text-xs ${tab === id ? 'bg-info/15 text-info font-medium' : 'text-gray-400 hover:text-gray-200'}`}>
      {label}
    </button>
  );

  // 图片页签数据：含 imgmap 的材料（pending/failed 替身条目的编辑入口）
  const imgMaterials = materials.filter(m => m.type !== 'chat');

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-base font-bold">🪺 飞书材料池</h1>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-500">为 agent 对话提供背景信息源 · 复核建边在「材料管理」页</span>
          <button className={btn} onClick={syncNow} disabled={busy === 'sync'}>
            {busy === 'sync' ? '同步中…' : '⇩ 立即同步'}
          </button>
          <FeishuWatchSettings onSaved={loadWatcher} />
        </div>
      </div>

      {/* 状态卡条 */}
      <div className={`${card} flex items-center gap-4 text-xs`}>
        {watcher?.running ? (
          <>
            <span className="text-green-400">● 监听运行中（{watcher.count} 用户）</span>
            {watcher.watchers.map((w: any) => (
              <span key={w.emp} className="text-gray-400">
                {w.emp} · 事件 {w.events_received} · 最近 {w.last_event_at || '—'}
              </span>
            ))}
          </>
        ) : (
          <span className="text-gray-500">○ 监听未启动（配置同步范围后自动拉起）</span>
        )}
        <span className="ml-auto text-gray-500">材料 {materials.length} · 候选话题 {topics.candidates.length} · 已确认话题 {topics.confirmed.length}</span>
      </div>

      {error && <div className="mb-3 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
      {notice && <div className="mb-3 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}

      <div className="flex items-center gap-1.5 mb-3 border-b border-border pb-2">
        {tabBtn('materials', `📦 材料池（${materials.length}）`)}
        {tabBtn('topics', `💬 话题（${topics.candidates.length + topics.confirmed.length}）`)}
        {tabBtn('images', '🖼 图片替身')}
      </div>

      {/* 页签 1：材料池清单 */}
      {tab === 'materials' && (
        <div className={card}>
          {materials.length === 0 ? (
            <div className="text-xs text-gray-500">材料池为空——点右上「⚙ 同步设置」配置授权范围（群聊/用户/文档）后「⇩ 立即同步」</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr><th className={th}>类型</th><th className={th}>标题 / 摘要</th><th className={th}>大小</th><th className={th}>更新时间</th></tr>
              </thead>
              <tbody>
                {materials.map(m => (
                  <tr key={m.id}>
                    <td className={td}>
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${TYPE_BADGE[m.type]?.cls || ''}`}>
                        {TYPE_BADGE[m.type]?.label || m.type}
                      </span>
                    </td>
                    <td className={td}>
                      <div className="text-gray-200">{m.title || m.id}</div>
                      {m.summary && <div className="text-[11px] text-gray-500 truncate max-w-[420px]">{m.summary}</div>}
                      <div className="text-[10px] text-gray-600">{m.id} · {m.sha}</div>
                    </td>
                    <td className={td}>{(m.size / 1024).toFixed(1)} KB</td>
                    <td className={td}>{fmtTime(m.mtime)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* 页签 2：话题清单 */}
      {tab === 'topics' && (
        <div className={card}>
          <h2 className="text-sm font-semibold mb-2">候选话题（待复核关联，{topics.candidates.length}）</h2>
          {topics.candidates.length === 0 && <div className="text-xs text-gray-500 mb-3">暂无</div>}
          <div className="space-y-2 mb-4">
            {topics.candidates.map(t => (
              <div key={t.id} className="p-2 rounded border border-border bg-surface-3 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-gray-200 font-medium">{t.title}</span>
                  <code className="text-[10px] text-gray-500">{t.id}</code>
                  {t.continues && <span className="text-[10px] text-amber-400">⤺ 延续 {t.continues}</span>}
                  <span className="ml-auto text-[10px] text-gray-500">{t.message_count} 条 · {t.participants_count} 人</span>
                </div>
                <p className="text-gray-400 mt-1">{t.summary}</p>
              </div>
            ))}
          </div>
          <h2 className="text-sm font-semibold mb-2">已确认话题（已入共享图谱，{topics.confirmed.length}）</h2>
          {topics.confirmed.length === 0 && <div className="text-xs text-gray-500">暂无</div>}
          <div className="space-y-2">
            {topics.confirmed.map(t => (
              <div key={t.id} className="p-2 rounded border border-green-500/30 bg-green-900/10 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-gray-200 font-medium">{t.title}</span>
                  <code className="text-[10px] text-gray-500">{t.id}</code>
                  {t.continues && <span className="text-[10px] text-amber-400">⤺ 延续 {t.continues}</span>}
                </div>
                <p className="text-gray-400 mt-1">{t.summary}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 页签 3：图片替身补写 */}
      {tab === 'images' && (
        <div className={card}>
          <h2 className="text-sm font-semibold mb-2">图片替身文本（人工补写兜底）</h2>
          <div className="text-[11px] text-gray-500 mb-3">
            输入材料 stem（如 fd-tokA）与占位符（如 图片#1）补写替身文本；新入池图片由 watcher 异步自动转述，存量手动转述在「材料管理 → 🖼 转述图片」
          </div>
          <CaptionEditor busy={busy} captionEdit={captionEdit}
            setCaptionEdit={setCaptionEdit} onSave={saveCaption}
            materials={imgMaterials} />
        </div>
      )}
    </div>
  );
}

function CaptionEditor({ busy, captionEdit, setCaptionEdit, onSave, materials }: {
  busy: string;
  captionEdit: Record<string, string>;
  setCaptionEdit: (fn: (p: Record<string, string>) => Record<string, string>) => void;
  onSave: (material: string, placeholder: string) => void;
  materials: FeishuPoolMaterial[];
}) {
  const [material, setMaterial] = useState('');
  const [placeholder, setPlaceholder] = useState('');
  const key = `${material}||${placeholder}`;
  const input = 'bg-surface-3 border border-border rounded px-2 py-1.5 text-xs text-gray-200 outline-none focus:border-info';
  return (
    <div className="flex items-end gap-2 flex-wrap">
      <div>
        <div className="text-[11px] text-gray-500 mb-1">材料 stem</div>
        <select className={input} value={material} onChange={e => setMaterial(e.target.value)}>
          <option value="">— 选择 —</option>
          {materials.map(m => (
            <option key={m.id} value={m.file.replace(/\.(md|json)$/, '')}>{m.file}</option>
          ))}
        </select>
      </div>
      <div>
        <div className="text-[11px] text-gray-500 mb-1">占位符</div>
        <input className={`${input} w-28`} value={placeholder} placeholder="图片#1"
          onChange={e => setPlaceholder(e.target.value)} />
      </div>
      <div className="flex-1 min-w-60">
        <div className="text-[11px] text-gray-500 mb-1">替身文本（≤60 字业务描述）</div>
        <input className={`${input} w-full`} value={captionEdit[key] || ''}
          placeholder="架构图：AgentChat → 图谱服务 → SQLite……"
          onChange={e => setCaptionEdit(prev => ({ ...prev, [key]: e.target.value }))} />
      </div>
      <button
        className="px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40"
        disabled={!material || !placeholder || !(captionEdit[key] || '').trim() || busy === key}
        onClick={() => onSave(material, placeholder)}>
        {busy === key ? '保存中…' : '保存替身'}
      </button>
    </div>
  );
}
