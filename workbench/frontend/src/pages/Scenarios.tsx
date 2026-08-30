/**
 * Scenarios — 场景管理（K-011：原 Plans 页「新建场景」Tab 升级为独立页）
 *
 * 三栏布局：
 *   左：文件选择（FileTree / 内容搜索）
 *   中：场景名称 + 基础信息包 + 操作（保存信息包 / 启动 Agent）
 *   右：已有场景（全高独立栏，点击回填继续编辑）
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { scenarioApi, workspaceApi, session } from '../api';
import type { ScenarioMeta } from '../api';
import FileTree from '../components/FileTree';
import type { FlatFile } from '../components/FileTree';

interface SearchResult {
  path: string;
  match_type: string;
  line?: number;
  preview: string;
  size: number;
}

export default function Scenarios() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [meta, setMeta] = useState<ScenarioMeta | null>(null);
  const [files, setFiles] = useState<FlatFile[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [existingMetas, setExistingMetas] = useState<ScenarioMeta[]>([]);

  const currentWorkspace = session.getWorkspace();

  // 加载文件列表
  const loadFiles = useCallback(async () => {
    try {
      const r = await workspaceApi.specFiles();
      setFiles(r.files || []);
    } catch {
      setFiles([]);
    }
  }, []);

  // 加载已有场景元数据
  const loadMetas = useCallback(async () => {
    try {
      const r = await scenarioApi.listMeta();
      setExistingMetas(r.metas || []);
    } catch {
      setExistingMetas([]);
    }
  }, []);

  useEffect(() => {
    loadFiles();
    loadMetas();
  }, [loadFiles, loadMetas]);

  // 内容搜索（防抖）
  useEffect(() => {
    if (!searchQuery || searchQuery.length < 2) {
      setSearchResults([]);
      return;
    }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await workspaceApi.search(searchQuery);
        setSearchResults(r.results || []);
      } catch {
        setSearchResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // 创建场景
  const handleCreate = async () => {
    if (!name.trim()) {
      setError('请填写场景名称');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const m = await scenarioApi.create({ name: name.trim() });
      setMeta(m);
    } catch (e: any) {
      setError(e.message || '创建失败');
    } finally {
      setLoading(false);
    }
  };

  const toggleFile = (path: string) => {
    setSelectedFiles(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // 保存基础信息包
  const handleSaveInfoPack = async () => {
    if (!meta) return;
    setLoading(true);
    setError('');
    try {
      const fileList = Array.from(selectedFiles);
      const updated = await scenarioApi.updateInfoPack(meta.id, fileList);
      setMeta(updated);
    } catch (e: any) {
      setError(e.message || '保存失败');
    } finally {
      setLoading(false);
    }
  };

  // 启动 Agent 分析
  const handleLaunchAgent = () => {
    if (!meta) return;
    navigate(`/agent?scenario_id=${meta.id}`);
  };

  // 回填已有场景继续编辑
  const handleLoadMeta = (m: ScenarioMeta) => {
    setMeta(m);
    setName(m.name);
    setSelectedFiles(new Set((m.info_pack || []).map(e => e.path)));
  };

  return (
    <div className="h-full flex flex-col">
      <div className="mb-3">
        <h2 className="text-lg font-bold text-gray-200">🧩 场景管理</h2>
        <p className="text-fs-body text-gray-500 mt-0.5">
          输入名称 → 选择文件（支持搜索）→ 启动 Agent 生成；场景内容编辑与依赖编排在「DAG 编排」页
        </p>
      </div>

      {error && (
        <div className="mb-3 bg-red-900/30 border border-red-700/50 rounded-lg px-3 py-2">
          <span className="text-red-400 text-sm">{error}</span>
        </div>
      )}

      <div className="flex gap-3 flex-1 min-h-0">
        {/* 左栏：文件树 + 搜索 */}
        <div className="w-72 flex-shrink-0 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          {/* 内容搜索框 */}
          <div className="p-2 border-b border-border">
            <input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="搜索文件内容（≥2字符）..."
              className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-300 placeholder-gray-600 focus:border-info outline-none"
            />
          </div>

          {searchQuery.length >= 2 ? (
            // 搜索结果模式
            <div className="flex-1 overflow-y-auto p-1">
              <div className="text-fs-aux text-gray-500 px-1 py-1">
                {searching ? '搜索中...' : `${searchResults.length} 个结果`}
              </div>
              {searchResults.map((r, i) => (
                <div
                  key={i}
                  onClick={() => toggleFile(r.path)}
                  className={`px-2 py-1.5 rounded text-fs-body cursor-pointer transition-colors mb-0.5 ${
                    selectedFiles.has(r.path)
                      ? 'bg-info/10 text-info'
                      : 'text-gray-400 hover:bg-surface-3'
                  }`}
                >
                  <div className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={selectedFiles.has(r.path)}
                      onChange={() => toggleFile(r.path)}
                      onClick={e => e.stopPropagation()}
                      className="w-3 h-3 accent-info flex-shrink-0"
                    />
                    <span className="truncate flex-1 font-mono text-fs-aux">{r.path}</span>
                    {r.match_type === 'content' && r.line && (
                      <span className="text-fs-micro text-gray-600">L{r.line}</span>
                    )}
                  </div>
                  {r.preview && (
                    <div className="text-fs-aux text-gray-600 mt-0.5 truncate pl-5">
                      {r.preview.replace(/\n/g, ' ')}
                    </div>
                  )}
                </div>
              ))}
              {searchResults.length === 0 && !searching && (
                <div className="text-center text-gray-600 text-fs-body py-4">无匹配结果</div>
              )}
            </div>
          ) : (
            // 文件树模式
            <FileTree
              files={files}
              selectedPaths={selectedFiles}
              onToggle={toggleFile}
              mode="select"
              searchable
              className="flex-1"
            />
          )}
        </div>

        {/* 中栏：场景信息 + 已选文件 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 场景名称 */}
          <div className="bg-surface-2 border border-border rounded-lg p-3 mb-3">
            <label className="block text-fs-body text-gray-400 mb-1">场景名称</label>
            <div className="flex gap-2">
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="如：员工全景档案-权限校验"
                className="flex-1 bg-surface-3 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none"
              />
              <button
                onClick={handleCreate}
                disabled={loading || !name.trim() || !!meta}
                className="px-4 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
              >
                {meta ? '✓ 已创建' : loading ? '创建中...' : '创建'}
              </button>
            </div>
            {meta && (
              <div className="mt-2 text-fs-aux text-gray-500">
                ID: <span className="font-mono text-info">{meta.id}</span>
                {currentWorkspace && <span className="ml-2">工作区: {currentWorkspace}</span>}
              </div>
            )}
          </div>

          {/* 已选文件 + 操作 */}
          <div className="flex-1 bg-surface-2 border border-border rounded-lg p-3 overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <span className="text-fs-body text-gray-400">基础信息包（{selectedFiles.size} 个文件）</span>
              {selectedFiles.size > 0 && (
                <button
                  onClick={() => setSelectedFiles(new Set())}
                  className="text-fs-aux text-gray-500 hover:text-fail"
                >
                  清空
                </button>
              )}
            </div>
            {selectedFiles.size === 0 ? (
              <div className="text-center text-gray-600 text-fs-body py-8">
                从左侧文件树或搜索结果中选择文件
              </div>
            ) : (
              <div className="space-y-0.5">
                {Array.from(selectedFiles).map(path => (
                  <div key={path} className="flex items-center gap-2 px-2 py-1 hover:bg-surface-3 rounded group">
                    <span className="text-fs-aux">📄</span>
                    <span className="text-fs-body font-mono text-gray-400 truncate flex-1">{path}</span>
                    <button
                      onClick={() => toggleFile(path)}
                      className="text-red-500 text-fs-aux opacity-0 group-hover:opacity-100"
                    >✕</button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 底部操作栏 */}
          <div className="flex items-center gap-2 mt-3">
            <button
              onClick={handleSaveInfoPack}
              disabled={loading || !meta || selectedFiles.size === 0}
              className="px-4 py-2 bg-surface-3 text-gray-300 rounded-lg text-sm hover:bg-surface-2 border border-border disabled:opacity-40 disabled:cursor-not-allowed"
            >
              💾 保存信息包
            </button>
            <button
              onClick={handleLaunchAgent}
              disabled={!meta || selectedFiles.size === 0}
              className="px-5 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              🚀 启动 Agent
            </button>
          </div>
        </div>

        {/* 右栏：已有场景（全高独立栏） */}
        <div className="w-72 flex-shrink-0 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-border text-fs-body text-gray-500 bg-surface-2 flex items-center justify-between">
            <span>已有场景（{existingMetas.length}）</span>
            <button onClick={loadMetas} className="text-fs-aux text-gray-600 hover:text-info">刷新</button>
          </div>
          <div className="flex-1 overflow-y-auto p-1">
            {existingMetas.length === 0 ? (
              <div className="text-center text-gray-600 text-fs-body py-8">暂无场景</div>
            ) : (
              existingMetas.map(m => (
                <button
                  key={m.id}
                  onClick={() => handleLoadMeta(m)}
                  className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded text-fs-body mb-0.5 transition-colors ${
                    meta?.id === m.id ? 'bg-info/10 text-info' : 'hover:bg-surface-3 text-gray-400'
                  }`}
                >
                  <span className="font-mono text-fs-aux text-info">{m.id}</span>
                  <span className="truncate flex-1">{m.name}</span>
                  <span className="text-fs-aux text-gray-600">{m.info_pack?.length || 0} 文件</span>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
