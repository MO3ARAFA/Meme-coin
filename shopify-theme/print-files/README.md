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
