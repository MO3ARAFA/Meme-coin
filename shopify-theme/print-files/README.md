# ملفات الطباعة: حروفي (Lulu Direct / Amazon KDP)

ملفات Vector PDF جاهزة للطباعة: 7 كتب، وكل كتاب ليه ملف داخلي وملف غلاف ملفوف (Wraparound). مولّدة بالكامل بالكود من `tools/print_engine/`.

| الكتاب | الملف الداخلي | ملف الغلاف | الصفحات | المقاس (بوصة) | التجليد | الكعب | الغلاف بالكامل |
|---|---|---|---|---|---|---|---|
| الحروف العربية | `arabic-alphabet-interior.pdf` | `covers/arabic-alphabet-cover.pdf` | 60 | 8.5 × 11 | Perfect Bound | 0.1951" | 17.4451 × 11.2500" |
| ABC Fun | `english-alphabet-interior.pdf` | `covers/english-alphabet-cover.pdf` | 56 | 8.5 × 11 | Perfect Bound | 0.1861" | 17.4361 × 11.2500" |
| الأرقام والحساب | `numbers-math-interior.pdf` | `covers/numbers-math-cover.pdf` | 56 | 8.5 × 11 | Perfect Bound | 0.1861" | 17.4361 × 11.2500" |
| عالم الحيوانات | `animals-world-interior.pdf` | `covers/animals-world-cover.pdf` | 52 | 8.5 × 11 | Perfect Bound | 0.1771" | 17.4271 × 11.2500" |
| الفضاء والمغامرات | `space-adventures-interior.pdf` | `covers/space-adventures-cover.pdf` | 48 | 8.5 × 11 | Perfect Bound | 0.1681" | 17.4181 × 11.2500" |
| ارسم وأكمل | `draw-and-complete-interior.pdf` | `covers/draw-and-complete-cover.pdf` | 56 | 8.5 × 11 | Perfect Bound | 0.1861" | 17.4361 × 11.2500" |
| كتيب الجيب السحري | `magic-pocket-gift-interior.pdf` | `covers/magic-pocket-gift-cover.pdf` | 12 | 4.25 × 6.875 | Saddle Stitch | 0.0000" | 8.7500 × 7.1250" |

## مواصفات الملفات الداخلية
- **المقاس:** حد القص (Trim) زائد 0.125 بوصة Bleed من كل ناحية. الـ MediaBox مضبوط بالظبط، وفيه `TrimBox` و`BleedBox`.
- **هوامش متماثلة:** 0.625 بوصة يمين وشمال في كتب الـ Letter، و0.4375 بوصة في كتيب الجيب، و0.5 بوصة فوق وتحت. عشان كده **نفس الملف بيشتغل لو التجليد يمين أو شمال**، ومش محتاج نسخة تانية لـ Lulu.
- **قاعدة الوجه الواحد:** كل صفحة رسم ظهرها فاضي، وعليه إطار باهت وشعار "حروفي" باهت وجملة "هذه الصفحة تُركت فارغة لحماية رسمتك التالية من تلطخ الألوان".
- **الخطوط:** Baloo Bhaijaan 2 وCairo مدمجين (رخصة OFL، والرخصة جوه `tools/print_engine/fonts/`).
- **عدد الصفحات:** زوجي في كل الملفات.

## مواصفات الأغلفة (Lulu Wraparound)
- **الترتيب من الشمال لليمين:** Bleed | الخلفي | الكعب | الأمامي | Bleed.
- **عرض الكعب:** `عدد الصفحات ÷ 444 + 0.06` بوصة لكتب Perfect Bound، وصفر لكتيب الـ Saddle Stitch.
- **عرض الغلاف:** `2 × عرض القص + الكعب + 0.25`، و**الارتفاع:** `ارتفاع القص + 0.25`.
- **الكعب من غير نص:** كل الكعوب أقل من 0.25 بوصة، فالسكريبت مابيكتبش عليها. لو الكتب كبرت، النص بيتضاف لوحده.
- **الغلاف الخلفي:**
  - نبذة للأهل.
  - 3 صفحات مصغرة Vector من جوه الكتاب.
  - شعار حروفي.
  - مساحة بيضاء للباركود تحت على اليمين: 2 × 1.2 بوصة (في كتيب الجيب 1.6 × 1 بوصة).
