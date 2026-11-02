"""Builders for the Animals, Space and Draw-and-Complete interiors.

Imported by generate_print_pdfs.py; uses its Book/geometry/text helpers.
"""
import drawings as D


def build_extra(g):
    """Return {key: builder} using helpers from the generate_print_pdfs module g."""
    text, hollow, line = g.text, g.hollow, g.line
    INK, GREY = g.INK, g.GREY

    # ------------------------------------------------------------ fact pages
    def fact_page(cw, ch, section, ar, en, drawing, fact):
        out = text(cw / 2, 34, section, 26, "b", GREY, rtl=True)
        out += D.wrap(drawing, (cw - 500) / 2, 60, 500)
        out += text(cw / 2, 640, ar, 64, "h", rtl=True)
        out += text(cw / 2, 695, en, 34, "b", "#777")
        out += (f'<rect x="30" y="730" width="{cw - 60}" height="{70 + 40 * len(fact)}" rx="24" '
                f'fill="#fff" stroke="#BDBDBD" stroke-width="3" stroke-dasharray="10 8"/>')
        out += text(cw / 2, 778, "هل تعرف؟", 30, "h", rtl=True)
        for i, ln in enumerate(fact):
            out += text(cw / 2, 822 + i * 40, ln, 25, "b", "#444", rtl=True)
        return out

    # ------------------------------------------------------------ animals
    JUNGLE, FARM, SEA = "حيوانات الغابة والسفاري", "حيوانات المزرعة", "حيوانات البحر والمية"
    ANIMALS = [
        (JUNGLE, "أَسَد", "Lion", "lion", ["زئير الأسد بيتسمع من بعيد جداً،", "حوالي 8 كيلومتر!"]),
        (JUNGLE, "فِيل", "Elephant", "elephant", ["الفيل أكبر حيوان بيعيش على الأرض،", "وبيستخدم خرطومه عشان يشرب."]),
        (JUNGLE, "زَرَافَة", "Giraffe", "giraffe", ["الزرافة أطول حيوان في العالم!"]),
        (JUNGLE, "حِمَار وَحْشِيّ", "Zebra", "zebra", ["مفيش حمارين وحشيين ليهم", "نفس الخطوط بالظبط."]),
        (JUNGLE, "ثَعْلَب", "Fox", "fox", ["الثعلب سمعه قوي جداً،", "وبيسمع صوت الفار تحت الأرض."]),
        (JUNGLE, "دُبّ", "Bear", "bear", ["بعض الدببة بتنام طول الشتا", "في كهف دافي."]),
        (JUNGLE, "جَمَل", "Camel", "camel", ["الجمل بيقدر يستحمل العطش", "أيام كتير في الصحرا."]),
        (JUNGLE, "بُومَة", "Owl", "owl", ["البومة بتقدر تلف راسها", "لورا تقريباً!"]),
        (FARM, "بَقَرَة", "Cow", "cow", ["البقرة بتدينا اللبن اللي بنعمل منه", "الجبنة والزبادي."]),
        (FARM, "خَرُوف", "Sheep", "sheep", ["صوف الخروف بيتعمل منه هدوم", "بتدفينا في الشتا."]),
        (FARM, "دَجَاجَة", "Hen", "hen", ["الفرخة ممكن تبيض بيضة", "كل يوم تقريباً."]),
        (FARM, "بَطَّة", "Duck", "duck", ["ريش البطة مبيتبلّش بسهولة،", "عشان كده بتعوم براحتها."]),
        (FARM, "خِنْزِير", "Pig", "pig", ["الخنزير حيوان ذكي جداً، وبيتمرّغ", "في الطين عشان يبرد."]),
        (FARM, "أَرْنَب", "Rabbit", "rabbit", ["الأرنب بيقدر يشوف اللي وراه", "من غير ما يلف راسه!"]),
        (FARM, "قِطَّة", "Cat", "cat", ["القطة بتنام حوالي نص اليوم!"]),
        (FARM, "عُصْفُور", "Bird", "bird", ["العصافير بتبني أعشاشها", "من القش والفروع الصغيرة."]),
        (SEA, "حُوت", "Whale", "whale", ["الحوت الأزرق أكبر حيوان", "عاش على كوكب الأرض!"]),
        (SEA, "سَمَكَة", "Fish", "fish", ["السمكة بتتنفس تحت المية", "بالخياشيم."]),
        (SEA, "أُخْطُبُوط", "Octopus", "octopus", ["الأخطبوط عنده 8 أذرع و3 قلوب!"]),
        (SEA, "سَلْطَعُون", "Crab", "crab", ["السلطعون بيمشي على جنب!"]),
        (SEA, "سُلَحْفَاة", "Turtle", "turtle", ["السلحفاة بتشيل بيتها على ضهرها", "في كل حتة."]),
        (SEA, "قِنْدِيل البَحْر", "Jellyfish", "jellyfish", ["قنديل البحر مالوش مخ ولا عضم!"]),
        (SEA, "ضِفْدَع", "Frog", "frog", ["الضفدع بيبدأ حياته شرغوف صغير", "بيعوم في المية."]),
        (SEA, "بِطْرِيق", "Penguin", "penguin", ["البطريق طائر.. بس مبيطيرش،", "وبيعوم بسرعة كبيرة!"]),
    ]

    def build_animals(binding):
        b = g.Book("animals-world-interior", "كتاب عالم الحيوانات", g.LETTER, binding or "symmetric", "ar")
        cw, ch = b.g.content_w, b.g.content_h
        b.add_with_back(g.ownership_page(b, cw, ch, "كتاب عالم الحيوانات", True))
        for section, ar, en, drawing, fact in ANIMALS:
            b.add_with_back(fact_page(cw, ch, section, ar, en, drawing, fact))
        b.add_with_back(g.certificate_page(cw, ch, "كتاب عالم الحيوانات", True))
        return b

    # ------------------------------------------------------------ space
    PLANETS, ADV = "الكواكب والمجموعة الشمسية", "مغامرات الفضاء"
    SPACE = [
        (PLANETS, "الشَّمْس", "The Sun", "sun", ["الشمس نجم كبير جداً،", "وبتدينا النور والدفا."]),
        (PLANETS, "عُطَارِد", "Mercury", "mercury", ["عطارد أقرب كوكب للشمس،", "وأصغر كواكب المجموعة الشمسية."]),
        (PLANETS, "الزُّهَرَة", "Venus", "venus", ["الزهرة أسخن كوكب", "في المجموعة الشمسية."]),
        (PLANETS, "الأَرْض", "Earth", "earth", ["الأرض بيتنا، والكوكب الوحيد", "اللي نعرف إن فيه حياة."]),
        (PLANETS, "القَمَر", "The Moon", "moon", ["القمر مالوش نور..", "هو بيعكس نور الشمس."]),
        (PLANETS, "المِرِّيخ", "Mars", "mars", ["المريخ لونه أحمر بسبب الصدأ", "اللي في ترابه."]),
        (PLANETS, "المُشْتَرِي", "Jupiter", "jupiter", ["المشتري أكبر كوكب، والبقعة اللي عليه", "عاصفة كبيرة جداً."]),
        (PLANETS, "زُحَل", "Saturn", "saturn", ["حلقات زحل معمولة من تلج وصخور."]),
        (PLANETS, "أُورَانُوس", "Uranus", "uranus", ["أورانوس بيلف وهو نايم على جنبه!"]),
        (PLANETS, "نِبْتُون", "Neptune", "neptune", ["نبتون أبعد كوكب عن الشمس،", "ورياحه سريعة جداً."]),
        (ADV, "صَارُوخ", "Rocket", "rocket", ["الصاروخ لازم يطير بسرعة كبيرة جداً", "عشان يخرج من الأرض."]),
        (ADV, "رَائِد فَضَاء", "Astronaut", "astronaut", ["رائد الفضاء بيلبس بدلة خاصة", "عشان يتنفس ويتحمى في الفضاء."]),
        (ADV, "مَحَطَّة الفَضَاء", "Space Station", "station", ["محطة الفضاء الدولية بتلف حوالين", "الأرض كل ساعة ونص تقريباً."]),
        (ADV, "قَمَر صِنَاعِيّ", "Satellite", "satellite", ["الأقمار الصناعية بتساعدنا نتفرج", "على التلفزيون ونعرف الطقس."]),
        (ADV, "تِلِسْكُوب", "Telescope", "telescope", ["بالتلسكوب نقدر نشوف نجوم", "وكواكب بعيدة جداً."]),
        (ADV, "مُذَنَّب", "Comet", "comet", ["المذنّب كتلة من التلج والتراب،", "وليه ديل منوّر."]),
        (ADV, "كُوَيْكِب", "Asteroid", "asteroid", ["الكويكبات صخور بتلف حوالين الشمس،", "وأغلبها بين المريخ والمشتري."]),
        (ADV, "الدُّبّ الأَكْبَر", "Big Dipper", "bigdipper", ["الدب الأكبر 7 نجوم لامعة", "شكلها زي المغرفة."]),
        (ADV, "مَرْكَبَة جَوَّالَة", "Mars Rover", "rover", ["المركبات الجوالة بتمشي على المريخ", "وبتصوّر وتدرس ترابه."]),
        (ADV, "نَجْمَة", "Star", "star", ["كل نجمة في السما شمس..", "بس بعيدة جداً عننا."]),
        (ADV, "كَائِن فَضَائِيّ", "Alien", "alien", ["لسه محدش لقى كائنات فضائية..", "بس إحنا ممكن نتخيلها ونرسمها!"]),
        (ADV, "طَبَق طَائِر", "UFO", "ufo", ["الطبق الطاير موجود في الحكايات", "والأفلام.. وكمان في كراستك!"]),
    ]

    def build_space(binding):
        b = g.Book("space-adventures-interior", "كتاب الفضاء والمغامرات", g.LETTER, binding or "symmetric", "ar")
        cw, ch = b.g.content_w, b.g.content_h
        b.add_with_back(g.ownership_page(b, cw, ch, "كتاب الفضاء والمغامرات", True))
        for section, ar, en, drawing, fact in SPACE:
            b.add_with_back(fact_page(cw, ch, section, ar, en, drawing, fact))
        b.add_with_back(g.certificate_page(cw, ch, "كتاب الفضاء والمغامرات", True))
        return b

    # ------------------------------------------------------------ draw & complete
    SYMMETRY = ["butterfly", "heart", "star", "bear", "cat", "owl", "ladybug", "crab",
                "tree", "umbrella", "icecream", "flower", "kite", "jellyfish", "penguin", "lion"]
    TRACE = [("whale", "حُوت"), ("giraffe", "زَرَافَة"), ("airplane", "طَائِرَة"), ("house", "بَيْت")]
    FREE = [("box_open", "إيه اللي جوه الصندوق؟ ارسمه!"), ("fishbowl", "ارسم سمك ملوّن في الحوض"),
            ("cake", "زيّن تورتة عيد ميلادك"), ("helmet", "ارسم وشّك وإنت رائد فضاء!"),
            (None, "ارسم بيتك وجنينتك"), (None, "ارسم وحش لطيف.. وسمّيه!")]
    BOX = 520

    def grid(x, y, size, step=40):
        out = ""
        k = 0
        while k <= size + 0.1:
            out += line(x + k, y, x + k, y + size, "#E6E6E6", 1.5) + line(x, y + k, x + size, y + k, "#E6E6E6", 1.5)
            k += step
        return out

    def symmetry_page(cw, ch, name, idx):
        x0, y0 = (cw - BOX) / 2, 150
        cx = x0 + BOX / 2
        cid = f"half{idx}"
        out = hollow(cw / 2, 70, "أكمل النص التاني", 54, rtl=True, sw=5)
        out += text(cw / 2, 120, "ارسم النص الناقص بنفس الشكل.. والمربعات هتساعدك", 24, "b", "#555", rtl=True)
        out += grid(x0, y0, BOX)
        out += (f'<defs><clipPath id="{cid}L"><rect x="{x0 - 10}" y="{y0 - 10}" width="{BOX / 2 + 10}" height="{BOX + 20}"/></clipPath>'
                f'<clipPath id="{cid}R"><rect x="{cx}" y="{y0 - 10}" width="{BOX / 2 + 10}" height="{BOX + 20}"/></clipPath></defs>')
        out += f'<g clip-path="url(#{cid}L)">{D.wrap(name, x0, y0, BOX)}</g>'
        out += f'<g clip-path="url(#{cid}R)" class="ghost">{D.wrap(name, x0, y0, BOX)}</g>'
        out += line(cx, y0 - 20, cx, y0 + BOX + 20, "#888", 3, "10 8")
        out += text(cw / 2, y0 + BOX + 90, "بعد ما تكمّلها.. لوّنها بألوانك المفضلة!", 28, "h", rtl=True)
        return out

    def trace_page(cw, ch, name, word):
        out = hollow(cw / 2, 70, "اتبع النقط وكمّل الرسمة", 54, rtl=True, sw=5)
        out += text(cw / 2, 120, "امشي بالقلم على النقط.. وبعدين لوّن", 24, "b", "#555", rtl=True)
        out += f'<g class="ghost">{D.wrap(name, (cw - BOX) / 2, 150, BOX)}</g>'
        out += text(cw / 2, 760, word, 60, "h", rtl=True)
        return out

    def free_page(cw, ch, name, prompt):
        out = hollow(cw / 2, 70, "ارسم بخيالك", 54, rtl=True, sw=5)
        out += text(cw / 2, 125, prompt, 30, "h", rtl=True)
        if name:
            out += D.wrap(name, (cw - 560) / 2, 160, 560)
        else:
            out += f'<rect x="30" y="160" width="{cw - 60}" height="620" rx="30" fill="#fff" stroke="{INK}" stroke-width="5"/>'
        out += text(cw - 40, 850, "اسم رسمتي:", 26, "b", anchor="start", rtl=True) + g.dotline(40, cw - 200, 850)
        return out

    def build_creative(binding):
        b = g.Book("draw-and-complete-interior", "كتاب ارسم وأكمل", g.LETTER, binding or "symmetric", "ar")
        cw, ch = b.g.content_w, b.g.content_h
        b.add_with_back(g.ownership_page(b, cw, ch, "كتاب ارسم وأكمل", True))
        for i, name in enumerate(SYMMETRY):
            b.add_with_back(symmetry_page(cw, ch, name, i))
        for name, word in TRACE:
            b.add_with_back(trace_page(cw, ch, name, word))
        for name, prompt in FREE:
            b.add_with_back(free_page(cw, ch, name, prompt))
        b.add_with_back(g.certificate_page(cw, ch, "كتاب ارسم وأكمل", True))
        return b

    return {"animals": build_animals, "space": build_space, "creative": build_creative}
