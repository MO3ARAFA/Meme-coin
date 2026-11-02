# Amazon KDP: ملفات الطباعة والتسعير والبيانات الوصفية

مولَّدة بـ `tools/print_engine` (`--target kdp`) وتم فحصها بـ `tools/print_engine/check_kdp_files.py` (كل الفحوص OK).

## 1) الملفات

| الملف | المقاس | الصفحات |
|---|---|---|
| `*-interior.pdf` (6 كتب) | 8.5×11 in بالضبط، **بدون Bleed** (مفيش رسم بيلمس الحافة) | 48 - 60 |
| `letters-bundle-interior.pdf` | 8.5×11 in | 116 |
| `magic-pocket-gift-interior.pdf` | 6×9 in | 24 (ملكية + 10 رسمات + شهادة، وكل ورقة ليها ظهر محمي) |
| `covers/*-cover.pdf` | عرض = 2×العرض + الكعب + 0.25، ارتفاع = 11.25 in | حسب الكتاب |
| `covers-hardcover/letters-bundle-hardcover.pdf` | 18.982 × 12.182 in | 116 |

- **الكعب (Paperback ورق أبيض)** = عدد الصفحات × 0.002252 in: 60 ص = 0.1351، 56 = 0.1261، 52 = 0.1171، 48 = 0.1081، 24 = 0.0540، 116 = 0.2612.
- **نص الكعب** بيتكتب **بس** في باقة الحروف (116 ص ≥ 79). الكتب المفردة بدون نص على الكعب.
- **الباركود:** مربع أبيض 2.0×1.2 in أسفل يمين الغلاف الخلفي، على بعد 0.375 in من حافة القص ومن طية الكعب (الحد الأدنى 0.25).
- **هوامش الداخل:** 0.625 in يمين ويسار (الحد الأدنى للجتر في KDP لـ 24-150 ص هو 0.375) و0.5 in فوق وتحت (الحد الأدنى 0.25)، متماثلة فبتصلح لأي اتجاه تجليد.
- **Hardcover (باقة الحروف فقط، 116 ص ≥ 75):** Case Laminate بالقيم اللي حددتها: wrap 0.591، كعب 0.45، منطقة الكعب+المفصلات 0.8 (العرض = 2×8.5 + 0.8 + 2×0.591). **الأرقام دي لم أقدر أتحقق منها من مصدر رسمي**، فاستخدم Cover Calculator بتاع KDP قبل الرفع (الباراميترات في `generate_print_covers.py`: `KDP_HC_WRAP`, `KDP_HC_SPINE`, `KDP_HC_ZONE`).
- اتجاه القراءة: الكتب العربية مبنية بتجليد متماثل؛ KDP بيجلّد الكتاب على اليسار، فتأكد من الـ Preview في KDP إن ترتيب الصفحات مناسب.

إعادة التوليد:
```bash
python3 tools/print_engine/generate_print_pdfs.py --target kdp
python3 tools/print_engine/merge_bundles.py --target kdp
python3 tools/print_engine/generate_print_covers.py --target kdp
python3 tools/print_engine/generate_print_covers.py --target kdp --hardcover
python3 tools/print_engine/check_kdp_files.py
```

## 2) الأسعار والأرباح

**تكاليف الطباعة المستخدمة هي أرقامك (Author copy $2.84 / $3.62)، ولم أتحقق منها.** تكلفة HC = $8.55 مستنتجة من صافي $6.44 اللي ذكرته (24.99×60% − 6.44). تكلفة كتيب الجيب 6×9 / 24 صفحة غير متاحة: احسبها من KDP Print Cost Calculator.

### أ) Amazon.com (بالدولار، صافي = 60% × السعر − تكلفة الطباعة)

| المنتج | السعر | التكلفة | صافي الربح | الهامش |
|---|---|---|---|---|
| كتاب مفرد (Paperback) | $9.99 | $2.84 | $3.15 | 31.6% |
| باقة الحروف PB 116 ص | $16.99 | $3.62 | $6.57 | 38.7% |
| باقة الحروف HC 116 ص | $24.99 | $8.55 * | $6.44 | 25.8% |

\* مستنتجة. الكتاب المفرد بسعر $9.99 هامشه ~31.6% (مقبول لقناة Amazon لأن الشحن والـ Prime على Amazon).

### ب) الخليج (Amazon.ae / Amazon.sa)

