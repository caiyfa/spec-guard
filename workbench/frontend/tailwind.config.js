/** @type {import('tailwindcss').Config} */

// K-043：颜色全部走 CSS 变量（RGB 三元组 + <alpha-value> 支持 /透明度 修饰），
// 主题切换 = html[data-theme] 换变量值，组件零改动。变量定义见 src/styles/themes.css
const v = (name) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
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
