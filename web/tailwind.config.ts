import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0A0B",
        panel: "#111114",
        border: "#1F1F24",
        muted: "#8A8A94",
        text: "#EDEDF0",
        accent: "#3F8CFF",
        good: "#22C55E",
        warn: "#F59E0B",
        bad: "#EF4444",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "-apple-system", "Inter", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
