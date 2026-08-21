// 系统包管理（T-973 后端 9 端点的前端管理页，T-996 挂「系统管理」分组）：
// 目录 + 详情（tier/启停/评审闸）+ 注册 + manifest/env/assertions 编辑 + extensions 上传/评审/热加载

import { useCallback, useEffect, useState } from 'react';
import { systemsApi, type SystemEntry } from '../api';

const TIER_BADGE: Record<string, string> = {
  config: 'bg-green-900/30 text-green-400',
  template: 'bg-cyan-900/30 text-cyan-400',
  code: 'bg-purple-900/30 text-purple-400',
};

export default function SystemsAdmin() {
  const [systems, setSystems] = useState<SystemEntry[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState('');

  // 注册表单
  const [cName, setCName] = useState('');
  const [cDisplay, setCDisplay] = useState('');
  const [cTier, setCTier] = useState('config');
  const [cDesc, setCDesc] = useState('');
  const [cEnvYaml, setCEnvYaml] = useState('');

  // 详情编辑
  const [envName, setEnvName] = useState('sit');
  const [envRaw, setEnvRaw] = useState('');
  const [assertRaw, setAssertRaw] = useState('');
  const [extContent, setExtContent] = useState('');

  const load = useCallback(async (keep = '') => {
    try {
      const r = await systemsApi.list();
      setSystems(r.systems);
      const next = keep || selected || localStorage.getItem('sg_systems_sel') || r.systems[0]?.name || '';
      if (next && r.systems.some(s => s.name === next)) setSelected(next);
      else setSelected(r.systems[0]?.name || '');
    } catch (e: any) {
      setError(e.message || '加载失败');
    }
  }, [selected]);

  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (selected) localStorage.setItem('sg_systems_sel', selected); }, [selected]);

  const flash = (t: string) => { setMessage(t); setTimeout(() => setMessage(''), 2500); };
  const cur = systems.find(s => s.name === selected);

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key); setError('');
    try {
      await fn();
      flash(ok);
      await load(selected);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setBusy('');
    }
  };

  const handleCreate = async () => {
    if (!cName) { setError('请输入系统标识'); return; }
    await run('create', () => systemsApi.create({
      name: cName, display_name: cDisplay, tier: cTier, description: cDesc,
      env_yaml: cEnvYaml || undefined,
    }), `系统 ${cName} 已注册`);
    setShowCreate(false);
    setCName(''); setCDisplay(''); setCDesc(''); setCEnvYaml('');
  };

  const gate = cur?.extensions_review;

  return (
    <div className="flex flex-col h-full max-w-5xl">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-200">📦 系统包管理</h2>
          <p className="text-xs text-gray-500 mt-1">
            被测系统适配包分级接入：config/template 级注册编辑即时生效；code 级 extensions.py 走评审闸后热加载
          </p>
        </div>
        <button onClick={() => setShowCreate(true)} className="px-3 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90">
          + 注册系统
        </button>
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-3 text-red-400 text-sm" onClick={() => setError('')}>{error}</div>}
      {message && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 mb-3 text-green-400 text-sm">{message}</div>}

      <div className="flex gap-4 flex-1 min-h-0">
        {/* 左：系统目录 */}
        <div className="w-64 flex-shrink-0 space-y-1 overflow-y-auto">
          {systems.map(s => (
            <button key={s.name} onClick={() => setSelected(s.name)}
              className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                selected === s.name ? 'border-info/60 bg-info/10 text-gray-200' : 'border-border bg-surface-1 text-gray-400 hover:text-gray-200'
              }`}>
              <div className="flex items-center gap-2">
                <span className="font-medium">{s.display_name}</span>
                <span className="font-mono text-[10px] text-gray-600">{s.name}</span>
                {!s.enabled && <span className="text-[10px] text-gray-600">⏸ 停用</span>}
              </div>
              <div className="text-[10px] text-gray-600 mt-0.5">
                <span className={`px-1 rounded ${TIER_BADGE[s.tier] || ''}`}>{s.tier}</span>
                {s.envs.length > 0 && <span className="ml-1">env: {s.envs.join(',')}</span>}
              </div>
            </button>
          ))}
          {systems.length === 0 && <div className="text-center text-gray-600 text-sm py-8">暂无系统包</div>}
        </div>

        {/* 右：详情 */}
        <div className="flex-1 min-w-0 overflow-y-auto space-y-3">
          {!cur ? (
            <div className="text-center text-gray-600 text-sm py-10">选择左侧系统查看详情</div>
          ) : (
            <>
              <div className="bg-surface-1 rounded-lg border border-border p-3">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-bold text-gray-200">{cur.display_name}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${TIER_BADGE[cur.tier] || ''}`}>{cur.tier_label || cur.tier}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${cur.enabled ? 'bg-green-900/30 text-green-400' : 'bg-gray-700 text-gray-500'}`}>
                    {cur.enabled ? '✅ 启用' : '⏸️ 停用'}
                  </span>
                </div>
                {cur.description && <div className="text-xs text-gray-500">{cur.description}</div>}
                {cur.package_dir && <div className="text-[10px] text-gray-700 font-mono mt-1">{cur.package_dir}</div>}
                <div className="text-xs text-gray-600 mt-1">环境: {cur.envs.join(', ') || '—'} · 账号别名: {cur.accounts.join(', ') || '—'}</div>
                <div className="flex gap-2 mt-2">
                  <button disabled={busy === 'toggle'}
                    onClick={() => run('toggle', () => systemsApi.updateManifest(cur.name, { enabled: !cur.enabled }), '已更新启停状态')}
                    className="px-2 py-1 text-xs bg-surface-3 text-gray-400 rounded hover:text-gray-200 disabled:opacity-40">
                    {cur.enabled ? '停用' : '启用'}
                  </button>
                  <button disabled={busy === 'reload'}
                    onClick={() => run('reload', () => systemsApi.reload(cur.name), '热重建完成')}
                    className="px-2 py-1 text-xs bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40">
                    {busy === 'reload' ? '重建中…' : '🔄 热重建'}
                  </button>
                </div>
              </div>

              {/* 评审闸 */}
              <div className="bg-surface-1 rounded-lg border border-border p-3">
                <div className="text-xs font-medium text-gray-400 mb-1">🛂 extensions.py 评审闸</div>
                {gate?.present ? (
                  <>
                    <div className={`text-xs ${gate.loadable ? 'text-green-400' : 'text-amber-400'}`}>
                      {gate.loadable ? `✅ 已评审加载（${gate.approved_by} @ ${gate.approved_at}）` : `⚠ ${gate.reason}`}
                    </div>
                    <div className="text-[10px] text-gray-700 font-mono mt-1">sha256: {gate.sha256.slice(0, 16)}…</div>
                    {!gate.loadable && (
                      <button disabled={busy === 'review'}
                        onClick={() => run('review', () => systemsApi.review(cur.name), '评审通过，已绑定指纹并热加载')}
                        className="mt-2 px-2 py-1 text-xs bg-green-900/30 text-green-400 rounded hover:bg-green-900/50 disabled:opacity-40">
                        ✓ 评审通过（绑定当前 sha256）
                      </button>
                    )}
                  </>
                ) : (
                  <div className="text-xs text-gray-600">{gate?.reason || 'extensions.py 不存在（纯配置/模板系统）'}</div>
                )}
                <details className="mt-2">
                  <summary className="text-[11px] text-gray-600 cursor-pointer hover:text-gray-400">上传 extensions.py（落待评审）</summary>
                  <textarea value={extContent} onChange={e => setExtContent(e.target.value)} rows={6}
                    placeholder="# extensions.py：声明 steps/oracles（语法校验后落盘，评审通过才加载）"
                    className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-xs font-mono text-gray-300" />
                  <button disabled={!extContent || busy === 'ext'}
                    onClick={() => run('ext', () => systemsApi.uploadExtensions(cur.name, extContent), '已上传，待评审')}
                    className="mt-1 px-2 py-1 text-xs bg-info/20 text-info rounded disabled:opacity-40">上传</button>
                </details>
              </div>

              {/* env 配置 */}
              <div className="bg-surface-1 rounded-lg border border-border p-3">
                <div className="text-xs font-medium text-gray-400 mb-1">⚙️ 环境配置（config/env.{`{env}`}.yaml，写入即时生效）</div>
                <div className="flex gap-2 mb-1">
                  <input value={envName} onChange={e => setEnvName(e.target.value)}
                    className="w-24 bg-surface-2 border border-border rounded px-2 py-1 text-xs text-gray-300" placeholder="sit" />
                </div>
                <textarea value={envRaw} onChange={e => setEnvRaw(e.target.value)} rows={5}
                  placeholder="gateway: ...&#10;accounts: ..."
                  className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-xs font-mono text-gray-300" />
                <button disabled={!envRaw || busy === 'env'}
                  onClick={() => run('env', () => systemsApi.writeEnv(cur.name, envName, envRaw), `env.${envName}.yaml 已写入`)}
                  className="mt-1 px-2 py-1 text-xs bg-info/20 text-info rounded disabled:opacity-40">写入 env 配置</button>
              </div>

              {/* assertions */}
              <div className="bg-surface-1 rounded-lg border border-border p-3">
                <div className="text-xs font-medium text-gray-400 mb-1">📐 模板断言（assertions.yaml，注册期确定性校验：SELECT-only）</div>
                <textarea value={assertRaw} onChange={e => setAssertRaw(e.target.value)} rows={4}
                  placeholder="oracles: ..."
                  className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-xs font-mono text-gray-300" />
                <button disabled={!assertRaw || busy === 'assert'}
                  onClick={() => run('assert', () => systemsApi.writeAssertions(cur.name, assertRaw), '断言模板校验通过并已写入')}
                  className="mt-1 px-2 py-1 text-xs bg-info/20 text-info rounded disabled:opacity-40">校验并写入</button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 注册弹层 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-surface-1 rounded-lg border border-border p-4 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-gray-200 mb-3">注册系统包</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500">系统标识（Python 模块名）</label>
                <input value={cName} onChange={e => setCName(e.target.value)} placeholder="如 pbs"
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              </div>
              <div>
                <label className="text-xs text-gray-500">显示名</label>
                <input value={cDisplay} onChange={e => setCDisplay(e.target.value)}
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              </div>
              <div>
                <label className="text-xs text-gray-500">接入分级</label>
                <div className="flex gap-2 mt-1">
                  {(['config', 'template', 'code'] as const).map(t => (
                    <button key={t} onClick={() => setCTier(t)}
                      className={`px-3 py-1.5 text-xs rounded ${cTier === t ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>{t}</button>
                  ))}
                </div>
              </div>
              <div>
                <label className="text-xs text-gray-500">描述</label>
                <input value={cDesc} onChange={e => setCDesc(e.target.value)}
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              </div>
              <div>
                <label className="text-xs text-gray-500">首个环境配置（env.sit.yaml，可选）</label>
                <textarea value={cEnvYaml} onChange={e => setCEnvYaml(e.target.value)} rows={4}
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-xs font-mono text-gray-300" />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowCreate(false)} className="px-3 py-1.5 text-sm bg-surface-3 text-gray-400 rounded">取消</button>
              <button onClick={handleCreate} disabled={busy === 'create'}
                className="px-4 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90 disabled:opacity-40">
                {busy === 'create' ? '注册中…' : '注册'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
