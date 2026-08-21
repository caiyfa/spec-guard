import type { ArtifactInfo, ChatMessage, GroupedItem } from './types';
import { firstMdTitle, stripPlan, tryParseJson } from './utils';

// ── 默认计划（K-023 去模式化：统一任务骨架）+ 工具→步骤映射 ──
// K-xxx：DEFAULT_PLANS 仅作「工具调用分组锚点」（groupMessages 把工具归到步骤展示），
// 不再预填待办区——待办由模型 todo_write / <plan> 输出，避免「刚发消息就出写死待办」
// 后半段为编排/验证类工具的分组锚点（dag-orchestration 技能链路）
const DEFAULT_PLANS: string[] = [
  '读取基础信息包和需求文档',
  '查询注册表（tool / oracle）',
  '参考已有场景结构',
  '获取场景 ID',
  '生成场景 YAML',
  '校验场景',
  '写入草稿',
  '分析依赖建议',
  '落地依赖边',
  'DAG 复核',
  '试执行验证',
  'DB 证据查询',
];

// 工具名 → 待办步骤序号映射（供 groupMessages 把工具调用归到对应步骤展示）
const TOOL_TO_STEP: Record<string, number> = {
  // T-982：合并工具按 "name.action" 键映射；legacy 名保留（历史会话回放兼容）
  'info_pack.read': 0, 'spec.read': 0, 'spec.list': 0,
  read_info_pack: 0, read_spec: 0, list_spec_files: 0,
  query_registry: 1,
  'scenario.list': 2, 'scenario.read': 2,
  list_scenarios: 2, read_scenario: 2,
  'scenario.next_id': 3,
  next_scenario_id: 3,
  validate: 5,
  'draft.write': 6, 'draft.promote': 6, 'draft.promote_batch': 6, 'draft.undo': 6,
  write_draft: 6, promote_draft: 6, promote_drafts: 6,
  'info_pack.add': 0,
  add_to_info_pack: 0,
  undo_draft: 6,
  // 归因/调试类工具 → DB 证据查询步骤
  'attribution.report': 11, 'attribution.db': 11, 'attribution.log': 11,
  'attribution.failures': 11, 'attribution.executions': 11,
  read_run_report: 11, db_evidence: 11, read_run_log: 11,
  list_failures: 11, list_executions: 11,
  // K-xxx：DAG 编排链路分组锚点
  'scenario.suggest_deps': 7,
  suggest_deps: 7,
  'scenario.edit': 8,
  edit_dependency: 8,
  'scenario.check_dag': 9,
  check_dag: 9,
  'scenario.run': 10,
  run_scenario: 10,
};

// T-982：合并工具查步骤用 "name.action" 键（无 action 或历史会话 legacy 名直接命中）
function toolStepKey(tc: { function: { name: string; arguments: string } }): string {
  const n = tc.function.name;
  try {
    const a = JSON.parse(tc.function.arguments)?.action;
    if (a && `${n}.${a}` in TOOL_TO_STEP) return `${n}.${a}`;
  } catch { /* 参数解析失败按工具名查 */ }
  return n;
}

// T-982：draft 合并工具按 action 判定写/撤销（兼容历史会话 write_draft/undo_draft 名）
export function draftWriteUndo(name: string, args: Record<string, unknown> | null): 'write' | 'undo' | null {
  if (name === 'write_draft') return 'write';
  if (name === 'undo_draft') return 'undo';
  if (name === 'draft' && (args?.action === 'write' || args?.action === 'undo')) return args.action as 'write' | 'undo';
  return null;
}

