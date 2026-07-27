// 顶栏工作区选择器：全页生效（localStorage + X-SG-Workspace header），可设为个人默认

import { useEffect, useState } from 'react';
import { session, usersApi, workspaceApi } from '../api';
import type { CurrentUser, WorkspaceInfo } from '../api';

export default function WorkspaceSelector({ user }: { user: CurrentUser }) {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [current, setCurrent] = useState(session.getWorkspace());
  const [myDefault, setMyDefault] = useState(user.default_workspace || '');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    workspaceApi.list()
      .then(r => {
        setWorkspaces(r.workspaces);
        setMyDefault(r.my_default || user.default_workspace || '');
        // 初始化：无会话选择时回落到个人默认
        if (!session.getWorkspace()) {
          const fallback = r.my_default || user.default_workspace || '';
          if (fallback) {
            session.setWorkspace(fallback);
            setCurrent(fallback);
          }
        }
      })
      .catch(() => {});
  }, [user.default_workspace]);

  const handleChange = (name: string) => {
    setCurrent(name);
    session.setWorkspace(name);
    setSaved(false);
  };

  const handleSetDefault = async () => {
    try {
      await usersApi.setDefaultWorkspace(current);
      setMyDefault(current);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch { /* 403 等由 api 层抛错，静默即可（选择器仅授权范围内） */ }
  };

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-gray-500 text-xs">工作区</span>
      <select
        value={current}
        onChange={e => handleChange(e.target.value)}
        className="bg-surface-1 border border-border rounded px-2 py-1 text-sm text-gray-200 focus:border-info outline-none min-w-[10rem]"
      >
        <option value="">（未选择）</option>
        {workspaces.map(w => (
          <option key={w.name} value={w.name}>
            {w.name}{w.source?.type === 'git' ? ' ⚡' : ''}
          </option>
        ))}
      </select>
      {current && current !== myDefault && (
        <button
          onClick={handleSetDefault}
          className="text-xs text-info hover:underline"
          title="设为我的默认工作区"
        >
          设为默认
        </button>
      )}
      {saved && <span className="text-xs text-green-500">✓ 已设为默认</span>}
      {workspaces.length === 0 && (
        <span className="text-xs text-yellow-500">无可用工作区，请联系管理员授权</span>
      )}
    </div>
  );
}
