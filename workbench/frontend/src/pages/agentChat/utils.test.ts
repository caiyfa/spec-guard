import { describe, it, expect } from 'vitest';
import { isToolError, filterTreeSessions, stripRefBlock, resolveViewingFocus } from './utils';

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

describe('filterTreeSessions', () => {
  it('过滤 aux 会话（§B5——辅助会话只活在面板页签）', () => {
    const list = [
      { id: 'a', kind: '' },
      { id: 'b', kind: 'aux' },
      { id: 'c' },
    ] as any[];
    const out = filterTreeSessions(list);
    expect(out.map(s => s.id)).toEqual(['a', 'c']);
  });
});

describe('stripRefBlock 注入块剥离（K-013/T-1031）', () => {
  it('剥离 <references> 块，保留正文（原有语义不变）', () => {
    expect(stripRefBlock('<references>\n--- a.yaml ---\n内容\n</references>\n\n问题')).toBe('问题');
  });

  it('剥离 <parent_context> 块与 [parent_context] 单行降级形态', () => {
    expect(stripRefBlock('<parent_context>\n父会话快照\n</parent_context>\n帮我看看'))
      .toBe('帮我看看');
    expect(stripRefBlock('[parent_context] 主会话自上轮起无变更\n继续')).toBe('继续');
  });

  it('剥离 <knowledge_refs> 知识 nudge 块（T-508 落盘进 user 消息尾部，UI 不显示）', () => {
    const input = '用人和我讲一下 HI-PERM-002 测试的是什么内容'
      + '\n\n<knowledge_refs>\n知识模组提示：<环境叙事 (sit)>（env）：# TDM 系统——SIT 环境叙事\n</knowledge_refs>';
    expect(stripRefBlock(input)).toBe('用人和我讲一下 HI-PERM-002 测试的是什么内容');
  });

  it('多块叠加全剥且不受位置约束', () => {
    const input = '<parent_context>\nA\n</parent_context>'
      + '<viewing_context>用户当前正在查看…HI-PERM-002.yaml…</viewing_context>'
      + '<knowledge_refs>x</knowledge_refs>'
      + '\n讲一下这个文件';
    expect(stripRefBlock(input)).toBe('讲一下这个文件');
  });

  it('无注入块时原样返回', () => {
    expect(stripRefBlock('普通消息')).toBe('普通消息');
  });
});

describe('resolveViewingFocus（验收缺陷 A：最近文件签记忆）', () => {
  const tabs: ReadonlyArray<{ path: string; kind?: 'file' | 'draft' }> =
    [{ path: 'a.yaml' }, { path: 'b/b.md', kind: 'draft' }];

  it('活动签是 file: 时优先取当前', () => {
    expect(resolveViewingFocus('file:a.yaml', '', tabs)).toEqual({ path: 'a.yaml', kind: 'file' });
  });

  it('切到辅助面板提问时回退最近活动的文件签（原实现此处恒 null）', () => {
    expect(resolveViewingFocus('sql_aux', 'file:b/b.md', tabs))
      .toEqual({ path: 'b/b.md', kind: 'draft' });
  });

  it('记忆页签已关闭 / 从未打开过文件签 → 无焦点', () => {
    expect(resolveViewingFocus('sql_aux', 'file:gone.yaml', tabs)).toBeNull();
    expect(resolveViewingFocus('sql_aux', '', tabs)).toBeNull();
    expect(resolveViewingFocus('todos', '', tabs)).toBeNull();
  });
});
