/** LarkBinding — T-703：绑定飞书页签
 *
 * 状态管理：
 *   unbound → 引导绑定流程 + 绑定按钮
 *   pending → 二维码模态框（轮询）
 *   bound   → 身份卡片 + scope 清单 + 解绑
 *   error   → 错误提示 + 重试
 */
import { useEffect, useState, useCallback } from 'react';
import { larkApi } from '../api';
import type { LarkStatus, LarkLoginResult } from '../api';

type BindState = 'loading' | 'unbound' | 'pending' | 'bound' | 'error';

export default function LarkBinding() {
  const [state, setState] = useState<BindState>('loading');
  const [status, setStatus] = useState<LarkStatus | null>(null);
  const [loginResult, setLoginResult] = useState<LarkLoginResult | null>(null);
  const [error, setError] = useState('');

  const loadStatus = useCallback(async () => {
    setState('loading');
    try {
      const s = await larkApi.status();
      setStatus(s);
      setState(s.bound ? 'bound' : 'unbound');
    } catch (e: any) {
      setError(String(e.message || e));
      setState('error');
    }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleLogin = async () => {
    try {
      const r = await larkApi.login();
      setLoginResult(r);
      if (r.phase === 'waiting') {
        setState('pending');
        if (r.verification_url) {
          window.open(r.verification_url, '_blank');
        }
        // 轮询：先 device-code 收尾（用户扫码后 token 落盘），再查状态确认
        const deviceCode = r.device_code || '';
        const poll = setInterval(async () => {
          try {
            if (deviceCode) {
              const c = await larkApi.complete(deviceCode);
              if (c.phase === 'completed') {
                clearInterval(poll);
                await loadStatus();
                return;
              }
            }
            const s = await larkApi.status();
            if (s.bound) {
              clearInterval(poll);
              setStatus(s);
              setState('bound');
            }
          } catch { /* 忽略轮询错误 */ }
        }, 3000);
        // 3 分钟后停止轮询
        setTimeout(() => clearInterval(poll), 180000);
      } else if (r.phase === 'completed') {
        setState('bound');
        await loadStatus();
      } else {
        setError(r.error || '授权失败');
        setState('error');
      }
    } catch (e: any) {
      setError(String(e.message || e));
      setState('error');
    }
  };

  const handleLogout = async () => {
    try {
      await larkApi.logout();
      setStatus(null);
      setLoginResult(null);
      setState('unbound');
    } catch (e: any) {
      setError(String(e.message || e));
    }
  };

  if (state === 'loading') {
    return (
      <div className="p-6 text-gray-500 text-sm">加载飞书绑定状态...</div>
    );
  }

  return (
    <div className="h-full flex flex-col p-6 max-w-2xl">
      <div className="flex items-center gap-2 mb-6">
        <span className="text-xl">🐦</span>
        <h2 className="text-lg font-semibold">绑定飞书账号</h2>
      </div>

      {/* 状态卡片 */}
      <div className="bg-surface-2 border border-border rounded-lg p-4 mb-4">
        {state === 'bound' && status && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="font-medium">已绑定</span>
              <span className="text-fs-body text-gray-500 ml-auto">
                配置目录: {status.config_dir}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-gray-500">身份</span>
                <span className="ml-2">{status.identity} / {status.identity_name}</span>
              </div>
              <div>
                <span className="text-gray-500">OpenID</span>
                <span className="ml-2 text-fs-body font-mono">{status.open_id}</span>
              </div>
              <div>
                <span className="text-gray-500">授权 scope</span>
                <span className="ml-2">{status.scopes?.length || 0} 项</span>
              </div>
            </div>
            <button onClick={handleLogout}
              className="mt-4 px-3 py-1.5 text-fs-body bg-red-900/30 text-red-400 rounded hover:bg-red-900/50 transition-colors">
              解绑
            </button>
          </div>
        )}

        {state === 'unbound' && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-gray-500" />
              <span className="font-medium">未绑定</span>
            </div>
            <p className="text-sm text-gray-400 mb-4">
              绑定飞书账号后，可在 Agent 对话中使用飞书 CLI 能力
              （文档/多维表格/妙记/聊天/日程等）。
            </p>
            <div className="space-y-2 text-sm text-gray-400 mb-4">
              <p>① 点击下方「绑定飞书」按钮</p>
              <p>② 在弹出的飞书授权页面完成授权</p>
              <p>③ 授权完成后页面自动刷新</p>
            </div>
            <button onClick={handleLogin}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">
              🔗 绑定飞书
            </button>
          </div>
        )}

        {state === 'pending' && loginResult?.verification_url && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
              <span className="font-medium">等待授权完成...</span>
            </div>
            {loginResult.qr_data_uri ? (
              <div className="mb-3 flex flex-col items-center gap-2">
                <img src={loginResult.qr_data_uri} alt="飞书授权二维码"
                  className="w-48 h-48 bg-white rounded-lg p-2" />
                <p className="text-fs-body text-gray-500">使用飞书 App 扫码完成授权</p>
              </div>
            ) : (
              <p className="text-sm text-gray-400 mb-3">
                请在弹出的页面中完成飞书授权。页面将自动检测授权状态。
              </p>
            )}
            <div className="bg-surface-1 rounded p-3 mb-3 text-fs-body break-all">
              <p className="text-gray-500 mb-1">授权 URL:</p>
              <a href={loginResult.verification_url} target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:underline">
                {loginResult.verification_url}
              </a>
            </div>
            <p className="text-fs-body text-gray-600">
              若页面未自动打开，请手动复制上方链接在浏览器中打开，或用飞书扫码。
            </p>
          </div>
        )}

        {state === 'error' && (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="font-medium text-red-400">出错</span>
            </div>
            <p className="text-sm text-red-400 mb-3">{error}</p>
            <button onClick={loadStatus}
              className="px-3 py-1.5 text-fs-body bg-surface-1 rounded hover:bg-surface-3 transition-colors">
              重试
            </button>
          </div>
        )}
      </div>

      {/* Scope 清单（已绑定时展开） */}
      {state === 'bound' && status?.scopes && status.scopes.length > 0 && (
        <div className="bg-surface-2 border border-border rounded-lg p-4">
          <h3 className="text-sm font-medium mb-2">📋 已授权权限</h3>
          <div className="space-y-1">
            {status.scopes.map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-fs-body text-gray-400">
                <span className="text-green-500">✅</span>
                <span className="font-mono">{s}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}