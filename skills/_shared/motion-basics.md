# Motion Basics — Animation Principles & Presets

> Shared design knowledge for dev-design / dev-code / dev-selfcheck.
> Covers: timing/easing principles, reduced-motion, framework presets, anti-patterns.

## Core Principles

1. **Motion conveys meaning** — every animation should explain a state change, spatial relationship, or draw attention. Decorative-only animation is noise.
2. **Exit faster than enter** — elements leaving the screen should animate faster (150ms) than elements entering (250ms). Users want new content quickly, but need time to register what appeared.
3. **Spatial continuity** — if a card expands into a detail view, animate from the card's position, not a fade-in from nowhere.
4. **Respect reduced-motion** — `@media (prefers-reduced-motion: reduce)` MUST disable or minimize animations. Non-negotiable for accessibility.

## Timing Standards

| Interaction | Duration | Easing | Example |
| --- | --- | --- | --- |
| Micro (hover, tap feedback) | 100-150ms | `ease-out` | Button hover color change |
| Small (toggle, chip, tooltip) | 150-200ms | `ease-out` | Tooltip appear, chip select |
| Medium (card expand, drawer) | 200-300ms | `ease-in-out` | Side drawer slide-in |
| Large (page transition, modal) | 300-400ms | `ease-in-out` | Modal backdrop + content |
| Enter (new content appears) | 250-300ms | `ease-out` | List item stagger-in |
| Exit (content leaves) | 150-200ms | `ease-in` | Toast dismiss, modal close |

### Anti-timing

- **0ms (instant)** — FORBIDDEN for state changes (feels broken, no feedback)
- **>500ms** — FORBIDDEN for micro-interactions (feels sluggish, laggy)
- **Equal enter/exit** — avoid; exit should be faster

## Easing Functions

```css
:root {
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);      /* decelerate: elements entering */
  --ease-in: cubic-bezier(0.7, 0, 0.84, 0);        /* accelerate: elements leaving */
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);   /* standard: state transitions */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* overshoot: playful, bouncy */
}
```

- `ease-out`: start fast, end slow — for things ENTERING the screen (user sees the destination clearly)
- `ease-in`: start slow, end fast — for things LEAVING the screen (gets out of the way quickly)
- `ease-in-out`: symmetric — for state transitions (expand/collapse, toggle)
- `ease-spring` (overshoot): ONLY for playful/brand contexts — never for data UI or enterprise

## CSS Animation Presets

### Fade In (content appear)
```css
@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
.animate-fade-in { animation: fade-in 250ms var(--ease-out); }
```

### Slide Up (list stagger)
```css
@keyframes slide-up {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-slide-up { animation: slide-up 300ms var(--ease-out); }
```

### Scale In (modal/dialog)
```css
@keyframes scale-in {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
.animate-scale-in { animation: scale-in 200ms var(--ease-out); }
```

### Hover Lift (card interaction)
```css
.hover-lift { transition: transform 200ms var(--ease-out), box-shadow 200ms var(--ease-out); }
.hover-lift:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.12); }
```

## Stagger Pattern (list items)

When multiple items animate in, stagger them by 50-80ms (not all at once):

```css
.stagger-item { opacity: 0; animation: slide-up 300ms var(--ease-out) forwards; }
.stagger-item:nth-child(1) { animation-delay: 0ms; }
.stagger-item:nth-child(2) { animation-delay: 60ms; }
.stagger-item:nth-child(3) { animation-delay: 120ms; }
/* max 6-8 items staggered; beyond that, just fade the container */
```

## Reduced-Motion (MANDATORY)

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

This MUST be included in every frontend project. dev-selfcheck verifies its presence.

## Framework Quick Reference

### CSS Transitions (vanilla)
```css
.button { transition: background-color 150ms var(--ease-out), transform 150ms var(--ease-out); }
.button:hover { background-color: var(--primary); transform: translateY(-1px); }
```

### React (CSS Modules / Tailwind)
- Prefer CSS transitions over JS animation libraries for simple interactions.
- For complex choreography: Framer Motion (`motion.div` with `initial` / `animate` / `exit`).
- Stagger: `<motion.div initial={{opacity:0}} animate={{opacity:1}} transition={{delay: index * 0.06}}>`.

### Vue
- `<Transition>` / `<TransitionGroup>` for enter/leave.
- Transition classes: `.v-enter-from`, `.v-enter-active`, `.v-leave-to`.

## Anti-Patterns

- **Animating `width`/`height`** — triggers layout reflow (jank). Animate `transform` and `opacity` instead.
- **Animating `top`/`left`** — same; use `transform: translate()`.
- **No exit animation** — content vanishing instantly feels broken. Always animate leave.
- **Animation without reduced-motion fallback** — accessibility failure.
- **Spring/bounce on enterprise UI** — feels unprofessional; reserve for playful brands.
- **More than 3 simultaneous animations** — visual chaos. Sequence them.
- **Loading spinner for >3s with no progress** — use skeleton screen + progress indicator instead.
- **Layout-shifting animation** — animation that moves surrounding content (e.g. expanding a card pushes siblings). Use overlay/portal instead.
