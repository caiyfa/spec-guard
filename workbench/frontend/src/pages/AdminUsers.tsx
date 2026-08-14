// 用户与工作区授权管理（admin 专属）：用户角色 + 工作区授权 + 审计日志

import { useCallback, useEffect, useState } from 'react';
import { usersApi, workspaceApi, rolesApi } from '../api';
import type { UserItem, GrantItem, WorkspaceInfo, RoleRecord } from '../api';

export default function AdminUsers() {
  const [users, setUsers] = useState<UserItem[]>([]);
  const [grants, setGrants] = useState<GrantItem[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [roles, setRoles] = useState<RoleRecord[]>([]);  // RBAC：角色源动态化（内置 + 自定义）
  const [audit, setAudit] = useState<any[]>([]);
  const [tab, setTab] = useState<'users' | 'audit'>('users');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [u, g, w, a, r] = await Promise.all([
        usersApi.list(), usersApi.grants(), workspaceApi.list(), usersApi.auditLog(50), rolesApi.list(),
      ]);
      setUsers(u.users);
      setGrants(g.grants);
      setWorkspaces(w.workspaces);
      setAudit(a.entries);
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

  const handleSetRoles = async (empNo: string, nextRoles: string[]) => {
    if (nextRoles.length === 0) { setError('用户至少保留一个角色'); return; }
    try {
      await usersApi.setRoles(empNo, nextRoles);
      flash(`已更新 ${empNo} 角色`);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleGrant = async (empNo: string, wsName: string) => {
    if (!wsName) return;
    try {
      await usersApi.grant(empNo, wsName);
      flash(`已授权 ${wsName} 给 ${empNo}`);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const handleRevoke = async (empNo: string, wsName: string) => {
    try {
      await usersApi.revoke(empNo, wsName);
      flash(`已撤销 ${empNo} 的 ${wsName} 授权`);
      await refresh();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const grantsOf = (empNo: string) => grants.filter(g => g.emp_no === empNo);
  const ungrantedOf = (empNo: string) =>
    workspaces.filter(w => !grantsOf(empNo).some(g => g.workspace_name === w.name));

  return (
    <div className="max-w-5xl">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">👥 用户与授权</h2>
        <p className="text-xs text-gray-500 mt-1">
          用户首次登录自动建档（默认只读角色）；工作区由高权限人员注册后在此开通给用户。
        </p>
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-700/50">
          {error}
        </div>
      )}
      {message && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm bg-green-900/30 text-green-400 border border-green-700/50">
          {message}
        </div>
      )}

      <div className="flex gap-2 mb-4">
        <button onClick={() => setTab('users')}
          className={`px-3 py-1.5 text-sm rounded ${tab === 'users' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>
          用户与授权 ({users.length})
        </button>
        <button onClick={() => setTab('audit')}
          className={`px-3 py-1.5 text-sm rounded ${tab === 'audit' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>
          审计日志 ({audit.length})
        </button>
      </div>

      {tab === 'users' && (
        <div className="space-y-3">
          {users.map(u => (
            <div key={u.emp_no} className="bg-surface-2 border border-border rounded-lg p-4">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-sm text-gray-200 font-medium">{u.name || u.emp_no}</span>
                <span className="text-xs text-gray-500 font-mono">{u.emp_no}</span>
                <span className="text-[10px] text-gray-600 ml-auto">
                  默认工作区: {u.default_workspace || '—'} · 最近登录: {u.last_login_at || '—'}
                </span>
              </div>
              {/* 多角色 chips（RBAC：内置 + 自定义角色多选） */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-gray-500">角色:</span>
                {(u.roles ?? []).map(r => {
                  const rl = roles.find(x => x.role_key === r);
                  return (
                    <span key={r} className="inline-flex items-center gap-1 text-xs bg-info/10 text-info rounded px-2 py-0.5">
                      {rl?.label || r}
                      <button onClick={() => handleSetRoles(u.emp_no, (u.roles ?? []).filter(x => x !== r))}
                        className="text-red-400 hover:text-red-300" title="移除角色">×</button>
                    </span>
                  );
                })}
                {(u.roles ?? []).length === 0 && <span className="text-xs text-gray-600">（无）</span>}
                <select
                  value=""
                  onChange={e => {
                    if (e.target.value) handleSetRoles(u.emp_no, [...(u.roles ?? []), e.target.value]);
                    e.target.value = '';
                  }}
                  className="bg-surface-1 border border-border rounded px-1.5 py-0.5 text-xs text-gray-400"
                >
                  <option value="">＋ 添加角色…</option>
                  {roles.filter(r => !(u.roles ?? []).includes(r.role_key)).map(r => (
                    <option key={r.role_key} value={r.role_key}>{r.label} ({r.role_key})</option>
                  ))}
                </select>
                <a href="/menu-roles" className="text-[10px] text-gray-600 hover:text-gray-400 underline ml-auto">角色管理 →</a>
              </div>
              {/* 工作区授权 */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs text-gray-500">授权工作区:</span>
                {grantsOf(u.emp_no).map(g => (
                  <span key={g.id} className="inline-flex items-center gap-1 text-xs bg-info/10 text-info rounded px-2 py-0.5">
                    {g.workspace_name}
                    <button onClick={() => handleRevoke(u.emp_no, g.workspace_name)}
                      className="text-red-400 hover:text-red-300" title="撤销授权">×</button>
                  </span>
                ))}
                {grantsOf(u.emp_no).length === 0 && (
                  <span className="text-xs text-gray-600">（无）</span>
                )}
                {ungrantedOf(u.emp_no).length > 0 && (
                  <select
                    value=""
                    onChange={e => { handleGrant(u.emp_no, e.target.value); e.target.value = ''; }}
                    className="bg-surface-1 border border-border rounded px-1.5 py-0.5 text-xs text-gray-400"
                  >
                    <option value="">＋ 开通…</option>
                    {ungrantedOf(u.emp_no).map(w => (
                      <option key={w.name} value={w.name}>{w.name}</option>
                    ))}
                  </select>
                )}
              </div>
            </div>
          ))}
          {users.length === 0 && (
            <div className="text-center text-gray-600 text-sm py-10">暂无用户（用户首次登录后出现在此）</div>
          )}
        </div>
      )}

      {tab === 'audit' && (
        <div className="bg-surface-2 border border-border rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500 border-b border-border">
                <th className="px-3 py-2">时间</th>
                <th className="px-3 py-2">操作人</th>
                <th className="px-3 py-2">动作</th>
                <th className="px-3 py-2">对象</th>
                <th className="px-3 py-2">详情</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((a, i) => (
                <tr key={i} className="border-b border-border/50 text-gray-400">
                  <td className="px-3 py-1.5 font-mono">{a.created_at}</td>
                  <td className="px-3 py-1.5">{a.emp_no}</td>
                  <td className="px-3 py-1.5">{a.action}</td>
                  <td className="px-3 py-1.5">{a.target}</td>
                  <td className="px-3 py-1.5 truncate max-w-[16rem]">{a.detail}</td>
                </tr>
              ))}
              {audit.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-600">暂无审计记录</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
