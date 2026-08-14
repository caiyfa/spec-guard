import { describe, it, expect } from 'vitest'
import { encodeWorkspaceHeader } from './api'

describe('encodeWorkspaceHeader', () => {
  it('ASCII 名原样保留（后端 unquote 无副作用）', () => {
    expect(encodeWorkspaceHeader('tdm')).toBe('tdm')
  })

  it('中文名编码后仅含 ISO-8859-1 可表示字符，且解码还原', () => {
    const enc = encodeWorkspaceHeader('人才发展')
    // HTTP header 值合法字符域：0x20-0x7E + 0x80-0xFF（Latin-1）
    expect(/^[\x20-\xFF]+$/.test(enc)).toBe(true)
    expect(decodeURIComponent(enc)).toBe('人才发展')
  })

  it('含 % 的名字编码为 %25，解码还原无歧义', () => {
    const enc = encodeWorkspaceHeader('a%b')
    expect(enc).toBe('a%25b')
    expect(decodeURIComponent(enc)).toBe('a%b')
  })
})
