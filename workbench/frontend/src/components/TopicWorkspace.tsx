// TopicWorkspace.tsx — 人工介入工作台（T-950 双栏重构）：
// 左栏消息时间轴（JSONL 事实源精确渲染）+ 右栏话题泳道色卡。
// git-log 类比：话题=commit（色卡/泳道），消息=hunk；hover/点击色卡 →
// 左栏对应消息精确高亮（message_ids 集合匹配，window 时间窗兜底）+ 滚动定位。
// window 重叠的话题分泳道（lane）水平铺排——并行话题一眼可辨。

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  feishuPoolApi,
  type FeishuPoolMaterial,
  type FeishuTopic,
  type FeishuTopicDraft,
  type FeishuChatMessage,
  type FeishuWatch,
} from '../api';
import { useChatOptions, sha256Hex8 } from './useChatOptions';
import TopicCard from './TopicCard';
import ModelSetupModal from './ModelSetupModal';
import ImageLightbox from './ImageLightbox';

// 泳道分配：话题按优先级 + window 起止排序（T-991：high 提前占前排泳道），
// 贪心放入首个无时间重叠的泳道
type Laned = { card: FeishuTopic | FeishuTopicDraft; lane: number; key: string };

// T-991：优先级排序权重（high 先行；无值按 normal）
const PRIORITY_RANK: Record<string, number> = { high: 0, normal: 1, low: 2 };

function assignLanes(cards: (FeishuTopic | FeishuTopicDraft)[]): Laned[] {
  const sorted = [...cards].sort((a, b) => {
    const pr = (PRIORITY_RANK[(a as FeishuTopic).priority || 'normal'] ?? 1)
      - (PRIORITY_RANK[(b as FeishuTopic).priority || 'normal'] ?? 1);
    if (pr !== 0) return pr;
    return String(a.window?.[0] || '').localeCompare(String(b.window?.[0] || ''));
  });
  const laneEnds: string[] = [];      // 每泳道当前占用末端（ISO HH:MM）
  return sorted.map(card => {
    const start = String(card.window?.[0] || '');
    const end = String(card.window?.[1] || start);
    let lane = laneEnds.findIndex(le => !le || start > le);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(end);
    } else {
      laneEnds[lane] = end;
    }
    const t = card as FeishuTopic;
    return { card, lane, key: t.id || `draft-${start}-${t.title}` };
  });
}

// T-953：操作状态持久化（UX 连续性——进入页面恢复上次选择，不重新选）
// T-991：追加 categoryFilter（分类筛选）与 hideChat（闲聊默认过滤开关，拍板③）
const WORKSPACE_STORE_KEY = 'sg-feishu-workspace';
function loadWorkspacePersisted(): {
  sha8?: string; daySel?: string; categoryFilter?: string; hideChat?: boolean;
} {
  try {
    return JSON.parse(localStorage.getItem(WORKSPACE_STORE_KEY) || '{}');
  } catch { return {}; }
}

