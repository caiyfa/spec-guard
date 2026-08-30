// T-1035 v2.1：用例试跑 = 执行准备面板——环境就绪度一屏可见 + 参数微调，然后联网执行。
// 复用 RunControl 既有件：runsApi.trigger/accounts/preflight（T-311/T-312 同款）
// + useRunStream 实时进度 + TrialRunDetailModal 完整报告（与正式执行同一落盘面）。
// T-1039：执行环境下拉（env.{name}.yaml 枚举，nacos 启用时 load_env 内部 nacos 优先）
// + 账号三档语义：试跑手动输入 > 按权限自动解析（runsApi.resolveAccount 探针）> 固定配置。
// covers 前置闸（全库级，服务端判定不可绕过）：锚点失效时进面板即预警并指路，
// 不让用户点了才开始失败。引擎语义开关（仅准备/上游不断言/严格依赖）不在此暴露，
// 需要时走「测试执行」页（RunControl）。

import { useEffect, useMemo, useState } from 'react';
import Modal from '../../components/Modal';
import { TrialRunDetailModal } from '../../components/TrialRunDetailModal';
import { useRunStream } from '../../hooks/useRunStream';
import { runsApi } from '../../api';
import type { AccountResolution, PreflightResult, TrialRunResult } from '../../api';
import type { ScenarioQualityRow } from '../../api/scenarioQuality';

// 账号选择哨兵值：固定配置 / 按权限自动解析 / 手动输入（其余值 = 配置别名，K-056 语义）
const ACCOUNT_CONFIG = '__config__';
const ACCOUNT_AUTO = '__auto__';
const ACCOUNT_MANUAL = '__manual__';

interface Props {
  scenarioId: string;
  scenarios: ScenarioQualityRow[];   // 全库（depends_on 反算上下游闭包）
  anchorsAvailable: boolean;         // 当前工作区锚点表是否可用
  invalidCoversCount: number;        // 全库「需求锚点失效」用例数（>0 时 covers 闸拦截一切触发）
  onClose: () => void;
}

