/** DagEditor — DAG 编排（Dify 模式）：全屏画布 + ELK 布局 + 连线建依赖 + 抽屉编辑器
 *
 * 画布交互：
 * - 连线（上游 → 下游）→ 客户端环预检 → POST /api/scenarios/{target}/deps → 自动重排
 * - 选边 Delete/Backspace → 移除依赖 → 自动重排
 * - 节点点击 → 右侧抽屉打开场景编辑器；点空白处收起
 * - 边着色：绿=版本匹配 / 蓝=minor 漂移 / 琥珀=major 漂移(DRIFT) / 红虚线=缺失(ORPHANED)
 * K-046：?focus= 高亮居中（草稿入库落点）+ 节点依赖建议面板（抽屉内一键采纳）
 *        + Shift 框选/ Ctrl 点选多节点 → 工具栏「执行选中」跳 RunControl 预选
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState,
  type Node, type Edge, type Connection, type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { scenariosApi, referenceApi, runsApi, plansApi } from '../api';
import type { DagData, Scenario, EmpRole, OracleRef, UpstreamVar, EnvVar, TestPlan, DriftItem, DepSuggestion } from '../api';
import ScenarioFormEditor from '../components/ScenarioFormEditor';
import ScenarioNode, { CATEGORY_META } from '../components/ScenarioNode';
import { layoutDagByELK, NODE_WIDTH, NODE_HEIGHT } from '../utils/elkLayout';
import { useJsTokens } from '../theme';

const nodeTypes = { scenario: ScenarioNode };

/** 边状态配色（match 低调灰 / minor 蓝 / major 琥珀 / orphan 红虚线） */
const EDGE_STATUS_STYLE: Record<string, { stroke: string; dash?: string }> = {
  match: { stroke: '' },  // match 走 tokens.edgeStroke（K-043）
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
  const tokens = useJsTokens();  // K-043
  // K-046：流程衔接——focus 聚焦 / 依赖建议 / 多选执行
  // 注意：navigate/searchParams 必须在 useState 初始化器（subset）之前声明，
  // 否则触发 const TDZ 报错（Cannot access 'searchParams' before initialization）
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
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
  const [selectedModule, setSelectedModule] = useState('');  // K-027: 模块分组筛选
  const [searchQuery, setSearchQuery] = useState('');        // K-027: 场景搜索定位
  // K-xxx：子集编排——先勾选一组场景再进画布（默认不再铺全量）
  const [subsetOpen, setSubsetOpen] = useState(false);
  const [subset, setSubset] = useState<Set<string>>(() => {
    const sel = searchParams.get('sel');
    return new Set(sel ? sel.split(',').filter(Boolean) : []);
  });
  // 子集变化 → URL 同步（?sel=，可带参直达/分享）
  useEffect(() => {
    const params = new URLSearchParams(searchParams);
    if (subset.size > 0) params.set('sel', [...subset].join(','));
    else params.delete('sel');
    navigate(`/dag?${params.toString()}`, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subset]);
  const [error, setError] = useState('');
  const [driftItems, setDriftItems] = useState<DriftItem[]>([]);
  const [cycleItems, setCycleItems] = useState<string[][]>([]);  // T-101: 库存在环时降级显示
  const [showDrift, setShowDrift] = useState(false);
  // K-046：流程衔接——focus 聚焦 / 依赖建议 / 多选执行
  const focusId = searchParams.get('focus') || '';
  const focusAppliedRef = useRef(false);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [suggestions, setSuggestions] = useState<DepSuggestion[]>([]);
  const [suggestError, setSuggestError] = useState('');  // T-104：建图失败显式提示（环预检失效）

  // 加载参考数据
  useEffect(() => {
    scenariosApi.list().then(setScenarios);
    referenceApi.empRoles().then(setEmpRoles);
    referenceApi.oracles().then(setOracles);
    referenceApi.envVars().then(setEnvVars);
    plansApi.list().then(setPlans);
    scenariosApi.drift().then((r) => { setDriftItems(r.items); setCycleItems(r.cycles || []); }).catch(() => {});
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

  // T-202：计划断点集合（选中计划时画布标记「在该场景前暂停」的场景）
  const breakpointSet = useMemo(() => {
    if (!selectedPlan) return new Set<string>();
    const plan = plans.find((p) => p.id === selectedPlan);
    return new Set((plan?.breakpoints || []) as string[]);
  }, [selectedPlan, plans]);

  // ELK 布局并渲染 DAG（异步）
  const layoutDag = useCallback(async (dag: DagData) => {
    const flowNodes = dag.nodes.map((n) => ({
      id: n.id,
      type: 'scenario',
      // 节点尺寸与 ELK 布局参数一致（elkljs 布局需要精确尺寸；固定宽高规避
      // 字体加载差异导致的布局抖动，如无 ResizeObserver 环境边不渲染的问题
      //（Dify 同策略；同时规避 ResizeObserver 不可用环境下边不渲染的问题）
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      // K-046：focus 高亮放在布局数据流里（异步重排/verdicts 刷新会重建 nodes，命令式打标会被覆盖）
      className: n.id === focusId ? 'ring-2 ring-info rounded-lg shadow-lg' : undefined,
      data: {
        label: n.id,
        title: (n.data as { title?: string }).title || '',
        version: (n.data as { version?: string }).version || '',
        category: (n.data as { category?: string }).category || 'validator',
        verdict: verdicts[n.id] || '',
        // T-202：计划断点场景画布标记（选中计划时生效）
        isBreakpoint: breakpointSet.has(n.id),
      },
    }));
    const flowEdges: Edge[] = dag.edges.map((e) => {
      const st = EDGE_STATUS_STYLE[e.status || 'match'] || EDGE_STATUS_STYLE.match;
      // T-103：边信息可视化——exclusive 标 excl；漂移边标期望/实际版本（此前只上色不给数值）
      let label: string | undefined;
      if (e.label === 'exclusive') label = 'excl';
      else if (e.status && e.status !== 'match' && e.expected) label = `v${e.expected}→${e.actual ?? '缺失'}`;
      return {
        id: e.id, source: e.source, target: e.target, animated: e.animated,
        label,
        style: { stroke: (e.status && e.status !== 'match') ? st.stroke : tokens.edgeStroke, strokeDasharray: st.dash },
      };
    });

    const positions = await layoutDagByELK(flowNodes, flowEdges);
    setNodes(flowNodes.map((n) => ({ ...n, position: positions.get(n.id) || { x: 0, y: 0 } })));
    setEdges(flowEdges);
  }, [verdicts, focusId, breakpointSet, setNodes, setEdges]);

  // 初始加载 DAG
  useEffect(() => {
    scenariosApi.dag().then((dag) => {
      setDagData(dag);
      layoutDag(dag);
    });
    scenariosApi.validate().then((r) => setDagValid(r.ok));
  }, [layoutDag]);

  // K-027：模块清单（从场景列表收集，按名称排序）
  const modules = useMemo(() => {
    const set = new Set<string>();
    scenarios.forEach((s) => { if (s.module) set.add(s.module); });
    return [...set].sort();
  }, [scenarios]);

  // 计划 + 模块 + 搜索 三重过滤后的 DAG
  const filteredDag = useMemo(() => {
    if (!dagData) return dagData;
    let nodes = dagData.nodes;
    let edges = dagData.edges;
    // ⓪ 子集过滤（K-xxx：勾选场景 + 直接依赖闭包，保持依赖边可见；
    //    ?focus= 无 ?sel= 时以 focus 场景闭包为默认视图）
    const selIds = subset.size > 0 ? subset : (focusId ? new Set([focusId]) : null);
    if (selIds) {
      const keep = new Set(selIds);
      edges.forEach((e) => {
        if (selIds.has(e.source) || selIds.has(e.target)) {
          keep.add(e.source); keep.add(e.target);
        }
      });
      nodes = nodes.filter((n) => keep.has(n.id));
    }
    // ① 计划过滤
    if (selectedPlan) {
      const plan = plans.find((p) => p.id === selectedPlan);
      const ids = new Set((plan?.filter?.scenarios || []) as string[]);
      if (ids.size) nodes = nodes.filter((n) => ids.has(n.id));
    }
    // ② 模块过滤（选中模块的场景 + 其直接上下游，保持依赖边可见）
    if (selectedModule) {
      const inModule = new Set(
        nodes.filter((n) => (n.data as { module?: string }).module === selectedModule).map((n) => n.id)
      );
      const keep = new Set(inModule);
      edges.forEach((e) => {
        if (inModule.has(e.source) || inModule.has(e.target)) {
          keep.add(e.source); keep.add(e.target);
        }
      });
      nodes = nodes.filter((n) => keep.has(n.id));
    }
    // ③ 搜索过滤（id/title 模糊）
    const q = searchQuery.trim().toLowerCase();
    if (q) {
      nodes = nodes.filter((n) =>
        n.id.toLowerCase().includes(q) ||
        ((n.data as { title?: string }).title || '').toLowerCase().includes(q));
    }
    // K-xxx：纯默认态（无子集/计划/模块/搜索）→ 空画布引导，不铺全量
    if (!selIds && !selectedPlan && !selectedModule && !q) {
      return { nodes: [], edges: [] };
    }
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes, edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
  }, [dagData, selectedPlan, selectedModule, searchQuery, plans, subset, focusId]);

  // 计划变更时重新布局
  useEffect(() => {
    if (filteredDag) layoutDag(filteredDag);
  }, [filteredDag, layoutDag]);

  // K-046：?focus= 聚焦——布局完成后居中目标节点（高亮由 layoutDag 数据流负责，此处只居中一次）
  useEffect(() => {
    if (!focusId || !rfInstance || focusAppliedRef.current || nodes.length === 0) return;
    const n = nodes.find((x) => x.id === focusId);
    if (!n) return;
    focusAppliedRef.current = true;
    rfInstance.setCenter(n.position.x + NODE_WIDTH / 2, n.position.y + NODE_HEIGHT / 2,
      { zoom: 1.15, duration: 500 });
  }, [focusId, rfInstance, nodes]);

  // K-046：多选节点（Shift 框选 / Ctrl 点选）→ 执行选中
  const selectedIds = useMemo(() => nodes.filter((n) => n.selected).map((n) => n.id), [nodes]);

  // 保存后刷新 DAG（自动重排）+ 漂移报告
  const refreshDag = useCallback(() => {
    scenariosApi.dag().then((dag) => {
      setDagData(dag);
      layoutDag(dag);
    });
    scenariosApi.validate().then((r) => setDagValid(r.ok));
    scenariosApi.drift().then((r) => { setDriftItems(r.items); setCycleItems(r.cycles || []); }).catch(() => {});
  }, [layoutDag]);

  // ─── 连线建依赖（Dify handleNodeConnect 模式：守卫 → 建边 → 同步）───
  // T-103：Shift 拖拽 = 独占依赖（exclusive，动画边 + 多实例重跑语义）
  const shiftPressed = useRef(false);
  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (e.key === 'Shift') shiftPressed.current = true; };
    const up = (e: KeyboardEvent) => { if (e.key === 'Shift') shiftPressed.current = false; };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); };
  }, []);

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
      const mode = shiftPressed.current ? 'exclusive' : 'shared';
      await scenariosApi.editDep(conn.target, { action: 'add', dep_id: conn.source, mode });
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

  // 点击节点 → 打开抽屉编辑器 + 拉取依赖建议（K-046）
  const onNodeClick = useCallback((_: unknown, node: Node) => {
    setSelected(node.id);
    scenariosApi.get(node.id).then((r) => setYamlContent(r.content)).catch(() => setYamlContent(''));
    referenceApi.upstreamVars(node.id).then(setUpstreamVars).catch(() => setUpstreamVars([]));
    scenariosApi.suggestDeps(node.id)
      .then((r) => { setSuggestions(r.suggestions || []); setSuggestError(r.graph_error || ''); })
      .catch(() => { setSuggestions([]); setSuggestError(''); });
  }, []);

  // 点空白处收起抽屉
  const onPaneClick = useCallback(() => { setSelected(null); setSuggestions([]); }, []);

  // K-046：采纳依赖建议（走现有 /deps 端点，服务端环校验兜底）
  // T-104：采纳时标注来源（confidence/kind → YAML 尾注释留痕，可追溯）
  const handleAcceptSuggestion = useCallback(async (sug: DepSuggestion) => {
    if (!selected) return;
    setError('');
    try {
      await scenariosApi.editDep(selected, {
        action: 'add', dep_id: sug.dep_id, mode: 'shared',
        note: `${sug.confidence} ${sug.kind}`,
      });
      setSuggestions((prev) => prev.filter((s) => s.dep_id !== sug.dep_id));
      refreshDag();
    } catch (e) {
      setError(`连线失败: ${e instanceof Error ? e.message : e}`);
    }
  }, [selected, refreshDag]);

  // T-105：批量采纳选中场景的依赖建议（逐个扫描 + 添加，服务端环校验兜底单条失败）
  const handleBatchAcceptSuggestions = useCallback(async () => {
    const targets = [...selectedIds];
    if (!targets.length) return;
    setError('');
    let added = 0;
    for (const sid of targets) {
      try {
        const r = await scenariosApi.suggestDeps(sid);
        for (const sug of r.suggestions || []) {
          try {
            await scenariosApi.editDep(sid, {
              action: 'add', dep_id: sug.dep_id, mode: 'shared',
              note: `${sug.confidence} ${sug.kind}`,
            });
            added++;
          } catch { /* 环校验等拒绝单条，继续 */ }
        }
      } catch { /* 单个场景失败不阻断批量 */ }
    }
    setError(added
      ? `批量采纳完成：${added} 条依赖已添加`
      : '所选场景没有可采纳的依赖建议');
    if (added) refreshDag();
  }, [selectedIds, refreshDag]);

  // T-201：孤节点补全——无依赖上游的场景批量扫描建议并采纳（T-105 验收点补全）
  const handleCompleteOrphans = useCallback(async () => {
    if (!dagData) return;
    const withInEdge = new Set(dagData.edges.map((e) => e.target));
    const orphans = dagData.nodes.map((n) => n.id).filter((id) => !withInEdge.has(id));
    if (!orphans.length) {
      setError('没有孤节点（所有场景都有依赖上游）');
      return;
    }
    setError('');
    let added = 0;
    for (const sid of orphans) {
      try {
        const r = await scenariosApi.suggestDeps(sid);
        for (const sug of r.suggestions || []) {
          try {
            await scenariosApi.editDep(sid, {
              action: 'add', dep_id: sug.dep_id, mode: 'shared',
              note: `${sug.confidence} ${sug.kind}`,
            });
            added++;
          } catch { /* 单条拒绝继续 */ }
        }
      } catch { /* 单个场景失败不阻断 */ }
    }
    setError(added
      ? `孤节点补全完成：扫描 ${orphans.length} 个无上游场景，采纳 ${added} 条依赖`
      : `孤节点扫描完成：${orphans.length} 个无上游场景均无可采纳建议`);
    if (added) refreshDag();
  }, [dagData, refreshDag]);

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
        <h2 className="text-fs-title font-semibold">🔀 DAG 编排</h2>
        {!dagValid && <span className="text-fs-body text-fail bg-fail/10 px-2 py-1 rounded">⚠️ 循环依赖</span>}
        {cycleItems.length > 0 && (
          <button
            onClick={() => setShowDrift(!showDrift)}
            className="text-fs-body px-2 py-1 rounded hover:opacity-80"
            style={{ color: '#f85149', background: '#f8514915' }}
            title="点击展开环清单">
            ⛔ {cycleItems.length} 条依赖环（已降级显示）{showDrift ? '▲' : '▼'}
          </button>
        )}
        {driftCount > 0 && (
          <button
            onClick={() => setShowDrift(!showDrift)}
            className="text-fs-body px-2 py-1 rounded hover:opacity-80"
            style={{ color: '#d29922', background: '#d2992215' }}
            title="点击展开漂移报告">
            ⚠️ {driftCount} 条版本漂移 {showDrift ? '▲' : '▼'}
          </button>
        )}
        {/* K-xxx：子集编排入口——先勾选一组场景再进画布（含直接依赖闭包） */}
        <button onClick={() => setSubsetOpen(true)}
          className={`px-2.5 py-1 rounded text-fs-body border transition-colors ${
            subset.size > 0
              ? 'bg-info/15 text-info border-info/40 hover:bg-info/25'
              : 'bg-surface-3 text-gray-300 border-border hover:border-info/40'
          }`}
          title="先勾选一组场景再编排依赖（自动包含直接依赖闭包），选择会同步到 URL ?sel=">
          🧩 选择场景{subset.size > 0 ? `（${subset.size}）` : ''}
        </button>
        {/* 计划选择器 */}
        <select value={selectedPlan} onChange={(e) => setSelectedPlan(e.target.value)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-fs-body"
          title="按测试计划筛选场景">
          <option value="">全部场景</option>
          {plans.map((p) => <option key={p.id} value={p.id}>📋 {p.name}{(p.breakpoints || []).length > 0 ? ` 🔴${(p.breakpoints || []).length}` : ''}</option>)}
        </select>
        {/* K-027：模块分组筛选（含直接上下游，保持依赖边可见） */}
        <select value={selectedModule} onChange={(e) => setSelectedModule(e.target.value)}
          className="bg-surface-3 border border-border rounded px-2 py-1 text-fs-body"
          title="按模块分组筛选（含直接上下游）">
          <option value="">全部模块</option>
          {modules.map((m) => <option key={m} value={m}>📁 {m}</option>)}
        </select>
        {/* K-027：场景搜索定位（id/标题模糊） */}
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="🔍 搜索场景 ID / 标题"
          className="w-44 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body"
        />
        <span className="text-fs-aux text-gray-600">
          {filteredDag && dagData ? `${filteredDag.nodes.length}/${dagData.nodes.length} 节点` : ''}
        </span>
        {/* K-046：多选执行（Shift 框选 / Ctrl 点选后一键跳 RunControl 预选）；T-105：批量断点/批量采纳 */}
        {selectedIds.length > 0 && (
          <>
            <button
              onClick={() => navigate(`/run?ids=${selectedIds.join(',')}`)}
              className="px-2.5 py-1 bg-info text-white rounded text-fs-body hover:bg-info/90"
              title={`执行选中场景：${selectedIds.join('、')}`}
            >
              ▶ 执行选中（{selectedIds.length}）
            </button>
            <button
              onClick={() => navigate(`/run?ids=${selectedIds.join(',')}&bps=${selectedIds.join(',')}`)}
              className="px-2.5 py-1 bg-warn/90 text-black rounded text-fs-body hover:opacity-85"
              title="全部选中场景设为断点（执行到每个断点前暂停），跳 RunControl 确认"
            >
              🔴 批量设断点
            </button>
            <button
              onClick={handleBatchAcceptSuggestions}
              className="px-2.5 py-1 bg-surface-3 border border-border rounded text-fs-body text-info hover:border-info/40"
              title="对选中场景批量扫描并采纳依赖建议（服务端环校验兜底）"
            >
              💡 批量采纳建议
            </button>
          </>
        )}
        {/* 类型图例 */}
        <div className="flex gap-2 ml-auto">
          {Object.entries(CATEGORY_META).map(([key, meta]) => (
            <span key={key} className="text-fs-aux px-1.5 py-0.5 rounded" style={{ color: meta.color, background: meta.color + '15' }}>
              {meta.icon} {meta.label}({catCounts[key] || 0})
            </span>
          ))}
        </div>
        <button onClick={refreshDag} className="text-fs-aux text-gray-500 hover:text-info px-2 py-1 rounded border border-border hover:border-info/40" title="重新布局">
          🔄 重排
        </button>
        {/* T-201：孤节点补全——无上游场景批量扫描建议并采纳 */}
        <button
          onClick={handleCompleteOrphans}
          className="text-fs-aux text-gray-500 hover:text-pass px-2 py-1 rounded border border-border hover:border-pass/40"
          title="扫描无依赖上游的场景，批量采纳依赖建议（跨场景变量引用补全）"
        >
          🟢 补全孤节点
        </button>
        {/* K-xxx：对话编排主入口——Agent 会话承担编排，画布保留编辑作复核视图 */}
        <button
          onClick={() => navigate(`/agent?hint=dag-orchestration`)}
          className="text-fs-aux text-info hover:opacity-80 px-2 py-1 rounded border border-info/40 hover:border-info/60 bg-info/10"
          title="在对话中编排依赖（建议/加边/删边/复核）——Agent 会话是 DAG 编排主入口，本画布为可视化复核视图"
        >
          🤖 对话编排
        </button>
      </div>

      {error && (
        <div className="text-fs-body text-fail bg-fail/10 border border-fail/30 rounded px-3 py-2 flex items-center">
          <span className="flex-1">⛔ {error}</span>
          <button onClick={() => setError('')} className="text-gray-500 hover:text-fail ml-2">✕</button>
        </div>
      )}

      {/* K-xxx：场景子集选择弹层（模块分组勾选，画布实时预览闭包） */}
      {subsetOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center"
          onClick={() => setSubsetOpen(false)}>
          <div className="bg-surface-2 border border-border rounded-xl p-4 w-[620px] max-w-[92vw] max-h-[80vh] flex flex-col shadow-2xl"
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2">
              <div className="text-fs-lead font-medium text-gray-200">
                🧩 选择编排场景（自动包含直接依赖闭包）
              </div>
              <button onClick={() => setSubsetOpen(false)} className="text-gray-500 hover:text-gray-300">✕</button>
            </div>
            <div className="flex items-center gap-2 mb-2 text-fs-body">
              <button onClick={() => setSubset(new Set(scenarios.map(s => s.id)))}
                className="px-2 py-0.5 rounded bg-surface-3 text-gray-300 hover:bg-surface-1">全选</button>
              <button onClick={() => setSubset(new Set())}
                className="px-2 py-0.5 rounded bg-surface-3 text-gray-300 hover:bg-surface-1">清空</button>
              <span className="text-gray-500">已选 {subset.size} / {scenarios.length}</span>
              <button onClick={() => setSubsetOpen(false)}
                className="ml-auto px-3 py-0.5 rounded bg-info text-white hover:bg-info/90">确定</button>
            </div>
            <div className="flex-1 overflow-y-auto space-y-2">
              {modules.map(mod => {
                const modScs = scenarios.filter(s => s.module === mod);
                return (
                  <div key={mod}>
                    <div className="text-fs-body text-gray-500 mb-1">📁 {mod}</div>
                    <div className="grid grid-cols-3 gap-1">
                      {modScs.map(s => (
                        <label key={s.id}
                          className="flex items-center gap-1.5 text-fs-body text-gray-300 cursor-pointer hover:bg-surface-3 rounded px-1.5 py-0.5 truncate"
                          title={s.title}>
                          <input type="checkbox" className="flex-shrink-0" checked={subset.has(s.id)}
                            onChange={(e) => {
                              const next = new Set(subset);
                              if (e.target.checked) next.add(s.id); else next.delete(s.id);
                              setSubset(next);
                            }} />
                          <span className="font-mono truncate">{s.id}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 漂移报告面板（DRIFT/ORPHANED 清单 + T-101 依赖环清单） */}
      {showDrift && (driftCount > 0 || cycleItems.length > 0) && (
        <div className="border rounded-lg px-4 py-3 space-y-1.5" style={{ borderColor: '#d2992240', background: '#d2992208' }}>
          {cycleItems.length > 0 && (
            <>
              <div className="text-fs-body font-medium" style={{ color: '#f85149' }}>依赖环（DAG 仲裁已降级，请修正后重载）</div>
              {cycleItems.map((c, idx) => (
                <div key={idx} className="flex items-start gap-2 text-fs-body font-mono">
                  <span style={{ color: '#f85149' }}>⛔</span>
                  <span>{c.join(' → ')}</span>
                </div>
              ))}
            </>
          )}
          {driftCount > 0 && (
            <>
              <div className="text-fs-body font-medium" style={{ color: '#d29922' }}>版本漂移报告（归档前必须清零）</div>
              {driftItems.filter((i) => i.status === 'major_drift' || i.status === 'orphan').map((i, idx) => (
                <div key={idx} className="flex items-start gap-2 text-fs-body">
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
            </>
          )}
        </div>
      )}

      <div className="flex-1 flex gap-3 min-h-0">
        {/* 全屏 DAG 画布（连线=建依赖，选边 Delete=移除） */}
        <div className="flex-1 min-w-0 border border-border rounded-lg overflow-hidden relative">
          {dagData && filteredDag && filteredDag.nodes.length === 0 && (
            <div className="absolute inset-0 z-10 flex items-center justify-center pointer-events-none">
              <div className="bg-surface-2/95 border border-border rounded-xl p-8 text-center pointer-events-auto shadow-2xl">
                <div className="text-4xl mb-3">🧩</div>
                <div className="text-fs-lead text-gray-200 mb-1 font-medium">先选择一组场景，再开始编排依赖</div>
                <div className="text-fs-body text-gray-500 mb-4 leading-relaxed">
                  90+ 测试全部上画布会找不到重点——勾选目标场景（自动包含<br />
                  直接依赖闭包），或按计划 / 模块 / 搜索收敛视图
                </div>
                <button onClick={() => setSubsetOpen(true)}
                  className="px-4 py-1.5 bg-info text-white rounded text-fs-body hover:bg-info/90">
                  🧩 选择场景
                </button>
              </div>
            </div>
          )}
          <ReactFlow
            nodes={nodes} edges={edges}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
            onConnect={onConnect} onEdgesDelete={onEdgesDelete}
            onNodeClick={onNodeClick} onPaneClick={onPaneClick}
            onInit={setRfInstance}
            nodeTypes={nodeTypes}
            deleteKeyCode={['Backspace', 'Delete']}
            fitView proOptions={{ hideAttribution: true }}
            colorMode={tokens.dark ? 'dark' : 'light'}
          >
            <Background color={tokens.rfBackground} gap={20} />
            <Controls />
            <MiniMap nodeColor={tokens.minimapNode} maskColor={tokens.minimapMask} style={{ background: tokens.minimapBg }} />
          </ReactFlow>
        </div>

        {/* 抽屉式场景编辑器 */}
        {selected && (
          <div className="w-[46%] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-surface-2">
              <span className="text-fs-body text-gray-400 font-mono">{selected}</span>
              <button onClick={() => { setSelected(null); setSuggestions([]); }} className="text-gray-500 hover:text-fail text-fs-lead" title="收起编辑器">✕</button>
            </div>
            {/* K-046：依赖建议面板（确定性引擎扫描插值得出，一键采纳连线） */}
            {suggestions.length > 0 && (
              <div className="px-3 py-2 border-b border-info/40 bg-info/5">
                <div className="text-info text-fs-body font-medium mb-1">
                  💡 {suggestions.length} 条依赖建议（扫描 {'{{...}}'} 插值匹配生产者）
                </div>
                {suggestError && (
                  <div className="text-fail text-fs-aux mb-1" title={suggestError}>
                    ⚠️ 建图失败，环预检已失效：{suggestError.slice(0, 80)}
                  </div>
                )}
                <ul className="space-y-1">
                  {suggestions.map((s, i) => (
                    <li key={i} className="flex items-center gap-2 text-fs-body">
                      <span className={`px-1 py-0.5 rounded ${
                        s.confidence === 'high' ? 'bg-pass/20 text-pass' : 'bg-warn/20 text-warn'
                      }`}>{s.confidence === 'high' ? '高置信' : '中置信'}</span>
                      <span className="font-mono text-gray-200">{s.dep_id}</span>
                      <span className="text-gray-500 truncate flex-1" title={s.reason}>
                        {s.dep_title || s.reason}
                      </span>
                      <button
                        onClick={() => handleAcceptSuggestion(s)}
                        title={s.reason}
                        className="px-2 py-0.5 bg-info/20 text-info rounded hover:bg-info/30"
                      >
                        采纳
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
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

