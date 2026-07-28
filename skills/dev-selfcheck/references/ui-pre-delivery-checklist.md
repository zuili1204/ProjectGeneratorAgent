# UI Pre-Delivery Checklist

> Enforced by dev-selfcheck as a UI quality gate for frontend projects (fullstack / frontend_only / pure HTML+JS).
> This is the web-side subset distilled from `skills/_shared/accessibility-checklist.md` + the anti-pattern rules in `skills/_shared/design-principles.md`, scoped to what a static scan + LLM judgment can verify without a browser.
> Token rules cross-reference `skills/dev-code/references/token-implementation.md`.

---

## When to Run

- Run the **full checklist** when `project_type` is `fullstack` or `frontend_only` (any project with a frontend).
- Skip (mark N/A) for `cli` / `script` / `backend_only` projects with no UI.
- This gate runs AFTER the existing syntax/test/runtime checks — it does not replace them.

---

## Gate Categories

Each item is PASS / FAIL / N/A. Any FAIL on a CRITICAL item blocks delivery; FAIL on a HIGH item requires a fix or an explicit "unfixed issue" record with rationale.

### 1. Token Discipline (CRITICAL)

Verifies that the frontend consumes `DESIGN_SYSTEM.md` tokens rather than raw values.

| Check | Method | FAIL example |
| --- | --- | --- |
| `tokens.css` exists and is imported | `list_files` confirm `code/frontend/src/styles/tokens.css` (or equivalent); grep the entry HTML/JS for the import | `tokens.css` missing |
| No bare hex in components | `run_command` grep `#[0-9a-fA-F]{3,8}` across `.jsx/.tsx/.vue/.css/.html` under `code/frontend/src/` (exclude `tokens.css` itself and comments) | `style={{ color: '#2563eb' }}` |
| No arbitrary px in spacing | grep `\b(padding\|margin\|gap)\s*:\s*\d+px` for values NOT in the 4/8dp scale (4/8/12/16/20/24/32/40/48/64) | `padding: 13px` |
| Fonts loaded via @import | grep for the Google Fonts `@import url(...)` from DESIGN_SYSTEM.md §3; confirm no `font-family: serif` / `times` system defaults | `font-family: serif` |
| Dark mode tokens present | if DESIGN_SYSTEM.md declares dark mode, confirm `[data-theme="dark"]` block exists in `tokens.css` | dark block missing |

**Acceptable exception**: a commented `/* 例外: 装饰性渐变，非语义色 */` next to a bare hex in an SVG gradient stop. Everything else is FAIL.

### 2. Icon Discipline (CRITICAL)

| Check | Method | FAIL example |
| --- | --- | --- |
| No emoji as structural icons | scan nav / settings / system-control elements for emoji characters (🔍 ⚙️ 📊 etc.) used as the primary icon | `<button>⚙️ 设置</button>` (emoji as the only icon) |
| SVG icon family consistent | confirm icons come from one set (Lucide / Heroicons) with consistent stroke-width; mixed icon families = warning | Lucide + Heroicons mixed |

> Emoji in **content text** (e.g. a blog post body, a success toast message) is allowed. The ban applies to emoji used as **structural UI icons** (navigation, buttons, status indicators).

### 3. Color Contrast (HIGH)

| Check | Method | Threshold |
| --- | --- | --- |
| Body text contrast | LLM-judge the key foreground/background token pairs from `tokens.css` (compute ratio or estimate) | ≥ 4.5:1 (AA) |
| Large text / UI contrast | headings, icon backgrounds, borders | ≥ 3:1 |
| Info not by color alone | scan for status indicators that rely solely on color (e.g. a red dot with no text/icon) | must pair color with text or icon |

> If a precise ratio is hard to compute, the LLM may paste the token pairs and a reasoned estimate (e.g. "foreground #1e293b on background #f8fafc ≈ 12:1, PASS"). The estimate MUST cite the actual token values, not "looks fine".

