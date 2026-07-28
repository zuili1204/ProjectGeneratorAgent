# Color Theory & Semantic Token System

> Shared design knowledge for dev-design / dev-code / dev-selfcheck.
> Covers: semantic token architecture, WCAG contrast, light/dark mode, industry color baselines.

## Semantic Color Token Architecture

Never use raw hex in components. Always define semantic tokens and reference them. This is the canonical token set (adapted from Material 3 / shadcn):

### Token Roles

| Token | Purpose | Example |
| --- | --- | --- |
| `--primary` | Brand color, primary actions, active states | CTA button background |
| `--on-primary` | Text/icon color on top of `--primary` | CTA button label |
| `--secondary` | Secondary brand, less prominent actions | Secondary button background |
| `--on-secondary` | Text/icon on `--secondary` | Secondary button label |
| `--accent` | Highlight, attention-grabbing (different from primary) | Badge, notification dot |
| `--on-accent` | Text/icon on `--accent` | Badge label |
| `--background` | App/page background | Page root |
| `--foreground` | Default body text on `--background` | Paragraph text |
| `--card` | Card/surface background (slightly elevated) | Card component bg |
| `--card-foreground` | Text on `--card` | Card content |
| `--muted` | Muted surface (subtle backgrounds, hover) | Table stripe, hover bg |
| `--muted-foreground` | Secondary/placeholder text | Captions, hints |
| `--border` | Borders, dividers | Card border, input border |
| `--destructive` | Error/danger actions | Delete button |
| `--on-destructive` | Text on `--destructive` | Delete button label |
| `--ring` | Focus ring color | Keyboard focus outline |

### CSS Variable Form (tokens.css)

```css
:root {
  /* Light mode */
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
}

[data-theme="dark"] {
  --primary: #3b82f6;
  --on-primary: #ffffff;
  --background: #0f172a;
  --foreground: #f1f5f9;
  --card: #1e293b;
  --card-foreground: #f1f5f9;
  --muted: #334155;
  --muted-foreground: #94a3b8;
  --border: #334155;
  --destructive: #ef4444;
  --on-destructive: #ffffff;
  --ring: #3b82f6;
}
```

### Tailwind Config Form

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: { DEFAULT: 'var(--primary)', foreground: 'var(--on-primary)' },
        secondary: { DEFAULT: 'var(--secondary)', foreground: 'var(--on-secondary)' },
        accent: { DEFAULT: 'var(--accent)', foreground: 'var(--on-accent)' },
        background: 'var(--background)',
        foreground: 'var(--foreground)',
        card: { DEFAULT: 'var(--card)', foreground: 'var(--card-foreground)' },
        muted: { DEFAULT: 'var(--muted)', foreground: 'var(--muted-foreground)' },
        border: 'var(--border)',
        destructive: { DEFAULT: 'var(--destructive)', foreground: 'var(--on-destructive)' },
        ring: 'var(--ring)',
      },
      borderRadius: { sm: '4px', md: '8px', lg: '12px', xl: '16px' },
    },
  },
}
```

## WCAG Contrast Rules

| Text type | Minimum ratio (AA) | Enhanced (AAA) |
| --- | --- | --- |
| Normal text (< 18px / < 14px bold) | 4.5:1 | 7:1 |
| Large text (≥ 18px / ≥ 14px bold) | 3.0:1 | 4.5:1 |
| UI components & icons | 3.0:1 | — |

### Contrast Verification (mental model)

- White (#fff) on `--primary`: primary must be dark enough (luminance ≤ 0.18 for 4.5:1)
- `--muted-foreground` on `--background`: must stay ≥ 4.5:1 (common failure: gray-on-gray)
- `--foreground` on `--card`: same as on background (card is usually close to background)
- Dark mode: `--foreground` must be light enough; avoid pure white (#fff → use #f1f5f9 to reduce strain)

### Quick Contrast Pairs to Verify

Always check these 5 pairs before delivery:
1. `--foreground` / `--background` (body text)
2. `--muted-foreground` / `--background` (secondary text — most common failure)
3. `--on-primary` / `--primary` (button label)
4. `--on-destructive` / `--destructive` (error button)
5. `--muted-foreground` / `--card` (card secondary text)

## Light/Dark Mode Rules

- **Dark mode is NOT inverted colors.** Use desaturated/lighter tonal variants, not raw inversion.
- Surfaces: dark mode uses layered dark grays (#0f172a → #1e293b → #334155), not pure black (unless OLED).
- Text: avoid pure white (#ffffff) — use #f1f5f9 / #e2e8f0 to reduce eye strain.
- Accents: may need brightening in dark mode (e.g. #2563eb → #3b82f6) to maintain contrast.
- Borders: must be visible in BOTH modes (a light gray border invisible on dark = failure).
- Test BOTH themes independently — never assume light-mode values carry over.

## Industry Color Baselines

Curated baselines per product type (use as starting point, adjust per brand):

| Industry | Primary | Accent | Background | Mood | Avoid |
| --- | --- | --- | --- | --- | --- |
| SaaS/Tool | #2563eb (blue) | #ea580c (orange CTA) | #f8fafc | Trust + action | Neon, pastel |
| E-commerce | #059669 (green) | #ea580c (urgency orange) | #ecfdf5 | Success + urgency | Dark-only, low contrast |
| Finance/Banking | #0f172a (navy) | #22c55e (green positive) | #f8fafc | Trust + stability | AI purple/pink gradients, neon |
| Healthcare | #0891b2 (calm cyan) | #059669 (health green) | #ecfeff | Calm + healing | High-saturation red, harsh contrast |
| Creative/Agency | #ec4899 (pink) | #0891b2 (cyan) | #fdf2f8 | Bold + creative | Enterprise gray, muted |
| Education/Kids | #4f46e5 (indigo) | #ea580c (orange) | #eef2ff | Playful + energetic | Cold geometry, low saturation |
| Dashboard/Analytics | #1e40af (data blue) | #d97706 (amber highlight) | #f8fafc | Data + clarity | Decorative gradients, wide whitespace |
| Gaming/Entertainment | #7c3aed (purple) | #f43f5e (rose) | #0f0f23 (dark) | Immersive + neon | Light-only, flat |
| Portfolio | #18181b (monochrome) | #2563eb (blue) | #fafafa | Minimal + focus | Clashing colors, busy |

## Functional Color Conventions

- **Error/danger:** red (#dc2626 light / #ef4444 dark) — always paired with icon + text, never color alone
- **Success:** green (#16a34a / #22c55e) — same rule
- **Warning:** amber (#d97706 / #f59e0b)
- **Info:** blue (#2563eb / #3b82f6)
- These 4 functional colors must have distinct hues — never use the same red for both error and accent.
