/** @type {import('tailwindcss').Config} */

// K-043：颜色全部走 CSS 变量（RGB 三元组 + <alpha-value> 支持 /透明度 修饰），
// 主题切换 = html[data-theme] 换变量值，组件零改动。变量定义见 src/styles/themes.css
const v = (name) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  // T-1044：删除 darkMode:'class' 死配置（实际机制是 html[data-theme] CSS 变量，见 themes.css）
  theme: {
    extend: {
      // T-1044 U0：字号五档语义阶梯（方案 §3.1）——散点 text-[Npx] 全量归档，ratchet 闸禁新增
      fontSize: {
        'fs-micro': ['9px', { lineHeight: '1.4' }],    // 徽标计数、极辅助标注
        'fs-aux': ['10.5px', { lineHeight: '1.5' }],   // 辅助信息、证据行、表头
        'fs-body': ['12px', { lineHeight: '1.6' }],    // 正文/列表/按钮主力
        'fs-lead': ['13px', { lineHeight: '1.65' }],   // 段落正文、强调读文
        'fs-title': ['15px', { lineHeight: '1.4' }],   // 页面标题/卡标题
      },
      // T-1044 U0（B·Paper 语言）：字体族 token——display=衬线（页面标题/阅读模式），
      // body 走默认 font-sans；mono 供 ID/日志/代码
      fontFamily: {
        display: ['Georgia', 'Times New Roman', 'Songti SC', 'SimSun', 'serif'],
        mono: ['ui-monospace', 'JetBrains Mono', 'Cascadia Code', 'Consolas', 'Courier New', 'monospace'],
      },
      colors: {
        surface: { DEFAULT: v('--surface-1'), 1: v('--surface-1'), 2: v('--surface-2'), 3: v('--surface-3') },
        border: v('--border'),
        pass: v('--pass'),
        fail: v('--fail'),
        skip: v('--skip'),
        blocked: v('--blocked'),
        info: v('--info'),
        railDot: v('--rail-dot'),
        pinnedBg: v('--pinned-bg'),
        warn: v('--warn'),
        // gray 阶 = 文字层级变量（深主题浅文字、浅主题深文字，语义映射非真实灰）
        gray: {
          100: v('--gray-100'),
          200: v('--gray-200'),
          300: v('--gray-300'),
          400: v('--gray-400'),
          500: v('--gray-500'),
          600: v('--gray-600'),
          700: v('--gray-700'),
          900: v('--gray-900'),
        },
      },
    },
  },
  plugins: [],
}