- **فحص الأمان:** السكريبت بيرندر كل غلاف مرة تانية من غير خلفيات، وبيتأكد إن كل النصوص والرسومات على الأقل 0.375 بوصة جوه حد القص ومن خطوط طي الكعب، يعني نص بوصة من حافة الـ Bleed.

## ⚠️ قبل الرفع على Lulu
1. **راجع عرض الكعب:** Lulu بيحسب الكعب حسب نوع الورق. افتح مشروعك على Lulu وقارن مقاس الغلاف اللي بيطلبه بالجدول فوق. لو مختلف، أعد التوليد بالأرقام بتاعته:
   ```bash
   python3 tools/print_engine/generate_print_covers.py --pages-per-inch 444 --spine-extra 0.06
   ```
2. **الأغلفة Paperback بس:** الـ Hardcover (Casewrap) في Lulu ليه مقاسات لف مختلفة. الملفات دي للـ Paperback.
3. **الكتب العربية:** هتتجلّد من الشمال في Lulu. الصفحات الداخلية مش هتتأثر بفضل الهوامش المتماثلة، وكل صفحة تلوين مستقلة بذاتها.

## إعادة التوليد والفحص
```bash
python3 tools/print_engine/generate_print_pdfs.py
```
```bash
python3 tools/print_engine/generate_print_covers.py
```
```bash
python3 tools/print_engine/check_print_pdfs.py
```
المتطلبات: Python 3.9+ مع Pillow وpypdf، وNode 18+ مع Playwright (Chromium)، وpoppler-utils.


---

## أغلفة الـ Hardcover (Lulu Casewrap)

```bash
python3 tools/print_engine/generate_print_covers.py --hardcover
```

| الكتاب | ملف الغلاف | الصفحات | الكعب | الغلاف بالكامل |
|---|---|---|---|---|
| الحروف العربية | `covers-hardcover/arabic-alphabet-hardcover.pdf` | 60 | 0.25" | 18.75 × 12.50" |
| ABC Fun | `covers-hardcover/english-alphabet-hardcover.pdf` | 56 | 0.25" | 18.75 × 12.50" |
| الأرقام والحساب | `covers-hardcover/numbers-math-hardcover.pdf` | 56 | 0.25" | 18.75 × 12.50" |
| عالم الحيوانات | `covers-hardcover/animals-world-hardcover.pdf` | 52 | 0.25" | 18.75 × 12.50" |
| الفضاء والمغامرات | `covers-hardcover/space-adventures-hardcover.pdf` | 48 | 0.25" | 18.75 × 12.50" |
| ارسم وأكمل | `covers-hardcover/draw-and-complete-hardcover.pdf` | 56 | 0.25" | 18.75 × 12.50" |

- **هامش اللف (Wrap):** 0.75 بوصة من كل ناحية. يعني العرض = 2 × عرض القص + الكعب + 1.5، والارتفاع = ارتفاع القص + 1.5.
- **عرض الكعب:** ثابت 0.25 بوصة للكتب من 24 لـ 84 صفحة. لو الكتاب بره المدى ده (زي باقة الحروف، 116 صفحة)، السكريبت بيتخطاه برسالة واضحة، إلا لو حددت العرض بنفسك:
  ```bash
  python3 tools/print_engine/generate_print_covers.py letters_bundle --hardcover --hardcover-spine 0.5
  ```
  استخدم العرض اللي Lulu بيعرضه لكتابك مكان 0.5.
- **الأمان:** المحتوى بيفضل على بعد 0.375 بوصة على الأقل من حد القص، ونص بوصة من خطوط طي الكعب (منطقة المفصّلة). والفحص بيتعمل أوتوماتيك.
- **كتيب الجيب:** مالوش نسخة Hardcover، لأنه Saddle Stitch.
- ⚠️ **قبل الرفع:** قارن المقاس بقالب الغلاف (Cover Template) اللي Lulu بيعرضه لمشروع الـ Hardcover. لو مختلف، ظبط `--hardcover-spine` والثوابت `HC_WRAP` و`HC_HINGE` في السكريبت.