KDP **لا يدعم بيع الورقي على Amazon.ae ولا Amazon.sa** (حسب علمي، تأكد من قائمة Marketplaces في KDP). يعني الكتاب مش هيظهر هناك. الخيارات: (1) العميل الخليجي يشتري من Amazon.com بشحن دولي بسعر الدولار نفسه وبنفس الـ Royalty في الجدول (أ)، والشحن على العميل؛ (2) يشتري من Shopify بالجدول (ج).

### ج) Shopify (دولي بالدولار) - تكلفة = طباعة + شحن ~$4.5 للطلب الواحد (~$8 لباقة 6 كتب، تقدير)، رسوم 2.9% + $0.30

| المنتج | السعر | التكلفة | صافي الربح | الهامش |
|---|---|---|---|---|
| كتاب مفرد PB | $12.99 | $7.34 | $4.97 | 38.3% |
| باقة الحروف PB | $21.99 | $8.12 | $12.93 | 58.8% |
| باقة الحروف HC | $29.99 | $13.05 | $15.77 | 52.6% |
| باقة العباقرة (6 كتب PB) | $59.99 | $25.04 | $32.91 | 54.9% |

- المفرد بـ $12.99 هامشه 38.3% (أقل من 40%)؛ $13.99 يديه 42.5%. لو عايز ≥40% اختر $13.99.
- شحن مجاني فوق $35 وهدية فوق $55 (من خطتك): الشحن المجاني بياكل جزء من الهامش في الطلبات الصغيرة.

### د) Shopify مصر (EGP) - افتراض سعر صرف 1$ = 50 ج.م (**حدّثه**)

شحن العميل 118 ج.م للطلبات أقل من 750 ج.م، ومجاني فوقها.

| المنتج | السعر | التكلفة | صافي الربح | الهامش |
|---|---|---|---|---|
| كتاب مفرد PB | 399 ج.م (~$7.98) | $7.34 | $2.40 | 23.2% |
| باقة الحروف PB | 699 ج.م (~$13.98) | $8.12 | $7.45 | 45.6% |
| باقة الحروف HC | 999 ج.م (~$19.98) | $13.05 | $6.05 | 30.3% |
| باقة العباقرة PB | 1999 ج.م (~$39.98) | $25.04 | $13.48 | 33.7% |

- المفرد بـ 399 ج.م هامشه ~23% فقط لو الكتاب بيتطبع بالولايات المتحدة ويتشحن لمصر؛ ده مش مربح بشكل مريح. بيتحسن لو الشراء بباقة (الشحن المجاني بـ 750).
- **تنبيه تشغيلي مهم:** KDP **لا يتكامل مع Shopify**. طلبات Shopify لا تتنفذ تلقائياً: لازم تطلب Author Copies يدوياً من KDP وتشحنها بنفسك (أو تستخدم Amazon MCF لو متاح لحسابك، لم أتحقق). Author copies بتتشحن من KDP لعنوانك أنت.

## 3) البيانات الوصفية لـ KDP (جاهزة للنسخ)

اللغة: العربية لكل الكتب (ما عدا ABC Fun: اختار Arabic أو English حسب المحتوى الغالب). الفئات مقترحة: تأكد من الأسماء الدقيقة داخل KDP لأنها بتتغير. الكلمات المفتاحية: 7 لكل كتاب (أقل من 50 حرف لكل واحدة).

### الحروف العربية
- **Title:** كتاب تلوين الحروف العربية من أ إلى ي
- **Subtitle:** تلوين وتتبع الحروف الـ28 بالكلمات المشكولة | للأطفال من 3 إلى 6 سنوات | Arabic Alphabet Coloring & Tracing Book
- **Pages:** 60 | **Reading age:** 3-6
- **Description:** 28 صفحة (حرف لكل صفحة) بالرسمة والكلمة المشكولة وأشكال الحرف وسطور تتبع بالنقط، صفحة «هذا الكتاب ملك»، وشهادة إنجاز. ظهر كل رسمة فاضي. طباعة عند الطلب. يناسب الأطفال من 3 إلى 6 سنوات.
- **Categories (3):**
  1. Children's Books > Education & Reference > Language Arts & Reading
  2. Children's Books > Activities, Crafts & Games > Coloring Books
  3. Children's Books > Foreign Languages > Arabic
