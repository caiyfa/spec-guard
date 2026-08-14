import { describe, it, expect } from 'vitest'
import { extractLastAnchor } from './focusAnchor'

describe('extractLastAnchor', () => {
  it('取最近一条消息的最后一个锚点', () => {
    const msgs = [
      { role: 'user', content: '看一下 FR-001 和 FR-002' },
      { role: 'assistant', content: 'FR-003 关联 AC-01' },
    ]
    expect(extractLastAnchor(msgs)).toBe('AC-01')
  })

  it('无锚点返回空串', () => {
    expect(extractLastAnchor([{ role: 'user', content: '你好' }])).toBe('')
  })

  it('空数组返回空串', () => {
    expect(extractLastAnchor([])).toBe('')
  })
})
