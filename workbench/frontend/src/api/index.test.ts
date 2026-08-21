import { describe, it, expect } from 'vitest';
import * as api from './index';

/** T-997 拆分完整性守卫：api.ts → api/*.ts 后，门面导出面一个都不能少。
 *  此处枚举的是各域模块的运行时导出（interface/type 无运行时形态不入列）——
 *  任何域模块漏挂 export *、导出改名、index 漏行都会当场红灯。 */
const EXPECTED_EXPORTS: Record<string, string> = {
  // core
  WORKSPACE_CHANGED_EVENT: 'string', session: 'object', apiRequest: 'function',
  encodeWorkspaceHeader: 'function', request: 'function',
  uploadFile: 'function', uploadFiles: 'function',
  // 各域 Api 对象
  authApi: 'object', usersApi: 'object', menusApi: 'object', rolesApi: 'object',
  scenariosApi: 'object', runsApi: 'object', plansApi: 'object',
  specApi: 'object', rebaseApi: 'object', referenceApi: 'object',
  workspaceApi: 'object', agentApi: 'object', settingsApi: 'object', modelApi: 'object',
  draftsApi: 'object', coverageApi: 'object', attributionApi: 'object', scenarioApi: 'object',
  schedulesApi: 'object', notifyApi: 'object', lifecycleApi: 'object', zentaoApi: 'object',
  specflowApi: 'object', graphApi: 'object', lineageApi: 'object',
  auditApi: 'object', skillsApi: 'object', larkApi: 'object',
  knowledgeApi: 'object', feishuPoolApi: 'object', systemsApi: 'object',
  productsApi: 'object',
};

describe('api/index 门面（T-997 拆分完整性）', () => {
  for (const [name, kind] of Object.entries(EXPECTED_EXPORTS)) {
    it(`导出 ${name}`, () => {
      expect(typeof (api as Record<string, unknown>)[name]).toBe(kind);
    });
  }

  it('apiRequest 与 request 同一函数（core 单例）', () => {
    expect(api.apiRequest).toBe(api.request);
  });
});
