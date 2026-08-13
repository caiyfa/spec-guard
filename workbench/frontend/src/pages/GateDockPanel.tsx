// 对话操作台面板（GateDock 一期）：聚合当前会话上下文的待办闸门卡片。
// 人点按钮直调原有 REST + RBAC（后端写接口零改动）；
// 「🤖 帮我」为 L1 引导（Agent 解释 + 指导），由父组件注入回调。
// 分档接管：L2 卡（评分/冻结/禅道）永远人拍板；L3 卡（入包/议题）为可代执行白名单。

import { useCallback, useEffect, useState } from 'react';
import {
  specflowApi,
  zentaoApi,
  type GateCard,
  type GateDockResp,
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
const btn = 'px-2.5 py-1 rounded text-[11px] font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40 disabled:cursor-not-allowed';
const btnOk = 'px-2.5 py-1 rounded text-[11px] font-medium bg-green-500/15 text-green-400 hover:bg-green-500/25 disabled:opacity-40 disabled:cursor-not-allowed';
const btnDanger = 'px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/15 text-red-400 hover:bg-red-500/25 disabled:opacity-40 disabled:cursor-not-allowed';

interface Props {
  sessionId: string;
  onAskAgent: (card: GateCard) => void;
  onError: (msg: string) => void;
}

export default function GateDockPanel({ sessionId, onAskAgent, onError }: Props) {
  const [interview, setInterview] = useState<GateDockResp['interview']>(null);
  const [cards, setCards] = useState<GateCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');        // 正在执行的按钮 key（防连点）
  const [storyTitle, setStoryTitle] = useState('');  // 禅道建故事标题（L2 预填可改）

  const load = useCallback(async () => {
    if (!sessionId) {
      setInterview(null);
      setCards([]);
      return;
    }
    setLoading(true);
    try {
      const r = await specflowApi.gateDock({ session_id: sessionId });
      setInterview(r.interview);
      setCards(r.cards);
      const storyCard = r.cards.find(c => c.kind === 'zentao_story');
      if (storyCard && !storyTitle) {
        setStoryTitle(storyCard.payload?.suggested_title || '');
      }
    } catch (e: any) {
      onError(`操作台加载失败: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }, [sessionId, onError, storyTitle]);

  useEffect(() => { load(); }, [load]);

  // 人拍板动作统一入口：执行 → 刷新（卡片消失/状态变化即反馈）
  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    try {
      await fn();
      await load();
    } catch (e: any) {
      onError(`操作失败: ${e?.message || e}`);
    } finally {
      setBusy('');
    }
  };

  // ── 各卡片动作区（按 kind 渲染，payload 由后端 gate-dock 供给）──
  const renderActions = (c: GateCard) => {
    const p = c.payload || {};
    switch (c.kind) {
      case 'topic_confirm':
        return (
          <div className="space-y-1">
            {(p.topics || []).map((t: any) => (
              <div key={t.tid} className="flex items-center gap-1.5 text-[11px]">
                <span className="text-gray-300 flex-1 truncate" title={t.summary}>○ {t.title}</span>
                <button className={btn} disabled={!!busy}
                  onClick={() => run(`topic:${t.tid}`,
                    () => specflowApi.confirmTopic(p.mid, t.tid, true))}>
                  {busy === `topic:${t.tid}` ? '…' : '确认'}
                </button>
              </div>
            ))}
          </div>
        );
      case 'material_include':
        return (
          <button className={btnOk} disabled={!!busy}
            onClick={() => run(`include:${p.mid}`,
              () => specflowApi.includeMaterial(p.iv_id, p.mid, true))}>
            {busy === `include:${p.mid}` ? '…' : '📥 入包'}
          </button>
        );
      case 'score_confirm':
        return (
          <div className="space-y-1">
            {(p.scores || []).map((s: any) => (
              <div key={s.id} className="flex items-center gap-1.5 text-[11px]">
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
                    className={`text-[10px] px-1.5 py-0.5 rounded border ${
                      st === 'pass'
                        ? 'text-green-400 border-green-500/40'
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
              className="flex-1 bg-surface-3 border border-border rounded px-2 py-1 text-[11px] text-gray-200 outline-none focus:border-info" />
            <button className={btnOk} disabled={!!busy || !storyTitle.trim()}
              title="从冻结 delta 创建禅道故事（product 角色，幂等防重）"
              onClick={() => run(`story:${p.delta_id}`,
                () => zentaoApi.createStory(p.delta_id, storyTitle.trim()))}>
              {busy === `story:${p.delta_id}` ? '…' : '🔗 建故事'}
            </button>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="p-2 space-y-2">
      {/* 上下文标头 */}
      <div className="flex items-center justify-between px-1">
        <div className="text-[11px] text-gray-500 truncate">
          {interview
            ? <>🎯 <span className="font-mono text-info">{interview.iv_id}</span> · {interview.title}
                <span className="text-gray-600">（{interview.status}）</span></>
            : '当前会话未绑定需求面试'}
        </div>
        <button onClick={load} disabled={loading}
          className="text-[10px] text-gray-600 hover:text-info flex-shrink-0">
          {loading ? '加载中…' : '刷新'}
        </button>
      </div>

      {/* 空态 */}
      {!loading && interview && cards.length === 0 && (
        <div className="text-xs text-gray-600 text-center py-6">
          当前无待办闸门——材料/评分/冻结/禅道均已就位
        </div>
      )}
      {!loading && !interview && (
        <div className="text-xs text-gray-600 text-center py-6 space-y-1">
          <div>操作台跟随需求面试会话工作</div>
          <div className="text-[10px] text-gray-700">在产品工作台开标后，此处聚合材料/评分/冻结/禅道待办</div>
        </div>
      )}

      {/* 闸门卡片 */}
      {cards.map(c => (
        <div key={`${c.kind}:${c.ref_id}`} className={cardCls}>
          <div className="flex items-center gap-1.5 mb-1">
            <span>{KIND_ICON[c.kind] || '🔧'}</span>
            <span className="text-xs font-medium text-gray-200 flex-1 truncate">{c.title}</span>
            <span className={`text-[9px] px-1 py-0.5 rounded border ${
              c.level === 'L3'
                ? 'text-green-400 border-green-500/40'
                : 'text-yellow-400 border-yellow-500/40'}`}
              title={c.level === 'L3'
                ? '可逆低危操作（代执行白名单）'
                : '定性决策：Agent 可引导/预填，最后一下永远人点'}>
              {c.level === 'L3' ? '可代执行' : '人拍板'}
            </span>
            <button onClick={() => onAskAgent(c)}
              title="让 Agent 解释此闸门并指导操作（L1 引导，不代执行）"
              className="text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20">
              🤖 帮我
            </button>
          </div>
          <div className="text-[11px] text-gray-500 mb-2">{c.summary}
            <span className="text-gray-700 font-mono"> · {c.ref_id}</span>
          </div>
          {renderActions(c)}
        </div>
      ))}
    </div>
  );
}
