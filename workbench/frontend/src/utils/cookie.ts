/** Cookie 工具（集团 UAC SSO 跨子域共享：fesso_access_token / fesso_refresh_token） */

export function getCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : '';
}

export function setCookie(
  name: string,
  value: string,
  options?: { domain?: string; path?: string; maxAge?: number; sameSite?: 'Lax' | 'Strict' | 'None' },
): void {
  const parts: string[] = [`${encodeURIComponent(name)}=${encodeURIComponent(value)}`];
  if (options?.path) parts.push(`path=${options.path}`);
  if (options?.domain) parts.push(`domain=${options.domain}`);
  if (options?.maxAge !== undefined) parts.push(`max-age=${options.maxAge}`);
  if (options?.sameSite) parts.push(`SameSite=${options.sameSite}`);
  document.cookie = parts.join('; ');
}

export function removeCookie(name: string, options?: { domain?: string; path?: string }): void {
  const parts: string[] = [`${encodeURIComponent(name)}=`];
  if (options?.path) parts.push(`path=${options.path}`);
  if (options?.domain) parts.push(`domain=${options.domain}`);
  parts.push('max-age=0');
  document.cookie = parts.join('; ');
}