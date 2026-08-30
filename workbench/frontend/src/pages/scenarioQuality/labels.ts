// T-1035：测试用例管理页共享徽标/标签映射（页面与详情弹层共用，口径唯一）。
import type { QualityGrade } from '../../api/scenarioQuality';

export const GRADE_LABEL: Record<QualityGrade, string> = {
  deep: '深断言', medium: '中等', shallow: '浅断言', 'no-verify': '无断言',
};
export const GRADE_CLS: Record<QualityGrade, string> = {
  deep: 'bg-pass/12 text-pass',
  medium: 'bg-blue-900/40 text-blue-400',
  shallow: 'bg-warn/12 text-warn',
  'no-verify': 'bg-fail/12 text-fail',
};
export const ISSUE_LABEL: Record<string, string> = {
  'missing-covers': '缺关联需求', 'invalid-covers': '需求锚点失效',
  shallow: '浅断言', 'no-verify': '无断言', probe: '探针',
};
export const ISSUE_CLS: Record<string, string> = {
  'missing-covers': 'bg-warn/12 text-warn',
  'invalid-covers': 'bg-fail/12 text-fail',
  shallow: 'bg-warn/12 text-warn',
  'no-verify': 'bg-fail/12 text-fail',
  probe: 'bg-fail/12 text-fail',
};
// 断言证据：后端从断言内容确定性提取的特征（评级的输入），此处翻译为人话
export const EVIDENCE_LABEL: Record<string, string> = {
  http_ok: '成功状态', http_error: '显式拒绝', body_error_code: '错误码',
  error_message: '错误消息', absent: '不泄露', json_field: '响应字段',
  oracle: 'DB 校对断言器', db_proof: '持久层证据', python: 'Python 脚本',
};
