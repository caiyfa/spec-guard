/**
 * SpecCenter — 文档中心：FileTree + FileViewer（md/html/yaml 成熟框架渲染）
 */

import { useState, useEffect, useCallback } from 'react';
import { workspaceApi } from '../api';
import FileTree from '../components/FileTree';
import FileViewer from '../components/FileViewer';
import type { FlatFile } from '../components/FileTree';

export default function SpecCenter() {
  const [files, setFiles] = useState<FlatFile[]>([]);
  const [activeFile, setActiveFile] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadFiles = useCallback(async () => {
    setError('');
    try {
      const result = await workspaceApi.specFiles();
      setFiles(result.files);
      setWorkspace(result.workspace);
    } catch (e: any) {
      setError(e.message || '加载文件列表失败');
      setFiles([]);
    }
  }, []);

  const readFile = useCallback(async (path: string) => {
    setLoading(true);
    setError('');
    try {
      const result = await workspaceApi.readFile(path);
      setActiveFile(path);
      setFileContent(result.content);
    } catch (e: any) {
      setError(e.message || '读取文件失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  return (
    <div className="flex flex-col h-full">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-200">文档中心</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {workspace ? `工作区: ${workspace} · ${files.length} 个文件` : '无激活工作区'}
          </p>
        </div>
        <button
          onClick={loadFiles}
          className="px-3 py-1.5 bg-surface-3 text-gray-300 rounded-md text-xs hover:bg-surface-2 border border-border"
        >
          刷新
        </button>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-700/50 rounded p-2 mb-3">
          <span className="text-red-400 text-sm">❌ {error}</span>
        </div>
      )}

      <div className="flex gap-3 flex-1 min-h-0">
        {/* 左侧：文件树 */}
        <div className="w-64 flex-shrink-0 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          <div className="p-2 text-xs text-gray-500 border-b border-border flex items-center justify-between">
            <span>文件树</span>
            <span className="text-[10px] text-gray-600">{files.length} 文件</span>
          </div>
          <FileTree
            files={files}
            selectedPath={activeFile}
            onSelect={readFile}
            mode="view"
            searchable
            className="flex-1"
          />
        </div>

        {/* 右侧：文件渲染 */}
        <div className="flex-1 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          {activeFile ? (
            <>
              <div className="px-3 py-2 border-b border-border flex items-center justify-between flex-shrink-0">
                <span className="text-xs font-mono text-gray-400 truncate">{activeFile}</span>
                {loading && <span className="text-xs text-gray-500">读取中...</span>}
              </div>
              <FileViewer
                path={activeFile}
                content={fileContent}
                loading={loading}
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
