/** DagEditor — DAG 编排（Dify 模式）：全屏画布 + ELK 布局 + 连线建依赖 + 抽屉编辑器
 *
 * 画布交互：
 * - 连线（上游 → 下游）→ 客户端环预检 → POST /api/scenarios/{target}/deps → 自动重排
 * - 选边 Delete/Backspace → 移除依赖 → 自动重排
 * - 节点点击 → 右侧抽屉打开场景编辑器；点空白处收起
 * - 边着色：绿=版本匹配 / 蓝=minor 漂移 / 琥珀=major 漂移(DRIFT) / 红虚线=缺失(ORPHANED)
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  type Node, type Edge, type Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { scenariosApi, referenceApi, runsApi, plansApi } from '../api';
import type { DagData, Scenario, EmpRole, OracleRef, UpstreamVar, EnvVar, TestPlan, DriftItem } from '../api';
import ScenarioFormEditor from '../components/ScenarioFormEditor';
import ScenarioNode, { CATEGORY_META } from '../components/ScenarioNode';
import { layoutDagByELK, NODE_WIDTH, NODE_HEIGHT } from '../utils/elkLayout';

const nodeTypes = { scenario: ScenarioNode };

/** 边状态配色（match 低调灰 / minor 蓝 / major 琥珀 / orphan 红虚线） */
const EDGE_STATUS_STYLE: Record<string, { stroke: string; dash?: string }> = {
  match: { stroke: '#2d3646' },
  minor_drift: { stroke: '#58a6ff' },
  major_drift: { stroke: '#d29922' },
  orphan: { stroke: '#f85149', dash: '6 4' },
};

/** DFS 可达性：从 from 沿 edges（source→target 方向）能否到达 to（环预检） */
function isReachable(from: string, to: string, edges: Edge[]): boolean {
  const adj = new Map<string, string[]>();
  edges.forEach((e) => {
    if (!adj.has(e.source)) adj.set(e.source, []);
    adj.get(e.source)!.push(e.target);
  });
  const visited = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === to) return true;
    if (visited.has(cur)) continue;
    visited.add(cur);
    (adj.get(cur) || []).forEach((n) => stack.push(n));
  }
  return false;
}

