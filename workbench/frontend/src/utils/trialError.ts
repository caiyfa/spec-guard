import type { TrialRunResult } from '../api';

/** 试跑失败复制文本（一键复制后贴给 Agent 即可排查：场景 + 错误 + 任务号 + 报告目录） */
export function buildTrialErrorText(target: string, trial: TrialRunResult): string {
  const lines = [
    `试跑失败：${target}`,
    `错误：${trial.error || trial.reason || '未知错误'}`,
  ];
  if (trial.run_id) lines.push(`任务号：${trial.run_id}`);
  if (trial.report_dir) lines.push(`报告：${trial.report_dir}`);
  return lines.join('\n');
}
