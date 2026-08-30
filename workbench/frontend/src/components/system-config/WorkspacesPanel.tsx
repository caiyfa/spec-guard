/** 系统配置 · 栏2：工作区（随栏1选中系统过滤）+ 注册（登录即可）+ 文档浏览（折叠区）
 *
 * T-1010 自 WorkspaceCenter 页迁入：卡片墙从「全系统分组」收窄为「当前系统一组」，
 * 注册表单的系统下拉默认锁定栏1选中系统；文档浏览收进可折叠区（状态持久化）。
 * 选中工作区仍写 session（X-SG-Workspace），全站页面自动跟随。
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { workspaceApi, session, WORKSPACE_CHANGED_EVENT, type SystemInfo, type WorkspaceTreeGroup } from '../../api';
import FileTree from '../FileTree';
import FileViewer from '../FileViewer';
import DirectoryPicker from '../DirectoryPicker';
import type { FlatFile } from '../FileTree';

interface Props {
  system: string;          // 栏1选中的系统标识
  systems: SystemInfo[];   // 注册表单系统下拉数据源
  role: string;
}

export default function WorkspacesPanel({ system, systems, role }: Props) {
  const isAdmin = role === 'admin';
  const canSync = isAdmin || role === 'tester';

  const [tree, setTree] = useState<WorkspaceTreeGroup[]>([]);
  const [active, setActive] = useState('');
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [conformance, setConformance] = useState<any>(null);
  const [loadingConformance, setLoadingConformance] = useState(false);

  const [syncing, setSyncing] = useState('');
  const [syncMsg, setSyncMsg] = useState('');

  // 文档浏览（折叠区，状态持久化）
  const [docsOpen, setDocsOpen] = useState(() => localStorage.getItem('sg_sysconf_docs') === '1');
  const [files, setFiles] = useState<FlatFile[]>([]);
  const [activeFile, setActiveFile] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [loadingFile, setLoadingFile] = useState(false);

  // 注册表单（登录即可）
  const [showRegister, setShowRegister] = useState(false);
  const [regType, setRegType] = useState<'local' | 'git'>('local');
  const [regName, setRegName] = useState('');
  const [regPath, setRegPath] = useState('');
  const [regUrl, setRegUrl] = useState('');
  const [regSystem, setRegSystem] = useState(system);
  const [regBranch, setRegBranch] = useState('main');
  const [regSpecguardPath, setRegSpecguardPath] = useState('');
  const [regCloneDir, setRegCloneDir] = useState('');
  const [pickerFor, setPickerFor] = useState<'local' | 'git' | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  // 栏1切换系统 → 注册表单系统下拉跟随（用户手改过别的系统则不打扰，除非该值已不在系统列表）
  useEffect(() => {
    setRegSystem(system);
  }, [system]);

  // ── 文档加载 ──
  const loadFiles = useCallback(async () => {
    try {
      const result = await workspaceApi.specFiles();
      setFiles(result.files);
    } catch (e: any) {
      setError(e.message || '加载文件列表失败');
      setFiles([]);
    }
  }, []);

  const readFile = useCallback(async (path: string) => {
    setLoadingFile(true);
    setError('');
    try {
      const result = await workspaceApi.readFile(path);
      setActiveFile(path);
      setFileContent(result.content);
    } catch (e: any) {
      setError(e.message || '读取文件失败');
    } finally {
      setLoadingFile(false);
    }
  }, []);

  // 选中工作区：写入 session（全局生效）；文档浏览展开时同步加载
  const handleSelect = useCallback((name: string) => {
    if (!name || name === selectedRef.current) return;
    // K-042：必须先同步更新 ref 再派发事件（防无限递归爆栈）
    selectedRef.current = name;
    session.setWorkspace(name);
    setSelected(name);
    setActiveFile('');
    setFileContent('');
    if (docsOpen) loadFiles();
  }, [loadFiles, docsOpen]);

  // ── 二级树加载 ──
  const load = useCallback(async () => {
    try {
      const [t, l] = await Promise.all([workspaceApi.tree(), workspaceApi.list()]);
      setTree(t.tree);
      setActive(l.active);
      if (!selectedRef.current) {
        const cur = session.getWorkspace();
        const all = t.tree.flatMap(g => g.workspaces);
        const hit = all.find(w => w.name === cur) || all[0];
        if (hit) handleSelect(hit.name);
      }
    } catch (e: any) {
      setError(e.message);
    }
  }, [handleSelect]);

  useEffect(() => { load(); }, [load]);

  // 顶栏选择器切换 → 联动
  useEffect(() => {
    const onChanged = (e: Event) => {
      const name = (e as CustomEvent<string>).detail;
      if (name && name !== selectedRef.current) handleSelect(name);
    };
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
  }, [handleSelect]);

  // 展开文档浏览时才拉文件列表（长操作按需触发）
  useEffect(() => {
    localStorage.setItem('sg_sysconf_docs', docsOpen ? '1' : '0');
    if (docsOpen && selectedRef.current) loadFiles();
  }, [docsOpen, loadFiles]);

  // ── 同步（git 型，admin/tester）──
  const handleSync = async (name: string) => {
    setSyncing(name);
    setSyncMsg('');
    setError('');
    try {
      const result = await workspaceApi.pull(name);
      if (!result.ok) {
        setError(`同步失败: ${result.error || '未知错误'}`);
      } else {
        const verdict = result.report?.verdict;
        const changeText = result.changed
          ? `有变更 ${result.old_commit} → ${result.new_commit}`
          : '已是最新';
        setSyncMsg(`${name}: ${changeText}${verdict ? ` · 合规 ${verdict}` : ''}`);
        load();
        if (name === selectedRef.current && docsOpen) loadFiles();
      }
    } catch (e: any) {
      setError(`同步失败: ${e.message}`);
    } finally {
      setSyncing('');
    }
  };

  // ── 注册（登录即可）──
  const handleRegister = async () => {
    if (!regName) { setError('请输入工作区名称'); return; }
    setSubmitting(true);
    setError('');
    setSuccess('');
    try {
      if (regType === 'local') {
        if (!regPath) { setError('请输入本地路径'); return; }
        const result = await workspaceApi.registerLocal({ name: regName, path: regPath, system: regSystem, specguard_path: regSpecguardPath || undefined } as any);
        if (!result.ok) {
          setError(result.error || '注册失败');
          if (result.report) setConformance(result.report);
        } else {
          setSuccess(`工作区 ${regName} 注册成功${result.system_pending ? '（系统适配包待接入，跑测试前请先在栏1注册系统）' : ''}`);
          setRegName(''); setRegPath(''); setRegSpecguardPath('');
          setShowRegister(false);
          load();
        }
      } else {
        if (!regUrl) { setError('请输入 git URL'); return; }
        const result = await workspaceApi.registerGit({ name: regName, url: regUrl, system: regSystem, branch: regBranch, specguard_path: regSpecguardPath || undefined, clone_dir: regCloneDir || undefined } as any);
        if (!result.ok) {
          setError(result.error || '注册失败');
          if (result.report) setConformance(result.report);
        } else {
          setSuccess(`工作区 ${regName} 克隆成功${result.system_pending ? '（系统适配包待接入）' : ''}`);
          setRegName(''); setRegUrl(''); setRegSpecguardPath(''); setRegCloneDir('');
          setShowRegister(false);
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
    try {
      await workspaceApi.unregister(name);
      if (selectedRef.current === name) setSelected('');
      load();
    } catch (e: any) { setError(e.message); }
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

  // 当前系统分组（tree 的组键即 WorkspaceInfo.system）
  const group = tree.find(g => g.system === system);
  const workspaces = group?.workspaces || [];

  return (
    <div className="h-full flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-2 flex-shrink-0">
        <span className="text-xs font-medium text-gray-300">🗂 工作区（{system || '—'}）</span>
        <button onClick={() => setShowRegister(true)}
          className="px-2 py-1 bg-info text-white rounded text-xs hover:bg-info/90">
          + 注册工作区
        </button>
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-2 text-red-400 text-xs flex-shrink-0">{error}</div>}
      {success && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 mb-2 text-green-400 text-xs flex-shrink-0">{success}</div>}
      {syncMsg && <div className="bg-info/10 border border-info/30 rounded p-2 mb-2 text-info text-xs flex-shrink-0">⟳ {syncMsg}</div>}

      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 pr-1">
        {/* 当前系统的工作区卡片 */}
        {!system ? (
          <div className="text-center text-gray-600 text-xs py-6">先在栏1选择系统</div>
        ) : workspaces.length === 0 ? (
          <div className="text-center text-gray-600 text-xs py-6">
            系统「{system}」下暂无工作区，点击右上「注册工作区」接入
          </div>
        ) : (
          <div className="space-y-2">
            {workspaces.map(ws => (
              <div key={ws.name}
                onClick={() => handleSelect(ws.name)}
                className={`p-2.5 rounded-lg border cursor-pointer transition-colors ${
                  selected === ws.name ? 'border-info bg-info/5' : 'border-border bg-surface-1 hover:border-gray-600'
                }`}>
                <div className="flex items-center gap-1.5 mb-1.5">
                  <span className="text-sm text-gray-300 font-medium truncate">{ws.name}</span>
                  {selected === ws.name && <span className="px-1.5 py-0.5 rounded text-fs-aux bg-info/20 text-info flex-shrink-0">当前</span>}
                  {active === ws.name && <span className="px-1.5 py-0.5 rounded text-fs-aux bg-green-900/30 text-green-400 flex-shrink-0">全局激活</span>}
                  {ws.system_pending && <span className="px-1.5 py-0.5 rounded text-fs-aux bg-amber-900/30 text-amber-400 flex-shrink-0">⏳ 包待接入</span>}
                </div>
                <div className="flex items-center gap-1.5 text-[11px] text-gray-500 mb-2 min-w-0">
                  <span className={`px-1 py-0.5 rounded flex-shrink-0 ${ws.source.type === 'git' ? 'bg-info/10 text-info/80' : 'bg-surface-3 text-gray-500'}`}>
                    {ws.source.type === 'git' ? 'git' : 'local'}
                  </span>
                  {ws.owner_emp && <span className="px-1 py-0.5 rounded bg-surface-3 flex-shrink-0">👤 {ws.owner_emp}</span>}
                  {ws.last_commit && <span className="font-mono truncate">commit: {ws.last_commit}</span>}
                </div>
                <div className="flex gap-1 flex-wrap" onClick={e => e.stopPropagation()}>
                  {ws.source.type === 'git' && canSync && (
                    <button onClick={() => handleSync(ws.name)} disabled={syncing === ws.name}
                      className="px-2 py-1 text-xs bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40">
                      {syncing === ws.name ? '同步中...' : '⟳ 同步'}
                    </button>
                  )}
                  {active !== ws.name && (
                    <button onClick={() => handleActivate(ws.name)} className="px-2 py-1 text-xs bg-surface-3 text-gray-400 rounded hover:bg-surface-2">激活</button>
                  )}
                  {isAdmin && (
                    <button onClick={() => handleConformance(ws.name)} className="px-2 py-1 text-xs bg-surface-3 text-gray-400 rounded hover:bg-surface-2">校验</button>
                  )}
                  {isAdmin && (
                    <button onClick={() => handleUnregister(ws.name)} className="px-2 py-1 text-xs bg-red-900/30 text-red-400 rounded hover:bg-red-900/50">注销</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 合规报告（admin） */}
        {isAdmin && loadingConformance && <div className="text-center text-gray-500 text-xs py-2">校验中...</div>}
        {isAdmin && conformance && (
          <div className="bg-surface-1 rounded-lg border border-border p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500">合规校验报告</span>
              <span className={`text-xs font-bold ${conformance.verdict === 'PASS' ? 'text-green-400' : 'text-red-400'}`}>{conformance.verdict}</span>
            </div>
            {conformance.findings && conformance.findings.length > 0 ? (
              <div className="space-y-1 max-h-40 overflow-y-auto">
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

        {/* 文档浏览（折叠区） */}
        <div className="bg-surface-1 rounded-lg border border-border">
          <button onClick={() => setDocsOpen(v => !v)}
            className="w-full flex items-center justify-between px-3 py-2 text-xs text-gray-400 hover:text-gray-200">
            <span>📄 文档浏览{selected ? ` · ${selected}` : ''}</span>
            <span className="text-fs-aux text-gray-600">{docsOpen ? '▼ 收起' : '▶ 展开'}</span>
          </button>
          {docsOpen && (
            <div className="border-t border-border p-2 flex gap-2 h-96">
              <div className="w-52 flex-shrink-0 bg-surface-2 rounded border border-border overflow-hidden flex flex-col">
                <div className="p-2 text-fs-aux text-gray-500 border-b border-border flex items-center justify-between">
                  <span>文档</span>
                  <span className="text-gray-600">{files.length} 文件</span>
                </div>
                {selected ? (
                  <FileTree files={files} selectedPath={activeFile} onSelect={readFile} mode="view" searchable className="flex-1" />
                ) : (
                  <div className="flex-1 flex items-center justify-center text-gray-600 text-fs-aux p-3 text-center">选择上方工作区浏览文档</div>
                )}
              </div>
              <div className="flex-1 min-w-0 bg-surface-2 rounded border border-border overflow-hidden flex flex-col">
                {activeFile ? (
                  <>
                    <div className="px-3 py-1.5 border-b border-border flex items-center justify-between flex-shrink-0">
                      <span className="text-fs-aux font-mono text-gray-400 truncate">{activeFile}</span>
                      {loadingFile && <span className="text-fs-aux text-gray-500">读取中...</span>}
                    </div>
                    <FileViewer path={activeFile} content={fileContent} loading={loadingFile} />
                  </>
                ) : (
                  <div className="flex-1 flex items-center justify-center text-gray-600 text-xs">选择左侧文件查看内容</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 注册工作区弹层（登录即可；z-40 让 DirectoryPicker 的 z-50 浮在上层） */}
      {showRegister && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-40" onClick={() => setShowRegister(false)}>
          <div className="bg-surface-1 rounded-lg border border-border p-4 w-full max-w-2xl max-h-[90vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold text-gray-200 mb-1">注册工作区</h3>
            <div className="text-xs text-gray-500 mb-3">注册人即归属人，系统包未建可先用待接入态</div>
            <div className="flex gap-2 mb-3">
              <button onClick={() => setRegType('local')} className={`px-3 py-1 text-xs rounded ${regType === 'local' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>本地文件夹</button>
              <button onClick={() => setRegType('git')} className={`px-3 py-1 text-xs rounded ${regType === 'git' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>Git 仓库</button>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input value={regName} onChange={e => setRegName(e.target.value)} placeholder="工作区名称" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              {systems.length > 0 ? (
                <select value={regSystem} onChange={e => setRegSystem(e.target.value)} title="归属系统（默认跟随栏1选中）"
                  className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300">
                  {systems.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                  {!systems.some(s => s.name === regSystem) && regSystem && <option value={regSystem}>{regSystem}（待接入）</option>}
                </select>
              ) : (
                <input value={regSystem} onChange={e => setRegSystem(e.target.value)} placeholder="系统标识 (tdm)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
              )}
              {(() => {
                const cur = systems.find(s => s.name === regSystem);
                return cur ? (
                  <div className="col-span-2 text-[11px] text-gray-500 bg-surface-2/50 rounded px-2 py-1">
                    环境: {cur.envs.join(', ') || '无'} · 账号别名: {cur.accounts.join(', ') || '无'}
                  </div>
                ) : (
                  <div className="col-span-2 text-[11px] text-amber-500/80 bg-amber-900/10 rounded px-2 py-1">
                    ⏳ 系统「{regSystem}」适配包未建——工作区可先注册（待接入），跑测试前需先在栏1注册系统
                  </div>
                );
              })()}
              {regType === 'local' ? (
                <div className="col-span-2 flex gap-2">
                  <input value={regPath} onChange={e => setRegPath(e.target.value)} placeholder="本地路径 (D:/work/spec-tdm)" className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
                  <button onClick={() => setPickerFor('local')} className="px-2.5 py-1.5 text-xs bg-surface-3 text-gray-400 rounded hover:bg-surface-2 flex-shrink-0" title="浏览选择目录">📂 浏览</button>
                </div>
              ) : (
                <>
                  <input value={regUrl} onChange={e => setRegUrl(e.target.value)} placeholder="Git URL" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
                  <input value={regBranch} onChange={e => setRegBranch(e.target.value)} placeholder="分支 (main)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
                  <div className="col-span-2 flex gap-2">
                    <input value={regCloneDir} onChange={e => setRegCloneDir(e.target.value)} placeholder="克隆目录（可选，默认 {specguard}/workspaces/_clones/{名称}）" className="flex-1 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
                    <button onClick={() => setPickerFor('git')} className="px-2.5 py-1.5 text-xs bg-surface-3 text-gray-400 rounded hover:bg-surface-2 flex-shrink-0" title="浏览选择目录">📂 浏览</button>
                  </div>
                </>
              )}
              <input value={regSpecguardPath} onChange={e => setRegSpecguardPath(e.target.value)} placeholder=".specguard 目录位置（可选，默认 {工作区}/.specguard/）" className="col-span-2 bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowRegister(false)} className="px-3 py-1.5 text-sm bg-surface-3 text-gray-400 rounded">取消</button>
              <button onClick={handleRegister} disabled={submitting}
                className="px-4 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90 disabled:opacity-40">
                {submitting ? '处理中...' : regType === 'local' ? '注册' : '克隆并注册'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 目录选择弹窗（本地路径 / 克隆落点） */}
      <DirectoryPicker
        open={pickerFor !== null}
        title={pickerFor === 'git' ? '选择克隆目录（可选，留空用默认落点）' : '选择本地文件夹'}
        onSelect={p => {
          if (pickerFor === 'git') setRegCloneDir(p); else setRegPath(p);
          setPickerFor(null);
        }}
        onClose={() => setPickerFor(null)}
      />
    </div>
  );
}
