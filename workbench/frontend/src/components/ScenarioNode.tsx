/** ScenarioNode — DAG 画布自定义场景节点（Dify nodes/_base 模式精简版）
 *
 * 显示：类型图标 + 场景 ID + 版本徽章 + 标题（两行截断）
 * 边框颜色：最近一次运行 verdict（PASS 绿 / FAIL 红 / SKIP 黄 / BLOCKED 紫），无则类型色
 * Handle：左 target / 右 source（ELK RIGHT 方向，支撑 onConnect 连线建依赖）
 */
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react';
import { useJsTokens } from '../theme';

export const CATEGORY_META: Record<string, { icon: string; label: string; color: string }> = {
  producer: { icon: '📤', label: '产出', color: '#3fb950' },
  modifier: { icon: '✏️', label: '修改', color: '#f0883e' },
  query: { icon: '🔍', label: '查询', color: '#58a6ff' },
  validator: { icon: '✅', label: '校验', color: '#8957e5' },
};

const VERDICT_COLORS: Record<string, string> = {
  PASS: '#3fb950', FAIL: '#f85149', SKIP: '#d29922', BLOCKED: '#8957e5',
  DRIFT: '#d29922', ORPHANED: '#f85149',
};

export type ScenarioNodeType = Node<{
  label: string;
  title?: string;
  version?: string;
  category?: string;
  verdict?: string;
  isBreakpoint?: boolean;  // T-202：计划断点场景画布标记
  isDraft?: boolean;       // 草稿节点（未入库，AgentChat 会话依赖图用）
}>;

export default function ScenarioNode({ data, selected }: NodeProps<ScenarioNodeType>) {
  const cat = CATEGORY_META[data.category || 'validator'] || CATEGORY_META.validator;
  // 草稿节点固定黄框（区别于库内场景的类型色/verdict 色）
  const borderColor = data.isDraft
    ? '#d29922'
    : ((data.verdict && VERDICT_COLORS[data.verdict]) || cat.color + '66');
  const tokens = useJsTokens();  // K-043：节点配色跟随主题
  return (
    <div
      className="rounded-lg px-2.5 py-2 text-left"
      style={{
        width: 220,
        minHeight: 88,
        background: tokens.nodeBg,
        border: `2px solid ${selected ? '#58a6ff' : borderColor}`,
        color: tokens.nodeText,
        fontSize: 11,
        boxShadow: selected ? '0 0 0 2px rgba(88,166,255,0.25)' : undefined,
      }}
    >
      <Handle type="target" position={Position.Left} style={{ width: 8, height: 8, background: cat.color }} />
      <div className="flex items-center gap-1.5">
        {data.isDraft && (
          <span className="text-[10px]" title="草稿（未入库）">📝</span>
        )}
        <span>{cat.icon}</span>
        <span className="font-mono font-semibold truncate">{data.label}</span>
        {data.isBreakpoint && (
          <span className="text-[10px]" title="计划断点：执行到该场景前暂停">🔴</span>
        )}
        {data.version && (
          <span
            className="ml-auto text-[9px] px-1 py-px rounded font-mono"
            style={{ color: tokens.nodeSubText, background: tokens.nodeSubBg, border: `1px solid ${tokens.edgeStroke}` }}
            title={`契约版本 v${data.version}`}
          >
            v{data.version}
          </span>
        )}
      </div>
      {data.title && (
        <div
          className="mt-1 text-[10px] leading-tight overflow-hidden"
          style={{
            color: tokens.nodeSubText,
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {data.title}
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ width: 8, height: 8, background: cat.color }} />
    </div>
  );
}
