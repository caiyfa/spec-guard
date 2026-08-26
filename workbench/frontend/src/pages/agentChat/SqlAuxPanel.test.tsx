/** SqlAuxPanel 单测：parent_context 剥离（快照注入块是 LLM 上下文，UI 不显示）。 */
import { describe, expect, test } from 'vitest';
import { stripParentContext } from './SqlAuxPanel';

describe('stripParentContext', () => {
  test('剥离 <parent_context> 块，保留用户正文', () => {
    const input = '<parent_context>\n父会话 xxx 最新快照：\n- 最新草稿文件: a.sql\n</parent_context>\n帮我改 SQL';
    expect(stripParentContext(input)).toBe('帮我改 SQL');
  });

  test('剥离 [parent_context] 单行降级形态', () => {
    const input = '[parent_context] 主会话自上轮起无变更\n帮我改 SQL';
    expect(stripParentContext(input)).toBe('帮我改 SQL');
  });

  test('无注入块时原样返回', () => {
    expect(stripParentContext('普通消息')).toBe('普通消息');
  });

  test('多个块叠加全剥', () => {
    const input = '<parent_context>\nA\n</parent_context>\n[parent_context] 无变更\n正文';
    expect(stripParentContext(input)).toBe('正文');
  });
});
