# حروفي Hroofy: دليل المتجر

متجر طباعة حسب الطلب (POD) لكتب تلوين الأطفال التعليمية: الحروف العربية والإنجليزية، الأرقام، والرسم الإبداعي.

- المتجر: `c9ebj8-dw.myshopify.com` (EGP، مصر)
- القالب: نسخة **Hroofy Kids - Draft** من Horizon (غير منشورة، للمراجعة قبل النشر)

---

## 1. الهوية التجارية

### مقترحات الاسم

| # | العربي | English | الشعار | ليه؟ |
|---|--------|---------|--------|------|
| ⭐ 1 | **حروفي** | **Hroofy** | لوّن.. تعلّم.. ابدع / *Color. Learn. Create.* | قصير وسهل النطق وفيه ملكية للطفل ("حروفي أنا"). بيوصف المنتج الأساسي ويتوسع بسهولة للأرقام والرسم. الـ Handle بالإنجليزي سهل للدومين والسوشيال. |
| 2 | أرض لوني | Lawni Land | عالم كامل من الألوان والتعلم | مرح وخيالي، لكنه أطول وأضعف في الـ SEO. |
| 3 | أقلام صغار | Tiny Crayons | فنانين صغار، أحلام كبيرة | واضح بالإنجليزي، لكن الترجمة العربية أضعف. |

**الاختيار: حروفي / Hroofy**

**قصة البراند:** حروفي بدأت من سؤال بيسأله كل أب وأم: "إزاي أخلّي ابني يتعلم وهو مبسوط، بعيد عن الموبايل؟". الإجابة كانت أبسط مما نتخيل: قلم تلوين وصفحة بتحكي حكاية. كل كتاب من حروفي مصمم إن الطفل يتعلم حرف أو رقم أو فكرة جديدة وهو بيلوّن، على ورق سميك يستحمل خياله، وبخطوط عريضة تناسب إيده الصغيرة. ولأن كل كتاب بيتطبع مخصوص عند الطلب، بيوصل لبيتك جديد ومعمول عشان طفلك.

### لوحة الألوان (Design System)

| الدور | الاسم | HEX | الاستخدام |
|------|------|-----|-----------|
| Background | Cream | `#FFFBF2` | خلفية الصفحات، دافية ومريحة للعين |
| Text | Ink | `#2B2D42` | النصوص (تباين 13.1:1 على الخلفية) |
| Text Soft | Ink Soft | `#5B5F7A` | نصوص ثانوية |
| Primary Button | Coral | `#FF6B4A` | أزرار الشراء والـ CTA |
| Primary Shadow | Coral Dark | `#E2553A` | ظل الزر الضاغط (Toy UI) |
| Secondary Accent | Teal | `#2EC4B6` | الأزرار الثانوية، الاختيارات النشطة |
| Highlight | Sunny | `#FFD23F` | شارات الخصم، النجوم |
| Fun 1 | Sky | `#5B8DEF` | بطاقات العمر |
| Fun 2 | Grape | `#A66CFF` | الرسم الإبداعي |
| Fun 3 | Bubblegum | `#FF8FB1` | الحروف |
| Fun 4 | Mint | `#7BD389` | النجاح والإنجاز |
| Border | Peach | `#FFE3B3` | الحدود والفواصل |

> ♿ **إمكانية الوصول:** نص الأزرار كحلي `#2B2D42` على الكورال (تباين 4.79:1، بيعدّي WCAG AA). الأبيض على الكورال 2.8:1 بس، فما يتستخدمش للنص. المبالغ في شريط السلة لونها `#CC3F25` عشان تبقى مقروءة على الخلفية الفاتحة.

### الخطوط
- **العناوين:** Baloo Bhaijaan 2 (مرح ومستدير وبيدعم العربي والإنجليزي)
- **النصوص:** Cairo (واضح جداً للعربي)
- **احتياطي:** Tajawal ثم خطوط النظام

بتتحمّل من Google Fonts عن طريق `snippets/hroofy-brand-styles.liquid`، وبتغيّر متغيرات خطوط Horizon (`--font-body--family`، `--font-heading--family` ...).

---

## 2. الكتالوج (اتعمل على المتجر)

### الـ Metafields (namespace `custom`)
`age_range`، `skill_type`، `page_count`، `paper_spec`، `book_size`، `pod_provider`، `learning_outcomes`، `preview_character`

