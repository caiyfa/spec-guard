/**
 * DirectoryPicker — 目录选择弹窗（注册工作区时选择本地路径/克隆落点用）
 *
 * 为什么必须走后端 browse-dir API：浏览器原生 <input type=file>/showDirectoryPicker
 * 拿不到绝对路径（安全限制），而注册工作区后端需要真实绝对路径。
 *
 * 交互：单击行进入子目录；行内「选择」快捷确认；底部「选择当前目录」；
 * 顶部路径输入框支持手输回车跳转；关闭后重开恢复上次浏览位置。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import Modal from './Modal';
import { workspaceApi } from '../api';

export interface DirectoryEntry {
  name: string;
  path: string;
}

interface Props {
  open: boolean;
  title?: string;
  onSelect: (path: string) => void;
  onClose: () => void;
}

export default function DirectoryPicker({ open, title = '选择目录', onSelect, onClose }: Props) {
  const [current, setCurrent] = useState('');
  const [parent, setParent] = useState<string | null>(null);
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [pathInput, setPathInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const lastPathRef = useRef(''); // 重开时恢复到上次浏览位置

  const load = useCallback(async (path: string) => {
    setLoading(true);
    setError('');
    try {
      const r = await workspaceApi.browseDir(path);
      if (!r.ok) { setError(r.error || '加载失败'); return; }
      setCurrent(r.current);
      setParent(r.parent);
      setEntries(r.entries);
      setPathInput(r.current);
      lastPathRef.current = r.current;
    } catch (e: any) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  // 打开时加载（根视图或上次位置）
  useEffect(() => {
    if (open) load(lastPathRef.current);
  }, [open, load]);

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title={title} width={560}>
      <div className="p-3.5">
        {/* 路径输入 + 上级 */}
        <div className="flex items-center gap-2 mb-2">
          <button
            onClick={() => parent && load(parent)}
            disabled={!parent || loading}
            className="px-2 py-1.5 text-fs-body bg-surface-3 text-gray-400 rounded hover:bg-surface-2 disabled:opacity-40 flex-shrink-0"
            title="上级目录"
          >
            ⬆ 上级
          </button>
          <input
            value={pathInput}
            onChange={e => setPathInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') load(pathInput); }}
            placeholder="输入路径后回车跳转"
            className="flex-1 bg-surface-3 border border-border rounded px-2 py-1.5 text-fs-body font-mono text-gray-300 focus:border-info outline-none"
          />
        </div>

        {error && (
          <div className="mb-2 text-fs-body text-red-400 bg-red-900/30 border border-red-700/40 rounded px-2 py-1.5">{error}</div>
        )}

        {/* 目录列表 */}
        <div className="h-64 overflow-y-auto bg-surface-1 border border-border rounded">
          {loading ? (
            <div className="flex items-center justify-center h-full text-gray-600 text-fs-body">加载中...</div>
          ) : entries.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-600 text-fs-body">
              {current ? '（无子目录）' : '无可浏览目录'}
            </div>
          ) : (
            entries.map(e => (
              <div
                key={e.path}
                className="flex items-center gap-2 px-2 py-1.5 border-b border-border/40 last:border-0 hover:bg-surface-2 cursor-pointer group"
                onClick={() => load(e.path)}
              >
                <span className="text-gray-500 text-fs-body">📁</span>
                <span className="flex-1 min-w-0 truncate text-fs-body text-gray-300">{e.name}</span>
                <span className="text-fs-aux font-mono text-gray-600 truncate max-w-[38%]">{e.path}</span>
                <button
                  onClick={ev => { ev.stopPropagation(); onSelect(e.path); }}
                  className="text-fs-aux px-1.5 py-0.5 rounded border border-border text-gray-500 hover:text-info hover:border-info/40 flex-shrink-0 opacity-0 group-hover:opacity-100"
                  title={`选择 ${e.path}`}
                >
                  选择
                </button>
              </div>
            ))
          )}
        </div>

        {/* 底部操作 */}
        <div className="flex items-center justify-between mt-2.5">
          <span className="text-fs-aux font-mono text-gray-600 truncate">{current || '（根视图）'}</span>
          <div className="flex gap-2 flex-shrink-0">
            <button onClick={onClose} className="px-3 py-1.5 text-fs-body bg-surface-3 text-gray-400 rounded hover:bg-surface-2">取消</button>
            <button
              onClick={() => current && onSelect(current)}
              disabled={!current || loading}
              className="px-3 py-1.5 text-fs-body bg-info text-white rounded hover:bg-info/90 disabled:opacity-40"
            >
              选择此目录
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
