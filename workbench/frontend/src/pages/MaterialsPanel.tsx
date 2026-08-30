// 材料管理面板（T-058，S3 前端缺口补丁）：上传/解析状态/候选确认/入包/重装配

import { useEffect, useState } from 'react';
import {
  specflowApi,
  type InterviewItem,
  type MaterialItem,
  type MaterialTopic,
} from '../api';
import FeishuReviewPanel from '../components/FeishuReviewPanel';

const STATUS_COLOR: Record<string, string> = {
  uploaded: 'text-blue-400',
  parsing: 'text-yellow-400',
  parsed: 'text-green-400',
  indexed: 'text-green-400',
  packed: 'text-emerald-400',
  failed: 'text-red-400',
};

export default function MaterialsPanel() {
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [interviews, setInterviews] = useState<InterviewItem[]>([]);
  const [selIv, setSelIv] = useState('');
  const [materials, setMaterials] = useState<MaterialItem[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [topicsByMid, setTopicsByMid] = useState<Record<string, MaterialTopic[]>>({});
  const [packText, setPackText] = useState('');
  const [busy, setBusy] = useState('');

  const flash = (fn: () => void) => { setError(''); setNotice(''); fn(); };

  const loadInterviews = async () => {
    try {
      const { interviews } = await specflowApi.listInterviews();
      setInterviews(interviews);
      if (interviews.length > 0 && !selIv) setSelIv(interviews[0].iv_id);
    } catch (e: any) { setError(e.message); }
  };

  const loadMaterials = async (ivId: string) => {
    if (!ivId) { setMaterials([]); return; }
    try {
      const { materials } = await specflowApi.listMaterials(ivId);
      setMaterials(materials);
    } catch (e: any) { setError(e.message); }
  };

  const loadTopics = async (mid: string) => {
    try {
      const { topics } = await specflowApi.listTopics(mid);
      setTopicsByMid(prev => ({ ...prev, [mid]: topics }));
    } catch (e: any) { setError(e.message); }
  };

  useEffect(() => { flash(loadInterviews); }, []);
  useEffect(() => { flash(() => loadMaterials(selIv)); }, [selIv]);

  const handleUpload = async () => {
    if (!selIv || !file) { setError('请选择面试并选择文件'); return; }
    setBusy('upload');
    try {
      const { material } = await specflowApi.uploadMaterial(selIv, file);
      setNotice(`已上传 ${material.filename} → ${material.status}（${material.mid}）`);
      setFile(null);
      loadMaterials(selIv);
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const handleConfirmTopic = async (mid: string, topic: MaterialTopic, confirmed: boolean) => {
    try {
      await specflowApi.confirmTopic(mid, topic.tid, confirmed);
      setNotice(`议题「${topic.title}」${confirmed ? '已确认' : '已取消确认'}`);
      loadTopics(mid);
    } catch (e: any) { setError(e.message); }
  };

  const handleInclude = async (m: MaterialItem, included: boolean) => {
    try {
      await specflowApi.includeMaterial(selIv, m.mid, included);
      setNotice(`材料「${m.filename}」${included ? '已入包' : '已移出包'}`);
      loadMaterials(selIv);
    } catch (e: any) { setError(e.message); }
  };

  const handleReassemble = async () => {
    if (!selIv) return;
    try {
      const { pack } = await specflowApi.reassemblePack(selIv);
      setPackText(typeof pack === 'string' ? pack : JSON.stringify(pack, null, 2));
      setNotice('六分区重新装配完成');
    } catch (e: any) { setError(e.message); }
  };

  const card = 'bg-surface-2 border border-border rounded-lg p-4 mb-4';
  const label = 'block text-fs-body text-gray-400 mb-1';
  const input = 'w-full bg-surface-3 border border-border rounded px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-info';
  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';
  const th = 'text-left text-fs-body text-gray-500 font-normal px-2 py-1 border-b border-border';
  const td = 'px-2 py-1.5 text-fs-body text-gray-300 border-b border-border/50 align-top';

  return (
    <div className="p-4 max-w-[1100px] mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-base font-bold">📚 材料管理</h1>
        <div className="text-fs-body text-gray-500">候选确认/入包需 product 角色 · 解析失败可查看 parse_error</div>
      </div>
      {error && <div className="mb-3 px-3 py-2 rounded bg-red-500/10 text-red-400 text-fs-body">{error}</div>}
      {notice && <div className="mb-3 px-3 py-2 rounded bg-green-500/10 text-green-400 text-fs-body">{notice}</div>}

      <div className={card}>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-72">
            <span className={label}>面试（IV-xxx）</span>
            <select className={input} value={selIv} onChange={e => setSelIv(e.target.value)}>
              <option value="">— 选择面试 —</option>
              {interviews.map(iv => (
                <option key={iv.iv_id} value={iv.iv_id}>{iv.iv_id} · {iv.title}</option>
              ))}
            </select>
          </div>
          <div className="w-64">
            <span className={label}>上传材料（.md/.docx/.pdf，≤20MB）</span>
            <input type="file" className={`${input} file:mr-2 file:px-2 file:py-1 file:rounded file:bg-info/15 file:text-info file:text-fs-body file:border-0`}
                   onChange={e => setFile(e.target.files?.[0] || null)} />
          </div>
          <button className={btn} onClick={handleUpload} disabled={busy === 'upload' || !selIv || !file}>
            {busy === 'upload' ? '上传中…' : '上传并解析'}
          </button>
        </div>
      </div>

      <div className={card}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold">材料列表（{materials.length}）</h2>
          <button className={btn} onClick={handleReassemble} disabled={!selIv}>六分区重新装配</button>
        </div>
        {materials.length === 0 ? (
          <div className="text-fs-body text-gray-500">暂无材料，请上传</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr>
                <th className={th}>材料</th><th className={th}>格式</th><th className={th}>状态</th>
                <th className={th}>指纹</th><th className={th}>议题候选</th><th className={th}>操作</th>
              </tr>
            </thead>
            <tbody>
              {materials.map(m => (
                <tr key={m.mid}>
                  <td className={td}>
                    <div className="font-medium">{m.filename}</div>
                    <div className="text-fs-body text-gray-500">{m.mid}</div>
                  </td>
                  <td className={td}>{m.fmt}</td>
                  <td className={`${td} ${STATUS_COLOR[m.status] || ''}`}>
                    {m.status}
                    {m.parse_error && <div className="text-fs-body text-red-400">{m.parse_error}</div>}
                  </td>
                  <td className={td}><code className="text-fs-body">{m.sha256_12}</code></td>
                  <td className={td}>
                    {m.status === 'indexed' ? (
                      <div className="space-y-1">
                        <button className={btn} onClick={() => loadTopics(m.mid)}>查看候选</button>
                        {(topicsByMid[m.mid] || []).map(t => (
                          <div key={t.tid} className="flex items-center gap-1.5 text-fs-body">
                            <span className={t.confirmed ? 'text-green-400' : 'text-gray-400'}>
                              {t.confirmed ? '✓' : '○'} {t.title}
                            </span>
                            <button
                              className="text-fs-aux px-1.5 py-0.5 rounded bg-info/10 text-info hover:bg-info/20"
                              onClick={() => handleConfirmTopic(m.mid, t, !t.confirmed)}>
                              {t.confirmed ? '取消' : '确认'}
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : <span className="text-fs-body text-gray-600">解析完成后可取候选</span>}
                  </td>
                  <td className={td}>
                    <button
                      className={m.pack_included ? btn : `${btn} opacity-70`}
                      onClick={() => handleInclude(m, !m.pack_included)}>
                      {m.pack_included ? '已入包 · 移出' : '入包'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {packText && (
        <div className={card}>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-sm font-semibold">信息包（info_pack.yaml）</h2>
            <button className={btn} onClick={() => setPackText('')}>收起</button>
          </div>
          <pre className="text-fs-body text-gray-400 bg-surface-3 rounded p-3 max-h-80 overflow-auto whitespace-pre-wrap">{packText}</pre>
        </div>
      )}

      {/* 飞书知识图谱一期 T-915：飞书材料→FR 关联复核（人拍板闸门） */}
      <FeishuReviewPanel />
    </div>
  );
}
