import { describe, it, expect, beforeEach } from 'vitest';
import { _store, ensureSideStore } from './sessionStore';

/** 每例前复位 live 字段与分侧快照（模块级单例，用例间隔离） */
beforeEach(() => {
  _store.side = '';
  _store.sides = {};
  _store.buffer = [];
  _store.messages = [];
  _store.loading = false;
  _store.sessionId = '';
  _store.sessionTitle = '';
  _store.stats = null;
  _store.turnInfo = '';
  _store.error = '';
  _store.planItems = [];
  _store.ctxUsage = null;
  _store.readingFeed = [];
  _store.writingFeed = [];
});

describe('ensureSideStore（T-1039 双菜单分侧交换）', () => {
  it('首次挂载：空白就位，标记本侧，未发生交换', () => {
    expect(ensureSideStore('test')).toBe(true);  // side '' → 'test' 属异侧
    expect(_store.side).toBe('test');
    expect(_store.messages).toEqual([]);
    expect(ensureSideStore('test')).toBe(false);  // 幂等：同侧不再交换
  });

  it('异侧切换：stash 对侧 live，本侧空白就位，事件缓冲清空', () => {
    ensureSideStore('test');
    _store.messages = [{ role: 'user', content: '测试侧消息' }];
    _store.sessionId = 'SID-TEST';
    _store.loading = true;
    _store.buffer = [{ type: 'assistant', session_id: 'SID-TEST' }];

    expect(ensureSideStore('product')).toBe(true);
    expect(_store.side).toBe('product');
    expect(_store.messages).toEqual([]);       // 本侧（product）无快照 → 空白
    expect(_store.sessionId).toBe('');
    expect(_store.loading).toBe(false);
    expect(_store.buffer).toEqual([]);          // 异侧缓冲不得灌入本侧
    // 对侧快照完整 stash
    expect(_store.sides.test.sessionId).toBe('SID-TEST');
    expect(_store.sides.test.loading).toBe(true);
    expect(_store.sides.test.messages).toHaveLength(1);
  });

  it('切回：恢复本侧快照（run 进行中的 loading/sessionId 不丢）', () => {
    ensureSideStore('test');
    _store.sessionId = 'SID-TEST';
    _store.loading = true;
    _store.messages = [{ role: 'user', content: 'A' }];
    ensureSideStore('product');
    _store.sessionId = 'SID-PROD';
    _store.messages = [{ role: 'user', content: 'B' }];

    expect(ensureSideStore('test')).toBe(true);
    expect(_store.sessionId).toBe('SID-TEST');
    expect(_store.loading).toBe(true);
    expect(_store.messages[0].content).toBe('A');
    // product 侧快照也已 stash，可再切回
    expect(_store.sides.product.sessionId).toBe('SID-PROD');
  });

  it('连接级与角色级字段不分侧（wsState/purposes 不随交换重置）', () => {
    ensureSideStore('test');
    _store.wsState = 'open';
    _store.purposes = [{ id: 'test_workbench' } as any];
    ensureSideStore('product');
    expect(_store.wsState).toBe('open');
    expect(_store.purposes).toHaveLength(1);
  });
});
