import { describe, it, expect } from 'vitest';
import { buildTrialErrorText } from './trialError';

describe('buildTrialErrorText 试跑失败复制文本', () => {
  it('包含场景/错误/任务号/报告目录（贴给 Agent 即可排查）', () => {
    const text = buildTrialErrorText('HI-PERM-001.yaml', {
      ok: false,
      error: "AttributeError: 'str' object has no attribute 'get'",
      run_id: 'agent_20260826_112704',
      report_dir: 'D:/ws/.specguard/reports/agent_20260826_112704',
    });
    expect(text).toContain('HI-PERM-001.yaml');
    expect(text).toContain("AttributeError: 'str' object has no attribute 'get'");
    expect(text).toContain('任务号：agent_20260826_112704');
    expect(text).toContain('报告：D:/ws/.specguard/reports/agent_20260826_112704');
  });

  it('缺 run_id/report_dir 时不留空行；error 缺失时回退 reason', () => {
    const text = buildTrialErrorText('A.yaml', { ok: false, reason: '测试数据缺失' });
    expect(text).toBe('试跑失败：A.yaml\n错误：测试数据缺失');
  });

  it('error 与 reason 均缺时给未知错误占位', () => {
    const text = buildTrialErrorText('B.yaml', { ok: false });
    expect(text).toContain('未知错误');
  });
});
