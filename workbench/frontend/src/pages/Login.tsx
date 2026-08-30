// 登录页：支持 Mock 登录（开发）和 UAC SSO 登录（生产），可自由切换
// 自动检测 fesso_access_token cookie（集团 UAC 跨子域共享），用户已在其他应用登录时无需重复操作
// UAC 回跳：登录成功后 UAC 重定向回本页并携带 token（参数名兼容 accessToken/token）

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { authApi, session } from '../api';
import { useBg } from '../theme';
import { getCookie, setCookie } from '../utils/cookie';

const UAC_TOKEN_COOKIE = 'fesso_access_token';

export default function Login() {
  const navigate = useNavigate();
  const bg = useBg();
  const [mode, setMode] = useState<'uac' | 'mock' | 'dual' | ''>('');
  const [uacBase, setUacBase] = useState('');
  const [ssoBase, setSsoBase] = useState('');
  const [ssoAppId, setSsoAppId] = useState('');
  const [empNo, setEmpNo] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [checkingCookie, setCheckingCookie] = useState(true);

  useEffect(() => {
    // ① UAC 回跳：URL 携带 token → 存 localStorage + 写回 cookie → 进入主页
    const params = new URLSearchParams(window.location.search);
    const token = params.get('accessToken') || params.get('access_token') || params.get('token') || '';
    if (token) {
      session.setToken(token);
      // 同步写回 fesso_access_token cookie（domain=.fehorizon.com），
      // 让同一浏览器下其他应用共享登录状态
      const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
      setCookie(UAC_TOKEN_COOKIE, token, {
        path: '/',
        domain: isLocalhost ? undefined : '.fehorizon.com',
        maxAge: 86400,
        sameSite: 'Lax',
      });
      // 整页重载进入主页（比 SPA navigate 更稳：避免登录后路由切换白屏风险）
      window.location.href = '/';
      return;
    }

    // ② 已有 token → 直接进主页
    if (session.getToken()) {
      window.location.href = '/';
      return;
    }

    // ③ 加载认证配置 + 检测 fesso_access_token cookie
    authApi.config()
      .then(c => {
        setUacBase(c.uac_base);
        setSsoBase(c.sso_base || '');
        setSsoAppId(c.sso_app_id || '');
        const m = c.auth_mode;
        setMode(m === 'dual' ? 'dual' : (m as 'uac' | 'mock'));

        // ④ 检测 fesso_access_token cookie（用户可能已在其他应用登录）
        const cookieToken = getCookie(UAC_TOKEN_COOKIE);
        if (cookieToken) {
          session.setToken(cookieToken);
          authApi.me()
            .then(() => {
              window.location.href = '/';
            })
            .catch(() => {
              // cookie token 无效，清除后显示登录页
              session.clearToken();
              setCheckingCookie(false);
              // ⑤ UAC 单模式：无有效 cookie 时自动跳转 UAC
              if (m === 'uac') {
                const redirect = encodeURIComponent(window.location.origin + '/login');
                const ssoUrl = c.sso_base ? `${c.sso_base}/login?app_id=${c.sso_app_id || ''}&protocol=oidc&redirect_uri=${redirect}` : `${c.uac_base}/api/authing/login?redirectURL=${redirect}`;
                window.location.href = ssoUrl;
              }
            });
          return;
        }

        setCheckingCookie(false);

        // ⑥ 无 cookie，UAC 单模式自动跳转 UAC 登录
        if (m === 'uac') {
          const redirect = encodeURIComponent(window.location.origin + '/login');
          const ssoUrl = c.sso_base ? `${c.sso_base}/login?app_id=${c.sso_app_id || ''}&protocol=oidc&redirect_uri=${redirect}` : `${c.uac_base}/api/authing/login?redirectURL=${redirect}`;
          window.location.href = ssoUrl;
        }
      })
      .catch(() => {
        setError('无法连接后端服务');
        setCheckingCookie(false);
      });
  }, [navigate]);

  const gotoUac = () => {
    const redirect = encodeURIComponent(`${window.location.origin}/login`);
    if (ssoBase) {
      window.location.href = `${ssoBase}/login?app_id=${ssoAppId}&protocol=oidc&redirect_uri=${redirect}`;
    } else {
      window.location.href = `${uacBase}/api/authing/login?redirectURL=${redirect}`;
    }
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
    <div className={`min-h-screen flex items-center justify-center relative overflow-hidden ${bg.image ? '' : 'bg-surface-1'}`}>
      {/* K-043：氛围光晕背景（主题色渐变，深主题可见/浅主题淡雅） */}
      <div className="absolute inset-0 pointer-events-none" style={{
        background: `radial-gradient(600px 400px at 20% 15%, rgb(var(--info) / 0.12), transparent 60%),
                     radial-gradient(700px 500px at 85% 80%, rgb(var(--blocked) / 0.10), transparent 60%)`,
      }} />
      <div className="w-96 relative bg-surface-2/80 border border-border rounded-2xl p-8 backdrop-blur-sm" style={{ boxShadow: 'var(--shadow)' }}>
        <div className="text-center mb-6">
          <h1 className="text-xl font-bold brand-gradient">🛡 SpecGuard</h1>
          <p className="text-fs-body text-gray-500 mt-1">契约驱动的场景测试与AI智能编排平台</p>
        </div>

        {error && (
          <div className="mb-4 px-3 py-2 rounded-lg text-sm bg-fail/15 text-fail border border-fail/40">
            {error}
          </div>
        )}

        {/* dual 模式：同时展示 mock 登录和 UAC SSO 登录，自由切换 */}
        {mode === 'dual' && (
          <div>
            <div className="space-y-3 mb-4">
              <p className="text-fs-body text-skip text-center">
                开发模式，输入工号直接登录
              </p>
              <input
                value={empNo}
                onChange={e => setEmpNo(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && mockLogin()}
                placeholder="工号 / AD 账号（如 90024166 或 caiyunfei）"
                className="input w-full"
              />
              <input
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && mockLogin()}
                placeholder="姓名（可选）"
                className="input w-full"
              />
              <button
                onClick={mockLogin}
                disabled={!empNo.trim() || busy}
                className="btn-primary w-full py-2.5"
              >
                {busy ? '登录中…' : 'Mock 登录'}
              </button>
            </div>
            <div className="flex items-center gap-2 my-3">
              <div className="flex-1 border-t border-border"></div>
              <span className="text-fs-body text-gray-400">或</span>
              <div className="flex-1 border-t border-border"></div>
            </div>
            <div>
              <p className="text-fs-body text-gray-400 text-center mb-3">
                使用集团统一身份认证（Authing）登录
              </p>
              <button
                onClick={gotoUac}
                className="btn-primary w-full py-2.5"
              >
                前往集团 SSO 登录
              </button>
            </div>
          </div>
        )}

        {mode === 'uac' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-400 text-center">
              使用集团统一身份认证（Authing）登录
            </p>
            <button
              onClick={gotoUac}
              className="btn-primary w-full py-2.5"
            >
              前往集团 SSO 登录
            </button>
          </div>
        )}

        {mode === 'mock' && (
          <div className="space-y-3">
            <p className="text-fs-body text-skip text-center">
              开发模式（SG_AUTH_MODE=mock），输入工号直接登录
            </p>
            <input
              value={empNo}
              onChange={e => setEmpNo(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && mockLogin()}
              placeholder="工号 / AD 账号（如 90024166 或 caiyunfei）"
              className="input w-full"
            />
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && mockLogin()}
              placeholder="姓名（可选）"
              className="input w-full"
            />
            <button
              onClick={mockLogin}
              disabled={!empNo.trim() || busy}
              className="btn-primary w-full py-2.5"
            >
              {busy ? '登录中…' : '登录'}
            </button>
          </div>
        )}

        {checkingCookie && (
          <div className="text-center text-gray-500 text-sm">检测登录状态…</div>
        )}

        {mode === '' && !error && !checkingCookie && (
          <div className="text-center text-gray-500 text-sm">加载认证配置…</div>
        )}
      </div>
    </div>
  );
}
