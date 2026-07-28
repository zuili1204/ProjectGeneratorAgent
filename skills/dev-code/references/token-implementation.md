# Design Token Implementation Guide

> Consumed by dev-code when the project has a frontend (fullstack / frontend_only).
> This reference enforces that frontend code consumes the tokens from `DESIGN_SYSTEM.md` (produced by dev-design) rather than hardcoding raw values.
> Related: `skills/dev-design/references/design-system-template.md` (the token source of truth), `skills/_shared/color-theory.md`, `skills/_shared/typography-pairing.md`.

---

## 1. Why Tokens, Not Raw Values

Hardcoding `#2563eb`, `padding: 13px`, `font-family: Poppins` directly in components creates three problems:

1. **Drift** — ten buttons each define their own "blue"; they slowly diverge across pages.
2. **No theming** — dark mode / brand switch requires touching every component instead of one file.
3. **No reviewability** — dev-selfcheck and dev-review cannot tell whether a color is an intentional token or an accident.

The fix: dev-design emits a single `DESIGN_SYSTEM.md` (the source of truth), and dev-code **lands it as an importable stylesheet** that every component references by token name. dev-selfcheck then scans for raw hex / arbitrary px and fails the gate.

---

## 2. Mandatory Artifact: tokens.css

For ANY project with a frontend, dev-code MUST produce one of:

- **Tailwind project:** extend `tailwind.config.js` with the tokens (preferred) AND emit `code/frontend/src/styles/tokens.css` with the raw CSS variables (so non-Tailwind CSS and inline styles can still reference them).
- **Non-Tailwind project (pure HTML+JS / Vue scoped CSS):** emit `code/frontend/src/styles/tokens.css` (or `code/frontend/styles/tokens.css`) and `@import` it as the first line of the main stylesheet.

### tokens.css — canonical structure

The CSS variables in `tokens.css` MUST be transcribed verbatim from `DESIGN_SYSTEM.md` §2/§3/§4/§5. Do not invent new tokens; do not drop tokens.

```css
/* tokens.css — 由 DESIGN_SYSTEM.md 落地，禁止手工修改此文件中的色值 */
:root {
  /* === Color (from DESIGN_SYSTEM.md §2) === */
  --primary: #2563eb;
  --on-primary: #ffffff;
  --secondary: #3b82f6;
  --on-secondary: #ffffff;
  --accent: #ea580c;
  --on-accent: #ffffff;
  --background: #f8fafc;
  --foreground: #1e293b;
  --card: #ffffff;
  --card-foreground: #1e293b;
  --muted: #e9eff8;
  --muted-foreground: #64748b;
  --border: #e2e8f0;
  --destructive: #dc2626;
  --on-destructive: #ffffff;
  --ring: #2563eb;

  /* === Typography (from DESIGN_SYSTEM.md §3) === */
  --font-heading: 'Poppins', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  --font-body: 'Open Sans', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  --text-xs: 12px;
  --text-sm: 14px;
  --text-base: 16px;
  --text-lg: 18px;
  --text-xl: 20px;
  --text-2xl: 24px;
  --text-3xl: 30px;
  --text-5xl: 48px;

  /* === Spacing (from DESIGN_SYSTEM.md §4, 4/8dp rhythm) === */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;

  /* === Radius · Shadow · Motion (from DESIGN_SYSTEM.md §5) === */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;
  --radius-full: 9999px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
  --shadow-lg: 0 8px 24px rgba(0,0,0,0.12);
  --shadow-xl: 0 16px 48px rgba(0,0,0,0.16);
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in: cubic-bezier(0.7, 0, 0.84, 0);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --duration-fast: 150ms;
  --duration-normal: 250ms;
  --duration-slow: 350ms;
}

[data-theme="dark"] {
  --primary: #3b82f6;
  --on-primary: #ffffff;
  --background: #0f172a;
  --foreground: #f8fafc;
  --card: #1e293b;
  --card-foreground: #f8fafc;
  --muted: #334155;
  --muted-foreground: #94a3b8;
  --border: #334155;
  --destructive: #ef4444;
  --ring: #3b82f6;
}

@media (prefers-reduced-motion: reduce) {
  :root {
    --duration-fast: 0ms;
    --duration-normal: 0ms;
    --duration-slow: 0ms;
  }
}
```

---

## 3. Token Consumption Hard Constraints (Red Lines)

These apply to every frontend file under `code/frontend/` (and to any `code/*.html` for pure HTML+JS projects):

