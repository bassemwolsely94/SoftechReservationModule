"""The item-search golden corpus (unified item search S1, Task 8).

The 52 queries of the 2026-11-16 probe with what the TOP results must look like. One list, two
users:
  · apps/tests/test_search_corpus.py seeds SEED_NAMES (+ SEED_BARCODES, SEED_INGREDIENTS) in an
    empty test DB and asserts every entry (CI, no timing);
  · `manage.py search_probe` runs the same entries on the real catalog through every search path
    and times them (budget: item_search p95 ≤ 40 ms).

An entry: {'q', 'expect' (regex, case-insensitive, that a name in the top `top` rows must match),
'top' (1 or 3), 'tier' (optional: the tier of that row), 'note'}. `real_report_only=True` means
the real catalog can't satisfy it (missing data, not an engine rule) — the probe prints it but it
doesn't fail the run.

A new search bug adds a row here (and the names it needs to SEED_NAMES). Change an expectation
only when it contradicts the spec, and say why in the commit.
"""
import re

CORPUS = [
    {'q': 'panadol', 'expect': r'^PANADOL', 'top': 1, 'tier': 'starts', 'note': 'brand'},
    {'q': 'panadol extra', 'expect': r'PANADOL.*EXTRA', 'top': 1, 'tier': 'starts',
     'note': 'brand + variant; catalog has "EXTRA  24TAB"'},
    {'q': 'cataflam 50mg', 'expect': r'CATAFLAM\s+50\s*MG', 'top': 1, 'note': 'strength glued; name "CATAFLAM  50MG"'},
    {'q': 'cataflam 50 mg', 'expect': r'CATAFLAM\s+50\s*MG', 'top': 1, 'note': 'strength spaced; scientific "50  MG"'},
    {'q': 'voltaren 1%', 'expect': r'VOLTAREN.*1%', 'top': 1, 'tier': 'starts', 'note': 'catalog has triple spaces'},
    {'q': 'VOLTAREN 1% 15 GM', 'expect': r'VOLTAREN.*1%.*15', 'top': 1, 'tier': 'starts',
     'note': 'a copy of the name with single spaces'},
    {'q': 'vol*50', 'expect': r'VOL.*50', 'top': 1, 'note': 'wildcard; starts-with VOL beats DIVOL'},
    {'q': 'augmentin 1g', 'expect': r'AUGMENTIN 1G', 'top': 1, 'tier': 'starts', 'note': 'strength'},
    {'q': 'augmentin 1gm', 'expect': r'AUGMENTIN 1G', 'top': 1, 'note': '1gm vs 1G'},
    {'q': '1g augmentin', 'expect': r'AUGMENTIN 1G', 'top': 1, 'tier': 'any_order', 'note': 'any order'},
    {'q': 'augmentin syrup', 'expect': r'AUGMENTIN.*SYRUP', 'top': 1, 'tier': 'any_order', 'note': 'form'},
    {'q': 'augmentin syp', 'expect': r'AUGMENTIN.*SYRUP', 'top': 1, 'tier': 'synonym',
     'note': 'form abbreviation (Appendix A)'},
    {'q': 'panadool', 'expect': r'^PANADOL', 'top': 1, 'tier': 'approx', 'note': 'typo'},
    {'q': 'voltren', 'expect': r'^VOLTAREN', 'top': 1, 'tier': 'approx', 'note': 'typo'},
    {'q': 'agmentin', 'expect': r'^AUGMENTIN', 'top': 1, 'tier': 'approx', 'note': 'typo'},
    {'q': 'cataflm 50', 'expect': r'CATAFLAM', 'top': 1, 'tier': 'approx', 'note': 'typo + strength'},
    {'q': 'glucophage xr 500', 'expect': r'GLUCOPHAGE XR 500', 'top': 1, 'tier': 'starts', 'note': 'multi-word'},
    {'q': 'concor 5', 'expect': r'^CONCOR 5MG', 'top': 1, 'tier': 'starts',
     'note': 'a small number prefers the exact strength over COR 2.5MG / PLUS 5MG'},
    {'q': 'nexium 40', 'expect': r'NEXIUM 40', 'top': 1, 'tier': 'starts', 'note': 'strength'},
    {'q': 'omega 3', 'expect': r'OMEGA.?3', 'top': 1, 'note': 'word with a number'},
    {'q': 'omega3', 'expect': r'OMEGA.?3', 'top': 1, 'note': 'glued'},
    {'q': 'vit c', 'expect': r'VIT(AMIN)? ?C', 'top': 1, 'note': 'abbreviation'},
    {'q': 'zyrtec drops', 'expect': r'ZYRTEC.*DROPS', 'top': 1, 'tier': 'any_order', 'note': 'form'},
    {'q': 'PaNaDoL', 'expect': r'^PANADOL', 'top': 1, 'tier': 'starts', 'note': 'case'},
    {'q': '3690', 'expect': r'AUGMENTIN 1G', 'top': 1, 'tier': 'code', 'note': 'exact SOFTECH code'},
    {'q': '6221025032348', 'expect': r'^CONCOR 5MG', 'top': 1, 'tier': 'code', 'note': 'barcode (ItemBarcode)'},
    {'q': 'diclofenac', 'expect': r'VOLTAREN|CATAFLAM|DICLO', 'top': 1, 'tier': 'ingredient',
     'real_report_only': True,
     'note': 'active ingredient; the real catalog has no diclofenac ItemIngredientMap yet'},
    {'q': 'paracetamol', 'expect': r'PANADOL|PARACETAMOL|ABIMOL|CETAL', 'top': 1, 'note': 'ingredient word in names'},
    {'q': 'metformin', 'expect': r'GLUCOPHAGE|METFORMIN|CIDOPHAGE', 'top': 1, 'note': 'ingredient word in names'},
    {'q': 'بنادول', 'expect': r'^PANADOL', 'top': 1, 'tier': 'sound', 'note': 'Arabic brand, no Arabic in the name'},
    {'q': 'بانادول', 'expect': r'^PANADOL', 'top': 1, 'tier': 'sound', 'note': 'Arabic alt spelling'},
    {'q': 'فولتارين', 'expect': r'^VOLTAREN', 'top': 1, 'note': 'Arabic brand'},
    # AUGMACILLIN's name also carries «اوجمنتين»: both are `word` hits and the tier is A→Z
    # (spec §5.2), so AUGMACILLIN leads — AUGMENTIN must be in the top 3
    {'q': 'اوجمنتين', 'expect': r'^AUGMENTIN', 'top': 3, 'tier': 'word', 'note': 'Arabic (in the name)'},
    {'q': 'أوجمنتين', 'expect': r'^AUGMENTIN', 'top': 3, 'tier': 'word', 'note': 'Arabic with hamza (folded)'},
    {'q': 'اوجمنتين شراب', 'expect': r'AUGMENTIN.*SYRUP', 'top': 3, 'tier': 'any_order', 'note': 'Arabic brand + form'},
    {'q': 'اوجمنتين 1 جم', 'expect': r'AUGMENTIN 1G', 'top': 1, 'note': 'Arabic brand + strength'},
    {'q': 'كونجستال', 'expect': r'^CONGESTAL', 'top': 1, 'tier': 'word', 'note': 'Arabic (in the name)'},
    {'q': 'كونجستال ٢٠', 'expect': r'^CONGESTAL 20', 'top': 1, 'note': 'Arabic-Indic digits'},
    {'q': 'كتافلام', 'expect': r'^CATAFLAM', 'top': 1, 'tier': 'sound', 'note': 'Arabic by sound'},
    {'q': 'كاتافلام 50', 'expect': r'CATAFLAM\s+50', 'top': 1, 'tier': 'sound', 'note': 'Arabic + number'},
    {'q': 'سيريلاك', 'expect': r'^CERELAC', 'top': 1, 'tier': 'word', 'note': 'Arabic (in the name)'},
    {'q': 'جلوكوفاج', 'expect': r'^GLUCOPHAGE', 'top': 1, 'note': 'Arabic'},
    {'q': 'نيكسيوم', 'expect': r'^NEXIUM', 'top': 1, 'tier': 'sound', 'note': 'Arabic by sound'},
    {'q': 'زيرتك', 'expect': r'^ZYRTEC', 'top': 1, 'tier': 'sound', 'note': 'Arabic by sound'},
    {'q': 'بروفين', 'expect': r'^BRUFEN', 'top': 1, 'note': 'Arabic'},
    {'q': 'انتينال', 'expect': r'^ANTINAL', 'top': 1, 'note': 'Arabic'},
    # D5: no disease expansion in pickers — «سكر» is the product: glucose meters (and a sugar
    # bowl, which STARTS with the word and so leads)
    {'q': 'سكر', 'expect': r'جهاز سكر', 'top': 3, 'note': 'disease word = the product (D5): a device row'},
    {'q': 'augmentin شراب', 'expect': r'AUGMENTIN.*SYRUP', 'top': 1, 'tier': 'any_order', 'note': 'mixed EN + AR'},
    {'q': 'panadol*extra', 'expect': r'PANADOL.*EXTRA', 'top': 1, 'tier': 'starts', 'note': 'wildcard'},
    {'q': '%1%cream', 'expect': r'1%.*CREAM', 'top': 3, 'note': 'leading wildcard'},
    {'q': 'vol ren', 'expect': r'VOLTAREN', 'top': 1, 'tier': 'any_order', 'note': 'space inside a word'},
    {'q': 'pa', 'expect': r'^PA', 'top': 1, 'tier': 'starts', 'note': 'two letters = starts-with only (D7)'},
]

