/** T-1027 F1：FileViewer 草稿编辑模式测试（入口仅 draft、保存回调、结果内联回显）。 */
import { expect, test, vi, beforeEach, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';

// Monaco 打桩为 textarea（jsdom 无法跑真实 monaco；只验证受控行为：值/onChange）
vi.mock('@monaco-editor/react', () => ({
  default: ({ value, onChange }: { value: string; onChange?: (v: string) => void }) => (
    <textarea aria-label="monaco-yaml" value={value} onChange={e => onChange?.(e.target.value)} />
  ),
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
});

test('可编辑草稿：出「✏️ 编辑」入口，改文保存后回调与横幅回显', async () => {
  const onSave = vi.fn().mockResolvedValue(OK_OUTCOME);
  const { container } = render(
    <FileViewer path="HI-PERM-002.yaml" content={SCENARIO_YAML} canEdit onSaveContent={onSave} />,
  );
  fireEvent.click(screen.getByText('✏️ 编辑'));
  const editor = screen.getByLabelText('monaco-yaml') as HTMLTextAreaElement;
  expect(editor.value).toBe(SCENARIO_YAML);
  // 改动 → dirty 提示出现，保存可用
  fireEvent.change(editor, { target: { value: SCENARIO_YAML + '\n# 用户手改' } });
  expect(screen.getByText('未保存修改')).toBeTruthy();
  fireEvent.click(screen.getByText('💾 保存并校验'));
  await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
  expect(onSave.mock.calls[0][0]).toContain('# 用户手改');
  // 横幅：verdict + 摘要 + 感知去向 + findings 摘录
  await waitFor(() => expect(screen.getByText(/校验 PASS/)).toBeTruthy());
  expect(container.textContent).toContain('对话已感知本次编辑与校验结论');
  expect(container.textContent).toContain('[DIM_MAP] 提示一下');
});

test('不可编辑（场景库文件）：无编辑入口', () => {
  render(<FileViewer path="scenarios/x.yaml" content={SCENARIO_YAML} />);
  expect(screen.queryByText('✏️ 编辑')).toBeNull();
});

test('保存失败结果如实回显不静默', async () => {
  const onSave = vi.fn().mockResolvedValue({ ok: false, message: 'YAML 解析失败，未写入' });
  render(<FileViewer path="a.yaml" content={SCENARIO_YAML} canEdit onSaveContent={onSave} />);
  fireEvent.click(screen.getByText('✏️ 编辑'));
  fireEvent.change(screen.getByLabelText('monaco-yaml'),
    { target: { value: SCENARIO_YAML + '\nbroken: [' } });
  fireEvent.click(screen.getByText('💾 保存并校验'));
  await waitFor(() => expect(screen.getByText('✗ 保存失败')).toBeTruthy());
  expect(screen.getByText(/YAML 解析失败，未写入/)).toBeTruthy();
});
