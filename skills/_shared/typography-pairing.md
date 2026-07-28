# Typography Pairing Quick Reference

> Shared design knowledge. 16 curated font pairings with Google Fonts URLs, CSS imports, and Tailwind configs.
> Curated (not exhaustive) — enough coverage for all common product types.

## Pairing Rules

- Match heading + body personality: elegant serif heading + clean sans body; bold display heading + readable sans body
- Use ONE heading font + ONE body font (max). Adding a third (e.g. mono for code) is allowed for dev tools only.
- Body font MUST be highly readable at 14-16px. Avoid display/decorative fonts for body text.
- Define a type scale (6-8 sizes), never use arbitrary px. Standard scale: 12 / 14 / 16 / 18 / 24 / 32 / 48 / 64.

## Standard Type Scale (CSS)

```css
:root {
  --text-xs: 12px;   /* captions, badges */
  --text-sm: 14px;   /* secondary text, table cells */
  --text-base: 16px; /* body text (minimum for mobile) */
  --text-lg: 18px;   /* emphasized body */
  --text-xl: 20px;   /* card titles */
  --text-2xl: 24px;  /* section headings */
  --text-3xl: 30px;  /* page titles */
  --text-4xl: 36px;  /* hero subtitle */
  --text-5xl: 48px;  /* hero title */
  --text-6xl: 60px;  /* display */
  /* line-heights */
  --leading-tight: 1.25;  /* headings */
  --leading-normal: 1.5;  /* body */
  --leading-relaxed: 1.75; /* long-form reading */
}
```

## Curated Pairings

### 1. Modern Professional (SaaS / Corporate / Startup)
- **Heading:** Poppins | **Body:** Open Sans
- **Mood:** modern, professional, clean, approachable
- **Best for:** SaaS, corporate sites, business apps, startups
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap`
- **CSS:** `@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@300;400;500;600;700&family=Poppins:wght@400;500;600;700&display=swap');`
- **Tailwind:** `fontFamily: { heading: ['Poppins', 'sans-serif'], body: ['Open Sans', 'sans-serif'] }`

### 2. Tech Startup (Developer Tools / AI Products)
- **Heading:** Space Grotesk | **Body:** DM Sans
- **Mood:** tech, innovative, bold, futuristic
- **Best for:** tech companies, startups, dev tools, AI products
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Grotesk:wght@400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { heading: ['Space Grotesk', 'sans-serif'], body: ['DM Sans', 'sans-serif'] }`

### 3. Classic Elegant (Luxury / Fashion / Spa / Editorial)
- **Heading:** Playfair Display | **Body:** Inter
- **Mood:** elegant, luxury, sophisticated, timeless
- **Best for:** luxury brands, fashion, spa, beauty, editorial, high-end e-commerce
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { serif: ['Playfair Display', 'serif'], sans: ['Inter', 'sans-serif'] }`

### 4. Minimal Swiss (Dashboards / Enterprise / Design Systems)
- **Heading + Body:** Inter (single family, weight variation)
- **Mood:** minimal, clean, functional, neutral
- **Best for:** dashboards, admin panels, documentation, enterprise apps, design systems
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { sans: ['Inter', 'sans-serif'] }`

### 5. Geometric Modern (Landing Pages / Portfolios / Agencies)
- **Heading:** Outfit | **Body:** Work Sans
- **Mood:** geometric, modern, balanced, versatile
- **Best for:** general purpose, portfolios, agencies, modern brands, landing pages
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Work+Sans:wght@300;400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { heading: ['Outfit', 'sans-serif'], body: ['Work Sans', 'sans-serif'] }`

