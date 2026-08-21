// 对话操作台面板（GateDock 一期）：聚合当前会话上下文的待办闸门卡片。
// 二期（T-901）起卡片渲染复用 components/GateCardView（与对话流内嵌卡同一组件）。
// 人点按钮直调原有 REST + RBAC（后端写接口零改动）；「🤖 帮我」L1 引导由父组件注入。

import { useCallback, useEffect, useState } from 'react';
import { specflowApi, type GateCard, type GateDockResp } from '../api';
import GateCardView from '../components/GateCardView';
import MaterialsPanel from './MaterialsPanel';
import ScoreFreezePanel from './ScoreFreezePanel';
import ZentaoPanel from './ZentaoPanel';

// T-996 菜单收缩：材料管理/评分冻结/禅道集成 收操作台子页签（原独立菜单页）
const GATE_TABS = [
  { id: 'gates', label: '🎛 闸门' },
  { id: 'materials', label: '📦 材料' },
  { id: 'scores', label: '⚖️ 评分冻结' },
  { id: 'zentao', label: '🐞 禅道' },
] as const;
type GateTab = typeof GATE_TABS[number]['id'];

interface Props {
  sessionId: string;
  onAskAgent: (card: GateCard) => void;
  onError: (msg: string) => void;
}

export default function GateDockPanel({ sessionId, onAskAgent, onError }: Props) {
  const [tab, setTab] = useState<GateTab>(() => {
    const saved = localStorage.getItem('sg_gatedock_tab');
    return (GATE_TABS.some(t => t.id === saved) ? saved : 'gates') as GateTab;
  });
  useEffect(() => { localStorage.setItem('sg_gatedock_tab', tab); }, [tab]);
  const [interview, setInterview] = useState<GateDockResp['interview']>(null);
  const [cards, setCards] = useState<GateCard[]>([]);
  const [loading, setLoading] = useState(false);

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
    } catch (e: any) {
      onError(`操作台加载失败: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }, [sessionId, onError]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="flex flex-col h-full">
      {/* 子页签条（闸门/材料/评分冻结/禅道） */}
      <div className="flex gap-1 px-1 py-1 border-b border-border/50 flex-shrink-0">
        {GATE_TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-2 py-1 text-[11px] rounded ${tab === t.id ? 'bg-info/15 text-info' : 'text-gray-500 hover:text-gray-300'}`}>
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'materials' && <MaterialsPanel />}
        {tab === 'scores' && <ScoreFreezePanel />}
        {tab === 'zentao' && <ZentaoPanel />}
        {tab === 'gates' && (
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

      {/* 闸门卡片（动作执行后 reload 保持与后端一致） */}
      {cards.map(c => (
        <GateCardView key={`${c.kind}:${c.ref_id}`} card={c}
          onAskAgent={onAskAgent} onDone={load} onError={onError} />
      ))}
    </div>
        )}
      </div>
    </div>
  );
}
