/** TodoPanel — 待办面板组件（H-FE）
 *
 * 显示 Agent 的任务待办列表，支持两种数据源：
 * 1. 结构化待办（todo_update 事件）：{id, title, status, mode}
 * 2. 遗留计划项（<plan> 标签）：string[]
 *
 * 结构化待办优先展示，无结构化待办时回退到计划项。
 */

export interface StructuredTodo {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'done' | 'blocked';
  mode?: string;
}

export interface TodoPanelProps {
  todos: StructuredTodo[];      // 结构化待办（todo_update 事件）
  planItems: string[];           // 遗留计划项（<plan> 标签）
  loading: boolean;
}

const STATUS_ICONS: Record<string, string> = {
  done: '✅',
  in_progress: '🔄',
  blocked: '⛔',
  pending: '○',
};

const STATUS_COLORS: Record<string, string> = {
  done: 'text-gray-600 line-through',
  in_progress: 'text-yellow-400',
  blocked: 'text-fail',
  pending: 'text-gray-400',
};

export default function TodoPanel({ todos, planItems, loading }: TodoPanelProps) {
  // 优先使用结构化待办，无则回退到计划项
  const hasStructured = todos.length > 0;

  return (
    <>
      <div className="px-3 py-2 border-b border-border">
        <span className="text-fs-body font-medium text-gray-300">📋 待办</span>
        {loading && <span className="text-fs-aux text-gray-600 ml-2 animate-pulse">执行中…</span>}
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {hasStructured ? (
          // 结构化待办渲染（K-023 去模式化：不再按模式分组/高亮）
          todos.map((todo, i) => {
            const icon = STATUS_ICONS[todo.status] || '○';
            const color = STATUS_COLORS[todo.status] || 'text-gray-400';

            return (
              <div
                key={todo.id || i}
                className={`text-fs-body flex items-start gap-1.5 ${color} ${
                  todo.status === 'in_progress' ? 'bg-yellow-500/5 rounded px-1 -mx-1' : ''
                }`}
              >
                <span className="flex-shrink-0 mt-0.5">{icon}</span>
                <div className="flex-1 min-w-0">
                  <div>{todo.title}</div>
                </div>
              </div>
            );
          })
        ) : (
          // 遗留计划项渲染
          planItems.map((item, i) => {
            const isLLMDone = item.includes('✅');
            const isInferredDone = false; // 结构化模式下不推断
            const isDone = isLLMDone || isInferredDone;
            const isCurrent = !isDone && i === 0 && loading;

            return (
              <div
                key={i}
                className={`text-fs-body flex items-start gap-1.5 ${
                  isDone ? 'text-gray-600 line-through' : isCurrent ? 'text-yellow-400' : 'text-gray-400'
                }`}
              >
                <span className="flex-shrink-0 mt-0.5">
                  {isDone ? '✅' : isCurrent ? '🔵' : '○'}
                </span>
                <span>{item.replace(/^✅\s*/, '').replace(/^\d+\.\s*/, '')}</span>
              </div>
            );
          })
        )}
        {!hasStructured && planItems.length === 0 && (
          <div className="text-fs-body text-gray-600 text-center py-2">
            {loading ? '模型正在分析任务…' : '暂无待办'}
          </div>
        )}
      </div>
    </>
  );
}
