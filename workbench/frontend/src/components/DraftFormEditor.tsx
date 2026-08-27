/** DraftFormEditor — T-1027 验收反馈：草稿编辑应落在结构化预览而非裸 YAML 文本。
 *
 * 复用场景编辑器 ScenarioFormEditor（阅读/表单/YAML 三模式，默认进表单），
 * 参考registries（角色/oracle/环境变量/上游变量）懒加载、失败静默降级为空下拉
 * （与 Drafts.tsx 草稿评审页同一数据源口径）；allScenarios 留空——依赖连线在
 * 面板走 suggest-deps 一键采纳通道，不在下拉里重建全库列表。
 * 保存借道 FileViewer 的 onSaveContent 回调（PUT /api/drafts，后端自动校验+
 * 版本链+对话感知）；ok=false 以异常抛回，由 ScenarioFormEditor 自身的
 * 错误条呈现；完整校验报告由上层 SaveOutcomeBanner 展示。
 */
import { useEffect, useMemo, useState } from 'react';
import { load as yamlLoad } from 'js-yaml';
import { referenceApi } from '../api';
import type { EmpRole, EnvVar, OracleRef, UpstreamVar } from '../api';
import ScenarioFormEditor from './ScenarioFormEditor';

export interface EditSaveOutcome {
  ok: boolean;
  message?: string;     // 人话结论（含对话感知去向：已注入/执行中暂存/无关联会话）
  verdict?: string;     // 自动格式校验结论（PASS/FAIL/ERROR…）
  summaryError?: number;
  summaryWarn?: number;
  findings?: { level: string; rule: string; message: string }[];
}

interface Props {
  filename: string;
  yaml: string;         // 已落盘文本（非受控缓冲——缓冲在 ScenarioFormEditor 内部）
  onSave: (content: string) => Promise<EditSaveOutcome>;
}

export default function DraftFormEditor({ filename, yaml, onSave }: Props) {
  const [empRoles, setEmpRoles] = useState<EmpRole[]>([]);
  const [oracles, setOracles] = useState<OracleRef[]>([]);
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [upstreamVars, setUpstreamVars] = useState<UpstreamVar[]>([]);

  useEffect(() => {
    referenceApi.empRoles().then(setEmpRoles).catch(() => {});
    referenceApi.oracles().then(setOracles).catch(() => {});
    referenceApi.envVars().then(setEnvVars).catch(() => {});
  }, []);

  const sid = useMemo(() => {
    try { return String((yamlLoad(yaml) as Record<string, unknown>)?.id || ''); } catch { return ''; }
  }, [yaml]);
  useEffect(() => {
    if (!sid) { setUpstreamVars([]); return; }
    referenceApi.upstreamVars(sid).then(setUpstreamVars).catch(() => setUpstreamVars([]));
  }, [sid]);

  return (
    <div className="h-full min-h-0">
      <ScenarioFormEditor
        scenarioId={sid || filename}
        yamlContent={yaml}
        empRoles={empRoles}
        oracles={oracles}
        upstreamVars={upstreamVars}
        envVars={envVars}
        allScenarios={[]}
        onSave={async (yamlStr: string) => {
          const r = await onSave(yamlStr);
          if (!r.ok) throw new Error(r.message || '保存失败');
        }}
      />
    </div>
  );
}
