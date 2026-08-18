// 飞书材料池总览页（飞书知识图谱三期 T-929；T-939 体验重构）：
// 状态卡条（watcher 运行/事件数/最近事件）+ 三页签：
// ① 材料池清单（点击行看原文，图片内嵌直出）
// ② 话题清单（候选/已确认/演进链）
// ③ 图片描述（按材料分组：缩略图 + 转述状态 + 描述编辑；T-939 重构，
//    替代旧「图片替身」手输 stem/占位符编辑器）

import { useCallback, useEffect, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  feishuPoolApi,
  type FeishuPoolMaterial,
  type FeishuTopic,
  type FeishuMaterialContent,
  type FeishuWatch,
} from '../api';
import FeishuWatchSettings from '../components/FeishuWatchSettings';

type Tab = 'materials' | 'topics' | 'images';

const TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  feishu_doc: { label: '文档', cls: 'bg-sky-500/15 text-sky-400' },
  feishu_minutes: { label: '妙记', cls: 'bg-violet-500/15 text-violet-400' },
  chat: { label: '群聊', cls: 'bg-amber-500/15 text-amber-400' },
};

const IMG_STATUS: Record<string, { label: string; cls: string }> = {
  pending: { label: '待转述', cls: 'bg-amber-500/15 text-amber-400' },
  done: { label: '已转述', cls: 'bg-green-500/15 text-green-400' },
  failed: { label: '转述失败', cls: 'bg-red-500/15 text-red-400' },
};

const SCOPE_LABEL: Record<string, string> = {
  group_sender: '群消息', minutes: '妙记', docs: '文档',
};

function fmtTime(ts: number) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false });
}

// 材料 file（docs/fd-tokA.md）→ 配套 imgmap 路径（docs/fd-tokA.imgmap.json）
function imgmapOfFile(file: string) {
  return file.replace(/\.md$/, '').replace(/\.json$/, '') + '.imgmap.json';
}

// 图片字节并发拉取（Authorization header 不能走 <img src>，fetch blob → objectURL）
async function loadImages(file: string, images: { placeholder: string; media_key?: string }[]) {
  const urls: Record<string, string> = {};
  await Promise.all(images.filter(i => i.media_key).map(async i => {
    try {
      const blob = await feishuPoolApi.fetchMaterialImageBlob(imgmapOfFile(file), i.placeholder);
      urls[i.placeholder] = URL.createObjectURL(blob);
    } catch { /* 单图失败保留占位符，不阻断整体 */ }
  }));
  return urls;
}

