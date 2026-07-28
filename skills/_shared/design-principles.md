# UI Design Principles — Style Quick Reference

> Shared design knowledge for dev-design / dev-code / dev-selfcheck. Read on demand via `read_file`.
> Curated (not exhaustive): 14 mainstream UI styles with application context, visual signature, and anti-patterns.

## How to Use

When generating DESIGN_SYSTEM.md (dev-design) or reviewing UI (dev-review), pick ONE primary style that matches the product type. Do not mix incompatible styles (e.g. Brutalism + Neumorphism). Secondary influence is allowed at ≤30% (e.g. Minimalism primary + Soft UI accents).

## Style Catalog

### 1. Minimalism & Swiss Style
- **Visual signature:** generous whitespace, strict grid, limited color palette (1 primary + neutrals), sans-serif type, no decoration
- **Best for:** enterprise apps, dashboards, documentation, admin panels, SaaS tools
- **Key tokens:** flat shadows (none or 1 level), small radius (4-8px), tight type scale
- **Anti-patterns:** decorative gradients, emoji icons, more than 3 font sizes in body, cluttered density

### 2. Soft UI (Neumorphism evolved)
- **Visual signature:** soft extruded/inset shadows, monochromatic surfaces, subtle depth, low contrast between element and background
- **Best for:** wellness, health, meditation, premium services, dashboard cards
- **Key tokens:** dual shadows (light top-left + dark bottom-right), same hue family for surface + element, rounded radius (12-16px)
- **Anti-patterns:** low-contrast text (fails WCAG), using on data-dense tables, no hover state distinction

### 3. Glassmorphism
- **Visual signature:** frosted-glass blur backdrop, translucent layers, vibrant background showing through, subtle border highlight
- **Best for:** modern SaaS, financial dashboards, marketing hero sections, notification cards
- **Key tokens:** `backdrop-filter: blur(12px)`, semi-transparent surfaces (rgba 0.6-0.8), 1px light border
- **Anti-patterns:** stacking 3+ glass layers (unreadable), using on text-heavy pages, no fallback for `backdrop-filter` unsupported browsers

### 4. Bento Box Grid
- **Visual signature:** modular card grid of varying sizes, dense but organized, each card a self-contained unit
- **Best for:** product feature pages, dashboards, portfolios, landing pages with many features
- **Key tokens:** grid gap (16-24px), card radius (16-20px), consistent card padding, varied card sizes (1x/2x/2x2)
- **Anti-patterns:** too many card sizes (chaos), inconsistent card padding, cards without clear hierarchy

### 5. Flat Design
- **Visual signature:** solid colors, no shadows/gradients, bold typography, geometric shapes, high contrast
- **Best for:** web apps, mobile apps, startup MVPs, content-first sites
- **Key tokens:** no shadows, solid color fills, medium radius (8-12px), bold weight headings
- **Anti-patterns:** too-flat (no visual hierarchy cue), using for luxury/premium brands, no hover affordance

### 6. Brutalism / Neubrutalism
- **Visual signature:** raw, high-contrast, thick black borders, clashing colors, asymmetric, monospace/display fonts
- **Best for:** creative portfolios, agency sites, Gen Z brands, design studios
- **Key tokens:** 2-3px solid black borders, hard offset shadows (4px 4px 0 black), bold clashing colors, no rounded corners
- **Anti-patterns:** using for enterprise/finance/healthcare, ignoring readability, no responsive fallback

