/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
    "./app.py"
  ],
  theme: {
    extend: {
      colors: {
        'primary': {
          50: '#f0f9ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8'
        }
      },
      fontFamily: {
        'display': ['Funnel Display', 'sans-serif']
      }
    },
  },
  plugins: [],
}
