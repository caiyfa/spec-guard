import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { Background, ReactFlow, type Edge, type Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import ScenarioNode from '../../components/ScenarioNode';
import { layoutDagByELK } from '../../utils/elkLayout';
import { useJsTokens } from '../../theme';
import { draftsApi, scenariosApi } from '../../api';
import type { DagData, DraftItem } from '../../api';

// ── 会话依赖图面板（K-xxx：Agent 对话内直接看依赖——草稿 + 直接上下游闭包的图形化视图） ──
const nodeTypes = { scenario: ScenarioNode };

/** 边状态配色（与 DagEditor 一致：match 低调灰 / minor 蓝 / major 琥珀 / orphan 红虚线） */
const EDGE_STATUS_STYLE: Record<string, { stroke: string; dash?: string }> = {
  match: { stroke: '' },
  minor_drift: { stroke: '#58a6ff' },
  major_drift: { stroke: '#d29922' },
  orphan: { stroke: '#f85149', dash: '6 4' },
};

export function DepGraphPanel({ draftFiles, onError }: {
  draftFiles: string[];
  onError: (msg: string) => void;
}) {
  const navigate = useNavigate();
  const tokens = useJsTokens();
  const [dag, setDag] = useState<DagData | null>(null);
  const [draftMeta, setDraftMeta] = useState<Record<string, DraftItem>>({});
  const [draftNodes, setDraftNodes] = useState<{ id: string; data: Record<string, unknown> }[]>([]);
  const [draftEdges, setDraftEdges] = useState<{ source: string; target: string; label?: string; status?: string }[]>([]);
  const [cycles, setCycles] = useState<string[][]>([]);
  const [loading, setLoading] = useState(true);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [d, dl, drift] = await Promise.all([
          scenariosApi.dag(), draftsApi.list(), scenariosApi.drift(),
        ]);
        if (!alive) return;
        setDag(d);
        const m: Record<string, DraftItem> = {};
        for (const x of dl.drafts || []) m[x.filename] = x;
        setDraftMeta(m);
        setCycles(drift.cycles || []);
        // 会话相关草稿 → 独立节点 + 解析 depends_on 构建草稿边（草稿未入库，不在场景库 DAG 中）
        const nodes: { id: string; data: Record<string, unknown> }[] = [];
        const edges: { source: string; target: string; label?: string; status?: string }[] = [];
        for (const f of draftFiles) {
          const meta = m[f];
          const sid = meta?.scenario_id || f.replace(/\.ya?ml$/i, '');
          nodes.push({ id: sid, data: { label: sid, title: meta?.title || '', isDraft: true } });
          try {
            const r = await draftsApi.read(f);
            for (const dep of r.depends_on || []) {
              edges.push({ source: dep, target: sid, label: '', status: 'match' });
            }
          } catch { /* 草稿已入库/废弃读不到时跳过，节点仍保留 */ }
        }
        if (alive) { setDraftNodes(nodes); setDraftEdges(edges); }
      } catch (e: any) {
        if (alive) onError(`依赖图加载失败: ${e.message || ''}`);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftFiles.join('|')]);

  // 会话相关场景 = 草稿 scenario_id ∪ 直接依赖邻居（保持边可见）
  const scope = useMemo(() => {
    if (!dag && draftNodes.length === 0) return { seed: new Set<string>(), nodes: [] as { id: string; data: Record<string, unknown> }[], edges: [] as { source: string; target: string; label?: string; status?: string }[] };
    const seed = new Set<string>();
    draftFiles.forEach(f => {
      const meta = draftMeta[f];
      if (meta?.scenario_id) seed.add(meta.scenario_id);
      else seed.add(f.replace(/\.ya?ml$/i, ''));  // 文件名兜底 = 场景 ID
    });
    const keep = new Set(seed);
    const allEdges = [...(dag?.edges || []), ...draftEdges];
    allEdges.forEach(e => {
      if (seed.has(e.source) || seed.has(e.target)) { keep.add(e.source); keep.add(e.target); }
    });
    const dagNodes = dag?.nodes || [];
    const dagIds = new Set(dagNodes.map(n => n.id));
    // 草稿已入库时 DAG 已有同 ID 节点（含完整 label/title/category），不重复追加
    const allNodes = [...dagNodes, ...draftNodes.filter(n => !dagIds.has(n.id))];
    return {
      seed,
      nodes: allNodes.filter(n => keep.has(n.id)),
      edges: allEdges.filter(e => keep.has(e.source) && keep.has(e.target)),
    };
  }, [dag, draftMeta, draftFiles, draftNodes, draftEdges]);

  // ELK 布局 → React Flow 节点/边（会话闭包通常小图，懒加载 elkjs 成本可接受）
  useEffect(() => {
    if (scope.nodes.length === 0) { setRfNodes([]); setRfEdges([]); return; }
    let alive = true;
    (async () => {
      try {
        const pos = await layoutDagByELK(scope.nodes.map(n => ({ id: n.id })), scope.edges as Edge[]);
        if (!alive) return;
        setRfNodes(scope.nodes.map(n => ({
          id: n.id,
          type: 'scenario',
          position: { x: pos.get(n.id)?.x ?? 0, y: pos.get(n.id)?.y ?? 0 },
          data: n.data,
        })));
        setRfEdges(scope.edges.map((e, i) => {
          const st = EDGE_STATUS_STYLE[e.status || 'match'] || EDGE_STATUS_STYLE.match;
          return {
            id: `e${i}`,
            source: e.source,
            target: e.target,
            label: e.label || undefined,
            style: {
              stroke: st.stroke || tokens.edgeStroke,
              strokeDasharray: st.dash,
            },
          };
        }));
      } catch { /* ELK 布局失败：保持空画布，统计行仍可见 */ }
    })();
    return () => { alive = false; };
  }, [scope, tokens]);

  const cycleSets = useMemo(() => cycles.map(c => new Set(c)), [cycles]);

  return (
    <div className="px-2 py-2 space-y-2">
      <div className="px-1 text-xs font-medium text-gray-300">🕸 依赖图（会话相关闭包）</div>
      {loading ? (
        <div className="text-[11px] text-gray-600 text-center py-8">加载中…</div>
      ) : (!dag && draftNodes.length === 0) || scope.nodes.length === 0 ? (
        <div className="text-[11px] text-gray-600 text-center py-8 leading-relaxed">
          会话还没有草稿 / 场景。<br />Agent 写完草稿后，这里自动显示<br />它与其他测试的依赖关系
        </div>
      ) : (
        <>
          <div className="px-1 text-[10px] text-gray-600">
            {scope.nodes.length} 个场景 · {scope.edges.length} 条依赖边
            {cycleSets.length > 0 && <span className="text-fail"> · ⛔ {cycleSets.length} 条环</span>}
          </div>
          {/* 图形化画布（只读查看，不跳转 DAG 编排） */}
          <div className="h-72 border border-border rounded-lg overflow-hidden" style={{ background: tokens.rfBackground }}>
            {rfNodes.length > 0 ? (
              <ReactFlow
                nodes={rfNodes}
                edges={rfEdges}
                nodeTypes={nodeTypes}
                nodesDraggable={false}
                nodesConnectable={false}
                fitView
                minZoom={0.2}
                maxZoom={1.5}
                proOptions={{ hideAttribution: true }}
              >
                <Background color={tokens.rfBackground} gap={20} />
              </ReactFlow>
            ) : (
              <div className="text-[11px] text-gray-600 text-center py-8">布局中…</div>
            )}
          </div>
          <div className="px-1 pt-1">
            <button onClick={() => navigate('/dag')}
              className="w-full px-2 py-1.5 rounded border border-border text-[11px] text-info hover:border-info/40">
              🕸 打开 DAG 编排（选择子集）
            </button>
          </div>
        </>
      )}
    </div>
  );
}
