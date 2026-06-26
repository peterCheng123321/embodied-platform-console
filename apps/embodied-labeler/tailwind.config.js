/** Static Tailwind build for the labeler — replaces the 407KB Play CDN runtime JIT.
 *  Rebuild from this dir:
 *    npx tailwindcss@3 -i tailwind.input.css -o assets/console/tailwind.css --minify
 */
module.exports = {
  content: ["./index.html", "./assets/**/*.js"],
  theme: {
    extend: {
      colors: { primary: "#0d4f4a", secondary: "#1f7a6b", dark: "#16201f", light: "#fcfcfd", accent: "#ff5a36" },
      fontFamily: { sans: ['"IBM Plex Sans SC"', "sans-serif"], mono: ['"IBM Plex Mono"', "monospace"] },
    },
  },
};