# (softech_id, name, name_scientific) — copied from the real catalog as the probe printed them,
# double spaces and Arabic parts included. The decoys (AUGMACILLIN, CONCOR COR, DIVOL, the sugar
# bowl, the 1 % creams …) are what makes each expectation a real test.
SEED_NAMES = [
    ('88704', 'PANADOL  ACTFAST 20TAB (XX)', 'UnDefined Item'),
    ('80568', 'PANADOL 24TAB (XX)', 'UnDefined Item'),
    ('126874', 'PANADOL ADVANCE 500MG 48TAB LOCAL (4STRIPSX12)', 'PANADOL ADVANCE 500MG 48TAB LOCAL (4STRIPSX12)'),
    ('96878', 'PANADOL EXTRA  24TAB (EGYPT) (2STRIPSX12)', 'PANADOL EXTRA  24TAB (EGYPT) (2STRIPSX12'),
    ('127091', 'PANADOL EXTRA  48TAB (EGYPT) (4STRIPSX12)', 'PANADOL EXTRA  48TAB (EGYPT) (4STRIPSX12'),
    ('123157', 'PANADOL MIGRAINE 24TAB (XX)', 'UnDefined Item'),
    ('81872', 'PARACETAMOL - EL-NASR 500MG  20TAB', 'PARACETAMOL - EL-NASR 500MG  20TAB'),
    ('89489', 'CATAFLAM  50MG 20TAB (2STRIPSX10)', 'CATAFLAM  50  MG    20    TAB'),
    ('1002', 'CATAFLAM  75 MG  5 SUPP', 'CATAFLAM  75 MG  5 SUPP'),
    ('86754', 'CATAFLAM 25MG 20TAB (2STRIPSX10)', 'CATAFLAM 25MG 20TAB (2STRIPSX10)'),
    ('28979', 'VOLTAREN   1% 15  GM  EMULGEL', 'VOLTAREN   1% 15  GM  EMULGEL'),
    ('28984', 'VOLTAREN 1% EMULGEL 50GM MEDIUM SIZE', 'VOLTAREN 1% EMULGEL 50GM MEDIUM SIZE'),
    ('1017', 'VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم', 'VOLTAREN 50MG 20TAB (2STRIPSX10) فولتاري'),
    ('85808', 'VOLTAREN 75MG/3ML 3AMP', 'VOLTAREN 75MG/3ML 3AMP'),
    ('124981', 'VOLUVEN 6% SOL. FOR I.V.INFUSION 500ML SOLUTION XX',
     'VOLUVEN 6% SOL. FOR I.V.INFUSION 500ML SOLUTION XX'),
    ('30885', 'DIVOL KISS CONDITIONER 500ML', 'DIVOL KISS CONDITIONER 500ML'),
    ('3690', 'AUGMENTIN 1G (1000MG) 14 TAB (2STRIPSX7) اوجمنتين 1جم 14قرص', 'AUGMENTIN 1G (1000MG) 14TAB (2STRIPSX7)'),
    ('120643', 'AUGMENTIN 1GM/125MG 12SACH (XX) اوجمنتين فوار', 'AUGMENTIN 1GM/125MG 12SACH (XX)'),
    ('3655', 'AUGMENTIN 156MG SYRUP 80ML اوجمنتين 156مجم شراب', 'AUGMENTIN 156MG SYRUP 80ML'),
    ('90048', 'AUGMENTIN 457MG/5ML SYRUP 70ML اوجمنتين 457مجم شراب', 'AUGMENTIN 457MG/5ML SYRUP 70ML اوجمنتين'),
    ('95265', 'AUGMENTIN 62.5MG/ML  DROPS 20ML (XX) اوجمنتين 62.5مجم نقط', 'AUGMENTIN 62.5MG/ML  DROPS 20ML (XX)'),
    ('3679', 'AUGMENTINE 625MG 10TAB اوجمنتين 625مجم 10ق', 'AUGMENTINE 625MG 10TAB اوجمنتين 625مجم 1'),
    ('102879', 'AUGMENTINE  312MG 80ML SYRUP اوجمنتين 312مجم شراب', 'AUGMENTINE 312MG 80ML SYRUP'),
    ('94879', 'AUGMACILLIN 200/28.5MG    SYRUP  60  ML اوجمنتين 228مجم شراب', 'AUGMACILLIN 200/28.5MG    SYRUP  60  ML'),
    ('94878', 'AUGMACILLIN 400/57MG  MG  SYRUP  60  ML اوجمنتين 457مجم شراب', 'AUGMACILLIN 400/57MG  MG  SYRUP  60  ML'),
    ('112742', 'GLUCOPHAGE XR 500 MG 30 TAB (3STRIPSX10) XX EGYPT', 'GLUCOPHAGE XR 500 MG 30 TAB (3STRIPSX10)'),
    ('103855', 'GLUCOPHAGE XR 1000MG 1GM 30TAB (XX) (3STRIPSX10) جلوكوفاج اكس ار', 'GLUCOPHAGE XR 1000MG    30TAB (XX)'),
    ('88853', 'GLUCOPHAGE 500 MG 50 TAB (MINAPHARM) (5 STRIPSX10)',
     'GLUCOPHAGE 500 MG 50 TAB (MINAPHARM) (5 STRIPSX10)'),
    ('34214', 'METFORMIN 500 MG  30 TAB', 'METFORMIN 500 MG  30 TAB'),
    ('106903', 'CONCOR 5MG 30TAB (3STRIPX10) BIG SIZE', 'CONCOR 5MG 30TAB (3STRIPX10) BIG SIZE'),
    ('106488', 'CONCOR 10MG 30TAB (3STRIPSX10) BIG SIZE', 'CONCOR 10MG 30TAB (3STRIPSX10) BIG SIZE'),
    ('106487', 'CONCOR COR 2.5MG 30TAB (3STRIPSX10)', 'CONCOR COR 2.5MG 30TAB (3STRIPSX10'),
    ('100783', 'CONCOR AMLO 5MG/5MG 30TAB (XX) (3STRIPSX10)', 'CONCOR AMLO 5MG/5MG 30TAB (XX) (3STRIPSX'),
    ('106965', 'CONCOR PLUS 5MG / 12.5MG 30TAB (3STRIPSX10) BIG SIZE', 'CONCOR PLUS 5MG / 12.5MG 30TAB (3STRIPSX'),
    ('93999', 'NEXIUM 40 MG POWDER FOR I.V. INF. VIAL XX', 'NEXIUM 40 MG POWDER FOR I.V. INF. VIAL X'),
    ('103355', 'NEXIUM 40MG 28TAB (LOCAL)  (4STRIPSX7)', 'NEXIUM 40MG 28TAB (LOCAL) (4STRIPSX7)'),
    ('103356', 'NEXIUM 20MG 28TAB #LOCAL (4STRIPSX7)', 'NEXIUM 20MG 28TAB (LOCAL) (4STRIPSX7)'),
    ('96902', 'OMEGA 3 NAPCO 100ML SYRUP', 'OMEGA 3 NAPCO 100ML SYRUP'),
    ('125058', 'CERVELLO  KIDS OMEGA 3 60GUM', 'CERVELLO  KIDS OMEGA 3 60GUM'),
    ('102686', 'NINOLAC  WHEAT & MILK  OMEGA3 400GM', 'NINOLAC  WHEAT & MILK  OMEGA3 400GM'),
    ('127452', 'ALEJON VIT C & ALGAE PEEL OFF FACIAL MASK 125ML', 'ALEJON VIT C & ALGAE PEEL OFF FACIAL MASK 125ML'),
    ('126316', 'EVA FACE SERUM 30MIL VIT C', 'EVA FACE SERUM 30MIL VIT C'),
    ('98830', 'SANSOVIT CALCIUM  SYRUP 200ML', 'SANSOVIT CALCIUM  SYRUP 200ML'),
    ('84200', 'ZYRTEC ORAL DROPS 10ML', 'ZYRTEC ORAL DROPS 10ML'),
    ('82941', 'ZYRTEC 10MG 20TAB', 'ZYRTEC 10MG 20TAB'),
    ('82824', 'ZYRTEC ORAL SOLUTION SUSP 0.1% MG 100ML', 'ZYRTEC ORAL SOLUTION SUSP 0.1% MG 100ML'),
    ('130054', 'SOUVENIR ROGO COLORE 250M(3690) PERFUME SPLASH', 'SOUVENIR ROGO COLORE 250M(3690) PERFUME SPLASH'),
    ('87786', 'CONGESTAL 20TAB (2STRIPSX10) كونجستال 20قرص', 'CONGESTAL 20TAB (2STRIPSX10) كونجستال 20'),
    ('82209', 'CONGESTAL COLD AND FLU SYRUP 120ML كونجستال شراب', 'CONGESTAL COLD AND FLU SYRUP 120ML كونجس'),
    ('343', 'DECONGESTYL - N RECTAL 12SUPP', 'DECONGESTYL - N RECTAL 12SUPP'),
    ('117813', 'CERELAC WHEAT WITHOUT MILK 250GM 6MONTHS+ سيريلاك قمح بدون لبن', 'CERELAC WHEAT WITHOUT MILK 250GM 6MONTHS+'),
    ('117818', 'CERELAC WHEAT WITH MILK 125GM سيريلاك قمح مع لبن', 'CERELAC WHEAT WITH MILK 125GM سيريلاك قم'),
    ('569', 'BRUFEN 400MG 30TAB (3STRIPSX10) بروفين 400مجم', 'BRUFEN   400  MG  30 TAB'),
    ('613', 'BRUFEN 600MG 30TAB (3STRIPSX10)', 'BRUFEN 600MG 30TAB'),
    ('130770', 'PROVEN MOISTURIZING CREAM 10% UREA 100M', 'PROVEN MOISTURIZING CREAM 10% UREA 100M'),
    ('2324', 'ANTINAL 220MG/5ML SUSP 60ML انتينال معلق', 'ANTINAL 220MG/5ML SUSP 60ML انتينال معلق'),
    ('99178', 'ANTINAL  200  MG  24  CAP', 'ANTINAL  200  MG  24  CAP'),
    ('119232', 'PANTHENOL 2% CREAM 50GM BIG SIZE', 'PANTHENOL 2% CREAM 50GM BIG SIZE'),
    ('98318', 'سكريه', 'سكريه'),
    ('117418', 'ALLEVIA PLUS BLOOD GLUCOSE OFFR جهاز سكر +100 شريط', 'ALLEVIA PLUS BLOOD GLUCOSE OFFR جهاز سكر +100 شريط'),
    ('129013', 'CARESENS FIT  جهاز سكر', 'CARESENS FIT  جهاز سكر'),
    ('126131', 'GLUCO DR AUTO BLOOD GLUCOSE MONITOR جهاز سكر', 'GLUCO DR AUTO BLOOD GLUCOSE MONITOR جهاز سكر'),
    ('109387', 'ACNETROX 1% TOPICAL 25 GM  CREAM', 'ACNETROX 1% TOPICAL 25 GM  CREAM'),
    ('3759', 'DERMAZIN   1 %  30  GM  CREAM', 'DERMAZIN   1 %  30  GM  CREAM'),
    ('911', 'MICORT   1 %   20 GM   CREAM', 'MICORT   1 %   20 GM   CREAM'),
    ('87547', 'TOP-4  15 GM CREAM', 'TOP-4  15 GM CREAM'),
    ('1972', 'BETNOVATE  * C *   15  GM  CREAM', 'BETNOVATE  * C *   15  GM  CREAM'),
    ('92559', 'FIRST SURG PAD <15CMX25CM> DRESSING PAD', 'FIRST SURG PAD <15CMX25CM> DRESSING PAD'),
]

# (softech_id, barcode) — ItemBarcode rows
SEED_BARCODES = [('106903', '6221025032348')]

# (softech_id, ActiveIngredient name) — ItemIngredientMap rows. Nothing seeded is NAMED diclofenac,
# so «diclofenac» can only be found through this map (the `ingredient` tier).
SEED_INGREDIENTS = [('89489', 'DICLOFENAC POTASSIUM')]


def check(entry, rows) -> bool:
    """rows: [(name, tier)] best first. True when a row in the first entry['top'] matches
    entry['expect'] — and, if the entry names a tier, that row has that tier."""
    rx = re.compile(entry['expect'], re.I)
    for name, tier in rows[:entry.get('top', 1)]:
        if rx.search(name or ''):
            return entry.get('tier') is None or tier == entry['tier']
    return False
