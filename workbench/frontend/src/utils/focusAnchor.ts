/** 消息锚点提取（飞书知识图谱二期 T-921）：最近消息最后提及的图谱节点锚点。
 *
 * 识别范围：FR-xxx / AC-数字 / tp:xxx（话题）/ fd:xxx（飞书文档）/ fm:xxx（妙记）。
 * 纯函数，无副作用；无锚点返回空串。
 */

const ANCHOR_RE = /(FR-[A-Za-z0-9_-]+|AC-\d+|tp:[\w-]+|fd:\w+|fm:\w+)/g;

export interface AnchorMessage {
  role: string;
  content: string;
}

export function extractLastAnchor(messages: AnchorMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (!m || typeof m.content !== 'string') continue;
    const hits = m.content.match(ANCHOR_RE);
    if (hits && hits.length > 0) return hits[hits.length - 1];
  }
  return '';
}
