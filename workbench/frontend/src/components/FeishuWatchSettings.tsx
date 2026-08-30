// FeishuWatchSettings.tsx — 飞书同步设置（监听范围配置）共享组件。
// T-944 分 tab（群聊/监听用户/监听文档）降信息密度：①群聊先加载最近
// 活跃 10 群秒出、后台继续取全量，搜索为前端本地过滤；②单聊本期不支持
// 不显示；③授权块常显不受 tab 切换影响。授权闭环见 T-942 注释。
// T-1004（总控人拍板）：「监听运行中」状态条与「当前监听范围」只读摘要
// 从主页收进本弹层——主页不再常驻两块卡，状态/范围与配置入口同处。
// T-1008（总控人 08-23 反馈弹层拥挤）：①顶部状态条/范围摘要/保存栏收进
// 新增「⚙ 通用」页签，页头只留一行合并状态（监听+授权）；②保存/取消
// 移固定页脚，内容区独立滚动；③页签选择持久化（sg-feishu-watch-tab，
// 体验基线①）；④通用页签承接定时同步与自动话题分类双阈值配置；
// ⑤监听用户页签补空态引导与诚实语义文案（群消息始终来自授权群全量）。

import { useEffect, useRef, useState } from 'react';
import { feishuPoolApi, FEISHU_CHAT_KINDS, type FeishuWatch,
        type FeishuWatchUser, type FeishuChatItem, type FeishuUserItem,
        type FeishuUserDocItem, type LarkStatus, type LarkLoginResult } from '../api';

// T-1004：监听范围用户 scope 标签（主页摘要同款口径）
const SCOPE_LABEL: Record<string, string> = {
  group_sender: '群消息', minutes: '妙记', docs: '文档',
};

type WatcherStatus = { running: boolean; count: number;
  watchers: { emp: string; events_received: number; last_event_at: string }[] };

// T-1008：页签持久化（体验基线①；非法值/隐私模式诚实回退 chats）
type WatchTab = 'chats' | 'users' | 'docs' | 'general';
const TAB_KEY = 'sg-feishu-watch-tab';
const readTab = (): WatchTab => {
  try {
    const v = localStorage.getItem(TAB_KEY);
    return v === 'users' || v === 'docs' || v === 'general' || v === 'chats' ? v : 'chats';
  } catch { return 'chats'; }
};

