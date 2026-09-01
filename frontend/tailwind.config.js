/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        "ink-navy":      "#1a1a2e",
        "ink-light":     "#f5f2ea",
        "ledger":        "#f4f0e7",
        "card-bg":       "#faf9f5",
        "seal-gold":     "#9a7c2e",
        "verified-green":"#2d6a4f",
        "violation-red": "#b02a2a",
        "graphite":      "#3a3a3a",
        "border-main":   "#ddd8cc",
        "muted-fg":      "#7a7060",
      },
      fontFamily: {
        display: ["Zilla Slab","Roboto Slab","Georgia","serif"],
        sans:    ["Inter","ui-sans-serif","system-ui","sans-serif"],
        mono:    ["IBM Plex Mono","ui-monospace","monospace"],
      },
      boxShadow: {
        stamp: "0 1px 0 0 rgba(58,58,58,0.18)",
        lift:  "0 14px 34px -18px rgba(26,26,46,0.55)",
      },
      keyframes: {
        "stamp-hit":  { "0%":{ opacity:0,transform:"scale(1.5) rotate(-9deg)" }, "55%":{ opacity:1,transform:"scale(0.94) rotate(-2.5deg)" }, "100%":{ opacity:1,transform:"scale(1) rotate(-3.5deg)" } },
        "settle-in":  { from:{ opacity:0,transform:"translateY(18px)" }, to:{ opacity:1,transform:"none" } },
      },
      animation: {
        stamp:  "stamp-hit 420ms cubic-bezier(0.2,0.9,0.3,1.2) both",
        settle: "settle-in 700ms cubic-bezier(0.22,1,0.36,1) both",
      },
    },
  },
  plugins: [],
};