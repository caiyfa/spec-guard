/** scenarioReader — T-1023 结构化阅读视图的纯函数层（vitest 可测）。
 *
 * 从场景 YAML 的解析对象 + 原文提取「给测试人员看」的描述：
 * - unwrapReaderStep：tool 信封 {tool:{use,with,save}} 与裸步骤 {precheck_permission:{...}} 双形态归一
 * - extractSectionComments：行扫描提取 flow/verify 每个顶层步骤上方紧贴的 # 注释块
 *   （js-yaml 丢注释，注释是步骤意图说明，对阅读体验关键；脚本块内部的 #
 *   行缩进更深，靠「注释缩进 ≤ 步骤项缩进」守卫不串行）
 * - describeStep / describeVerify：步骤/断言 → 图标 + 中文类型 + 一行摘要 + 折叠代码
 * - buildAnchorHint：锚点同号歧义排序用的 hint 词来源（文件路径 + id + 标题 + 调用路径）
 */

export interface ReaderStep {
  type: string;
  body: Record<string, unknown>;
}

export interface StepDesc {
  icon: string;
  typeLabel: string;   // 中文类型名（工具调用/接口调用/python 脚本/数据库查询…）
  title: string;       // 一行摘要（工具名 / METHOD path / note…）
  lines: string[];     // 补充参数行（已截断）
  save?: string;
  code?: { lang: string; text: string };
}

export interface VerifyDesc {
  icon: string;
  text: string;        // 友好断言文案
  code?: { lang: string; text: string };
}

// ── 步骤归一 ──

