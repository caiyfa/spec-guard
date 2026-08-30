/** 系统配置 · 栏1：系统包目录 + 注册 + 详情（manifest 启停/热重建/extensions 评审闸/assertions）
 *
 * T-1010 自 SystemsAdmin 页迁入：env yaml 编辑移至栏3 环境配置（带原文回读），本栏不再重复。
 */
import { useState } from 'react';
import { systemsApi, type SystemEntry } from '../../api';

const TIER_BADGE: Record<string, string> = {
  config: 'bg-green-900/30 text-green-400',
  template: 'bg-cyan-900/30 text-cyan-400',
  code: 'bg-purple-900/30 text-purple-400',
};

// T-1011：接入分级人话解释（注册弹层选项下随选随显）
const TIER_DESC: Record<string, string> = {
  config: '纯配置接入——只需环境配置（env.yaml：网关/账号池/资源码），注册后在栏3维护即可跑场景',
  template: '配置 + 断言模板——额外提供 assertions.yaml（SELECT-only DB 断言模板），注册后在栏1详情区维护',
  code: '代码扩展——额外提供 extensions.py（自定义步骤/断言器，Python 代码），走评审闸通过后热加载',
};

interface Props {
  systems: SystemEntry[];
  selected: string;
  onSelect: (name: string) => void;
  isAdmin: boolean;
  onChanged: () => void;   // 任何写操作成功后刷新系统目录
}

