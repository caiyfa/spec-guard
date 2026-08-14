// 菜单管理 + 角色管理 + 角色授权（RBAC，admin 默认可见）
import { useCallback, useEffect, useState } from 'react';
import { menusApi, rolesApi } from '../api';
import type { MenuRecord, RoleRecord } from '../api';
import Modal from '../components/Modal';

type Tab = 'menu' | 'roles' | 'grants';

export default function MenuRoles() {
  const [tab, setTab] = useState<Tab>('menu');
  const [menus, setMenus] = useState<MenuRecord[]>([]);
  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [m, r] = await Promise.all([menusApi.list(), rolesApi.list()]);
      setMenus(m.menus);
      setRoles(r.roles);
    } catch (e: any) {
      setError(e.message || '加载失败');
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const flash = (text: string) => {
    setMessage(text);
    setTimeout(() => setMessage(''), 2000);
  };

  return (
    <div className="max-w-5xl">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">🗂 菜单与角色授权</h2>
        <p className="text-xs text-gray-500 mt-1">
          菜单树入库可配置；角色授权控制页面可见性与后端接口访问（前后端双控）。
        </p>
      </div>
      {error && <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-700/50">{error}</div>}
      {message && <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-green-900/30 text-green-400 border border-green-700/50">{message}</div>}
      <div className="flex gap-2 mb-4">
        {([['menu', `菜单管理 (${menus.length})`], ['roles', `角色管理 (${roles.length})`], ['grants', '角色授权']] as [Tab, string][]).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-3 py-1.5 text-sm rounded ${tab === k ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'menu' && <MenuTab menus={menus} onChanged={refresh} flash={flash} setError={setError} />}
      {tab === 'roles' && <RolesTab roles={roles} onChanged={refresh} flash={flash} setError={setError} />}
      {tab === 'grants' && <GrantsTab roles={roles} menus={menus} flash={flash} setError={setError} />}
    </div>
  );
}

// ── 页签 1：菜单树管理 ──
function MenuTab({ menus, onChanged, flash, setError }: {
  menus: MenuRecord[]; onChanged: () => void; flash: (t: string) => void; setError: (t: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null); // null=关；''=新增分组；group key=新增子菜单
  const [draft, setDraft] = useState<Partial<MenuRecord>>({});

  const groups = menus.filter(m => !m.parent_key).sort((a, b) => a.sort - b.sort);
  const itemsOf = (g: string) => menus.filter(m => m.parent_key === g).sort((a, b) => a.sort - b.sort);

  const saveRow = async (menu_key: string) => {
    try {
      await menusApi.update(menu_key, draft);
      flash('已保存'); setEditing(null); onChanged();
    } catch (e: any) { setError(e.message); }
  };
  const create = async () => {
    try {
      await menusApi.create({ ...draft, parent_key: adding ?? '', visible: true });
      flash('已新增'); setAdding(null); setDraft({}); onChanged();
    } catch (e: any) { setError(e.message); }
  };
  const remove = async (menu_key: string) => {
    if (!window.confirm(`确认删除 ${menu_key}？其角色授权将一并清除`)) return;
    try { await menusApi.remove(menu_key); flash('已删除'); onChanged(); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <div className="space-y-2">
      <button onClick={() => setAdding('')} className="text-xs bg-info text-white rounded px-2 py-1">＋ 新增分组</button>
      {groups.map(g => (
        <div key={g.menu_key} className="bg-surface-2 border border-border rounded-lg p-3">
          <div className="flex items-center gap-2 text-sm text-gray-200 font-medium">
            <span>{g.icon}</span><span>{g.label}</span>
            {g.is_system ? <span className="text-[10px] bg-purple-900/50 text-purple-300 rounded px-1">系统</span> : null}
            <button onClick={() => setAdding(g.menu_key)} className="ml-auto text-xs text-gray-500 hover:text-gray-300">＋ 新增菜单</button>
          </div>
          <div className="mt-1 space-y-1 pl-4 border-l border-border/50">
            {itemsOf(g.menu_key).map(m => (
              <div key={m.menu_key} className="flex items-center gap-2 text-xs text-gray-400 py-0.5">
                <span className="font-mono text-gray-600">{m.menu_key}</span>
                {editing === m.menu_key ? (
                  <>
                    <input className="bg-surface-1 border border-border rounded px-1.5 py-0.5 w-24" value={draft.label ?? m.label}
                      onChange={e => setDraft({ ...draft, label: e.target.value })} />
                    <input className="bg-surface-1 border border-border rounded px-1.5 py-0.5 w-20" value={draft.path ?? m.path}
                      onChange={e => setDraft({ ...draft, path: e.target.value })} />
                    <button onClick={() => saveRow(m.menu_key)} className="text-info">保存</button>
                    <button onClick={() => setEditing(null)} className="text-gray-500">取消</button>
                  </>
                ) : (
                  <>
                    <span>{m.label}</span>
                    <span className="font-mono text-gray-600">{m.path}</span>
                    <span className="text-gray-600">排序 {m.sort}</span>
                    <input type="checkbox" checked={!!m.visible} disabled={!!m.is_system} title="显隐"
                      onChange={async e => {
                        try { await menusApi.update(m.menu_key, { visible: e.target.checked }); onChanged(); }
                        catch (err: any) { setError(err.message); }
                      }} />
                    <button onClick={() => { setEditing(m.menu_key); setDraft({ label: m.label, path: m.path, sort: m.sort }); }}
                      className="text-gray-500 hover:text-gray-300">编辑</button>
                    <button onClick={() => remove(m.menu_key)} disabled={!!m.is_system}
                      className="text-red-400 hover:text-red-300 disabled:opacity-30">删除</button>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
      {adding !== null && (
        <Modal open title={adding ? '新增菜单' : '新增分组'} onClose={() => setAdding(null)}>
          <div className="space-y-2 text-sm">
            <input placeholder="menu_key（menu-xxx / group-xxx）" className="w-full bg-surface-1 border border-border rounded px-2 py-1"
              value={draft.menu_key ?? ''} onChange={e => setDraft({ ...draft, menu_key: e.target.value })} />
            <input placeholder="显示名" className="w-full bg-surface-1 border border-border rounded px-2 py-1"
              value={draft.label ?? ''} onChange={e => setDraft({ ...draft, label: e.target.value })} />
            {adding ? (
              <input placeholder="路由 path（如 /my-page）" className="w-full bg-surface-1 border border-border rounded px-2 py-1"
                value={draft.path ?? ''} onChange={e => setDraft({ ...draft, path: e.target.value })} />
            ) : (
              <input placeholder="图标 emoji" className="w-full bg-surface-1 border border-border rounded px-2 py-1"
                value={draft.icon ?? ''} onChange={e => setDraft({ ...draft, icon: e.target.value })} />
            )}
            <button onClick={create} className="w-full bg-info text-white rounded py-1.5">创建</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── 页签 2：角色管理 ──
function RolesTab({ roles, onChanged, flash, setError }: {
  roles: RoleRecord[]; onChanged: () => void; flash: (t: string) => void; setError: (t: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [key, setKey] = useState('');
  const [label, setLabel] = useState('');

  const create = async () => {
    try {
      await rolesApi.create(key.trim(), label.trim() || key.trim());
      flash('已创建角色'); setAdding(false); setKey(''); setLabel(''); onChanged();
    } catch (e: any) { setError(e.message); }
  };
  const save = async (role_key: string) => {
    try { await rolesApi.update(role_key, label.trim() || role_key); flash('已保存'); setEditing(null); onChanged(); }
    catch (e: any) { setError(e.message); }
  };
  const remove = async (role_key: string) => {
    if (!window.confirm(`确认删除角色 ${role_key}？`)) return;
    try { await rolesApi.remove(role_key); flash('已删除'); onChanged(); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <div className="space-y-2">
      <button onClick={() => setAdding(true)} className="text-xs bg-info text-white rounded px-2 py-1">＋ 新增角色</button>
      {roles.map(r => (
        <div key={r.role_key} className="bg-surface-2 border border-border rounded-lg p-3 flex items-center gap-3 text-sm">
          <span className="font-mono text-gray-400">{r.role_key}</span>
          {editing === r.role_key ? (
            <>
              <input className="bg-surface-1 border border-border rounded px-2 py-0.5" value={label}
                onChange={e => setLabel(e.target.value)} />
              <button onClick={() => save(r.role_key)} className="text-info">保存</button>
              <button onClick={() => setEditing(null)} className="text-gray-500">取消</button>
            </>
          ) : (
            <>
              <span className="text-gray-200">{r.label}</span>
              {r.is_builtin && <span className="text-[10px] bg-purple-900/50 text-purple-300 rounded px-1">内置</span>}
              {!r.is_builtin && (
                <>
                  <button onClick={() => { setEditing(r.role_key); setLabel(r.label); }} className="ml-auto text-gray-500 hover:text-gray-300">重命名</button>
                  <button onClick={() => remove(r.role_key)} className="text-red-400 hover:text-red-300">删除</button>
                </>
              )}
            </>
          )}
        </div>
      ))}
      {adding && (
        <Modal open title="新增角色" onClose={() => setAdding(false)}>
          <div className="space-y-2 text-sm">
            <input placeholder="role_key（小写字母开头，如 dept-lead）" className="w-full bg-surface-1 border border-border rounded px-2 py-1"
              value={key} onChange={e => setKey(e.target.value)} />
            <input placeholder="显示名" className="w-full bg-surface-1 border border-border rounded px-2 py-1"
              value={label} onChange={e => setLabel(e.target.value)} />
            <button onClick={create} className="w-full bg-info text-white rounded py-1.5">创建</button>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ── 页签 3：角色授权（勾选 + 显式保存）──
function GrantsTab({ roles, menus, flash, setError }: {
  roles: RoleRecord[]; menus: MenuRecord[]; flash: (t: string) => void; setError: (t: string) => void;
}) {
  const [selRole, setSelRole] = useState('');
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  const groups = menus.filter(m => !m.parent_key).sort((a, b) => a.sort - b.sort);
  const itemsOf = (g: string) => menus.filter(m => m.parent_key === g).sort((a, b) => a.sort - b.sort);

  const loadRole = useCallback(async (role_key: string) => {
    setLoaded(false);
    try {
      const r = await rolesApi.getMenus(role_key);
      setChecked(new Set(r.menu_keys));
    } catch (e: any) { setError(e.message); }
    setLoaded(true);
  }, [setError]);

  useEffect(() => {
    if (roles.length && !selRole) setSelRole(roles[0].role_key);
  }, [roles, selRole]);
  useEffect(() => { if (selRole) loadRole(selRole); }, [selRole, loadRole]);

  const toggle = (key: string, isSystem: boolean) => {
    if (isSystem && selRole === 'admin') return; // 系统保底：admin 不可取消
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const save = async () => {
    try { await rolesApi.setMenus(selRole, [...checked]); flash('授权已保存'); }
    catch (e: any) { setError(e.message); }
  };

  return (
    <div className="flex gap-4">
      <div className="w-44 space-y-1 flex-shrink-0">
        {roles.map(r => (
          <button key={r.role_key} onClick={() => setSelRole(r.role_key)}
            className={`w-full text-left px-3 py-2 rounded text-sm ${selRole === r.role_key ? 'bg-info text-white' : 'bg-surface-2 text-gray-400'}`}>
            {r.label} <span className="font-mono text-[10px] opacity-70">{r.role_key}</span>
          </button>
        ))}
      </div>
      <div className="flex-1 bg-surface-2 border border-border rounded-lg p-4">
        {!loaded ? <div className="text-sm text-gray-500">加载中…</div> : (
          <div className="space-y-3">
            {groups.map(g => {
              const items = itemsOf(g.menu_key);
              const allChecked = items.length > 0 && items.every(i => checked.has(i.menu_key));
              return (
                <div key={g.menu_key}>
                  <label className="flex items-center gap-2 text-sm text-gray-300">
                    <input type="checkbox" checked={allChecked}
                      onChange={() => items.forEach(i => toggle(i.menu_key, !!i.is_system))} />
                    {g.icon} {g.label}
                  </label>
                  <div className="ml-5 pl-3 border-l border-border/50 space-y-1">
                    {items.map(i => (
                      <label key={i.menu_key} className="flex items-center gap-2 text-xs text-gray-400">
                        <input type="checkbox" checked={checked.has(i.menu_key)}
                          disabled={i.is_system && selRole === 'admin'}
                          onChange={() => toggle(i.menu_key, !!i.is_system)} />
                        {i.label}
                        {i.is_system && <span className="text-[10px] bg-purple-900/50 text-purple-300 rounded px-1">系统保底</span>}
                      </label>
                    ))}
                  </div>
                </div>
              );
            })}
            <button onClick={save} className="mt-2 text-xs bg-info text-white rounded px-3 py-1.5">保存授权</button>
          </div>
        )}
      </div>
    </div>
  );
}
