// GateDock 前端族（二期 T-901 / 三期 T-902）：
// - GateCardView：单张闸门卡片（操作台页签与对话流内嵌共用，同一组件两种容器）
// - GateExecCard：Agent 代执行确认卡（gate-exec 围栏渲染；白名单硬编码，用户确认才执行）
// 硬边界：L2 卡（评分/冻结/禅道写）永远人拍板；gate-exec 白名单仅三个可逆低危 action。

import { useState } from 'react';
import {
  specflowApi,
  zentaoApi,
  type GateCard,
} from '../api';

const KIND_ICON: Record<string, string> = {
  topic_confirm: '🗳',
  material_include: '📦',
  score_confirm: '📊',
  freeze_gates: '🧊',
  zentao_story: '🔗',
};

const GATE_LABEL: Record<string, string> = {
  product_confirm: '① 产品确认',
  conformance: '② specstd 合规',
  p0_zero: '③ P0 清零',
};

const DIM_LABEL: Record<string, string> = {
  logic: '逻辑完整性',
  coverage: '覆盖率',
  boundary: '边界异常',
  precondition: '前置条件',
  clarity: '预期清晰度',
};

const cardCls = 'bg-surface-1 border border-border rounded-lg p-3';
const btn = 'px-2.5 py-1 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40 disabled:cursor-not-allowed';
const btnOk = 'px-2.5 py-1 rounded text-fs-body font-medium bg-pass/15 text-pass hover:bg-pass/25 disabled:opacity-40 disabled:cursor-not-allowed';
const btnDanger = 'px-2 py-0.5 rounded text-fs-aux font-medium bg-fail/15 text-fail hover:bg-fail/25 disabled:opacity-40 disabled:cursor-not-allowed';

// ══════════════════════════════════════════════════════════
// GateCardView：单张闸门卡片（人拍板按钮直调原有 REST + RBAC）
// ══════════════════════════════════════════════════════════

export interface GateCardViewProps {
  card: GateCard;
  onAskAgent?: (card: GateCard) => void;  // 「🤖 帮我」L1 引导（父组件注入对话回调）
  onDone?: () => void;                     // 动作完成后回调（操作台列表刷新）
  onError?: (msg: string) => void;
}

