/** api/graph — T-997 自 api.ts 按域拆分（行为零变化纯重构） */
import { request } from './core';
import type { FocusGraphResp, NetworkViewResp } from './feishuPool';

// ══════════════════════════════════════════════════════════
// P-A 图谱（T-070/T-071，M11 §5.1）
// ══════════════════════════════════════════════════════════

export interface GraphStatus {
  fingerprint: string;
  source_fingerprint: string;
  stale: boolean;
  built_at: string | null;
}

export interface GraphNodeRef {
  file: string;
  line_range: number[];
}

export interface GraphNode {
  id: string;
  node_type: string;
  stage: string;
  title: string;
  module: string;
  feature: string;
  attrs: Record<string, any>;
  source_ref?: GraphNodeRef | null;
}

export interface GraphL0 {
  l0mods: Record<string, { name: string; fr_count: number; counts: number[] }>;
  l0edges: { a: string; b: string; w: number }[];
  lens?: string;
  era?: string;
}

export interface GraphL1Item {
  health: number | null;
  counts: number[];
  era: number;
  nCov: number;
  nGap: number;
}

export interface GraphL2Fr {
  id: string;
  t: string;
  era: number;
  modAt: string | null;
  goneAt: string | null;
  cov: 'ok' | 'gap';
  source_ref?: GraphNodeRef | null;
}

export interface GraphL2Scenario {
  id: string;
  title: string;
  covers: string[];
  source_ref?: GraphNodeRef | null;
}

export interface GraphL2 {
  frs: GraphL2Fr[];
  frEdges: string[][];
  scenarios: GraphL2Scenario[];
  era?: string;
}

export interface GraphBacklink {
  covered_by: string[];
  modified_by: string[];
  decided_by: string[];
  referenced_by: string[];
}

export interface GraphSourceFile {
  path: string;
  content: string;
  format: string;
  line: number;
  total_lines: number;
}

export interface GraphSnapshot {
  snapshot_id: string;
  label: string;
  trigger: string;
  created_at: string;
  source_fingerprint: string;
  nodes: number;
  edges: number;
}

export interface GraphDiff {
  from: string;
  to: string;
  added: number;
  removed: number;
  modified: number;
  edge_added: number;
  edge_removed: number;
  per_module: Record<string, { added: number; removed: number; modified: number }>;
  fingerprint_from: string;
  fingerprint_to: string;
  added_ids: string[];
  removed_ids: string[];
  modified_ids: string[];
}

export const graphApi = {
  status: () => request<GraphStatus>('/graph/status'),
  panoramaL0: (lens = 'map') => request<GraphL0>(`/graph/panorama?level=L0&lens=${lens}`),
  panoramaL1: (module: string, lens = 'map') =>
    request<Record<string, GraphL1Item>>(`/graph/panorama/${encodeURIComponent(module)}?lens=${lens}`),
  panoramaL2: (module: string, feature: string) =>
    request<GraphL2>(`/graph/panorama/${encodeURIComponent(module)}/${encodeURIComponent(feature)}`),
  backlink: (nodeId: string) =>
    request<{ node: GraphNode; backlink: GraphBacklink }>(`/graph/backlink/${encodeURIComponent(nodeId)}`),
  focus: (nodeId: string, depth = 2) =>
    request<FocusGraphResp>(`/graph/focus?node_id=${encodeURIComponent(nodeId)}&depth=${depth}`),
  network: () =>
    request<NetworkViewResp>('/graph/panorama?level=L0&lens=network'),
  rebuild: () => request<{ nodes: number; edges: number; source_fingerprint: string; built_at: string }>('/graph/rebuild', { method: 'POST' }),
  source: (file: string, line = 0) =>
    request<GraphSourceFile>(`/graph/source?file=${encodeURIComponent(file)}&line=${line}`),
  listSnapshots: () => request<{ snapshots: GraphSnapshot[] }>('/graph/snapshots'),
  createSnapshot: (label = '', trigger = 'manual') =>
    request<{ snapshot_id: string; nodes: number; edges: number; source_fingerprint: string }>(
      `/graph/snapshots?label=${encodeURIComponent(label)}&trigger=${encodeURIComponent(trigger)}`,
      { method: 'POST' }),
  diff: (fromSnapshot: string, toSnapshot = 'current') =>
    request<GraphDiff>(`/graph/diff?from_snapshot=${encodeURIComponent(fromSnapshot)}&to_snapshot=${encodeURIComponent(toSnapshot)}`),
};

// ══════════════════════════════════════════════════════════
// 血缘链（T-073，M10 §5.1）
// ══════════════════════════════════════════════════════════

export interface LineageNode {
  id: string;
  type: string;
  stage: string;
  title: string;
  status: string;
  external: boolean;
  url: string;
}

export interface LineageEdge {
  from: string;
  to: string;
  type: string;
}

export interface LineageTrace {
  path: LineageNode[];
  edges: LineageEdge[];
  truncated: boolean;
  root: string;
  direction: string;
}

export const lineageApi = {
  trace: (node: string, dir: 'up' | 'down' | 'both' = 'up', maxDepth = 8) =>
    request<LineageTrace>(`/lineage/trace?node=${encodeURIComponent(node)}&dir=${dir}&max_depth=${maxDepth}`),
  node: (nodeId: string) =>
    request<{ node: GraphNode; upstream: string[]; edges: { src: string; dst: string; edge_type: string; attrs: any }[] }>(
      `/lineage/node/${encodeURIComponent(nodeId)}`),
  check: (rebuild = false) =>
    request<{ warnings: { rule: string; node: string; node_type: string; message: string }[]; checked_at: string; graph_fingerprint: string }>(
      '/lineage/check', { method: rebuild ? 'POST' : 'GET' }),
};

