/**
 * FileTree — 可复用文件树组件
 * - 从扁平文件列表构建树形结构
 * - 文件夹展开/折叠
 * - 文件名搜索
 * - 支持多选（checkbox 模式）和单选（查看模式）
 * - 文件图标按扩展名区分
 */

import { useState, useMemo, useCallback } from 'react';

export interface FlatFile {
  path: string;
  is_delta?: boolean;
  size?: number;
}

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  children?: TreeNode[];
  is_delta?: boolean;
  size?: number;
  level: number;
}

const FILE_ICONS: Record<string, string> = {
  '.md': '📝', '.markdown': '📝',
  '.yaml': '📦', '.yml': '📦',
  '.json': '🔧',
  '.txt': '📄',
  '.html': '🌐', '.htm': '🌐',
  '.xlsx': '📊', '.xls': '📊',
  '.docx': '📘', '.doc': '📘',
  '.csv': '📑',
  '.py': '🐍',
  '.ts': '🔷', '.tsx': '🔷',
  '.js': '🟨',
  '.png': '🖼️', '.jpg': '🖼️', '.jpeg': '🖼️', '.svg': '🖼️',
};

export function getFileIcon(name: string): string {
  const ext = name.match(/\.[^.]+$/)?.[0]?.toLowerCase() || '';
  return FILE_ICONS[ext] || '📄';
}

export function getFileExt(name: string): string {
  return name.match(/\.[^.]+$/)?.[0]?.toLowerCase() || '';
}

/** 从扁平文件列表构建树 */
function buildTree(files: FlatFile[]): TreeNode[] {
  const root: TreeNode = { name: '', path: '', isDir: true, children: [], level: -1 };

  for (const f of files) {
    const parts = f.path.split('/');
    let current = root;
    let accumPath = '';

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      accumPath = accumPath ? `${accumPath}/${part}` : part;
      const isLast = i === parts.length - 1;

      if (isLast) {
        // 文件节点
        current.children = current.children || [];
        current.children.push({
          name: part,
          path: f.path,
          isDir: false,
          is_delta: f.is_delta,
          size: f.size,
          level: i,
        });
      } else {
        // 目录节点
        current.children = current.children || [];
        let dir = current.children.find(c => c.isDir && c.name === part);
        if (!dir) {
          dir = { name: part, path: accumPath, isDir: true, children: [], level: i };
          current.children.push(dir);
        }
        current = dir;
      }
    }
  }

  // 排序：目录在前，文件在后，各自字母序
  function sortNode(node: TreeNode) {
    if (!node.children) return;
    node.children.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sortNode);
  }
  sortNode(root);
  return root.children || [];
}

/** 过滤树（按搜索词） */
function filterTree(nodes: TreeNode[], query: string): TreeNode[] {
  if (!query) return nodes;
  const lower = query.toLowerCase();
  const result: TreeNode[] = [];

  for (const node of nodes) {
    if (node.isDir) {
      const filteredChildren = filterTree(node.children || [], query);
      if (filteredChildren.length > 0 || node.name.toLowerCase().includes(lower)) {
        result.push({ ...node, children: filteredChildren });
      }
    } else {
      if (node.name.toLowerCase().includes(lower) || node.path.toLowerCase().includes(lower)) {
        result.push(node);
      }
    }
  }
  return result;
}

interface FileTreeProps {
  files: FlatFile[];
  selectedPath?: string;
  selectedPaths?: Set<string>;
  onSelect?: (path: string) => void;
  onToggle?: (path: string) => void;
  mode?: 'view' | 'select';
  searchable?: boolean;
  className?: string;
}

export default function FileTree({
  files,
  selectedPath,
  selectedPaths,
  onSelect,
  onToggle,
  mode = 'view',
  searchable = true,
  className = '',
}: FileTreeProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');

  const tree = useMemo(() => {
    const built = buildTree(files);
    return filterTree(built, search);
  }, [files, search]);

  // 搜索时自动展开所有目录
  const effectiveExpanded = useMemo(() => {
    if (search) {
      // 搜索时展开所有含匹配项的目录
      const allDirs = new Set<string>();
      const collectDirs = (nodes: TreeNode[]) => {
        for (const n of nodes) {
          if (n.isDir) {
            allDirs.add(n.path);
            collectDirs(n.children || []);
          }
        }
      };
      collectDirs(tree);
      return allDirs;
    }
    return expanded;
  }, [search, tree, expanded]);

  const toggleDir = useCallback((path: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const formatSize = (bytes?: number) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / 1048576).toFixed(1)}MB`;
  };

  const renderNode = (node: TreeNode): React.ReactNode => {
    if (node.isDir) {
      const isExpanded = effectiveExpanded.has(node.path);
      return (
        <div key={node.path}>
          <button
            onClick={() => toggleDir(node.path)}
            className="w-full text-left flex items-center gap-1 px-1 py-0.5 hover:bg-surface-3 rounded text-fs-body text-gray-400"
            style={{ paddingLeft: `${node.level * 12 + 4}px` }}
          >
            <span className="text-fs-aux">{isExpanded ? '▼' : '▶'}</span>
            <span>{isExpanded ? '📂' : '📁'}</span>
            <span className="truncate">{node.name}</span>
          </button>
          {isExpanded && node.children && node.children.map(renderNode)}
        </div>
      );
    }

    const isSelected = selectedPath === node.path;
    const isChecked = selectedPaths?.has(node.path) || false;
    const handleClick = () => {
      if (mode === 'select' && onToggle) {
        onToggle(node.path);
      } else if (onSelect) {
        onSelect(node.path);
      }
    };

    return (
      <div
        key={node.path}
        onClick={handleClick}
        className={`flex items-center gap-1 px-1 py-0.5 rounded text-fs-body cursor-pointer transition-colors ${
          mode === 'select'
            ? isChecked
              ? 'bg-info/10 text-info'
              : 'text-gray-400 hover:bg-surface-3'
            : isSelected
              ? 'bg-info/10 text-info'
              : 'text-gray-400 hover:bg-surface-3'
        }`}
        style={{ paddingLeft: `${node.level * 12 + 20}px` }}
      >
        {mode === 'select' && (
          <input
            type="checkbox"
            checked={isChecked}
            onChange={() => onToggle?.(node.path)}
            onClick={(e) => e.stopPropagation()}
            className="w-3 h-3 accent-info flex-shrink-0"
          />
        )}
        <span className="flex-shrink-0">{getFileIcon(node.name)}</span>
        {node.is_delta && <span className="text-warn text-fs-aux flex-shrink-0">Δ</span>}
        <span className="truncate flex-1">{node.name}</span>
        {node.size !== undefined && (
          <span className="text-gray-600 text-fs-aux flex-shrink-0">{formatSize(node.size)}</span>
        )}
      </div>
    );
  };

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {searchable && (
        <div className="p-1.5 border-b border-border">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索文件名..."
            className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-300 placeholder-gray-600 focus:border-info outline-none"
          />
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-1">
        {tree.length === 0 ? (
          <div className="text-center text-gray-600 text-fs-body py-4">
            {search ? '无匹配文件' : '无文件'}
          </div>
        ) : (
          tree.map(renderNode)
        )}
      </div>
    </div>
  );
}
