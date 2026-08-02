/** ELK 自动布局（Dify elk-layout.ts 精简移植版）
 *
 * 保留：ROOT_LAYOUT_OPTIONS 调优参数 / 懒加载 / collectLayout / normaliseBounds / 层内 Y 居中
 * 砍掉：嵌套容器布局（iteration/loop）、分支端口排序（if-else 多出口）——SpecGuard 场景图为扁平 DAG
 */
import type { Edge } from '@xyflow/react';

let elk: import('elkjs/lib/elk-api').ELK | undefined;

async function getELK() {
  if (!elk) {
    const { default: ELK } = await import('elkjs/lib/elk.bundled.js');
    elk = new ELK();
  }
  return elk;
}

export const NODE_WIDTH = 220;
export const NODE_HEIGHT = 88;

/** Dify 生产调优的 layered 参数（方向 RIGHT，与场景 DAG 左→右拓扑一致） */
const ROOT_LAYOUT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  // Spacing
  'elk.layered.spacing.nodeNodeBetweenLayers': '100',
  'elk.spacing.nodeNode': '80',
  'elk.spacing.edgeNode': '50',
  'elk.spacing.edgeEdge': '30',
  // Port / 模型顺序
  'elk.portConstraints': 'FIXED_ORDER',
  'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
  'elk.layered.crossingMinimization.forceNodeModelOrder': 'true',
  // 节点放置
  'elk.layered.nodePlacement.strategy': 'BRANDES_KOEPF',
  'elk.layered.nodePlacement.favorStraightEdges': 'true',
  'elk.layered.nodePlacement.bk.fixedAlignment': 'BALANCED',
  // 边路由
  'elk.edgeRouting': 'SPLINES',
  'elk.layered.edgeRouting.splines.mode': 'CONSERVATIVE',
  // 交叉最小化
  'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
  'elk.layered.crossingMinimization.greedySwitch.type': 'TWO_SIDED',
  // 分层
  'elk.layered.layering.strategy': 'NETWORK_SIMPLEX',
  'elk.layered.layering.networkSimplex.nodeFlexibility': 'NODE_SIZE',
  // 环破解 / 连通分量
  'elk.layered.cycleBreaking.strategy': 'DEPTH_FIRST',
  'elk.separateConnectedComponents': 'true',
  'elk.spacing.componentComponent': '100',
  // 压缩
  'elk.layered.compaction.postCompaction.strategy': 'EDGE_LENGTH',
  'elk.layered.thoroughness': '10',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.contentAlignment': 'V_TOP H_LEFT',
};

export interface LayoutInfo { x: number; y: number; layer?: number }

interface ElkChildShape { id: string; width: number; height: number; x?: number; y?: number; layoutOptions?: Record<string, string> }

/** nodes/edges → ELK 布局坐标（含层内 Y 轴居中，移植自 Dify use-workflow-organize.helpers）。
 *  nodes 参数只需 id（布局前节点尚无 position） */
export async function layoutDagByELK(nodes: Array<{ id: string }>, edges: Edge[]): Promise<Map<string, LayoutInfo>> {
  const graph = {
    id: 'specguard-dag',
    layoutOptions: ROOT_LAYOUT_OPTIONS,
    children: nodes.map((n) => ({ id: n.id, width: NODE_WIDTH, height: NODE_HEIGHT })),
    edges: edges.map((e, i) => ({ id: `e${i}`, sources: [e.source], targets: [e.target] })),
  };

  const layouted = await (await getELK()).layout(graph);

  // collectLayout：收集坐标与层号
  const result = new Map<string, LayoutInfo>();
  let minX = Infinity;
  let minY = Infinity;
  (layouted.children || []).forEach((child: ElkChildShape) => {
    const layerRaw = child.layoutOptions?.['org.eclipse.elk.layered.layerIndex'];
    result.set(child.id, {
      x: child.x ?? 0,
      y: child.y ?? 0,
      layer: layerRaw !== undefined ? Number.parseInt(layerRaw) : undefined,
    });
    minX = Math.min(minX, child.x ?? 0);
    minY = Math.min(minY, child.y ?? 0);
  });
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return result;

  // normaliseBounds：原点归一
  const normalized = new Map<string, LayoutInfo>();
  result.forEach((info, id) => {
    normalized.set(id, { ...info, x: info.x - minX, y: info.y - minY });
  });

  // 层内 Y 居中对齐（createLayerMap + getAlignedYPosition）
  const layerMap = new Map<number, { minY: number; maxHeight: number }>();
  normalized.forEach((info) => {
    if (info.layer === undefined) return;
    const existing = layerMap.get(info.layer);
    layerMap.set(info.layer, {
      minY: existing ? Math.min(existing.minY, info.y) : info.y,
      maxHeight: existing ? Math.max(existing.maxHeight, NODE_HEIGHT) : NODE_HEIGHT,
    });
  });
  normalized.forEach((info, id) => {
    if (info.layer === undefined) return;
    const lm = layerMap.get(info.layer);
    if (!lm) return;
    normalized.set(id, { ...info, y: lm.minY + lm.maxHeight / 2 - NODE_HEIGHT / 2 });
  });

  return normalized;
}