### الـ Smart Collections (بتتملى تلقائياً من الـ Tags)
| المجموعة | Handle | الـ Tag |
|----------|--------|---------|
| كل كتب التلوين | `all-coloring-books` | `Hroofy_Book` |
| كتب تلوين الحروف | `letters-coloring-books` | `Letters` |
| الأرقام والحساب | `numbers-coloring-books` | `Numbers` |
| رسومات إبداعية ومغامرات | `creative-drawing-books` | `Drawing` |
| من 3 إلى 4 سنوات | `age-3-4` | `Age_3-4` |
| من 5 إلى 6 سنوات | `age-5-6` | `Age_5-6` |
| 7 سنوات فأكثر | `age-7-plus` | `Age_7-Plus` |
| باقات التوفير | `bundles` | `Bundle` |

### المنتجات (كلها Draft لحد رفع الصور)
| المنتج | Handle | Paperback | Hardcover |
|--------|--------|-----------|-----------|
| كتاب تلوين الحروف العربية من أ إلى ي | `arabic-alphabet-coloring-book` | 349 ~~499~~ | 549 ~~749~~ |
| ABC Fun: الحروف الإنجليزية A-Z | `english-alphabet-coloring-book` | 349 ~~499~~ | 549 ~~749~~ |
| كتاب الأرقام والحساب 1-20 | `numbers-math-coloring-book` | 349 ~~499~~ | 549 ~~749~~ |
| عالم الحيوانات: 40 حيواناً | `animals-world-coloring-book` | 349 ~~499~~ | 549 ~~749~~ |
| الفضاء والمغامرات | `space-adventures-coloring-book` | 349 ~~499~~ | 549 ~~749~~ |
| ارسم وأكمل: الرسم الإبداعي | `draw-and-complete-creative-book` | 349 ~~499~~ | 549 ~~749~~ |
| باقة الحروف المزدوجة (عربي + إنجليزي) | `arabic-english-letters-bundle` | 599 ~~998~~ | 899 ~~1498~~ |
| باقة العباقرة الشاملة (6 كتب) | `genius-complete-bundle` | 1799 ~~2994~~ | 2699 ~~4494~~ |

**التسعير:** الكتب المنفردة عليها خصم 30%، والباقات عليها خصم 40%. الأسعار بتنتهي بـ 9 (تسعير نفسي)، والكتاب المقوى بيبان "ترقية" منطقية بفرق 200 ج.م.

**الـ POD:** `Vendor = Hroofy`، و`Product Type = Coloring Book / Coloring Book Bundle`، و`custom.pod_provider = Lulu Direct`، و`Tag = POD_Lulu-Direct`. Lulu Direct هو الأنسب لطباعة الكتب (Paperback وHardcover، مقاس US Letter 8.5 × 11 بوصة). **نوع الورق ووزنه** بتختاره في مشروع Lulu، ومالوش رقم مكتوب في المتجر عشان مانوعدش بحاجة مش متأكدين منها. بعد تثبيت تطبيق Lulu Direct، اربط كل Variant بملف الـ PDF الداخلي والغلاف.

---

## 3. برومبتات توليد الصور (AI Image Prompts)

> للغلاف: Midjourney v7 / Flux / Ideogram (Ideogram الأفضل لو محتاج نص على الغلاف). للصفحات الداخلية: أي مولد مع `--style raw`، أو اكتب "pure black and white line art". النص العربي على الغلاف ضيفه بعدين في Canva أو Figma، لأن مولدات الصور بتغلط في الحروف العربية.

### 1) كتاب الحروف العربية
**Cover (3D Mockup):**
```
3D product mockup of a children's coloring book standing upright on a soft cream surface, slight angle, glossy hardcover, cover shows a giant playful Arabic letter "أ" made of colorful crayon strokes with a cute smiling rabbit hugging it, surrounded by floating Arabic letters ب ت ث in coral, sunny yellow, teal and bubblegum pink, rounded clay-like 3D style, soft studio lighting, gentle shadows, pastel peach background, a few real wax crayons scattered beside the book, high detail, commercial e-commerce photography, 4k --ar 4:5
```
**Inside page (Line art):**
```
Children's coloring book page, pure black and white line art, thick bold clean outlines (4px), no shading, no gray, white background, a large Arabic letter "ب" in bubble outline style in the center, next to it a cute cartoon duck (بطة) wearing a little bow, simple dotted tracing line of the letter at the bottom, big empty areas easy for a 4 year old to color, printable A4, vector style --ar 3:4 --style raw
```

