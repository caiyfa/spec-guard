import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { session, request, apiRequest, encodeWorkspaceHeader, WORKSPACE_CHANGED_EVENT, uploadFile, uploadFiles } from './core';

/** fetch 打桩助手：返回指定 status/json 的 Response */
function stubFetch(status: number, body: unknown) {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return {
      status, ok: status >= 200 && status < 300,
      statusText: `S${status}`,
      json: async () => body,
    } as Response;
  }));
  return calls;
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});
afterEach(() => vi.unstubAllGlobals());

describe('session 存储', () => {
  it('token 读写清除走 localStorage sg_token', () => {
    expect(session.getToken()).toBe('');
    session.setToken('t-1');
    expect(session.getToken()).toBe('t-1');
    session.clearToken();
    expect(session.getToken()).toBe('');
  });

  it('setWorkspace 广播 WORKSPACE_CHANGED_EVENT 并持久化', () => {
    const seen: string[] = [];
    window.addEventListener(WORKSPACE_CHANGED_EVENT, (e) => seen.push((e as CustomEvent).detail));
    session.setWorkspace('人才发展');
    expect(session.getWorkspace()).toBe('人才发展');
    expect(seen).toEqual(['人才发展']);
  });
});

describe('request 鉴权与错误路径', () => {
  it('携带 token 与编码后的工作区头', async () => {
    session.setToken('tk');
    session.setWorkspace('人才发展');
    const calls = stubFetch(200, { ok: true });
    const r = await request<{ ok: boolean }>('/x');
    expect(r.ok).toBe(true);
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer tk');
    expect(headers['X-SG-Workspace']).toBe(encodeWorkspaceHeader('人才发展'));
    expect(calls[0].url).toBe('/api/x');
  });

  it('401：清 token 并抛错', async () => {
    session.setToken('tk');
    stubFetch(401, { detail: 'expired' });
    await expect(request('/x')).rejects.toThrow('未登录或登录已过期');
    expect(session.getToken()).toBe('');
  });

  it('非 2xx：字符串 detail 直接作为错误消息', async () => {
    stubFetch(400, { detail: 'bad request 人话' });
    await expect(request('/x')).rejects.toThrow('bad request 人话');
  });

  it('非 2xx：结构化 detail（422 {message, findings}）取 message 字段', async () => {
    stubFetch(422, { detail: { message: '合规校验未通过', findings: [{ level: 'ERROR' }] } });
    await expect(request('/x')).rejects.toThrow('合规校验未通过');
  });

  it('非 ASCII token 预检：不发请求直接按 401 处理', async () => {
    session.setToken('中文token');
    const calls = stubFetch(200, {});
    await expect(request('/x')).rejects.toThrow('会话 token 非法');
    expect(calls.length).toBe(0);
    expect(session.getToken()).toBe('');
  });

  it('apiRequest 是 request 的别名（同一函数）', () => {
    expect(apiRequest).toBe(request);
  });
});

describe('uploadFiles 上传', () => {
  it('单文件字段名 file，附 fields 入 FormData，带鉴权头不带 JSON Content-Type', async () => {
    session.setToken('tk');
    const calls = stubFetch(200, { ok: true });
    const file = new File(['abc'], 'a.txt');
    await uploadFile('/upload', file);
    const init = calls[0].init;
    const headers = init.headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer tk');
    expect(headers['Content-Type']).toBeUndefined();  // boundary 由浏览器生成
    const fd = init.body as FormData;
    expect(fd.get('file')).toBeTruthy();
  });

  it('多文件字段名 files，fields 逐键附加', async () => {
    const calls = stubFetch(200, { ok: true });
    const files = [new File(['1'], 'a.txt'), new File(['2'], 'b.txt')];
    await uploadFiles('/upload', files, { kind: 'chat' });
    const fd = calls[0].init.body as FormData;
    expect(fd.getAll('files').length).toBe(2);
    expect(fd.get('kind')).toBe('chat');
  });

  it('上传 401 同样清 token', async () => {
    session.setToken('tk');
    stubFetch(401, {});
    await expect(uploadFiles('/upload', [new File(['1'], 'a.txt')])).rejects.toThrow('未登录或登录已过期');
    expect(session.getToken()).toBe('');
  });
});
