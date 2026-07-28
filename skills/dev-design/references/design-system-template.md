# DESIGN_SYSTEM.md Fixed Template

> This is the canonical template for the design system document produced by dev-design.
> dev-design MUST follow this section order. dev-code consumes these tokens directly.
> For full design knowledge, read `skills/_shared/design-principles.md`, `color-theory.md`, `typography-pairing.md`, `motion-basics.md`.

---

# 设计系统 / Design System — [项目名]

## 1. 设计基调 / Design Direction

- **UI 风格 / Style:** [e.g. Minimalism / Soft UI / Bento Grid — pick ONE primary from design-principles.md]
- **关键词 / Keywords:** [3-5 adjectives, e.g. 现代、专业、克制、可信赖]
- **适用理由 / Rationale:** [why this style fits the product type and audience]
- **次要影响 / Secondary influence:** [optional, ≤30%, e.g. Soft UI accents on card hover]

## 2. 配色 Token / Color Tokens

> See `skills/_shared/color-theory.md` for the full semantic token architecture.

### CSS 变量 / CSS Variables (tokens.css)

```css
:root {
  /* Light mode */
  --primary: #________;
  --on-primary: #________;
  --secondary: #________;
  --on-secondary: #________;
  --accent: #________;
  --on-accent: #________;
  --background: #________;
  --foreground: #________;
  --card: #________;
  --card-foreground: #________;
  --muted: #________;
  --muted-foreground: #________;
  --border: #________;
  --destructive: #________;
  --on-destructive: #________;
  --ring: #________;
}

[data-theme="dark"] {
  --primary: #________;
  --on-primary: #________;
  --background: #________;
  --foreground: #________;
  --card: #________;
  --card-foreground: #________;
  --muted: #________;
  --muted-foreground: #________;
  --border: #________;
  --destructive: #________;
  --ring: #________;
}
```

### WCAG 对比度备注 / Contrast Notes

| Token pair | Ratio | Pass AA? |
| --- | --- | --- |
| foreground / background | __:1 | ✅/❌ |
| muted-foreground / background | __:1 | ✅/❌ |
| on-primary / primary | __:1 | ✅/❌ |
| on-destructive / destructive | __:1 | ✅/❌ |
| muted-foreground / card | __:1 | ✅/❌ |

## 3. 字体配对 / Typography

- **标题字体 / Heading:** [e.g. Poppins]
- **正文字体 / Body:** [e.g. Open Sans]
- **配对名 / Pairing:** [e.g. Modern Professional — from typography-pairing.md]
- **Google Fonts URL:** `https://fonts.googleapis.com/css2?...`
- **CSS @import:** `@import url('...');`
- **Tailwind config:** `fontFamily: { heading: [...], body: [...] }`
- **中文 fallback:** `-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif`

### Type Scale

| Token | Size | Line-height | Usage |
| --- | --- | --- | --- |
| --text-xs | 12px | 1.5 | captions, badges |
| --text-sm | 14px | 1.5 | secondary text |
| --text-base | 16px | 1.5 | body |
| --text-lg | 18px | 1.5 | emphasized body |
| --text-xl | 20px | 1.4 | card titles |
| --text-2xl | 24px | 1.3 | section headings |
| --text-3xl | 30px | 1.25 | page titles |
| --text-5xl | 48px | 1.1 | hero title |

## 4. 间距系统 / Spacing Scale

> 4/8dp rhythm. All padding/margin/gap MUST use these tokens.

| Token | px | Usage |
| --- | --- | --- |
| --space-1 | 4px | tight icon-text gap |
| --space-2 | 8px | small gaps, button padding |
| --space-3 | 12px | input padding |
| --space-4 | 16px | default gap, card padding |
| --space-5 | 20px | section internal |
| --space-6 | 24px | section gap |
| --space-8 | 32px | large section gap |
| --space-10 | 40px | page section gap |
| --space-12 | 48px | hero spacing |
| --space-16 | 64px | page top/bottom |

## 5. 圆角 / 阴影 / 动效 Token / Radius · Shadow · Motion Tokens

### Radius

| Token | px | Usage |
| --- | --- | --- |
| --radius-sm | 4px | badges, tags |
| --radius-md | 8px | buttons, inputs |
| --radius-lg | 12px | cards |
| --radius-xl | 16px | modals, large cards |
| --radius-full | 9999px | pills, avatars |

### Shadow (elevation)

| Token | Value | Usage |
| --- | --- | --- |
| --shadow-sm | 0 1px 2px rgba(0,0,0,0.05) | subtle (cards default) |
| --shadow-md | 0 4px 12px rgba(0,0,0,0.08) | hover, dropdown |
| --shadow-lg | 0 8px 24px rgba(0,0,0,0.12) | modals, popovers |
| --shadow-xl | 0 16px 48px rgba(0,0,0,0.16) | full-screen overlays |

### Motion

| Token | Value | Usage |
| --- | --- | --- |
| --ease-out | cubic-bezier(0.16, 1, 0.3, 1) | enter animations |
| --ease-in | cubic-bezier(0.7, 0, 0.84, 0) | exit animations |
| --ease-in-out | cubic-bezier(0.65, 0, 0.35, 1) | state transitions |
| --duration-fast | 150ms | hover, tap |
| --duration-normal | 250ms | card, drawer |
| --duration-slow | 350ms | modal, page |

## 6. 反模式清单 / Anti-Patterns (AVOID)

> Industry-specific things to avoid for this product type.

- [specific anti-pattern 1, e.g. 高饱和霓虹色 — 不符合金融信任感]
- [specific anti-pattern 2, e.g. emoji 充当导航图标 — 不专业]
- [specific anti-pattern 3]
- [from industry-design-reasoning.md anti-pattern column]

## 7. 交付前 UI 清单 / Pre-Delivery UI Checklist

> dev-selfcheck enforces these. See `skills/_shared/accessibility-checklist.md` for full version.

- [ ] 无 emoji 充当结构图标（用 SVG: Lucide/Heroicons）
- [ ] 所有可点击元素有 cursor-pointer + 悬停反馈（150-300ms）
- [ ] 正文对比度 ≥ 4.5:1（WCAG AA）
- [ ] focus ring 可见（键盘导航）
- [ ] `@media (prefers-reduced-motion: reduce)` 已覆盖
- [ ] 响应式断点 375/768/1024/1440
- [ ] 间距遵循 4/8dp token 节奏（无随机 px）
- [ ] 语义化颜色 token（组件中无裸 hex）
- [ ] 字体经 @import 引入（非系统默认）
- [ ] 触控目标 ≥ 44×44px（移动端）
