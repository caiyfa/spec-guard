/** ScenarioCreate — 场景创建向导（G2-1）：3 步渐进式流水线 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { scenarioApi, workspaceApi, draftsApi, session } from '../api';
import type { ScenarioMeta } from '../api';

const FILE_ICONS: Record<string, string> = {
  '.md': '📝', '.markdown': '📝',
  '.yaml': '📦', '.yml': '📦',
  '.json': '🔧',
  '.txt': '📄',
  '.xlsx': '📊', '.xls': '📊',
  '.docx': '📘', '.doc': '📘',
  '.csv': '📑',
};

function getFileIcon(path: string): string {
  const ext = path.match(/\.[^.]+$/)?.[0]?.toLowerCase() || '';
  return FILE_ICONS[ext] || '📄';
}

export default function ScenarioCreate() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [name, setName] = useState('');
  const [module, setModule] = useState('');
  const [modules, setModules] = useState<string[]>([]);
  const [meta, setMeta] = useState<ScenarioMeta | null>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [wsName, setWsName] = useState('');

  const currentWorkspace = session.getWorkspace();

  useEffect(() => {
    draftsApi.modules().then(r => setModules(r.modules)).catch(() => {});
    setWsName(currentWorkspace);
  }, [currentWorkspace]);

  // Step 1: 创建场景元数据
  const handleCreate = async () => {
    if (!name.trim() || !module.trim()) {
      setError('请填写场景名称和模块');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const m = await scenarioApi.create({ name: name.trim(), module: module.trim() });
      setMeta(m);
      setStep(2);
    } catch (e: any) {
      setError(e.message || '创建失败');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: 加载文件树
  const loadFiles = useCallback(async () => {
    try {
      const r = await workspaceApi.specFiles();
      setFiles(r.files || []);
    } catch {
      setFiles([]);
    }
  }, []);

  useEffect(() => {
    if (step === 2 && files.length === 0) {
      loadFiles();
    }
  }, [step, files.length, loadFiles]);

  const toggleFile = (path: string) => {
    setSelectedFiles(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // 保存基础信息包
  const handleSaveInfoPack = async () => {
    if (!meta) return;
    setLoading(true);
    setError('');
    try {
      const fileList = Array.from(selectedFiles);
      const updated = await scenarioApi.updateInfoPack(meta.id, fileList);
      setMeta(updated);
      setStep(3);
    } catch (e: any) {
      setError(e.message || '保存失败');
    } finally {
      setLoading(false);
    }
  };

  // 重新选择文件
  const handleBackToStep2 = () => {
    setStep(2);
  };

  // 启动 Agent 分析
  const handleLaunchAgent = () => {
    if (!meta) return;
    navigate(`/agent?scenario_id=${meta.id}&mode=generate`);
  };

  // 跳转 DAG 编辑器
  const handleGoDAG = () => {
    navigate('/dag');
  };

  return (
    <div className="h-full flex flex-col max-w-4xl mx-auto">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-gray-200">✨ 新建场景</h2>
        <p className="text-xs text-gray-500 mt-1">
          从需求文档到测试编排的渐进式向导。选择基础信息包 → Agent 分析 → 生成草稿 → DAG 编排。
        </p>
      </div>

      {/* 步骤指示器 */}
      <div className="flex items-center gap-2 mb-6">
        {[
          { n: 1, label: '基础信息' },
          { n: 2, label: '选择文件' },
          { n: 3, label: 'Agent 分析' },
        ].map((s, i) => (
          <div key={s.n} className="flex items-center gap-2">
            <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs ${
              step === s.n ? 'bg-info/15 text-info border border-info/30'
              : step > s.n ? 'bg-pass/10 text-pass border border-pass/20'
              : 'bg-surface-2 text-gray-500 border border-border'
            }`}>
              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold ${
                step === s.n ? 'bg-info text-white'
                : step > s.n ? 'bg-pass text-white'
                : 'bg-surface-3 text-gray-500'
              }`}>{step > s.n ? '✓' : s.n}</span>
              {s.label}
            </div>
            {i < 2 && <div className={`w-8 h-px ${step > s.n ? 'bg-pass/30' : 'bg-border'}`} />}
          </div>
        ))}
      </div>

      {error && (
        <div className="mb-3 bg-red-900/30 border border-red-700/50 rounded-lg px-3 py-2">
          <span className="text-red-400 text-sm">{error}</span>
        </div>
      )}

      {/* Step 1: 基础信息 */}
      {step === 1 && (
        <div className="bg-surface-2 border border-border rounded-lg p-6 space-y-4">
          <div>
            <label className="block text-xs text-gray-400 mb-1">场景名称</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="如：员工全景档案-权限校验"
              className="w-full bg-surface-3 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">所属模块</label>
            <select
              value={module}
              onChange={e => setModule(e.target.value)}
              className="w-full bg-surface-3 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 focus:border-info outline-none"
            >
              <option value="">请选择模块...</option>
              {modules.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            <p className="text-[10px] text-gray-600 mt-1">模块对应 scenarios/ 下的目录路径</p>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">当前工作区</label>
            <div className="px-3 py-2 bg-surface-3 border border-border rounded-lg text-sm text-gray-400 font-mono">
              {wsName || '(未选择)'}
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={loading || !name.trim() || !module.trim()}
            className="px-4 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? '创建中...' : '下一步 →'}
          </button>
        </div>
      )}

      {/* Step 2: 选择文件 */}
      {step === 2 && (
        <div className="bg-surface-2 border border-border rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs text-gray-400">场景：{meta?.name}</span>
              <span className="text-[10px] text-gray-600 ml-2">ID: {meta?.id}</span>
            </div>
            <span className="text-[10px] text-gray-500">已选 {selectedFiles.size} 个文件</span>
          </div>

          <div className="flex gap-3">
            {/* 文件树 */}
            <div className="flex-1 bg-surface-1 border border-border rounded-lg p-2 max-h-80 overflow-y-auto">
              <div className="text-[10px] text-gray-500 mb-1 px-1">工作区文件（勾选加入基础信息包）</div>
              {files.length === 0 ? (
                <div className="text-center text-gray-600 text-xs py-8">
                  {wsName ? '加载中或工作区无文件' : '请先在顶栏选择工作区'}
                </div>
              ) : (
                files.map((f) => (
                  <label key={f.path} className="flex items-center gap-2 px-2 py-1 hover:bg-surface-3 rounded cursor-pointer">
                    <input
                      type="checkbox"
                      checked={selectedFiles.has(f.path)}
                      onChange={() => toggleFile(f.path)}
                      className="w-3 h-3 accent-info"
                    />
                    <span className="text-xs">{getFileIcon(f.path)}</span>
                    <span className={`text-xs font-mono ${f.is_delta ? 'text-yellow-500' : 'text-gray-300'}`}>
                      {f.path}
                    </span>
                    {f.is_delta && <span className="text-[9px] text-yellow-600">[delta]</span>}
                    <span className="text-[9px] text-gray-600 ml-auto">{(f.size / 1024).toFixed(1)}KB</span>
                  </label>
                ))
              )}
            </div>

            {/* 已选文件列表 */}
            <div className="w-56 flex-shrink-0 bg-surface-1 border border-border rounded-lg p-2 max-h-80 overflow-y-auto">
              <div className="text-[10px] text-gray-500 mb-1 px-1">基础信息包</div>
              {selectedFiles.size === 0 ? (
                <div className="text-center text-gray-600 text-xs py-8">未选择文件</div>
              ) : (
                Array.from(selectedFiles).map(path => (
                  <div key={path} className="flex items-center gap-1 px-2 py-1 hover:bg-surface-3 rounded group">
                    <span className="text-xs">{getFileIcon(path)}</span>
                    <span className="text-xs font-mono text-gray-400 truncate flex-1">{path}</span>
                    <button
                      onClick={() => toggleFile(path)}
                      className="text-red-500 text-[10px] opacity-0 group-hover:opacity-100"
                    >✕</button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 pt-2">
            <button
              onClick={() => setStep(1)}
              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 border border-border rounded-lg"
            >← 上一步</button>
            <button
              onClick={handleSaveInfoPack}
              disabled={loading || selectedFiles.size === 0}
              className="px-4 py-1.5 bg-info text-white rounded-lg text-xs font-medium hover:bg-info/90 disabled:opacity-40"
            >
              {loading ? '保存中...' : `保存并下一步 → (${selectedFiles.size} 文件)`}
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Agent 分析 */}
      {step === 3 && (
        <div className="bg-surface-2 border border-border rounded-lg p-6 space-y-4">
          <div className="text-center">
            <div className="text-3xl mb-2">🤖</div>
            <h3 className="text-sm font-medium text-gray-200">基础信息包已就绪</h3>
            <p className="text-xs text-gray-500 mt-1">
              场景 {meta?.id} 包含 {meta?.info_pack.length || 0} 个文件，Agent 将读取并生成测试场景 YAML 草稿。
            </p>
          </div>

          {/* 信息包文件列表 */}
          <div className="bg-surface-1 border border-border rounded-lg p-2 max-h-40 overflow-y-auto">
            {meta?.info_pack.map(path => (
              <div key={path} className="flex items-center gap-2 px-2 py-1">
                <span className="text-xs">{getFileIcon(path)}</span>
                <span className="text-xs font-mono text-gray-400">{path}</span>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2 justify-center">
            <button
              onClick={handleBackToStep2}
              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 border border-border rounded-lg"
            >← 修改文件</button>
            <button
              onClick={handleLaunchAgent}
              className="px-5 py-2 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90"
            >🚀 启动 Agent 分析</button>
            <button
              onClick={handleGoDAG}
              className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-200 border border-border rounded-lg"
            >🔀 DAG 编排</button>
          </div>
        </div>
      )}
    </div>
  );
}