### 7. Dark Mode (OLED)
- **Visual signature:** true black background (#000), vibrant accents, layered surface grays, glowing highlights
- **Best for:** coding platforms, media/entertainment, gaming, night-mode apps
- **Key tokens:** surface layers (#000 / #0F0F0F / #1A1A1A), desaturated accents (not pure neon), elevated contrast text
- **Anti-patterns:** pure white text (eye strain), low-contrast secondary text, colored shadows, no light-mode fallback

### 8. Material Design (Material 3)
- **Visual signature:** elevation shadows, dynamic color, rounded shapes, FAB, ripple feedback, prominent navigation
- **Best for:** Android apps, cross-platform, enterprise mobile, Google-ecosystem products
- **Key tokens:** elevation scale (5 levels), M3 color roles (primary/secondary/tertiary + surface variants), 16dp grid, ripple on interaction
- **Anti-patterns:** mixing with iOS conventions, overusing elevation, ignoring M3 dynamic color

### 9. AI-Native UI
- **Visual signature:** conversational interface, streaming text, suggestion chips, context cards, subtle gradient accents
- **Best for:** AI products, chatbots, copilots, AI search tools
- **Key tokens:** chat bubble layout, typing indicator, streaming text animation, suggestion chip components
- **Anti-patterns:** long blocking spinners (use streaming), no empty-state guidance, hiding AI uncertainty

### 10. Editorial / Magazine
- **Visual signature:** strong typography hierarchy, multi-column layouts, serif headings, image-driven, generous line-height
- **Best for:** news sites, blogs, magazines, publishing, content platforms
- **Key tokens:** serif heading + sans body, multi-column CSS, large hero images, 1.6-1.75 line-height
- **Anti-patterns:** narrow content width on desktop, low-contrast body text, no image optimization

### 11. Conversion-Optimized (Landing)
- **Visual signature:** hero with CTA above fold, social proof, benefit-driven sections, repeated CTAs, urgency cues
- **Best for:** SaaS landing, product launches, lead gen, sales pages
- **Key tokens:** large hero section, CTA button (high contrast accent), testimonial cards, pricing table
- **Anti-patterns:** CTA below fold, too many CTAs (decision paralysis), no social proof, low-contrast CTA

### 12. Claymorphism
- **Visual signature:** soft 3D clay-like shapes, rounded corners, pastel colors, playful depth, inflated feel
- **Best for:** educational apps, children's apps, playful SaaS, creative tools
- **Key tokens:** large radius (20-30px), layered soft shadows, pastel palette, rounded everything
- **Anti-patterns:** using for enterprise/finance, over-decorated (distracting), low contrast pastel-on-pastel

### 13. Data-Dense Dashboard
- **Visual signature:** compact spacing, tabular data, small charts, multiple panels, information-first, minimal decoration
- **Best for:** analytics dashboards, ops consoles, BI tools, admin panels, monitoring
- **Key tokens:** 8px spacing scale, small font (12-14px body), table components, chart palettes
- **Anti-patterns:** wide whitespace, large fonts, decorative animations, few data points per screen

### 14. Aurora / Gradient Mesh
- **Visual signature:** smooth multi-color gradients, mesh backgrounds, flowing color blobs, modern and vibrant
- **Best for:** hero sections, marketing pages, creative SaaS, modern brand sites
- **Key tokens:** CSS radial/linear gradient mesh, animated gradient shift, glass cards on top
- **Anti-patterns:** gradient behind body text (readability), using for data dashboards, 5+ colors (muddy)

## Style Selection Decision Tree

```
Product type?
├─ Enterprise/SaaS/Tool/Dashboard → Minimalism | Data-Dense | Soft UI
├─ E-commerce/Retail → Conversion-Optimized | Flat | Bento
├─ Finance/Banking → Minimalism | Material | Trust-focused Flat
├─ Health/Wellness → Soft UI | Claymorphism | Organic Minimalism
├─ Creative/Portfolio/Agency → Brutalism | Bento | Editorial | Aurora
├─ Education/Kids → Claymorphism | Flat (playful)
├─ Media/Entertainment → Dark Mode | Glassmorphism | Aurora
├─ AI Product → AI-Native | Minimalism | Glassmorphism
├─ Content/Publishing → Editorial | Minimalism
└─ Landing/Marketing → Conversion-Optimized | Aurora | Bento
```

## Consistency Rules (apply regardless of style)

- One icon family (same stroke width, same corner radius) — never mix Lucide + Heroicons + emoji
- One shadow scale (define 3-5 elevation levels, use consistently)
- One radius scale (define 3-4 radius tokens: sm/md/lg/full)
- One type scale (define 6-8 font sizes, never use arbitrary px)
- One spacing scale (4/8dp rhythm, define space-1 to space-12)
