// 全景图谱页（T-071，M11）：L0 模块星团 → L1 功能点 → L2 FR 邻域
// 三镜头（🧭 面试选题 / 🧊 测试债 / 🗺 系统概览）+ backlink 面板 + 源头文件定位（v1.19）

import { useCallback, useEffect, useState } from 'react';
import {
  graphApi,
  type GraphL0,
  type GraphL1Item,
  type GraphL2,
  type GraphBacklink,
  type GraphStatus,
  type GraphSourceFile,
  type GraphSnapshot,
  type GraphDiff,
} from '../api';
import NetworkGraph from '../components/NetworkGraph';
import LineageStory from './LineageStory';

type Lens = 'topic' | 'debt' | 'map' | 'network' | 'lineage';

const LENSES: { key: Lens; label: string; hint: string }[] = [
  { key: 'topic', label: '🧭 面试选题', hint: 'delta 活跃功能点优先进入下轮面试议题' },
  { key: 'debt', label: '🧊 测试债地图', hint: '健康分 <80 标 ❄，无场景新功能点虚线描边' },
  { key: 'map', label: '🗺 系统概览', hint: '模块耦合强度，服务新人 onboarding' },
  { key: 'network', label: '🕸 网状全景', hint: '全量节点力导向网状（含飞书材料/话题；橙色虚线=mentions 人工复核关联），>500 节点自动聚合' },
  { key: 'lineage', label: '🔗 血缘链', hint: '血缘链审计追溯（T-996 并入图谱镜头，原 /lineage 页）' },
];

const LENS_COLOR: Record<Lens, string> = {
  topic: 'border-purple-500/60',
  debt: 'border-cyan-500/60',
  map: 'border-gray-500/60',
  network: 'border-amber-500/60',
  lineage: 'border-blue-500/60',
};

// M-03：展示文案长度守卫
const MAX_LEN = 100;
const maxLen = (s: string, n = MAX_LEN) => s.length <= n ? s : s.slice(0, n - 1) + '…';

