import { describe, it, expect } from 'vitest';
import { isToolError } from './utils';

describe('isToolError 工具结果语义判错', () => {
  // 回归用例：会话 20260824_172320_84d21cfa，spec sync 返回 ok:true 但
  // 旧子串匹配命中 summary 里的 "error": 0 计数键，被误标执行失败
  it('ok:true 带 error 计数键不误判', () => {
    const specSync = JSON.stringify({
      ok: true, old_commit: 'ed013d', new_commit: 'e46964', changed: true,
      report: { verdict: 'PASS', summary: { error: 0, warn: 8, info: 0 }, findings: [] },
    });
    expect(isToolError(specSync)).toBe(false);
  });

  it('ok:false 判错', () => {
    expect(isToolError(JSON.stringify({ ok: false, error: '场景不存在' }))).toBe(true);
    expect(isToolError(JSON.stringify({ ok: false, error_code: 'edit_failed' }))).toBe(true);
  });

  it('verdict 报告：PASS/WARN 通过，REJECT/ERROR 失败', () => {
    expect(isToolError(JSON.stringify({ verdict: 'PASS', findings: [] }))).toBe(false);
    expect(isToolError(JSON.stringify({ verdict: 'WARN', findings: [] }))).toBe(false);
    expect(isToolError(JSON.stringify({ verdict: 'REJECT', findings: [] }))).toBe(true);
    expect(isToolError(JSON.stringify({ verdict: 'ERROR', findings: [] }))).toBe(true);
  });

  it('无协议字段的 JSON：顶层 error 非空值判错，计数 0 不判', () => {
    expect(isToolError(JSON.stringify({ error: 'boom' }))).toBe(true);
    expect(isToolError(JSON.stringify({ error: 0 }))).toBe(false);
    expect(isToolError(JSON.stringify({ id: 'PP-RC-008' }))).toBe(false);
  });

  it('纯文本结果保留启发式：ERROR/❌ 判错，普通文本不判', () => {
    expect(isToolError('ERROR: 连接超时')).toBe(true);
    expect(isToolError('执行失败 ❌')).toBe(true);
    expect(isToolError('清单如下，共 3 项')).toBe(false);
    expect(isToolError('warn 8 info 0')).toBe(false);
  });
});