| Rule | FORBIDDEN | REQUIRED |
| --- | --- | --- |
| Color | bare hex / rgb / hsl in components (`color: #2563eb`, `background: #fff`) | `var(--primary)`, `var(--on-primary)`, … OR Tailwind token classes (`bg-primary`, `text-foreground`) |
| Font | `font-family: 'Poppins'` inline; system-default fonts (`serif`, `times`) | `var(--font-heading)` / `var(--font-body)` OR Tailwind `font-heading` / `font-body`; fonts loaded via `@import` from DESIGN_SYSTEM.md §3 |
| Spacing | arbitrary px (`padding: 13px`, `gap: 7px`) | `var(--space-N)` OR Tailwind spacing scale (`p-4`, `gap-2`) |
| Radius / Shadow / Motion | `border-radius: 6px`, `box-shadow: 0 2px 4px ...`, `transition: 200ms ease` | `var(--radius-md)`, `var(--shadow-md)`, `transition: var(--duration-fast) var(--ease-out)` |
| Opacity-as-state | `opacity: 0.5` for disabled | a dedicated token OR Tailwind `disabled:opacity-50` (consistent scale) |

### Acceptable exceptions (rare, must be commented)

- A one-off decorative value (e.g. a SVG gradient stop) MAY use raw hex IF it is not part of the semantic palette AND a `/* 例外: 装饰性渐变，非语义色 */` comment explains why.
- Third-party component inline overrides where `var()` cannot be injected (rare in our stack).

Everything else MUST route through a token. dev-selfcheck greps for `#[0-9a-fA-F]{3,8}` and arbitrary `px` in component files and fails the UI quality gate.

---

## 4. Tech-Stack-Specific Implementation (P3)

Pick the section matching the frontend framework declared in `DESIGN.md`.

### 4.1 React (Vite + React, preferred)

**Styling approach — choose ONE and stay consistent across the project:**

| Option | When to pick | Token wiring |
| --- | --- | --- |
| **Tailwind + CSS variables** (preferred) | Default for most projects | `tailwind.config.js` reads the CSS vars: `colors: { primary: 'var(--primary)', ... }`; `tokens.css` imported in `main.tsx` |
| CSS Modules | Component-scoped styles, no Tailwind | `tokens.css` imported globally; modules reference `var(--primary)` |
| styled-components / emotion | Dynamic theming, runtime CSS-in-JS | Define a `theme` object transcribed from DESIGN_SYSTEM.md; `<ThemeProvider theme={theme}>` at root |

**Tailwind config — canonical skeleton:**

```js
// tailwind.config.js — tokens 来自 DESIGN_SYSTEM.md
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: 'var(--primary)',
        'on-primary': 'var(--on-primary)',
        secondary: 'var(--secondary)',
        accent: 'var(--accent)',
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: 'var(--card)',
        'card-foreground': 'var(--card-foreground)',
        muted: 'var(--muted)',
        'muted-foreground': 'var(--muted-foreground)',
        border: 'var(--border)',
        destructive: 'var(--destructive)',
        ring: 'var(--ring)',
      },
      fontFamily: {
        heading: 'var(--font-heading)',
        body: 'var(--font-body)',
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        xl: 'var(--shadow-xl)',
      },
      transitionDuration: {
        fast: 'var(--duration-fast)',
        normal: 'var(--duration-normal)',
        slow: 'var(--duration-slow)',
      },
    },
  },
  plugins: [],
};
```

**Component conventions:**

- Use **shadcn/ui** patterns when a component library is needed (Radix primitives + Tailwind tokens) — keeps tokens authoritative.
- State-driven classNames via `clsx` / `cn`: `className={cn('bg-primary text-on-primary', disabled && 'opacity-50')}`.
- Never inline `style={{ color: '#2563eb' }}`. If a dynamic value is unavoidable, route it through a CSS var: `style={{ '--local-accent': dynamicColor }}` then `className="text-[var(--local-accent)]"`.

```tsx
// ✅ token-driven
<button className="bg-primary text-on-primary rounded-md px-4 py-2 hover:bg-primary/90 transition-colors duration-fast">
  确认
</button>

// ❌ FORBIDDEN — bare hex + arbitrary px
<button style={{ background: '#2563eb', color: '#fff', borderRadius: '8px', padding: '16px' }}>
  确认
</button>
```

### 4.2 Vue (Vite + Vue 3)

| Option | When to pick | Token wiring |
| --- | --- | --- |
| **Tailwind + CSS variables** (preferred) | Default | Same Tailwind config as React §4.1 |
| Scoped CSS (`<style scoped>`) | Component-local styles | `tokens.css` imported in `main.ts`; scoped blocks use `var(--primary)` |
| Element Plus / Naive UI | Need a mature component library | Configure the library's CSS vars to map to our tokens (e.g. Element Plus `--el-color-primary: var(--primary)`) |

