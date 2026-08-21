// useChatOptions.ts — 介入工作区群/日期选项（T-948 从 FeishuPool 提取复用）。
// days 来自材料池已有 chat 快照文件；watch 授权群补充（无快照时 days 为空）。

import { useEffect, useState } from 'react';
import {
  type FeishuPoolMaterial,
  type FeishuWatch,
} from '../api';

export type ChatOption = { chat_sha8: string; name: string; days: string[]; kind?: string };

export async function sha256Hex8(input: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf))
    .map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 8);
}

export function useChatOptions(materials: FeishuPoolMaterial[],
                               watchCfg: FeishuWatch | null): ChatOption[] {
  const [options, setOptions] = useState<ChatOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    const map = new Map<string, ChatOption>();
    materials.filter(m => m.type === 'chat').forEach(m => {
      const parts = m.file.split('/');
      if (parts.length !== 3) return;
      const sha8 = parts[1];
      const day = parts[2].replace(/\.md$/, '');
      const existing = map.get(sha8);
      if (existing) {
        existing.days.push(day);
      } else {
        map.set(sha8, { chat_sha8: sha8, name: m.title || sha8, days: [day] });
      }
    });
    (async () => {
      if (watchCfg?.chats?.length) {
        // watch 授权群补充（无快照时 days 为空）；T-990：带出群类型标签
        const watchKindBySha8 = new Map<string, string>();
        const entries = await Promise.all(
          watchCfg.chats.map(async (c: any) => {
            const cid = c.chat_id;
            if (!cid) return null;
            const sha8 = await sha256Hex8(cid);
            if (c.kind) watchKindBySha8.set(sha8, String(c.kind));
            return { sha8, name: c.name || sha8 };
          }));
        for (const e of entries) {
          if (!e || map.has(e.sha8)) continue;
          map.set(e.sha8, { chat_sha8: e.sha8, name: e.name, days: [],
                            kind: watchKindBySha8.get(e.sha8) });
        }
        // 已有快照的群也补 watch 侧 kind（快照文件名不带类型）
        for (const [sha8, kind] of watchKindBySha8) {
          const existing = map.get(sha8);
          if (existing && !existing.kind) existing.kind = kind;
        }
      }
      const opts = Array.from(map.values());
      opts.forEach(c => { c.days = Array.from(new Set(c.days)).sort(); });
      if (!cancelled) setOptions(opts);
    })();
    return () => { cancelled = true; };
  }, [materials, watchCfg]);
  return options;
}
