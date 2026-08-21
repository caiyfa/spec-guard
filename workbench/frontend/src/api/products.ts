/** api/products — T-1000 F3：产出反查（自 api.ts 按域拆分门面移植） */
import { request } from './core';

export interface ProductRecord {
  id: number;
  product_path: string;
  product_type: string;  // draft / scenario / plan / doc
  session_id: string;
  emp_no: string;
  workspace: string;
  fr_anchor: string;
  created_at: string;
}

export const productsApi = {
  bySession: (sid: string) =>
    request<{ products: ProductRecord[]; session_id: string }>(`/products/by-session/${encodeURIComponent(sid)}`),
  mine: (params?: { emp?: string; type?: string; from?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.emp) q.set('emp', params.emp);
    if (params?.type) q.set('type', params.type);
    if (params?.from) q.set('from', params.from);
    if (params?.limit) q.set('limit', String(params.limit));
    const qs = q.toString();
    return request<{ products: ProductRecord[]; emp_no: string }>(`/products/mine${qs ? `?${qs}` : ''}`);
  },
  trace: (path: string) =>
    request<{ records: ProductRecord[]; path: string }>(`/products/trace?path=${encodeURIComponent(path)}`),
};
