import type { Config } from 'tailwindcss'

export default {
  content: [
    './components/**/*.{js,vue,ts}',
    './layouts/**/*.vue',
    './pages/**/*.vue',
    './plugins/**/*.{js,ts}',
    './app.vue',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          from: '#ff6b6b',
          to: '#feca57',
        },
        dark: {
          bg: '#0a0a0f',
          // P1-2: card 从 5% 半透明白 → 实色 #13131a,卡片边界可见
          card: '#13131a',
          // P1-2: border 从 10% → 8%,更克制
          border: 'rgba(255,255,255,0.08)',
        },
        // P0-1: text 色板,解决 text-text-secondary 未定义 bug
        text: {
          primary: 'rgba(255,255,255,0.96)',
          secondary: 'rgba(255,255,255,0.64)',
          tertiary: 'rgba(255,255,255,0.40)',
          disabled: 'rgba(255,255,255,0.24)',
          onAccent: '#0a0a0f',
        },
      },
      backgroundImage: {
        'gradient-primary': 'linear-gradient(135deg, #ff6b6b 0%, #feca57 100%)',
      },
      // P0-2: 设计 token —— shadow / radius / zIndex / timing
      boxShadow: {
        'card':   'inset 0 1px 0 rgba(255,255,255,0.05)',
        'input':  '0 1px 2px rgba(0,0,0,0.4)',
        'pop':    '0 16px 40px rgba(0,0,0,0.6), 0 4px 8px rgba(0,0,0,0.4)',
        'glow':   '0 0 0 1px rgba(255,107,107,0.3), 0 8px 24px rgba(255,107,107,0.25)',
      },
      borderRadius: {
        'btn':   '8px',   // 按钮 / 输入框
        'card':  '16px',  // 卡片
        'pop':   '12px',  // popover
        'pill':  '9999px',
      },
      zIndex: {
        'base':      '0',
        'elevated':  '10',
        'dropdown':  '20',
        'modal':     '50',
        'toast':     '60',
      },
      transitionTimingFunction: {
        'out':    'cubic-bezier(0.16, 1, 0.3, 1)',
        'in-out': 'cubic-bezier(0.65, 0, 0.35, 1)',
        'spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      // P0-3: 字体 family
      fontFamily: {
        sans:    ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['"Space Grotesk"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono:    ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
