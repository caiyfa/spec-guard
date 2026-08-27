/** SqlAuxPanel 单测（T-1031）：注入块剥离改走共享 stripRefBlock（utils）——
 * 剥离用例本体迁至 utils.test.ts，此处保留面板视角的回归锚点。 */
import { describe, expect, test } from 'vitest';
import { stripRefBlock } from './utils';

describe('辅助助手面板消息剥离（原 stripParentContext 语义并入共享工具）', () => {
  test('用户气泡正文剥离 <parent_context> 快照块', () => {
    const input = '<parent_context>\n父会话 xxx 最新快照：\n- 主会话产出的草稿: a.sql\n</parent_context>\n帮我改 SQL';
    expect(stripRefBlock(input)).toBe('帮我改 SQL');
  });

  test('剥离 [parent_context] 单行降级形态', () => {
    const input = '[parent_context] 主会话自上轮起无变更\n帮我改 SQL';
    expect(stripRefBlock(input)).toBe('帮我改 SQL');
  });

  test('无注入块时原样返回', () => {
    expect(stripRefBlock('普通消息')).toBe('普通消息');
  });

  test('<viewing_context> 查看指针块同样不进 UI', () => {
    const input = '<viewing_context>\n用户当前正在主界面查看主会话草稿（drafts/ 区）：HI-PERM-002.yaml\n</viewing_context>\n讲一下 HI-PERM-002';
    expect(stripRefBlock(input)).toBe('讲一下 HI-PERM-002');
  });
});
