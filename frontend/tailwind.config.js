/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        cairo: ['Cairo', 'sans-serif'],
      },
      colors: {
        brand: {
          50:  '#f0f9f4',
          100: '#dcf0e5',
          200: '#bce1ce',
          300: '#8dcaad',
          400: '#5aad87',
          500: '#38916a',
          600: '#1B6B3A',   // PRIMARY
          700: '#175a31',
          800: '#154928',
          900: '#123c21',
        },
        alert:  '#F5A623',
        danger: '#D93025',
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
  plugins: [],
}