---

## الباقات (Bundles) مع Lulu Direct

Lulu Direct بيربط كل Variant في Shopify بكتاب واحد. عشان كده الباقتين متحلّين بطريقتين مختلفتين:

### 1. باقة الحروف: كتاب واحد مدموج ✅
```bash
python3 tools/print_engine/merge_bundles.py
```
```bash
python3 tools/print_engine/generate_print_covers.py letters_bundle
```
- **الملف الداخلي:** `letters-bundle-interior.pdf` (116 صفحة)، وهو الكتاب العربي (60 صفحة) وبعده الإنجليزي (56 صفحة) في مجلد واحد. كل جزء محتفظ بصفحة الملكية والظهر الفاضي والشهادة بتوعه.
- **الغلاف:** `covers/letters-bundle-cover.pdf`، بكعب 0.3213 بوصة وعرض 17.5713 × 11.25 بوصة، والاسم مكتوب على الكعب.
- **في Lulu:** اعمل مشروع واحد بالملفين دول، واربطه بالـ Variant **Paperback** في منتج "باقة الحروف".
- **الـ Hardcover للباقة:** محتاج عرض كعب من Lulu (شوف الأمر اللي فوق). لحد ما يتعمل، ممكن توقف الـ Variant ده.
- **ليه أوفر؟** طباعة كتاب واحد وشحنة واحدة أرخص من كتابين منفصلين.

### 2. باقة العباقرة: تطبيق Shopify Bundles (بيفككها لـ 6 كتب)
6 كتب في مجلد واحد هيبقى أكتر من 300 صفحة، وده تقيل على طفل. فالأفضل كل كتاب يتطبع لوحده. تطبيق **Shopify Bundles** المجاني (من Shopify نفسها) بيعمل منتج باقة، ولما العميل يدفع، الطلب بيوصل لتطبيقات التنفيذ زي Lulu Direct كـ 6 كتب منفصلة (Components)، وكل كتاب مربوط بمشروعه في Lulu.

**الخطوات:**
1. ثبّت **Shopify Bundles** من Shopify App Store.
2. **قبل ما تبدأ:** اربط في Lulu Direct الـ Variants الـ 12 للكتب الستة (6 Paperback و6 Hardcover)، كل Variant بالملف الداخلي وملف الغلاف بتوعه.
3. من التطبيق اختار **Create bundle**، ونوعه **Fixed bundle**:
   - **الاسم:** باقة العباقرة الشاملة.
   - **المنتجات:** الكتب الستة، بكمية 1 من كل كتاب.
   - **الخيارات:** فعّل خيار الغلاف بقيمتين، بحيث Paperback في الباقة = Paperback في كل كتاب، وHardcover = Hardcover.
   - **السعر:** 1799 ج.م للـ Paperback، و2699 للـ Hardcover. والسعر قبل الخصم 2994 و4494.
4. انسخ للمنتج الجديد الوصف والصور والـ SEO، والـ Tags: `Hroofy_Book`، `Bundle`، `Best_Seller`، `Letters`، `Numbers`، `Drawing`، `Age_3-4`، `Age_5-6`، `Age_7-Plus`. الـ Tags دي بتدخّله أوتوماتيك في الـ Collections، وبتخليه يتحسب في شرط الهدية المجانية فوق 1500 ج.م.
5. **الـ Handle:** غيّر Handle المنتج القديم `genius-complete-bundle` لأي اسم تاني، وادّي الـ Handle ده للمنتج الجديد، عشان الروابط والقوايم تفضل شغالة. وبعدها اعمل **Archive** للمنتج القديم.
6. **اختبار:** اعمل طلب تجريبي، واتأكد إن Lulu Direct استقبل 6 كتب.

**ملاحظات:**
- **ممنوع على المنتجات الداخلة في الباقة:** ماينفعش يكون عليها Selling Plans (اشتراكات)، ولا تكون هي نفسها باقة.
- **قبل التفعيل:** راجع شروط التطبيق الحالية في صفحته على App Store، لأن Shopify بيحدّثها.
- **باقة الحروف:** ماتستخدمش معاها Shopify Bundles، لأنها اتعملت كتاب واحد مدموج.