export default function FeishuWatchSettings({ onSaved }: { onSaved?: () => void }) {
  const [open, setOpen] = useState(false);
  const [tab, setTabRaw] = useState<WatchTab>(readTab);
  const [watch, setWatch] = useState<FeishuWatch | null>(null);
  const [chatSelList, setChatSelList] = useState<FeishuChatItem[]>([]);
  const [chatSel, setChatSel] = useState<Set<string>>(new Set());
  const [chatTopicDays, setChatTopicDays] = useState<Record<string, number>>({});
  // T-990：按群类型标签（话题分类先验/优先级信号；空=未标注）
  const [chatKind, setChatKind] = useState<Record<string, string>>({});
  const [chatsLoading, setChatsLoading] = useState(false);
  const [chatsFullLoaded, setChatsFullLoaded] = useState(false);
  const [chatFilter, setChatFilter] = useState('');
  const [watchUsers, setWatchUsers] = useState<FeishuWatchUser[]>([]);
  const [userQuery, setUserQuery] = useState('');
  const [userResults, setUserResults] = useState<FeishuUserItem[]>([]);
  const [docOwner, setDocOwner] = useState<{ open_id: string; name: string } | null>(null);
  const [docUserQuery, setDocUserQuery] = useState('');
  const [docUserResults, setDocUserResults] = useState<FeishuUserItem[]>([]);
  const [docQuery, setDocQuery] = useState('');
  const [nameQuery, setNameQuery] = useState('');
  const [docSelList, setDocSelList] = useState<FeishuUserDocItem[]>([]);
  const [docSel, setDocSel] = useState<Set<string>>(new Set());
  const [linkInput, setLinkInput] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  // T-942：飞书授权闭环（用户接触不到服务器——未绑定/缺权限在弹层内直接授权）
  const [authStatus, setAuthStatus] = useState<LarkStatus | null>(null);
  // T-1004：监听运行状态（主页状态卡迁入；开弹层即拉）
  const [watcher, setWatcher] = useState<WatcherStatus | null>(null);
  const [authPending, setAuthPending] = useState<LarkLoginResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const setTab = (t: WatchTab) => {
    setTabRaw(t);
    try { localStorage.setItem(TAB_KEY, t); } catch { /* 隐私模式不持久化 */ }
  };

  const stopAuthPoll = () => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);   // 兼容 timeout/interval id（同一 id 池）
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };
  useEffect(() => stopAuthPoll, []);   // 组件卸载清理轮询

  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';

  // ── 弹层秒开：点击立即渲染骨架，数据并行加载填充 ──
  const openWatch = () => {
    setError(''); setNotice('');
    setTabRaw(readTab());          // T-1008：恢复上次页签（体验基线①）
    setWatch(null); setChatSelList([]); setChatSel(new Set());
    setChatsFullLoaded(false); setChatFilter('');
    setWatchUsers([]); setUserResults([]);
    setDocOwner(null); setDocUserResults([]); setDocSelList([]); setDocSel(new Set());
    setLinkInput(''); setNameQuery('');
    setAuthPending(null);
    setOpen(true);
    void loadWatch();
    void loadChatsQuick();     // T-944：先出最近活跃 10 群，全量后台补齐
    larkStatus().then(setAuthStatus).catch(() => setAuthStatus(null));
    feishuPoolApi.watcherStatus().then(setWatcher).catch(() => setWatcher(null));
  };

  const larkStatus = () => feishuPoolApi.authStatus();   // feishu-pool 前缀（登录即可，无菜单门槛）

  // T-942：弹层内发起授权（--domain all 全域一次补齐）→ 二维码 + 轮询 → 自动重载
  const startAuth = async () => {
    setError(''); setNotice('');
    try {
      const r = await feishuPoolApi.authLogin();
      if (r.phase === 'waiting') {
        setAuthPending(r);
        if (r.verification_url) window.open(r.verification_url, '_blank');
        stopAuthPoll();
        // 递归 setTimeout（非 setInterval）：complete 后端随 CLI 阻塞可达 15s，
        // 固定间隔会堆积请求（用户实锄轮询不生效的成因之一）——上一轮
        // 检测返回后再排下一轮，天然串行。
        const tick = async () => {
          const done = await checkAuthOnce(r.device_code);
          if (!done && pollRef.current !== null) {
            pollRef.current = setTimeout(tick, 1000) as unknown as typeof pollRef.current;
          }
        };
        pollRef.current = setTimeout(tick, 1500) as unknown as typeof pollRef.current;
        setTimeout(() => stopAuthPoll(), 180000);
      } else if (r.phase === 'completed') {
        await onAuthDone();
      } else {
        setError(r.error || '发起授权失败');
      }
    } catch (e: any) { setError(e.message); }
  };

  // 单次检测：complete（CLI poll，用户完成后立即返回）→ 兜底 status。
  // 手动「已完成授权」按钮与自动轮询共用。返回是否已完成。
  const checkAuthOnce = async (deviceCode?: string): Promise<boolean> => {
    try {
      if (deviceCode) {
        const c = await feishuPoolApi.authComplete(deviceCode);
        if (c.phase === 'completed') { await onAuthDone(); return true; }
      }
      const s = await larkStatus();
      if (s.bound) { await onAuthDone(); return true; }
    } catch { /* 单次失败忽略 */ }
    return false;
  };

  const manualCheckAuth = async () => {
    if (!authPending) return;
    setNotice('正在检测授权状态…');
    const done = await checkAuthOnce(authPending.device_code);
    if (!done) setNotice('尚未检测到授权完成——请确认手机上已点「同意授权」后再试');
  };

  const onAuthDone = async () => {
    stopAuthPoll();
    setAuthPending(null);
    setNotice('飞书授权完成，正在重新加载群聊列表…');
    setAuthStatus(await larkStatus().catch(() => null));
    setChatsLoading(true);
    await loadChats();
  };

  const loadWatch = async () => {
    try {
      const w = await feishuPoolApi.getWatch();
      setWatch(w);
      setWatchUsers(w.users || []);
      setChatSel(new Set((w.chats || []).map(c => c.chat_id)));
      // T-946：按群话题窗口回显（缺省 7）
      const days: Record<string, number> = {};
      const kinds: Record<string, string> = {};
      (w.chats || []).forEach(c => {
        days[c.chat_id] = Number(c.topic_days ?? 7) || 0;
        kinds[c.chat_id] = c.kind || '';   // T-990：群类型标签回显
      });
      setChatTopicDays(days);
      setChatKind(kinds);
      // docs 回显到勾选列表（title 可读呈现；不再 textarea 裸 token 回显）
      const docs = (w.docs || []).map(d => ({
        token: d.token, title: d.title || '', url: d.url || '',
        doc_type: '', owner_id: d.owner_open_id || '', owner_name: '',
      }));
      setDocSelList(docs);
      setDocSel(new Set(docs.map(d => d.token)));
    } catch (e: any) { setError(e.message); }
  };

  // T-944：快速预览（最近活跃 10 群，秒出）→ 后台继续全量，全量到后本地搜索覆盖全部群。
  // 缓存命中时全量接口也是秒回，两次请求代价可接受；quick 失败静默由全量兑底。
  const loadChatsQuick = async () => {
    setChatsLoading(true);
    try {
      const r = await feishuPoolApi.listChats(10);
      if ((r.items || []).length > 0 && !chatsFullLoaded) setChatSelList(r.items || []);
    } catch { /* 快速失败静默，全量兑底 */ }
    finally { setChatsLoading(false); }
    void loadChats();
  };

  const loadChats = async () => {
    setChatsLoading(true);
    try {
      const r = await feishuPoolApi.listChats();
      setChatSelList(r.items || []);
      setChatsFullLoaded(true);
      if (r.errors?.length) setError(`群聊列表加载：${r.errors.join('；')}`);
    } catch (e: any) { setError(`群聊列表加载失败：${e.message}`); }
    finally { setChatsLoading(false); }
  };

  const saveWatch = async () => {
    if (!watch) return;
    setBusy('watch'); setError(''); setNotice('');
    try {
      // 已配置项保留（CLI 列表未覆盖到时防丢）+ 勾选列表合并，勾选为准
      const chatMap = new Map<string, { chat_id: string; name?: string }>();
      (watch.chats || []).forEach(c => { if (chatSel.has(c.chat_id)) chatMap.set(c.chat_id, c); });
      chatSelList.filter(c => chatSel.has(c.chat_id))
        .forEach(c => { if (!chatMap.has(c.chat_id)) chatMap.set(c.chat_id, { chat_id: c.chat_id, name: c.name }); });
      const cfg: FeishuWatch = {
        ...watch,
        chats: [...chatMap.values()].map(c => ({
          ...c,
          kind: chatKind[c.chat_id] || '',     // T-990：群类型标签（空=未标注）
          topic_days: chatTopicDays[c.chat_id] ?? 7,   // T-946：按群话题窗口
        })),
        docs: docSelList.filter(d => docSel.has(d.token)).map(d => ({
          token: d.token,
          url: d.url || undefined,
          owner_open_id: d.owner_id || undefined,
          title: d.title || undefined,
        })),
        users: watchUsers,
      };
      const r = await feishuPoolApi.putWatch(cfg);
      // T-1008：按返回的监听启停状态诚实提示；未拉起/异常时弹层不关，
      // 避免「已拉起」假提示关门（此前 notice 写完后即关弹层，失败不可见）。
      if (r.watcher === 'started' || r.watcher === 'reloaded') {
        setNotice(r.watcher === 'started'
          ? '同步范围已保存（即授权范围），监听已拉起'
          : '同步范围已保存，运行中的监听已热更新');
        setOpen(false);
        onSaved?.();
      } else {
        setNotice(r.watcher === 'failed'
          ? '同步范围已保存，但监听拉起异常（可重试保存，或查看后端日志）'
          : '同步范围已保存；监听未自动拉起（用户身份或监听服务未就绪）');
        feishuPoolApi.watcherStatus().then(setWatcher).catch(() => undefined);
      }
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const searchUsers = async () => {
    if (!userQuery.trim()) return;
    setBusy('user-search'); setError('');
    try {
      const r = await feishuPoolApi.searchUsers(userQuery.trim());
      setUserResults(r.items || []);
      if (r.errors?.length) setError(r.errors.join('；'));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const addUser = (u: FeishuUserItem) => {
    if (watchUsers.some(w => w.open_id === u.open_id)) return;
    setWatchUsers([...watchUsers,
      { open_id: u.open_id, name: u.name, scopes: ['group_sender'] }]);
  };

  const toggleScope = (openId: string, scope: string) => {
    setWatchUsers(watchUsers.map(u => u.open_id !== openId ? u : {
      ...u,
      scopes: u.scopes.includes(scope)
        ? u.scopes.filter(s => s !== scope) : [...u.scopes, scope],
    }));
  };

  // ── 文档检索目标：通讯录搜索（任意用户）或已配置快捷标签 ──
  const searchDocUsers = async () => {
    if (!docUserQuery.trim()) return;
    setBusy('doc-user-search'); setError('');
    try {
      const r = await feishuPoolApi.searchUsers(docUserQuery.trim());
      setDocUserResults(r.items || []);
      if (r.errors?.length) setError(r.errors.join('；'));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  // ── 按文档名全局搜索（T-941：与按用户检索解耦——无需选人，直接搜名字）──
  const searchDocsByName = async () => {
    if (!nameQuery.trim()) return;
    setBusy('name-search'); setError('');
    try {
      const r = await feishuPoolApi.searchDocs(nameQuery.trim());
      mergeDocResults(r.items || []);
      if (r.errors?.length) setError(r.errors.join('；'));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const mergeDocResults = (items: FeishuUserDocItem[]) => {
    setDocSelList(prev => {
      const map = new Map(prev.map(d => [d.token, d]));
      items.forEach(d => map.set(d.token, d));
      return [...map.values()];
    });
  };

  const searchUserDocs = async () => {
    if (!docOwner) { setError('请先选择要检索的用户'); return; }
    setBusy('doc-search'); setError('');
    try {
      const r = await feishuPoolApi.searchUserDocs(docOwner.open_id, docQuery.trim());
      mergeDocResults(r.items || []);
      if (r.errors?.length) setError(r.errors.join('；'));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  // ── 链接粘贴解析：docx/wiki 链接或裸 token → 勾选列表 ──
  const resolveLink = async () => {
    const v = linkInput.trim();
    if (!v) return;
    setBusy('resolve'); setError('');
    try {
      const r = await feishuPoolApi.resolveDoc(v);
      const item = r.items?.[0];
      if (!r.ok || !item) { setError(r.error || '解析失败'); return; }
      setDocSelList(prev => prev.some(d => d.token === item.token) ? prev : [...prev, {
        token: item.token, title: item.title || '', url: item.url || '',
        doc_type: item.doc_type || '', owner_id: item.owner_open_id || '',
        owner_name: '',
      }]);
      setDocSel(prev => new Set(prev).add(item.token));
      setLinkInput('');
      setNotice(`已加入监听：${item.title || item.token}`);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const docQuickUsers = watchUsers.filter(u => u.scopes.includes('docs'));

  return (
    <>
      <button className={btn} onClick={openWatch}>⚙ 同步设置</button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 py-6"
          onClick={() => setOpen(false)}>
          {/* T-1008：固定高度弹层——页头/页脚固定，页签内容区独立滚动 */}
          <div className="w-[720px] max-w-[92vw] max-h-[88vh] flex flex-col border border-border rounded-lg p-4 bg-surface-2"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-fs-body font-semibold">同步设置（同步范围即授权范围 · 保存即拉起监听）</h3>
            </div>
            {/* T-1008：页头合并状态行（监听 + 授权一行流；详情在「⚙ 通用」页签） */}
            <div className="mb-2 text-fs-body text-gray-500 flex items-center gap-3 flex-wrap">
              {watcher?.running
                ? <span className="text-green-400">● 监听运行中（{watcher.count} 用户）</span>
                : <span>○ 监听未运行（保存后自动拉起）</span>}
              {authStatus?.bound && (
                <span>
                  <span className="text-green-500">●</span> 飞书已绑定：{authStatus.identity_name}
                  <button className="ml-1 text-gray-500 hover:text-gray-300" onClick={startAuth}>重新授权</button>
                </span>
              )}
            </div>

            {/* 飞书授权块（T-942：未绑定/缺权限在弹层内闭环，无需接触服务器） */}
            {authPending ? (
              <div className="mb-2 p-3 rounded border border-amber-500/40 bg-amber-500/5">
                <div className="text-fs-body text-amber-300 mb-2">等待飞书授权完成…（用飞书 App 扫码，或打开授权链接）</div>
                <div className="flex items-start gap-3">
                  {authPending.qr_data_uri && (
                    <img src={authPending.qr_data_uri} alt="飞书授权二维码"
                      className="w-36 h-36 bg-white rounded p-1 shrink-0" />
                  )}
                  <div className="min-w-0 text-fs-body break-all">
                    <a href={authPending.verification_url} target="_blank" rel="noreferrer"
                      className="text-info hover:underline">{authPending.verification_url}</a>
                    <div className="text-gray-500 mt-1">扫码同意后自动检测（自动检测中…）；若长时间未跳转，点下方按钮手动确认</div>
                    <div className="flex gap-2 mt-2">
                      <button className={btn} onClick={manualCheckAuth}>✓ 我已完成授权，立即检测</button>
                      <button className={btn} onClick={() => { stopAuthPoll(); setAuthPending(null); }}>
                        取消授权流程</button>
                    </div>
                  </div>
                </div>
              </div>
            ) : /授权缺少权限|missing_scope|未绑定|认证未就绪/.test(error) ? (
              // 错误已表明授权问题 → 无条件显示带按钮的块（不依赖 authStatus 是否拉到——
              // status 请求失败时 authStatus=null，旧条件四分支全不渲染致按钮消失，用户实锄）
              <div className="mb-2 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 flex items-center gap-2 text-fs-body">
                <span className="text-amber-300">
                  ⚠ {authStatus?.bound
                    ? `当前授权缺少部分权限（${authStatus.identity_name}），重新授权一次补全全部域`
                    : '飞书账号未绑定或授权不全，点击右侧按钮完成/补全授权'}
                </span>
                <button className={btn} onClick={startAuth}>{authStatus?.bound ? '重新授权' : '绑定飞书'}</button>
              </div>
            ) : authStatus && !authStatus.bound ? (
              <div className="mb-2 px-3 py-2 rounded bg-red-500/10 border border-red-500/30 flex items-center gap-2 text-fs-body">
                <span className="text-red-400">⚠ 飞书账号未绑定（群聊/用户/文档搜索不可用）</span>
                <button className={btn} onClick={startAuth}>绑定飞书</button>
              </div>
            ) : authStatus?.bound && (authStatus.reviewing || (authStatus.missing_scopes?.length)) ? (
              // T-943：已绑定但必需 scope 缺失——刚授权→审核中；否则引导重新授权
              <div className="mb-2 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 flex items-center gap-2 text-fs-body flex-wrap">
                <span className="text-amber-300">
                  {authStatus.reviewing
                    ? `⏳ ${authStatus.identity_name}：授权已提交，${authStatus.missing_scopes?.length} 项权限管理员审核中（审核通过后自动生效，稍后重试即可）`
                    : `⚠ ${authStatus.identity_name}：已绑定但缺 ${authStatus.missing_scopes?.length} 项权限，重新授权一次补全`}
                </span>
                {authStatus.reviewing
                  ? <button className={btn} onClick={() => onAuthDone()}>审核通过后点此刷新</button>
                  : <button className={btn} onClick={startAuth}>重新授权</button>}
              </div>
            ) : null}
            {/* 授权类错误不在红框重复显示（顶部黄横幅已给提示与按钮） */}
            {error && !/授权缺少权限|未绑定/.test(error) && (
              <div className="mb-2 px-3 py-2 rounded bg-red-500/10 text-red-400 text-fs-body">{error}</div>
            )}
            {notice && <div className="mb-2 px-3 py-2 rounded bg-green-500/10 text-green-400 text-fs-body">{notice}</div>}

            {!watch ? (
              <div className="py-10 text-center text-fs-body text-gray-500">配置加载中…</div>
            ) : (
              <>
              {/* T-1008 四页签：授权群聊/监听用户/监听文档/通用（状态与节奏配置收通用） */}
              <div className="flex items-center gap-1.5 mb-3 border-b border-border pb-2">
                {([['chats', '💬 授权群聊'], ['users', '👤 监听用户'],
                   ['docs', '📄 监听文档'], ['general', '⚙ 通用']] as const)
                  .map(([id, label]) => (
                    <button key={id} onClick={() => setTab(id)}
                      className={`px-3 py-1.5 rounded text-fs-body ${tab === id ? 'bg-info/15 text-info font-medium' : 'text-gray-400 hover:text-gray-200'}`}>
                      {label}{id === 'chats' && chatSel.size > 0 ? `（${chatSel.size}）` : ''}
                      {id === 'users' && watchUsers.length > 0 ? `（${watchUsers.length}）` : ''}
                      {id === 'docs' && docSel.size > 0 ? `（${docSel.size}）` : ''}
                    </button>
                  ))}
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto grid grid-cols-1 gap-3">
                {/* Tab 1 群聊：最近活跃先行 + 本地搜索 + 后台全量补齐；单聊不显示 */}
                {tab === 'chats' && (
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info"
                      value={chatFilter} onChange={e => setChatFilter(e.target.value)}
                      placeholder="搜索群名（本地过滤，已加载全部群后可搜全部）" />
                    <span className="text-fs-body text-gray-500 whitespace-nowrap">
                      {chatsLoading ? '加载中…' : `${chatSelList.length} 群${chatsFullLoaded ? '' : '（后台同步全部中…）'}`}
                    </span>
                    {!chatsFullLoaded && !chatsLoading && (
                      <button className={btn} onClick={() => void loadChats()}>拉取全部</button>
                    )}
                  </div>
                  <div className="max-h-56 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1">
                    {chatsLoading && chatSelList.length === 0
                      && <div className="text-fs-body text-gray-500">群聊列表加载中（最近活跃优先）…</div>}
                    {!chatsLoading && chatSelList.length === 0
                      && <div className="flex items-center gap-2 text-fs-body text-gray-600">
                        群聊列表为空（或加载失败）
                        <button className={btn} onClick={() => void loadChatsQuick()}>重试</button>
                      </div>}
                    {chatSelList
                      .filter(c => c.chat_mode !== 'p2p')            // T-944：单聊不显示
                      .filter(c => !chatFilter.trim()
                        || (c.name || '').includes(chatFilter.trim())
                        || c.chat_id.includes(chatFilter.trim()))
                      .map(c => (
                      <label key={c.chat_id} className="flex items-center gap-2 text-fs-body cursor-pointer">
                        <input type="checkbox"
                          checked={chatSel.has(c.chat_id)}
                          onChange={e => {
                            const next = new Set(chatSel);
                            if (e.target.checked) next.add(c.chat_id); else next.delete(c.chat_id);
                            setChatSel(next);
                          }} />
                        <span className="text-gray-200 truncate">{c.name || c.chat_id}</span>
                        <code className="text-fs-aux text-gray-600">{c.chat_id}</code>
                        {chatSel.has(c.chat_id) && (
                          <span className="ml-auto flex items-center gap-1 shrink-0 text-fs-aux text-gray-500">
                            <select
                              className="bg-surface-3 border border-border rounded px-1 py-0.5 text-fs-aux text-gray-300 outline-none focus:border-info"
                              value={chatKind[c.chat_id] || ''}
                              onChange={e => setChatKind(prev => ({
                                ...prev,
                                [c.chat_id]: e.target.value,
                              }))}
                              title="群类型标签（话题分类的先验信号；未标注也可正常监听）">
                              <option value="">未标注</option>
                              {FEISHU_CHAT_KINDS.map(k => <option key={k} value={k}>{k}</option>)}
                            </select>
                            话题
                            <input type="number" min={0} max={365}
                              className="w-12 bg-surface-3 border border-border rounded px-1 py-0.5 text-fs-aux text-gray-300 outline-none focus:border-info"
                              value={chatTopicDays[c.chat_id] ?? 7}
                              onChange={e => setChatTopicDays(prev => ({
                                ...prev,
                                [c.chat_id]: Math.max(0, Number(e.target.value) || 0),
                              }))}
                              title="只聚近 N 天快照生成话题；0=该群不生成" />
                            天
                          </span>
                        )}
                      </label>
                    ))}
                    {chatSelList.filter(c => c.chat_mode !== 'p2p').length > 0
                      && chatFilter.trim()
                      && chatSelList.filter(c => c.chat_mode !== 'p2p'
                        && ((c.name || '').includes(chatFilter.trim())
                          || c.chat_id.includes(chatFilter.trim()))).length === 0 && (
                      <div className="text-fs-body text-gray-600">
                        当前已加载的群中无匹配{chatsFullLoaded ? '' : '——后台同步全部群后可搜全部，或点「拉取全部」'}</div>
                    )}
                  </div>
                </div>
                )}

                {/* Tab 2 用户：搜索选择 + scopes（T-1008 诚实语义文案 + 空态引导） */}
                {tab === 'users' && (
                <div>
                  <div className="text-fs-body text-gray-500 mb-1">
                    监听用户 = 拉取该用户产出的妙记 / 文档，并作为材料页「按人筛选」维度。
                    群聊消息始终来自「授权群聊」全量入池，与是否添加用户无关。
                  </div>
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info"
                      value={userQuery} onChange={e => setUserQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchUsers()}
                      placeholder="姓名 / 邮箱关键词" />
                    <button className={btn} onClick={searchUsers} disabled={busy === 'user-search'}>搜索</button>
                  </div>
                  {userResults.length > 0 && (
                    <div className="max-h-28 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1 mb-1.5">
                      {userResults.map(u => (
                        <div key={u.open_id} className="flex items-center gap-2 text-fs-body">
                          <span className="text-gray-200">{u.name || u.open_id}</span>
                          <span className="text-fs-aux text-gray-600">
                            {u.department}{u.email ? ` · ${u.email}` : ''}</span>
                          <button className={btn} onClick={() => addUser(u)}
                            disabled={watchUsers.some(w => w.open_id === u.open_id)}>添加</button>
                        </div>
                      ))}
                    </div>
                  )}
                  {/* T-1008 空态引导：添加入口是「先搜后加」——此前空态只有搜索框，
                      用户报告找不到添加的地方 */}
                  {watchUsers.length === 0 && userResults.length === 0 && (
                    <div className="px-3 py-4 border border-dashed border-border rounded text-center text-fs-body text-gray-500">
                      还没有监听用户——在上方输入姓名 / 邮箱关键词搜索，在结果中点「添加」
                    </div>
                  )}
                  {watchUsers.length > 0 && (
                    <div className="bg-surface-3 border border-border rounded p-2 space-y-1">
                      {watchUsers.map(u => (
                        <div key={u.open_id} className="flex items-center gap-3 text-fs-body">
                          <span className="text-gray-200 w-20 truncate">{u.name || u.open_id}</span>
                          {([['group_sender', '群消息'], ['minutes', '妙记'], ['docs', '文档']] as const)
                            .map(([s, label]) => (
                              <label key={s} className="flex items-center gap-1 text-gray-400 cursor-pointer"
                                title={s === 'group_sender'
                                  ? '秒级事件直写只入这些发送人的消息（每日 03:00 校对仍全量入池对齐）；材料页按人筛选不依赖此项'
                                  : s === 'minutes' ? '每日轮询拉取该用户产出的妙记'
                                  : '每日轮询拉取该用户产出的文档'}>
                                <input type="checkbox" checked={u.scopes.includes(s)}
                                  onChange={() => toggleScope(u.open_id, s)} />{label}
                              </label>
                            ))}
                          <button className="ml-auto text-fs-body text-red-400 hover:text-red-300"
                            onClick={() => setWatchUsers(watchUsers.filter(w => w.open_id !== u.open_id))}>
                            移除</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                )}

                {/* Tab 3 文档：三条独立路径（按名搜/按用户/粘链接）+ 勾选清单 */}
                {tab === 'docs' && (
                <div>
                  <div className="text-fs-body text-gray-500 mb-1">
                    添加监听文档（三条独立路径任选：按文档名搜 / 按用户检索 / 粘贴链接）</div>
                  {/* 路径 A：按文档名全局搜索（无需选人） */}
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info"
                      value={nameQuery} onChange={e => setNameQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchDocsByName()}
                      placeholder="按文档名搜索（如：ERD 评审），结果带产出人标注" />
                    <button className={btn} onClick={searchDocsByName}
                      disabled={busy === 'name-search' || !nameQuery.trim()}>搜文档</button>
                  </div>
                  {/* 路径 B：按用户检索（选人 → 搜其产出） */}
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info"
                      value={docUserQuery} onChange={e => setDocUserQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchDocUsers()}
                      placeholder="按用户检索：搜通讯录姓名 → 选为检索目标" />
                    <button className={btn} onClick={searchDocUsers}
                      disabled={busy === 'doc-user-search' || !docUserQuery.trim()}>搜用户</button>
                  </div>
                  {docUserResults.length > 0 && (
                    <div className="max-h-24 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1 mb-1.5">
                      {docUserResults.map(u => (
                        <div key={u.open_id} className="flex items-center gap-2 text-fs-body">
                          <span className="text-gray-200">{u.name || u.open_id}</span>
                          <span className="text-fs-aux text-gray-600">{u.department}</span>
                          <button className={btn}
                            onClick={() => { setDocOwner({ open_id: u.open_id, name: u.name }); setDocUserResults([]); }}>
                            选为检索目标</button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    {docOwner && (
                      <span className="px-2 py-0.5 rounded bg-info/15 text-info text-fs-body">
                        检索目标：{docOwner.name || docOwner.open_id}
                        <button className="ml-1 text-gray-500 hover:text-gray-300"
                          onClick={() => setDocOwner(null)}>×</button>
                      </span>
                    )}
                    {docQuickUsers.map(u => (
                      <button key={u.open_id}
                        className={`px-2 py-0.5 rounded text-fs-body border border-border ${docOwner?.open_id === u.open_id ? 'bg-info/20 text-info' : 'text-gray-400 hover:text-gray-200'}`}
                        onClick={() => setDocOwner({ open_id: u.open_id, name: u.name || u.open_id })}>
                        {u.name || u.open_id}</button>
                    ))}
                    <input className="flex-1 min-w-[140px] bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info"
                      value={docQuery} onChange={e => setDocQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchUserDocs()}
                      placeholder="文档关键词（可空）" />
                    <button className={btn} onClick={searchUserDocs}
                      disabled={busy === 'doc-search' || !docOwner}>搜文档</button>
                  </div>
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info"
                      value={linkInput} onChange={e => setLinkInput(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && resolveLink()}
                      placeholder="粘贴飞书云文档链接（/docx/ 或 /wiki/），token 自动解析" />
                    <button className={btn} onClick={resolveLink}
                      disabled={busy === 'resolve' || !linkInput.trim()}>解析</button>
                  </div>
                  {docSelList.length > 0 && (
                    <div className="max-h-32 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1">
                      {docSelList.map(d => (
                        <label key={d.token} className="flex items-center gap-2 text-fs-body cursor-pointer">
                          <input type="checkbox" checked={docSel.has(d.token)}
                            onChange={e => {
                              const next = new Set(docSel);
                              if (e.target.checked) next.add(d.token); else next.delete(d.token);
                              setDocSel(next);
                            }} />
                          <span className="text-gray-200 truncate">{d.title || d.token}</span>
                          {d.title && <code className="text-fs-aux text-gray-600">{d.token.slice(0, 12)}…</code>}
                          {d.owner_name && <span className="text-fs-aux text-gray-600">{d.owner_name}</span>}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
                )}

                {/* Tab 4 通用（T-1008）：监听运行状态 / 范围摘要 / 同步节奏与自动话题分类 */}
                {tab === 'general' && (
                <div className="space-y-3">
                  {/* 监听运行状态详情（T-1004 状态条的完整版，自页头搬入） */}
                  <div className="px-3 py-2 rounded bg-surface-3/60 border border-border/50 text-fs-body">
                    <div className="flex items-center gap-3 flex-wrap">
                      {watcher?.running ? (
                        <>
                          <span className="text-green-400">● 监听运行中（{watcher.count} 用户）</span>
                          {watcher.watchers.map((w: any) => (
                            <span key={w.emp} className="text-gray-500">
                              {w.emp} · 事件 {w.events_received} · 最近 {w.last_event_at || '—'}
                            </span>
                          ))}
                        </>
                      ) : (
                        <>
                          <span className="text-gray-400">○ 监听未运行</span>
                          <span className="text-gray-600">保存同步范围后自动拉起；此前保存过仍未拉起时：</span>
                          <button className={btn} onClick={saveWatch}
                            disabled={busy === 'watch' || !watch}>保存并拉起监听</button>
                        </>
                      )}
                    </div>
                    <div className="text-gray-600 mt-1.5">
                      群消息近实时入池（事件秒级直写，保存监听范围即生效）· 每日 03:00 校对重拉对齐飞书侧
                      · 文档 07:00 / 妙记与用户材料 08:00 每日轮询
                    </div>
                  </div>

                  {/* 当前监听范围只读摘要（T-1004 摘要自页头搬入；编辑走前三个页签） */}
                  <div className="px-3 py-2 rounded bg-surface-3/60 border border-border/50 text-fs-body space-y-1.5">
                    <div className="flex items-start gap-2 flex-wrap">
                      <span className="text-gray-500 shrink-0 mt-0.5">监听用户</span>
                      {watchUsers.length === 0
                        ? <span className="text-gray-600">无（「👤 监听用户」页签添加）</span>
                        : watchUsers.map(u => (
                          <span key={u.open_id}
                            className="px-2 py-0.5 rounded border border-border text-gray-300">
                            {u.name || u.open_id}
                            <span className="ml-1 text-gray-500">
                              {u.scopes.map(x => SCOPE_LABEL[x] || x).join('/') || '无监听项'}
                            </span>
                          </span>
                        ))}
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-gray-500 shrink-0">授权群聊</span>
                      {(watch.chats || []).length === 0
                        ? <span className="text-gray-600">无（「💬 授权群聊」页签添加）</span>
                        : (watch.chats || []).map(c => (
                          <span key={c.chat_id}
                            className="px-2 py-0.5 rounded border border-border text-gray-300">
                            {c.kind && <span className="text-info mr-1">{c.kind}</span>}
                            {c.name || c.chat_id}
                          </span>
                        ))}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-500 shrink-0">监听文档</span>
                      <span className="text-gray-300">{docSel.size} 篇</span>
                      <span className="text-gray-600">（「📄 监听文档」页签添加）</span>
                    </div>
                  </div>

                  {/* 同步节奏与自动话题分类（T-952 定时同步自底部栏搬入；T-1008 双阈值新增） */}
                  <div className="px-3 py-2 rounded bg-surface-3/60 border border-border/50 text-fs-body space-y-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-gray-500 shrink-0">定时全量同步</span>
                      <input type="number" min={0} max={1440}
                        className="w-16 bg-surface-3 border border-border rounded px-1.5 py-0.5 text-fs-body text-gray-200 outline-none focus:border-info"
                        value={watch.chat_sync_minutes ?? 0}
                        onChange={e => setWatch(prev => prev ? {
                          ...prev, chat_sync_minutes: Number(e.target.value) || 0,
                        } : prev)} />
                      <span className="text-gray-600">分钟（0=关；事件秒级直写与每日校对不受影响）</span>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-gray-500 shrink-0">自动话题分类</span>
                      <span>积累</span>
                      <input type="number" min={0} max={1000}
                        className="w-16 bg-surface-3 border border-border rounded px-1.5 py-0.5 text-fs-body text-gray-200 outline-none focus:border-info"
                        value={watch.topic_auto_count ?? 50}
                        onChange={e => setWatch(prev => prev ? {
                          ...prev, topic_auto_count: Math.max(0, Number(e.target.value) || 0),
                        } : prev)} />
                      <span>条新消息即分类；未达条数时距上次</span>
                      <input type="number" min={0} max={1440}
                        className="w-16 bg-surface-3 border border-border rounded px-1.5 py-0.5 text-fs-body text-gray-200 outline-none focus:border-info"
                        value={watch.topic_auto_minutes ?? 60}
                        onChange={e => setWatch(prev => prev ? {
                          ...prev, topic_auto_minutes: Math.max(0, Number(e.target.value) || 0),
                        } : prev)} />
                      <span className="text-gray-600">分钟且有新消息也分类（0=各自关闭；少量消息也可能已是一个话题）</span>
                    </div>
                    <div className="text-gray-600">
                      妙记窗口 {watch.minutes_days ?? '—'} 天 · 群聊窗口 {watch.chat_days ?? '—'} 天
                      （按群话题窗口在「💬 授权群聊」页签逐群配置；text 模型未配置时自动分类诚实跳过）
                    </div>
                  </div>
                </div>
                )}
              </div>
              </>
            )}

            {/* T-1008：保存/取消移固定页脚（原在页头挤压状态区） */}
            <div className="mt-3 pt-3 border-t border-border flex items-center gap-2">
              <span className="mr-auto text-fs-body text-gray-600">保存即生效：监听按配置拉起或热更新</span>
              <button className={btn} onClick={saveWatch}
                disabled={busy === 'watch' || !watch}>{busy === 'watch' ? '保存中…' : '保存'}</button>
              <button className={btn} onClick={() => { stopAuthPoll(); setOpen(false); }}>取消</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