### 2) ABC Fun (الحروف الإنجليزية)
**Cover:**
```
3D mockup of a kids' coloring book "ABC Fun", paperback lying at a 30 degree angle on a light wooden table, cover shows chunky 3D balloon letters A B C in coral, teal and yellow, a friendly cartoon bear holding a crayon, apple and star doodles around, claymorphism toy style, soft natural window light, colored pencils and a crayon box next to the book, clean minimal pastel background, premium product photography --ar 4:5
```
**Inside page:**
```
Kids coloring page, black and white only, bold thick outlines, no shading, capital letter "A" and lowercase "a" as large hollow bubble letters on the top, a big cute cartoon apple with a smiling face and a little worm below, dotted tracing lines with numbered stroke arrows, generous white space, printable A4 coloring sheet for preschoolers --ar 3:4 --style raw
```

### 3) الأرقام والحساب
**Cover:**
```
3D product mockup of a children's math coloring book standing on a cream background, cover features big playful 3D numbers 1 2 3 in rainbow crayon textures, a cute owl teacher with glasses counting on its wings, little stars and plus/minus signs floating, toy-like rounded clay style, soft lighting, crayons and wooden counting blocks beside the book, e-commerce hero shot --ar 4:5
```
**Inside page:**
```
Color by number coloring page for kids, black and white line art, thick outlines, no shading, a big cartoon hot air balloon divided into large simple areas each labeled with a small number 1 to 5, a color key at the bottom with five empty circles labeled 1-5, simple clouds, white background, easy for 5-7 year olds, printable A4 --ar 3:4 --style raw
```

### 4) عالم الحيوانات
**Cover:**
```
3D mockup of a kids animal coloring book, hardcover standing upright, slight perspective, cover illustration of a happy lion, elephant, giraffe and dolphin peeking from behind a big leafy frame, bright coral, teal, sunny yellow palette, cute chibi proportions, claymorphism 3D style, soft shadows, warm pastel background, real crayons scattered, professional product photography --ar 4:5
```
**Inside page:**
```
Coloring book page for toddlers, pure black outlines on white, very thick bold lines, no shading, a cute baby elephant spraying water from its trunk with big round water drops, simple grass and two flowers, large simple shapes, kawaii style, minimal details, printable A4 --ar 3:4 --style raw
```

### 5) الفضاء والمغامرات
**Cover:**
```
3D product mockup of a children's space coloring book, cover shows a small astronaut kid waving from a cartoon rocket flying past Saturn and a smiling moon, colorful planets in coral, teal, purple and yellow, starry deep blue background with crayon texture, toy-like 3D rendering, book placed on a cream desk with crayons and a small toy rocket, dramatic soft lighting, e-commerce photo --ar 4:5
```
**Inside page:**
```
Kids coloring page, black and white line art, bold clean outlines, no shading, a cute cartoon rocket with three round windows blasting off, a happy astronaut floating with a star, Saturn with rings in the corner, simple stars and a small alien waving, medium detail for ages 6-9, white background, printable A4 --ar 3:4 --style raw
```

### 6) ارسم وأكمل
**Cover:**
```
3D mockup of a creative "draw and complete" activity book for kids, cover shows half of a funny monster face drawn and the other half left as dotted lines with a child's hand holding a crayon completing it, paint splashes in coral, teal, purple and yellow, playful doodles, claymorphism style, cream background, colored markers next to the book, bright soft lighting, product photography --ar 4:5
```
**Inside page:**
```
Draw and complete activity page for children, black and white line art, thick outlines, left half of a cute butterfly fully drawn, right half empty with faint dotted guide points for symmetry, a title area at the top left blank, white background, no shading, printable A4 --ar 3:4 --style raw
```

### 7) باقة الحروف المزدوجة
**Cover / Mockup:**
```
3D mockup of two children's coloring books side by side, one with a giant Arabic letter "أ" on the cover in coral, the other with "ABC" balloon letters in teal, tied together with a yellow ribbon and a "SAVE 40%" round sticker, cream background, crayons scattered, soft studio lighting, playful toy-like style, e-commerce bundle shot --ar 4:5
```

### 8) باقة العباقرة الشاملة
**Cover / Mockup:**
```
3D product mockup of a gift box set of six colorful kids' coloring books fanned out (Arabic letters, ABC, numbers, animals, space, creative drawing), each with a bright cover in coral, teal, yellow, purple, pink and mint, a gold star "Genius Bundle" badge, crayons and a wrapped gift ribbon, cream backdrop with confetti, soft lighting, premium e-commerce hero photo --ar 4:5
```

---

## 4. أقسام القالب (Shopify OS 2.0)

