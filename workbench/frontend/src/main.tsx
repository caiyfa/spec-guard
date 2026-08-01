import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'
import './styles/themes.css'  // K-043：四主题变量（独立 CSS 文件，vite 原生处理）
import { initTheme } from './theme'

initTheme()  // K-043：主题对齐兜底（index.html 内联脚本已防 FOUC）

/**
 * ResizeObserver 兜底：CDP 无帧环境（自动化浏览器/jsdom）下原生 RO 不触发回调，
 * 会导致 React Flow 节点测量与边渲染卡死（节点 visibility:hidden、边层为空）。
 * 启动时探测 300ms，无回调则安装一次性触发 shim；真实浏览器探测通过、零影响。
 */
async function ensureResizeObserver(): Promise<void> {
  if (typeof window === 'undefined' || !('ResizeObserver' in window)) return
  const nativeWorks = await new Promise<boolean>((resolve) => {
    let fired = false
    const el = document.createElement('div')
    el.style.cssText = 'position:fixed;width:1px;height:1px;pointer-events:none;'
    document.body.appendChild(el)
    const ro = new ResizeObserver(() => { fired = true })
    ro.observe(el)
    setTimeout(() => { ro.disconnect(); el.remove(); resolve(fired) }, 300)
  })
  if (nativeWorks) return

  class ResizeObserverShim {
    private cb: ResizeObserverCallback
    private targets = new Set<Element>()
    private timer: ReturnType<typeof setTimeout> | null = null
    constructor(cb: ResizeObserverCallback) { this.cb = cb }
    observe(t: Element) { this.targets.add(t); this.schedule() }
    unobserve(t: Element) { this.targets.delete(t) }
    disconnect() { this.targets.clear(); if (this.timer) clearTimeout(this.timer) }
    private schedule() {
      if (this.timer) clearTimeout(this.timer)
      this.timer = setTimeout(() => this.fire(), 100)
    }
    private fire() {
      // 每次 observe 都触发（v12 依赖重复测量），防抖限流防渲染抖动
      const entries = Array.from(this.targets).map((t) => ({
        target: t,
        contentRect: t.getBoundingClientRect(),
        borderBoxSize: [{ inlineSize: t.clientWidth, blockSize: t.clientHeight }],
        contentBoxSize: [{ inlineSize: t.clientWidth, blockSize: t.clientHeight }],
        devicePixelContentBoxSize: [],
      })) as unknown as ResizeObserverEntry[]
      try { this.cb(entries, this as unknown as ResizeObserver) } catch { /* noop */ }
    }
  }
  ;(window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    ResizeObserverShim as unknown as typeof ResizeObserver
}

ensureResizeObserver().finally(() => {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  )
})
