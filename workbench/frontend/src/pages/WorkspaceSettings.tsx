// 工作区管理：注册/激活/注销/合规报告

import { useState, useEffect } from 'react';
import { workspaceApi, type WorkspaceInfo } from '../api';

export default function WorkspaceSettings() {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [active, setActive] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [conformance, setConformance] = useState<any>(null);
  const [loadingConformance, setLoadingConformance] = useState(false);

  // 注册表单
  const [regType, setRegType] = useState<'local' | 'git'>('local');
  const [regName, setRegName] = useState('');
  const [regPath, setRegPath] = useState('');
  const [regUrl, setRegUrl] = useState('');
  const [regSystem, setRegSystem] = useState('tdm');
  const [regBranch, setRegBranch] = useState('main');
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    try {
      const data = await workspaceApi.list();
      setWorkspaces(data.workspaces);
      setActive(data.active);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => { load(); }, []);

  const handleRegister = async () => {
    if (!regName) { setError('请输入工作区名称'); return; }
    setSubmitting(true);
    setError('');
    setSuccess('');
    try {
      if (regType === 'local') {
        if (!regPath) { setError('请输入本地路径'); return; }
        const result = await workspaceApi.registerLocal({ name: regName, path: regPath, system: regSystem });
        if (!result.ok) {
          setError(result.error || '注册失败');
          if (result.report) setConformance(result.report);
        } else {
          setSuccess(`工作区 ${regName} 注册成功`);
          setRegName(''); setRegPath('');
          load();
        }
      } else {
        if (!regUrl) { setError('请输入 git URL'); return; }
        const result = await workspaceApi.registerGit({ name: regName, url: regUrl, system: regSystem, branch: regBranch });
        if (!result.ok) {
          setError(result.error || '注册失败');
          if (result.report) setConformance(result.report);
        } else {
          setSuccess(`工作区 ${regName} 克隆成功`);
          setRegName(''); setRegUrl('');
          load();
        }
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleActivate = async (name: string) => {
    try { await workspaceApi.activate(name); setActive(name); load(); } catch (e: any) { setError(e.message); }
  };

  const handleUnregister = async (name: string) => {
    if (!confirm(`确定注销工作区 ${name}？`)) return;
    try { await workspaceApi.unregister(name); load(); } catch (e: any) { setError(e.message); }
  };

  const handleConformance = async (name?: string) => {
    setLoadingConformance(true);
    setConformance(null);
    try {
      const result = await workspaceApi.conformance(name);
      setConformance(result);
    } catch (e: any) { setError(e.message); }
    finally { setLoadingConformance(false); }
  };

  return (
    <div className="flex flex-col h-full max-w-4xl">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">🗂 工作区管理</h2>
        <p className="text-xs text-gray-500 mt-1">注册 spec 仓库（本地/git），激活后供 Agent 和 Spec 文档中心使用</p>
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-3 text-red-400 text-sm">{error}</div>}
      {success && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 mb-3 text-green-400 text-sm">{success}</div>}

      {/* 工作区列表 */}
      <div className="mb-4">
        <div className="text-xs text-gray-500 mb-2">已注册工作区 ({workspaces.length})</div>
        {workspaces.length === 0 ? (
          <div className="text-center text-gray-600 text-sm py-4">暂无工作区</div>
        ) : (
          <div className="space-y-2">
            {workspaces.map(ws => (
              <div key={ws.name} className={`flex items-center justify-between p-2 rounded-lg border ${active === ws.name ? 'border-info bg-info/5' : 'border-border bg-surface-1'}`}>
                <div className="flex-1">
                  <span className="text-sm text-gray-300">{ws.name}</span>
                  <span className="text-xs text-gray-600 ml-2">{ws.system}</span>
                  <span className="text-xs text-gray-600 ml-2">{ws.source.type === 'git' ? 'git' : 'local'}</span>
                  {ws.last_commit && <span className="text-xs text-gray-600 ml-2">commit: {ws.last_commit}</span>}
                </div>
                <div className="flex gap-1">
                  {active !== ws.name && <button onClick={() => handleActivate(ws.name)} className="px-2 py-1 text-xs bg-info/20 text-info rounded hover:bg-info/30">激活</button>}
                  <button onClick={() => handleConformance(ws.name)} className="px-2 py-1 text-xs bg-surface-3 text-gray-400 rounded hover:bg-surface-2">校验</button>
                  <button onClick={() => handleUnregister(ws.name)} className="px-2 py-1 text-xs bg-red-900/30 text-red-400 rounded hover:bg-red-900/50">注销</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 注册新工作区 */}
      <div className="bg-surface-1 rounded-lg border border-border p-3 mb-4">
        <div className="text-xs text-gray-500 mb-3">注册新工作区</div>
        <div className="flex gap-2 mb-3">
          <button onClick={() => setRegType('local')} className={`px-3 py-1 text-xs rounded ${regType === 'local' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>本地文件夹</button>
          <button onClick={() => setRegType('git')} className={`px-3 py-1 text-xs rounded ${regType === 'git' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>Git 仓库</button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input value={regName} onChange={e => setRegName(e.target.value)} placeholder="工作区名称" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
          <input value={regSystem} onChange={e => setRegSystem(e.target.value)} placeholder="系统标识 (tdm)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
          {regType === 'local' ? (
            <input value={regPath} onChange={e => setRegPath(e.target.value)} placeholder="本地路径 (D:/work/spec-tdm)" className="col-span-2 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
          ) : (
            <>
              <input value={regUrl} onChange={e => setRegUrl(e.target.value)} placeholder="Git URL" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              <input value={regBranch} onChange={e => setRegBranch(e.target.value)} placeholder="分支 (main)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
            </>
          )}
        </div>
        <button onClick={handleRegister} disabled={submitting} className="mt-2 px-4 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90 disabled:opacity-40">
          {submitting ? '处理中...' : regType === 'local' ? '注册' : '克隆并注册'}
        </button>
      </div>

      {/* 合规报告 */}
      {loadingConformance && <div className="text-center text-gray-500 text-sm py-4">校验中...</div>}
      {conformance && (
        <div className="bg-surface-1 rounded-lg border border-border p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500">合规校验报告</span>
            <span className={`text-xs font-bold ${conformance.verdict === 'PASS' ? 'text-green-400' : 'text-red-400'}`}>{conformance.verdict}</span>
          </div>
          {conformance.findings && conformance.findings.length > 0 ? (
            <div className="space-y-1 max-h-60 overflow-y-auto">
              {conformance.findings.map((f: any, i: number) => (
                <div key={i} className={`text-xs flex gap-2 ${f.level === 'ERROR' ? 'text-red-400' : f.level === 'WARN' ? 'text-yellow-400' : 'text-gray-500'}`}>
                  <span className="font-mono">[{f.level}]</span>
                  <span className="font-mono text-gray-600">{f.rule}</span>
                  <span className="flex-1">{f.message}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-green-400">全部通过，无违规项</div>
          )}
        </div>
      )}
    </div>
  );
}
