// T-509 知识维护页（一页三区）：词条编辑（保存即校验、断链标红）
// + 环境叙事编辑（凭据红线提示）+ 经验审核队列
// 纪律：RBAC 写权限（后端拦截）+ 审计留痕（后端落）；Agent 提议经「待确认」进队列

import { useCallback, useEffect, useState } from 'react';
import { knowledgeApi } from '../api';
import type {
  GlossaryData, EnvNarrative, ExperienceItem, KnowledgeFinding,
} from '../api';

const FINDING_STYLE: Record<string, string> = {
  ERROR: 'text-fail', WARN: 'text-warn',
};

export default function Knowledge() {
  const [tab, setTab] = useState<'glossary' | 'env' | 'experience'>('glossary');

  // ── 词条区 ──
  const [glossary, setGlossary] = useState<GlossaryData | null>(null);
  const [glossaryText, setGlossaryText] = useState('');
  const [glossaryBusy, setGlossaryBusy] = useState(false);
  const [glossaryMsg, setGlossaryMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // ── 环境叙事区 ──
  const [envs, setEnvs] = useState<EnvNarrative[]>([]);
  const [envSelected, setEnvSelected] = useState('');
  const [envText, setEnvText] = useState('');
  const [envFindings, setEnvFindings] = useState<KnowledgeFinding[]>([]);
  const [envBusy, setEnvBusy] = useState(false);
  const [envMsg, setEnvMsg] = useState<{ ok: boolean; text: string } | null>(null);

  // ── 经验审核区 ──
  const [expItems, setExpItems] = useState<ExperienceItem[]>([]);
  const [expError, setExpError] = useState('');
  // T-510：👍/👎 反馈
  const [expMsg, setExpMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const loadGlossary = useCallback(async () => {
    try {
      const d = await knowledgeApi.glossary();
      setGlossary(d);
      setGlossaryText(d.text);
    } catch (e) {
      setGlossaryMsg({ ok: false, text: `词典加载失败：${e}` });
    }
  }, []);

  const loadEnvs = useCallback(async () => {
    try {
      const r = await knowledgeApi.envList();
      setEnvs(r.narratives);
      if (r.narratives.length > 0 && !envSelected) {
        selectEnv(r.narratives[0].env);
      }
    } catch (e) {
      setEnvMsg({ ok: false, text: `环境叙事加载失败：${e}` });
    }
  }, [envSelected]);

  const selectEnv = useCallback(async (env: string) => {
    setEnvSelected(env);
    try {
      const r = await knowledgeApi.envGet(env);
      setEnvText(r.text);
      setEnvFindings(r.findings);
    } catch (e) {
      setEnvMsg({ ok: false, text: `环境叙事读取失败：${e}` });
    }
  }, []);

  const loadExperience = useCallback(async () => {
    try {
      const r = await knowledgeApi.experience();
      setExpItems(r.items);
      setExpError('');
    } catch (e) {
      setExpError(`经验队列加载失败：${e}`);
    }
  }, []);

  // T-510：👍/👎 反馈
  const rate = async (token: string, rating: 'up' | 'down') => {
    try {
      await knowledgeApi.experienceRate(token, rating);
      setExpMsg({ ok: true, text: `已${rating === 'up' ? '👍' : '👎'}：${token}` });
      loadExperience();
    } catch (e) {
      setExpMsg({ ok: false, text: `反馈失败：${e}` });
    }
  };

  useEffect(() => { loadGlossary(); }, [loadGlossary]);
  useEffect(() => { loadEnvs(); }, [loadEnvs]);
  useEffect(() => { if (tab === 'experience') loadExperience(); }, [tab, loadExperience]);

  const saveGlossary = async () => {
    setGlossaryBusy(true);
    try {
      const d = await knowledgeApi.saveGlossary(glossaryText);
      setGlossary(d);
      const nErr = d.findings.filter((f) => f.level === 'ERROR').length;
      setGlossaryMsg({
        ok: nErr === 0,
        text: nErr > 0
          ? `已保存，但存在 ${nErr} 处断链（FR 在当前 spec 中不存在）`
          : `已保存（${d.entries.length} 词条，校验通过）`,
      });
    } catch (e) {
      setGlossaryMsg({ ok: false, text: `保存失败：${e}` });
    } finally {
      setGlossaryBusy(false);
    }
  };

  const saveEnv = async () => {
    setEnvBusy(true);
    try {
      const r = await knowledgeApi.envSave(envSelected, envText);
      setEnvFindings(r.findings);
      setEnvMsg({ ok: r.saved, text: r.message });
    } catch (e) {
      setEnvMsg({ ok: false, text: `保存失败：${e}` });
    } finally {
      setEnvBusy(false);
    }
  };

  const nErr = (glossary?.findings ?? []).filter((f) => f.level === 'ERROR').length;

  return (
    <div className="page">
      <h2 className="font-display text-fs-title font-semibold text-gray-200">📚 知识</h2>
      <p className="text-dim" style={{ marginTop: -8 }}>
        语义词典 / 环境叙事 / 经验审核——知识按工作区与系统隔离，触景分发不堆提示词
      </p>

      <div className="tabs" style={{ margin: '12px 0' }}>
        <button className={tab === 'glossary' ? 'tab active' : 'tab'}
                onClick={() => setTab('glossary')}>
          词条{nErr > 0 ? `（${nErr} 断链）` : ''}
        </button>
        <button className={tab === 'env' ? 'tab active' : 'tab'}
                onClick={() => setTab('env')}>
          环境叙事
        </button>
        <button className={tab === 'experience' ? 'tab active' : 'tab'}
                onClick={() => setTab('experience')}>
          经验审核
        </button>
      </div>

      {/* ═══ 区一：词条编辑（保存即 conformance 校验、断链标红）═══ */}
      {tab === 'glossary' && (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
            <span className="text-dim">工作区词典：{glossary?.path ?? '（未加载）'}</span>
            <span className="text-dim">
              {glossary?.entries.length ?? 0} 词条
              {' · '}格式：<code>### 标题 [token: xxx]</code> + 语义/规则/数据/关联/歧义史/出处
            </span>
          </div>

          {glossaryMsg && (
            <div className={glossaryMsg.ok ? 'notice ok' : 'notice fail'}
                 style={{ marginBottom: 8 }}>
              {glossaryMsg.text}
            </div>
          )}

          {(glossary?.findings ?? []).length > 0 && (
            <ul style={{ marginBottom: 8, paddingLeft: 20 }}>
              {glossary!.findings.map((f, i) => (
                <li key={i} className={FINDING_STYLE[f.level]}>
                  {f.token ? `[${f.token}] ` : ''}{f.message}
                </li>
              ))}
            </ul>
          )}

          <textarea
            value={glossaryText}
            onChange={(e) => setGlossaryText(e.target.value)}
            rows={24}
            spellCheck={false}
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 13 }}
            placeholder="（工作区无 glossary.md——按上方格式新建词条后保存）"
          />
          <div style={{ marginTop: 8 }}>
            <button onClick={saveGlossary} disabled={glossaryBusy}>
              {glossaryBusy ? '保存中…' : '保存词条（保存即校验）'}
            </button>
            <button onClick={loadGlossary} style={{ marginLeft: 8 }}>重新加载</button>
          </div>
        </div>
      )}

      {/* ═══ 区二：环境叙事编辑（凭据红线提示）═══ */}
      {tab === 'env' && (
        <div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
            <label className="text-dim">环境：</label>
            <select value={envSelected} onChange={(e) => selectEnv(e.target.value)}>
              {envs.map((n) => (
                <option key={n.env} value={n.env}>env.{n.env}.md</option>
              ))}
            </select>
            <span className="text-warn" style={{ fontSize: 12 }}>
              ⚠️ 红线：叙事层永不写凭据（password/secret/token 含真实值将被拒绝保存）
            </span>
          </div>

          {envMsg && (
            <div className={envMsg.ok ? 'notice ok' : 'notice fail'}
                 style={{ marginBottom: 8 }}>
              {envMsg.text}
            </div>
          )}

          {envFindings.length > 0 && (
            <ul style={{ marginBottom: 8, paddingLeft: 20 }}>
              {envFindings.map((f, i) => (
                <li key={i} className={FINDING_STYLE[f.level]}>{f.message}</li>
              ))}
            </ul>
          )}

          <textarea
            value={envText}
            onChange={(e) => setEnvText(e.target.value)}
            rows={24}
            spellCheck={false}
            style={{ width: '100%', fontFamily: 'monospace', fontSize: 13 }}
            placeholder="（选择环境后编辑叙事；五段：定位/拓扑/账号池/资源码/已知坑）"
          />
          <div style={{ marginTop: 8 }}>
            <button onClick={saveEnv} disabled={envBusy}>
              {envBusy ? '保存中…' : '保存环境叙事'}
            </button>
            {envSelected && (
              <button onClick={() => selectEnv(envSelected)} style={{ marginLeft: 8 }}>
                重新加载
              </button>
            )}
          </div>
        </div>
      )}

      {/* ═══ 区三：经验审核队列（T-510 落行后消费）═══ */}
      {tab === 'experience' && (
        <div>
          {expError && <div className="notice fail" style={{ marginBottom: 8 }}>{expError}</div>}
          {expMsg && (
            <div className={expMsg.ok ? 'notice ok' : 'notice fail'}
                 style={{ marginBottom: 8 }}>{expMsg.text}</div>
          )}
          {expItems.length === 0 && !expError && (
            <p className="text-dim">
              经验库为空（{'{工作区}/.specguard/experience/'}）。T-510 经验飞轮落行后，
              此处展示 success/failed/corrected 自动积累条目，可 👍/👎 并提炼为经验包。
            </p>
          )}
          {expItems.map((item) => (
            <div key={item.token} className="card" style={{ marginBottom: 8, padding: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <strong>{item.token}</strong>
                <span className="text-dim">{item.path}</span>
              </div>
              <div className="text-dim" style={{ fontSize: 12, marginTop: 4 }}>
                verdict={item.verdict} · hit×{item.hit_count}
                {' · '}{item.rating === 'up' ? '👍' : item.rating === 'down' ? '👎' : '未评价'}
                {item.corrected ? ' · 已纠正' : ''}
              </div>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, marginTop: 6 }}>
                {item.text.slice(0, 600)}
              </pre>
              <div style={{ marginTop: 6 }}>
                <button onClick={() => rate(item.token, 'up')} title="有用">👍</button>
                <button onClick={() => rate(item.token, 'down')} title="无用"
                        style={{ marginLeft: 6 }}>👎</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