export default function TopicWorkspace({ materials, watchCfg, topics, onCommitted }: {
  materials: FeishuPoolMaterial[];
  watchCfg: FeishuWatch | null;
  topics: { candidates: FeishuTopic[]; confirmed: FeishuTopic[] };
  onCommitted: () => void;
}) {
  const chatOptions = useChatOptions(materials, watchCfg);
  const [sha8, setSha8] = useState(() => loadWorkspacePersisted().sha8 || '');
  const [daySel, setDaySel] = useState(() => loadWorkspacePersisted().daySel || '');        // 单日 yyyymmdd 或 'W:3'/'W:7' 窗口
  const [messages, setMessages] = useState<FeishuChatMessage[] | null>(null);
  const [msgEmpty, setMsgEmpty] = useState(false);     // 区分「加载中」与「无消息快照」
  const [drafts, setDrafts] = useState<FeishuTopicDraft[]>([]);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [hoverKey, setHoverKey] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('all');
  // T-991：分类筛选 + 闲聊默认过滤（拍板③：分类保留、默认隐藏可开关）
  const [categoryFilter, setCategoryFilter] = useState(
    () => loadWorkspacePersisted().categoryFilter ?? 'all');
  const [hideChat, setHideChat] = useState(
    () => loadWorkspacePersisted().hideChat ?? true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const timelineRef = useRef<HTMLDivElement>(null);
  // T-952：富渲染——图片 objectURL（mediaKey→URL）与转述 caption（mediaKey→描述）
  const [imgUrls, setImgUrls] = useState<Record<string, string>>({});
  const [imgFailed, setImgFailed] = useState<Set<string>>(new Set());   // T-955：图片三态之失败态
  const [captions, setCaptions] = useState<Record<string, string>>({});
  const [reloadKey, setReloadKey] = useState(0);       // T-952：单群刷新后重拉窗口
  // 图片大图预览弹层（点击缩略图就地放大，ESC/点遮罩关闭——不跳新标签页）
  const [previewImg, setPreviewImg] = useState<{ url: string; caption: string } | null>(null);
  // T-955：长操作耗时提示（分类/同步中实时显示已耗时秒数）
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!busy) { setElapsed(0); return; }
    setElapsed(0);
    const t0 = Date.now();
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  // T-954：模型缺失就地配置弹层（体验基线②③——不报错踢人去设置页）
  const [modelSetup, setModelSetup] = useState<'text' | 'vision' | null>(null);

  // T-953：选择变更即写入（进入页面恢复上次群/日期窗口；T-991 含分类筛选/闲聊开关）
  useEffect(() => {
    try {
      localStorage.setItem(WORKSPACE_STORE_KEY, JSON.stringify(
        { sha8, daySel, categoryFilter, hideChat }));
    } catch { /* 隐私模式/配额：跳过不阻断 */ }
  }, [sha8, daySel, categoryFilter, hideChat]);

  // T-953：恢复值有效性校验——选项就绪后失效则诚实回退默认（不报错不空白）
  useEffect(() => {
    if (!chatOptions.length) return;                 // 选项未就绪，等待
    if (sha8 && !chatOptions.some(c => c.chat_sha8 === sha8)) {
      setSha8(''); setDaySel('');
    }
  }, [chatOptions, sha8]);
  useEffect(() => {
    if (!sha8 || !daySel || daySel.startsWith('W:')) return;
    const chat = chatOptions.find(c => c.chat_sha8 === sha8);
    if (chat && !(chat.days || []).includes(daySel)) {
      setDaySel('');                                  // 恢复的单日已无快照：回退默认
    }
  }, [chatOptions, sha8, daySel]);

  // 选中群对应的原始 chat_id（watch 配置反查——「更新本群」单群同步用）
  const [selectedChatId, setSelectedChatId] = useState('');
  useEffect(() => {
    if (!sha8 || !watchCfg?.chats?.length) { setSelectedChatId(''); return; }
    let cancelled = false;
    (async () => {
      for (const c of watchCfg.chats) {
        if (c.chat_id && await sha256Hex8(c.chat_id) === sha8) {
          if (!cancelled) setSelectedChatId(c.chat_id);
          return;
        }
      }
      if (!cancelled) setSelectedChatId('');
    })();
    return () => { cancelled = true; };
  }, [sha8, watchCfg]);

  const selectedChat = chatOptions.find(c => c.chat_sha8 === sha8);
  const multiDay = daySel.startsWith('W:');
  const windowN = multiDay ? parseInt(daySel.slice(2), 10) : 1;

  // T-951c：选中窗口的实际日子（近 N 天 = 最近 N 个有快照的日子，倒序取 N 再正序）
  const selectedDays = useMemo(() => {
    const days = selectedChat?.days || [];
    if (!daySel) return [];
    if (!multiDay) return [daySel];
    return [...days].sort().slice(-windowN);
  }, [selectedChat, daySel, multiDay, windowN]);
  const isMulti = selectedDays.length > 1;

  useEffect(() => {
    setError(''); setNotice(''); setDrafts([]); setChecked(new Set());
    setHoverKey(null); setSelectedKey(null); setPreviewImg(null);
    if (!sha8 || !daySel) {
      setMessages(null); setMsgEmpty(false);
      return;
    }
    setMessages(null); setMsgEmpty(false);
    let cancelled = false;
    // T-951c：多日窗口逐日拉取拼接（空日跳过；行号跨日连续）
    (async () => {
      const rows: FeishuChatMessage[] = [];
      let any = false;
      for (const d of selectedDays) {
        try {
          const r = await feishuPoolApi.chatMessages(sha8, d);
          if (cancelled) return;
          if ((r.items || []).length) { rows.push(...r.items); any = true; }
        } catch { /* 无快照日跳过 */ }
      }
      if (any) {
        setMessages(rows); setMsgEmpty(false);
        return;
      }
      // 全部无 JSONL：回退读 md 视图（单日旧数据兼容）
      try {
        const d = selectedDays[selectedDays.length - 1];
        const md = await feishuPoolApi.materialContent(`chats/${sha8}/${d}.md`);
        if (cancelled) return;
        if (!md.ok) { setMessages([]); setMsgEmpty(true); return; }
        const mdRows: FeishuChatMessage[] = (md.content || '').split('\n')
          .filter(l => /^\[\d{2}:\d{2}\]/.test(l))
          .map((l, i) => {
            const m = l.match(/^\[(\d{2}:\d{2})\]\s([^:]+):\s([\s\S]*)$/) || [];
            return {
              message_id: `md-line-${i + 1}`,   // 行号伪 id（回退高亮按行匹配）
              ts: `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}T${m[1] || '??:??'}:00`,
              sender_name: m[2] || '?', msg_type: 'text', content: m[3] || l,
            };
          });
        setMessages(mdRows);
        setMsgEmpty(mdRows.length === 0);
      } catch {
        if (cancelled) return;
        setMessages([]); setMsgEmpty(true);
      }
    })();
    return () => { cancelled = true; };
  }, [sha8, daySel, selectedDays, reloadKey]);

  // T-952：富渲染素材——窗口内全部图片 (message_id, key) 配对懒拉字节 + imgmap captions
  useEffect(() => {
    if (!messages) return;
    const pairs = new Set<string>();            // "mid|key"（图属消息——im 下载需配对）
    messages.forEach(m => {
      (m.image_keys || []).forEach(k => k && pairs.add(`${m.message_id}|${k}`));
      if (m.image_key && m.message_id) pairs.add(`${m.message_id}|${m.image_key}`);
    });
    let cancelled = false;
    pairs.forEach(pk => {
      const [mid, k] = pk.split('|');
      feishuPoolApi.fetchChatImageBlob(mid, k).then(blob => {
        if (!cancelled) {
          const url = URL.createObjectURL(blob);
          setImgUrls(prev => prev[k] ? (URL.revokeObjectURL(url), prev) : { ...prev, [k]: url });
        }
      }).catch(() => {
        // T-955：失败态显式标记（三态分离——不再永远「加载中」）
        if (!cancelled) setImgFailed(prev => new Set(prev).add(k));
      });
    });
    // captions：逐日报 imgmap（key→caption）
    (async () => {
      const cap: Record<string, string> = {};
      for (const d of selectedDays) {
        try {
          const r = await feishuPoolApi.materialContent(`chats/${sha8}/${d}.md`);
          if (cancelled) return;
          (r.images || []).forEach((i: any) => {
            if (i.media_key && i.caption) cap[i.media_key] = i.caption;
          });
        } catch { /* 无快照日跳过 */ }
      }
      if (!cancelled && Object.keys(cap).length) setCaptions(prev => ({ ...prev, ...cap }));
    })();
    return () => {
      cancelled = true;
    };
    // eslint 无 imgUrls 依赖：函数式更新 + 卸载时由窗口切换的下一个 effect 清理
  }, [messages, sha8, selectedDays]);

  // 该群窗口内已入库卡片（含状态制全部状态——rejected 灰显留痕）
  const dayTopics = useMemo(() => {
    const all = [...topics.candidates, ...topics.confirmed];
    if (!sha8 || selectedDays.length === 0) return [];
    return all.filter(t => t.chat_sha8 === sha8
      && (selectedDays.some(d => String(t.id).includes(`-${d}-`))
          || (t.days || []).some(d => selectedDays.includes(d))));
  }, [topics, sha8, selectedDays]);

  // T-951：状态筛选作用右栏卡片流（drafts 草案不受筛选影响——未提交非状态卡）
  // T-991：叠加分类筛选 + 闲聊默认过滤（拍板③；草案同步受闲聊过滤影响）
  const shownTopics = useMemo(
    () => dayTopics.filter(t =>
      (statusFilter === 'all' || (t.status || 'draft') === statusFilter)
      && (categoryFilter === 'all' || (t.category || 'routine') === categoryFilter)
      && !(hideChat && (t.category || 'routine') === 'chat')),
    [dayTopics, statusFilter, categoryFilter, hideChat]);
  const shownDrafts = useMemo(
    () => hideChat
      ? drafts.filter(d => (d.category || 'routine') !== 'chat')
      : drafts,
    [drafts, hideChat]);
  const statusCount = (key: string) => key === 'all'
    ? dayTopics.length
    : dayTopics.filter(t => (t.status || 'draft') === key).length;

  const laned = useMemo(
    () => assignLanes([...shownTopics, ...shownDrafts]), [shownTopics, shownDrafts]);
  const activeKey = hoverKey ?? selectedKey;
  const activeCard = laned.find(l => l.key === activeKey)?.card as FeishuTopic | undefined;

  // 高亮集合：message_ids 精确（跨日天然支持）；无则 window 完整 ts 比较兑底
  const highlightIdx = useMemo(() => {
    const set = new Set<number>();
    if (!activeCard || !messages) return set;
    const ids = activeCard.message_ids || [];
    if (ids.length) {
      messages.forEach((m, i) => {
        if (ids.includes(m.message_id)) set.add(i);
      });
      return set;
    }
    const start = activeCard.window?.[0] || '';
    const end = activeCard.window?.[1] || '';
    if (!start || !end) return set;
    messages.forEach((m, i) => {
      if (m.ts >= start && m.ts <= end) set.add(i);
    });
    return set;
  }, [activeCard, messages]);

  useEffect(() => {
    if (highlightIdx.size === 0 || !timelineRef.current) return;
    const first = timelineRef.current.querySelector('[data-hl="1"]');
    first?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [highlightIdx]);

  const runDraft = async () => {
    if (!sha8 || selectedDays.length === 0) return;
    setBusy('draft'); setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.draftTopics(sha8, selectedDays);
      setDrafts(r.items);
      setChecked(new Set(r.items.map((_, i) => i)));
      setNotice(isMulti
        ? `已生成 ${r.items.length} 个候选段（${selectedDays.length} 天窗口，跨天讨论会聚为同一话题）`
        : `已生成 ${r.items.length} 个候选段（勾选后提交，覆盖该群该日旧卡）`);
    } catch (e: any) {
      // T-954：模型未配置→弹层就地配置（保存后自动重试），其余错误如实展示
      if (/未配置 (text|vision) 模型/.test(String(e?.message || ''))) {
        setModelSetup(/vision/.test(e.message) ? 'vision' : 'text');
      } else {
        setError(e.message);
      }
    } finally { setBusy(''); }
  };

  const commit = async () => {
    if (!sha8 || selectedDays.length === 0 || checked.size === 0) return;
    setBusy('commit'); setError(''); setNotice('');
    try {
      const picked = drafts.filter((_, i) => checked.has(i));
      await feishuPoolApi.commitTopics(
        sha8, selectedDays[selectedDays.length - 1], picked,
        isMulti ? selectedDays : undefined);
      setNotice(`已提交 ${picked.length} 个话题卡（窗口内旧卡已标 rejected 留痕）`);
      setDrafts([]); setChecked(new Set());
      onCommitted();
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  // T-952：单群刷新（只拉选中群；完成后重拉当前窗口消息）
  const syncOneChat = async () => {
    if (!sha8 || !selectedChatId) return;
    setBusy('sync'); setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.syncNow(selectedChatId);
      setNotice(`本群已更新：${r.chats} 个有消息日 / ${r.chats_empty || 0} 个空日`
        + (r.errors?.length ? `；${r.errors.length} 项失败` : ''));
      setReloadKey(k => k + 1);          // 重拉当前窗口（onCommitted 也拉话题）
      onCommitted();
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const btn = 'px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const input = 'bg-surface-3 border border-border rounded px-2 py-1.5 text-xs text-gray-200 outline-none focus:border-info';
  const laneCount = Math.max(1, ...laned.map(l => l.lane + 1));

  return (
    <div className="bg-surface-2 border border-border rounded-lg p-4">
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <span className="text-sm font-semibold">人工介入工作台</span>
        <span className="text-[11px] text-gray-500">左栏原文时间轴 × 右栏话题色卡（并行话题分泳道）；hover/点击色卡高亮对应消息</span>
      </div>
      {error && <div className="mb-2 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
      {notice && <div className="mb-2 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}
      {/* 顶栏：群/日期 + 重新分类 + 状态筛选（单一控制区，页面不再分上下两层） */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <select className={input} value={sha8}
          onChange={e => { setSha8(e.target.value); setDaySel(''); }}>
          <option value="">— 选择群 —</option>
          {chatOptions.map(c => (
            <option key={c.chat_sha8} value={c.chat_sha8}>
              {c.name}{c.kind ? ` · ${c.kind}` : ''} ({c.chat_sha8})
            </option>
          ))}
        </select>
        <select className={input} value={daySel} disabled={!sha8}
          onChange={e => setDaySel(e.target.value)}>
          <option value="">— 选择日期 —</option>
          {/* T-951c：多日窗口（近 N 个有快照的日子——跨天话题聚合入口） */}
          <option value="W:3">近 3 天（跨天话题）</option>
          <option value="W:7">近 7 天（跨天话题）</option>
          {(selectedChat?.days || []).slice().reverse().map(d => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        <button className={btn} disabled={!sha8 || !daySel || busy === 'draft'}
          onClick={runDraft}>
          {busy === 'draft' ? `分类中… ${elapsed}s` : '重新 AI 分类'}
        </button>
        {/* T-952：单群刷新（秒级反馈——只拉选中群，不动 docs/minutes） */}
        <button className={btn}
          disabled={!sha8 || busy === 'sync' || !selectedChatId}
          title={selectedChatId ? '只同步当前群的聊天记录（chat_days 窗口内重建）'
                                : '该群不在当前 watch 配置中（从同步设置添加后可刷新）'}
          onClick={syncOneChat}>
          {busy === 'sync' ? `更新中… ${elapsed}s` : '↻ 更新本群'}
        </button>
        {drafts.length > 0 && (
          <button className={btn} disabled={busy === 'commit' || checked.size === 0}
            onClick={commit}>
            {busy === 'commit' ? '提交中…' : `生成话题卡（勾选 ${checked.size} 段）`}
          </button>
        )}
        {sha8 && daySel && (
          <span className="ml-auto flex items-center gap-1.5">
            <select className="bg-surface-3 border border-border rounded px-1.5 py-0.5 text-[11px] text-gray-300 outline-none focus:border-info"
              value={categoryFilter}
              onChange={e => setCategoryFilter(e.target.value)}
              title="按五分类筛选话题">
              <option value="all">全部分类</option>
              <option value="requirement">需求</option>
              <option value="test">测试</option>
              <option value="solution">方案</option>
              <option value="routine">沟通</option>
              <option value="chat">闲聊</option>
            </select>
            <label className="flex items-center gap-1 text-[11px] text-gray-400 cursor-pointer"
              title="闲聊话题分类保留但默认隐藏（可审计/统计群噪声率）——拍板③">
              <input type="checkbox" checked={hideChat}
                onChange={e => setHideChat(e.target.checked)} />
              隐藏闲聊
            </label>
            {TOPIC_STATUS_TABS.map(s => (
              <button key={s.key}
                className={`px-2 py-0.5 rounded text-[11px] ${
                  statusFilter === s.key ? 'bg-info/20 text-info' : 'bg-surface-3 text-gray-400'}`}
                onClick={() => setStatusFilter(s.key)}>
                {s.label}{statusCount(s.key) > 0 ? ` ${statusCount(s.key)}` : ''}
              </button>
            ))}
          </span>
        )}
      </div>
      {sha8 && daySel ? (
        <div className="flex gap-3">
          {/* 左栏：消息时间轴（多日拼接；行带 MM-DD 日期前缀跨日不歧义） */}
          <div ref={timelineRef}
            className="w-[46%] shrink-0 border border-border rounded p-2 bg-surface-3 max-h-[560px] overflow-auto">
            {messages === null ? (
              <div className="text-xs text-gray-500">消息加载中…</div>
            ) : msgEmpty ? (
              <div className="text-xs text-gray-500">
                窗口内无消息快照——点「立即同步」补拉（chat_days 窗口内自动重建）
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={`${m.message_id}-${i}`} data-hl={highlightIdx.has(i) ? '1' : '0'}
                  className={`text-[11px] leading-relaxed px-1.5 py-1 mb-0.5 rounded transition-colors ${
                    highlightIdx.has(i)
                      ? 'bg-info/20'
                      : 'hover:bg-black/20'
                  }`}>
                  {/* T-955：两行制排版——头行「昵称 · 时间」（昵称按发送人稳定配色），
                      正文独立成行，消息问读性与 IM 应用一致 */}
                  <div className={`flex items-baseline gap-1.5 ${
                    highlightIdx.has(i) ? 'text-info' : 'text-gray-500'}`}>
                    <span className="font-medium"
                      style={{ color: highlightIdx.has(i) ? undefined : senderColor(m.sender_id || m.sender_name || '') }}>
                      {m.sender_name || m.sender_id || '?'}
                    </span>
                    <span className="text-[10px] text-gray-600">{fmtMsgTime(m.ts, isMulti)}</span>
                  </div>
                  <div className={highlightIdx.has(i) ? 'text-info' : 'text-gray-300'}>
                    {/* T-952：真实内容渲染——post 文本+内嵌图 / file 文件卡 / image 图 */}
                    <MessageBody msg={m} imgUrls={imgUrls} imgFailed={imgFailed}
                      captions={captions} highlight={highlightIdx.has(i)}
                      onImageClick={(url, caption) =>
                        setPreviewImg({ url, caption })} />
                  </div>
                </div>
              ))
            )}
          </div>
          {/* 右栏：话题泳道色卡（该日全部状态卡 + 分类草案；唯一卡片流） */}
          <div className="flex-1 min-w-0 space-y-2 max-h-[560px] overflow-auto pr-1">
            {laned.length === 0 ? (
              <div className="text-xs text-gray-500">
                {statusFilter === 'all'
                  ? '窗口内暂无话题卡——「重新 AI 分类」生成分段，或等待同步后自动聚类'
                  : `该状态暂无卡片（全部 ${dayTopics.length} 张）`}
              </div>
            ) : (
              Array.from({ length: laneCount }, (_, lane) => (
                <div key={lane}
                  className="flex gap-2 items-stretch pb-1">
                  {laned.filter(l => l.lane === lane).map(l => {
                    const t = l.card as FeishuTopic;
                    const isDraft = !t.id;
                    const active = activeKey === l.key;
                    const st = t.status || 'draft';
                    return (
                      <div key={l.key}
                        onMouseEnter={() => setHoverKey(l.key)}
                        onMouseLeave={() => setHoverKey(null)}
                        onClick={() => setSelectedKey(prev => prev === l.key ? null : l.key)}
                        className={`min-w-[240px] max-w-[360px] shrink-0 rounded-lg border p-2
                          cursor-pointer transition-all
                          ${active ? 'border-info/60 bg-info/10 shadow-[0_0_0_1px_rgba(59,130,246,0.3)]' : 'border-border bg-surface-3 hover:border-gray-500'}
                          ${st === 'rejected' ? 'opacity-50' : ''}`}
                        style={{ borderLeft: '3px solid', borderLeftColor: laneColor(lane) }}>
                        {isDraft ? (
                          <label className="flex items-start gap-2 cursor-pointer"
                            onClick={e => e.stopPropagation()}>
                            <input type="checkbox" className="mt-0.5"
                              checked={checked.has(drafts.indexOf(l.card as FeishuTopicDraft))}
                              onChange={() => {
                                const di = drafts.indexOf(l.card as FeishuTopicDraft);
                                setChecked(prev => {
                                  const next = new Set(prev);
                                  if (next.has(di)) next.delete(di); else next.add(di);
                                  return next;
                                });
                              }} />
                            <TopicCard topic={l.card as FeishuTopic} draft onRefresh={onCommitted} />
                          </label>
                        ) : (
                          <TopicCard topic={t} onRefresh={onCommitted}
                            selected={selectedKey === l.key}
                            onSelect={() => setSelectedKey(prev => prev === l.key ? null : l.key)} />
                        )}
                      </div>
                    );
                  })}
                </div>
              ))
            )}
          </div>
        </div>
      ) : (
        <div className="text-xs text-gray-500">请先选择群聊与日期。</div>
      )}
      {/* T-954：模型缺失就地配置弹层（保存后自动重试分类） */}
      {modelSetup && (
        <ModelSetupModal purpose={modelSetup}
          onClose={() => setModelSetup(null)}
          onConfigured={() => { setModelSetup(null); void runDraft(); }} />
      )}
      {/* 图片大图预览弹层（点击缩略图就地放大；ESC/点遮罩关闭） */}
      {previewImg && (
        <ImageLightbox url={previewImg.url} caption={previewImg.caption}
          onClose={() => setPreviewImg(null)} />
      )}
    </div>
  );
}

const TOPIC_STATUS_TABS: { key: string; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'draft', label: '待确认' },
  { key: 'confirmed', label: '已确认' },
  { key: 'rejected', label: '已拒绝' },
];

// 泳道配色（lane 序号 → 色相环取色，稳定可辨）
export function laneColor(lane: number): string {
  const palette = ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ef4444',
    '#14b8a6', '#eab308', '#6366f1'];
  return palette[lane % palette.length];
}

// T-952：消息体真实内容渲染——post 文本+内嵌图 / file 文件卡（可下载）/ image 图。
// 图片三态（加载中/失败/成功——体验基线③）；转述 caption 展示在图下（agent
// 检索与用户审阅同一份描述——技术侧转述对用户透明，无独立维护入口）。
function MessageBody({ msg, imgUrls, imgFailed, captions, highlight, onImageClick }: {
  msg: FeishuChatMessage;
  imgUrls: Record<string, string>;
  imgFailed: Set<string>;
  captions: Record<string, string>;
  highlight: boolean;
  onImageClick: (url: string, caption: string) => void;
}) {
  const imgCls = 'max-h-28 rounded border border-border mt-1 mr-1 inline-block align-top cursor-pointer';
  const capCls = `text-[10px] mt-0.5 ${highlight ? 'text-info/80' : 'text-gray-500'}`;
  const renderImgs = (keys: (string | undefined)[]) => (
    keys.filter(Boolean).map(k => {
      const key = k as string;
      return (
        <span key={key} className="inline-block mr-1 align-top">
          {imgUrls[key] ? (
            <img src={imgUrls[key]} alt="聊天图片"
              className={imgCls}
              title={captions[key] || 'AI 转述生成中…'}
              onClick={e => {
                // 点击大图预览（弹层就地放大；ESC/点遮罩关闭，不跳新标签页）
                e.stopPropagation();
                onImageClick(imgUrls[key], captions[key] || '');
              }} />
          ) : imgFailed.has(key) ? (
            <span className="inline-block w-16 h-16 leading-[3.5rem] text-center rounded
              border border-red-500/30 bg-red-500/5 text-[10px] text-red-400 align-top"
              title="图片加载失败（当前飞书账号无该图权限或下载失败，刷新页面重试）">加载失败</span>
          ) : (
            <span className="inline-block w-16 h-16 leading-[4rem] text-center rounded
              border border-border bg-black/30 text-[10px] text-gray-600 align-top">加载中…</span>
          )}
          {captions[key] && (
            <div className={capCls}>{captions[key]}</div>
          )}
        </span>
      );
    })
  );
  if (msg.msg_type === 'image') {
    return <>{renderImgs([msg.image_key])}</>;
  }
  if (msg.msg_type === 'post') {
    // 文本主体（内嵌图引用剔除——图单独渲染）
    const text = (msg.content || '')
      .replace(/!\[Image\]\([^)]*\)/g, '').trim();
    return (
      <>
        {text && <span className="whitespace-pre-wrap break-all">{text}</span>}
        {(msg.image_keys || []).length > 0 && <div>{renderImgs(msg.image_keys)}</div>}
      </>
    );
  }
  if (msg.msg_type === 'file') {
    if (!msg.file_key || !msg.message_id) {
      // 旧快照无附件信息（T-952a 前落盘）——提示重拉而非静默无响应
      return (
        <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded mt-1
          bg-black/20 border border-border"
          title="旧快照无附件下载信息——点「↻ 更新本群」重新同步后可下载">
          <span className="text-[13px]">📎</span>
          <span className="text-gray-300">{msg.file_name || '文件'}</span>
          <span className="text-[10px] text-amber-500/80">需更新后可下载</span>
        </span>
      );
    }
    return (
      // T-955：附件可下载（blob 拉取 + a.download；失败如实提示）
      <button
        className={`inline-flex items-center gap-1.5 px-2 py-1 rounded mt-1
          ${highlight ? 'bg-info/15' : 'bg-black/20 border border-border hover:border-info/50'}`}
        title="点击下载附件"
        onClick={e => {
          e.stopPropagation();
          const name = msg.file_name || 'attachment';
          feishuPoolApi.fetchChatFileBlob(msg.message_id!, msg.file_key!, name)
            .then(blob => {
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = name;
              a.click();
              setTimeout(() => URL.revokeObjectURL(url), 30_000);
            })
            .catch(() => { /* 下载失败：提示由调用方 notice 承担（本组件无 state） */ });
        }}>
        <span className="text-[13px]">📎</span>
        <span className="text-gray-300">{msg.file_name || '文件'}</span>
        <span className="text-[10px] text-gray-600">点击下载</span>
      </button>
    );
  }
  return <span className="whitespace-pre-wrap break-all">{msg.content}</span>;
}

// T-955：消息时间格式化（单日 HH:MM；多日 MM-DD HH:MM——去 ISO 的 T）
function fmtMsgTime(ts: string, isMulti: boolean): string {
  if (!ts) return '';
  return isMulti
    ? `${ts.slice(5, 10)} ${ts.slice(11, 16)}`
    : ts.slice(11, 16);
}

// T-955：发送人稳定配色（按 id 哈希取色相环——IM 惯例，一眼区分谁在说话）
const SENDER_PALETTE = ['#60a5fa', '#f59e0b', '#34d399', '#a78bfa', '#f87171',
  '#22d3ee', '#eab308', '#f472b6'];
function senderColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return SENDER_PALETTE[h % SENDER_PALETTE.length];
}