- **Keywords (7):**
  1. كتاب تلوين حروف عربية
  2. تعليم الحروف العربية للأطفال
  3. كتاب تتبع الحروف
  4. تلوين للأطفال
  5. Arabic alphabet coloring book
  6. Arabic letters tracing kids
  7. Arabic activity book preschool

### ABC Fun
- **Title:** ABC Fun: كتاب تلوين الحروف الإنجليزية
- **Subtitle:** Alphabet A-Z coloring and tracing book for kids ages 3-6 | الحرف الكبير والصغير وسطور كتابة
- **Pages:** 56 | **Reading age:** 3-6
- **Description:** 26 صفحة، لكل حرف: الحرف الكبير والصغير للتلوين، رسمة كلمة (Apple, Ball, Cat…)، وسطرين تتبع. صفحة ملكية وشهادة Hroofy Hero. طباعة عند الطلب. يناسب الأطفال من 3 إلى 6 سنوات.
- **Categories (3):**
  1. Children's Books > Education & Reference > Alphabet
  2. Children's Books > Activities, Crafts & Games > Coloring Books
  3. Children's Books > Education & Reference > Reading & Writing
- **Keywords (7):**
  1. abc coloring book
  2. alphabet tracing book
  3. letters coloring preschool
  4. capital and small letters
  5. kindergarten alphabet workbook
  6. كتاب حروف انجليزي للاطفال
  7. english alphabet arabic kids

### الأرقام والحساب
- **Title:** كتاب الأرقام والحساب: لوّن وعدّ من 1 إلى 20
- **Subtitle:** تلوين وعدّ وجمع وطرح بسيط بالعربي والإنجليزي | للأطفال من 5 إلى 8 سنوات | Numbers & Math Coloring Book
- **Pages:** 56 | **Reading age:** 5-8
- **Description:** 20 صفحة للأرقام 1-20 (الرقم مفرّغ، اسمه، أشكال للعد) + 6 صفحات تمارين: عُدّ واكتب، اجمع، اطرح واشطب، صِل، أكمل الأرقام الناقصة. طباعة عند الطلب. يناسب الأطفال من 5 إلى 8 سنوات.
- **Categories (3):**
  1. Children's Books > Education & Reference > Mathematics > Counting & Numbers
  2. Children's Books > Activities, Crafts & Games > Coloring Books
  3. Children's Books > Education & Reference > Early Learning
- **Keywords (7):**
  1. كتاب ارقام للاطفال
  2. تعليم الجمع والطرح
  3. numbers coloring book
  4. counting workbook kindergarten
  5. math activity book kids
  6. learn numbers 1-20
  7. تلوين الارقام

### عالم الحيوانات
- **Title:** عالم الحيوانات: كتاب تلوين 24 حيواناً
- **Subtitle:** أسماء بالعربي والإنجليزي ومعلومة مبسطة لكل حيوان | للأطفال من 3 إلى 6 سنوات | Animals Coloring Book
- **Pages:** 52 | **Reading age:** 3-6
- **Description:** 24 حيواناً (8 غابة وسفاري، 8 مزرعة، 8 بحر) باسمه مشكولاً بالعربي والإنجليزي ومعلومة «هل تعرف؟»، مع صفحة ملكية وشهادة. طباعة عند الطلب. يناسب الأطفال من 3 إلى 6 سنوات.
- **Categories (3):**
  1. Children's Books > Animals > General
  2. Children's Books > Activities, Crafts & Games > Coloring Books
  3. Children's Books > Education & Reference > Nature
- **Keywords (7):**
  1. animal coloring book kids
  2. كتاب تلوين حيوانات
  3. تلوين الحيوانات للاطفال
  4. farm sea safari animals coloring
  5. animals names arabic english
  6. toddler coloring book animals
  7. كتاب حيوانات للاطفال

### الفضاء والمغامرات
- **Title:** الفضاء والمغامرات: كتاب تلوين رواد الفضاء الصغار
- **Subtitle:** الكواكب والصواريخ ومعلومات علمية مبسطة | للأطفال من 5 إلى 9 سنوات | Space Coloring Book
- **Pages:** 48 | **Reading age:** 5-9
- **Description:** 22 صفحة: الشمس والقمر والكواكب الثمانية، و12 صفحة مغامرات (صاروخ، رائد فضاء، محطة فضاء، تلسكوب…) بأسماء عربي/إنجليزي ومعلومة مبسطة. طباعة عند الطلب. يناسب الأطفال من 5 إلى 9 سنوات.
- **Categories (3):**
  1. Children's Books > Science, Nature & How It Works > Space & Astronomy
  2. Children's Books > Activities, Crafts & Games > Coloring Books
  3. Children's Books > Education & Reference > Science
