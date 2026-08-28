/** 测试用例管理页 API（T-1035）——只读派生数据，评级/问题标记口径以后端
 *  workbench/backend/services/scenario_quality.py 为唯一事实源，前端只渲染。 */
import { request } from './core';

export type QualityGrade = 'deep' | 'medium' | 'shallow' | 'no-verify';

export type QualityIssue =
  | 'missing-covers' | 'invalid-covers' | 'shallow' | 'no-verify' | 'probe';

export interface CoverDetail {
  fr: string;
  valid: boolean;    // false = 当前工作区锚点表查不到（如 spec 世代/编号体系不匹配）
  title: string;     // 有效时的锚点标题（失效为 ''）
  module: string;
}

export interface ScenarioQualityRow {
  id: string;
  title: string;
  suite: string;
  module: string;
  path: string;
  covers: string[];
  covers_detail: CoverDetail[];
  invalid_covers: string[];
  dimensions: string[];
  priority: string;
  tags: string[];
  verify_count: number;
  evidence: string[];
  grade: QualityGrade;
  issues: QualityIssue[];
  doc_summary: { given: string; when: string; then: string };
  steps: Record<string, number>;
  tools: string[];
  oracles: string[];
  depends_on: { id: string; mode: string }[];
}

export interface SuiteQualityRow {
  key: string;
  feature: string;
  module: string;
  spec_ref: string;
  spec_version: string;
  scenarios: number;
  covers_tagged: number;
  covers_rate: number;
  grades: Record<QualityGrade, number>;
  scenarios_with_issues: number;
}

export interface QualityOverview {
  generated_at: string;
  root: string;
  anchors_available: boolean;
  totals: {
    scenarios: number;
    suites: number;
    covers_tagged: number;
    covers_rate: number;
    grades: Record<QualityGrade, number>;
    issues: Record<string, number>;
    scenarios_with_issues: number;
    anchors_total: number;
    anchors_covered: number;
    fr_gaps: number | null;
  };
  suites: SuiteQualityRow[];
  capability_matrix: {
    steps: Record<string, number>;
    tools: Record<string, number>;
    oracles: Record<string, number>;
    depends: Record<string, number>;
  };
  scenarios: ScenarioQualityRow[];
}

export const scenarioQualityApi = {
  overview: (refresh = false) =>
    request<QualityOverview>(`/scenario-quality/overview${refresh ? '?refresh=1' : ''}`),
  // ── T-1037 形状契约 / T-1038 并行安全 ──
  shapeContract: (refresh = false) =>
    request<ShapeContract>(`/scenario-quality/shape-contract${refresh ? '?refresh=1' : ''}`),
  parallelSafety: (refresh = false) =>
    request<ParallelSafety>(`/scenario-quality/parallel-safety${refresh ? '?refresh=1' : ''}`),
};

export interface ShapeFinding {
  type: 'unresolved-ref' | 'removed-path' | 'added-paths';
  level: 'WARN' | 'INFO';
  api: string;
  path: string;
  was_type?: string;
  consumers: string[];
  message: string;
}

export interface ShapeContract {
  generated_at: string;
  n_runs: number;
  apis: {
    api: string;
    runs: number;
    fields: number;
    refs: number;
    owner_scenarios: string[];
    importance: number;
    category: string;
  }[];
  findings: ShapeFinding[];
}

export interface ParallelSafety {
  generated_at: string;
  totals: {
    scenarios: number;
    readers: number;
    writers: number;
    max_parallelism: number;
    model: string;
  };
  writers: { id: string; title: string; category: string; priority: string; dependents: number; accounts: string[] }[];
  readers: { id: string; title: string; category: string; priority: string; dependents: number; accounts: string[] }[];
}