/** tool 信封与裸步骤双形态 → {type, body}（tool 信封的 with/save 平铺进 body） */
export function unwrapReaderStep(step: unknown): ReaderStep {
  if (!step || typeof step !== 'object' || Array.isArray(step)) return { type: 'unknown', body: {} };
  const [type, raw] = Object.entries(step as Record<string, unknown>)[0] || ['unknown', {}];
  const body = (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>;
  if (type === 'tool') {
    const b = body as { use?: string; with?: Record<string, unknown>; save?: unknown };
    if (b.use) {
      return { type: b.use, body: { ...(b.with || {}), ...(b.save ? { save: b.save } : {}) } };
    }
  }
  return { type, body };
}

// ── 注释提取（行扫描，保序对齐顶层步骤项） ──

const TOP_KEY_RE = /^[A-Za-z_][\w]*\s*:/;
const ITEM_RE = /^(\s*)-\s/;
const COMMENT_RE = /^(\s*)#\s?(.*)$/;

/** 提取 flow/verify 段每个顶层步骤项上方紧贴的注释块；返回与步骤项同序的数组（无注释为 ''） */
export function extractSectionComments(rawYaml: string, section: 'flow' | 'verify'): string[] {
  const out: string[] = [];
  const lines = rawYaml.split('\n');
  let inSection = false;
  let itemIndent = -1;
  let pending: string[] = [];
  const sectionRe = new RegExp(`^${section}\\s*:`);

  const flushPending = () => {
    out.push(pending.join('\n').trim());
    pending = [];
  };

  for (const line of lines) {
    if (!inSection) {
      if (sectionRe.test(line)) inSection = true;
      continue;
    }
    if (TOP_KEY_RE.test(line)) break;              // 下一顶层键 = 段结束
    const item = ITEM_RE.exec(line);
    if (item) {
      const indent = item[1].length;
      if (itemIndent === -1) itemIndent = indent;  // 首个步骤项缩进 = 顶层基准
      if (indent === itemIndent) { flushPending(); continue; }
      // 更深缩进的列表项 = 步骤体内嵌套列表（如 json.basicConditions），跳过
      continue;
    }
    const c = COMMENT_RE.exec(line);
    if (c && (itemIndent === -1 || c[1].length <= itemIndent)) {
      pending.push(c[2]);                           // 顶层注释：归入下一步骤
      continue;
    }
    if (line.trim() === '') continue;               // 空行不打断注释块归属判定
    pending = [];                                   // 步骤体行：之前的悬空注释作废
  }
  return out;
}

// ── 步骤描述 ──

const TOOL_LABEL: Record<string, string> = {
  resolve_account: '账号解析',
  precheck_permission: '权限预检',
  fetch_permission: '权限预言',
  select_emp: '选人工号',
  random: '随机数生成',
  set_var: '变量设置',
  oss_upload: 'OSS 上传',
  oss_download: 'OSS 下载',
};

function short(v: unknown, max = 72): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  if (s == null) return '';
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

export function describeStep(step: unknown): StepDesc {
  const { type, body } = unwrapReaderStep(step);
  const save = typeof body.save === 'string' ? body.save : undefined;

  if (type === 'call') {
    const method = String(body.method || 'GET').toUpperCase();
    const path = String(body.path || '');
    const lines: string[] = [];
    if (body.service) lines.push(`服务 ${short(body.service)}`);
    lines.push(`账号 ${short(body.as || 'default')}`);
    const payload: Record<string, unknown> = {};
    for (const k of ['params', 'json', 'data', 'headers']) {
      if (body[k] != null) payload[k] = body[k];
    }
    return {
      icon: '🌐', typeLabel: '接口调用',
      title: `${method} ${path}`,
      lines, save,
      code: Object.keys(payload).length
        ? { lang: 'json', text: JSON.stringify(payload, null, 2) } : undefined,
    };
  }

  if (type === 'python') {
    return {
      icon: '🐍', typeLabel: 'python 脚本',
      title: '内联脚本（数据加工/校验）',
      lines: [], save,
      code: typeof body.script === 'string' ? { lang: 'python', text: body.script } : undefined,
    };
  }

  if (type === 'db_query') {
    return {
      icon: '🗄', typeLabel: '数据库查询',
      title: String(body.note || body.purpose || 'SQL 查询'),
      lines: [], save,
      code: typeof body.sql === 'string' ? { lang: 'sql', text: body.sql } : undefined,
    };
  }

  if (type === 'poll') {
    return {
      icon: '⏳', typeLabel: '轮询等待',
      title: short(body.until || body.path || '条件达成即止'),
      lines: [], save,
      code: { lang: 'json', text: JSON.stringify(body, null, 2) },
    };
  }

  // 工具类（含信封拆解后的领域工具与未识别类型）
  const label = TOOL_LABEL[type] || (type === 'unknown' ? '未识别步骤' : '工具调用');
  const lines = Object.entries(body)
    .filter(([k]) => k !== 'save')
    .map(([k, v]) => `${k}: ${short(v)}`);
  return {
    icon: '🔧', typeLabel: label,
    title: type,
    lines, save,
  };
}

// ── 断言描述 ──

const OP_TEXT: Record<string, (v: unknown) => string> = {
  eq: (v) => `= ${short(v)}`,
  ne: (v) => `≠ ${short(v)}`,
  not_null: () => '非空',
  len_gte: (v) => `长度 ≥ ${short(v)}`,
  len_gt: (v) => `长度 > ${short(v)}`,
  len_eq: (v) => `长度 = ${short(v)}`,
  contains: (v) => `包含 ${short(v)}`,
};

export function describeVerify(item: unknown): VerifyDesc {
  if (!item || typeof item !== 'object' || Array.isArray(item)) {
    return { icon: '•', text: short(item) };
  }
  const [kind, raw] = Object.entries(item as Record<string, unknown>)[0] || ['', {}];
  const body = (raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {}) as Record<string, unknown>;
  const of = body.of != null ? `（${short(body.of, 24)}）` : '';

  if (kind === 'status') {
    return { icon: '📡', text: `HTTP 状态 = ${short(body.eq)}${of}` };
  }
  if (kind === 'json') {
    const path = String(body.path || '');
    const ops = Object.entries(body)
      .filter(([k]) => k !== 'of' && k !== 'path')
      .map(([k, v]) => (OP_TEXT[k] ? OP_TEXT[k](v) : `${k} ${short(v)}`))
      .join('，');
    return { icon: '🔍', text: `${path} ${ops}${of}` };
  }
  if (kind === 'oracle') {
    const name = String(body.name || body.use || 'oracle');
    const params = Object.entries(body).filter(([k]) => k !== 'name' && k !== 'use');
    return {
      icon: '🛡', text: `DB 校对：${name}`,
      code: params.length
        ? { lang: 'json', text: JSON.stringify(Object.fromEntries(params), null, 2) }
        : undefined,
    };
  }
  if (kind === 'python') {
    return {
      icon: '🐍', text: '脚本断言',
      code: typeof body.script === 'string' ? { lang: 'python', text: body.script } : undefined,
    };
  }
  return { icon: '•', text: `${kind} ${short(raw)}` };
}

// ── 锚点 hint ──

/** 锚点同号歧义排序 hint：文件路径 + 场景 id/标题 + flow 中 call 的 service/method/path */
export function buildAnchorHint(data: Record<string, unknown>, filePath?: string): string {
  const parts: string[] = [];
  if (filePath) parts.push(filePath);
  if (typeof data.id === 'string') parts.push(data.id);
  if (typeof data.title === 'string') parts.push(data.title);
  const flow = Array.isArray(data.flow) ? data.flow : [];
  for (const s of flow) {
    const { type, body } = unwrapReaderStep(s);
    if (type === 'call') {
      for (const k of ['service', 'method', 'path']) {
        if (typeof body[k] === 'string') parts.push(body[k] as string);
      }
    }
  }
  return parts.join(' ');
}

/** 场景 YAML 判定：解析结果为对象且含 flow(数组) + doc(对象) */
export function isScenarioDoc(data: unknown): data is Record<string, unknown> {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false;
  const d = data as Record<string, unknown>;
  return Array.isArray(d.flow) && !!d.doc && typeof d.doc === 'object' && !Array.isArray(d.doc);
}