export default function SystemsPanel({ systems, selected, onSelect, isAdmin, onChanged }: Props) {
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [showCreate, setShowCreate] = useState(false);
  const [busy, setBusy] = useState('');

  // 注册表单
  const [cName, setCName] = useState('');
  const [cDisplay, setCDisplay] = useState('');
  const [cTier, setCTier] = useState('config');
  const [cDesc, setCDesc] = useState('');

  // 详情编辑
  const [assertRaw, setAssertRaw] = useState('');
  const [extContent, setExtContent] = useState('');

  const flash = (t: string) => { setMessage(t); setTimeout(() => setMessage(''), 2500); };
  const cur = systems.find(s => s.name === selected);

  const run = async (key: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(key); setError('');
    try {
      await fn();
      flash(ok);
      onChanged();
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
    }), `系统 ${cName} 已注册`);
    setShowCreate(false);
    setCName(''); setCDisplay(''); setCDesc('');
    onSelect(cName);
  };

  const gate = cur?.extensions_review;

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <span className="text-fs-body font-medium text-gray-300">📦 系统（适配包）</span>
        {isAdmin && (
          <button onClick={() => setShowCreate(true)}
            className="px-2 py-1 bg-info text-white rounded text-fs-body hover:bg-info/90">
            + 注册系统
          </button>
        )}
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-2 text-red-400 text-fs-body flex-shrink-0" onClick={() => setError('')}>{error}</div>}
      {message && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 mb-2 text-green-400 text-fs-body flex-shrink-0">{message}</div>}

      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
        {/* 系统目录 */}
        <div className="space-y-1">
          {systems.map(s => (
            <button key={s.name} onClick={() => onSelect(s.name)}
              className={`w-full text-left px-3 py-2 rounded-lg border text-sm transition-colors ${
                selected === s.name ? 'border-info/60 bg-info/10 text-gray-200' : 'border-border bg-surface-1 text-gray-400 hover:text-gray-200'
              }`}>
              <div className="flex items-center gap-2">
                <span className="font-medium">{s.display_name}</span>
                <span className="font-mono text-fs-aux text-gray-600">{s.name}</span>
                {!s.enabled && <span className="text-fs-aux text-gray-600">⏸ 停用</span>}
              </div>
              <div className="text-fs-aux text-gray-600 mt-0.5">
                <span className={`px-1 rounded ${TIER_BADGE[s.tier] || ''}`}>{s.tier}</span>
                {s.envs.length > 0 && <span className="ml-1">env: {s.envs.join(',')}</span>}
              </div>
            </button>
          ))}
          {systems.length === 0 && (
            <div className="text-center text-gray-600 text-fs-body py-6">
              暂无系统包{isAdmin ? '，点击右上「注册系统」接入' : '（需管理员注册）'}
            </div>
          )}
        </div>

        {/* 选中系统详情 */}
        {cur && (
          <>
            <div className="bg-surface-1 rounded-lg border border-border p-3">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-fs-body px-1.5 py-0.5 rounded ${TIER_BADGE[cur.tier] || ''}`}>{cur.tier_label || cur.tier}</span>
                <span className={`text-fs-body px-1.5 py-0.5 rounded ${cur.enabled ? 'bg-green-900/30 text-green-400' : 'bg-gray-700 text-gray-500'}`}>
                  {cur.enabled ? '✅ 启用' : '⏸️ 停用'}
                </span>
              </div>
              {cur.description && <div className="text-fs-body text-gray-500">{cur.description}</div>}
              {cur.package_dir && <div className="text-fs-aux text-gray-700 font-mono mt-1" title="适配包目录（配置落点）">{cur.package_dir}</div>}
              <div className="text-fs-body text-gray-600 mt-1">环境: {cur.envs.join(', ') || '—'} · 账号别名: {cur.accounts.join(', ') || '—'}</div>
              {isAdmin && (
                <div className="flex gap-2 mt-2">
                  <button disabled={busy === 'toggle'}
                    onClick={() => run('toggle', () => systemsApi.updateManifest(cur.name, { enabled: !cur.enabled }), '已更新启停状态')}
                    className="px-2 py-1 text-fs-body bg-surface-3 text-gray-400 rounded hover:text-gray-200 disabled:opacity-40">
                    {cur.enabled ? '停用' : '启用'}
                  </button>
                  <button disabled={busy === 'reload'}
                    onClick={() => run('reload', () => systemsApi.reload(cur.name), '热重建完成')}
                    className="px-2 py-1 text-fs-body bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40">
                    {busy === 'reload' ? '重建中…' : '🔄 热重建'}
                  </button>
                </div>
              )}
            </div>

            {/* 评审闸 */}
            <div className="bg-surface-1 rounded-lg border border-border p-3">
              <div className="text-fs-body font-medium text-gray-400 mb-1">🛂 extensions.py 评审闸</div>
              {gate?.present ? (
                <>
                  <div className={`text-fs-body ${gate.loadable ? 'text-green-400' : 'text-amber-400'}`}>
                    {gate.loadable ? `✅ 已评审加载（${gate.approved_by} @ ${gate.approved_at}）` : `⚠ ${gate.reason}`}
                  </div>
                  <div className="text-fs-aux text-gray-700 font-mono mt-1">sha256: {gate.sha256.slice(0, 16)}…</div>
                  {isAdmin && !gate.loadable && (
                    <button disabled={busy === 'review'}
                      onClick={() => run('review', () => systemsApi.review(cur.name), '评审通过，已绑定指纹并热加载')}
                      className="mt-2 px-2 py-1 text-fs-body bg-green-900/30 text-green-400 rounded hover:bg-green-900/50 disabled:opacity-40">
                      ✓ 评审通过（绑定当前 sha256）
                    </button>
                  )}
                </>
              ) : (
                <div className="text-fs-body text-gray-600">{gate?.reason || 'extensions.py 不存在（纯配置/模板系统）'}</div>
              )}
              {isAdmin && (
                <details className="mt-2">
                  <summary className="text-fs-body text-gray-600 cursor-pointer hover:text-gray-400">上传 extensions.py（落待评审）</summary>
                  <textarea value={extContent} onChange={e => setExtContent(e.target.value)} rows={6}
                    placeholder="# extensions.py：声明 steps/oracles（语法校验后落盘，评审通过才加载）"
                    className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-body font-mono text-gray-300" />
                  <button disabled={!extContent || busy === 'ext'}
                    onClick={() => run('ext', () => systemsApi.uploadExtensions(cur.name, extContent), '已上传，待评审')}
                    className="mt-1 px-2 py-1 text-fs-body bg-info/20 text-info rounded disabled:opacity-40">上传</button>
                </details>
              )}
            </div>

            {/* assertions */}
            {isAdmin && (
              <div className="bg-surface-1 rounded-lg border border-border p-3">
                <div className="text-fs-body font-medium text-gray-400 mb-1">📐 模板断言（assertions.yaml，注册期确定性校验：SELECT-only）</div>
                <textarea value={assertRaw} onChange={e => setAssertRaw(e.target.value)} rows={4}
                  placeholder="oracles: ..."
                  className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-fs-body font-mono text-gray-300" />
                <button disabled={!assertRaw || busy === 'assert'}
                  onClick={() => run('assert', () => systemsApi.writeAssertions(cur.name, assertRaw), '断言模板校验通过并已写入')}
                  className="mt-1 px-2 py-1 text-fs-body bg-info/20 text-info rounded disabled:opacity-40">校验并写入</button>
              </div>
            )}
          </>
        )}
      </div>

      {/* 注册弹层 */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setShowCreate(false)}>
          <div className="bg-surface-1 rounded-lg border border-border p-4 w-full max-w-lg" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-gray-200 mb-3">注册系统</h3>
            <div className="space-y-3">
              <div>
                <label className="text-fs-body text-gray-500">系统标识（Python 模块名）</label>
                <input value={cName} onChange={e => setCName(e.target.value)} placeholder="如 pbs"
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              </div>
              <div>
                <label className="text-fs-body text-gray-500">显示名</label>
                <input value={cDisplay} onChange={e => setCDisplay(e.target.value)}
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              </div>
              <div>
                <label className="text-fs-body text-gray-500">接入分级（系统的扩展能力级别）</label>
                <div className="flex gap-2 mt-1">
                  {(['config', 'template', 'code'] as const).map(t => (
                    <button key={t} onClick={() => setCTier(t)}
                      className={`px-3 py-1.5 text-fs-body rounded ${cTier === t ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>{t}</button>
                  ))}
                </div>
                <div className="text-fs-body text-gray-500 mt-1">{TIER_DESC[cTier]}</div>
              </div>
              <div>
                <label className="text-fs-body text-gray-500">描述</label>
                <input value={cDesc} onChange={e => setCDesc(e.target.value)}
                  className="w-full mt-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              </div>
              <div className="text-fs-body text-gray-600 border-t border-border/50 pt-2">
                环境配置（网关/账号池/资源码/db）注册后到栏3维护；通用键（sso/internal_token）放栏3「通用配置」层。
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
