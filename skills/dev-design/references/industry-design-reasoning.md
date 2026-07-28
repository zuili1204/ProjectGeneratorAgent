# Industry Design Reasoning Table

> Used by dev-design to generate DESIGN_SYSTEM.md. Maps product type → recommended style, color baseline, typography mood, key effects, and anti-patterns.
> Curated baselines — adjust per specific brand requirements. Read `skills/_shared/` for full knowledge.

## How to Use

1. From REQUIREMENT.md, identify the product type / industry.
2. Find the closest match in the table below.
3. Use the recommended style + color baseline + typography as the starting point for DESIGN_SYSTEM.md.
4. Carry the anti-patterns into DESIGN_SYSTEM.md §6.
5. If no exact match, pick the closest category and note the assumption.

## Reasoning Table

| Product Type | Recommended Style | Color Baseline | Typography Pairing | Key Effects | Anti-Patterns |
| --- | --- | --- | --- | --- | --- |
| **SaaS / 工具** | Minimalism / Soft UI | 信任蓝 #2563eb + 橙 CTA #ea580c | Modern Professional (Poppins/Open Sans) | 柔和阴影 + 200ms 过渡 | 高饱和霓虹、emoji 图标、装饰性渐变 |
| **Micro SaaS** | Minimalism | 靛蓝 #6366f1 + 翠绿 CTA #059669 | Tech Startup (Space Grotesk/DM Sans) | 微交互 + 骨架屏 | 企业厚重感、宽留白 |
| **电商 (通用)** | Conversion-Optimized | 成功绿 #059669 + 紧迫橙 #ea580c | Geometric Modern (Outfit/Work Sans) | 悬停放大 + 加车反馈 | 仅暗色模式、低对比、无 CTA 反馈 |
| **电商 (奢侈品)** | Editorial / Minimal | 深黑 #1c1917 + 金 #a16207 | Classic Elegant (Playfair/Inter) | 克制动效 + 高级感淡入 | 高饱和色、卡通字体、促销红 |
| **金融 / 银行** | Trust & Authority / Minimalism | 海军蓝 #0f172a + 金/绿 #22c55e | Trust Finance (Source Serif 4/Inter) | 克制动效 + 数字滚动 | AI 紫粉渐变、装饰性模糊、霓虹 |
| **Fintech / 加密** | Dark Mode / Minimal | 金 #f59e0b + 紫 #8b5cf6 (暗底) | Tech Startup (Space Grotesk/DM Sans) | 实时数字 tween + 暗色玻璃 | 浅色仅、企业灰、低对比 |
| **医疗 / 健康** | Calm / Organic / Soft UI | 冷静青 #0891b2 + 健康绿 #059669 | Wellness Calm (Lora/Raleway) | 柔和淡入 + 呼吸感 | 高饱和红、强对比硬边、冷硬几何 |
| **教育 (通用)** | Flat / Minimalism | 活力靛 #4f46e5 + 橙 #ea580c | Modern Professional (Poppins/Open Sans) | 进度反馈 + 卡片翻转 | 冷硬、低饱和、无反馈 |
| **教育 / 儿童** | Claymorphism | 活力靛 + 橙 + 粉 | Playful Creative (Fredoka/Nunito) | 弹性回弹 + 趣味微交互 | 冷硬几何、低饱和、企业感 |
| **创意 / 作品集** | Brutalism / Bento | 大胆粉 #ec4899 + 青 #0891b2 | Bold Statement (Bebas/Source Sans 3) | 视差 + 动态排版 | 企业感、克制留白、通用模板 |
| **代理 / 工作室** | Bento / Aurora | 渐变 mesh + 玻璃 | Geometric Modern (Outfit/Work Sans) | 滚动揭示 + 卡片悬停 | 企业模板、低对比、无动效 |
| **游戏 / 娱乐** | Dark Mode / Cyberpunk | 霓虹紫 #7c3aed + 玫红 #f43f5e (暗底) | Bold Statement (Bebas/Source Sans 3) | 粒子 + 发光 + 视差 | 浅色仅、平铺无层次、低对比 |
| **数据看板 / BI** | Data-Dense / Bento | 深底 + 数据蓝 #1e40af + 琥珀 #d97706 | Data Precision (IBM Plex Sans/Mono) | 骨架屏 + 数字 tween | 装饰性动效、宽留白、大字号 |
| **政府 / 公共服务** | Accessible / Minimalism | 高对比海军蓝 #0f172a + 蓝 #0369a1 | Minimal Swiss (Inter) | 无装饰、即时反馈 | 装饰性渐变、低对比、emoji |
| **社交 / 社区** | Flat / Minimalism | 活力色 (粉/蓝/紫 任一) + 中性底 | Geometric Modern (Outfit/Work Sans) | 微交互 + 实时反馈 | 企业灰、无动效、低密度 |
| **内容 / 出版** | Editorial / Magazine | 中性 + 强调色 #18181b + #2563eb | Editorial Classic (Cormorant/Libre Baskerville) | 滚动阅读 + 图片淡入 | 窄栏桌面、低对比正文、无图优化 |
| **AI 产品 / 聊天** | AI-Native / Minimalism | 紫蓝 #6366f1 + 中性底 | Tech Startup (Space Grotesk/DM Sans) | 流式文本 + 打字指示器 | 长 spinner、无空态引导、隐藏不确定性 |
| **落地页 / 营销** | Conversion-Optimized / Aurora | 品牌色 + 高对比 CTA | Bold Statement (Bebas/Source Sans 3) 或 Geometric Modern | 滚动揭示 + hero 动效 | CTA 在折叠下方、多 CTA、无社会证明 |
| **预约 / 服务** | Soft UI / Conversion | 品牌柔和色 + 金/绿 CTA | Wellness Calm (Lora/Raleway) | 表单分步 + 确认反馈 | 冷硬表单、无进度、低对比 |
| **餐饮 / 餐厅** | Editorial / Warm | 暖色 #b45309 + #166534 | Classic Elegant (Playfair/Inter) | 图片为主 + 悬停菜单 | 冷色调、无图、企业模板 |
| **房地产** | Minimalism / Editorial | 中性 + 强调 #0f172a + #2563eb | Classic Elegant (Playfair/Inter) | 图片画廊 + 悬停放大 | 低质量图、无图优化、密集文字 |
| **旅行 / 酒店** | Soft UI / Editorial | 柔和蓝 #0284c7 + 暖色 #f59e0b | Wellness Calm (Lora/Raleway) | 视差 hero + 卡片悬停 | 密集列表、无图、冷硬 |

## Density / Variance / Motion Dials

Adjust the design system output with 3 dials (1=low, 10=high):

| Dial | Low (1-3) | Mid (4-7) | High (8-10) |
| --- | --- | --- | --- |
| **Variance** | 居中 / 极简 | 平衡 / 现代 | 大胆 / 不对称 (Bento, Brutalism) |
| **Motion** | 微交互 | 标准滚动/stagger | 复杂编排 (pin, parallax) |
| **Density** | 宽松 (24-96px 间距) | 标准 (16-64px) | 密集/看板 (8-32px) |

Default: variance=5, motion=4, density=5. Override for:
- Dashboards: density=8, motion=3, variance=4
- Marketing/landing: variance=7, motion=6, density=4
- Enterprise/SaaS: variance=3, motion=3, density=5
- Creative/portfolio: variance=9, motion=8, density=4
