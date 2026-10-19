import type { Config } from "tailwindcss";

/**
 * Paper & Pine theme. Every value resolves to a CSS variable defined in src/app/globals.css,
 * so components never carry hardcoded colors, sizes or shadows.
 */
const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--bg)",
        surface: {
          DEFAULT: "var(--surface)",
          subtle: "var(--surface-subtle)",
          muted: "var(--surface-muted)",
        },
        border: {
          DEFAULT: "var(--border)",
          strong: "var(--border-strong)",
        },
        fg: {
          DEFAULT: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          tertiary: "var(--text-tertiary)",
        },
        ink: {
          DEFAULT: "var(--ink)",
          hover: "var(--ink-hover)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          hover: "var(--accent-hover)",
          subtle: "var(--accent-subtle)",
        },
        success: {
          DEFAULT: "var(--success)",
          subtle: "var(--success-subtle)",
        },
        warning: {
          DEFAULT: "var(--warning)",
          subtle: "var(--warning-subtle)",
        },
        danger: {
          DEFAULT: "var(--danger)",
          subtle: "var(--danger-subtle)",
        },
        neutral: {
          DEFAULT: "var(--neutral-badge)",
          subtle: "var(--neutral-badge-subtle)",
        },
        // Landing page only: the rest of the app uses ink/accent above. Values match Tailwind's
        // standard emerald/slate scale so they read as a deliberate, known palette, not invented.
        brand: {
          50: "#ECFDF5",
          100: "#D1FAE5",
          200: "#A7F3D0",
          500: "#10B981",
          600: "#059669",
          700: "#047857",
          800: "#065F46",
          900: "#064E3B",
          dark: "#0B132B",
          navy: "#0F172A",
          slate: "#1E293B",
        },
      },
      fontFamily: {
        // Inter + JetBrains Mono site-wide (loaded once in src/app/layout.tsx).
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      // Type scale: 12 / 13 / 14 / 16 / 20 / 24 / 28 / 32
      fontSize: {
        xs: ["12px", { lineHeight: "16px" }],
        caption: ["13px", { lineHeight: "18px" }],
        sm: ["14px", { lineHeight: "20px" }],
        base: ["16px", { lineHeight: "24px" }],
        xl: ["20px", { lineHeight: "28px", letterSpacing: "-0.02em" }],
        "2xl": ["24px", { lineHeight: "32px", letterSpacing: "-0.02em" }],
        kpi: ["28px", { lineHeight: "32px", letterSpacing: "-0.02em" }],
        "3xl": ["32px", { lineHeight: "40px", letterSpacing: "-0.02em" }],
      },
      // Spacing scale (4px base): 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 are covered by the defaults.
      letterSpacing: {
        label: "0.02em", // rare 11-12px uppercase group labels
      },
      borderRadius: {
        control: "8px", // buttons, inputs, badges
        card: "12px", // cards, dropdowns
        sheet: "16px", // modals and sheets
      },
      boxShadow: {
        card: "var(--shadow-card)",
        pop: "var(--shadow-pop)",
        modal: "var(--shadow-modal)",
        // Landing page only, alongside the `brand` colors below.
        "landing-glow": "0 0 45px -10px rgba(16, 185, 129, 0.25)",
        "landing-card": "0 10px 30px -5px rgba(15, 23, 42, 0.05), 0 0 1px 1px rgba(226, 232, 240, 0.8)",
        "landing-elevation": "0 20px 40px -15px rgba(15, 23, 42, 0.12), 0 0 0 1px rgba(226, 232, 240, 0.8)",
      },
      height: {
        control: "36px",
        "control-sm": "32px",
        "control-lg": "40px",
        row: "44px",
        "row-compact": "36px",
        topbar: "var(--topbar-height)",
      },
      width: {
        sidebar: "var(--sidebar-width)",
        rail: "var(--sidebar-rail-width)",
        sheet: "520px",
      },
      keyframes: {
        popIn: {
          from: { opacity: "0", transform: "scale(0.96)" },
          to: { opacity: "1", transform: "scale(1)" },
        },
        popOut: {
          from: { opacity: "1", transform: "scale(1)" },
          to: { opacity: "0", transform: "scale(0.96)" },
        },
        fadeIn: { from: { opacity: "0" }, to: { opacity: "1" } },
        fadeOut: { from: { opacity: "1" }, to: { opacity: "0" } },
      },
      animation: {
        "pop-in": "popIn 180ms var(--ease-out)",
        "pop-out": "popOut 120ms var(--ease-in) forwards",
        "fade-in": "fadeIn 180ms var(--ease-out)",
        "fade-out": "fadeOut 120ms var(--ease-in) forwards",
      },
      transitionTimingFunction: {
        "out-expo": "var(--ease-out)",
        "in-quick": "var(--ease-in)",
      },
      transitionDuration: {
        fast: "130ms",
        base: "180ms",
        sheet: "280ms",
      },
    },
  },
  plugins: [],
};

export default config;