| الملف | النوع | المكان |
|-------|-------|--------|
| `sections/kids-playful-hero.liquid` | Section + Blocks (شارات الثقة) | الصفحة الرئيسية |
| `sections/age-skill-navigator.liquid` | Section + Blocks (بطاقات Collections) | الصفحة الرئيسية |
| `sections/interactive-coloring-preview.liquid` | Section (لصفحة المنتج بس) | `templates/product.json` |
| `snippets/cart-free-shipping-goal.liquid` | Snippet | داخل `snippets/cart-drawer.liquid` |
| `snippets/hroofy-brand-styles.liquid` | Snippet (الخطوط والألوان) | `layout/theme.liquid` |
| `config/settings_data.json` | ألوان وحواف القالب | — |

**ليه شريط السلة Snippet مش Section؟** الـ Cart Drawer في Horizon نفسه Snippet، وبيتعمل له Re-render بالـ Section Rendering API بعد كل تعديل في السلة. لو الشريط جواه، هيتحدث تلقائياً. الحدود (750 / 1500 ج.م) بتتعدل من: **Settings ← Custom data ← Shop ← حروفي**.

### معاينة التلوين
الرسمة بتتحدد من الـ Metafield `custom.preview_character`:
- حرف أو رقم (`أ`، `A`، `5`) ← مشهد الحرف الكبير
- `fish` ← مشهد السمكة (كتاب الحيوانات)
- `rocket` ← الصاروخ (كتاب الفضاء)
- `star` ← النجمة والقمر (الرسم الإبداعي والباقات)

---

## 5. خطوات قبل الإطلاق
1. **اللغة:** Settings ← Languages: خلّي العربية لغة المتجر الافتراضية (عشان `dir="rtl"`).
2. **الصور:** ولّد الصور بالبرومبتات، وارفعها لكل منتج، وبعدين حوّل الحالة لـ Active.
3. **الشحن المجاني:** خصم تلقائي للشحن المجاني فوق 750 ج.م (اتعمل).
4. **هدية الكتاب المصغر (1500 ج.م):** اتعملت (انظر القسم 6).
5. **Lulu Direct:** ثبّت التطبيق، وارفع ملفات الـ PDF، واربط كل Variant.
6. **راجع القالب** في Online Store ← Themes ← Hroofy Kids - Draft ← Preview، وبعدها Publish.
7. **الخطة:** المتجر على Trial، ولازم تعمل Upgrade قبل استقبال طلبات حقيقية.

---

## 6. الهدية المجانية، الصفحات، والقوائم

### هدية "كتيب تلوين الجيب السحري"
- المنتج: `magic-pocket-coloring-gift`، سعره 99 ج.م، ومخفي من البحث (`seo.hidden = 1`) ومش موجود في أي Collection.
- الخصم التلقائي (Buy X Get Y): لما كتب حروفي (مجموعة `all-coloring-books`) توصل لـ 1500 ج.م، الكتيب بيبقى خصم 100%، وبحد أقصى كتيب واحد لكل طلب.
- Shopify مابيضيفش هدية الـ BXGY للسلة لوحده، فشريط السلة بيعمل الآتي:
  - بيظهر زرار **"أضف هديتي المجانية"** لما السلة توصل للحد.
  - **بيشيل الهدية تلقائياً** لو المجموع نزل تحت الحد، عشان العميل مايدفعش 99 ج.م من غير ما ياخد باله.
  - سعر الهدية نفسها مابيتحسبش في التقدم.
- الـ Variant بتاع الهدية متخزن في `shop.metafields.hroofy.gift_variant`.

### الصفحات
| الصفحة | الرابط |
|--------|--------|
| قصتنا في حروفي | `/pages/our-story` |
| الأسئلة الشائعة | `/pages/faq` |
| سياسة الشحن والاسترجاع | `/pages/shipping-returns` |
| تواصل معنا (موجودة) | `/pages/contact` |

> ⚠️ راجع مدة الطباعة (3-5 أيام عمل) والتوصيل (3-7 أيام عمل) وشروط الاسترجاع (14 يوم) مع مزوّد الطباعة الفعلي وقانون حماية المستهلك قبل الإطلاق.

### القوائم
**Header (`main-menu`):**
- الرئيسية
- كتب التلوين ← كتب الحروف / الأرقام والحساب / رسومات إبداعية ومغامرات / كل الكتب
- حسب العمر ← 3-4 / 5-6 / 7+
- باقات التوفير 🎁
- قصتنا
- تواصل معنا

**Footer (`footer`):** قصتنا، الأسئلة الشائعة، الشحن والاسترجاع، باقات التوفير، تواصل معنا، البحث.

**شريط الإعلانات:** فيه 3 رسايل: الشحن المجاني، الهدية، وجودة الورق.
