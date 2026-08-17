// FeishuWatchSettings.tsx — 飞书同步设置（监听范围配置）共享组件。
// 自包含按钮+弹层：群聊勾选 / 用户搜索+scopes / 按用户搜文档。
// 历史挂在 FeishuReviewPanel（T-915）；抽出共享供材料池页与关联复核页复用
// ——同步范围即授权范围（watch 配置 = 显式授权载体），保存即拉起监听（T-924）。

import { useState } from 'react';
import { feishuPoolApi, type FeishuWatch,
        type FeishuWatchUser, type FeishuChatItem, type FeishuUserItem,
        type FeishuUserDocItem } from '../api';

export default function FeishuWatchSettings({ onSaved }: { onSaved?: () => void }) {
  const [open, setOpen] = useState(false);
  const [watch, setWatch] = useState<FeishuWatch | null>(null);
  const [watchChats, setWatchChats] = useState('');
  const [watchDocs, setWatchDocs] = useState('');
  const [chatSelList, setChatSelList] = useState<FeishuChatItem[]>([]);
  const [chatSel, setChatSel] = useState<Set<string>>(new Set());
  const [watchUsers, setWatchUsers] = useState<FeishuWatchUser[]>([]);
  const [userQuery, setUserQuery] = useState('');
  const [userResults, setUserResults] = useState<FeishuUserItem[]>([]);
  const [docOwner, setDocOwner] = useState('');
  const [docQuery, setDocQuery] = useState('');
  const [docSelList, setDocSelList] = useState<FeishuUserDocItem[]>([]);
  const [docSel, setDocSel] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const btn = 'px-3 py-1.5 rounded text-xs font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';

  const openWatch = async () => {
    setError(''); setNotice('');
    try {
      const w = await feishuPoolApi.getWatch();
      setWatch(w);
      setWatchChats((w.chats || []).map(c => c.chat_id).join('\n'));
      setWatchDocs((w.docs || []).map(d => d.token).join('\n'));
      setWatchUsers(w.users || []);
      // 群聊选择器数据源（失败诚实呈现，不阻断弹层）
      try {
        const r = await feishuPoolApi.listChats();
        setChatSelList(r.items || []);
        setChatSel(new Set((w.chats || []).map(c => c.chat_id)));
        if (r.errors?.length) setError(`群聊列表加载：${r.errors.join('；')}`);
      } catch (e: any) { setError(`群聊列表加载失败：${e.message}`); }
      setUserResults([]); setDocSelList([]); setDocSel(new Set());
      setOpen(true);
    } catch (e: any) { setError(e.message); }
  };

  const saveWatch = async () => {
    if (!watch) return;
    setBusy('watch'); setError('');
    try {
      // 手填兜底 + 勾选合并去重（勾选优先带 name/owner 标注）
      const chatMap = new Map<string, { chat_id: string; name?: string }>();
      chatSelList.filter(c => chatSel.has(c.chat_id))
        .forEach(c => chatMap.set(c.chat_id, { chat_id: c.chat_id, name: c.name }));
      watchChats.split('\n').map(s => s.trim()).filter(Boolean)
        .forEach(id => { if (!chatMap.has(id)) chatMap.set(id, { chat_id: id }); });
      const docMap = new Map<string,
        { token: string; url?: string; owner_open_id?: string }>();
      docSelList.filter(d => docSel.has(d.token))
        .forEach(d => docMap.set(d.token,
          { token: d.token, url: d.url, owner_open_id: d.owner_id }));
      watchDocs.split('\n').map(s => s.trim()).filter(Boolean)
        .forEach(t => { if (!docMap.has(t)) docMap.set(t, { token: t }); });
      const cfg: FeishuWatch = {
        ...watch,
        chats: [...chatMap.values()],
        docs: [...docMap.values()],
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

  const searchUserDocs = async () => {
    if (!docOwner) { setError('请先选择要检索的用户'); return; }
    setBusy('doc-search'); setError('');
    try {
      const r = await feishuPoolApi.searchUserDocs(docOwner, docQuery.trim());
      setDocSelList(r.items || []);
      if (r.errors?.length) setError(r.errors.join('；'));
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  return (
    <>
      <button className={btn} onClick={openWatch}>⚙ 同步设置</button>

      {open && watch && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 overflow-y-auto py-8"
          onClick={() => setOpen(false)}>
          <div className="w-[720px] max-w-[92vw] border border-border rounded-lg p-4 bg-surface-2"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold">同步设置（同步范围即授权范围 · 保存即拉起监听）</h3>
              <div className="flex gap-2">
                <button className={btn} onClick={saveWatch} disabled={busy === 'watch'}>保存</button>
                <button className={btn} onClick={() => setOpen(false)}>取消</button>
              </div>
            </div>
            {error && <div className="mb-2 px-3 py-2 rounded bg-red-500/10 text-red-400 text-xs">{error}</div>}
            {notice && <div className="mb-2 px-3 py-2 rounded bg-green-500/10 text-green-400 text-xs">{notice}</div>}

            <div className="grid grid-cols-1 gap-3">
              {/* 群聊区：列表勾选 + 手填兜底 */}
              <div>
                <div className="text-[11px] text-gray-500 mb-1">授权群聊（勾选我的群聊；单聊本期不支持监听）</div>
                <div className="max-h-36 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1">
                  {chatSelList.length === 0
                    && <div className="text-[11px] text-gray-600">群聊列表为空（或未认证）</div>}
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
                <div className="text-[11px] text-gray-500 mt-2 mb-1">手填补充（chat_id 每行一个，与勾选合并去重）</div>
                <textarea className="w-full h-16 bg-surface-3 border border-border rounded px-2 py-1.5 text-xs text-gray-200 outline-none focus:border-info"
                  value={watchChats} onChange={e => setWatchChats(e.target.value)}
                  placeholder="oc_xxxxxxxx" />
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

              {/* 文档区：按用户搜索 + 手填兜底 */}
              <div>
                <div className="text-[11px] text-gray-500 mb-1">
                  按用户搜文档（召回 = 当前用户可见文档 ∩ 该用户产出）</div>
                <div className="flex gap-2 mb-1.5">
                  <select className="bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200"
                    value={docOwner} onChange={e => setDocOwner(e.target.value)}>
                    <option value="">选择用户</option>
                    {watchUsers.filter(u => u.scopes.includes('docs')).map(u => (
                      <option key={u.open_id} value={u.open_id}>{u.name || u.open_id}</option>
                    ))}
                  </select>
                  <input className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-200 outline-none focus:border-info"
                    value={docQuery} onChange={e => setDocQuery(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && searchUserDocs()}
                    placeholder="关键词（可空）" />
                  <button className={btn} onClick={searchUserDocs} disabled={busy === 'doc-search'}>搜索</button>
                </div>
                {docSelList.length > 0 && (
                  <div className="max-h-28 overflow-y-auto bg-surface-3 border border-border rounded p-2 space-y-1">
                    {docSelList.map(d => (
                      <label key={d.token} className="flex items-center gap-2 text-xs cursor-pointer">
                        <input type="checkbox" checked={docSel.has(d.token)}
                          onChange={e => {
                            const next = new Set(docSel);
                            if (e.target.checked) next.add(d.token); else next.delete(d.token);
                            setDocSel(next);
                          }} />
                        <span className="text-gray-200">{d.title || d.token}</span>
                        <span className="text-[10px] text-gray-600">{d.doc_type} · {d.owner_name}</span>
                      </label>
                    ))}
                  </div>
                )}
                <div className="text-[11px] text-gray-500 mt-2 mb-1">手填文档 token（每行一个，与勾选合并去重）</div>
                <textarea className="w-full h-16 bg-surface-3 border border-border rounded px-2 py-1.5 text-xs text-gray-200 outline-none focus:border-info"
                  value={watchDocs} onChange={e => setWatchDocs(e.target.value)}
                  placeholder="FBxodQkaJoUicrxdk67cUkbhnwc" />
              </div>
            </div>

            <div className="mt-2 text-[11px] text-gray-500">
              妙记同步窗口 {watch.minutes_days} 天 · 群聊窗口 {watch.chat_days} 天（在 feishu_watch.yaml 中调整）
            </div>
          </div>
        </div>
      )}
    </>
  );
}
