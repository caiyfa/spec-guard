import type { DocHunk } from '../../components/FileViewer';

export interface ChatReference {
  type: 'info_pack' | 'file' | 'draft' | 'material';
  path: string;          // file=相对路径 / draft=文件名 / info_pack=SG-META-xxxx / material=MAT-xxx
  sha: string;           // 引用时的内容指纹（info_pack 为 ""）
  label?: string;        // K-015: 展示名（信息包为场景名，材料为文件名；持久化 refs 无此字段时回退 path）
  missing?: boolean;
}

export interface ChatMessage {
  role: string;
  content: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
  reasoning_content?: string;
  references?: ChatReference[];  // K-013: @引用（持久化在 user 消息上）
}

export interface AgentStats {
  total_tokens?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  elapsed_time?: number;
  tps?: number;
  is_mock?: boolean;
  model?: string;
  cache_hits?: number;
  cache_misses?: number;
}

// ── 上下文用量（per-turn，来自 LLM API usage） ──
export interface CtxUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

// ── 模型上下文窗口默认值 ──
export const DEFAULT_CTX_LIMIT = 128000;

// ── 消息分组类型 ──
export interface ToolItem {
  name: string;
  args: string;
  result?: string;
}
// ── 会话产物（write_draft 落盘文件 / 大段 markdown 文档），对话流内可点击预览 ──
export interface ArtifactInfo {
  title: string;       // 卡片主标题（md 首标题；fallback 文件名）
  fileName?: string;   // 已落盘文件名（yaml 点击开草稿预览；非 yaml 需带 content 走内容预览——draftsApi 仅支持 yaml）
  size?: number;       // 字节数（write_draft 结果真实字节）
  lines?: number;      // 行数（代码块卡片）
  content?: string;    // 未落盘/非 yaml 内容（点击开 memo: 内容预览页签）
  formatLabel?: string; // 无 fileName 时的格式标签（如 Markdown）
}
export interface GroupedItem {
  type: 'user' | 'assistant-text' | 'tool-group' | 'step-complete' | 'artifact';
  content?: string;
  tools?: ToolItem[];
  stepLabel?: string;   // 关联的待办步骤名称
  stepIdx?: number;    // 步骤索引
  thought?: boolean;    // K-024: 工具调用前的思考文本（轻量样式，常驻可见）
  references?: ChatReference[];  // K-013: user 消息携带的 @引用
  artifacts?: ArtifactInfo[];    // 产物卡片（工具组之后，独立于折叠组常驻可见）
  msgIdx?: number;     // 在 messages[] 中的索引（用于撤回定位）
}

// ── 更新足迹（S0.6：写型工具 doc_write 事件汇聚，与阅读足迹对称） ──
export interface DocWriteItem {
  key: string;
  tool: string;
  ref: string;
  path: string | null;
  turn: number;
  size: number;
  excerpt: string;
  label: string;
  thinking: string;
  verdict: string | null;   // PASS/REJECT/SKIP/ERROR（conformance/门禁确定性结果）
  findings: { level: string; rule: string; message: string }[];  // 校验失败原因（与 verdict 同源，Agent 据此修复）
  hunks: DocHunk[];
  writes: number;           // 同文件累计更新次数
}

export interface FileTab {
  path: string;
  kind: 'file' | 'draft';
  content: string;
  format?: 'raw' | 'markdown' | 'text';
  loading: boolean;
  hunks?: DocHunk[];  // T-511：阅读足迹打开时携带的使用位置（行区间定位+高亮）
}

// 用途标题兜底映射（页面刷新后 purposes 列表为空时 badge 仍可显示；新用途在 purposes 动态命中）
export const PURPOSE_TITLE_FALLBACK: Record<string, string> = {
  test_workbench: '测试工作台',
  requirement_interview: '产品工作台',
};
