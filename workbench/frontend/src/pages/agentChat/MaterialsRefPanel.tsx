import { useCallback, useEffect, useState } from 'react';
import { specflowApi } from '../../api';
import type { MaterialItem } from '../../api';
import type { ChatReference } from './types';

// T-933：材料状态徽标配色（与独立材料管理页语义一致）
const MAT_STATUS_COLOR: Record<string, string> = {
  uploaded: 'text-gray-500', parsing: 'text-amber-400', parsed: 'text-blue-400',
  indexed: 'text-green-500', packed: 'text-info', failed: 'text-red-400',
};

// T-933：材料页签——本会话绑定面试的材料清单（标题/解析状态/摘要），
// 会话消息里引用过的材料加 📌 标记；未绑定面试诚实空态引导（不报错）。
export function MaterialsRefPanel({ sessionId, references, onError }: {
  sessionId: string; references: ChatReference[]; onError: (msg: string) => void;
}) {
  const [items, setItems] = useState<MaterialItem[] | null>(null);
  const [ivTitle, setIvTitle] = useState('');
  const [loading, setLoading] = useState(false);
  const [heads, setHeads] = useState<Record<string, string>>({});
  const [loadErr, setLoadErr] = useState('');

  const load = useCallback(async () => {
    if (!sessionId) { setItems(null); setLoadErr(''); return; }
    setLoading(true); setLoadErr('');
    try {
      const dock = await specflowApi.gateDock({ session_id: sessionId });
      const iv = dock.interview;
      if (!iv) { setItems(null); setIvTitle(''); return; }   // 未绑定面试 → 空态引导
      setIvTitle(iv.title || iv.iv_id);
      const r = await specflowApi.listMaterials(iv.iv_id);
      setItems(r.materials || []);
      // 摘要：逐材料 preview 头部 120 字（前 20 条；单条失败不阻断）
      const next: Record<string, string> = {};
      await Promise.all((r.materials || []).slice(0, 20).map(async m => {
        try {
          const p = await specflowApi.previewMaterial(m.mid);
          const t = (p.text || '').replace(/\s+/g, ' ').trim().slice(0, 120);
          if (t) next[m.mid] = t;
        } catch { /* 单条摘要失败静默 */ }
      }));
      setHeads(next);
    } catch (e: any) {
      setLoadErr(e.message || '加载失败');
      onError(`材料列表加载失败: ${e.message}`);
    } finally { setLoading(false); }
  }, [sessionId, onError]);

  useEffect(() => { void load(); }, [load]);

  const refMids = new Set(references.filter(r => r.type === 'material').map(r => r.path));

  return (
    <div className="p-2 space-y-1">
      <div className="flex items-center gap-2 text-[11px] text-gray-500 pb-1 border-b border-border">
        <span>📎 会话材料{ivTitle ? `（${ivTitle}）` : ''}</span>
        <button className="ml-auto text-gray-500 hover:text-info" onClick={() => void load()}
          title="刷新材料列表与状态">⟳ 刷新</button>
      </div>
      {loading && <div className="text-xs text-gray-500 text-center py-4">材料加载中…</div>}
      {!loading && loadErr && (
        <div className="text-xs text-red-400 text-center py-4">材料列表加载失败：{loadErr}</div>
      )}
      {!loading && !loadErr && items === null && (
        <div className="text-xs text-gray-600 text-center py-4">
          当前会话未绑定需求面试——材料随面试归档；
          <br />在输入区点 🧾 上传前，先在对话中开标（如「开启需求面试」）
        </div>
      )}
      {!loading && !loadErr && items !== null && items.length === 0 && (
        <div className="text-xs text-gray-600 text-center py-4">
          面试尚未上传材料——点输入区 🧾 选择文件上传，上传成功自动挂入引用
        </div>
      )}
      {!loading && (items || []).map(m => (
        <div key={m.mid} className="px-2 py-1.5 rounded bg-surface-3/60 border border-border/50">
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-gray-200 truncate" title={m.filename}>{m.filename}</span>
            {refMids.has(m.mid) && (
              <span className="text-fs-aux text-info shrink-0" title="已在对话消息中引用">📌</span>
            )}
            <span className={`ml-auto shrink-0 text-fs-aux ${MAT_STATUS_COLOR[m.status] || 'text-gray-500'}`}>
              {m.status}{m.fmt ? ` · ${m.fmt}` : ''}
            </span>
          </div>
          {heads[m.mid] && (
            <div className="text-fs-aux text-gray-500 mt-0.5 line-clamp-2">{heads[m.mid]}</div>
          )}
          {m.parse_error && (
            <div className="text-fs-aux text-red-400/80 mt-0.5 truncate" title={m.parse_error}>
              {m.parse_error}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