export default function GateCardView({ card: c, onAskAgent, onDone, onError }: GateCardViewProps) {
  const [busy, setBusy] = useState('');
  const [done, setDone] = useState('');       // 完成标记（消息内嵌卡不回撤，给正反馈）
  const [storyTitle, setStoryTitle] = useState(c.payload?.suggested_title || '');

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      setDone(key);
      onDone?.();
    } catch (e: any) {
      onError?.(`操作失败: ${e?.message || e}`);
    } finally {
      setBusy('');
    }
  };

  const p = c.payload || {};
  const renderActions = () => {
    switch (c.kind) {
      case 'topic_confirm':
        return (
          <div className="space-y-1">
            {(p.topics || []).map((t: any) => (
              <div key={t.tid} className="flex items-center gap-1.5 text-fs-body">
                <span className="text-gray-300 flex-1 truncate" title={t.summary}>○ {t.title}</span>
                <button className={btn} disabled={!!busy}
                  onClick={() => run(`topic:${t.tid}`,
                    () => specflowApi.confirmTopic(p.mid, t.tid, true))}>
                  {busy === `topic:${t.tid}` ? '…' : done === `topic:${t.tid}` ? '✓' : '确认'}
                </button>
              </div>
            ))}
          </div>
        );
      case 'material_include':
        return (
          <button className={btnOk} disabled={!!busy || !!done}
            onClick={() => run(`include:${p.mid}`,
              () => specflowApi.includeMaterial(p.iv_id, p.mid, true))}>
            {busy ? '…' : done ? '✓ 已入包' : '📥 入包'}
          </button>
        );
      case 'score_confirm':
        return (
          <div className="space-y-1">
            {(p.scores || []).map((s: any) => (
              <div key={s.id} className="flex items-center gap-1.5 text-fs-body">
                <span className="text-gray-300 flex-1 truncate" title={s.evidence}>
                  {DIM_LABEL[s.dimension] || s.dimension} · {s.score} 分
                  <span className="text-gray-600">（{s.source}）</span>
                </span>
                <button className={btn} disabled={!!busy}
                  onClick={() => run(`score:${s.id}:ok`,
                    () => specflowApi.confirmScore(s.id, 'confirm'))}>✓</button>
                <button className={btnDanger} disabled={!!busy}
                  onClick={() => run(`score:${s.id}:no`,
                    () => specflowApi.confirmScore(s.id, 'reject'))}>✗</button>
              </div>
            ))}
          </div>
        );
      case 'freeze_gates': {
        const gates = p.gates || {};
        return (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 flex-wrap">
              {Object.entries(GATE_LABEL).map(([k, label]) => {
                const st = gates[k]?.status || '-';
                return (
                  <span key={k}
                    className={`text-fs-aux px-1.5 py-0.5 rounded border ${
                      st === 'pass'
                        ? 'text-pass border-pass/35'
                        : 'text-gray-500 border-border'}`}>
                    {label} {st === 'pass' ? '✓' : '·'}
                  </span>
                );
              })}
            </div>
            <div className="flex items-center gap-1.5 flex-wrap">
              <button className={btn} disabled={!!busy || gates.product_confirm?.status === 'pass'}
                title="闸① 产品确认（product 角色）"
                onClick={() => run(`g1:${p.delta_id}`,
                  () => specflowApi.gate1Confirm(p.delta_id, p.iv_id))}>① 产品确认</button>
              <button className={btn} disabled={!!busy}
                title="闸② specstd 合规校验（确定性纯读）"
                onClick={() => run(`g2:${p.delta_id}`,
                  () => specflowApi.gate2Conformance(p.delta_id))}>② 合规校验</button>
              {p.freeze_allowed && (
                <button className={btnOk} disabled={!!busy}
                  title="三闸全过，执行冻结（product 角色）"
                  onClick={() => run(`freeze:${p.delta_id}`,
                    () => specflowApi.freezeDelta(p.delta_id, p.iv_id))}>❄ 执行冻结</button>
              )}
            </div>
          </div>
        );
      }
      case 'zentao_story':
        return (
          <div className="flex items-center gap-1.5">
            <input value={storyTitle} onChange={e => setStoryTitle(e.target.value)}
              placeholder="故事标题（可改）"
              className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-fs-body text-gray-200 outline-none focus:border-info" />
            <button className={btnOk} disabled={!!busy || !storyTitle.trim() || !!done}
              title="从冻结 delta 创建禅道故事（product 角色，幂等防重）"
              onClick={() => run(`story:${p.delta_id}`,
                () => zentaoApi.createStory(p.delta_id, storyTitle.trim()))}>
              {busy ? '…' : done ? '✓ 已提交' : '🔗 建故事'}
            </button>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className={cardCls}>
      <div className="flex items-center gap-1.5 mb-1">
        <span>{KIND_ICON[c.kind] || '🔧'}</span>
        <span className="text-fs-body font-medium text-gray-200 flex-1 truncate">{c.title}</span>
        <span className={`text-fs-micro px-1 py-0.5 rounded border ${
          c.level === 'L3'
            ? 'text-pass border-pass/35'
            : 'text-warn border-yellow-500/40'}`}
          title={c.level === 'L3'
            ? '可逆低危操作（代执行白名单）'
            : '定性决策：Agent 可引导/预填，最后一下永远人点'}>
          {c.level === 'L3' ? '可代执行' : '人拍板'}
        </span>
        {onAskAgent && (
          <button onClick={() => onAskAgent(c)}
            title="让 Agent 解释此闸门并指导操作（L1 引导，不代执行）"
            className="text-fs-aux px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20">
            🤖 帮我
          </button>
        )}
      </div>
      <div className="text-fs-body text-gray-500 mb-2">{c.summary}
        <span className="text-gray-700 font-mono"> · {c.ref_id}</span>
      </div>
      {renderActions()}
    </div>
  );
}

// ══════════════════════════════════════════════════════════
// GateExecCard：Agent 代执行确认卡（gate-exec 围栏渲染，三期 T-902）
// 白名单硬编码——扩缩需评审（比照引擎冻结层语义变更流程）；
// 前端确定性拒绝白名单外 action，用户点「确认执行」才真正调原 REST。
// ══════════════════════════════════════════════════════════

interface ExecAction {
  describe: (p: Record<string, any>) => string;
  run: (p: Record<string, any>) => Promise<unknown>;
}

export const GATE_EXEC_ACTIONS: Record<string, ExecAction> = {
  material_include: {
    describe: p => `材料入包：${p.mid || ''}`,
    run: p => specflowApi.includeMaterial(p.iv_id, p.mid, true),
  },
  material_exclude: {
    describe: p => `材料移出信息包：${p.mid || ''}`,
    run: p => specflowApi.includeMaterial(p.iv_id, p.mid, false),
  },
  topic_confirm: {
    describe: p => `议题候选确认：${p.tid || ''}`,
    run: p => specflowApi.confirmTopic(p.mid, p.tid, true),
  },
};

export function GateExecCard({ text, onDone }: { text: string; onDone?: () => void }) {
  const [state, setState] = useState<'pending' | 'running' | 'ok' | 'failed' | 'dismissed'>('pending');
  const [result, setResult] = useState('');

  let parsed: { action?: string } & Record<string, any> = {};
  let parseError = '';
  try {
    parsed = JSON.parse(text);
  } catch {
    parseError = 'gate-exec 围栏 JSON 解析失败';
  }
  const { action = '', ...params } = parsed;
  const spec = action ? GATE_EXEC_ACTIONS[action] : undefined;

  if (parseError) {
    return <div className={`${cardCls} border-fail/35/40 text-fs-body text-fail`}>⚠ {parseError}</div>;
  }
  if (!spec) {
    // 白名单外 action：确定性拒绝，不执行（分档接管边界）
    return (
      <div className={`${cardCls} border-yellow-500/40`}>
        <div className="text-fs-body text-warn">
          🚫 Agent 提议的代执行「{action || '(缺 action)'}」不在白名单内——已拦截。
        </div>
        <div className="text-fs-aux text-gray-500 mt-1">
          代执行仅限可逆低危操作（材料入包/移出、议题确认）；该操作请在操作台手动拍板。
        </div>
      </div>
    );
  }

  const doExec = async () => {
    setState('running');
    try {
      await spec.run(params);
      setState('ok');
      setResult('已执行（以用户身份调原有接口，权限由 RBAC 兜底）');
      onDone?.();
    } catch (e: any) {
      setState('failed');
      setResult(`执行失败: ${e?.message || e}`);
    }
  };

  return (
    <div className={`${cardCls} border-info/40`}>
      <div className="flex items-center gap-1.5 mb-1">
        <span>🤖</span>
        <span className="text-fs-body font-medium text-gray-200 flex-1">Agent 代执行提议（可逆操作）</span>
        <span className="text-fs-micro px-1 py-0.5 rounded border text-pass border-pass/35">L3 白名单</span>
      </div>
      <div className="text-fs-body text-gray-400 mb-2">{spec.describe(params)}</div>
      {state === 'pending' && (
        <div className="flex items-center gap-1.5">
          <button className={btnOk} onClick={doExec}>✓ 确认执行</button>
          <button className={btn} onClick={() => setState('dismissed')}>忽略</button>
        </div>
      )}
      {state === 'running' && <div className="text-fs-body text-gray-500">执行中…</div>}
      {state === 'ok' && <div className="text-fs-body text-pass">✓ {result}</div>}
      {state === 'failed' && <div className="text-fs-body text-fail">✗ {result}</div>}
      {state === 'dismissed' && <div className="text-fs-body text-gray-600">已忽略（未执行任何操作）</div>}
    </div>
  );
}