export default function GraphPanorama() {
  const [error, setError] = useState('');
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [lens, setLens] = useState<Lens>('map');
  const [l0, setL0] = useState<GraphL0 | null>(null);
  const [module, setModule] = useState('');
  const [l1, setL1] = useState<Record<string, GraphL1Item> | null>(null);
  const [feature, setFeature] = useState('');
  const [l2, setL2] = useState<GraphL2 | null>(null);
  const [backlink, setBacklink] = useState<{ node: string; data: GraphBacklink } | null>(null);
  const [source, setSource] = useState<GraphSourceFile | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  // ── T-072：里程碑快照 + 演化 diff ──
  const [snapshots, setSnapshots] = useState<GraphSnapshot[]>([]);
  const [snapLabel, setSnapLabel] = useState('');
  const [diffResult, setDiffResult] = useState<GraphDiff | null>(null);
  const [diffFrom, setDiffFrom] = useState('');

  // ── 索引状态（stale 自动提示）──
  const loadStatus = useCallback(() => {
    graphApi.status().then(setStatus).catch(e => setError(String(e)));
  }, []);
  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleRebuild = async () => {
    setError('');
    try {
      await graphApi.rebuild();
      await loadStatus();
      if (module) {
        setL1(await graphApi.panoramaL1(module, lens));
      } else {
        setL0(await graphApi.panoramaL0(lens));
      }
    } catch (e) {
      setError(String(e));
    }
  };

  // ── L0 加载（network 镜头走 NetworkGraph 自取数，不经 panoramaL0）──
  useEffect(() => {
    if (lens === 'network' || lens === 'lineage') return;
    graphApi.panoramaL0(lens).then(setL0).catch(e => setError(String(e)));
  }, [lens]);

  // ── 下钻 L1 ──
  const openModule = async (mod: string) => {
    setError('');
    setModule(mod);
    setFeature('');
    setL2(null);
    setBacklink(null);
    try {
      setL1(await graphApi.panoramaL1(mod, lens));
    } catch (e) {
      setError(String(e));
    }
  };

  // ── 下钻 L2 ──
  const openFeature = async (feat: string) => {
    setError('');
    setFeature(feat);
    setBacklink(null);
    try {
      setL2(await graphApi.panoramaL2(module, feat));
    } catch (e) {
      setError(String(e));
    }
  };

  const backToL0 = () => {
    setModule('');
    setFeature('');
    setL1(null);
    setL2(null);
    setBacklink(null);
  };
  const backToL1 = () => {
    setFeature('');
    setL2(null);
    setBacklink(null);
  };

  // ── backlink ──
  const queryBacklink = async (nodeId: string) => {
    setError('');
    try {
      const r = await graphApi.backlink(nodeId);
      setBacklink({ node: nodeId, data: r.backlink });
    } catch (e) {
      setError(String(e));
    }
  };

  // ── 源头文件定位（v1.19）──
  const openSource = async (file: string, line = 0) => {
    setError('');
    setSourceLoading(true);
    try {
      setSource(await graphApi.source(file, line));
    } catch (e) {
      setError(String(e));
    } finally {
      setSourceLoading(false);
    }
  };

  // ── 里程碑快照（T-072）──
  const loadSnapshots = useCallback(() => {
    graphApi.listSnapshots().then(r => {
      setSnapshots(r.snapshots);
      if (!diffFrom && r.snapshots.length > 0) setDiffFrom(r.snapshots[0].snapshot_id);
    }).catch(e => setError(String(e)));
  }, [diffFrom]);
  useEffect(() => {
    loadSnapshots();
  }, [loadSnapshots]);

  const handleCreateSnapshot = async () => {
    setError('');
    try {
      await graphApi.createSnapshot(snapLabel, 'manual');
      setSnapLabel('');
      setDiffResult(null);
      await loadSnapshots();
    } catch (e) {
      setError(String(e));
    }
  };

  const handleDiff = async () => {
    if (!diffFrom) return;
    setError('');
    try {
      setDiffResult(await graphApi.diff(diffFrom, 'current'));
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="space-y-4">
      {/* 顶栏：状态 + 三镜头 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <h2 className="text-base font-bold">🕸 全景图谱</h2>
          {status && (
            status.stale ? (
              <span className="flex items-center gap-2 text-xs bg-yellow-900/40 text-yellow-300 px-2 py-1 rounded">
                ⚠ 源数据已变更，索引过期
                <button onClick={handleRebuild} className="underline hover:text-yellow-100">重建</button>
              </span>
            ) : (
              <span className="text-xs bg-green-900/40 text-green-300 px-2 py-1 rounded">
                ✓ 索引新鲜{status.built_at ? ` · ${status.built_at.slice(0, 16).replace('T', ' ')}` : ''}
              </span>
            )
          )}
        </div>
        <div className="flex items-center gap-2">
          {LENSES.map(l => (
            <button
              key={l.key}
              onClick={() => setLens(l.key)}
              title={l.hint}
              className={`px-3 py-1.5 rounded text-xs border transition-colors ${
                lens === l.key
                  ? `bg-info/10 text-info font-medium ${LENS_COLOR[l.key]}`
                  : 'text-gray-400 border-border hover:text-gray-200'
              }`}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>
      {LENSES.find(l => l.key === lens) && (
        <p className="text-[11px] text-gray-500 -mt-2">{LENSES.find(l => l.key === lens)!.hint}</p>
      )}

      {/* ── 里程碑时间轴 + 演化 diff（T-072）── */}
      <div className="rounded-lg bg-surface-2 border border-border p-3 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <p className="text-xs text-gray-300 font-medium">📸 里程碑快照</p>
          <div className="flex items-center gap-2">
            <input
              value={snapLabel}
              onChange={e => setSnapLabel(e.target.value)}
              placeholder="标签（如 es-acceleration 归档）"
              className="bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-300 w-56"
            />
            <button
              onClick={handleCreateSnapshot}
              className="text-xs bg-info/10 text-info px-2.5 py-1 rounded hover:bg-info/20"
            >
              打快照
            </button>
          </div>
        </div>
        {snapshots.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            {snapshots.map(s => (
              <span key={s.snapshot_id} className="text-[10px] bg-surface-3 text-gray-400 px-2 py-1 rounded">
                {s.label} · {s.created_at.slice(0, 16).replace('T', ' ')} · {s.nodes} 节点 · {s.source_fingerprint.slice(0, 8)}…
              </span>
            ))}
          </div>
        )}
        <div className="flex items-center gap-2">
          <select
            value={diffFrom}
            onChange={e => { setDiffFrom(e.target.value); setDiffResult(null); }}
            className="bg-surface-3 border border-border rounded px-2 py-1 text-xs text-gray-300"
          >
            {snapshots.map(s => (
              <option key={s.snapshot_id} value={s.snapshot_id}>{s.label}</option>
            ))}
          </select>
          <span className="text-xs text-gray-500">→ 当前</span>
          <button onClick={handleDiff} className="text-xs bg-info/10 text-info px-2.5 py-1 rounded hover:bg-info/20">
            ⇄ 演化 diff
          </button>
          {diffResult && (
            <span className="text-[11px] text-gray-400">
              📸 {diffResult.from.slice(0, 22)} → 当前：
              <b className="text-green-400">+{diffResult.added}</b> 新增 ·
              <b className="text-red-400">-{diffResult.removed}</b> 移除 ·
              <b className="text-yellow-400">~{diffResult.modified}</b> 修改
              <span className="text-gray-600 ml-1">｜指纹 {diffResult.fingerprint_from.slice(0, 8)} → {diffResult.fingerprint_to.slice(0, 8)}</span>
            </span>
          )}
        </div>
        {diffResult && Object.keys(diffResult.per_module).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(diffResult.per_module).map(([mod, c]) => (
              <span key={mod} className="text-[10px] bg-surface-3 px-2 py-1 rounded text-gray-400">
                {mod}：+{c.added} / -{c.removed} / ~{c.modified}
              </span>
            ))}
          </div>
        )}
      </div>

      {error && <div className="text-xs text-red-400 bg-red-900/20 px-3 py-2 rounded">{error}</div>}

      {/* 面包屑 */}
      <div className="flex items-center gap-1.5 text-xs text-gray-500">
        <button onClick={backToL0} className="hover:text-info">系统星座图</button>
        {module && (<>
          <span>/</span>
          <button onClick={backToL1} className="hover:text-info">{module}</button>
        </>)}
        {feature && (<>
          <span>/</span>
          <span className="text-gray-300">{feature}</span>
        </>)}
      </div>

      {/* ── 网状全景（T-915 第 4 镜头：力导向全量节点网状）── */}
      {lens === 'network' && <NetworkGraph />}

      {/* ── 血缘链（T-996 第 5 镜头：原 /lineage 页并入）── */}
      {lens === 'lineage' && <LineageStory />}

      {/* ── L0 模块星团 ── */}
      {lens !== 'network' && lens !== 'lineage' && !module && l0 && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {Object.entries(l0.l0mods).map(([mod, m]) => (
              <button
                key={mod}
                onClick={() => openModule(mod)}
                className="p-4 rounded-lg bg-surface-2 border border-border hover:border-info/50 text-left transition-colors"
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-200">{m.name}</span>
                  <span className="text-[10px] bg-info/10 text-info px-1.5 py-0.5 rounded">FR {m.fr_count}</span>
                </div>
                <div className="mt-2 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                  <div className="h-full bg-info/60 rounded-full" style={{ width: `${Math.min(100, m.fr_count * 8)}%` }} />
                </div>
              </button>
            ))}
          </div>
          {l0.l0edges.length > 0 && (
            <div className="rounded-lg bg-surface-2 border border-border p-3">
              <p className="text-[11px] text-gray-500 mb-2">跨模块耦合（边粗 = 共享 FR / 跨模块依赖强度）</p>
              <div className="flex flex-wrap gap-2">
                {l0.l0edges.map((e, i) => (
                  <span key={i} className="text-[11px] bg-surface-3 px-2 py-1 rounded text-gray-400">
                    {e.a} ↔ {e.b} <b className="text-gray-300">w:{e.w}</b>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── L1 功能点 ── */}
      {module && !feature && l1 && (
        <div className="space-y-2">
          {Object.entries(l1).map(([feat, item]) => {
            const health = item.health;
            const isDebt = health !== null && health < 80;
            const isNew = health === null;
            return (
              <button
                key={feat}
                onClick={() => openFeature(feat)}
                className={`w-full p-3 rounded-lg bg-surface-2 border text-left transition-colors hover:border-info/50 ${
                  isNew ? 'border-dashed border-border' : 'border-border'
                }`}
              >
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-gray-200 font-medium">{feat.split('/').pop()}</span>
                  {isDebt && <span title="测试债：健康分 <80">❄</span>}
                  {isNew && <span className="text-[10px] text-gray-500">新功能点（无健康分）</span>}
                  <span className="ml-auto flex items-center gap-2 text-[11px] text-gray-500">
                    <span className="text-green-400">覆盖 {item.nCov}</span>
                    <span className="text-red-400">缺口 {item.nGap}</span>
                    {health !== null && (
                      <span className={`px-1.5 py-0.5 rounded ${health >= 80 ? 'bg-green-900/40 text-green-300' : 'bg-red-900/40 text-red-300'}`}>
                        健康分 {health}
                      </span>
                    )}
                  </span>
                </div>
                <div className="mt-2 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${health !== null && health >= 80 ? 'bg-green-500/70' : 'bg-red-500/70'}`}
                    style={{ width: `${health ?? 0}%` }}
                  />
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* ── L2 FR 邻域 + backlink ── */}
      {module && feature && l2 && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* FR 列表 */}
          <div className="lg:col-span-1 rounded-lg bg-surface-2 border border-border p-3 space-y-1.5">
            <p className="text-[11px] text-gray-500 mb-2">FR 邻域（{l2.frs.length}）</p>
            {l2.frs.map(fr => (
              <div
                key={fr.id}
                className={`p-2 rounded border text-xs cursor-pointer transition-colors ${
                  fr.cov === 'ok' ? 'border-green-500/30 bg-green-900/10' : 'border-red-500/30 bg-red-900/10'
                } hover:border-info/50`}
                onClick={() => queryBacklink(fr.id)}
              >
                <div className="flex items-center gap-1.5">
                  <span className={`w-2 h-2 rounded-full ${fr.cov === 'ok' ? 'bg-green-400' : 'bg-red-400'}`} />
                  <span className="text-gray-200 font-medium">{fr.id}</span>
                  <span className="text-[10px] text-gray-500">{fr.cov === 'ok' ? '已覆盖' : '缺口'}</span>
                </div>
                <p className="text-gray-400 mt-1 line-clamp-2">{maxLen(fr.t)}</p>
                {fr.source_ref && (
                  <button
                    className="mt-1.5 text-[10px] text-info/80 hover:text-info"
                    onClick={e => { e.stopPropagation(); openSource(fr.source_ref!.file, fr.source_ref!.line_range[0]); }}
                  >
                    📍 {maxLen(fr.source_ref.file, 80)}:{fr.source_ref.line_range[0]}
                  </button>
                )}
              </div>
            ))}
          </div>

          {/* 场景列表 */}
          <div className="lg:col-span-1 rounded-lg bg-surface-2 border border-border p-3 space-y-1.5">
            <p className="text-[11px] text-gray-500 mb-2">覆盖场景（{l2.scenarios.length}）</p>
            {l2.scenarios.map(sc => (
              <div key={sc.id} className="p-2 rounded border border-border bg-surface-3 text-xs">
                <div className="flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-cyan-400" />
                  <span className="text-gray-200 font-medium">{sc.id}</span>
                </div>
                <p className="text-gray-400 mt-1 line-clamp-1">{maxLen(sc.title)}</p>
                <p className="text-[10px] text-gray-600 mt-0.5">covers: {sc.covers.join(', ')}</p>
                {sc.source_ref && (
                  <button
                    className="mt-1 text-[10px] text-info/80 hover:text-info"
                    onClick={() => openSource(sc.source_ref!.file, sc.source_ref!.line_range[0])}
                  >
                    📍 {maxLen(sc.source_ref.file, 80)}:{sc.source_ref.line_range[0]}
                  </button>
                )}
              </div>
            ))}
            {l2.scenarios.length === 0 && (
              <p className="text-[11px] text-gray-600">无场景覆盖此功能点（测试债缺口）</p>
            )}
          </div>

          {/* backlink 面板 */}
          <div className="lg:col-span-1 rounded-lg bg-surface-2 border border-border p-3">
            <p className="text-[11px] text-gray-500 mb-2">
              {backlink ? `反向链接 · ${backlink.node}` : '点 FR 查看反向链接'}
            </p>
            {backlink && (
              <div className="space-y-2 text-xs">
                <div>
                  <p className="text-gray-500 mb-1">✅ 哪些场景覆盖我（covers）</p>
                  <div className="flex flex-wrap gap-1">
                    {backlink.data.covered_by.map(id => (
                      <span key={id} className="bg-cyan-900/40 text-cyan-300 px-1.5 py-0.5 rounded">{id}</span>
                    ))}
                    {backlink.data.covered_by.length === 0 && <span className="text-gray-600">无</span>}
                  </div>
                </div>
                <div>
                  <p className="text-gray-500 mb-1">🔄 哪些 delta 改过我（contains）</p>
                  <div className="flex flex-wrap gap-1">
                    {backlink.data.modified_by.map(id => (
                      <span key={id} className="bg-purple-900/40 text-purple-300 px-1.5 py-0.5 rounded">{id}</span>
                    ))}
                    {backlink.data.modified_by.length === 0 && <span className="text-gray-600">无</span>}
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-gray-500 mb-1">📝 决策引用</p>
                    <p className="text-gray-400">{backlink.data.decided_by.length || '无'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500 mb-1">🔗 外部锚点引用</p>
                    <p className="text-gray-400">{backlink.data.referenced_by.length || '无'}</p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 源头文件查看器 ── */}
      {source && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={() => setSource(null)}>
          <div
            className="w-full max-w-3xl h-[70vh] flex flex-col rounded-lg bg-surface-2 border border-border overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-2 border-b border-border text-xs">
              <span className="text-gray-300 font-medium">📍 {source.path}{source.line > 0 ? `:${source.line}` : ''}</span>
              <button className="text-gray-500 hover:text-gray-200" onClick={() => setSource(null)}>✕ 关闭</button>
            </div>
            <div className="flex-1 overflow-auto text-[11px] leading-5 font-mono">
              {sourceLoading ? (
                <div className="p-4 text-gray-500">读取中…</div>
              ) : (
                source.content.split('\n').map((line, i) => {
                  const n = i + 1;
                  const highlight = source.line > 0 && n === source.line;
                  return (
                    <div key={n} className={`flex ${highlight ? 'bg-yellow-900/40' : ''}`}>
                      <span className="w-12 flex-shrink-0 text-right pr-3 text-gray-600 select-none">{n}</span>
                      <span className={`whitespace-pre ${highlight ? 'text-yellow-100' : 'text-gray-300'}`}>{line}</span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