### 6. Wellness Calm (Health / Wellness / Meditation)
- **Heading:** Lora | **Body:** Raleway
- **Mood:** calm, relaxing, natural, organic
- **Best for:** health apps, wellness, spa, meditation, yoga, organic brands
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Lora:wght@400;500;600;700&family=Raleway:wght@300;400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { serif: ['Lora', 'serif'], sans: ['Raleway', 'sans-serif'] }`

### 7. Playful Creative (Education / Kids / Gaming)
- **Heading:** Fredoka | **Body:** Nunito
- **Mood:** playful, friendly, fun, warm
- **Best for:** children's apps, educational, gaming, creative tools, entertainment
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Fredoka:wght@400;500;600;700&family=Nunito:wght@300;400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { heading: ['Fredoka', 'sans-serif'], body: ['Nunito', 'sans-serif'] }`

### 8. Bold Statement (Marketing / Sports / Events)
- **Heading:** Bebas Neue | **Body:** Source Sans 3
- **Mood:** bold, impactful, dramatic, headlines
- **Best for:** marketing sites, portfolios, agencies, event pages, sports
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Source+Sans+3:wght@300;400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { display: ['Bebas Neue', 'sans-serif'], body: ['Source Sans 3', 'sans-serif'] }`
- **Note:** Bebas Neue is all-caps, for large headlines only — never use for body.

### 9. Developer Mono (Dev Tools / Documentation / Code Editors)
- **Heading:** JetBrains Mono | **Body:** IBM Plex Sans
- **Mood:** code, technical, precise, functional
- **Best for:** developer tools, documentation, code editors, tech blogs, CLI apps
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { mono: ['JetBrains Mono', 'monospace'], sans: ['IBM Plex Sans', 'sans-serif'] }`

### 10. Editorial Classic (Publishing / Blogs / News)
- **Heading:** Cormorant Garamond | **Body:** Libre Baskerville
- **Mood:** editorial, classic, literary, refined
- **Best for:** publishing, blogs, news sites, literary magazines, book covers
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Libre+Baskerville:wght@400;700&display=swap`
- **Tailwind:** `fontFamily: { heading: ['Cormorant Garamond', 'serif'], body: ['Libre Baskerville', 'serif'] }`

### 11. Trust Finance (Banking / Fintech / Insurance)
- **Heading:** Source Serif 4 | **Body:** Inter
- **Mood:** trustworthy, stable, serious, authoritative
- **Best for:** banking, fintech, insurance, legal, accounting
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Source+Serif+4:wght@400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { serif: ['Source Serif 4', 'serif'], sans: ['Inter', 'sans-serif'] }`

### 12. Data Precision (Dashboards / Analytics / Data Tools)
- **Heading + Body:** IBM Plex Sans (single family) | **Mono:** IBM Plex Mono (for numbers)
- **Mood:** precise, technical, data-focused, neutral
- **Best for:** analytics dashboards, data tools, financial dashboards, monitoring
- **Google Fonts:** `https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap`
- **Tailwind:** `fontFamily: { sans: ['IBM Plex Sans', 'sans-serif'], mono: ['IBM Plex Mono', 'monospace'] }`
- **Note:** Use `font-variant-numeric: tabular-nums` for data columns to prevent layout shift.

## Font Loading Best Practices

- Always use `font-display: swap` (or `optional`) to avoid invisible text (FOIT).
- Preload only the critical font weights (regular 400 + bold 700), not every variant.
- Declare `font-size` AND `line-height` together to reserve space (prevent CLS).
- For Chinese sites: pair the Latin font with a system Chinese font stack:
  ```css
  body { font-family: 'Inter', -apple-system, 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif; }
  ```
- Minimum body font-size on mobile: 16px (avoids iOS auto-zoom).

## Weight Hierarchy

| Role | Weight | Usage |
| --- | --- | --- |
| Display/Hero | 700 (Bold) | Large hero titles |
| Heading | 600 (Semi-Bold) | Section titles, card titles |
| Body | 400 (Regular) | Paragraphs, default text |
| Emphasized body | 500 (Medium) | Labels, captions, key terms |
| Secondary | 300 (Light) | Large decorative text only (never body < 18px) |
