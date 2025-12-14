/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          blue: '#4A90E2',
          'blue-light': '#6BA3E8',
          'blue-dark': '#357ABD',
        },
        secondary: {
          pink: '#F5B5C7',
          'pink-light': '#F9D1DC',
          'pink-dark': '#E89BB0',
        },
      },
    },
  },
  plugins: [],
}

