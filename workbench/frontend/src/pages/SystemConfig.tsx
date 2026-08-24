/** SystemConfig — 系统配置（T-1010 三栏合一：系统 → 工作区 → 环境配置）
 *
 * 合并原三个页面：系统包管理（/systems）、工作区中心（/workspace）、环境配置（/env-config），
 * 外加原「系统设置」的数据库 tab（迁入栏3，system 跟随栏1选中不再写死）。
 * 导航流：栏1 先选/注册系统 → 栏2 在该系统下注册/管理工作区 → 栏3 维护该系统环境配置与 DB。
 * internal_token 等跨系统通用键在栏3「通用配置」层维护（systems/_shared）。
 *
 * 可见性：登录即可见；写操作按原角色控制（系统/环境/DB 写=admin，工作区注册=登录即可，同步=admin/tester）。
 */
import { useCallback, useEffect, useState } from 'react';
import { systemsApi, workspaceApi, type SystemEntry, type SystemInfo } from '../api';
import SystemsPanel from '../components/system-config/SystemsPanel';
import WorkspacesPanel from '../components/system-config/WorkspacesPanel';
import EnvConfigPanel from '../components/system-config/EnvConfigPanel';

export default function SystemConfig({ role }: { role: string }) {
  const isAdmin = role === 'admin';
  const [systems, setSystems] = useState<SystemEntry[]>([]);
  const [wsSystems, setWsSystems] = useState<SystemInfo[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await systemsApi.list();
      setSystems(r.systems);
      setSelected(prev => {
        const keep = prev || localStorage.getItem('sg_sysconf_system') || '';
        if (keep && r.systems.some(s => s.name === keep)) return keep;
        return r.systems[0]?.name || '';
      });
    } catch (e: any) {
      setError(e.message || '加载系统目录失败');
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (selected) localStorage.setItem('sg_sysconf_system', selected); }, [selected]);

  // 注册工作区表单的系统下拉数据源（软校验：允许未建包系统待接入）
  useEffect(() => {
    workspaceApi.systems().then(r => setWsSystems(r.systems)).catch(() => {});
  }, []);

  // 栏2/栏3 共用的系统枚举（envs/accounts）：优先 systemsApi 目录，回退 workspaceApi
  const sysInfos: SystemInfo[] = systems.length > 0
    ? systems.map(s => ({ name: s.name, envs: s.envs, default_env: s.default_env, accounts: s.accounts }))
    : wsSystems;

  return (
    <div className="h-full flex flex-col">
      <div className="mb-3 flex-shrink-0">
        <h2 className="text-lg font-bold text-gray-200">🧩 系统配置</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          栏1 注册/选择系统 → 栏2 注册/管理工作区 → 栏3 环境配置（通用配置含 sso/internal_token，本系统配置含网关/账号池/数据库）
        </p>
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-3 text-red-400 text-sm flex-shrink-0" onClick={() => setError('')}>{error}</div>}

      {/* 三栏：行高钉死、各栏内部滚动（T-1009 同款先例） */}
      <div className="flex-1 min-h-0 flex gap-3">
        <div className="w-72 flex-shrink-0 min-h-0">
          <SystemsPanel systems={systems} selected={selected} onSelect={setSelected} isAdmin={isAdmin} onChanged={load} />
        </div>
        <div className="flex-1 min-w-0 min-h-0">
          <WorkspacesPanel system={selected} systems={wsSystems.length > 0 ? wsSystems : sysInfos} role={role} />
        </div>
        <div className="flex-1 min-w-0 min-h-0">
          <EnvConfigPanel system={selected} systems={sysInfos} isAdmin={isAdmin} />
        </div>
      </div>
    </div>
  );
}
