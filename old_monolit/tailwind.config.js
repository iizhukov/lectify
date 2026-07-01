/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './resources/templates/**/*.html',
    './resources/static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#0066CC',
          dark: '#222222',
          light: '#DCDCDC',
          bg: '#FFFFFF',
          muted: '#787878',
        }
      }
    }
  },
  plugins: [],
}
