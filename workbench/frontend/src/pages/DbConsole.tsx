/** DB 证据面板独立页（设计 2026-08-25 §A3）——只读 SQL 执行 / schema 切换 / 结果表格 / 查询历史。
 * 状态逻辑与内嵌 DbPanel（agentChat/DbPanel.tsx）共享 useDbConsole（localStorage 互通）。
 * 状态持久化（基线①）：schema 选择与编辑器草稿 localStorage 恢复；
 * 三态分离（基线③）：加载中 / 空态 / 错误分别呈现。 */
import { useEffect, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router';
import Editor from '@monaco-editor/react';
import { useDbConsole } from './agentChat/DbPanel';
import { SqlResultTable } from '../components/SqlResultTable';

export function DbConsole() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { schemas, schemasLoaded, schema, setSchema, sql, setSql, result, loading, error, history, runQuery } = useDbConsole();

  // 联动入口：?sql=... 回填并自动执行（A4 入口②跳转目标）
  useEffect(() => {
    const incoming = searchParams.get('sql');
    if (incoming) {
      setSql(incoming);
      runQueryRef.current(incoming, schema);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // onMount 闭包捕获的是初始态——经 ref 取最新 runQuery
  const runQueryRef = useRef(runQuery);
  runQueryRef.current = runQuery;

  return (
    <div className="max-w-6xl mx-auto p-4 space-y-3">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-medium">🗄 DB 证据</h1>
        <span className="text-xs text-gray-500">只读查询（共享只读账号，无行级权限）——仅 SELECT/SHOW/DESCRIBE/EXPLAIN</span>
      </div>

      {/* schema 切换器 */}
      <div className="flex items-center gap-2 text-xs">
        <span className="text-gray-500">schema</span>
        {schemasLoaded ? (schemas.length ? schemas.map(s => (
          <button key={s.name}
            onClick={() => setSchema(s.name)}
            className={`px-2 py-0.5 rounded border ${schema === s.name
              ? 'border-info text-info' : 'border-border text-gray-400 hover:text-gray-200'} ${!s.alive ? 'opacity-40' : ''}`}
            title={s.is_default ? '默认连接' : ''}>
            <span>{s.name}</span>{s.is_default ? ' ·default' : ''}{!s.alive ? '（连接失败）' : ''}
          </button>
        )) : <span className="text-gray-600">环境配置未设置 db 段（去系统配置页补充）</span>
        ) : <span className="text-gray-600">加载中…</span>}
      </div>

      {/* SQL 编辑器 */}
      <div className="border border-border rounded h-56">
        <Editor
          defaultLanguage="sql"
          value={sql}
          onChange={(v) => setSql(v || '')}
          theme="vs-dark"
          options={{ minimap: { enabled: false }, fontSize: 12, scrollBeyondLastLine: false }}
          onMount={(editor, monaco) => {
            editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => runQueryRef.current());
          }}
        />
      </div>

      <div className="flex items-center gap-3">
        <button onClick={() => runQuery()} disabled={loading}
          title="执行 (Ctrl+Enter)"
          className="px-3 py-1 text-xs rounded bg-info/20 text-info border border-info/40 hover:bg-info/30 disabled:opacity-50">
          {loading ? '查询中…' : '▶ 执行'}
        </button>
        <button onClick={() => {
          // 交给辅助助手：SQL 草稿经 sessionStorage 中转 → /agent 激活页签自动发送（§C3；T-1031 改称）
          sessionStorage.setItem('sg_sql_aux_send', sql);
          navigate('/agent');
        }} disabled={!sql.trim()}
          className="px-3 py-1 text-xs rounded border border-border text-gray-400 hover:text-info disabled:opacity-50"
          title="把当前 SQL 发给辅助助手迭代（解释表关系/设计理由/多轮优化）">
          🤖 交给辅助助手
        </button>
        <span className="text-[10px] text-gray-600">Ctrl+Enter 执行</span>
      </div>

      {/* 三态分离：错误 / 结果 / 空态 */}
      {error && <div className="text-xs text-red-400 bg-red-900/10 border border-red-700/20 rounded p-2">❌ {error}</div>}
      {result && (
        <div className="space-y-1">
          <div className="text-[10px] text-gray-500">{result.elapsed_ms}ms{result.truncated ? ' · 结果超上限已截断' : ''}</div>
          <SqlResultTable rows={result.rows} row_count={result.row_count} truncated={result.truncated} />
        </div>
      )}
      {!result && !error && !loading && (
        <div className="text-xs text-gray-600 py-4">输入 SQL 后执行；结果仅在本页展示并记录查询历史</div>
      )}

      {/* 查询历史 */}
      {history.length > 0 && (
        <div>
          <div className="text-xs text-gray-500 mb-1">查询历史（{history.length}）</div>
          <div className="space-y-0.5 max-h-40 overflow-y-auto">
            {history.map((h, i) => (
              <button key={i} onClick={() => { setSql(h.sql); setSchema(h.schema); }}
                className="block w-full text-left text-[11px] font-mono text-gray-500 hover:text-gray-300 truncate"
                title={h.sql}>
                [{h.schema}] {h.sql}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default DbConsole;
