/** 内嵌 DB 证据面板（设计 2026-08-26 SQL 探索模式）——会话内左右分栏的右侧栏。
 *
 * 与独立页 /db-console（DbConsole.tsx）共享 useDbConsole 状态逻辑与 localStorage
 * （schema/草稿/查询历史互通），仅布局不同：本组件为紧凑纵向排布（嵌入对话页）。
 * 「交给辅助助手」（T-1031 前称 SQL 助手）不再经 sessionStorage+navigate 跳页，直接走 onHandToAux 回调
 * 发给左栏辅助会话。 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Editor from '@monaco-editor/react';
import { dbApi } from '../../api/db';
import type { DbQueryResult, DbSchema } from '../../api/db';
import { SqlResultTable } from '../../components/SqlResultTable';

const LS_SCHEMA = 'sg_db_schema';
const LS_SQL = 'sg_db_sql_draft';
const LS_HISTORY = 'sg_db_history';

interface HistoryItem { sql: string; schema: string; ts: number }

/** DB 面板状态逻辑（DbConsole 页面与内嵌 DbPanel 共用；localStorage 键同一套）。 */
export function useDbConsole() {
  const [schemas, setSchemas] = useState<DbSchema[]>([]);
  const [schemasLoaded, setSchemasLoaded] = useState(false);
  const [schema, setSchema] = useState(() => localStorage.getItem(LS_SCHEMA) || '');
  const [sql, setSql] = useState(() => localStorage.getItem(LS_SQL) || 'SELECT 1');
  const [result, setResult] = useState<DbQueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [history, setHistory] = useState<HistoryItem[]>(() => {
    try { return JSON.parse(localStorage.getItem(LS_HISTORY) || '[]'); } catch { return []; }
  });

  useEffect(() => {
    dbApi.schemas().then(r => {
      setSchemas(r.schemas || []);
      if (!schema && r.default) setSchema(r.default);
    }).catch(() => setSchemas([])).finally(() => setSchemasLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { localStorage.setItem(LS_SQL, sql); }, [sql]);
  useEffect(() => { localStorage.setItem(LS_SCHEMA, schema); }, [schema]);

  const runQuery = useCallback(async (sqlText = sql, schemaName = schema) => {
    if (!sqlText.trim() || loading) return;
    setLoading(true); setError(''); setResult(null);
    try {
      const r = await dbApi.query({ sql: sqlText, schema: schemaName || undefined });
      setResult(r);
      setHistory(prev => {
        const next = [{ sql: sqlText, schema: schemaName, ts: Date.now() },
          ...prev.filter(h => h.sql !== sqlText)].slice(0, 50);
        localStorage.setItem(LS_HISTORY, JSON.stringify(next));
        return next;
      });
    } catch (e: any) {
      setError(e.message || '查询失败');
    } finally {
      setLoading(false);
    }
  }, [sql, schema, loading]);

  return {
    schemas, schemasLoaded, schema, setSchema,
    sql, setSql, result, loading, error, history, runQuery,
  };
}

/** 内嵌 DB 面板（SQL 探索模式右侧栏）：紧凑纵向布局，initialSql 变化即回填自动执行。 */
export function DbPanel({ initialSql, onClose, onHandToAux }: {
  initialSql?: string;         // 左栏 SQL 助手产出物跳来时的回填 SQL（变化即重填+执行）
  onClose: () => void;         // 退出 SQL 探索模式
  onHandToAux?: (sql: string) => void;  // 「交给辅助助手」：直发左栏对话（不走跳页中转）
}) {
  const db = useDbConsole();
  const { schemas, schemasLoaded, schema, setSchema, sql, setSql, result, loading, error, history, runQuery } = db;

  // onMount 闭包捕获的是初始态——经 ref 取最新 runQuery（Ctrl+Enter 快捷键）
  const runQueryRef = useRef(runQuery);
  runQueryRef.current = runQuery;

  // 左栏「▶ DB 面板」回填：initialSql 变化即回填并自动执行（同 DbConsole ?sql= 语义）
  useEffect(() => {
    if (initialSql) {
      setSql(initialSql);
      runQueryRef.current(initialSql, schema);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSql]);

  return (
    <div className="flex-1 min-w-0 flex flex-col border-l border-border bg-surface-2/50">
      {/* 标题条 */}
      <div className="flex-shrink-0 px-3 py-1.5 border-b border-border flex items-center gap-2 text-fs-body">
        <span className="text-gray-200">🗄 DB 证据</span>
        <span className="text-fs-aux text-gray-500 truncate">只读查询——仅 SELECT/SHOW/DESCRIBE/EXPLAIN</span>
        <button onClick={onClose} title="关闭 DB 面板，返回主会话"
          className="ml-auto text-gray-500 hover:text-info px-1 rounded hover:bg-surface-3 flex-shrink-0">✕</button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-2">
        {/* schema 切换器 */}
        <div className="flex items-center gap-2 text-fs-body flex-wrap">
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
        <div className="border border-border rounded h-40 flex-shrink-0">
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
            className="px-3 py-1 text-fs-body rounded bg-info/20 text-info border border-info/40 hover:bg-info/30 disabled:opacity-50">
            {loading ? '查询中…' : '▶ 执行'}
          </button>
          {onHandToAux && (
            <button onClick={() => onHandToAux(sql)} disabled={!sql.trim()}
              className="px-3 py-1 text-fs-body rounded border border-border text-gray-400 hover:text-info disabled:opacity-50"
              title="把当前 SQL 发给左栏辅助助手迭代（解释表关系/设计理由/多轮优化）">
              🤖 交给辅助助手
            </button>
          )}
          <span className="text-fs-aux text-gray-600">Ctrl+Enter 执行</span>
        </div>

        {/* 三态分离：错误 / 结果 / 空态 */}
        {error && <div className="text-fs-body text-fail bg-fail/12 border border-fail/35/20 rounded p-2">❌ {error}</div>}
        {result && (
          <div className="space-y-1">
            <div className="text-fs-aux text-gray-500">{result.elapsed_ms}ms{result.truncated ? ' · 结果超上限已截断' : ''}</div>
            <SqlResultTable rows={result.rows} row_count={result.row_count} truncated={result.truncated} />
          </div>
        )}
        {!result && !error && !loading && (
          <div className="text-fs-body text-gray-600 py-2">输入 SQL 后执行；结果仅在本面板展示并记录查询历史</div>
        )}

        {/* 查询历史 */}
        {history.length > 0 && (
          <div>
            <div className="text-fs-body text-gray-500 mb-1">查询历史（{history.length}）</div>
            <div className="space-y-0.5 max-h-32 overflow-y-auto">
              {history.map((h, i) => (
                <button key={i} onClick={() => { setSql(h.sql); setSchema(h.schema); }}
                  className="block w-full text-left text-fs-body font-mono text-gray-500 hover:text-gray-300 truncate"
                  title={h.sql}>
                  [{h.schema}] {h.sql}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
