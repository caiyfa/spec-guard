// TopicWorkspace.tsx — 人工介入工作台（T-950 双栏重构；T-1001 列表化+专注模式）：
// 左栏消息时间轴（JSONL 事实源精确渲染）+ 右栏话题列表（搜索/排序快速定位）。
// git-log 类比：话题=commit，消息=hunk；hover/点击列表行 →
// 左栏对应消息精确高亮（message_ids 集合匹配，window 时间窗兜底）+ 滚动定位。
// T-1001：泳道色卡平铺改紧凑列表行（话题多时配合搜索/排序）；
// 编辑迁入 TopicEditModal 弹框（左原文右话题并排 + 手动重关联）；
// focus 专注模式由页面层（FeishuPool）驱动——隐藏页头/状态卡占满视口。

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  feishuPoolApi,
  type FeishuPoolMaterial,
  type FeishuTopic,
  type FeishuTopicDraft,
  type FeishuChatMessage,
  type FeishuWatch,
  type TopicRelation,
  type CrossChatCandidate,
} from '../api';
import { useChatOptions, sha256Hex8 } from './useChatOptions';
import TopicCard from './TopicCard';
import TopicEditModal from './TopicEditModal';
import ModelSetupModal from './ModelSetupModal';
import ImageLightbox from './ImageLightbox';
import { loadChatMessages, MessageBody, useChatMedia, senderColor, fmtMsgTime }
  from './ChatMessageView';
import { filterAndSortTopics, filterTopics, TOPIC_SORT_OPTIONS,
  dedupeTopics, collectKeywords, type TopicSortKey }
  from './topicList';

// T-953：操作状态持久化（UX 连续性——进入页面恢复上次选择，不重新选）
// T-991：追加 categoryFilter（分类筛选）与 hideChat（闲聊默认过滤开关，拍板③）
// T-1001：追加 query/sortKey（列表搜索与排序——话题多时快速定位）
// T-1001 追修：追加 tags（标签筛选，多选 AND）
const WORKSPACE_STORE_KEY = 'sg-feishu-workspace';
function loadWorkspacePersisted(): {
  sha8?: string; daySel?: string; categoryFilter?: string; hideChat?: boolean;
  query?: string; sortKey?: TopicSortKey; tags?: string[];
} {
  try {
    return JSON.parse(localStorage.getItem(WORKSPACE_STORE_KEY) || '{}');
  } catch { return {}; }
}

