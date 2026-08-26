// ChatMessageView.test.ts — T-1016 merge_forward 内层解析纯函数测试
import { describe, expect, it } from 'vitest';
import { parseForwardedMessages } from './ChatMessageView';

// 契约形状与 test_specstd/feishu_cli_contract.py MERGE_FORWARD_MESSAGE 同源
// （2026-08-26 实测落盘，结构原样、条数裁剪为 3 条）。
const CONTENT = `<forwarded_messages>
[2026-08-21T15:29:08+08:00] 曹怡华:
    @蔡云飞 蔡老师，这个应该怎么处理呀
    ![Image](img_v3_0214p_a8cd9662-24ff-4113-a552-61e3fed37b1g)
[2026-08-21T15:30:48+08:00] 蔡云飞:
    <p>@曹怡华 文件名的问题</p>
[2026-08-21T15:31:40+08:00] 蔡云飞:
    [Image: img_v3_0214p_b5659d96-eb78-4eb9-b7c6-e6c035afa3ag]
</forwarded_messages>`;

describe('parseForwardedMessages（T-1016 merge_forward 内层解析）', () => {
  it('头行+缩进内容行 → 结构化子消息（<p> 剥离、多行 join）', () => {
    const subs = parseForwardedMessages(CONTENT);
    expect(subs).toHaveLength(3);
    expect(subs[0].sender).toBe('曹怡华');
    expect(subs[0].ts).toBe('2026-08-21T15:29:08+08:00');
    expect(subs[0].text).toContain('蔡老师');
    // <p> 段落标签剥离
    expect(subs[1].text).toBe('@曹怡华 文件名的问题');
  });

  it('内嵌图两种占位（![Image](key) / [Image: key]）按出现顺序提取 keys', () => {
    const subs = parseForwardedMessages(CONTENT);
    expect(subs[0].keys).toEqual(['img_v3_0214p_a8cd9662-24ff-4113-a552-61e3fed37b1g']);
    expect(subs[1].keys).toEqual([]);
    expect(subs[2].keys).toEqual(['img_v3_0214p_b5659d96-eb78-4eb9-b7c6-e6c035afa3ag']);
  });

  it('非 forwarded 包裹内容 → 空数组（调用方兜底原文）', () => {
    expect(parseForwardedMessages('普通文本')).toEqual([]);
    expect(parseForwardedMessages('')).toEqual([]);
  });
});
