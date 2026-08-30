// 焦点子图组件（飞书知识图谱一期 T-915）：以 FR/议题为中心渲染 N 跳邻居。
// 数据：GET /api/graph/focus；布局：BFS 分层环形（root 圆心，逐跳外扩，零新依赖）。

import { useEffect, useMemo, useState } from 'react';
import { ReactFlow, Background, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { graphApi, type FocusGraphResp } from '../api';
import { extractLastAnchor } from '../utils/focusAnchor';

const TYPE_COLOR: Record<string, string> = {
  fr: '#38bdf8', ac: '#22d3ee', scenario: '#34d399', decision: '#fbbf24',
  interview: '#a78bfa', delta: '#f472b6', plan: '#2dd4bf', run: '#9ca3af',
  spq: '#f87171', external_ref: '#94a3b8', module: '#818cf8', feature: '#c084fc',
  feishu_doc: '#60a5fa', feishu_minutes: '#c4b5fd', topic: '#fb923c',
};

interface Props {
  nodeId: string;          // 中心节点（FR-xxx / tp:xxx / fd:xxx）
  depth?: number;          // 默认 2 跳
  height?: number;         // 画布高度
}

export default function FocusGraph({ nodeId, depth = 2, height = 360 }: Props) {
  const [data, setData] = useState<FocusGraphResp | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!nodeId) { setData(null); return; }
    setError('');
    graphApi.focus(nodeId, depth)
      .then(setData)
      .catch(e => { setError(String(e?.message || e)); setData(null); });
  }, [nodeId, depth]);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    // BFS 分层：root 第 0 层，沿边外扩
    const layer: Record<string, number> = { [data.root]: 0 };
    let frontier = [data.root];
    for (let d = 0; d < data.depth; d++) {
      const next: string[] = [];
      for (const cur of frontier) {
        for (const e of data.edges) {
          const other = e.src === cur ? e.dst : e.dst === cur ? e.src : null;
          if (other && layer[other] === undefined) {
            layer[other] = d + 1;
            next.push(other);
          }
        }
      }
      frontier = next;
    }
    const byLayer: Record<number, string[]> = {};
    for (const n of data.nodes) {
      const l = layer[n.id] ?? data.depth;
      (byLayer[l] = byLayer[l] || []).push(n.id);
    }
    const rfNodes: Node[] = data.nodes.map(n => {
      const l = layer[n.id] ?? data.depth;
      const siblings = byLayer[l];
      const idx = siblings.indexOf(n.id);
      const radius = l === 0 ? 0 : 120 + (l - 1) * 110;
      const angle = l === 0 ? 0 : (2 * Math.PI * idx) / siblings.length;
      const color = TYPE_COLOR[n.node_type] || '#6b7280';
      return {
        id: n.id,
        position: { x: 320 + radius * Math.cos(angle), y: 200 + radius * Math.sin(angle) },
        data: {
          label: `${n.id === data.root ? '◎ ' : ''}${n.title || n.id}`,
          sub: n.id,
        },
        style: {
          background: '#1e2230', border: `1.5px solid ${color}`, color: '#e5e7eb',
          borderRadius: 8, fontSize: 11, padding: '6px 8px', maxWidth: 180,
          boxShadow: n.id === data.root ? `0 0 0 2px ${color}55` : undefined,
        },
      } as Node;
    });
    const rfEdges: Edge[] = data.edges.map((e, i) => ({
      id: `e${i}`,
      source: e.src,
      target: e.dst,
      label: e.edge_type,
      labelStyle: { fontSize: 9, fill: '#6b7280' },
      style: {
        stroke: e.edge_type === 'mentions' ? '#f59e0b' : '#4b5563',
        strokeDasharray: e.edge_type === 'mentions' ? '5 4' : undefined,
        strokeWidth: 1.2,
      },
    }));
    return { nodes: rfNodes, edges: rfEdges };
  }, [data]);

  const selNode = data?.nodes.find(n => n.id === selected);

  if (!nodeId) {
    return <div className="text-fs-body text-gray-500 p-2">未选择焦点节点</div>;
  }
  if (error) {
    return <div className="text-fs-body text-red-400 p-2">子图加载失败：{error}</div>;
  }
  if (!data) {
    return <div className="text-fs-body text-gray-500 p-2">加载中…</div>;
  }

  return (
    <div className="relative" style={{ height }}>
      <ReactFlow
        nodes={nodes} edges={edges} fitView
        nodesDraggable={false} nodesConnectable={false} elementsSelectable
        onNodeClick={(_, n) => setSelected(n.id === selected ? null : n.id)}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={18} size={1} color="#2a2f3f" />
      </ReactFlow>
      {selNode && (
        <div className="absolute right-2 top-2 w-60 rounded border border-border bg-surface-2 p-2.5 text-fs-body shadow-lg">
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-gray-200">{selNode.title || selNode.id}</span>
            <button className="text-gray-500 hover:text-gray-300" onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="text-gray-500 mb-1">
            <span style={{ color: TYPE_COLOR[selNode.node_type] || '#9ca3af' }}>{selNode.node_type}</span>
            {' · '}<code>{selNode.id}</code>
          </div>
          {!!selNode.attrs?.summary && (
            <div className="text-gray-400 mb-1">{String(selNode.attrs.summary)}</div>
          )}
          {!!selNode.attrs?.evidence && (
            <div className="text-gray-500 mb-1">依据：{String(selNode.attrs.evidence)}</div>
          )}
          {selNode.source_ref?.file && (
            <div className="text-gray-600 truncate">源头：{selNode.source_ref.file}</div>
          )}
        </div>
      )}
    </div>
  );
}

/** AgentChat 侧栏「◎ 图谱」页签容器：焦点输入 + 深度选择 + FocusGraph 渲染。
 *  T-921：messages 传入时自动检测最近消息最后提及的锚点；手动输入优先可覆盖。 */
export function FocusGraphTab({ messages = [] }: { messages?: { role: string; content: string }[] }) {
  const [input, setInput] = useState('');
  const [nodeId, setNodeId] = useState('');
  const [depth, setDepth] = useState(2);
  const [manual, setManual] = useState(false);
  const inputCls = 'flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info';

  // T-921：消息锚点自动焦点（手动输入过则以手动为准）
  useEffect(() => {
    if (manual) return;
    const anchor = extractLastAnchor(messages);
    if (anchor) setNodeId(anchor);
  }, [messages, manual]);

  return (
    <div className="p-2">
      <div className="flex items-center gap-1.5 mb-2">
        <input className={inputCls} value={input} onChange={e => setInput(e.target.value)}
          placeholder="FR-xxx / tp:xxx / fd:xxx"
          onKeyDown={e => { if (e.key === 'Enter') { setManual(true); setNodeId(input.trim()); } }} />
        <select className="bg-surface-3 border border-border rounded px-1.5 py-1 text-fs-body text-gray-300"
          value={depth} onChange={e => setDepth(Number(e.target.value))}>
          <option value={1}>1 跳</option>
          <option value={2}>2 跳</option>
          <option value={3}>3 跳</option>
        </select>
        <button className="px-2.5 py-1 rounded text-fs-body bg-info/15 text-info hover:bg-info/25"
          onClick={() => { setManual(true); setNodeId(input.trim()); }}>查看</button>
      </div>
      {nodeId
        ? <FocusGraph nodeId={nodeId} depth={depth} height={420} />
        : <div className="text-fs-body text-gray-500 px-1 py-4 text-center">
            对话中提及 FR/话题/材料锚点时自动显示其子图；也可手动输入节点 ID
          </div>}
    </div>
  );
}