// [图片#N] → 内嵌 markdown 图片（有 objectURL）或失败标注
function inlineImages(content: string, imgUrls: Record<string, string>) {
  return content.replace(/\[(图片#\d+)\]/g, (_m, ph: string) =>
    imgUrls[ph] ? `![${ph}](${imgUrls[ph]})` : `*（${ph} 图片暂不可见）*`);
}

export default function FeishuPool() {
  const [tab, setTab] = useState<Tab>('materials');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [watcher, setWatcher] = useState<any>(null);
  const [watchCfg, setWatchCfg] = useState<FeishuWatch | null>(null);
  const [ownerFilter, setOwnerFilter] = useState('');
  const [materials, setMaterials] = useState<FeishuPoolMaterial[]>([]);
  const [topics, setTopics] = useState<{ candidates: FeishuTopic[]; confirmed: FeishuTopic[] }>({ candidates: [], confirmed: [] });
  const [detail, setDetail] = useState<{ m: FeishuPoolMaterial; data: FeishuMaterialContent | null; imgUrls: Record<string, string> } | null>(null);
  const [busy, setBusy] = useState('');

  const loadWatcher = useCallback(() => {
    feishuPoolApi.watcherStatus().then(setWatcher).catch(e => setError(String(e?.message || e)));
    feishuPoolApi.getWatch().then(setWatchCfg)   // T-940：监听范围卡数据源
      .catch(e => setError(String(e?.message || e)));
  }, []);
  const loadMaterials = useCallback(() => {
    feishuPoolApi.poolMaterials().then(r => setMaterials(r.items)).catch(e => setError(String(e?.message || e)));
  }, []);
  const loadTopics = useCallback(() => {
    feishuPoolApi.poolTopics().then(setTopics).catch(e => setError(String(e?.message || e)));
  }, []);

  useEffect(() => { loadWatcher(); loadMaterials(); loadTopics(); },
    [loadWatcher, loadMaterials, loadTopics]);

  const openDetail = async (m: FeishuPoolMaterial) => {
    setError('');
    setDetail({ m, data: null, imgUrls: {} });
    try {
      const d = await feishuPoolApi.materialContent(m.file);
      if (!d.ok) throw new Error(d.error || '材料读取失败');
      const urls = await loadImages(m.file, d.images || []);
      setDetail({ m, data: d, imgUrls: urls });
    } catch (e: any) { setError(e.message); setDetail(null); }
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

  // 材料按监听用户筛选（T-940）：产出物归人（docs/minutes 带 owner meta），
  // 群聊不归人——选具体用户时只显示该用户产出；再点一次取消筛选。
  const watchUsers = watchCfg?.users || [];
  const filteredMaterials = ownerFilter
    ? materials.filter(m => m.type !== 'chat' && m.owner_open_id === ownerFilter)
    : materials;

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

      {/* 监听范围卡（T-940）：监听用户/授权群/文档一目了然 + 就近维护入口 */}
      <div className={card + ' text-xs'}>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-gray-500">监听范围</span>
          <span className="text-gray-600">（同步范围即授权范围）</span>
          <span className="ml-auto">
            <FeishuWatchSettings onSaved={() => { loadWatcher(); loadMaterials(); }} />
          </span>
        </div>
        {watchCfg ? (
          <div className="space-y-1.5">
            <div className="flex items-start gap-2 flex-wrap">
              <span className="text-gray-500 shrink-0 mt-0.5">监听用户</span>
              {watchUsers.length === 0
                ? <span className="text-gray-600">无（点右上「⚙ 同步设置」添加）</span>
                : watchUsers.map(u => (
                  <button key={u.open_id}
                    onClick={() => setOwnerFilter(ownerFilter === u.open_id ? '' : u.open_id)}
                    className={'px-2 py-0.5 rounded border text-[11px] '
                      + (ownerFilter === u.open_id
                        ? 'bg-info/20 text-info border-info/40'
                        : 'text-gray-300 border-border hover:border-gray-500')}>
                    {u.name || u.open_id}
                    <span className="ml-1 text-gray-500">
                      {u.scopes.map(s => SCOPE_LABEL[s] || s).join('/') || '无监听项'}
                    </span>
                  </button>
                ))}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-gray-500 shrink-0">授权群聊</span>
              {(watchCfg.chats || []).length === 0
                ? <span className="text-gray-600">无</span>
                : (watchCfg.chats || []).map(c => (
                  <span key={c.chat_id} className="px-2 py-0.5 rounded border border-border text-[11px] text-gray-300">
                    {c.name || c.chat_id}
                  </span>
                ))}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-gray-500 shrink-0">监听文档</span>
              <span className="text-gray-300">{(watchCfg.docs || []).length} 篇</span>
              <span className="text-gray-600">（粘贴链接/按用户检索添加）</span>
            </div>
          </div>
        ) : (
          <div className="text-gray-500">监听配置加载中…</div>
        )}
      </div>

      {error && <div className="mb-3 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
      {notice && <div className="mb-3 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}

      <div className="flex items-center gap-1.5 mb-3 border-b border-border pb-2">
        {tabBtn('materials', `📦 材料池（${materials.length}）`)}
        {tabBtn('topics', `💬 话题（${topics.candidates.length + topics.confirmed.length}）`)}
        {tabBtn('images', '🖼 图片描述')}
      </div>

      {/* 页签 1：材料池清单（监听用户筛选 + 飞书原文直链 + 行点击本地快照） */}
      {tab === 'materials' && (
        <div className={card}>
          {ownerFilter && (
            <div className="mb-2 flex items-center gap-2 text-[11px] text-info">
              ▸ 只看 {(watchUsers.find(u => u.open_id === ownerFilter)?.name) || ownerFilter} 的产出（文档+妙记）
              <button className="text-gray-500 hover:text-gray-300"
                onClick={() => setOwnerFilter('')}>× 取消</button>
            </div>
          )}
          {materials.length === 0 ? (
            <div className="text-xs text-gray-500">材料池为空——点右上「⚙ 同步设置」配置授权范围（群聊/用户/文档）后「⇩ 立即同步」</div>
          ) : filteredMaterials.length === 0 ? (
            <div className="text-xs text-gray-500">该用户暂无产出材料（重新同步后新落盘材料才带归属）</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr><th className={th}>类型</th><th className={th}>标题 / 摘要</th><th className={th}>产出人</th><th className={th}>大小</th><th className={th}>更新时间</th><th className={th}></th></tr>
              </thead>
              <tbody>
                {filteredMaterials.map(m => (
                  <tr key={m.id} className="cursor-pointer hover:bg-surface-3/60" onClick={() => openDetail(m)}>
                    <td className={td}>
                      <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${TYPE_BADGE[m.type]?.cls || ''}`}>
                        {TYPE_BADGE[m.type]?.label || m.type}
                      </span>
                    </td>
                    <td className={td}>
                      <div className="text-gray-200">{m.title || m.id}</div>
                      {m.summary && <div className="text-[11px] text-gray-500 truncate max-w-[360px]">{m.summary}</div>}
                      <div className="text-[10px] text-gray-600">{m.id} · {m.sha}</div>
                    </td>
                    <td className={td}>{m.owner_name || <span className="text-gray-600">—</span>}</td>
                    <td className={td}>{(m.size / 1024).toFixed(1)} KB</td>
                    <td className={td}>{fmtTime(m.mtime)}</td>
                    <td className={td}>
                      <div className="flex items-center gap-2 whitespace-nowrap">
                        {m.source_url && (
                          <a href={m.source_url} target="_blank" rel="noreferrer"
                            onClick={e => e.stopPropagation()}
                            className="text-[11px] text-info hover:underline">飞书原文 ↗</a>
                        )}
                        <span className="text-[11px] text-gray-500">本地快照 →</span>
                      </div>
                    </td>
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

      {/* 页签 3：图片描述（按材料分组卡片流；T-939 重构） */}
      {tab === 'images' && (
        <ImagePanel materials={materials.filter(m => m.type === 'feishu_doc')} />
      )}

      {/* 材料详情弹层（原文 + 图片内嵌） */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8"
          onClick={() => setDetail(null)}>
          <div className="w-[860px] max-w-[94vw] border border-border rounded-lg p-4 bg-surface-2"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold flex items-center gap-2 min-w-0">
                <span className="truncate">{detail.m.title || detail.m.id}</span>
                <span className={`px-1.5 py-0.5 rounded text-[10px] shrink-0 ${TYPE_BADGE[detail.m.type]?.cls}`}>
                  {TYPE_BADGE[detail.m.type]?.label}
                </span>
                {detail.m.source_url && (
                  <a href={detail.m.source_url} target="_blank" rel="noreferrer"
                    className="shrink-0 text-[11px] text-info hover:underline">在飞书打开原始文件 ↗</a>
                )}
              </h3>
              <button className={btn} onClick={() => setDetail(null)}>关闭</button>
            </div>
            {!detail.data ? (
              <div className="py-10 text-center text-xs text-gray-500">原文加载中…</div>
            ) : (
              <>
                <div className="text-xs text-gray-400 prose prose-invert prose-sm max-w-none
                  [&_img]:max-w-full [&_img]:rounded [&_img]:border [&_img]:border-border [&_img]:my-2">
                  <Markdown remarkPlugins={[remarkGfm]}>
                    {inlineImages(detail.data.content, detail.imgUrls)}
                  </Markdown>
                </div>
                {detail.data.type === 'feishu_minutes' && detail.data.raw && (
                  <details className="mt-3">
                    <summary className="text-[11px] text-gray-500 cursor-pointer">原始 JSON</summary>
                    <pre className="mt-2 max-h-64 overflow-auto text-[10px] text-gray-500
                      bg-surface-3 border border-border rounded p-2">{detail.data.raw}</pre>
                  </details>
                )}
                {(detail.data.images || []).some(i => i.caption) && (
                  <div className="mt-3 border-t border-border pt-2 space-y-1">
                    <div className="text-[11px] text-gray-500">图片描述（供 agent 检索用）：</div>
                    {detail.data.images.filter(i => i.caption).map(i => (
                      <div key={i.placeholder} className="text-[11px] text-gray-400">
                        <span className="text-gray-600">{i.placeholder}</span> {i.caption}
                        <span className="ml-1 text-gray-600">（{i.caption_by === 'manual' ? '人工' : 'AI 转述'}）</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// 图片描述面板：材料下拉 → 图片卡片流（缩略图 + 状态 + 描述编辑）
function ImagePanel({ materials }: { materials: FeishuPoolMaterial[] }) {
  const [file, setFile] = useState('');
  const [data, setData] = useState<FeishuMaterialContent | null>(null);
  const [imgUrls, setImgUrls] = useState<Record<string, string>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!file) { setData(null); return; }
    let revoked = false;
    const prev = imgUrls;
    feishuPoolApi.materialContent(file).then(async d => {
      if (!d.ok) throw new Error(d.error);
      const urls = await loadImages(file, d.images || []);
      if (revoked) return;
      setData(d); setImgUrls(urls); setEdits({}); setError('');
    }).catch(e => setError(String(e?.message || e)));
    return () => {
      revoked = true;
      Object.values(prev).forEach(u => URL.revokeObjectURL(u));
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file]);

  const saveCaption = async (placeholder: string) => {
    const caption = (edits[placeholder] || '').trim();
    if (!caption || !data) return;
    const stem = file.replace(/^docs\//, '').replace(/\.imgmap\.json$/, '').replace(/\.md$/, '');
    setBusy(placeholder); setError(''); setNotice('');
    try {
      await feishuPoolApi.updateCaption(stem, placeholder, caption);
      setNotice(`已保存 ${placeholder} 的图片描述`);
      setEdits(prev => ({ ...prev, [placeholder]: '' }));
      const d = await feishuPoolApi.materialContent(file);
      if (d.ok) setData(d);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const btn = 'px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const input = 'bg-surface-3 border border-border rounded px-2 py-1.5 text-xs text-gray-200 outline-none focus:border-info';

  return (
    <div className="bg-surface-2 border border-border rounded-lg p-4 mb-4">
      <h2 className="text-sm font-semibold mb-1">图片描述（AI 自动转述，人工可改）</h2>
      <div className="text-[11px] text-gray-500 mb-3">
        新入池图片由监听自动转述；此页查看各材料图片原文并修订描述（描述供 agent 检索图片内容）
      </div>
      {error && <div className="mb-2 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
      {notice && <div className="mb-2 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}
      {materials.length === 0 ? (
        <div className="text-xs text-gray-500">暂无含图片的文档材料</div>
      ) : (
        <>
          <select className={`${input} mb-3`} value={file} onChange={e => setFile(e.target.value)}>
            <option value="">— 选择材料 —</option>
            {materials.map(m => (
              <option key={m.id} value={m.file}>{m.title || m.id}（{m.file}）</option>
            ))}
          </select>
          {data && (
            <div className="grid grid-cols-1 gap-3">
              {(data.images || []).length === 0 && (
                <div className="text-xs text-gray-500">该材料无图片</div>
              )}
              {data.images.map(img => (
                <div key={img.placeholder} className="flex gap-3 p-2 rounded border border-border bg-surface-3">
                  {imgUrls[img.placeholder] ? (
                    <img src={imgUrls[img.placeholder]} alt={img.placeholder}
                      className="w-40 h-28 object-contain rounded border border-border bg-black/30" />
                  ) : (
                    <div className="w-40 h-28 flex items-center justify-center rounded border border-border
                      bg-black/30 text-[10px] text-gray-600">{img.media_key ? '加载失败' : '无原图'}</div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${IMG_STATUS[img.status || 'pending']?.cls || ''}`}>
                        {IMG_STATUS[img.status || 'pending']?.label || img.status}
                      </span>
                      <span className="text-[10px] text-gray-600">{img.placeholder}</span>
                      {img.caption && (
                        <span className="text-[10px] text-gray-500 truncate">
                          当前：{img.caption}（{img.caption_by === 'manual' ? '人工' : 'AI 转述'}）
                        </span>
                      )}
                      {img.error && <span className="text-[10px] text-red-400" title={img.error}>失败原因 ⓘ</span>}
                    </div>
                    <div className="flex gap-2">
                      <input className={`${input} flex-1`} value={edits[img.placeholder] || ''}
                        placeholder={img.caption ? '修订描述…' : '补写图片描述（≤60 字业务描述）'}
                        onChange={e => setEdits(prev => ({ ...prev, [img.placeholder]: e.target.value }))} />
                      <button className={btn}
                        disabled={!(edits[img.placeholder] || '').trim() || busy === img.placeholder}
                        onClick={() => saveCaption(img.placeholder)}>
                        {busy === img.placeholder ? '保存中…' : '保存'}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
