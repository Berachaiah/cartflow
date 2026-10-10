/* Tailwind config — the compiled replacement for the CDN build.
 *
 * `theme.extend` below is a verbatim port of the object that used to be assigned
 * to `tailwind.config` in an inline <script> in base.html. It has to stay
 * verbatim: `bg-surface`, `text-muted`, `rounded-xl2` and `shadow-glow` are used
 * across 31 templates, and a name that quietly stops resolving here does not
 * error anywhere — it just renders unstyled, which is the failure mode this
 * whole change exists to remove.
 *
 * CONTENT GLOBS ARE THE THING TO GET RIGHT. The CDN build compiled in the
 * browser, so it saw the final DOM and every class in it. This build sees only
 * files, at build time, via a regex over their raw text. Three sources carry
 * class names and all three must be listed:
 *
 *   - templates, the obvious one;
 *   - app/static/js, because cartflow-messages.js is the ONE RENDERER for
 *     everything in a conversation — every bubble, row and preview class exists
 *     only there and appears in no template;
 *   - app/routers/pages.py, which emits markup directly.
 *
 * The scanner reads candidates as plain text, so the interpolated forms in
 * cartflow-messages.js (`${size} ${radius || "rounded-xl"}`) are safe: the
 * literals passed at the call sites ("w-11 h-11", "w-9 h-9", "rounded-lg") sit
 * in the same scanned file. Building a class by concatenating a *fragment*
 * (`text-${c}-500`) would not be, and must not be introduced.
 */
module.exports = {
    content: [
        "./app/templates/**/*.html",
        "./app/static/js/**/*.js",
        "./app/routers/*.py",
    ],
    // Inert today — the app themes through [data-theme] and CSS variables, and
    // there are zero `dark:` variants in the codebase. Kept because the CDN
    // config carried it, so dropping it would be a silent behaviour change the
    // day someone writes the first one.
    darkMode: "class",
    theme: {
        extend: {
            colors: {
                primary: "#7CC6FF",
                primaryDark: "#5AB6FF",
                accent: "#FFB547",
                background: "var(--c-bg)",
                surface: "var(--c-surface)",
                card: "var(--c-card)",
                glass: "var(--c-glass)",
                border: "var(--c-border)",
                muted: "var(--c-muted)",
                success: "#32D583",
                danger: "#F04438",
            },
            fontFamily: {
                display: ["Fraunces", "serif"],
                body: ["Inter", "sans-serif"],
            },
            boxShadow: {
                glow: "0 0 40px rgba(124,198,255,.15)",
                card: "0 20px 60px rgba(0,0,0,.25)",
            },
            borderRadius: {
                xl2: "22px",
            },
        },
    },
    // The three the CDN URL requested: ?plugins=forms,typography,container-queries
    plugins: [
        require("@tailwindcss/forms"),
        require("@tailwindcss/typography"),
        require("@tailwindcss/container-queries"),
    ],
};