export default function TopicWorkspace({ materials, watchCfg, topics, onCommitted,
                                          crossSuggestions, focus, onToggleFocus }: {
  materials: FeishuPoolMaterial[];
  watchCfg: FeishuWatch | null;
  topics: { candidates: FeishuTopic[]; confirmed: FeishuTopic[] };
  onCommitted: () => void;
  crossSuggestions?: CrossChatCandidate[];   // T-993：确定性预筛（list_pool_topics 附带）
  focus?: boolean;                           // T-1001：专注模式（页面层驱动，临时态不持久化）
  onToggleFocus?: () => void;
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
  // T-1001 F2：列表搜索 + 排序（状态/分类/闲聊筛选取既有控件；此处文本搜索与排序键）
  const [query, setQuery] = useState(() => loadWorkspacePersisted().query || '');
  const [sortKey, setSortKey] = useState<TopicSortKey>(
    () => loadWorkspacePersisted().sortKey || 'time-desc');
  // T-1001 追修：标签筛选（多选 AND；恢复值非数组时诚实回退空集）
  const [tags, setTags] = useState<string[]>(() => {
    const t = loadWorkspacePersisted().tags;
    return Array.isArray(t) ? t.filter(x => typeof x === 'string' && x) : [];
  });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const timelineRef = useRef<HTMLDivElement>(null);
  const [reloadKey, setReloadKey] = useState(0);       // T-952：单群刷新后重拉窗口
  // T-993：跨群关联——confirmed 边 / 推荐面板 / 关联抽屉
  const [relations, setRelations] = useState<TopicRelation[]>([]);
  const [crossOpen, setCrossOpen] = useState(false);
  const [crossSugg, setCrossSugg] = useState<CrossChatCandidate[]>([]);
  const [refining, setRefining] = useState(false);
  const [unrefined, setUnrefined] = useState(false);
  const [relateDrawer, setRelateDrawer] = useState<FeishuTopic | null>(null);
  // T-1001 F3：编辑弹框（左原文右话题并排 + 手动重关联）
  const [editingTopic, setEditingTopic] = useState<FeishuTopic | null>(null);
  useEffect(() => {
    feishuPoolApi.topicRelations()
      .then(r => setRelations(r.items || []))
      .catch(() => setRelations([]));
  }, [topics]);
  useEffect(() => { setCrossSugg(crossSuggestions || []); }, [crossSuggestions]);
  // 关联邻接表 {topicId: [对方 id]}（连通分量入口——A-B、B-C 则 A 含 C）
  const relatedMap = useMemo(() => {
    const m: Record<string, string[]> = {};
    relations.forEach(r => {
      (m[r.src] = m[r.src] || []).push(r.dst);
      (m[r.dst] = m[r.dst] || []).push(r.src);
    });
    return m;
  }, [relations]);
  const topicById = useMemo(() => {
    const m: Record<string, FeishuTopic> = {};
    [...topics.candidates, ...topics.confirmed]
      .forEach(t => { if (t.id) m[t.id] = t; });
    return m;
  }, [topics]);
  // 关联操作：确认/忽略（忽略写 rejected 防重复推荐）→ 刷新关联与清单
  const relate = async (a: string, b: string, confirmed: boolean) => {
    try {
      await feishuPoolApi.relateTopics(a, b, confirmed);
      const r = await feishuPoolApi.topicRelations();
      setRelations(r.items || []);
      onCommitted();
      if (relateDrawer) {
        const still = (r.items || []).some(x =>
          (x.src === relateDrawer.id && x.dst === b) || (x.dst === relateDrawer.id && x.src === b));
        if (!still && !confirmed) setRelateDrawer(null);
      }
    } catch (e: any) { setError(e.message); }
  };
  const runRefine = async () => {
    setRefining(true); setError('');
    try {
      const r = await feishuPoolApi.crossRefine();
      setCrossSugg(r.items || []);
      setUnrefined(!!r.unrefined);
    } catch (e: any) { setError(e.message); } finally { setRefining(false); }
  };
  // 跳转：关联抽屉里点某群卡 → 切到该群该日（复用既有群/日选择）
  const jumpToTopic = (t: FeishuTopic) => {
    const day = (t.days || [])[0]
      || String(t.id).match(/-(\d{8})-/)?.[1] || '';
    if (t.chat_sha8 && day) { setSha8(t.chat_sha8); setDaySel(day); }
    setRelateDrawer(null);
  };
  const chatNameOf = (sha8: string) => {
    const c = chatOptions.find(o => o.chat_sha8 === sha8);
    return c ? `${c.name}${c.kind ? ` · ${c.kind}` : ''}` : sha8;
  };
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

  // T-953：选择变更即写入（进入页面恢复上次群/日期窗口；T-991 含分类筛选/闲聊开关；
  // T-1001 含搜索/排序；追修含标签筛选）
  useEffect(() => {
    try {
      localStorage.setItem(WORKSPACE_STORE_KEY, JSON.stringify(
        { sha8, daySel, categoryFilter, hideChat, query, sortKey, tags }));
    } catch { /* 隐私模式/配额：跳过不阻断 */ }
  }, [sha8, daySel, categoryFilter, hideChat, query, sortKey, tags]);

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
    setEditingTopic(null);
    if (!sha8 || !daySel) {
      setMessages(null); setMsgEmpty(false);
      return;
    }
    setMessages(null); setMsgEmpty(false);
    let cancelled = false;
    // T-1001：加载逻辑抽至 ChatMessageView.loadChatMessages（多日 JSONL 拼接 +
    // md 视图回退——与编辑弹框共用同一份事实）
    (async () => {
      const r = await loadChatMessages(sha8, selectedDays);
      if (cancelled) return;
      setMessages(r.rows);
      setMsgEmpty(r.empty);
    })();
    return () => { cancelled = true; };
  }, [sha8, daySel, selectedDays, reloadKey]);

  // T-952/T-1001：富渲染素材（图片三态 + 转述 caption）——抽至 useChatMedia 共享
  const { imgUrls, imgFailed, captions } = useChatMedia(messages, sha8, selectedDays);

  // 该群窗口内已入库卡片（含状态制全部状态——rejected 灰显留痕）
  // T-1001 追修：candidates/confirmed 同 id 双份（confirmed 卡两存：私有区
  // _topics.yaml + 共享区 facts）——先按 id 去重（candidates 副本胜出，与页头
  // byId 同口径），否则列表 key 撞车撕裂渲染（搜索/排序看似不生效的根因）。
  const dayTopics = useMemo(() => {
    const all = dedupeTopics([...topics.confirmed, ...topics.candidates]);
    if (!sha8 || selectedDays.length === 0) return [];
    return all.filter(t => t.chat_sha8 === sha8
      && (selectedDays.some(d => String(t.id).includes(`-${d}-`))
          || (t.days || []).some(d => selectedDays.includes(d))));
  }, [topics, sha8, selectedDays]);

  // T-951：状态筛选作用右栏卡片流（drafts 草案不受状态筛选影响——未提交非状态卡）
  // T-991：叠加分类筛选 + 闲聊默认过滤（拍板③；草案同步受闲聊过滤影响）
  // T-1001 F2：改为 filterAndSortTopics 纯函数（追加文本搜索 + 排序）
  // T-1001 追修：叠加 tags 标签筛选（多选 AND）
  const statusCountNum = (key: string) => key === 'all'
    ? dayTopics.length
    : dayTopics.filter(t => (t.status || 'draft') === key).length;
  const shownTopics = useMemo(
    () => filterAndSortTopics(dayTopics,
      { status: statusFilter, category: categoryFilter, hideChat, query, tags }, sortKey),
    [dayTopics, statusFilter, categoryFilter, hideChat, query, tags, sortKey]);
  const shownDrafts = useMemo(
    () => filterAndSortTopics(drafts, { hideChat, query, tags }, sortKey),
    [drafts, hideChat, query, tags, sortKey]);
  // 标签芯片行：分面计数口径——状态/分类/闲聊/搜索已生效、标签筛选未生效的集合
  const tagFacets = useMemo(
    () => collectKeywords(filterTopics(dayTopics,
      { status: statusFilter, category: categoryFilter, hideChat, query })),
    [dayTopics, statusFilter, categoryFilter, hideChat, query]);
  const toggleTag = (kw: string) =>
    setTags(prev => prev.includes(kw) ? prev.filter(x => x !== kw) : [...prev, kw]);

  const activeKey = hoverKey ?? selectedKey;
  const activeCard = useMemo(() => {
    const pool: (FeishuTopic | FeishuTopicDraft)[] = [...shownDrafts, ...shownTopics];
    const t = pool.find(c => (c as FeishuTopic).id
      ? (c as FeishuTopic).id === activeKey
      : `draft-${c.window?.[0] || ''}-${c.title}` === activeKey);
    return t as FeishuTopic | undefined;
  }, [shownDrafts, shownTopics, activeKey]);

  // 高亮集合：message_ids 精确（跨日天然支持）；无则 window 完整 ts 比较兜底
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
  // T-1001：专注模式双栏吃满视口（默认 560px 上限）
  const paneH = focus ? 'h-[calc(100vh-170px)]' : 'max-h-[560px]';

  return (
    <div className="bg-surface-2 border border-border rounded-lg p-4">
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <span className="text-sm font-semibold">人工介入工作台</span>
        <span className="text-[11px] text-gray-500">左栏原文时间轴 × 右栏话题列表（搜索/排序定位；hover/点击行高亮对应消息）</span>
        {onToggleFocus && (
          <button
            className={`ml-auto transition-colors px-1 rounded hover:bg-surface-3
              ${focus ? 'text-info' : 'text-gray-500 hover:text-info'}`}
            onClick={onToggleFocus}
            title={focus ? '退出专注，恢复页面结构' : '专注模式：隐藏页头/状态卡/页签，工作台占满视口'}>
            {focus ? '⤡ 退出专注' : '⤢ 专注'}
          </button>
        )}
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
        {/* T-993：跨群推荐入口（确定性预筛即时可见；LLM 精筛按需触发） */}
        <button className={btn} onClick={() => setCrossOpen(v => !v)}
          title="跨群同主题话题候选（预筛 + 可选模型精筛；只推荐不合并，关联需人工确认）">
          🔗 跨群推荐{crossSugg.length > 0 ? `（${crossSugg.length}）` : ''}
        </button>
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
                {s.label}{statusCountNum(s.key) > 0 ? ` ${statusCountNum(s.key)}` : ''}
              </button>
            ))}
          </span>
        )}
      </div>
      {sha8 && daySel ? (
        <div className="flex gap-3">
          {/* 左栏：消息时间轴（多日拼接；行带 MM-DD 日期前缀跨日不歧义） */}
          <div ref={timelineRef}
            className={`w-[46%] shrink-0 border border-border rounded p-2 bg-surface-3 overflow-auto ${paneH}`}>
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
                      正文独立成行，消息可读性与 IM 应用一致 */}
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
          {/* 右栏：话题列表（T-1001 F2：搜索 + 排序 + 紧凑行；唯一卡片流） */}
          <div className={`flex-1 min-w-0 flex flex-col ${focus ? '' : 'max-h-[560px]'}`}>
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <input className={`${input} w-48`} placeholder="搜索标题/摘要/关键词…"
                value={query} onChange={e => setQuery(e.target.value)}
                title="支持多词（空格分隔，AND 语义）；命中标题/摘要/关键词" />
              <select className="bg-surface-3 border border-border rounded px-1.5 py-1 text-[11px] text-gray-300 outline-none focus:border-info"
                value={sortKey} onChange={e => setSortKey(e.target.value as TopicSortKey)}
                title="列表排序">
                {TOPIC_SORT_OPTIONS.map(o => (
                  <option key={o.key} value={o.key}>{o.label}</option>
                ))}
              </select>
              <span className="text-[10px] text-gray-600">
                {shownDrafts.length + shownTopics.length} 项
              </span>
            </div>
            {/* T-1001 追修：标签筛选芯片行（词频降序；点选 toggle，多选 AND；
                计数为分面口径——其他筛选已生效、标签未生效） */}
            {tagFacets.length > 0 && (
              <div className="flex items-center gap-1 mb-2 flex-wrap">
                <span className="text-[10px] text-gray-600 shrink-0">标签</span>
                {tagFacets.map(f => {
                  const on = tags.includes(f.kw);
                  return (
                    <button key={f.kw}
                      className={`px-1.5 py-0.5 rounded border text-[10px] transition-colors ${
                        on ? 'border-info/60 bg-info/20 text-info'
                           : 'border-border bg-surface-3 text-gray-400 hover:border-gray-500'}`}
                      title={`${f.n} 张话题卡含此标签（点选筛选，多选为 AND）`}
                      onClick={() => toggleTag(f.kw)}>
                      {f.kw} {f.n}
                    </button>
                  );
                })}
                {tags.length > 0 && (
                  <button className="text-[10px] text-gray-500 hover:text-red-400 shrink-0"
                    title="清除全部已选标签"
                    onClick={() => setTags([])}>
                    清除
                  </button>
                )}
              </div>
            )}
            <div className="flex-1 min-h-0 overflow-auto pr-1 space-y-1.5">
              {shownDrafts.length === 0 && shownTopics.length === 0 ? (
                <div className="text-xs text-gray-500">
                  {query
                    ? '无匹配话题（调整搜索词或筛选条件）'
                    : tags.length > 0
                      ? '无同时命中所选标签的话题（减少标签或清除筛选）'
                      : statusFilter === 'all'
                        ? '窗口内暂无话题卡——「重新 AI 分类」生成分段，或等待同步后自动聚类'
                        : `该状态暂无卡片（全部 ${dayTopics.length} 张）`}
                </div>
              ) : (
                <>
                  {shownDrafts.length > 0 && (
                    <div className="text-[10px] text-gray-500 pt-0.5">
                      候选段（勾选后「生成话题卡」；未提交不入库）
                    </div>
                  )}
                  {shownDrafts.map(d => (
                    <label key={`draft-${d.window?.[0] || ''}-${d.title}`}
                      className="flex items-start gap-2 cursor-pointer"
                      onMouseEnter={() => setHoverKey(`draft-${d.window?.[0] || ''}-${d.title}`)}
                      onMouseLeave={() => setHoverKey(null)}
                      onClick={() => setSelectedKey(prev =>
                        prev === `draft-${d.window?.[0] || ''}-${d.title}` ? null
                          : `draft-${d.window?.[0] || ''}-${d.title}`)}>
                      <input type="checkbox" className="mt-2.5 shrink-0"
                        checked={checked.has(drafts.indexOf(d))}
                        onChange={() => {
                          const di = drafts.indexOf(d);
                          setChecked(prev => {
                            const next = new Set(prev);
                            if (next.has(di)) next.delete(di); else next.add(di);
                            return next;
                          });
                        }} />
                      <div className="flex-1 min-w-0">
                        <TopicCard topic={d as FeishuTopic} draft onRefresh={onCommitted} />
                      </div>
                    </label>
                  ))}
                  {shownDrafts.length > 0 && shownTopics.length > 0 && (
                    <div className="text-[10px] text-gray-500 pt-1.5">话题卡</div>
                  )}
                  {shownTopics.map(t => (
                    <div key={t.id}
                      onMouseEnter={() => setHoverKey(t.id || '')}
                      onMouseLeave={() => setHoverKey(null)}
                      onClick={() => setSelectedKey(prev => prev === t.id ? null : t.id)}>
                      <TopicCard topic={t} onRefresh={onCommitted}
                        selected={selectedKey === t.id}
                        onSelect={() => setSelectedKey(prev => prev === t.id ? null : t.id)}
                        relatedCount={(relatedMap[t.id] || []).length}
                        onOpenRelations={() => setRelateDrawer(t)}
                        onEdit={() => setEditingTopic(t)} />
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="text-xs text-gray-500">请先选择群聊与日期。</div>
      )}
      {/* T-1001 F3：编辑弹框（左原文右话题并排；F4 勾选消息手动重关联） */}
      {editingTopic && (
        <TopicEditModal topic={editingTopic}
          onClose={() => setEditingTopic(null)}
          onSaved={onCommitted} />
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
      {/* T-993：跨群推荐面板（预筛清单 + 可选模型精筛 + 关联/忽略） */}
      {crossOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8"
          onClick={() => setCrossOpen(false)}>
          <div className="w-[760px] max-w-[94vw] border border-border rounded-lg p-4 bg-surface-2"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold">🔗 跨群同主题候选（只推荐不合并，关联需人工确认）</span>
              <button className={btn} onClick={runRefine} disabled={refining}
                title="用 text 模型逐对复核是否同一主题（未配置时诚实降级为预筛结果）">
                {refining ? '精筛中…' : '模型精筛'}
              </button>
              {unrefined && (
                <span className="text-[10px] text-amber-400">未经模型复核（未配置 text 模型或不可达）</span>
              )}
              <button className="ml-auto text-gray-500 hover:text-gray-300"
                onClick={() => setCrossOpen(false)}>✕</button>
            </div>
            {crossSugg.length === 0 ? (
              <div className="text-xs text-gray-500 text-center py-6">
                暂无跨群候选（预筛条件：跨群 + 同分类非闲聊 + 时间近 7 天 + 标题相似或关键词交集）
              </div>
            ) : crossSugg.map(c => {
              const a = topicById[c.src];
              const b = topicById[c.dst];
              if (!a || !b) return null;
              const pairRelated = (relatedMap[c.src] || []).includes(c.dst);
              return (
                <div key={`${c.src}|${c.dst}`}
                  className="mb-2 p-2 rounded border border-border bg-surface-3/60">
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {[a, b].map(t => (
                      <div key={t.id} className="min-w-0">
                        <div className="text-gray-200 truncate" title={t.title}>{t.title}</div>
                        <div className="text-[10px] text-gray-500 truncate">
                          {chatNameOf(t.chat_sha8)} · {String(t.window?.[0] || '').slice(5, 16)}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 text-[10px] flex-wrap">
                    <span className="text-gray-500">{c.reasons.join('；')} · 分 {c.score}</span>
                    {c.refined && (
                      <span className={c.llm_same ? 'text-green-400' : 'text-gray-500'}>
                        模型：{c.llm_same ? '同一主题' : '不同主题'}（{c.llm_confidence}）{c.llm_reason}
                      </span>
                    )}
                    {!pairRelated ? (
                      <span className="ml-auto flex gap-2">
                        <button className="text-emerald-400 hover:underline"
                          onClick={() => relate(c.src, c.dst, true)}>🔗 关联</button>
                        <button className="text-gray-500 hover:text-red-400"
                          title="忽略（留痕，不再重复推荐）"
                          onClick={() => relate(c.src, c.dst, false)}>忽略</button>
                      </span>
                    ) : (
                      <span className="ml-auto text-emerald-400">已关联 ✓</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {/* T-993：关联抽屉（多群证据并排 + 跳原文 + 解除关联） */}
      {relateDrawer && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8"
          onClick={() => setRelateDrawer(null)}>
          <div className="w-[760px] max-w-[94vw] border border-border rounded-lg p-4 bg-surface-2"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold">🔗 跨群关联（{(relatedMap[relateDrawer.id] || []).length + 1} 群并排）</span>
              <button className="ml-auto text-gray-500 hover:text-gray-300"
                onClick={() => setRelateDrawer(null)}>✕</button>
            </div>
            <div className="grid grid-cols-1 gap-2">
              {[relateDrawer, ...(relatedMap[relateDrawer.id] || [])
                .map(id => topicById[id]).filter(Boolean)].map((t, i) => (
                <div key={t.id} className="p-2 rounded border border-border bg-surface-3/60
                  flex items-start gap-2 text-xs">
                  <span className="text-[10px] text-gray-600 shrink-0 mt-0.5">
                    {i === 0 ? '本卡' : `群${i + 1}`}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-gray-200 truncate" title={t.title}>{t.title}</div>
                    <div className="text-[10px] text-gray-500">
                      {chatNameOf(t.chat_sha8)} · {String(t.window?.[0] || '').slice(5, 16)}
                      {t.category ? ` · ${t.category}` : ''}
                    </div>
                    <div className="text-[10px] text-gray-400 truncate mt-0.5">{t.summary}</div>
                  </div>
                  <button className="text-info hover:underline text-[10px] shrink-0"
                    onClick={() => jumpToTopic(t)}>跳原文 →</button>
                  {i > 0 && (
                    <button className="text-gray-500 hover:text-red-400 text-[10px] shrink-0"
                      title="解除该关联（写 rejected 留痕）"
                      onClick={() => relate(relateDrawer.id, t.id, false)}>解除</button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
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
