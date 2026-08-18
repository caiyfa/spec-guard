// FeishuWatchSettings.tsx — 飞书同步设置（监听范围配置）共享组件。
// 自包含按钮+弹层：群聊勾选 / 用户搜索+scopes / 按用户搜文档（搜索选人）/ 链接粘贴解析。
// 历史挂在 FeishuReviewPanel（T-915）；抽出共享供材料池页与关联复核页复用
// ——同步范围即授权范围（watch 配置 = 显式授权载体），保存即拉起监听（T-924）。
// T-937 体验修复：①弹层秒开（立即渲染+骨架，watch/群聊列表并行加载，不再串行阻塞）；
// ②去 ID 手填（群聊失败→重试；文档粘贴链接自动解析，裸 token 仍兼容）；
// ③文档检索目标改为通讯录搜索+已配置快捷标签（不再要求先加监听人）。

import { useEffect, useRef, useState } from 'react';
import { feishuPoolApi, type FeishuWatch,
        type FeishuWatchUser, type FeishuChatItem, type FeishuUserItem,
        type FeishuUserDocItem, type LarkStatus, type LarkLoginResult } from '../api';

export default function FeishuWatchSettings({ onSaved }: { onSaved?: () => void }) {
  const [open, setOpen] = useState(false);
  const [watch, setWatch] = useState<FeishuWatch | null>(null);
  const [chatSelList, setChatSelList] = useState<FeishuChatItem[]>([]);
  const [chatSel, setChatSel] = useState<Set<string>>(new Set());
  const [chatsLoading, setChatsLoading] = useState(false);
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
  const [authPending, setAuthPending] = useState<LarkLoginResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopAuthPoll = () => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);   // 兼容 timeout/interval id（同一 id 池）
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };
  useEffect(() => stopAuthPoll, []);   // 组件卸载清理轮询

  const btn = 'px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';

  // ── 弹层秒开：点击立即渲染骨架，数据并行加载填充 ──
  const openWatch = () => {
    setError(''); setNotice('');
    setWatch(null); setChatSelList([]); setChatSel(new Set());
    setWatchUsers([]); setUserResults([]);
    setDocOwner(null); setDocUserResults([]); setDocSelList([]); setDocSel(new Set());
    setLinkInput(''); setNameQuery('');
    setAuthPending(null);
    setOpen(true);
    void loadWatch();
    void loadChats();
    larkStatus().then(setAuthStatus).catch(() => setAuthStatus(null));
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
      // docs 回显到勾选列表（title 可读呈现；不再 textarea 裸 token 回显）
      const docs = (w.docs || []).map(d => ({
        token: d.token, title: d.title || '', url: d.url || '',
        doc_type: '', owner_id: d.owner_open_id || '', owner_name: '',
      }));
      setDocSelList(docs);
      setDocSel(new Set(docs.map(d => d.token)));
    } catch (e: any) { setError(e.message); }
  };

  const loadChats = async () => {
    setChatsLoading(true);
    try {
      const r = await feishuPoolApi.listChats();
      setChatSelList(r.items || []);
      if (r.errors?.length) setError(`群聊列表加载：${r.errors.join('；')}`);
    } catch (e: any) { setError(`群聊列表加载失败：${e.message}`); }
    finally { setChatsLoading(false); }
  };

  const saveWatch = async () => {
    if (!watch) return;
    setBusy('watch'); setError('');
    try {
      // 已配置项保留（CLI 列表未覆盖到时防丢）+ 勾选列表合并，勾选为准
      const chatMap = new Map<string, { chat_id: string; name?: string }>();
      (watch.chats || []).forEach(c => { if (chatSel.has(c.chat_id)) chatMap.set(c.chat_id, c); });
      chatSelList.filter(c => chatSel.has(c.chat_id))
        .forEach(c => { if (!chatMap.has(c.chat_id)) chatMap.set(c.chat_id, { chat_id: c.chat_id, name: c.name }); });
      const cfg: FeishuWatch = {
        ...watch,
        chats: [...chatMap.values()],
        docs: docSelList.filter(d => docSel.has(d.token)).map(d => ({
          token: d.token,
          url: d.url || undefined,
          owner_open_id: d.owner_id || undefined,
          title: d.title || undefined,
        })),
        users: watchUsers,
      };
      await feishuPoolApi.putWatch(cfg);
      setNotice('同步范围已保存（即授权范围），监听已按配置拉起');
      setOpen(false);
      onSaved?.();
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
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8"
          onClick={() => setOpen(false)}>
          <div className="w-[720px] max-w-[92vw] border border-border rounded-lg p-4 bg-surface-2"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold">同步设置（同步范围即授权范围 · 保存即拉起监听）</h3>
              <div className="flex gap-2">
                <button className={btn} onClick={saveWatch}
                  disabled={busy === 'watch' || !watch}>保存</button>
                <button className={btn} onClick={() => { stopAuthPoll(); setOpen(false); }}>取消</button>
              </div>
            </div>

            {/* 飞书授权块（T-942：未绑定/缺权限在弹层内闭环，无需接触服务器） */}
            {authPending ? (
              <div className="mb-2 p-3 rounded border border-amber-500/40 bg-amber-500/5">
                <div className="text-xs text-amber-300 mb-2">等待飞书授权完成…（用飞书 App 扫码，或打开授权链接）</div>
                <div className="flex items-start gap-3">
                  {authPending.qr_data_uri && (
                    <img src={authPending.qr_data_uri} alt="飞书授权二维码"
                      className="w-36 h-36 bg-white rounded p-1 shrink-0" />
                  )}
                  <div className="min-w-0 text-[11px] break-all">
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
              <div className="mb-2 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 flex items-center gap-2 text-xs">
                <span className="text-amber-300">
                  ⚠ {authStatus?.bound
                    ? `当前授权缺少部分权限（${authStatus.identity_name}），重新授权一次补全全部域`
                    : '飞书账号未绑定或授权不全，点击右侧按钮完成/补全授权'}
                </span>
                <button className={btn} onClick={startAuth}>{authStatus?.bound ? '重新授权' : '绑定飞书'}</button>
              </div>
            ) : authStatus && !authStatus.bound ? (
              <div className="mb-2 px-3 py-2 rounded bg-red-500/10 border border-red-500/30 flex items-center gap-2 text-xs">
                <span className="text-red-400">⚠ 飞书账号未绑定（群聊/用户/文档搜索不可用）</span>
                <button className={btn} onClick={startAuth}>绑定飞书</button>
              </div>
            ) : authStatus?.bound && (authStatus.reviewing || (authStatus.missing_scopes?.length)) ? (
              // T-943：已绑定但必需 scope 缺失——刚授权→审核中；否则引导重新授权
              <div className="mb-2 px-3 py-2 rounded bg-amber-500/10 border border-amber-500/30 flex items-center gap-2 text-xs flex-wrap">
                <span className="text-amber-300">
                  {authStatus.reviewing
                    ? `⏳ ${authStatus.identity_name}：授权已提交，${authStatus.missing_scopes?.length} 项权限管理员审核中（审核通过后自动生效，稍后重试即可）`
                    : `⚠ ${authStatus.identity_name}：已绑定但缺 ${authStatus.missing_scopes?.length} 项权限，重新授权一次补全`}
                </span>
                {authStatus.reviewing
                  ? <button className={btn} onClick={() => onAuthDone()}>审核通过后点此刷新</button>
                  : <button className={btn} onClick={startAuth}>重新授权</button>}
              </div>
            ) : authStatus?.bound ? (
              <div className="mb-2 text-[11px] text-gray-600 flex items-center gap-2">
                <span className="text-green-500">●</span> 飞书已绑定：{authStatus.identity_name}
                <button className="text-gray-500 hover:text-gray-300" onClick={startAuth}>重新授权</button>
              </div>
            ) : (
              <div className="mb-2 text-[11px] text-gray-600 flex items-center gap-2">
                <span className="text-gray-500">● 授权状态未知</span>
                <button className="text-gray-500 hover:text-gray-300" onClick={startAuth}>重新授权</button>
              </div>
            )}
            {/* 授权类错误不在红框重复显示（顶部黄横幅已给提示与按钮） */}
            {error && !/授权缺少权限|未绑定/.test(error) && (
              <div className="mb-2 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>
            )}
            {notice && <div className="mb-2 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}

            {!watch ? (
              <div className="py-10 text-center text-xs text-gray-500">配置加载中…</div>
            ) : (
              <div className="grid grid-cols-1 gap-3">
                {/* 群聊区：列表勾选（CLI 加载；失败重试，不提供手填） */}
                <div>
                  <div className="text-[11px] text-gray-500 mb-1">
                    授权群聊（勾选我的群聊；单聊本期不支持监听）</div>
                  <div className="max-h-36 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1">
                    {chatsLoading
                      && <div className="text-[11px] text-gray-500">群聊列表加载中（飞书 CLI）…</div>}
                    {!chatsLoading && chatSelList.length === 0
                      && <div className="flex items-center gap-2 text-[11px] text-gray-600">
                        群聊列表为空（或加载失败）
                        <button className={btn} onClick={loadChats}>重试</button>
                      </div>}
                    {chatSelList.map(c => (
                      <label key={c.chat_id}
                        className={`flex items-center gap-2 text-xs ${c.chat_mode === 'p2p' ? 'opacity-40' : 'cursor-pointer'}`}>
                        <input type="checkbox" disabled={c.chat_mode === 'p2p'}
                          checked={chatSel.has(c.chat_id)}
                          onChange={e => {
                            const next = new Set(chatSel);
                            if (e.target.checked) next.add(c.chat_id); else next.delete(c.chat_id);
                            setChatSel(next);
                          }} />
                        <span className="text-gray-200">{c.name || c.chat_id}</span>
                        <code className="text-[10px] text-gray-600">
                          {c.chat_id}{c.chat_mode === 'p2p' ? ' · 单聊' : ''}</code>
                      </label>
                    ))}
                  </div>
                </div>

                {/* 用户区：搜索选择 + scopes */}
                <div>
                  <div className="text-[11px] text-gray-500 mb-1">监听用户（群消息按发送人过滤 / 用户产出妙记 / 用户产出文档）</div>
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info"
                      value={userQuery} onChange={e => setUserQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchUsers()}
                      placeholder="姓名 / 邮箱关键词" />
                    <button className={btn} onClick={searchUsers} disabled={busy === 'user-search'}>搜索</button>
                  </div>
                  {userResults.length > 0 && (
                    <div className="max-h-28 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1 mb-1.5">
                      {userResults.map(u => (
                        <div key={u.open_id} className="flex items-center gap-2 text-xs">
                          <span className="text-gray-200">{u.name || u.open_id}</span>
                          <span className="text-[10px] text-gray-600">
                            {u.department}{u.email ? ` · ${u.email}` : ''}</span>
                          <button className={btn} onClick={() => addUser(u)}
                            disabled={watchUsers.some(w => w.open_id === u.open_id)}>添加</button>
                        </div>
                      ))}
                    </div>
                  )}
                  {watchUsers.length > 0 && (
                    <div className="bg-surface-3 border border-border rounded p-2 space-y-1">
                      {watchUsers.map(u => (
                        <div key={u.open_id} className="flex items-center gap-3 text-xs">
                          <span className="text-gray-200 w-20 truncate">{u.name || u.open_id}</span>
                          {([['group_sender', '群消息'], ['minutes', '妙记'], ['docs', '文档']] as const)
                            .map(([s, label]) => (
                              <label key={s} className="flex items-center gap-1 text-gray-400 cursor-pointer">
                                <input type="checkbox" checked={u.scopes.includes(s)}
                                  onChange={() => toggleScope(u.open_id, s)} />{label}
                              </label>
                            ))}
                          <button className="ml-auto text-[11px] text-red-400 hover:text-red-300"
                            onClick={() => setWatchUsers(watchUsers.filter(w => w.open_id !== u.open_id))}>
                            移除</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* 文档区：三条独立路径（按名搜/按用户/粘链接）+ 勾选清单 */}
                <div>
                  <div className="text-[11px] text-gray-500 mb-1">
                    添加监听文档（三条独立路径任选：按文档名搜 / 按用户检索 / 粘贴链接）</div>
                  {/* 路径 A：按文档名全局搜索（无需选人） */}
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info"
                      value={nameQuery} onChange={e => setNameQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchDocsByName()}
                      placeholder="按文档名搜索（如：ERD 评审），结果带产出人标注" />
                    <button className={btn} onClick={searchDocsByName}
                      disabled={busy === 'name-search' || !nameQuery.trim()}>搜文档</button>
                  </div>
                  {/* 路径 B：按用户检索（选人 → 搜其产出） */}
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info"
                      value={docUserQuery} onChange={e => setDocUserQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchDocUsers()}
                      placeholder="按用户检索：搜通讯录姓名 → 选为检索目标" />
                    <button className={btn} onClick={searchDocUsers}
                      disabled={busy === 'doc-user-search' || !docUserQuery.trim()}>搜用户</button>
                  </div>
                  {docUserResults.length > 0 && (
                    <div className="max-h-24 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1 mb-1.5">
                      {docUserResults.map(u => (
                        <div key={u.open_id} className="flex items-center gap-2 text-xs">
                          <span className="text-gray-200">{u.name || u.open_id}</span>
                          <span className="text-[10px] text-gray-600">{u.department}</span>
                          <button className={btn}
                            onClick={() => { setDocOwner({ open_id: u.open_id, name: u.name }); setDocUserResults([]); }}>
                            选为检索目标</button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    {docOwner && (
                      <span className="px-2 py-0.5 rounded bg-info/15 text-info text-[11px]">
                        检索目标：{docOwner.name || docOwner.open_id}
                        <button className="ml-1 text-gray-500 hover:text-gray-300"
                          onClick={() => setDocOwner(null)}>×</button>
                      </span>
                    )}
                    {docQuickUsers.map(u => (
                      <button key={u.open_id}
                        className={`px-2 py-0.5 rounded text-[11px] border border-border ${docOwner?.open_id === u.open_id ? 'bg-info/20 text-info' : 'text-gray-400 hover:text-gray-200'}`}
                        onClick={() => setDocOwner({ open_id: u.open_id, name: u.name || u.open_id })}>
                        {u.name || u.open_id}</button>
                    ))}
                    <input className="flex-1 min-w-[140px] bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info"
                      value={docQuery} onChange={e => setDocQuery(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && searchUserDocs()}
                      placeholder="文档关键词（可空）" />
                    <button className={btn} onClick={searchUserDocs}
                      disabled={busy === 'doc-search' || !docOwner}>搜文档</button>
                  </div>
                  <div className="flex gap-2 mb-1.5">
                    <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info"
                      value={linkInput} onChange={e => setLinkInput(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && resolveLink()}
                      placeholder="粘贴飞书云文档链接（/docx/ 或 /wiki/），token 自动解析" />
                    <button className={btn} onClick={resolveLink}
                      disabled={busy === 'resolve' || !linkInput.trim()}>解析</button>
                  </div>
                  {docSelList.length > 0 && (
                    <div className="max-h-32 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1">
                      {docSelList.map(d => (
                        <label key={d.token} className="flex items-center gap-2 text-xs cursor-pointer">
                          <input type="checkbox" checked={docSel.has(d.token)}
                            onChange={e => {
                              const next = new Set(docSel);
                              if (e.target.checked) next.add(d.token); else next.delete(d.token);
                              setDocSel(next);
                            }} />
                          <span className="text-gray-200 truncate">{d.title || d.token}</span>
                          {d.title && <code className="text-[10px] text-gray-600">{d.token.slice(0, 12)}…</code>}
                          {d.owner_name && <span className="text-[10px] text-gray-600">{d.owner_name}</span>}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            <div className="mt-2 text-[11px] text-gray-500">
              妙记同步窗口 {watch?.minutes_days ?? '—'} 天 · 群聊窗口 {watch?.chat_days ?? '—'} 天（在 feishu_watch.yaml 中调整）
            </div>
          </div>
        </div>
      )}
    </>
  );
}
