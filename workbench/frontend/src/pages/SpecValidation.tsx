/** SpecValidation — Spec 文档校验 + TestCase 格式校验 */
import { useEffect, useState } from 'react';
import { specApi, type DeltaInfo, type SpecValidationResult, type TestCaseValidationResult } from '../api';

type ValidationTab = 'spec' | 'testcase';

export default function SpecValidation() {
  const [deltas, setDeltas] = useState<DeltaInfo[]>([]);
  const [currentDelta, setCurrentDelta] = useState('');
  const [selectedDelta, setSelectedDelta] = useState('');
  const [mode, setMode] = useState('create');
  const [tab, setTab] = useState<ValidationTab>('spec');
  const [specResult, setSpecResult] = useState<SpecValidationResult | null>(null);
  const [tcResult, setTcResult] = useState<TestCaseValidationResult | null>(null);
  const [reportContent, setReportContent] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    specApi.deltas().then((r) => {
      setDeltas(r.deltas);
      setCurrentDelta(r.current);
      setSelectedDelta(r.current || r.deltas[0]?.id || '');
    });
  }, []);

  const runSpecValidation = async () => {
    if (!selectedDelta) return;
    setLoading(true);
    setReportContent('');
    try {
      const r = await specApi.validate(selectedDelta, mode);
      setSpecResult(r);
      if (r.report_path) {
        specApi.report(r.report_path).then((rep) => setReportContent(rep.content)).catch(() => {});
      }
    } catch (e: unknown) {
      setSpecResult({
        verdict: 'ERROR', delta: selectedDelta, mode,
        findings: [{ level: 'ERROR', vid: 'API', message: e instanceof Error ? e.message : '请求失败' }],
        summary: { error: 1, warn: 0 },
      });
    } finally { setLoading(false); }
  };

  const runTcValidation = async () => {
    setLoading(true);
    try { setTcResult(await specApi.validateTestCases()); }
    catch { /* */ } finally { setLoading(false); }
  };

  const levelColor: Record<string, string> = {
    ERROR: 'text-fail', WARN: 'text-skip', INFO: 'text-gray-500',
  };
  const levelBg: Record<string, string> = {
    ERROR: 'bg-fail/10', WARN: 'bg-skip/10', INFO: 'bg-surface-3',
  };

  return (
    <div className="h-full flex flex-col space-y-4">
      <h2 className="text-lg font-semibold">🛡 Spec 校验</h2>

      {/* 控制面板 */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex bg-surface-3 rounded overflow-hidden">
          {(['spec', 'testcase'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-3 py-1.5 text-[11px] ${tab === t ? 'bg-info/20 text-info' : 'text-gray-500'}`}>
              {t === 'spec' ? '📄 Spec 文档校验' : '🧪 TestCase 格式校验'}
            </button>
          ))}
        </div>

        {tab === 'spec' && (
          <>
            <select value={selectedDelta} onChange={(e) => setSelectedDelta(e.target.value)}
              className="bg-surface-3 border border-border rounded px-2 py-1.5 text-xs">
              {deltas.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.id}{d.id === currentDelta ? '（当前）' : ''}
                </option>
              ))}
            </select>
            <select value={mode} onChange={(e) => setMode(e.target.value)}
              className="bg-surface-3 border border-border rounded px-2 py-1.5 text-xs">
              <option value="create">create（创建时结构校验）</option>
              <option value="pre">pre（合并前检查）</option>
              <option value="post">post（合并后验证）</option>
            </select>
            <button onClick={runSpecValidation} disabled={loading}
              className="px-4 py-1.5 rounded text-xs bg-info/20 text-info hover:bg-info/30 disabled:opacity-40">
              {loading ? '校验中…' : '🔍 运行校验'}
            </button>
          </>
        )}

        {tab === 'testcase' && (
          <button onClick={runTcValidation} disabled={loading}
            className="px-4 py-1.5 rounded text-xs bg-info/20 text-info hover:bg-info/30 disabled:opacity-40">
            {loading ? '校验中…' : '🔍 校验全部 TestCase'}
          </button>
        )}
      </div>

      {/* 校验结果 */}
      <div className="flex-1 flex gap-3 min-h-0">
        {/* 左侧：结果列表 */}
        <div className="flex-1 border border-border rounded-lg overflow-hidden flex flex-col">
          {tab === 'spec' && specResult && (
            <>
              <div className={`px-3 py-2 border-b border-border flex items-center justify-between ${
                specResult.verdict === 'PASS' ? 'bg-pass/10' : 'bg-fail/10'
              }`}>
                <span className="text-xs font-medium">
                  {specResult.verdict === 'PASS' ? '✅ PASS' : '❌ REJECT'}
                  <span className="text-gray-500 ml-2">delta: {specResult.delta} · mode: {specResult.mode}</span>
                </span>
                <span className="text-fs-aux text-gray-500">
                  ERROR={specResult.summary.error} WARN={specResult.summary.warn} INFO={specResult.summary.info || 0}
                </span>
              </div>
              <div className="flex-1 overflow-y-auto">
                {specResult.findings.map((f, i) => (
                  <div key={i} className={`flex items-start gap-2 px-3 py-1.5 border-b border-border/20 text-xs ${levelBg[f.level] || ''}`}>
                    <span className={`font-mono w-12 flex-shrink-0 ${levelColor[f.level]}`}>{f.level}</span>
                    <span className="font-mono text-gray-500 w-8 flex-shrink-0">{f.vid}</span>
                    <span className="text-gray-300">{f.message}</span>
                  </div>
                ))}
                {specResult.findings.length === 0 && (
                  <div className="p-4 text-center text-gray-500 text-xs">无发现问题</div>
                )}
              </div>
            </>
          )}

          {tab === 'testcase' && tcResult && (
            <>
              <div className={`px-3 py-2 border-b border-border flex items-center justify-between ${
                tcResult.verdict === 'PASS' ? 'bg-pass/10' : 'bg-fail/10'
              }`}>
                <span className="text-xs font-medium">
                  {tcResult.verdict === 'PASS' ? '✅ PASS' : '❌ REJECT'}
                  <span className="text-gray-500 ml-2">共 {tcResult.total_scenarios} 个场景</span>
                </span>
                <span className="text-fs-aux text-gray-500">
                  ERROR={tcResult.summary.error} WARN={tcResult.summary.warn}
                </span>
              </div>
              <div className="flex-1 overflow-y-auto">
                {tcResult.findings.map((f, i) => (
                  <div key={i} className={`flex items-start gap-2 px-3 py-1.5 border-b border-border/20 text-xs ${levelBg[f.level] || ''}`}>
                    <span className={`font-mono w-12 flex-shrink-0 ${levelColor[f.level]}`}>{f.level}</span>
                    <span className="font-mono text-gray-500 w-8 flex-shrink-0">{f.vid}</span>
                    <span className="font-mono text-info/60 w-28 flex-shrink-0 truncate">{f.scenario}</span>
                    <span className="text-gray-300">{f.message}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {!specResult && !tcResult && (
            <div className="h-full flex items-center justify-center text-gray-600 text-sm">
              点击上方按钮运行校验
            </div>
          )}
        </div>

        {/* 右侧：报告预览 */}
        {reportContent && tab === 'spec' && (
          <div className="w-[480px] flex-shrink-0 border border-border rounded-lg overflow-hidden flex flex-col">
            <div className="px-3 py-2 border-b border-border text-xs font-medium bg-surface-2">
              📄 校验报告
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              <pre className="text-[11px] text-gray-300 whitespace-pre-wrap font-mono leading-5">{reportContent}</pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
