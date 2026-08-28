// T-1035 v2：用例详情弹层——结构化查看/编辑（ScenarioFormEditor 三模式）+ 试跑入口。
// 编辑复用 DagEditor 同款通道（PUT /api/scenarios/{id}，RBAC tester+）；
// registries 懒加载同 DraftFormEditor 装配模式；保存成功后父页强制重扫质量数据。

import { useCallback, useEffect, useState } from 'react';
import Modal from '../../components/Modal';
import ScenarioFormEditor from '../../components/ScenarioFormEditor';
import { referenceApi, scenariosApi } from '../../api';
import type { EmpRole, EnvVar, OracleRef, UpstreamVar } from '../../api';
import type { ScenarioQualityRow } from '../../api/scenarioQuality';
import { EVIDENCE_LABEL, GRADE_CLS, GRADE_LABEL, ISSUE_CLS, ISSUE_LABEL } from './labels';
import ScenarioRunDialog from './ScenarioRunDialog';

interface Props {
  row: ScenarioQualityRow;                       // 列表行（徽标/关联需求/语义直接复用）
  scenarios: ScenarioQualityRow[];               // 全库（试跑对话框算上下游闭包）
  anchorsAvailable: boolean;                     // 当前工作区锚点表可用性（试跑 covers 预警）
  invalidCoversCount: number;                    // 全库锚点失效数（>0 时试跑被 covers 闸拦截）
  canRun: boolean;                               // role ∈ admin/tester（与后端 RBAC 一致）
  onClose: () => void;
  onSaved: () => void;                           // 保存成功 → 父页 refresh(true)
}

export default function ScenarioDetailModal({ row, scenarios, anchorsAvailable, invalidCoversCount, canRun, onClose, onSaved }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [savedFlash, setSavedFlash] = useState(false);
  const [showRun, setShowRun] = useState(false);
  const [empRoles, setEmpRoles] = useState<EmpRole[]>([]);
  const [oracles, setOracles] = useState<OracleRef[]>([]);
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [upstreamVars, setUpstreamVars] = useState<UpstreamVar[]>([]);

  useEffect(() => {
    let alive = true;
    setContent(null);
    setError('');
    scenariosApi.get(row.id)
      .then(r => { if (alive) setContent(r.content); })
      .catch(e => { if (alive) setError(e.message || '加载失败'); });
    return () => { alive = false; };
  }, [row.id]);

  useEffect(() => {
    referenceApi.empRoles().then(setEmpRoles).catch(() => {});
    referenceApi.oracles().then(setOracles).catch(() => {});
    referenceApi.envVars().then(setEnvVars).catch(() => {});
    referenceApi.upstreamVars(row.id).then(setUpstreamVars).catch(() => setUpstreamVars([]));
  }, [row.id]);

  const handleSave = useCallback(async (yaml: string) => {
    await scenariosApi.save(row.id, yaml);  // 失败抛错 → 编辑器错误条呈现（403/校验不通过如实上屏）
    setContent(yaml);
    setSavedFlash(true);
    setTimeout(() => setSavedFlash(false), 2000);
    onSaved();
  }, [row.id, onSaved]);

  const doc = row.doc_summary;
  const hasDoc = doc.given || doc.when || doc.then;

  return (
    <Modal open onClose={onClose} width={980} title={`${row.id}　${row.title}`}>
      {/* 徽标与动作行 */}
      <div className="flex flex-wrap items-center gap-1.5 mb-2">
        <span className={`px-2 py-0.5 rounded text-xs ${GRADE_CLS[row.grade]}`}>{GRADE_LABEL[row.grade]}</span>
        {row.issues.map(i => (
          <span key={i} className={`px-1.5 py-0.5 rounded text-xs ${ISSUE_CLS[i]}`}>{ISSUE_LABEL[i]}</span>
        ))}
        <span className="text-xs text-gray-500 ml-2">关联需求：</span>
        {row.covers_detail.length === 0 ? <span className="text-xs text-gray-600">—</span> : row.covers_detail.map(c => (
          <span key={c.fr}
            title={c.valid ? `${c.fr}：${c.title || '（无标题）'}${c.module ? `（${c.module}）` : ''}` : `${c.fr}：当前工作区锚点表查不到`}
            className={`px-1.5 py-0.5 rounded text-xs ${c.valid ? 'bg-surface-3' : 'bg-red-900/40 text-red-400'}`}>
            {c.fr}{!c.valid && ' ⚠'}
          </span>
        ))}
        <div className="flex-1" />
        {savedFlash && <span className="text-pass text-sm">✓ 已保存</span>}
        {canRun && (
          <button className="btn-primary text-sm" onClick={() => setShowRun(true)}>▶ 试跑</button>
        )}
      </div>

      {/* doc 语义速览（完整结构化内容见下方编辑器） */}
      {hasDoc && (
        <div className="text-xs text-gray-400 mb-2 space-y-0.5">
          {doc.given && <div>· 给定：{doc.given}</div>}
          {doc.when && <div>· 操作：{doc.when}</div>}
          {doc.then && <div>· 预期：{doc.then}</div>}
        </div>
      )}
      {row.evidence.length > 0 && (
        <div className="flex flex-wrap items-center gap-1 mb-3 text-xs">
          <span className="text-gray-500">断言证据（评级的确定性输入）：</span>
          {row.evidence.map(e => (
            <span key={e} className="px-1.5 py-0.5 rounded bg-surface-3" title={`证据特征 ${e}`}>
              {EVIDENCE_LABEL[e] || e}
            </span>
          ))}
        </div>
      )}

      {/* 三态：错误 / 加载中 / 编辑器 */}
      {error && (
        <div className="mb-3 p-3 rounded-lg bg-red-900/30 text-red-400 border border-red-700/50 text-sm">
          ❌ 加载用例失败：{error}
        </div>
      )}
      {!error && content === null && (
        <div className="py-16 text-center text-gray-500 text-sm">加载中…</div>
      )}
      {!error && content !== null && (
        <div className="h-[62vh] min-h-0 overflow-y-auto pr-1">
          <ScenarioFormEditor
            scenarioId={row.id}
            yamlContent={content}
            empRoles={empRoles}
            oracles={oracles}
            upstreamVars={upstreamVars}
            envVars={envVars}
            allScenarios={scenarios.map(s => ({ id: s.id, title: s.title }))}
            onSave={handleSave}
          />
        </div>
      )}

      {showRun && (
        <ScenarioRunDialog
          scenarioId={row.id}
          scenarios={scenarios}
          anchorsAvailable={anchorsAvailable}
          invalidCoversCount={invalidCoversCount}
          onClose={() => setShowRun(false)}
        />
      )}
    </Modal>
  );
}
