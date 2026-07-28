# Accessibility Checklist (WCAG 2.1 AA)

> Shared design knowledge for dev-design / dev-code / dev-selfcheck.
> The minimum accessibility bar for every frontend project. dev-selfcheck enforces these as a UI quality gate.

## How to Verify

- **Contrast:** inspect color pairs in CSS/tokens, compute ratio (≥4.5:1 body, ≥3:1 large/UI). Tools: browser DevTools contrast checker, or LLM manual check of the 5 critical pairs (see color-theory.md).
- **Keyboard:** tab through the page — every interactive element reachable + operable, focus visible, order matches visual order.
- **Screen reader:** meaningful images have alt, icon-only buttons have aria-label, form inputs have associated labels.
- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` present and tested.

## CRITICAL Checks (failure = blocker)

### 1. Color Contrast
- [ ] Body text contrast ≥ 4.5:1 against background
- [ ] Large text (≥18px or ≥14px bold) contrast ≥ 3:1
- [ ] Icon/UI component contrast ≥ 3:1
- [ ] `--muted-foreground` on `--background` ≥ 4.5:1 (most common failure)
- [ ] `--on-primary` on `--primary` ≥ 4.5:1
- [ ] Dark mode contrast checked independently (not inferred from light mode)

### 2. Keyboard Navigation
- [ ] All interactive elements reachable via Tab (no `tabindex="-1"` on buttons/links)
- [ ] Focus order matches visual reading order (top-to-bottom, left-to-right)
- [ ] Focus ring visible (2-4px outline, `--ring` color, not `outline: none` without replacement)
- [ ] Modal/dialog traps focus within (focus doesn't escape to background)
- [ ] Escape key closes modals/drawers
- [ ] No keyboard trap (user can always Tab out)

### 3. Images & Icons
- [ ] Meaningful images have descriptive `alt` text
- [ ] Decorative images have `alt=""` (empty, not omitted)
- [ ] Icon-only buttons have `aria-label` (e.g. `<button aria-label="关闭"><svg>...</svg></button>`)
- [ ] No emoji used as structural icons (navigation, settings, system controls) — use SVG (Lucide/Heroicons)

### 4. Forms
- [ ] Every input has an associated `<label for="id">` (not placeholder-as-label)
- [ ] Required fields marked with `aria-required="true"` or `required`
- [ ] Error messages near the field (not only at top), with `aria-describedby` linking input to error
- [ ] Error messages include text (not color alone — add icon + text)
- [ ] Field validation doesn't rely on color alone

## HIGH Checks (failure = major)

### 5. Semantic HTML
- [ ] Use `<nav>`, `<main>`, `<article>`, `<section>`, `<aside>`, `<footer>` for landmarks
- [ ] Heading hierarchy is sequential (h1 → h2 → h3, no level skip)
- [ ] Exactly one `<h1>` per page
- [ ] Lists use `<ul>`/`<ol>` + `<li>` (not divs styled as lists)
- [ ] Buttons are `<button>`, links are `<a>` (don't use `<div onclick>`)

### 6. Responsive & Layout
- [ ] `<meta name="viewport" content="width=device-width, initial-scale=1">` present
- [ ] Zoom NOT disabled (`user-scalable=yes` or omitted — never `maximum-scale=1`)
- [ ] No horizontal scroll on 375px viewport
- [ ] Body font-size ≥ 16px on mobile (avoids iOS auto-zoom)
- [ ] Touch targets ≥ 44×44px (expand with padding/hitSlop if visual is smaller)

### 7. Motion & Animation
- [ ] `@media (prefers-reduced-motion: reduce)` present and reduces/disables animations
- [ ] No auto-playing video/audio (or provide controls + pause)
- [ ] No content flashing more than 3 times/second (seizure risk)

### 8. ARIA (when needed)
- [ ] `role` only when semantic HTML is insufficient (don't add `role="button"` to a `<button>`)
- [ ] Dynamic content updates announced via `aria-live` (e.g. toast notifications: `aria-live="polite"`)
- [ ] Loading states announced (`aria-busy="true"` or `role="status"`)
- [ ] Expandable content: `aria-expanded` on trigger, `aria-controls` linking to content

## MEDIUM Checks (failure = minor)

### 9. Language & Content
- [ ] `<html lang="zh-CN">` (or correct language code) present
- [ ] `lang` attribute changes for foreign-language content
- [ ] Abbreviations explained on first use (`<abbr title="...">`)

### 10. Skip Links & Navigation
- [ ] "Skip to main content" link present (first focusable element)
- [ ] Multiple ways to find a page (nav + search, or nav + sitemap)

## Quick Verification Commands

```bash
# Check for missing alt attributes
grep -rn '<img' code/frontend/src/ | grep -v 'alt='

# Check for icon-only buttons missing aria-label
grep -rn '<button' code/frontend/src/ | grep -v 'aria-label'

# Check for outline:none without focus replacement
grep -rn 'outline:\s*none' code/frontend/src/

# Check reduced-motion presence
grep -rn 'prefers-reduced-motion' code/frontend/src/

# Check viewport meta
grep -rn 'viewport' code/frontend/index.html
```

## Common Failure Patterns (actively avoid)

1. **Placeholder-as-label:** `<input placeholder="邮箱">` with no `<label>` — screen reader users get no label. Fix: add `<label for="email">邮箱</label>`.
2. **`outline: none` with no replacement:** removes focus ring → keyboard users can't see where they are. Fix: add `:focus-visible { outline: 2px solid var(--ring); }`.
3. **Color-only meaning:** "red text = error, green text = success" with no icon/text. Colorblind users can't tell. Fix: add icon + text label.
4. **`<div onclick>` as button:** not keyboard accessible, no button semantics. Fix: use `<button>`.
5. **Missing `lang` attribute:** screen reader reads with wrong pronunciation. Fix: `<html lang="zh-CN">`.
6. **Touch target too small:** 24×24px icon button with no padding. Fix: `padding: 12px` or `min-width: 44px; min-height: 44px`.
7. **Disabled zoom:** `maximum-scale=1` — violates WCAG 1.4.4. Fix: remove the restriction.
