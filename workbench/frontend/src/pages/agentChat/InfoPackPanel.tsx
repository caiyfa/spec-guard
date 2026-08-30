import { useCallback, useEffect, useRef, useState } from 'react';
import { scenarioApi } from '../../api';
import type { InfoPackFreshness, ScenarioMeta } from '../../api';
import { FreshBadge } from './RefPanel';

// ── 基础信息包面板（K-013：条目化 + 新鲜度徽标 + 变更发现补入） ──
export function InfoPackPanel({ meta, onUpdate, onError, onViewFile, defaultOpen = false }: {
  meta: ScenarioMeta;
  onUpdate: (m: ScenarioMeta) => void;
  onError: (msg: string) => void;
  onViewFile: (path: string) => void;
  defaultOpen?: boolean;  // K-032：页签内直接展开
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [freshness, setFreshness] = useState<InfoPackFreshness | null>(null);
  const [uploading, setUploading] = useState(false);  // K-033
  const fileInputRef = useRef<HTMLInputElement>(null);  // K-033

  // K-033：上传材料到信息包（xlsx/docx/pdf 后端自动转文本可读）
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';  // 允许重复选同一文件
    if (!file) return;
    setUploading(true);
    try {
      const updated = await scenarioApi.uploadInfoPackFile(meta.id, file);
      onUpdate(updated);
    } catch (err) {
      onError(`上传失败: ${err instanceof Error ? err.message : err}`);
    } finally {
      setUploading(false);
    }
  };

  const loadFreshness = useCallback(() => {
    scenarioApi.infoPackFreshness(meta.id).then(setFreshness).catch(() => setFreshness(null));
  }, [meta.id]);
  useEffect(() => { loadFreshness(); }, [loadFreshness, meta.updated_at]);

  const statusOf = (p: string) => freshness?.files.find(f => f.path === p)?.status || '';
  const outside = freshness?.outside_changes || [];

  const handleAddOutside = async (path: string) => {
    try {
      const updated = await scenarioApi.updateInfoPack(
        meta.id, [...meta.info_pack.map(e => e.path), path]);
      onUpdate(updated);
    } catch { onError('补入文件失败'); }
  };

  return (
    <div className="px-3 py-2 border-b border-border">
      <div className="flex items-center justify-between">
        <button onClick={() => setOpen(v => !v)}
          className="flex-1 flex items-center justify-between text-fs-body font-medium text-gray-300 hover:text-gray-100">
          <span>
            📦 基础信息包（{meta.info_pack.length}）
            {freshness && freshness.stale_count > 0 && (
              <span className="text-yellow-400 text-fs-micro ml-1">⚠️ {freshness.stale_count} 项已变更</span>
            )}
          </span>
          <span className="text-fs-micro text-gray-600">{open ? '▲' : '▼'}</span>
        </button>
        {/* K-033：直接上传材料到信息包（不再只能 git 拉取） */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="ml-1 text-fs-aux px-1.5 py-0.5 rounded border border-border text-gray-500 hover:text-info hover:border-info/40 disabled:opacity-40"
          title="上传材料到信息包（xlsx/docx/pdf/md/csv 等，≤20MB）"
        >
          {uploading ? '上传中…' : '⬆ 上传'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={handleUpload}
        />
      </div>
      {open && (
        <div className="mt-1.5">
          <div className="max-h-40 overflow-y-auto">
            {meta.info_pack.map(entry => (
              <div key={entry.path} className="flex items-center gap-1 group">
                <FreshBadge status={statusOf(entry.path)} />
                <span className="text-fs-aux">📄</span>
                <span onClick={() => onViewFile(entry.path)}
                  className="text-fs-aux font-mono text-gray-500 flex-1 truncate cursor-pointer hover:text-info"
                  title={`${entry.path}\nsha: ${entry.sha || '-'}\n添加: ${entry.added_at || '-'}`}>
                  {entry.path}
                </span>
                <button onClick={async () => {
                  const newFiles = meta.info_pack.map(e => e.path).filter(f => f !== entry.path);
                  try {
                    const updated = await scenarioApi.updateInfoPack(meta.id, newFiles);
                    onUpdate(updated);
                  } catch { onError('移除文件失败'); }
                }} className="text-fail text-fs-aux opacity-0 group-hover:opacity-100">✕</button>
              </div>
            ))}
          </div>
          {/* K-013: git 变更发现——信息包外的相关变更/新增文件，一键补入 */}
          {outside.length > 0 && (
            <div className="mt-2 pt-2 border-t border-border/50">
              <div className="text-fs-micro text-yellow-400/80 mb-1">
                ⚠️ {outside.length} 个相关文件已变更/新增（{freshness?.base_commit}→{freshness?.head_commit}），未在信息包中：
              </div>
              <div className="max-h-24 overflow-y-auto space-y-0.5">
                {outside.map(p => (
                  <div key={p} className="flex items-center gap-1">
                    <span onClick={() => onViewFile(p)}
                      className="text-fs-aux font-mono text-gray-500 flex-1 truncate cursor-pointer hover:text-info">{p}</span>
                    <button onClick={() => handleAddOutside(p)}
                      className="text-fs-micro text-info hover:underline flex-shrink-0">+ 补入</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
