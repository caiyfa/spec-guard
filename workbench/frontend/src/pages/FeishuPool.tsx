// 飞书话题总览页（原「飞书材料池」，T-1003 总控人拍板改名；飞书知识图谱三期 T-929；T-939 体验重构；T-950 话题工作台重构；
// T-952 体验收敛）：
// 计数条（材料/话题数）+ 两页签（T-1004：监听运行状态/监听范围收进同步设置弹层）：
// ① 话题材料清单（点击行看原文，图片内嵌直出；T-949 perm 徽标）
// ② 话题工作台（人工介入双栏：时间轴×泳道色卡；T-952 富渲染：
//    post 文本+内嵌图 / file 文件卡 / image 图+转述 caption——
//    图片描述维护融入时间轴展示，独立 tab 退役：多模态转述是技术侧
//    实现细节（同步后自动触发），不应作为用户操作面）

import { useCallback, useEffect, useMemo, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  feishuPoolApi,
  type FeishuPoolMaterial,
  type FeishuTopic,
  type CrossChatCandidate,
  type FeishuMaterialContent,
  type FeishuWatch,
  type FeishuChatMessage,
} from '../api';
import FeishuWatchSettings from '../components/FeishuWatchSettings';
import TopicWorkspace from '../components/TopicWorkspace';
import { dedupeTopics } from '../components/topicList';
import { MessageBody, useChatMedia, senderColor } from '../components/ChatMessageView';
import ImageLightbox from '../components/ImageLightbox';

type Tab = 'materials' | 'topics';

