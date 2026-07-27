// 登录页：UAC 跳转登录（生产）+ mock 登录（开发降级）
// UAC 回跳：登录成功后 UAC 重定向回本页并携带 token（参数名兼容 accessToken/token）

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi, session } from '../api';

export default function Login() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'uac' | 'mock' | ''>('');
  const [uacBase, setUacBase] = useState('');
  const [empNo, setEmpNo] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // ① UAC 回跳：URL 携带 token → 存 sessionStorage → 清 query → 进入主页
    const params = new URLSearchParams(window.location.search);
    const token = params.get('accessToken') || params.get('access_token') || params.get('token') || '';
    if (token) {
      session.setToken(token);
      // 整页重载进入主页（比 SPA navigate 更稳：避免登录后路由切换白屏风险）
      window.location.href = '/';
      return;
    }
    // ② 已登录 → 直接进主页
    if (session.getToken()) {
      window.location.href = '/';
      return;
    }
    // ③ 加载认证配置
    authApi.config()
      .then(c => {
        setMode(c.auth_mode as 'uac' | 'mock');
        setUacBase(c.uac_base);
      })
      .catch(() => setError('无法连接后端服务'));
  }, [navigate]);

  const gotoUac = () => {
    const redirect = encodeURIComponent(`${window.location.origin}/login`);
    window.location.href = `${uacBase}/api/authing/login?redirectURL=${redirect}`;
  };

  const EMP_NO_RE = /^[A-Za-z0-9_-]+$/;

  const mockLogin = async () => {
    const emp = empNo.trim();
    if (!emp || busy) return;
    // 工号将编进 token 并放入 HTTP header（仅支持 ASCII），中文/特殊字符必须前端拦截
    if (!EMP_NO_RE.test(emp)) {
      setError('工号仅支持字母、数字、下划线、连字符（不能含中文或空格）');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const r = await authApi.mockLogin(emp, name.trim());
      if (r.ok && r.token) {
        session.setToken(r.token);
        // 整页重载进入主页（避免 SPA 切换白屏风险）
        window.location.href = '/';
      } else {
        setError('登录失败');
      }
    } catch (e: any) {
      setError(e.message || '登录失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-1">
      <div className="w-96 bg-surface-2 border border-border rounded-xl p-8">
        <div className="text-center mb-6">
          <h1 className="text-xl font-bold text-info">🛡 SpecGuard</h1>
          <p className="text-xs text-gray-500 mt-1">契约驱动的后端场景测试工作台</p>
        </div>

        {error && (
          <div className="mb-4 px-3 py-2 rounded-lg text-sm bg-red-900/30 text-red-400 border border-red-700/50">
            {error}
          </div>
        )}

        {mode === 'uac' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-400 text-center">
              使用集团统一身份认证（Authing）登录
            </p>
            <button
              onClick={gotoUac}
              className="w-full py-2.5 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 transition-colors"
            >
              前往集团 SSO 登录
            </button>
          </div>
        )}

        {mode === 'mock' && (
          <div className="space-y-3">
            <p className="text-xs text-yellow-500 text-center">
              开发模式（SG_AUTH_MODE=mock），输入工号直接登录
            </p>
            <input
              value={empNo}
              onChange={e => setEmpNo(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && mockLogin()}
              placeholder="工号 / AD 账号（如 90024166 或 caiyunfei）"
              className="w-full bg-surface-1 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none"
            />
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && mockLogin()}
              placeholder="姓名（可选）"
              className="w-full bg-surface-1 border border-border rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:border-info outline-none"
            />
            <button
              onClick={mockLogin}
              disabled={!empNo.trim() || busy}
              className="w-full py-2.5 bg-info text-white rounded-lg text-sm font-medium hover:bg-info/90 disabled:opacity-40 transition-colors"
            >
              {busy ? '登录中…' : '登录'}
            </button>
          </div>
        )}

        {mode === '' && !error && (
          <div className="text-center text-gray-500 text-sm">加载认证配置…</div>
        )}
      </div>
    </div>
  );
}
