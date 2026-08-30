// 网状全景组件（飞书知识图谱一期 T-915）：全量节点力导向网状视图。
// 数据：GET /api/graph/panorama?level=L0&lens=network；布局：elk force（零新增依赖）。
// >500 节点后端护栏 truncated → 只回模块聚合，前端横幅提示。

import { useEffect, useMemo, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { graphApi, type NetworkViewResp } from '../api';
import { layoutNetworkByELK } from '../utils/elkLayout';

const TYPE_COLOR: Record<string, string> = {
  fr: '#38bdf8', ac: '#22d3ee', scenario: '#34d399', decision: '#fbbf24',
  interview: '#a78bfa', delta: '#f472b6', plan: '#2dd4bf', run: '#9ca3af',
  spq: '#f87171', external_ref: '#94a3b8', module: '#818cf8', feature: '#c084fc',
  feishu_doc: '#60a5fa', feishu_minutes: '#c4b5fd', topic: '#fb923c',
};

const LEGEND: [string, string][] = [
  ['fr', 'FR'], ['scenario', '场景'], ['decision', '决策'], ['interview', '面试'],
  ['feishu_doc', '飞书文档'], ['feishu_minutes', '妙记'], ['topic', '话题'],
  ['delta', 'Delta'], ['plan', '计划'], ['run', '执行'], ['spq', 'SPQ'],
];

export default function NetworkGraph() {
  const [data, setData] = useState<NetworkViewResp | null>(null);
  const [positions, setPositions] = useState<Map<string, { x: number; y: number }> | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    graphApi.network()
      .then(async (resp) => {
        setData(resp);
        const edges: Edge[] = resp.edges.map((e, i) => ({
          id: `e${i}`, source: e.src, target: e.dst,
        }));
        const pos = await layoutNetworkByELK(
          resp.nodes.map(n => ({ id: n.id })), edges);
        setPositions(pos);
      })
      .catch(e => setError(String(e?.message || e)));
  }, []);

  const { nodes, edges } = useMemo(() => {
    if (!data || !positions) return { nodes: [] as Node[], edges: [] as Edge[] };
    const rfNodes: Node[] = data.nodes.map(n => {
      const color = TYPE_COLOR[n.node_type] || '#6b7280';
      return {
        id: n.id,
        position: positions.get(n.id) || { x: 0, y: 0 },
        data: { label: n.title || n.id },
        style: {
          background: '#1e2230', border: `1.5px solid ${color}`, color: '#e5e7eb',
          borderRadius: 8, fontSize: 10, padding: '4px 7px', maxWidth: 170,
        },
      } as Node;
    });
    const rfEdges: Edge[] = data.edges.map((e, i) => ({
      id: `e${i}`,
      source: e.src,
      target: e.dst,
      style: {
        stroke: e.edge_type === 'mentions' ? '#f59e0b' : '#3f4756',
        strokeDasharray: e.edge_type === 'mentions' ? '5 4' : undefined,
        strokeWidth: e.edge_type === 'mentions' ? 1.4 : 1,
      },
    }));
    return { nodes: rfNodes, edges: rfEdges };
  }, [data, positions]);

  const selNode = data?.nodes.find(n => n.id === selected);

  if (error) {
    return <div className="text-fs-body text-red-400 bg-red-900/20 px-3 py-2 rounded">网状视图加载失败：{error}</div>;
  }
  if (!data || !positions) {
    return <div className="text-fs-body text-gray-500 px-3 py-6 text-center">力导向布局计算中…</div>;
  }

  return (
    <div className="rounded-lg bg-surface-2 border border-border overflow-hidden">
      {data.truncated && (
        <div className="px-3 py-2 text-fs-body bg-yellow-900/30 text-yellow-300 border-b border-border">
          ⚠ 节点总数 {data.total_nodes} 超过 500 护栏——已聚合为模块级视图（展开请用 L1/L2 下钻）
        </div>
      )}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border text-fs-aux text-gray-500 flex-wrap">
        <span>图例：</span>
        {LEGEND.map(([t, label]) => (
          <span key={t} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full" style={{ background: TYPE_COLOR[t] }} />
            {label}
          </span>
        ))}
        <span className="ml-auto">橙色虚线 = mentions（人工复核确认的关联）</span>
      </div>
      <div style={{ height: 560 }}>
        <ReactFlow
          nodes={nodes} edges={edges} fitView
          nodesConnectable={false} elementsSelectable
          onNodeClick={(_, n) => setSelected(n.id === selected ? null : n.id)}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={20} size={1} color="#2a2f3f" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable
            nodeColor={n => TYPE_COLOR[(n.data as any)?.node_type] || '#4b5563'}
            style={{ background: '#161928' }} />
        </ReactFlow>
      </div>
      {selNode && (
        <div className="border-t border-border px-3 py-2 text-fs-body flex items-start gap-3">
          <span className="font-semibold text-gray-200">{selNode.title || selNode.id}</span>
          <span style={{ color: TYPE_COLOR[selNode.node_type] || '#9ca3af' }}>{selNode.node_type}</span>
          <code className="text-gray-500">{selNode.id}</code>
          {!!selNode.attrs?.summary && (
            <span className="text-gray-400 flex-1">{String(selNode.attrs.summary)}</span>
          )}
          <button className="text-gray-500 hover:text-gray-300 ml-auto" onClick={() => setSelected(null)}>✕</button>
        </div>
      )}
    </div>
  );
}
