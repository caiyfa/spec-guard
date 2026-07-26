// Spec 文档中心：当前工作区文件树 + delta 标记 + 文件内容查看

import { useState, useEffect } from 'react';
import { workspaceApi } from '../api';

interface SpecFile {
  path: string;
  is_delta: boolean;
  size: number;
}

export default function SpecCenter() {
  const [files, setFiles] = useState<SpecFile[]>([]);
  const [activeFile, setActiveFile] = useState('');
  const [fileContent, setFileContent] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadFiles = async () => {
    setError('');
    try {
      const result = await workspaceApi.specFiles();
      setFiles(result.files);
      setWorkspace(result.workspace);
    } catch (e: any) {
      setError(e.message || '加载文件列表失败');
      setFiles([]);
    }
  };

  const readFile = async (path: string) => {
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
  };

  useEffect(() => {
    loadFiles();
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / 1048576).toFixed(1)}MB`;
  };

  return (
    <div className="flex flex-col h-full">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-200">📄 Spec 文档中心</h2>
          <p className="text-xs text-gray-500 mt-1">
            {workspace ? `当前工作区: ${workspace}` : '无激活工作区'}
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

      <div className="flex gap-4 flex-1 min-h-0">
        {/* 文件树 */}
        <div className="w-64 flex-shrink-0 bg-surface-1 rounded-lg border border-border overflow-y-auto">
          <div className="p-2 text-xs text-gray-500 border-b border-border">
            文件列表 ({files.length})
          </div>
          <div className="p-1">
            {files.length === 0 && (
              <div className="text-center text-gray-600 text-xs py-8">
                {loading ? '加载中...' : '无文件'}
              </div>
            )}
            {files.map((f, i) => (
              <button
                key={i}
                onClick={() => readFile(f.path)}
                className={`w-full text-left px-2 py-1 rounded text-xs hover:bg-surface-3 transition-colors ${
                  activeFile === f.path ? 'bg-info/10 text-info' : 'text-gray-400'
                }`}
              >
                <span className="flex items-center gap-1">
                  {f.is_delta && <span className="text-yellow-500" title="delta 文件">Δ</span>}
                  <span className="truncate flex-1">{f.path}</span>
                  <span className="text-gray-600 text-[10px]">{formatSize(f.size)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* 文件内容 */}
        <div className="flex-1 bg-surface-1 rounded-lg border border-border overflow-hidden flex flex-col">
          {activeFile ? (
            <>
              <div className="px-3 py-2 border-b border-border flex items-center justify-between">
                <span className="text-xs font-mono text-gray-400 truncate">{activeFile}</span>
                {loading && <span className="text-xs text-gray-500">读取中...</span>}
              </div>
              <pre className="flex-1 overflow-auto p-3 text-xs font-mono text-gray-300 bg-gray-900/50">
                {fileContent}
              </pre>
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
