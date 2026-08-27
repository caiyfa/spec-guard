/** scenarioReader 纯函数测试（T-1023）——样例结构取自 HI-PERM-002.yaml 实物 */
import { describe, expect, it } from 'vitest';
import {
  buildAnchorHint, describeStep, describeVerify, extractSectionComments,
  isScenarioDoc, unwrapReaderStep,
} from './scenarioReader';

const SAMPLE = `id: HI-PERM-002
title: corp=PART(非空) 主路
doc:
  given: g
  when: w
  then: t
  covers: [FR-005, FR-007]
  related_ac: [AC-005]
flow:
  # ① 动态账号解析：K-055 标准用法
  #    若无候选 → SkipScenario
  - tool: {use: resolve_account, with: {resource_code: VIEW_HISTORY}, save: acct}

  # ② python 校验
  - python:
      script: |
        acct = ns.get('acct', {}) or {}
        # 拼 SQL 注入片段（脚本内注释，不得串到下一步）
        ns['x'] = 1
      save: corp_csv

  # ⑤ 业务调用
  - call:
      as: partCorp
      service: hr_tdm
      method: POST
      path: /api/history/inventory/query
      json: {current: 1, size: 50}
      save: query_resp

  # ⑥ DB 校对
  - db_query:
      sql: |
        SELECT COUNT(*) AS total FROM tdm_snap_profile
      save: db_total
verify:
  # 接口响应包装协议正确
  - status: {of: query_resp, eq: 200}
  - json: {of: query_resp, path: "$.status", eq: "200"}
  # 主路断言
  - json: {of: db_total, path: "$[0].total", len_gt: 0}
`;

describe('unwrapReaderStep', () => {
  it('tool 信封拆解：use/with/save 平铺', () => {
    const s = unwrapReaderStep({ tool: { use: 'resolve_account', with: { resource_code: 'VIEW_HISTORY' }, save: 'acct' } });
    expect(s.type).toBe('resolve_account');
    expect(s.body.resource_code).toBe('VIEW_HISTORY');
    expect(s.body.save).toBe('acct');
  });
  it('裸步骤直出', () => {
    const s = unwrapReaderStep({ precheck_permission: { account: 'default' } });
    expect(s.type).toBe('precheck_permission');
    expect(s.body.account).toBe('default');
  });
});

describe('extractSectionComments', () => {
  it('flow：注释块对齐步骤，脚本内注释不串行', () => {
    const c = extractSectionComments(SAMPLE, 'flow');
    expect(c).toHaveLength(4);
    expect(c[0]).toContain('动态账号解析');
    expect(c[0]).toContain('SkipScenario');
    expect(c[1]).toBe('② python 校验');
    expect(c[2]).toBe('⑤ 业务调用');
    expect(c[3]).toBe('⑥ DB 校对');
    // 脚本字面块内的 # 行（缩进更深）不归任何步骤
    expect(c.join('\n')).not.toContain('拼 SQL 注入片段');
  });
  it('verify：首个注释归第一条断言，无注释断言为空串', () => {
    const c = extractSectionComments(SAMPLE, 'verify');
    expect(c).toHaveLength(3);
    expect(c[0]).toBe('接口响应包装协议正确');
    expect(c[1]).toBe('');
    expect(c[2]).toBe('主路断言');
  });
  it('段不存在时返回空', () => {
    expect(extractSectionComments('id: x\n', 'flow')).toEqual([]);
  });
});

describe('describeStep', () => {
  it('tool → 工具调用 + 参数行 + save', () => {
    const d = describeStep({ tool: { use: 'fetch_permission', with: { account: 'partCorp' }, save: 'scope' } });
    expect(d.typeLabel).toBe('权限预言');
    expect(d.title).toBe('fetch_permission');
    expect(d.lines).toEqual(['account: partCorp']);
    expect(d.save).toBe('scope');
  });
  it('call → METHOD path + 服务/账号 + 报文折叠', () => {
    const d = describeStep({ call: { service: 'hr_tdm', method: 'post', path: '/api/x', as: 'partCorp', json: { a: 1 }, save: 'r' } });
    expect(d.icon).toBe('🌐');
    expect(d.title).toBe('POST /api/x');
    expect(d.lines).toContain('服务 hr_tdm');
    expect(d.lines).toContain('账号 partCorp');
    expect(d.code?.lang).toBe('json');
    expect(d.code?.text).toContain('"a": 1');
  });
  it('python/db_query → 脚本与 SQL 折叠', () => {
    const p = describeStep({ python: { script: 'x = 1', save: 'v' } });
    expect(p.code).toEqual({ lang: 'python', text: 'x = 1' });
    const q = describeStep({ db_query: { sql: 'SELECT 1', note: '校对总数' } });
    expect(q.title).toBe('校对总数');
    expect(q.code?.lang).toBe('sql');
  });
});

describe('describeVerify', () => {
  it('status/json/oracle 友好文案', () => {
    expect(describeVerify({ status: { of: 'resp', eq: 200 } }).text).toBe('HTTP 状态 = 200（resp）');
    expect(describeVerify({ json: { of: 'resp', path: '$.status', eq: '200' } }).text)
      .toBe('$.status = 200（resp）');
    expect(describeVerify({ json: { of: 's', path: '$.corp_codes', len_gte: 1 } }).text)
      .toBe('$.corp_codes 长度 ≥ 1（s）');
    expect(describeVerify({ json: { of: 'r', path: '$.data.records', not_null: true } }).text)
      .toBe('$.data.records 非空（r）');
    const o = describeVerify({ oracle: { name: 'snapshot_frozen', with: { a: 1 } } });
    expect(o.text).toBe('DB 校对：snapshot_frozen');
    expect(o.code?.text).toContain('"a": 1');
  });
});

describe('buildAnchorHint / isScenarioDoc', () => {
  it('hint 含文件路径、id、标题与 call 路径', () => {
    const data = {
      id: 'HI-PERM-002', title: '主路', doc: {},
      flow: [{ call: { service: 'hr_tdm', method: 'POST', path: '/api/history/inventory/query' } }],
    };
    const hint = buildAnchorHint(data, 'drafts/HI-PERM-002.yaml');
    expect(hint).toContain('HI-PERM-002');
    expect(hint).toContain('/api/history/inventory/query');
    expect(hint).toContain('hr_tdm');
  });
  it('场景判定：flow+doc 双有才算', () => {
    expect(isScenarioDoc({ id: 'x', doc: {}, flow: [] })).toBe(true);
    expect(isScenarioDoc({ gateway: 'http://x' })).toBe(false);
    expect(isScenarioDoc(null)).toBe(false);
    expect(isScenarioDoc([1, 2])).toBe(false);
  });
});
