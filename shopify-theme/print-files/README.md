# ملفات الطباعة الداخلية: حروفي (Interior Print Files)

ملفات PDF داخلية جاهزة لـ Lulu Direct وAmazon KDP. ولّدها `tools/print_engine/generate_print_pdfs.py`.

| الملف | الصفحات | المقاس النهائي (Trim) | مقاس الملف (مع Bleed) | الكعب |
|---|---|---|---|---|
| `arabic-alphabet-interior.pdf` | 60 | 8.5 × 11 in | 8.75 × 11.25 in | يمين (RTL) |
| `english-alphabet-interior.pdf` | 56 | 8.5 × 11 in | 8.75 × 11.25 in | شمال (LTR) |
| `numbers-math-interior.pdf` | 56 | 8.5 × 11 in | 8.75 × 11.25 in | يمين (RTL) |
| `magic-pocket-gift-interior.pdf` | 12 | 4.25 × 6.875 in (Pocket Book) | 4.5 × 7.125 in | يمين (RTL) |

## المواصفات المطبّقة
- **Vector PDF:** كل الرسومات والنصوص Vector، والخطوط مدمجة (Baloo Bhaijaan 2 وCairo، رخصة OFL).
- **Bleed:** 0.125 بوصة من كل ناحية.
- **هامش الأمان:** نص بوصة جوه حد القص من كل ناحية، وربع بوصة زيادة ناحية الكعب. الكعب بيتبدّل بين الصفحات الفردية والزوجية.
- **قاعدة الوجه الواحد:** كل صفحة رسم ظهرها فاضي، وعليه إطار باهت وشعار "حروفي" باهت وجملة "هذه الصفحة تُركت فارغة لحماية رسمتك التالية من تلطخ الألوان".
- **عدد الصفحات:** زوجي في كل الملفات.

## خطوات الرفع على Lulu
1. Create → Print Book، واختار المقاس: **US Letter 8.5 × 11** للكتب، و**Pocket Book 4.25 × 6.875** للكتيب.
2. Interior Color: **Standard Black & White**. الورق: **White**. وزن الورق اللي هتختاره هو اللي المفروض يتكتب في وصف المنتج على المتجر.
3. Binding: **Paperback Perfect Bound** أو **Hardcover Casewrap**. الكتيب الصغير: **Saddle Stitch**، واتأكد إن 12 صفحة فوق الحد الأدنى بتاع Lulu.
4. ارفع ملف الـ Interior PDF المناسب.
5. **الغلاف:** Lulu محتاج ملف غلاف منفصل (أمامي + كعب + خلفي)، وعرض الكعب بيتحسب من عدد الصفحات ونوع الورق. نزّل قالب الغلاف من صفحة المشروع على Lulu، واستخدم تصميمات الأغلفة اللي في `product-images/`.
6. اربط كل Variant في Shopify (Paperback / Hardcover) بالمشروع المناسب في تطبيق Lulu Direct.

## ⚠️ اتجاه التجليد للكتب العربية
الكتب العربية متولدة على إن الكعب **يمين** (الكتاب بيتفتح من اليمين). لو Lulu مابيدعمش التجليد من اليمين في المنتج اللي اخترته، اعمل نسخة كعبها شمال:

```bash
python3 tools/print_engine/generate_print_pdfs.py arabic numbers gift --binding left
```

## إعادة التوليد والفحص
```bash
python3 tools/print_engine/generate_print_pdfs.py
```
```bash
python3 tools/print_engine/check_print_pdfs.py
```
سكريبت الفحص بيتأكد من المقاس، وإن عدد الصفحات زوجي، وإن الخطوط مدمجة، وإن مفيش حبر بره منطقة الأمان في أي صفحة. وبيحفظ معاينة لأول وآخر صفحات كل ملف في `_preview/`.

المتطلبات: Python 3.9+، وNode 18+ مع Playwright (Chromium)، وpoppler-utils، وPillow.

## ما لم يُولّد بعد
ملفات Interior لكتب **عالم الحيوانات** و**الفضاء والمغامرات** و**ارسم وأكمل** لسه ماتعملتش. مكتبة الرسومات في `tools/print_engine/drawings.py` جاهزة تتوسّع ليهم.