const TYPE_BADGE: Record<string, { label: string; cls: string }> = {
  feishu_doc: { label: '文档', cls: 'bg-sky-500/15 text-sky-400' },
  feishu_minutes: { label: '妙记', cls: 'bg-violet-500/15 text-violet-400' },
  chat: { label: '群聊', cls: 'bg-amber-500/15 text-amber-400' },
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

// T-1006：群聊详情消息流（与话题工作台时间轴/编辑弹框同源渲染——
// JSONL 事实源逐条呈现：发送人配色 / 图片真实加载·失败标注·转述 caption /
// 附件下载；单日 isMulti=false 只显 HH:MM）
function ChatDetailView({ rows, sha8, day }: {
  rows: FeishuChatMessage[]; sha8: string; day: string;
}) {
  const { imgUrls, imgFailed, captions } = useChatMedia(rows, sha8, [day]);
  const [previewImg, setPreviewImg] = useState<{ url: string; caption: string } | null>(null);
  return (
    <div className="space-y-0.5">
      {rows.map((m, i) => (
        <div key={`${m.message_id}-${i}`}
          className="text-[11px] leading-relaxed px-1.5 py-1 rounded hover:bg-black/20">
          <div className="flex items-baseline gap-1.5 text-gray-500">
            <span className="font-medium"
              style={{ color: senderColor(m.sender_id || m.sender_name || '') }}>
              {m.sender_name || m.sender_id || '?'}
            </span>
            <span className="text-[10px] text-gray-600">{(m.ts || '').slice(11, 16)}</span>
          </div>
          <div className="text-gray-300">
            <MessageBody msg={m} imgUrls={imgUrls} imgFailed={imgFailed}
              captions={captions} highlight={false}
              onImageClick={(url, caption) => setPreviewImg({ url, caption })} />
          </div>
        </div>
      ))}
      {previewImg && (
        <ImageLightbox url={previewImg.url} caption={previewImg.caption}
          onClose={() => setPreviewImg(null)} />
      )}
    </div>
  );
}


export default function FeishuPool() {
  // T-953：页签持久化（恢复上次所在页；T-1005：默认/非法值回退话题页——
  // 话题是主工作面，材料池为话题服务）
  const [tab, setTab] = useState<Tab>(() => {
    try {
      const saved = localStorage.getItem('sg-feishu-tab');
      return saved === 'materials' ? 'materials' : 'topics';
    } catch { return 'topics'; }
  });
  useEffect(() => {
    try { localStorage.setItem('sg-feishu-tab', tab); } catch { /* 跳过 */ }
  }, [tab]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [watchCfg, setWatchCfg] = useState<FeishuWatch | null>(null);
  const [ownerFilter, setOwnerFilter] = useState('');
  const [materials, setMaterials] = useState<FeishuPoolMaterial[]>([]);
  const [topics, setTopics] = useState<{ candidates: FeishuTopic[]; confirmed: FeishuTopic[] }>({ candidates: [], confirmed: [] });
  // T-993：确定性预筛的跨群候选（list_pool_topics 附带，透传给工作台推荐位）
  const [crossSuggestions, setCrossSuggestions] = useState<CrossChatCandidate[]>([]);
  const [detail, setDetail] = useState<{ m: FeishuPoolMaterial; data: FeishuMaterialContent | null;
    imgUrls: Record<string, string>; chatRows: FeishuChatMessage[] | null } | null>(null);
  const [busy, setBusy] = useState('');
  // T-1001 F1：话题工作台专注模式（类 AgentChat K-039——临时态不持久化，
  // 隐藏页头/状态卡/监听范围卡/页签条，工作台双栏占满视口；ESC 退出）
  const [focusMode, setFocusMode] = useState(false);
  useEffect(() => {
    if (!focusMode) return;
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') setFocusMode(false); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [focusMode]);

  // T-951：全部话题卡计数（页签 badge；卡片流本体在工作台右栏）
  // T-1001 追修：byId 内联去重收敛为 dedupeTopics 同语义（同 id 后值覆盖先值、
  // 位置保持首次——confirmed 先入、candidates 覆盖胜出，行为零漂移）
  const allTopicCards = useMemo(() => dedupeTopics([
    ...topics.confirmed.map(t => ({ ...t, status: 'confirmed' as const })),
    ...topics.candidates,
  ]), [topics]);

  const loadWatcher = useCallback(() => {
    feishuPoolApi.getWatch().then(setWatchCfg)   // 监听用户筛选芯片数据源
      .catch(e => setError(String(e?.message || e)));
  }, []);
  const loadMaterials = useCallback(() => {
    feishuPoolApi.poolMaterials().then(r => setMaterials(r.items)).catch(e => setError(String(e?.message || e)));
  }, []);
  const loadTopics = useCallback(() => {
    feishuPoolApi.poolTopics()
      .then(r => { setTopics({ candidates: r.candidates, confirmed: r.confirmed });
                   setCrossSuggestions(r.cross_suggestions || []); })
      .catch(e => setError(String(e?.message || e)));
  }, []);

  useEffect(() => { loadWatcher(); loadMaterials(); loadTopics(); },
    [loadWatcher, loadMaterials, loadTopics]);

  const openDetail = async (m: FeishuPoolMaterial) => {
    setError('');
    setDetail({ m, data: null, imgUrls: {}, chatRows: null });
    try {
      // T-1006：群聊类详情并行拉 JSONL 事实源（消息流渲染取代整段 md 文本——
      // 时间轴同款富渲染：图片真实加载/失败标注/发送人配色；失败回退 md 视图）
      const chatMatch = m.type === 'chat'
        ? m.file.match(/^chats\/([0-9a-f]{8})\/(\d{8})\.md$/) : null;
      const [d, chatRows] = await Promise.all([
        feishuPoolApi.materialContent(m.file),
        chatMatch
          ? feishuPoolApi.chatMessages(chatMatch[1], chatMatch[2])
              .then(r => (r.items || []).length ? r.items : null)
              .catch(() => null)
          : Promise.resolve(null),
      ]);
      if (!d.ok) throw new Error(d.error || '材料读取失败');
      const urls = await loadImages(m.file, d.images || []);
      setDetail({ m, data: d, imgUrls: urls, chatRows });
    } catch (e: any) { setError(e.message); setDetail(null); }
  };

  const syncNow = async () => {
    setBusy('sync'); setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.syncNow();
      setNotice(`同步完成：文档 ${r.docs} / 妙记 ${r.minutes} / 群聊 ${r.chats}`
        + (r.errors.length ? `；${r.errors.length} 条失败（诚实呈现）` : '')
        + '；话题生成中（后台聚类，稍后刷新「话题」页签查看候选）');
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
    <div className={focusMode ? 'p-2' : 'p-4 max-w-[1100px] mx-auto'}>
      {/* T-1001：专注模式隐藏页面骨架（页头/状态卡/监听范围卡/页签条） */}
      {!focusMode && (
        <>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-base font-bold">🪺 飞书话题</h1>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-gray-500">为 agent 对话提供背景信息源 · 复核建边在「材料管理」页</span>
          <button className={btn} onClick={syncNow} disabled={busy === 'sync'}>
            {busy === 'sync' ? '同步中…' : '⇩ 立即同步'}
          </button>
          <FeishuWatchSettings onSaved={loadWatcher} />
        </div>
      </div>

      {/* 计数条（T-1004：监听运行中/监听范围两卡收进「⚙ 同步设置」弹层——
          主页只留材料/话题计数） */}
      <div className={`${card} flex items-center gap-4 text-xs`}>
        <span className="ml-auto text-gray-500">材料 {materials.length} · 候选话题 {topics.candidates.length} · 已确认话题 {topics.confirmed.length}</span>
      </div>
        </>
      )}

      {error && <div className="mb-3 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
      {notice && <div className="mb-3 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}

      {!focusMode && (
        <div className="flex items-center gap-1.5 mb-3 border-b border-border pb-2">
          {tabBtn('topics', `💬 话题（${allTopicCards.length}）`)}
          {tabBtn('materials', `📦 话题材料（${materials.length}）`)}
        </div>
      )}

      {/* 页签 1：话题材料清单（监听用户筛选 + 飞书原文直链 + 行点击本地快照） */}
      {tab === 'materials' && (
        <div className={card}>
          {/* T-1004：监听用户筛选芯片行（原监听范围卡的「只看产出」入口保留在
              其作用对象旁——材料清单；范围展示本身已收进同步设置弹层） */}
          {watchUsers.length > 0 && (
            <div className="mb-2 flex items-center gap-2 flex-wrap text-[11px]">
              <span className="text-gray-500 shrink-0">按监听用户筛选</span>
              {watchUsers.map(u => (
                <button key={u.open_id}
                  onClick={() => setOwnerFilter(ownerFilter === u.open_id ? '' : u.open_id)}
                  title={`${u.scopes.map(x => SCOPE_LABEL[x] || x).join('/') || '无监听项'}（点选只看其文档+妙记产出）`}
                  className={'px-2 py-0.5 rounded border '
                    + (ownerFilter === u.open_id
                      ? 'bg-info/20 text-info border-info/40'
                      : 'text-gray-300 border-border hover:border-gray-500')}>
                  {u.name || u.open_id}
                </button>
              ))}
            </div>
          )}
          {ownerFilter && (
            <div className="mb-2 flex items-center gap-2 text-[11px] text-info">
              ▸ 只看 {(watchUsers.find(u => u.open_id === ownerFilter)?.name) || ownerFilter} 的产出（文档+妙记）
              <button className="text-gray-500 hover:text-gray-300"
                onClick={() => setOwnerFilter('')}>× 取消</button>
            </div>
          )}
          {materials.length === 0 ? (
            <div className="text-xs text-gray-500">暂无话题材料——点右上「⚙ 同步设置」配置授权范围（群聊/用户/文档）后「⇩ 立即同步」</div>
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
                      {/* T-949：perm 缺失（需补授权）诚实标注——重新扫码授权后同步即补齐 */}
                      {m.type !== 'chat' && m.perm && !m.perm.pulled_at && (
                        <span className="ml-1 inline-block px-1.5 py-0.5 rounded text-[10px] bg-amber-500/15 text-amber-400"
                          title={(m.perm.error || '').slice(0, 120) || '权限元数据缺失'}>
                          需补授权
                        </span>
                      )}
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

      {/* 页签 2：话题工作台（T-951：单一双栏——消息时间轴×话题列表；
          T-1001 F1 专注模式由本页驱动：隐藏骨架 + 双栏占满视口） */}
      {tab === 'topics' && (
        <TopicWorkspace
          materials={materials}
          watchCfg={watchCfg}
          topics={topics}
          onCommitted={loadTopics}
          crossSuggestions={crossSuggestions}
          focus={focusMode}
          onToggleFocus={() => setFocusMode(v => !v)} />
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
            ) : !(detail.data.content || '').trim() ? (
              <div className="py-10 text-center text-xs text-gray-500">
                该快照内容为空（可能当日无消息或文档为空）
              </div>
            ) : (
              <>
                {/* T-1006：群聊类有 JSONL 事实源 → 消息流呈现（不再是整段 md 一坨）；
                    md 视图收折叠底稿（占位符口径原文，供对照） */}
                {detail.m.type === 'chat' && detail.chatRows ? (
                  <>
                    <ChatDetailView rows={detail.chatRows}
                      sha8={detail.m.file.match(/^chats\/([0-9a-f]{8})\//)?.[1] || ''}
                      day={detail.m.file.match(/\/(\d{8})\.md$/)?.[1] || ''} />
                    <details className="mt-3">
                      <summary className="text-[11px] text-gray-500 cursor-pointer">md 底稿（占位符口径）</summary>
                      <div className="mt-2 text-xs text-gray-400 prose prose-invert prose-sm max-w-none
                        [&_img]:max-w-full [&_img]:rounded [&_img]:border [&_img]:border-border [&_img]:my-2">
                        <Markdown remarkPlugins={[remarkGfm]}>
                          {inlineImages(detail.data.content, detail.imgUrls)}
                        </Markdown>
                      </div>
                    </details>
                  </>
                ) : (
                  <div className="text-xs text-gray-400 prose prose-invert prose-sm max-w-none
                    [&_img]:max-w-full [&_img]:rounded [&_img]:border [&_img]:border-border [&_img]:my-2">
                    <Markdown remarkPlugins={[remarkGfm]}>
                      {inlineImages(detail.data.content, detail.imgUrls)}
                    </Markdown>
                  </div>
                )}
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

