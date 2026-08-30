// 顶栏工作区选择器（T-1000 二级：系统 → 工作区）：
// 全页生效（localStorage + X-SG-Workspace header），可设为个人默认。
// 第一级选系统（含「待接入」「未绑定」），第二级选该系统下工作区。

import { useEffect, useMemo, useState } from 'react';
import { session, usersApi, workspaceApi, WORKSPACE_CHANGED_EVENT } from '../api';
import type { CurrentUser, WorkspaceTreeGroup } from '../api';

export default function WorkspaceSelector({ user }: { user: CurrentUser }) {
  const [tree, setTree] = useState<WorkspaceTreeGroup[]>([]);
  const [sysSel, setSysSel] = useState(() => localStorage.getItem('sg_ws_system') || '');
  const [current, setCurrent] = useState(session.getWorkspace());
  const [myDefault, setMyDefault] = useState(user.default_workspace || '');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    workspaceApi.tree()
      .then(r => {
        setTree(r.tree);
        // 初始化：无会话选择时回落到个人默认
        if (!session.getWorkspace()) {
          const fallback = user.default_workspace || '';
          if (fallback) {
            session.setWorkspace(fallback);
            setCurrent(fallback);
          }
        }
      })
      .catch(() => {});
    workspaceApi.list()
      .then(r => setMyDefault(r.my_default || user.default_workspace || ''))
      .catch(() => {});
  }, [user.default_workspace]);

  // 当前工作区所属系统（选中工作区时对齐第一级）
  const sysOfCurrent = useMemo(() => {
    for (const g of tree) {
      if (g.workspaces.some(w => w.name === current)) return g.system;
    }
    return '';
  }, [tree, current]);

  // 第一级有效值：显式选择优先，否则跟随当前工作区所属系统
  const effSys = sysSel || sysOfCurrent;
  const curGroup = tree.find(g => g.system === effSys);

  const handleSysChange = (sys: string) => {
    setSysSel(sys);
    localStorage.setItem('sg_ws_system', sys);
    // 换系统时自动选中该系统第一个工作区（二级联动，不留失效旧值）
    const g = tree.find(x => x.system === sys);
    const first = g?.workspaces[0]?.name || '';
    if (first && first !== current) {
      setCurrent(first);
      session.setWorkspace(first);
      setSaved(false);
    }
  };

  const handleChange = (name: string) => {
    setCurrent(name);
    session.setWorkspace(name);
    setSaved(false);
  };

  // K-009：其他页面（如系统配置）切换工作区时联动刷新显示
  useEffect(() => {
    const onChanged = (e: Event) => {
      const name = (e as CustomEvent<string>).detail;
      if (name) setCurrent(name);
    };
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
  }, []);

  const handleSetDefault = async () => {
    try {
      await usersApi.setDefaultWorkspace(current);
      setMyDefault(current);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch { /* 403 等由 api 层抛错，静默即可（选择器仅授权范围内） */ }
  };

  return (
    <div className="flex items-center gap-2 text-fs-lead">
      <span className="text-gray-500 text-fs-body">工作区</span>
      {/* 第一级：系统 */}
      <select
        value={effSys}
        onChange={e => handleSysChange(e.target.value)}
        title="系统（适配包分组）"
        className="bg-surface-1 border border-border rounded px-2 py-1 text-fs-lead text-gray-200 focus:border-info outline-none max-w-[9rem]"
      >
        {tree.length === 0 && <option value="">（无系统）</option>}
        {tree.map(g => (
          <option key={g.system || '_unbound'} value={g.system}>
            {g.display_name}{g.system_pending ? ' ⏳' : ''}
          </option>
        ))}
      </select>
      {/* 第二级：该系统下工作区 */}
      <select
        value={current}
        onChange={e => handleChange(e.target.value)}
        className="bg-surface-1 border border-border rounded px-2 py-1 text-fs-lead text-gray-200 focus:border-info outline-none min-w-[9rem]"
      >
        <option value="">（未选择）</option>
        {(curGroup?.workspaces || []).map(w => (
          <option key={w.name} value={w.name}>
            {w.name}{w.source?.type === 'git' ? ' ⚡' : ''}
          </option>
        ))}
      </select>
      {current && current !== myDefault && (
        <button
          onClick={handleSetDefault}
          className="text-fs-body text-info hover:underline"
          title="设为我的默认工作区"
        >
          设为默认
        </button>
      )}
      {saved && <span className="text-fs-body text-green-500">✓ 已设为默认</span>}
      {tree.every(g => g.workspaces.length === 0) && (
        <span className="text-fs-body text-yellow-500">无可用工作区，请到「系统配置」注册</span>
      )}
    </div>
  );
}
