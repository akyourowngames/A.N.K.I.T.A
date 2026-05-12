import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/App.tsx"
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#030405",
        panel: "rgba(255,255,255,0.045)",
        line: "rgba(255,255,255,0.12)",
        primaryText: "#E8E8E8",
        secondaryText: "#9A9A9A",
        mutedText: "#606060",
        statusGold: "#BFA66A"
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"]
      },
      boxShadow: {
        glass: "inset 0 1px 0 rgba(255,255,255,0.08), 0 24px 80px rgba(0,0,0,0.42)"
      }
    }
  },
  plugins: []
};

export default config;
