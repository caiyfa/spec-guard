/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        surface: { DEFAULT: '#0d1117', 2: '#161b22', 3: '#1c2330' },
        border: '#2d3646',
        pass: '#3fb950',
        fail: '#f85149',
        skip: '#d29922',
        blocked: '#8957e5',
        info: '#58a6ff',
      },
    },
  },
  plugins: [],
}
