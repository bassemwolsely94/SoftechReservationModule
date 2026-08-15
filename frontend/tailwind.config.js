/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  safelist: [
    'w-[220px]', 'w-0',
  ],
  theme: {
    extend: {
      fontFamily: {
        // ── ElRezeiky brand fonts (see index.css @font-face + CSS vars) ──
        // Default UI stack: Latin picks Harabara, Arabic falls through to Jozoor.
        sans:  ['var(--font-ui)', 'system-ui', 'sans-serif'],
        ar:    ['var(--font-ar)', 'sans-serif'],   // Arabic  → Jozoor
        en:    ['var(--font-en)', 'sans-serif'],   // Latin   → Harabara Mais Demo
        num:   ['var(--font-num)', 'sans-serif'],  // Numbers → Berlin Sans FB
        // Legacy alias: `font-cairo` is used in ~29 places as "the Arabic font".
        // Repointed to the brand Arabic stack (Jozoor → Cairo) so those adopt the
        // brand font automatically without touching every file.
        cairo: ['var(--font-ar)', 'sans-serif'],
      },
      colors: {
        // ── ElRezeiky brand palette (runtime-themeable) ──────────────────
        // Values come from CSS vars set by src/theme/theme.js so the admin
        // Appearance page can recolor the whole UI live. Defaults live in
        // index.css :root. `<alpha-value>` keeps `/opacity` modifiers working.
        brand: {
          50:  'rgb(var(--c-brand-50) / <alpha-value>)',
          100: 'rgb(var(--c-brand-100) / <alpha-value>)',
          200: 'rgb(var(--c-brand-200) / <alpha-value>)',
          300: 'rgb(var(--c-brand-300) / <alpha-value>)',
          400: 'rgb(var(--c-brand-400) / <alpha-value>)',
          500: 'rgb(var(--c-brand-500) / <alpha-value>)',
          600: 'rgb(var(--c-brand-600) / <alpha-value>)',
          700: 'rgb(var(--c-brand-700) / <alpha-value>)',
          800: 'rgb(var(--c-brand-800) / <alpha-value>)',
          900: 'rgb(var(--c-brand-900) / <alpha-value>)',
        },
        'brand-navy': 'rgb(var(--c-brand-600) / <alpha-value>)',
        'brand-sky':  'rgb(var(--c-brand-sky) / <alpha-value>)',
        'brand-red':  'rgb(var(--c-brand-red) / <alpha-value>)',
        alert:  '#F5A623',
        danger: 'rgb(var(--c-danger) / <alpha-value>)',
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      animation: {
        'fade-in':    'fadeIn 0.25s ease-out both',
        'slide-in':   'slideIn 0.22s ease-out both',
        'slide-left': 'slideInLeft 0.22s ease-out both',
        'scale-in':   'scaleIn 0.2s ease-out both',
        'shimmer':    'shimmer 1.4s ease infinite',
        'toast-in':   'toastIn 0.3s ease-out both',
        'toast-out':  'toastOut 0.25s ease-in both',
      },
      keyframes: {
        fadeIn: {
          from: { opacity: 0, transform: 'translateY(6px)' },
          to:   { opacity: 1, transform: 'translateY(0)' },
        },
        slideIn: {
          from: { opacity: 0, transform: 'translateX(12px)' },
          to:   { opacity: 1, transform: 'translateX(0)' },
        },
        slideInLeft: {
          from: { opacity: 0, transform: 'translateX(-12px)' },
          to:   { opacity: 1, transform: 'translateX(0)' },
        },
        scaleIn: {
          from: { opacity: 0, transform: 'scale(0.95)' },
          to:   { opacity: 1, transform: 'scale(1)' },
        },
        shimmer: {
          '0%':   { backgroundPosition: '100% 50%' },
          '100%': { backgroundPosition: '0% 50%' },
        },
        toastIn: {
          from: { opacity: 0, transform: 'translateX(100%)' },
          to:   { opacity: 1, transform: 'translateX(0)' },
        },
        toastOut: {
          from: { opacity: 1, transform: 'translateX(0)' },
          to:   { opacity: 0, transform: 'translateX(100%)' },
        },
      },
      screens: {
        xs: '380px',
      },
      spacing: {
        'safe-bottom': 'env(safe-area-inset-bottom, 0)',
      },
    },
  },
  plugins: [
    function({ addUtilities }) {
      addUtilities({
        '.scrollbar-hide': {
          '-ms-overflow-style': 'none',
          'scrollbar-width': 'none',
          '&::-webkit-scrollbar': { display: 'none' },
        },
      })
    },
  ],
}