```vue
<!-- ✅ token-driven scoped CSS -->
<template>
  <button class="btn-primary">确认</button>
</template>

<style scoped>
.btn-primary {
  background: var(--primary);
  color: var(--on-primary);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-4);
  transition: background var(--duration-fast) var(--ease-out);
}
.btn-primary:hover {
  background: var(--secondary);
}
</style>
```

### 4.3 Pure HTML + JS (no framework)

- **No build step:** use Tailwind via CDN is acceptable ONLY for prototypes; for deliverables prefer a small `tokens.css` + handwritten CSS using `var(--*)`. If Tailwind CDN is used, still inject `tokens.css` and reference tokens for any custom CSS.
- Load fonts via the `@import` from DESIGN_SYSTEM.md §3 in the main stylesheet (NOT a `<link>` to system fonts).
- Use **BEM naming** for class names: `.card__title`, `.card__title--muted`. Mapped to tokens in CSS, not inline.

```html
<!-- index.html -->
<link rel="stylesheet" href="./styles/tokens.css">
<link rel="stylesheet" href="./styles/main.css">
```

```css
/* main.css — @import 字体（来自 DESIGN_SYSTEM.md §3） */
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');

body {
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-body);
}

.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  box-shadow: var(--shadow-sm);
}
```

### 4.4 FastAPI / Flask Server-Rendered Templates

When the frontend is Jinja2 templates (not a separate SPA), the same token rules apply:

- `tokens.css` lives under `code/backend/static/styles/tokens.css` (or `code/static/styles/tokens.css`) and is served as a static asset.
- Jinja2 templates `{{ url_for('static', path='styles/tokens.css') }}` to load it.
- **Style boundary:** server templates own layout + content; if a separate SPA exists under `code/frontend/`, it owns its own components and imports the SAME `tokens.css` (symlink or copy at build) — never two divergent token files.
- Template fragment example:

```html
<!-- code/backend/templates/base.html -->
<link rel="stylesheet" href="{{ url_for('static', path='styles/tokens.css') }}">
<link rel="stylesheet" href="{{ url_for('static', path='styles/main.css') }}">
```

---

## 5. Multi-Page Token Override (P2)

`DESIGN_SYSTEM.md` is the **single global source of truth**. For multi-page projects (fullstack / frontend_only with several routes), a page MAY override a token locally — but only through the CSS variable cascade, never by re-hardcoding.

### Mechanism

1. dev-design produces `DESIGN_SYSTEM.md` (global) → dev-code lands `tokens.css` (global, loaded at app root).
2. If a specific page needs a deviation (e.g. a marketing landing page wants a warmer accent), create a **page-level override file**: `code/frontend/src/pages/<page>.tokens.css`.
3. The override file ONLY re-declares the tokens that change, scoped to a page-specific selector:

```css
/* code/frontend/src/pages/landing.tokens.css — 仅覆盖需要变更的 token */
.page-landing {
  --accent: #d97706;          /* 覆盖全局 --accent，仅本页生效 */
  --background: #fffbeb;      /* 营销页暖色底 */
}
```

4. The page component imports its override and wraps its root in the matching class:

```tsx
// pages/Landing.tsx
import './landing.tokens.css';

export default function Landing() {
  return (
    <div className="page-landing">
      {/* 此处所有 var(--accent) 自动取覆盖值，其他 token 仍走全局 */}
    </div>
  );
}
```

### Rules

- Overrides MUST be additive / re-declarative of existing token names — never invent new tokens at the page level.
- A page override file MUST be small (typically ≤ 10 lines). If it exceeds that, the page probably deserves its own design direction in `DESIGN_SYSTEM.md` instead — escalate to dev-design.
- dev-code MUST read `DESIGN_SYSTEM.md` before generating each page, and check whether a page-level override is warranted (only when the page's intent genuinely diverges from the global direction).

---

## 6. Pre-Delivery Self-Audit (run before handing off to dev-selfcheck)

dev-code should self-audit the frontend before finishing:

- [ ] `tokens.css` (and `tailwind.config.js` extension) exists and matches DESIGN_SYSTEM.md §2–§5.
- [ ] Fonts loaded via `@import` (not system defaults).
- [ ] `grep -rn "#[0-9a-fA-F]\{3,8\}" code/frontend/src/` returns only commented exceptions.
- [ ] No arbitrary `px` in padding/margin/gap (only `var(--space-N)` or Tailwind scale).
- [ ] `[data-theme="dark"]` block present if DESIGN_SYSTEM.md declares dark mode.
- [ ] `@media (prefers-reduced-motion: reduce)` zeroes the motion durations.
- [ ] Touch targets ≥ 44×44px on mobile (use `min-height: 44px` / `min-w-[44px]`).

dev-selfcheck will re-run these as a hard gate (see `skills/dev-selfcheck/references/ui-pre-delivery-checklist.md`).