- **Keywords (7):**
  1. space coloring book kids
  2. solar system coloring
  3. planets rockets astronauts coloring
  4. كتاب تلوين فضاء
  5. تلوين الكواكب للاطفال
  6. astronaut coloring book
  7. كتاب علوم للاطفال

### ارسم وأكمل
- **Title:** ارسم وأكمل: كتاب الرسم الإبداعي للفنانين الصغار
- **Subtitle:** أكمل النصف الثاني من الرسمة وارسم من خيالك | للأطفال من 5 إلى 10 سنوات | Draw & Complete Activity Book
- **Pages:** 56 | **Reading age:** 5-10
- **Description:** 16 صفحة تماثل على شبكة مربعات، 4 صفحات «اتبع النقط»، 6 صفحات رسم حر، صفحة ملكية وشهادة. طباعة عند الطلب. يناسب الأطفال من 5 إلى 10 سنوات.
- **Categories (3):**
  1. Children's Books > Activities, Crafts & Games > Drawing
  2. Children's Books > Activities, Crafts & Games > Coloring Books
  3. Children's Books > Education & Reference > Art
- **Keywords (7):**
  1. draw and complete book kids
  2. symmetry drawing activity
  3. كتاب رسم للاطفال
  4. اتبع النقط وارسم
  5. creative drawing book children
  6. finish the picture activity book
  7. كتاب ابداع

### باقة الحروف
- **Title:** باقة الحروف: عربي + إنجليزي في مجلد واحد
- **Subtitle:** 116 صفحة تلوين وتتبع للحروف العربية A-Z | للأطفال من 3 إلى 6 سنوات | Arabic & English Alphabet Coloring Book
- **Pages:** 116 | **Reading age:** 3-6
- **Description:** جزءان في مجلد واحد (116 صفحة): الحروف العربية (60 صفحة) وABC Fun (56 صفحة) بكل ما فيهما، متوفر Paperback وHardcover. طباعة عند الطلب. يناسب الأطفال من 3 إلى 6 سنوات.
- **Categories (3):**
  1. Children's Books > Education & Reference > Alphabet
  2. Children's Books > Foreign Languages > Arabic
  3. Children's Books > Activities, Crafts & Games > Coloring Books
- **Keywords (7):**
  1. arabic english alphabet book
  2. bilingual alphabet coloring
  3. كتاب حروف عربي وانجليزي
  4. تعليم الحروف للاطفال
  5. alphabet tracing bilingual kids
  6. حروف عربية وانجليزية تلوين
  7. preschool workbook arabic

### كتيب الجيب السحري
- **Title:** كتيب تلوين الجيب السحري
- **Subtitle:** 10 رسمات وشهادة إنجاز | للأطفال من 3 إلى 9 سنوات | Small Coloring Book for Kids
- **Pages:** 24 | **Reading age:** 3-9
- **Description:** 10 رسمات (نجمة، سمكة، صاروخ، فراشة، وردة، قمر، شمس، بيت، قطة، تفاحة) بأسمائها، صفحة ملكية، شهادة، وظهر كل رسمة فاضي. 24 صفحة 6×9 بوصة. طباعة عند الطلب. يناسب الأطفال من 3 إلى 9 سنوات.
- **Categories (3):**
  1. Children's Books > Activities, Crafts & Games > Coloring Books
  2. Children's Books > Activities, Crafts & Games > Drawing
  3. Children's Books > Education & Reference > Early Learning
- **Keywords (7):**
  1. small coloring book kids
  2. travel coloring book
  3. كتيب تلوين اطفال
  4. تلوين للاطفال
  5. 6x9 coloring book
  6. toddler coloring gift
  7. كتاب تلوين صغير

## 4) Shopify وربط Amazon

- زرار «🌍 خارج مصر؟ اطلبه مباشرة من Amazon بشحن Prime سريع» ظاهر تحت زرار الشراء بس لو الميتافيلد `custom.amazon_kdp_url` (نوع URL) فيه قيمة. الملف: `blocks/amazon-kdp-button.liquid`.
- Hardcover اتشال من الكتب الستة ومن باقة العباقرة، وفضل لباقة الحروف بس.
