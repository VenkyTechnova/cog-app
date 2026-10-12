/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: { 50: "#eef6fb", 100: "#d6e9f5", 200: "#aed2ea", 300: "#7cb3d9", 400: "#4a8fc2", 500: "#2a72a8", 600: "#1d5a88", 700: "#17496f", 800: "#0f3d5e", 900: "#0b2c45" },
        // Category colors = categorical slots 1-4 of the validated data-viz palette.
        automate: { DEFAULT: "#2a78d6", dark: "#3987e5" },
        delegate: { DEFAULT: "#eb6834", dark: "#d95926" },
        simplify: { DEFAULT: "#1baf7a", dark: "#199e70" },
        human: { DEFAULT: "#eda100", dark: "#c98500" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
    },
  },
  plugins: [],
};
