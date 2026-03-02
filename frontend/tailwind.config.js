/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: '#0a0a0f', card: '#111118', hover: '#1a1a24' },
        accent: { DEFAULT: '#10b981', dim: '#065f46' },
        heat: {
          fire: '#10b981',
          high: '#f59e0b',
          mid: '#3b82f6',
          low: '#6b7280',
        },
        rarity: {
          ultra: '#ef4444',
          limited: '#f97316',
          semi: '#3b82f6',
          mass: '#6b7280',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        display: ['Oswald', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
