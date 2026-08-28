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
  flow_summary: string[];    // flow 步骤一行式人话描述
  verify_summary: string[];  // verify 断言一行式人话描述
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
};