export default function DagEditor() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [yamlContent, setYamlContent] = useState('');
  const [dagValid, setDagValid] = useState(true);
  const [verdicts, setVerdicts] = useState<Record<string, string>>({});
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [empRoles, setEmpRoles] = useState<EmpRole[]>([]);
  const [oracles, setOracles] = useState<OracleRef[]>([]);
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [upstreamVars, setUpstreamVars] = useState<UpstreamVar[]>([]);
  const [dagData, setDagData] = useState<DagData | null>(null);
  const [plans, setPlans] = useState<TestPlan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState('');
  const [error, setError] = useState('');
  const [driftItems, setDriftItems] = useState<DriftItem[]>([]);
  const [showDrift, setShowDrift] = useState(false);

  // 加载参考数据
  useEffect(() => {
    scenariosApi.list().then(setScenarios);
    referenceApi.empRoles().then(setEmpRoles);
    referenceApi.oracles().then(setOracles);
    referenceApi.envVars().then(setEnvVars);
    plansApi.list().then(setPlans);
    scenariosApi.drift().then((r) => setDriftItems(r.items)).catch(() => {});
  }, []);

  // 加载最近一次运行 verdicts
  useEffect(() => {
    runsApi.history(1).then((runs) => {
      if (!runs.length) return;
      runsApi.get(runs[0].run_id).then((detail) => {
        const cases = (detail as { cases?: { id: string; verdict: string }[] }).cases || [];
        const map: Record<string, string> = {};
        cases.forEach((c) => { if (!map[c.id] || c.verdict === 'FAIL') map[c.id] = c.verdict; });
        setVerdicts(map);
      }).catch(() => {});
    }).catch(() => {});
  }, []);

  // ELK 布局并渲染 DAG（异步）
  const layoutDag = useCallback(async (dag: DagData) => {
    const flowNodes: Node[] = dag.nodes.map((n) => ({
      id: n.id,
      type: 'scenario',
      position: { x: 0, y: 0 },
      // 显式尺寸：v12 跳过 ResizeObserver 测量等待，节点/边立即可渲染
      //（Dify 同策略；同时规避 ResizeObserver 不可用环境下边不渲染的问题）
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: {
        label: n.id,
        title: (n.data as { title?: string }).title || '',
        version: (n.data as { version?: string }).version || '',
        category: (n.data as { category?: string }).category || 'validator',
        verdict: verdicts[n.id] || '',
      },
    }));
    const flowEdges: Edge[] = dag.edges.map((e) => {
      const st = EDGE_STATUS_STYLE[e.status || 'match'] || EDGE_STATUS_STYLE.match;
      return {
        id: e.id, source: e.source, target: e.target, animated: e.animated,
        label: e.label || undefined,
        style: { stroke: st.stroke, strokeDasharray: st.dash },
      };
    });

    const positions = await layoutDagByELK(flowNodes, flowEdges);
    setNodes(flowNodes.map((n) => ({ ...n, position: positions.get(n.id) || { x: 0, y: 0 } })));
    setEdges(flowEdges);
  }, [verdicts, setNodes, setEdges]);

  // 初始加载 DAG
  useEffect(() => {
    scenariosApi.dag().then((dag) => {
      setDagData(dag);
      layoutDag(dag);
    });
    scenariosApi.validate().then((r) => setDagValid(r.ok));
  }, [layoutDag]);

  // 计划过滤后的 DAG
  const filteredDag = useMemo(() => {
    if (!dagData || !selectedPlan) return dagData;
    const plan = plans.find((p) => p.id === selectedPlan);
    if (!plan) return dagData;
    const ids = new Set((plan.filter?.scenarios || []) as string[]);
    if (!ids.size) return dagData;
    return {
      nodes: dagData.nodes.filter((n) => ids.has(n.id)),
      edges: dagData.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
    };
  }, [dagData, selectedPlan, plans]);

  // 计划变更时重新布局
  useEffect(() => {
    if (filteredDag) layoutDag(filteredDag);
  }, [filteredDag, layoutDag]);

  // 保存后刷新 DAG（自动重排）+ 漂移报告
  const refreshDag = useCallback(() => {
    scenariosApi.dag().then((dag) => {
      setDagData(dag);
      layoutDag(dag);
    });
    scenariosApi.validate().then((r) => setDagValid(r.ok));
    scenariosApi.drift().then((r) => setDriftItems(r.items)).catch(() => {});
  }, [layoutDag]);

  // ─── 连线建依赖（Dify handleNodeConnect 模式：守卫 → 建边 → 同步）───
  const onConnect = useCallback(async (conn: Connection) => {
    setError('');
    if (!conn.source || !conn.target) return;
    if (conn.source === conn.target) {
      setError('不允许自依赖');
      return;
    }
    // 重边守卫
    if (edges.some((e) => e.source === conn.source && e.target === conn.target)) return;
    // 环预检：新增 source→target 后，若 target 已可达 source 则成环
    if (isReachable(conn.target, conn.source, edges)) {
      setError(`会形成循环依赖: ${conn.source} → ${conn.target} → … → ${conn.source}`);
      return;
    }
    try {
      // depends_on 写在下游（target）身上，依赖上游（source）
      await scenariosApi.editDep(conn.target, { action: 'add', dep_id: conn.source, mode: 'shared' });
      refreshDag();
    } catch (e) {
      setError(`依赖创建失败: ${e instanceof Error ? e.message : e}`);
    }
  }, [edges, refreshDag]);

  // ─── 删边移除依赖 ───
  const onEdgesDelete = useCallback(async (deleted: Edge[]) => {
    setError('');
    for (const e of deleted) {
      try {
        await scenariosApi.editDep(e.target, { action: 'remove', dep_id: e.source });
      } catch (err) {
        setError(`依赖移除失败: ${err instanceof Error ? err.message : err}`);
      }
    }
    refreshDag();
  }, [refreshDag]);

  // 点击节点 → 打开抽屉编辑器
  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setSelected(node.id);
    scenariosApi.get(node.id).then((r) => setYamlContent(r.content)).catch(() => setYamlContent(''));
    referenceApi.upstreamVars(node.id).then(setUpstreamVars).catch(() => setUpstreamVars([]));
  }, []);

  // 点空白处收起抽屉
  const onPaneClick = useCallback(() => setSelected(null), []);

  // 保存回调
  const handleSave = useCallback(async (yaml: string) => {
    if (!selected) return;
    await scenariosApi.save(selected, yaml);
    setYamlContent(yaml);
    refreshDag();
  }, [selected, refreshDag]);

  // 统计各类型数量
  const catCounts = scenarios.reduce((acc, s) => {
    acc[s.category] = (acc[s.category] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const driftCount = driftItems.filter((i) => i.status === 'major_drift' || i.status === 'orphan').length;

  return (
    <div className="h-full flex flex-col space-y-3">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold">🔀 DAG 编排</h2>
        {!dagValid && <span className="text-xs text-fail bg-fail/10 px-2 py-1 rounded">⚠️ 循环依赖</span>}
        {driftCount > 0 && (
          <button
            onClick={() => setShowDrift(!showDrift)}
            className="text-xs px-2 py-1 rounded hover:opacity-80"
            style={{ color: '#d29922', background: '#d2992215' }}
            title="点击展开漂移报告">
            ⚠️ {driftCount} 条版本漂移 {showDrift ? '▲' : '▼'}
          </button>
        )}
        {/* 计划选择器 */}
        <select value={selectedPlan} onChange={(e) => setSelectedPlan(e.target.value)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-xs">
          <option value="">全部场景</option>
          {plans.map((p) => <option key={p.id} value={p.id}>📋 {p.name}</option>)}
        </select>
        {/* ID 查询（创建场景时用） */}
        <IdQueryTool />
        {/* 类型图例 */}
        <div className="flex gap-2 ml-auto">
          {Object.entries(CATEGORY_META).map(([key, meta]) => (
            <span key={key} className="text-[10px] px-1.5 py-0.5 rounded" style={{ color: meta.color, background: meta.color + '15' }}>
              {meta.icon} {meta.label}({catCounts[key] || 0})
            </span>
          ))}
        </div>
        <button onClick={refreshDag} className="text-[10px] text-gray-500 hover:text-info px-2 py-1 rounded border border-border hover:border-info/40" title="重新布局">
          🔄 重排
        </button>
      </div>

      {error && (
        <div className="text-xs text-fail bg-fail/10 border border-fail/30 rounded px-3 py-2 flex items-center">
          <span className="flex-1">⛔ {error}</span>
          <button onClick={() => setError('')} className="text-gray-500 hover:text-fail ml-2">✕</button>
        </div>
      )}

      {/* 漂移报告面板（DRIFT/ORPHANED 清单 + 处理建议） */}
      {showDrift && driftCount > 0 && (
        <div className="border rounded-lg px-4 py-3 space-y-1.5" style={{ borderColor: '#d2992240', background: '#d2992208' }}>
          <div className="text-xs font-medium" style={{ color: '#d29922' }}>版本漂移报告（归档前必须清零）</div>
          {driftItems.filter((i) => i.status === 'major_drift' || i.status === 'orphan').map((i, idx) => (
            <div key={idx} className="flex items-start gap-2 text-[11px]">
              <span style={{ color: i.status === 'orphan' ? '#f85149' : '#d29922' }}>
                {i.status === 'orphan' ? '✗' : '⚠'}
              </span>
              <span className="font-mono">{i.consumer} → {i.id}</span>
              <span className="text-gray-500">
                期望 {i.expected || '(未声明)'} / 实际 {i.actual || '缺失'}
              </span>
              <span className="text-gray-600 ml-auto">
                {i.status === 'orphan' ? '上游已删除/改名，请修正 depends_on' : '请核对上游契约后 bump 期望版本'}
              </span>
            </div>
          ))}
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* 全屏 DAG 画布（连线=建依赖，选边 Delete=移除） */}
        <div className="flex-1 min-w-0 border border-border rounded-lg overflow-hidden">
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onConnect={onConnect} onEdgesDelete={onEdgesDelete}
            onNodeClick={onNodeClick} onPaneClick={onPaneClick}
            nodeTypes={nodeTypes}
            deleteKeyCode={['Backspace', 'Delete']}
            fitView proOptions={{ hideAttribution: true }}
          >
            <Background color="#2d3646" gap={20} />
            <Controls />
            <MiniMap nodeColor="#161b22" maskColor="rgba(13,17,23,0.8)" style={{ background: '#0d1117' }} />
          </ReactFlow>
        </div>

        {/* 抽屉式场景编辑器 */}
        {selected && (
          <div className="w-[46%] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-surface-2">
              <span className="text-xs text-gray-400 font-mono">{selected}</span>
              <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-fail text-sm" title="收起编辑器">✕</button>
            </div>
            <div className="flex-1 min-h-0">
              <ScenarioFormEditor
                scenarioId={selected}
                yamlContent={yamlContent}
                empRoles={empRoles}
                oracles={oracles}
                upstreamVars={upstreamVars}
                envVars={envVars}
                allScenarios={scenarios.map((s) => ({ id: s.id, title: s.title }))}
                onSave={handleSave}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** ID 查询工具（创建场景时查下一可用 ID / 校验唯一性） */
function IdQueryTool() {
  const [prefix, setPrefix] = useState('PP');
  const [type, setType] = useState('RC');
  const [result, setResult] = useState('');
  const [checkId, setCheckId] = useState('');
  const [checkResult, setCheckResult] = useState('');

  const queryNext = async () => {
    try {
      const r = await referenceApi.nextId(prefix, type);
      setResult(`${r.next_id}`);
    } catch { setResult('查询失败'); }
  };

  const checkUnique = async () => {
    if (!checkId) return;
    try {
      const r = await referenceApi.validateId(checkId);
      setCheckResult(r.unique ? `✅ 可用` : `❌ 已占用`);
    } catch { setCheckResult('校验失败'); }
  };

  return (
    <div className="flex items-center gap-1.5 text-[10px]">
      <select value={prefix} onChange={(e) => setPrefix(e.target.value)}
        className="bg-surface-3 border border-border rounded px-1 py-0.5">
        {['PP', 'IS', 'IP', 'SS', 'EV'].map((p) => <option key={p}>{p}</option>)}
      </select>
      <select value={type} onChange={(e) => setType(e.target.value)}
        className="bg-surface-3 border border-border rounded px-1 py-0.5">
        {['RC', 'SNAP', 'PERM', 'SEC', 'PREP'].map((t) => <option key={t}>{t}</option>)}
      </select>
      <button onClick={queryNext} className="text-info hover:underline" title="查询下一可用 ID">🆔</button>
      {result && <span className="text-pass font-mono">{result}</span>}
      <input value={checkId} onChange={(e) => setCheckId(e.target.value)}
        placeholder="校验ID" className="w-20 bg-surface-3 border border-border rounded px-1 py-0.5 font-mono" />
      <button onClick={checkUnique} className="text-info hover:underline">校验</button>
      {checkResult && <span className="font-mono">{checkResult}</span>}
    </div>
  );
}