// ── 将扁平消息列表分组（按待办步骤关联 + 完成提示） ──
export function groupMessages(messages: ChatMessage[]): GroupedItem[] {
  const groups: GroupedItem[] = [];
  let currentToolGroup: GroupedItem | null = null;
  let lastStepIdx = -1;  // 上一个工具组对应的步骤索引

  // 产物卡片口径与右侧草稿产物区一致（sessionDrafts 同源）：undo_draft 后卡片不再出现
  const liveDrafts = new Set<string>();
  for (const m of messages) {
    if (m.role !== 'assistant' || !m.tool_calls) continue;
    for (const tc of m.tool_calls) {
      try {
        const args = JSON.parse(tc.function.arguments);
        const da = draftWriteUndo(tc.function.name, args);  // T-982：draft action 判定
        if (da === 'write' && args.filename) liveDrafts.add(args.filename);
        else if (da === 'undo' && args.filename) liveDrafts.delete(args.filename);
      } catch { /* 参数解析失败忽略 */ }
    }
  }

  const flushToolGroup = () => {
    if (currentToolGroup) {
      groups.push(currentToolGroup);
      // 如果该步骤所有工具都已完成，插入步骤完成提示
      if (currentToolGroup.stepIdx !== undefined && currentToolGroup.stepIdx > lastStepIdx) {
        const allDone = (currentToolGroup.tools || []).every(t => t.result !== undefined);
        if (allDone && currentToolGroup.stepLabel) {
          groups.push({ type: 'step-complete', content: currentToolGroup.stepLabel, stepIdx: currentToolGroup.stepIdx });
          lastStepIdx = currentToolGroup.stepIdx;
        }
      }
      // write_draft 产物卡片（独立于折叠工具组常驻可见，点击右侧页签预览）
      const artifacts: ArtifactInfo[] = [];
      for (const t of currentToolGroup.tools || []) {
        const args = tryParseJson(t.args);
        if (draftWriteUndo(t.name, args) !== 'write' || !t.result) continue;  // T-982
        const res = tryParseJson(t.result);
        const fn = args?.filename;
        if (!fn || !liveDrafts.has(fn) || res?.ok === false) continue;
        const content = typeof args?.content === 'string' ? args.content : '';
        const isYaml = /\.ya?ml$/i.test(fn);
        artifacts.push({
          fileName: fn,
          title: (content && firstMdTitle(content)) || fn,
          size: typeof res?.size === 'number' ? res.size : undefined,
          content: isYaml ? undefined : content || undefined,  // 非 yaml 产物走内容预览
        });
      }
      if (artifacts.length) groups.push({ type: 'artifact', artifacts });
      currentToolGroup = null;
    }
  };

  for (let mi = 0; mi < messages.length; mi++) {
    const msg = messages[mi];
    if (msg.role === 'system') continue;

    if (msg.role === 'user') {
      flushToolGroup();
      groups.push({ type: 'user', content: msg.content, references: msg.references, msgIdx: mi });
    } else if (msg.role === 'assistant') {
      if (msg.tool_calls && msg.tool_calls.length > 0) {
        const cleanContent = msg.content ? stripPlan(msg.content) : '';
        // K-024：思考文本提升为独立可见气泡——此前塞进 tools[0].assistantText 藏进
        // 折叠的工具组（工具跑完用户只剩一行「7/7 工具」，完全看不到为什么调用；
        // 生产会话取证：100 轮带思考文本的工具调用全部不可见）
        if (cleanContent) {
          flushToolGroup();  // 保证时序：上一工具组 → 思考 → 新工具组
          groups.push({ type: 'assistant-text', content: cleanContent, thought: true });
        }
        // 根据第一个工具名推断步骤
        const stepIdx = TOOL_TO_STEP[toolStepKey(msg.tool_calls[0])];  // T-982：name.action 键
        const stepLabel = stepIdx !== undefined ? DEFAULT_PLANS[stepIdx] : undefined;
        // 如果步骤变化了，先 flush 上一组
        if (currentToolGroup && stepIdx !== undefined && currentToolGroup.stepIdx !== undefined && stepIdx !== currentToolGroup.stepIdx) {
          flushToolGroup();
        }
        if (!currentToolGroup) currentToolGroup = { type: 'tool-group', tools: [], stepIdx, stepLabel };
        // 如果新组的 stepIdx 更高，更新（可能同一步骤多次调用）
        if (stepIdx !== undefined && (currentToolGroup.stepIdx === undefined || stepIdx > currentToolGroup.stepIdx)) {
          currentToolGroup.stepIdx = stepIdx;
          currentToolGroup.stepLabel = DEFAULT_PLANS[stepIdx];
        }
        for (let i = 0; i < msg.tool_calls.length; i++) {
          currentToolGroup.tools!.push({
            name: msg.tool_calls[i].function.name,
            args: msg.tool_calls[i].function.arguments,
          });
        }
      } else {
        flushToolGroup();
        const cleanContent = msg.content ? stripPlan(msg.content) : '';
        if (cleanContent) {
          groups.push({ type: 'assistant-text', content: cleanContent });
        }
      }
    } else if (msg.role === 'tool') {
      if (currentToolGroup && currentToolGroup.tools!.length > 0) {
        for (let i = currentToolGroup.tools!.length - 1; i >= 0; i--) {
          if (!currentToolGroup.tools![i].result) {
            currentToolGroup.tools![i].result = msg.content;
            break;
          }
        }
      }
    }
  }
  flushToolGroup();
  return groups;
}