export default function ScenarioRunDialog({ scenarioId, scenarios, anchorsAvailable, invalidCoversCount, onClose }: Props) {
  // ── 链路闭包（客户端确定性计算，与引擎 depends_on 图同源）──
  const { upstream, downstream } = useMemo(() => {
    const ups = new Map<string, string[]>();
    const downs = new Map<string, string[]>();
    for (const s of scenarios) {
      for (const d of s.depends_on) {
        ups.set(s.id, [...(ups.get(s.id) || []), d.id]);
        downs.set(d.id, [...(downs.get(d.id) || []), s.id]);
      }
    }
    const bfs = (start: string, map: Map<string, string[]>) => {
      const seen = new Set<string>();
      const stack = [start];
      while (stack.length) {
        const cur = stack.pop()!;
        for (const n of map.get(cur) || []) {
          if (n !== start && !seen.has(n)) { seen.add(n); stack.push(n); }
        }
      }
      return [...seen].sort();
    };
    return { upstream: bfs(scenarioId, ups), downstream: bfs(scenarioId, downs) };
  }, [scenarios, scenarioId]);

  const coversBlocked = anchorsAvailable && invalidCoversCount > 0;

  const [withDownstream, setWithDownstream] = useState(false);
  // T-1039：执行环境（下拉切换；'' = 尚未拉到清单，用后端默认）
  const [envName, setEnvName] = useState('');
  const [envs, setEnvs] = useState<{ name: string; ok: boolean; source: string; error: string }[]>([]);
  // T-1039：账号三档（配置默认 / 按权限自动解析 / 手动输入 / 具体别名）
  const [accountSel, setAccountSel] = useState(ACCOUNT_CONFIG);
  const [manualAccount, setManualAccount] = useState('');
  const [resolution, setResolution] = useState<AccountResolution | null>(null);
  const [resolving, setResolving] = useState(false);
  const [accounts, setAccounts] = useState<Record<string, { ad: string; emp_no: string; type: string }>>({});
  const [configSource, setConfigSource] = useState('');
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [overrideInputs, setOverrideInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [triggerError, setTriggerError] = useState('');
  const [queued, setQueued] = useState('');
  const [runId, setRunId] = useState('');
  const [finished, setFinished] = useState(false);
  const [showReport, setShowReport] = useState(false);

  // 执行目标：含下游时展开为 "A or B"（上游闭包由引擎依赖调度默认连带）
  const targetIds = useMemo(
    () => (withDownstream ? [scenarioId, ...downstream] : [scenarioId]),
    [withDownstream, scenarioId, downstream]);
  // 预检范围：目标 + 上游闭包（缺失账号/env 键要连准备链一起扫）
  const preflightIds = useMemo(
    () => [...new Set([...targetIds, ...upstream])],
    [targetIds, upstream]);

  // 环境清单（T-1039）：env.{name}.yaml 枚举；失败诚实回退 'sit'（不空白不卡加载）
  useEffect(() => {
    runsApi.envs()
      .then(r => {
        setEnvs(r.envs || []);
        const names = (r.envs || []).map(e => e.name);
        if (r.default && names.includes(r.default)) setEnvName(r.default);
        else if (names.length) setEnvName(names[0]);
        else setEnvName(n => n || 'sit');
      })
      .catch(() => { setEnvs([]); setEnvName(n => n || 'sit'); });
  }, []);

  // 账号随环境联动（T-1039）：环境就位后再拉一次（避免 '' → 默认值 双拉闪变）
  useEffect(() => {
    if (!envName) return;
    runsApi.accounts(envName)
      .then(r => {
        setAccounts(r.accounts || {});
        setConfigSource(r.source || '');
      })
      .catch(() => setAccounts({}));
  }, [envName]);

  useEffect(() => {
    if (!envName) return;
    let alive = true;
    setPreflightLoading(true);
    runsApi.preflight(preflightIds, envName)
      .then(r => { if (alive) setPreflight(r); })
      .catch(() => { if (alive) setPreflight(null); })
      .finally(() => { if (alive) setPreflightLoading(false); });
    return () => { alive = false; };
  }, [preflightIds, envName]);

  // 自动档（T-1039）：按权限解析 default 账号——探针联网（SSO + hr-center），数秒级
  useEffect(() => {
    if (accountSel !== ACCOUNT_AUTO || !envName) { setResolution(null); setResolving(false); return; }
    let alive = true;
    setResolving(true);
    runsApi.resolveAccount(preflightIds, envName)
      .then(r => { if (alive) setResolution(r); })
      .catch(() => { if (alive) setResolution(null); })
      .finally(() => { if (alive) setResolving(false); });
    return () => { alive = false; };
  }, [accountSel, envName, preflightIds]);

  // ── 进度：全局 run 事件流过滤本 run ──
  const { events } = useRunStream();
  const runEvents = useMemo(() => events.filter(e => e.run_id === runId), [events, runId]);
  useEffect(() => {
    if (runId && runEvents.some(e => e.type === 'finished' || e.type === 'aborted')) {
      setFinished(true);
    }
  }, [runEvents, runId]);
  const progressLines = runEvents.filter(e => e.type === 'output' && e.line).slice(-8);

  const collectOverrides = () =>
    Object.entries(overrideInputs)
      .filter(([, v]) => v.trim() !== '')
      .map(([k, v]) => {
        const sep = k.indexOf('::');
        return { kind: k.slice(0, sep), name: k.slice(sep + 2), value: v.trim() };
      });

  const startRun = async () => {
    setBusy(true);
    setTriggerError('');
    // T-1039 账号三档落地：
    //   手动输入/自动解析 → SG_OVERRIDES account::default（试跑输入优先级最高，
    //   conftest apply_overrides 替换 default 别名配置）；固定别名 → K-056 重映射；
    //   配置默认 → 不传，conftest 原样生效。显式别名（no_access 等）永不被替换。
    const overrides = collectOverrides();
    let accountOverride: string | undefined;
    if (accountSel === ACCOUNT_MANUAL && manualAccount.trim()) {
      overrides.push({ kind: 'account', name: 'default', value: manualAccount.trim() });
    } else if (accountSel === ACCOUNT_AUTO && resolution?.override_value) {
      overrides.push({ kind: 'account', name: 'default', value: resolution.override_value });
    } else if (accountSel !== ACCOUNT_CONFIG && accountSel !== ACCOUNT_AUTO && accountSel !== ACCOUNT_MANUAL) {
      accountOverride = accountSel;
    }
    try {
      const r = await runsApi.trigger('scenario', targetIds.join(' or '), envName || 'sit', [],
        { accountOverride }, overrides);
      if (r.queued) setQueued(`已有执行在进行，本次已排队（第 ${r.position ?? '?'} 位）`);
      if (r.run_id) setRunId(r.run_id);
    } catch (e: any) {
      const msg = typeof e.message === 'string' ? e.message : '';
      setTriggerError(msg.includes('covers')
        ? 'covers 校验未通过（全库存在需求锚点失效的用例）——切换到与用例库同世代的工作区后重试'
        : (msg || '触发失败'));
    } finally {
      setBusy(false);
    }
  };

  const startDisabled = busy || coversBlocked
    || (accountSel === ACCOUNT_MANUAL && !manualAccount.trim());

  const trialResult: TrialRunResult = { ok: true, run_id: runId, target: targetIds.join(' or ') };

  return (
    <Modal open onClose={onClose} width={620} title={`试跑 ${scenarioId} · 执行准备`}>
      {/* covers 前置闸预警（全库级，服务端判定；不满足时不必点开始才知道失败） */}
      {coversBlocked && (
        <div className="mb-3 p-3 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
          <div>⛔ covers 前置闸将拦截本次触发：当前用例库有 <b>{invalidCoversCount}</b> 个用例的需求锚点
            在当前工作区查不到（全库级校验，任一失效即拦截所有触发）。</div>
          <div className="mt-1 text-fs-body">
            处置：① 顶栏切换到与用例库同世代的工作区（如「干部盘点 (TDM)」）后重试；
            ② 或修复用例的 covers 标签（见用例详情「需求锚点失效」标记）。
          </div>
        </div>
      )}

      {/* 链路范围 */}
      <div className="text-sm mb-3">
        <div className="text-fs-body text-gray-500 mb-1.5">链路范围</div>
        <label className="flex items-center gap-2 py-0.5 cursor-pointer">
          <input type="radio" checked={!withDownstream} onChange={() => setWithDownstream(false)} />
          <span>本用例 + 上游准备链
            <span className="text-fs-body text-gray-500 ml-1">
              {upstream.length ? `（连带 ${upstream.length} 个上游）` : '（无上游）'}
            </span>
          </span>
        </label>
        <label className="flex items-center gap-2 py-0.5 cursor-pointer">
          <input type="radio" checked={withDownstream} onChange={() => setWithDownstream(true)} />
          <span>上下链路一起跑
            <span className="text-fs-body text-gray-500 ml-1"
              title={downstream.join('、') || undefined}>
              （上游 {upstream.length} + 下游 {downstream.length}）
            </span>
          </span>
        </label>
        {upstream.length > 0 && (
          <div className="text-fs-body text-gray-600 mt-0.5">上游闭包：{upstream.join('、')}</div>
        )}
        {withDownstream && downstream.length > 0 && (
          <div className="text-fs-body text-gray-600 mt-0.5">下游消费方：{downstream.join('、')}</div>
        )}
      </div>

      {/* 执行环境：环境切换 + 账号三档 + 就绪度 + 参数微调 */}
      <div className="text-sm mb-3">
        <div className="text-fs-body text-gray-500 mb-1.5">执行环境</div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mb-2">
          <span className="flex items-center gap-1.5">
            <span className="text-fs-body text-gray-500">环境</span>
            <select value={envName} disabled={!!runId}
              onChange={e => setEnvName(e.target.value)}
              className="input text-sm"
              title="执行环境（env.{name}.yaml）；Nacos 启用时配置优先从配置中心取（T-1036 单收点）">
              {(envs.length ? envs : [{ name: envName || 'sit', ok: true, source: '', error: '' }])
                .map(e => (
                  <option key={e.name} value={e.name} disabled={!e.ok}>
                    {e.name}{e.ok ? '' : `（加载失败：${e.error.slice(0, 40)}）`}
                  </option>
                ))}
            </select>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="text-fs-body text-gray-500">执行账号</span>
            <select value={accountSel} disabled={!!runId}
              onChange={e => setAccountSel(e.target.value)}
              className="input text-sm"
              title="优先级：手动输入 / 按权限解析 > 固定配置；显式别名（如 no_access）保留配置语义">
              <option value={ACCOUNT_CONFIG}>默认（配置账号）</option>
              <option value={ACCOUNT_AUTO}>自动（按权限解析）</option>
              <option value={ACCOUNT_MANUAL}>手动输入…</option>
              {Object.entries(accounts).filter(([alias]) => alias !== 'default').map(([alias, cfg]) => (
                <option key={alias} value={alias}>{alias}（{cfg.ad || cfg.emp_no || alias}）</option>
              ))}
            </select>
          </span>
          {configSource && (
            <span className="text-fs-body text-gray-400"
              title="当前环境的配置来源（T-1036）：nacos 表示统一管理配置中心，file 表示本地 env yaml；降级时已 WARN">
              配置源：{configSource.startsWith('nacos') ? 'Nacos' : '本地文件'}
              {configSource.startsWith('nacos') && `（${configSource.slice('nacos:'.length)}）`}
              {configSource.includes('降级') && <span className="text-warn">（已降级）</span>}
            </span>
          )}
          {!preflightLoading && preflight && !preflight.has_gaps && (
            <span className="text-fs-body text-pass"
              title={`账号：${(preflight.accounts || []).join('、') || '—'}｜环境键：${(preflight.env_keys || []).join('、') || '—'}`}>
              ✅ 依赖就绪（账号 {preflight.accounts?.length ?? 0} · 环境键 {preflight.env_keys?.length ?? 0}）
            </span>
          )}
          {preflightLoading && <span className="text-fs-body text-gray-500">扫描中…</span>}
        </div>

        {/* 手动输入档（T-1039）：自由账号替换 default 别名，仅本次执行生效 */}
        {accountSel === ACCOUNT_MANUAL && (
          <div className="mb-2">
            <input
              value={manualAccount}
              onChange={e => setManualAccount(e.target.value)}
              placeholder="AD 账号 或 AD:工号（替换 default 别名，仅本次执行生效）"
              className="w-full bg-surface-3 border border-border rounded px-2 py-1 text-fs-body font-mono text-gray-200 focus:border-info outline-none" />
            <div className="text-fs-body text-gray-600 mt-0.5">
              场景中 <code>as: default</code> 及未声明账号的步骤将以该账号执行；显式别名（如 no_access）保留配置语义。
            </div>
          </div>
        )}

        {/* 自动档（T-1039）：按权限解析——探针矩阵 + 匹配结果 + 诚实回退说明 */}
        {accountSel === ACCOUNT_AUTO && (
          <div className="mb-2 px-2 py-1.5 bg-surface-1 border border-border rounded space-y-1 text-fs-body">
            {resolving && <div className="text-gray-500">🔍 探针中…（SSO 登录 + hr-center 权限查询，数秒）</div>}
            {!resolving && !resolution && <div className="text-warn">解析失败（网络/服务异常）——将按固定配置账号执行</div>}
            {!resolving && resolution && (
              <>
                {Object.keys(resolution.requirements).length > 0 && (
                  <div className="text-gray-400">
                    权限需求：
                    <span className="font-mono">
                      {Object.entries(resolution.requirements)
                        .map(([a, codes]) => `${a} → ${codes.join('、')}`)
                        .join('；')}
                    </span>
                  </div>
                )}
                {resolution.unresolved.map(u => (
                  <div key={u} className="text-warn">🔗 {u}（运行期按实际插值处理）</div>
                ))}
                {resolution.errors.map(e => (
                  <div key={e} className="text-fail">⚠ {e}</div>
                ))}
                {resolution.candidates.length > 0 && (
                  <table className="w-full text-fs-body">
                    <thead>
                      <tr className="text-gray-500">
                        <th className="text-left font-normal py-0.5">候选</th>
                        {Object.keys(resolution.candidates[0]?.probe || {}).map(c => (
                          <th key={c} className="text-left font-normal py-0.5 font-mono">{c}</th>
                        ))}
                        <th className="text-left font-normal py-0.5">结果</th>
                      </tr>
                    </thead>
                    <tbody>
                      {resolution.candidates.map(c => (
                        <tr key={c.alias}>
                          <td className="py-0.5">{c.alias}（{c.ad}:{c.emp_no}）</td>
                          {Object.keys(resolution.candidates[0]?.probe || {}).map(code => (
                            <td key={code} className="py-0.5"
                              title={c.probe[code]?.summary || c.probe[code]?.status || ''}>
                              {c.probe[code]?.has_any ? '✅' : (c.probe[code] ? '❌' : '—')}
                            </td>
                          ))}
                          <td className="py-0.5">
                            {c.matched
                              ? <span className="text-pass">✅ 匹配</span>
                              : <span className="text-gray-500">不满足</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {resolution.matched && (
                  <div className="text-pass">
                    ✅ 本次试跑 default 别名以 <b>{resolution.matched.ad}</b>（{resolution.matched.emp_no}）执行
                  </div>
                )}
                {resolution.reason && (
                  <div className="text-warn">{resolution.reason}</div>
                )}
              </>
            )}
          </div>
        )}

        {/* 参数微调：预检缺失项就地填写（T-312 同款，只本次执行生效） */}
        {preflight && preflight.has_gaps && (
          <div className="px-2 py-1.5 bg-fail/5 border border-fail/30 rounded space-y-1.5 max-h-36 overflow-y-auto">
            <div className="text-fs-body text-gray-500">以下缺失项就地填写，仅对本次执行生效（不改配置文件）：</div>
            {preflight.missing_accounts.map(g => (
              <div key={g.account} className="text-fs-body">
                <div className="text-fail">
                  🔑 账号 <span className="font-mono">{g.account}</span> 未配置
                  <span className="text-gray-500">（{g.scenarios.join('、')} → 将 SKIP）</span>
                </div>
                <input
                  value={overrideInputs[`account::${g.account}`] || ''}
                  onChange={e => setOverrideInputs(prev => ({ ...prev, [`account::${g.account}`]: e.target.value }))}
                  placeholder="输入 AD 账号（或 ad:工号）替代配置"
                  className="mt-0.5 w-full bg-surface-3 border border-border rounded px-2 py-0.5 text-fs-body font-mono text-gray-200 focus:border-info outline-none" />
              </div>
            ))}
            {preflight.missing_env.map(g => (
              <div key={g.key} className="text-fs-body">
                <div className="text-warn">🌐 环境键 <span className="font-mono">{g.key}</span> 缺失</div>
                <input
                  value={overrideInputs[`env::${g.key}`] || ''}
                  onChange={e => setOverrideInputs(prev => ({ ...prev, [`env::${g.key}`]: e.target.value }))}
                  placeholder={`输入 ${g.key} 的值`}
                  className="mt-0.5 w-full bg-surface-3 border border-border rounded px-2 py-0.5 text-fs-body font-mono text-gray-200 focus:border-info outline-none" />
              </div>
            ))}
            {preflight.unresolved_upstream.map(g => (
              <div key={g.ref} className="text-fs-body text-warn">
                🔗 跨场景引用 <span className="font-mono">{g.ref}</span> 不在本次依赖闭包（{g.scenarios.join('、')}）
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 触发与进度 */}
      {triggerError && (
        <div className="mb-3 p-2.5 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
          ❌ 试跑触发失败：{triggerError}
        </div>
      )}
      {queued && <div className="mb-3 text-sm text-warn">⏳ {queued}</div>}
      {runId && (
        <div className="mb-3">
          <div className="text-sm mb-1">
            任务号 <span className="font-mono text-info">{runId}</span>
            <span className={`ml-2 text-fs-body ${finished ? 'text-pass' : 'text-warn'}`}>
              {finished ? '● 已完成' : '● 执行中…'}
            </span>
          </div>
          {progressLines.length > 0 && (
            <div className="bg-surface-1 border border-border rounded p-2 max-h-32 overflow-y-auto">
              {progressLines.map((l, i) => (
                <div key={i} className="text-fs-body font-mono text-gray-400 whitespace-pre-wrap">{l.line}</div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center justify-end gap-2">
        {finished && runId && (
          <button className="btn-primary text-sm" onClick={() => setShowReport(true)}>
            查看完整报告
          </button>
        )}
        {!runId ? (
          <button className="btn-primary text-sm" onClick={startRun}
            disabled={startDisabled}
            title={coversBlocked
              ? 'covers 前置闸未通过——按上方提示处置后重试'
              : (accountSel === ACCOUNT_MANUAL && !manualAccount.trim()
                ? '手动输入档需填写账号（AD 或 AD:工号）'
                : undefined)}>
            {busy ? '触发中…' : '▶ 开始试跑（联网执行）'}
          </button>
        ) : (
          <button className="btn-ghost text-sm" onClick={onClose}>关闭</button>
        )}
      </div>

      {showReport && runId && (
        <TrialRunDetailModal trial={trialResult} onClose={() => setShowReport(false)} />
      )}
    </Modal>
  );
}
