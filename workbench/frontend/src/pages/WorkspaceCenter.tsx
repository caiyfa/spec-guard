/**
 * WorkspaceCenter — 工作区中心（K-009：合并原「工作区管理」+「文档中心」）
 *
 * 上部：工作区列表（浏览/同步/校验/注销 + admin 注册表单 + 合规报告）
 * 下部：文档浏览区（FileTree + FileViewer），绑定当前选中工作区
 *
 * 选中工作区即写入 session（X-SG-Workspace），场景管理等页面自动跟随；
 * 顶栏选择器切换时通过 sg-workspace-changed 事件联动重载。
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router';
import { workspaceApi, session, WORKSPACE_CHANGED_EVENT, type WorkspaceInfo } from '../api';
import FileTree from '../components/FileTree';
import FileViewer from '../components/FileViewer';
import DirectoryPicker from '../components/DirectoryPicker';
import type { FlatFile } from '../components/FileTree';

export default function WorkspaceCenter({ role }: { role: string }) {
  const isAdmin = role === 'admin';
  const canSync = isAdmin || role === 'tester';
  const navigate = useNavigate();

  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  const [active, setActive] = useState('');
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [conformance, setConformance] = useState<any>(null);
  const [loadingConformance, setLoadingConformance] = useState(false);

  // 同步状态
  const [syncing, setSyncing] = useState('');
  const [syncMsg, setSyncMsg] = useState('');

  // 文档浏览
  const [files, setFiles] = useState<FlatFile[]>([]);
  const [activeFile, setActiveFile] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [loadingFile, setLoadingFile] = useState(false);

  // 注册表单（admin）
  const [showRegister, setShowRegister] = useState(false);
  const [regType, setRegType] = useState<'local' | 'git'>('local');
  const [regName, setRegName] = useState('');
  const [regPath, setRegPath] = useState('');
  const [regUrl, setRegUrl] = useState('');
  const [regSystem, setRegSystem] = useState('tdm');
  const [regBranch, setRegBranch] = useState('main');
  const [regSpecguardPath, setRegSpecguardPath] = useState('');
  const [regCloneDir, setRegCloneDir] = useState(''); // git 型：自定义克隆落点（可选）
  const [pickerFor, setPickerFor] = useState<'local' | 'git' | null>(null); // 目录选择弹窗目标
  const [submitting, setSubmitting] = useState(false);

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

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

  // 选中工作区：写入 session（全局生效）并加载文档
  const handleSelect = useCallback((name: string) => {
    if (!name || name === selectedRef.current) return;
    // K-042：必须先同步更新 ref 再派发事件——selectedRef.current 平时在渲染期赋值（第 51 行），
    // 而 setWorkspace 同步派发 WORKSPACE_CHANGED_EVENT，自身 onChanged 监听在同一调用栈内触发，
    // 此时 setSelected 尚未触发重渲染、ref 还是旧值 → 守卫失效 → handleSelect 无限递归爆栈
    selectedRef.current = name;
    session.setWorkspace(name); // 触发 WORKSPACE_CHANGED_EVENT（自身监听器因上面的同步守卫忽略）
    setSelected(name);
    setActiveFile('');
    setFileContent('');
    loadFiles();
  }, [loadFiles]);

  // ── 工作区列表 ──
  const load = useCallback(async () => {
    try {
      const data = await workspaceApi.list();
      setWorkspaces(data.workspaces);
      setActive(data.active);
      // 默认选中：session 当前工作区（在列表内）→ 否则列表第一项
      if (!selectedRef.current && data.workspaces.length > 0) {
        const cur = session.getWorkspace();
        const hit = data.workspaces.find(w => w.name === cur) || data.workspaces[0];
        handleSelect(hit.name);
      }
    } catch (e: any) {
      setError(e.message);
    }
  }, [handleSelect]);

  useEffect(() => { load(); }, [load]);

  // 顶栏选择器切换 → 联动重载
  useEffect(() => {
    const onChanged = (e: Event) => {
      const name = (e as CustomEvent<string>).detail;
      if (name && name !== selectedRef.current) handleSelect(name);
    };
    window.addEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(WORKSPACE_CHANGED_EVENT, onChanged);
  }, [handleSelect]);

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
        if (name === selectedRef.current) loadFiles();
      }
    } catch (e: any) {
      setError(`同步失败: ${e.message}`);
    } finally {
      setSyncing('');
    }
  };

  // ── 管理操作（admin）──
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
          setSuccess(`工作区 ${regName} 注册成功`);
          setRegName(''); setRegPath(''); setRegSpecguardPath('');
          load();
        }
      } else {
        if (!regUrl) { setError('请输入 git URL'); return; }
        const result = await workspaceApi.registerGit({ name: regName, url: regUrl, system: regSystem, branch: regBranch, specguard_path: regSpecguardPath || undefined, clone_dir: regCloneDir || undefined } as any);
        if (!result.ok) {
          setError(result.error || '注册失败');
          if (result.report) setConformance(result.report);
        } else {
          setSuccess(`工作区 ${regName} 克隆成功`);
          setRegName(''); setRegUrl(''); setRegSpecguardPath(''); setRegCloneDir('');
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

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="flex items-center justify-between flex-shrink-0">
        <div>
          <h2 className="text-lg font-bold text-gray-200">🗂 工作区中心</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            选择/同步 spec 工作区并浏览文档；选中后场景管理等页面自动跟随
          </p>
        </div>
        {isAdmin && (
          <button
            onClick={() => setShowRegister(v => !v)}
            className="px-3 py-1.5 bg-info text-white rounded-md text-xs hover:bg-info/90"
          >
            {showRegister ? '收起注册' : '+ 注册工作区'}
          </button>
        )}
      </div>

      {error && <div className="bg-red-900/30 border border-red-700/50 rounded p-2 text-red-400 text-sm flex-shrink-0">{error}</div>}
      {success && <div className="bg-green-900/30 border border-green-700/50 rounded p-2 text-green-400 text-sm flex-shrink-0">{success}</div>}
      {syncMsg && <div className="bg-info/10 border border-info/30 rounded p-2 text-info text-sm flex-shrink-0">⟳ {syncMsg}</div>}

      {/* 工作区列表 */}
      <div className="flex-shrink-0">
        <div className="text-xs text-gray-500 mb-2">已注册工作区 ({workspaces.length})</div>
        {workspaces.length === 0 ? (
          <div className="text-center text-gray-600 text-sm py-4">暂无工作区{isAdmin ? '，点击右上角「注册工作区」接入' : ''}</div>
        ) : (
          <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
            {workspaces.map(ws => (
              <div
                key={ws.name}
                onClick={() => handleSelect(ws.name)}
                className={`flex items-center justify-between p-2 rounded-lg border cursor-pointer ${
                  selected === ws.name ? 'border-info bg-info/5' : 'border-border bg-surface-1 hover:border-gray-600'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <span className="text-sm text-gray-300">{ws.name}</span>
                  {selected === ws.name && <span className="text-[10px] text-info ml-2">当前</span>}
                  {active === ws.name && <span className="text-[10px] text-green-500 ml-1">全局激活</span>}
                  <span className="text-xs text-gray-600 ml-2">{ws.system}</span>
                  <span className="text-xs text-gray-600 ml-2">{ws.source.type === 'git' ? 'git' : 'local'}</span>
                  {ws.last_commit && <span className="text-xs text-gray-600 ml-2">commit: {ws.last_commit}</span>}
                </div>
                <div className="flex gap-1" onClick={e => e.stopPropagation()}>
                  {ws.source.type === 'git' && (
                    <button
                      onClick={() => { handleSelect(ws.name); navigate('/workspace/git-log'); }}
                      className="px-2 py-1 text-xs bg-surface-3 text-gray-400 rounded hover:bg-surface-2"
                      title="查看 git 提交历史（SourceTree 风格）"
                    >
                      📜 记录
                    </button>
                  )}
                  {ws.source.type === 'git' && canSync && (
                    <button
                      onClick={() => handleSync(ws.name)}
                      disabled={syncing === ws.name}
                      className="px-2 py-1 text-xs bg-info/20 text-info rounded hover:bg-info/30 disabled:opacity-40"
                    >
                      {syncing === ws.name ? '同步中...' : '⟳ 同步'}
                    </button>
                  )}
                  {isAdmin && active !== ws.name && (
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
      </div>

      {/* 注册新工作区（admin，可折叠） */}
      {isAdmin && showRegister && (
        <div className="bg-surface-1 rounded-lg border border-border p-3 flex-shrink-0">
          <div className="text-xs text-gray-500 mb-3">注册新工作区</div>
          <div className="flex gap-2 mb-3">
            <button onClick={() => setRegType('local')} className={`px-3 py-1 text-xs rounded ${regType === 'local' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>本地文件夹</button>
            <button onClick={() => setRegType('git')} className={`px-3 py-1 text-xs rounded ${regType === 'git' ? 'bg-info text-white' : 'bg-surface-3 text-gray-400'}`}>Git 仓库</button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input value={regName} onChange={e => setRegName(e.target.value)} placeholder="工作区名称" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
            <input value={regSystem} onChange={e => setRegSystem(e.target.value)} placeholder="系统标识 (tdm)" className="bg-surface-2 border border-border rounded px-2 py-1.5 text-sm text-gray-300" />
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
          <button onClick={handleRegister} disabled={submitting} className="mt-2 px-4 py-1.5 bg-info text-white rounded text-sm hover:bg-info/90 disabled:opacity-40">
            {submitting ? '处理中...' : regType === 'local' ? '注册' : '克隆并注册'}
          </button>
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

      {/* 合规报告（admin） */}
      {isAdmin && loadingConformance && <div className="text-center text-gray-500 text-sm py-2 flex-shrink-0">校验中...</div>}
      {isAdmin && conformance && (
        <div className="bg-surface-1 rounded-lg border border-border p-3 flex-shrink-0">
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

      {/* 文档浏览区 */}
      <div className="flex-1 min-h-[320px] flex gap-3 min-h-0">
        {/* 左侧：文件树 */}
        <div className="w-64 flex-shrink-0 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          <div className="p-2 text-xs text-gray-500 border-b border-border flex items-center justify-between">
            <span>文档{selected ? ` · ${selected}` : ''}</span>
            <span className="text-[10px] text-gray-600">{files.length} 文件</span>
          </div>
          {selected ? (
            <FileTree
              files={files}
              selectedPath={activeFile}
              onSelect={readFile}
              mode="view"
              searchable
              className="flex-1"
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-xs p-3 text-center">
              选择上方工作区浏览文档
            </div>
          )}
        </div>

        {/* 右侧：文件渲染 */}
        <div className="flex-1 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          {activeFile ? (
            <>
              <div className="px-3 py-2 border-b border-border flex items-center justify-between flex-shrink-0">
                <span className="text-xs font-mono text-gray-400 truncate">{activeFile}</span>
                {loadingFile && <span className="text-xs text-gray-500">读取中...</span>}
              </div>
              <FileViewer
                path={activeFile}
                content={fileContent}
                loading={loadingFile}
              />
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-600 text-sm">
              选择左侧文件查看内容
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
