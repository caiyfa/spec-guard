import { describe, expect, it } from 'vitest';
import { isShortReply } from './MessageWithToolbar';

// 工具调用后收尾短句降级判定（生产取证：会话 20260826_185503_0cdb0988 两次「等你的拍板 ⏳」）
describe('isShortReply 短收尾句判定', () => {
  it('工具后收尾短句判定为轻量', () => {
    expect(isShortReply('等你的拍板 ⏳')).toBe(true);
    expect(isShortReply('OK，我马上处理')).toBe(true);
    expect(isShortReply('待你确认后继续。')).toBe(true);
  });

  it('空内容不降级', () => {
    expect(isShortReply('')).toBe(false);
    expect(isShortReply('   \n  ')).toBe(false);
  });

  it('多行内容不降级（正式文档特征）', () => {
    expect(isShortReply('好的。\n马上处理。')).toBe(false);
  });

  it('超长单行不降级，阈值边界内降级', () => {
    expect(isShortReply('a'.repeat(41))).toBe(false);
    expect(isShortReply('a'.repeat(40))).toBe(true);
  });

  it('块级 Markdown 语法开头不降级（即使很短）', () => {
    expect(isShortReply('## 标题')).toBe(false);
    expect(isShortReply('- 待办项')).toBe(false);
    expect(isShortReply('* 强调列表')).toBe(false);
    expect(isShortReply('1. 第一步')).toBe(false);
    expect(isShortReply('1) 第一步')).toBe(false);
    expect(isShortReply('> 引用一句')).toBe(false);
    expect(isShortReply('| a | b |')).toBe(false);
    expect(isShortReply('```text')).toBe(false);
  });

  it('普通技术短句不受块级误伤（不以语法标记开头）', () => {
    expect(isShortReply('fr-005 校对完成，diff 为空')).toBe(true);
    expect(isShortReply('场景已写入 drafts/')).toBe(true);
  });
});
