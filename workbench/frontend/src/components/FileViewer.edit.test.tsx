/** T-1027 F1 返修：草稿编辑落在结构化预览（DraftFormEditor 复用场景编辑器），非裸 YAML。
 * ScenarioFormEditor 以桩件替身——捕获 props 驱动保存成功/失败两条路径。 */
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

const sfeProps: Record<string, unknown> = {};
vi.mock('./ScenarioFormEditor', () => ({
  default: (props: any) => {   // eslint-disable-line @typescript-eslint/no-explicit-any
    Object.assign(sfeProps, props);
    return (
      <div data-testid="sfe">
        <div data-testid="sfe-yaml">{props.yamlContent}</div>
        <div data-testid="sfe-sid">{props.scenarioId}</div>
        <button onClick={() => {
          Promise.resolve(props.onSave(props.yamlContent + '\n# 表单改动'))
            .catch((e: Error) => { sfeProps._err = e.message; });
        }}>__save_ok</button>
        <button onClick={() => {
          Promise.resolve(props.onSave('broken: ['))
            .catch((e: Error) => { sfeProps._err = e.message; });
        }}>__save_reject</button>
      </div>
    );
  },
}));

import FileViewer from './FileViewer';

afterEach(cleanup);

const SCENARIO_YAML = `id: HI-PERM-002
version: 1.0
title: corp=PART 主路
doc:
  given: SIT 环境
  when: 调用接口
  then: HTTP 200
flow:
  - step: call
    args: {path: /api/x}
verify:
  - jsonpath: $.status
    equals: '200'
`;

const OK_OUTCOME = {
  ok: true,
  message: '对话已感知本次编辑与校验结论',
  verdict: 'PASS',
  summaryError: 0,
  summaryWarn: 2,
  findings: [{ level: 'WARN', rule: 'DIM_MAP', message: '提示一下' }],
};

beforeEach(() => {
  localStorage.clear();
  for (const k of Object.keys(sfeProps)) delete sfeProps[k];
});

test('可编辑草稿：✏️ 编辑进结构化表单（非裸 YAML 编辑器）', async () => {
  const onSave = vi.fn().mockResolvedValue(OK_OUTCOME);
  render(<FileViewer path="HI-PERM-002.yaml" content={SCENARIO_YAML} canEdit onSaveContent={onSave} />);
  fireEvent.click(screen.getByText('✏️ 编辑'));
  // 场景编辑器桩在屏、携带当前落盘文本与场景 ID；参考 registries 为空数组降级形态
  await waitFor(() => expect(screen.getByTestId('sfe')).toBeTruthy());
  expect(screen.getByTestId('sfe-yaml').textContent).toBe(SCENARIO_YAML);
  expect(screen.getByTestId('sfe-sid').textContent).toContain('HI-PERM-002');
  expect(sfeProps.allScenarios).toEqual([]);
});

test('结构化编辑保存成功：回调收到表单产物 YAML + 横幅回显校验结论', async () => {
  const onSave = vi.fn().mockResolvedValue(OK_OUTCOME);
  const { container } = render(
    <FileViewer path="HI-PERM-002.yaml" content={SCENARIO_YAML} canEdit onSaveContent={onSave} />,
  );
  fireEvent.click(screen.getByText('✏️ 编辑'));
  await waitFor(() => expect(sfeProps.onSave).toBeTruthy());
  fireEvent.click(screen.getByText('__save_ok'));
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(String(onSave.mock.calls[0][0])).toContain('# 表单改动');
  // 横幅：verdict + 摘要 + 感知去向 + findings 摘录
  await waitFor(() => expect(screen.getByText(/校验 PASS/)).toBeTruthy());
  expect(container.textContent).toContain('对话已感知本次编辑与校验结论');
  expect(container.textContent).toContain('[DIM_MAP] 提示一下');
});

test('保存失败（后端 422 等）：错误信息抛回场景编辑器错误条，横幅如实显示', async () => {
  const onSave = vi.fn().mockResolvedValue({ ok: false, message: 'YAML 解析失败，未写入' });
  const { container } = render(
    <FileViewer path="a.yaml" content={SCENARIO_YAML} canEdit onSaveContent={onSave} />,
  );
  fireEvent.click(screen.getByText('✏️ 编辑'));
  await waitFor(() => expect(sfeProps.onSave).toBeTruthy());
  fireEvent.click(screen.getByText('__save_reject'));
  await waitFor(() => {
    expect(container.textContent).toContain('✗ 保存失败');
    expect(container.textContent).toContain('YAML 解析失败，未写入');
  });
  expect(sfeProps._err).toBe('YAML 解析失败，未写入');   // 抛回子组件供其错误条呈现
});

test('不可编辑（场景库文件）：无编辑入口', () => {
  render(<FileViewer path="scenarios/x.yaml" content={SCENARIO_YAML} />);
  expect(screen.queryByText('✏️ 编辑')).toBeNull();
});
