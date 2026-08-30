// ModelSetupModal.tsx — T-954 模型缺失就地配置弹层（体验基线②③）：
// 「重新 AI 分类」等动作因未配置 text/vision 模型失败时，不报错踢用户去设置页，
// 而是直接弹出本组件就地配置（预填可改的默认值），保存后自动重试原动作。
// 用途绑定靠 name 别名（T-951b：name=text/vision 即被 get_model 命中）；
// 已有同名配置时走更新（key 掩码规则：空/含***跳过不覆盖——后端防线）。

import { useEffect, useState } from 'react';
import { modelApi, type ModelConfig } from '../api';

const PRESETS: Record<string, { label: string; baseUrl: string; model: string }> = {
  text: { label: '文本模型（话题分类/编辑重生成）', baseUrl: 'https://api.minimaxi.com', model: 'MiniMax-M3' },
  vision: { label: '视觉模型（图片转述）', baseUrl: 'https://api.minimaxi.com', model: 'MiniMax-M3' },
};

export default function ModelSetupModal({ purpose, onClose, onConfigured }: {
  purpose: 'text' | 'vision';
  onClose: () => void;
  onConfigured: () => void;        // 保存成功后自动重试原动作
}) {
  const preset = PRESETS[purpose];
  const [baseUrl, setBaseUrl] = useState(preset.baseUrl);
  const [model, setModel] = useState(preset.model);
  const [apiKey, setApiKey] = useState('');
  const [existing, setExisting] = useState<ModelConfig | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  // 已有同名配置（name=purpose）→ 预填并走更新
  useEffect(() => {
    modelApi.list().then(r => {
      const hit = (r.models || []).find(m => m.name === purpose);
      if (hit) {
        setExisting(hit);
        if (hit.base_url) setBaseUrl(hit.base_url);
        if (hit.model) setModel(hit.model);
      }
    }).catch(() => { /* 列表失败不阻断手填 */ });
  }, [purpose]);

  const save = async () => {
    // 已配置 Key 的更新场景允许留空（后端 _is_key_unchanged：空串跳过不覆盖）
    if (!baseUrl.trim() || !model.trim()
        || (!apiKey.trim() && !(existing?.has_api_key))) {
      setError('地址 / 模型名 / API Key 均需填写' + (existing?.has_api_key ? '（Key 可留空保持现有）' : ''));
      return;
    }
    setBusy('save'); setError('');
    try {
      const payload = {
        name: purpose,               // 用途别名——get_model("text"/"vision") 命中
        base_url: baseUrl.trim(),
        api_key: apiKey.trim(),
        model: model.trim(),
        timeout: '120', temperature: '0.7',
        max_context_tokens: '', max_output_tokens: '',
        thinking_enabled: 'false', reasoning_effort: '',
      };
      if (existing) {
        await modelApi.update(existing.id, payload);
      } else {
        await modelApi.create(payload);
      }
      onClose();
      onConfigured();
    } catch (e: any) { setError(e.message); } finally { setBusy(''); }
  };

  const input = 'bg-surface-3 border border-border rounded px-2 py-1.5 text-fs-body text-gray-200 outline-none focus:border-info w-full';
  const btn = 'px-3 py-1.5 rounded text-fs-body font-medium bg-info/15 text-info hover:bg-info/25 disabled:opacity-40';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}>
      <div className="w-[440px] max-w-[92vw] border border-border rounded-lg p-4 bg-surface-2"
        onClick={e => e.stopPropagation()}>
        <h3 className="text-fs-lead font-semibold mb-1">配置{preset.label}</h3>
        <div className="text-fs-body text-gray-500 mb-3">
          该用途尚未配置模型，填写后保存将自动重试操作（配置保存为「{purpose}」用途绑定；
          MiniMax M3 的 Key 在 platform.minimaxi.com 获取，也可改用任意 OpenAI 兼容服务）
        </div>
        {error && <div className="mb-2 px-3 py-2 rounded bg-fail/12 text-fail text-fs-body">{error}</div>}
        <div className="space-y-2">
          <label className="block">
            <span className="text-fs-body text-gray-500">Base URL（OpenAI 兼容端点）</span>
            <input className={input} value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              placeholder="https://api.minimaxi.com" />
          </label>
          <label className="block">
            <span className="text-fs-body text-gray-500">模型名</span>
            <input className={input} value={model}
              onChange={e => setModel(e.target.value)}
              placeholder="MiniMax-M3" />
          </label>
          <label className="block">
            <span className="text-fs-body text-gray-500">API Key{existing?.has_api_key ? '（已配置，填写即覆盖）' : ''}</span>
            <input className={input} type="password" value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder={existing?.has_api_key ? '留空保持现有 Key' : 'sk-…'} />
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="px-3 py-1.5 rounded text-fs-body text-gray-400 hover:text-gray-200"
            onClick={onClose}>取消</button>
          <button className={btn} disabled={busy === 'save'} onClick={save}>
            {busy === 'save' ? '保存中…' : '保存并重试'}
          </button>
        </div>
      </div>
    </div>
  );
}