### 4. Touch Targets (HIGH, mobile)

| Check | Method | Threshold |
| --- | --- | --- |
| Interactive element size | scan buttons / links / inputs for `min-width`/`min-height` or Tailwind `min-w-[44px]` | ≥ 44×44px on mobile |
| Touch spacing | gap between adjacent touch targets | ≥ 8px |

### 5. Accessibility (HIGH)

| Check | Method | FAIL example |
| --- | --- | --- |
| `img` alt text | grep `<img` tags; meaningful images need `alt="..."` | `<img src="logo.png">` (no alt) |
| Icon-only buttons have `aria-label` | grep `<button` with no visible text | `<button><svg>...</svg></button>` (no aria-label) |
| Form labels associated | grep `<input` for paired `<label for=...>` or `aria-label` | `<input type="email">` with no label |
| Focus ring visible | confirm `:focus-visible` / `:focus` styles exist (not `outline: none` without replacement) | `* { outline: none }` with no focus ring |
| Heading hierarchy | scan `h1`→`h6` for skipped levels | `h1` → `h3` (skip h2) |
| `prefers-reduced-motion` covered | grep `@media (prefers-reduced-motion` in CSS / tokens.css | missing |

### 6. Responsive (HIGH)

| Check | Method | Threshold |
| --- | --- | --- |
| viewport meta | grep `<meta name="viewport"` in HTML | `width=device-width, initial-scale=1` present |
| Breakpoints | scan CSS / Tailwind config for mobile-first breakpoints | 375 / 768 / 1024 / 1440 (or equivalent) |
| No horizontal scroll | LLM-judge: confirm no fixed-width elements exceeding 375px on mobile | `width: 1200px` in a mobile-first section |

---

## Compact Checklist (paste into SELF_CHECK.md)

```markdown
### UI 质量门禁（前端项目必填）
- [ ] tokens.css 存在且被引入（CRITICAL）
- [ ] 组件无裸 hex 值（CRITICAL）
- [ ] 间距无任意 px，遵循 4/8dp token（CRITICAL）
- [ ] 字体经 @import 引入，无系统默认字体（CRITICAL）
- [ ] 无 emoji 充当结构图标（CRITICAL）
- [ ] 正文对比度 ≥ 4.5:1（HIGH）
- [ ] 触控目标 ≥ 44×44px（移动端）（HIGH）
- [ ] img 有 alt、icon-only 按钮有 aria-label（HIGH）
- [ ] focus ring 可见（键盘导航）（HIGH）
- [ ] prefers-reduced-motion 已覆盖（HIGH）
- [ ] viewport meta + 响应式断点 375/768/1024/1440（HIGH）
- [ ] 信息不仅靠颜色传达（HIGH）
```

---

## Verification Evidence Requirement

Per the dev-selfcheck core principle (`NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE`), the UI gate is no exception:

- For grep-based checks (hex, px, emoji, alt, aria-label): paste the actual `run_command` grep output (command + hit count + sample lines). "No hits" MUST be backed by a grep that returned exit_code 1 / empty output.
- For LLM-judged checks (contrast, hierarchy, responsive): cite the actual token values / code snippets inspected, not a vague "looks compliant".
- A FAIL item that was fixed MUST be re-verified with a fresh grep / re-judgment, and the new evidence pasted.

---

## Relationship to Other Gates

- This checklist is **additive** to the existing dev-selfcheck seven categories (syntax / test execution / tags / paths / deps / startup command / runtime verification). It does NOT replace them.
- The token rules here mirror the hard constraints in `skills/dev-code/references/token-implementation.md` §3 — dev-code is expected to self-audit before handoff, so a FAIL here usually means dev-code skipped its self-audit.
- dev-review's UI dimension (see `skills/dev-review/SKILL.md`) reviews token consistency at design time; this gate verifies it at delivery time.
