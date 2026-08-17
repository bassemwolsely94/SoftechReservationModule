"""
apps/chronic/management/commands/seed_drug_interactions.py

Seeds the DrugInteraction and DrugContraindication tables with a curated
pharmacy-grade knowledge base covering the most common interactions and
contraindications encountered in an Egyptian pharmacy chain.

Usage:
    python manage.py seed_drug_interactions
    python manage.py seed_drug_interactions --clear   (delete all existing and re-seed)
    python manage.py seed_drug_interactions --dry-run (show what would be added)

Sources:
    BNF (British National Formulary), Drugs.com, clinical pharmacology guidelines.
    All entries are manually validated for the Egyptian context.

Run ONCE on initial setup, then manually add new interactions via Django admin.
"""
from django.core.management.base import BaseCommand


# ── Drug-Drug Interactions ─────────────────────────────────────────────────────
# Format: (ingredient_a, ingredient_b, severity, clinical_effect, management_ar, source)
# NOTE: ingredient_a < ingredient_b alphabetically (enforced by model.save())

DRUG_INTERACTIONS = [
    # ── Anticoagulants ────────────────────────────────────────────────────────
    ('aspirin',    'warfarin',        'major',
     'زيادة خطر النزيف بشكل كبير عند الجمع بينهما',
     'تجنب الجمع إلا بأمر الطبيب. إذا كان ضرورياً: أقل جرعة أسبرين ممكنة مع مراقبة دورية INR.',
     'BNF'),
    ('clopidogrel', 'warfarin',       'major',
     'تضاعف خطر النزيف الشديد',
     'تجنب الجمع. إذا لزم: مراقبة INR يومياً في البداية.',
     'Drugs.com'),
    ('ibuprofen',  'warfarin',        'major',
     'NSAIDs تزيد تأثير الوارفارين وتزيد خطر نزيف المعدة',
     'استخدم باراسيتامول بدلاً من إيبوبروفين عند مرضى الوارفارين.',
     'BNF'),
    ('aspirin',    'ibuprofen',       'moderate',
     'إيبوبروفين يقلل من التأثير المضاد للصفائح للأسبرين بجرعة منخفضة',
     'خذ الأسبرين قبل الإيبوبروفين بـ 30 دقيقة على الأقل أو بعده بـ 8 ساعات.',
     'FDA'),
    ('apixaban',   'ibuprofen',       'major',
     'NSAID مع DOAC يزيد خطر النزيف',
     'استخدم باراسيتامول. تجنب NSAIDs مع DOACs.',
     'BNF'),
    ('rivaroxaban', 'ibuprofen',      'major',
     'NSAID مع DOAC يزيد خطر النزيف الهضمي',
     'استخدم باراسيتامول بدلاً من NSAIDs.',
     'BNF'),

    # ── Statins ───────────────────────────────────────────────────────────────
    ('atorvastatin', 'clarithromycin', 'major',
     'كلاريثروميسين يثبط CYP3A4 فيزيد مستوى الستاتين → خطر اعتلال العضلات والرابدوميوليسيس',
     'أوقف الأتورفاستاتين مؤقتاً أثناء دورة الكلاريثروميسين.',
     'BNF'),
    ('atorvastatin', 'erythromycin',  'moderate',
     'إريثروميسين يزيد مستوى الأتورفاستاتين',
     'راقب أعراض آلام العضلات. أوقف الستاتين إذا ارتفع CK.',
     'Drugs.com'),
    ('simvastatin', 'clarithromycin', 'major',
     'زيادة كبيرة في مستوى سيمفاستاتين → رابدوميوليسيس',
     'تجنب تماماً. استخدم روسوفاستاتين أو برافاستاتين إذا لزم الستاتين.',
     'BNF'),
    ('atorvastatin', 'amlodipine',    'minor',
     'أملوديبين يزيد مستوى الأتورفاستاتين بنسبة 18%',
     'لا تتجاوز 40mg أتورفاستاتين مع أملوديبين. المراقبة كافية في الغالب.',
     'FDA'),
    ('rosuvastatin', 'antacid',       'minor',
     'مضادات الحموضة قد تقلل امتصاص الروسوفاستاتين',
     'خذ الروسوفاستاتين بعد مضادات الحموضة بساعتين.',
     'Drugs.com'),

    # ── ACE Inhibitors / ARBs + Potassium ─────────────────────────────────────
    ('enalapril',   'spironolactone', 'major',
     'الجمع يؤدي لفرط بوتاسيوم الدم — خاصة عند مرضى الكلى',
     'تحقق من وظائف الكلى وبوتاسيوم الدم بانتظام. ابدأ بجرعات منخفضة.',
     'BNF'),
    ('lisinopril',  'potassium',      'moderate',
     'ACE Inhibitors ترفع البوتاسيوم — المكملات تزيد الخطر',
     'راقب بوتاسيوم الدم إذا أُضيف مكمل البوتاسيوم.',
     'BNF'),
    ('losartan',    'spironolactone', 'major',
     'فرط بوتاسيوم الدم الخطير',
     'تجنب الجمع إلا مع مراقبة مستمرة لبوتاسيوم الدم والكلى.',
     'Drugs.com'),

    # ── Diabetes ─────────────────────────────────────────────────────────────
    ('glibenclamide', 'fluconazole',  'major',
     'فلوكونازول يثبط استقلاب السلفونيل يوريا → نقص سكر حاد',
     'راقب سكر الدم بشكل متكرر. قد تحتاج لتقليل جرعة الجليبنكلاميد.',
     'BNF'),
    ('metformin',    'contrast_dye',  'major',
     'صبغة التباين الإشعاعي تزيد خطر الحماض اللبني مع الميتفورمين',
     'أوقف الميتفورمين 48 ساعة قبل الأشعة بالصبغة وبعدها حتى تطبيع الكلى.',
     'Clinical Guidelines'),
    ('glimepiride',  'fluconazole',   'major',
     'نفس تأثير الجليبنكلاميد — خطر نقص سكر حاد',
     'راقب سكر الدم. قلل الجرعة إذا لزم.',
     'Drugs.com'),
    ('metformin',    'alcohol',       'moderate',
     'الكحول يزيد خطر الحماض اللبني مع الميتفورمين',
     'انصح المريض بتجنب الكحول أثناء استخدام الميتفورمين.',
     'BNF'),

    # ── Antihypertensives ─────────────────────────────────────────────────────
    ('amlodipine',  'simvastatin',    'moderate',
     'أملوديبين يزيد مستوى سيمفاستاتين',
     'لا تتجاوز 20mg سيمفاستاتين مع أملوديبين.',
     'FDA'),
    ('bisoprolol',  'verapamil',      'major',
     'بيتا بلوكر + فيراباميل يسببان بطء القلب الشديد والانسداد الأذيني البطيني',
     'تجنب الجمع تماماً إلا تحت إشراف القلب.',
     'BNF'),
    ('metoprolol',  'verapamil',      'major',
     'انسداد قلبي خطير',
     'تجنب الجمع.',
     'BNF'),

    # ── Antibiotics ───────────────────────────────────────────────────────────
    ('ciprofloxacin', 'antacid',      'moderate',
     'مضادات الحموضة تقلل امتصاص الكينولونات بنسبة تصل لـ 90%',
     'خذ السيبروفلوكساسين قبل مضادات الحموضة بساعتين أو بعدها بـ 6 ساعات.',
     'BNF'),
    ('ciprofloxacin', 'warfarin',     'moderate',
     'سيبروفلوكساسين يزيد تأثير الوارفارين',
     'راقب INR خلال وبعد الدورة.',
     'BNF'),
    ('metronidazole', 'warfarin',     'major',
     'ميترونيدازول يضاعف تأثير الوارفارين بشكل كبير',
     'تجنب أو قلل جرعة الوارفارين بنسبة 50% مع مراقبة INR يومياً.',
     'BNF'),
    ('amoxicillin',  'warfarin',      'moderate',
     'المضادات الحيوية الواسعة الطيف قد تزيد INR',
     'راقب INR خلال الدورة وبعدها.',
     'Drugs.com'),

    # ── Thyroid ───────────────────────────────────────────────────────────────
    ('levothyroxine', 'calcium',      'moderate',
     'الكالسيوم يقلل امتصاص الليفوثيروكسين',
     'خذ الليفوثيروكسين صائماً وبعيداً عن الكالسيوم 4 ساعات على الأقل.',
     'BNF'),
    ('levothyroxine', 'antacid',      'moderate',
     'مضادات الحموضة تقلل امتصاص هرمون الغدة الدرقية',
     'خذ الهرمون قبل مضادات الحموضة بـ 4 ساعات.',
     'Drugs.com'),
    ('levothyroxine', 'iron',         'moderate',
     'الحديد يقلل امتصاص الليفوثيروكسين',
     'فاصل 4 ساعات على الأقل بين الليفوثيروكسين والحديد.',
     'BNF'),

    # ── Psychiatric ───────────────────────────────────────────────────────────
    ('sertraline',   'tramadol',      'major',
     'خطر متلازمة السيروتونين — قد تكون قاتلة',
     'تجنب الجمع. استخدم مسكنات ألم أخرى مع مضادات الاكتئاب السيروتونينية.',
     'BNF'),
    ('fluoxetine',   'tramadol',      'major',
     'متلازمة السيروتونين الخطيرة',
     'تجنب تماماً.',
     'FDA'),
    ('sertraline',   'nsaids',        'moderate',
     'SSRI + NSAID يزيد خطر نزيف الجهاز الهضمي',
     'أضف حماية معدة (PPI) إذا كان الجمع ضرورياً.',
     'BNF'),
    ('alprazolam',   'clarithromycin','major',
     'كلاريثروميسين يزيد مستوى الألبرازولام بشكل كبير → تنميل مفرط',
     'قلل جرعة الألبرازولام أو استخدم بنزوديازيبين بديل لا يستقلب عبر CYP3A4.',
     'BNF'),

    # ── Cardiac ───────────────────────────────────────────────────────────────
    ('digoxin',      'amiodarone',    'major',
     'أميودارون يرفع مستوى الديجوكسين بنسبة 50-100%',
     'قلل جرعة الديجوكسين 50% عند بدء الأميودارون. راقب مستوى الدم.',
     'BNF'),
    ('digoxin',      'erythromycin',  'moderate',
     'إريثروميسين يزيد مستوى الديجوكسين',
     'راقب أعراض تسمم الديجوكسين وقس مستواه في الدم.',
     'Drugs.com'),
    ('bisoprolol',   'diltiazem',     'major',
     'تثبيط مشترك للعقدة الجيبية الأذينية → بطء قلب وانسداد قلبي',
     'تجنب إلا تحت إشراف طبي مكثف مع مراقبة ECG.',
     'BNF'),

    # ── Acid Reflux ──────────────────────────────────────────────────────────
    ('omeprazole',   'clopidogrel',   'moderate',
     'أوميبرازول يقلل التحويل الحيوي للكلوبيدوجريل إلى شكله الفعال',
     'استخدم بانتوبرازول أو رابيبرازول بدلاً من أوميبرازول مع كلوبيدوجريل.',
     'FDA'),
    ('pantoprazole', 'methotrexate',  'moderate',
     'PPIs ترفع مستوى الميثوتريكسات',
     'راقب سمية الميثوتريكسات. أوقف PPI قبل الجرعة العالية منه.',
     'BNF'),

    # ── Pain / NSAIDs ─────────────────────────────────────────────────────────
    ('ibuprofen',    'lisinopril',    'moderate',
     'NSAIDs تقلل تأثير ACE Inhibitors وقد ترفع ضغط الدم',
     'استخدم باراسيتامول بدلاً من إيبوبروفين. راقب ضغط الدم.',
     'BNF'),
    ('diclofenac',   'methotrexate',  'major',
     'ديكلوفيناك يقلل إفراز الميثوتريكسات الكلوي → سمية مضاعفة',
     'تجنب الجمع. استخدم باراسيتامول بجرعات منخفضة إذا لزم.',
     'BNF'),
    ('ibuprofen',    'methotrexate',  'major',
     'NSAIDs تزيد سمية الميثوتريكسات بشكل خطير',
     'تجنب تماماً.',
     'BNF'),
]

# ── Drug-Condition Contraindications ──────────────────────────────────────────
# Format: (ingredient, condition, severity, population, description_ar, source)

DRUG_CONTRAINDICATIONS = [
    # ── NSAIDs ────────────────────────────────────────────────────────────────
    ('ibuprofen',     'renal',          'absolute',   '',          'NSAIDs تسبب تدهور حاد لوظائف الكلى عند مرضى القصور الكلوي', 'BNF'),
    ('diclofenac',    'renal',          'absolute',   '',          'NSAIDs ممنوعة في قصور الكلى الشديد', 'BNF'),
    ('ibuprofen',     'cardiovascular', 'relative',   '',          'NSAIDs ترفع خطر النوبة القلبية والسكتة الدماغية', 'FDA'),
    ('diclofenac',    'cardiovascular', 'relative',   '',          'تجنب NSAIDs عند مرضى القلب إلا عند الضرورة', 'BNF'),
    ('ibuprofen',     'gerd',           'caution',    '',          'NSAIDs تهيج بطانة المعدة — أضف PPI وقائي', 'BNF'),
    ('naproxen',      'renal',          'absolute',   '',          'NSAIDs ممنوعة مع قصور الكلى', 'BNF'),
    ('ibuprofen',     'hypertension',   'caution',    '',          'NSAIDs ترفع الضغط وتقاوم مفعول أدوية الضغط', 'BNF'),

    # ── Pregnancy ─────────────────────────────────────────────────────────────
    ('ibuprofen',     'other_chronic',  'absolute',   'pregnancy', 'NSAIDs ممنوعة في الثلث الثالث من الحمل — تسبب إغلاق القناة الشريانية', 'BNF'),
    ('diclofenac',    'other_chronic',  'absolute',   'pregnancy', 'NSAIDs ممنوعة في الثلث الثالث', 'BNF'),
    ('aspirin',       'other_chronic',  'relative',   'pregnancy', 'الجرعة العالية ممنوعة في الحمل. الجرعة المنخفضة (75-150mg) تحت إشراف طبي مقبولة', 'BNF'),
    ('atorvastatin',  'other_chronic',  'absolute',   'pregnancy', 'الستاتينات ممنوعة في الحمل — خطر على الجنين', 'FDA'),
    ('rosuvastatin',  'other_chronic',  'absolute',   'pregnancy', 'الستاتينات ممنوعة في الحمل', 'FDA'),
    ('warfarin',      'other_chronic',  'absolute',   'pregnancy', 'وارفارين يعبر المشيمة ويسبب تشوهات جنينية', 'BNF'),
    ('methotrexate',  'other_chronic',  'absolute',   'pregnancy', 'ميثوتريكسات مشيج ومسرطن — ممنوع منعاً باتاً في الحمل', 'BNF'),
    ('fluconazole',   'other_chronic',  'relative',   'pregnancy', 'الجرعة العالية المتكررة مرتبطة بتشوهات. دورة واحدة 150mg مقبولة', 'FDA'),

    # ── Renal Impairment ──────────────────────────────────────────────────────
    ('metformin',     'renal',          'absolute',   'renal',     'ميتفورمين ممنوع مع eGFR<30 — خطر الحماض اللبني', 'BNF'),
    ('metformin',     'renal',          'relative',   '',          'قلل الجرعة مع eGFR 30-45. توقف مع eGFR<30', 'BNF'),
    ('enalapril',     'renal',          'caution',    '',          'ACE Inhibitors قد تزيد البوتاسيوم وتسوء الكلى في الأوعية الكلوية الضيقة', 'BNF'),

    # ── Hepatic Impairment ────────────────────────────────────────────────────
    ('atorvastatin',  'other_chronic',  'absolute',   'hepatic',   'الستاتينات ممنوعة مع أمراض الكبد النشطة وارتفاع الإنزيمات الكبدية', 'BNF'),
    ('methotrexate',  'other_chronic',  'absolute',   'hepatic',   'ميثوتريكسات يسبب تليف كبدي — ممنوع مع أمراض الكبد', 'BNF'),
    ('paracetamol',   'other_chronic',  'relative',   'hepatic',   'قلل جرعة الباراسيتامول إلى 2g/يوم عند مرضى الكبد المزمن', 'BNF'),

    # ── Diabetes ─────────────────────────────────────────────────────────────
    ('metformin',     'cardiovascular', 'caution',    '',          'توقف الميتفورمين قبل القسطرة القلبية وعند تدهور وظائف الكلى', 'Clinical'),
    ('glibenclamide', 'renal',          'absolute',   '',          'خطر نقص سكر طويل الأمد عند القصور الكلوي — لا يُطرح مناسباً', 'BNF'),

    # ── Thyroid ───────────────────────────────────────────────────────────────
    ('levothyroxine', 'cardiovascular', 'caution',    '',          'ابدأ بجرعة منخفضة جداً عند مرضى القلب — قد تحفز الذبحة', 'BNF'),

    # ── Anticoagulants ────────────────────────────────────────────────────────
    ('warfarin',      'renal',          'caution',    '',          'قصور الكلى يؤثر على استقلاب الوارفارين — راقب INR أكثر', 'BNF'),

    # ── Asthma ────────────────────────────────────────────────────────────────
    ('bisoprolol',    'asthma',         'absolute',   '',          'حاصرات بيتا ممنوعة في الربو — تسبب تشنج قصبي قاتل', 'BNF'),
    ('metoprolol',    'asthma',         'absolute',   '',          'حاصرات بيتا ممنوعة في الربو وCOPD الشديد', 'BNF'),
    ('atenolol',      'asthma',         'absolute',   '',          'حاصرات بيتا غير الانتقائية ممنوعة في الربو', 'BNF'),
    ('propranolol',   'asthma',         'absolute',   '',          'ممنوع منعاً باتاً في الربو', 'BNF'),
    ('ibuprofen',     'asthma',         'caution',    '',          '10% من مرضى الربو حساسون للـ NSAIDs — ابدأ بحذر', 'BNF'),
    ('aspirin',       'asthma',         'relative',   '',          'خطر الربو بالأسبرين عند المرضى الحساسين (NSAID-sensitive asthma)', 'BNF'),

    # ── Oncology ─────────────────────────────────────────────────────────────
    ('ibuprofen',     'oncology',       'relative',   '',          'NSAIDs تتفاعل مع بعض العلاجات الكيماوية — استشر أخصائي الأورام', 'Clinical'),
    ('aspirin',       'oncology',       'caution',    '',          'قد يزيد خطر النزيف مع العلاج الكيماوي', 'Clinical'),

    # ── Cholesterol ───────────────────────────────────────────────────────────
    ('atorvastatin',  'other_chronic',  'absolute',   'hepatic',   'الستاتينات ممنوعة مع ارتفاع إنزيمات الكبد الناشط', 'BNF'),

    # ── GERD / Peptic Ulcer ───────────────────────────────────────────────────
    ('ibuprofen',     'gerd',           'relative',   '',          'NSAIDs تهيج المعدة وتسبب تقرحات — أضف PPI وقائي دائماً', 'BNF'),
    ('naproxen',      'gerd',           'relative',   '',          'NSAIDs تهيج المعدة', 'BNF'),
    ('aspirin',       'gerd',           'caution',    '',          'الأسبرين يهيج المعدة. الجرعة المعوية مغلفة مفضلة', 'BNF'),
]


class Command(BaseCommand):
    help = 'Seed DrugInteraction and DrugContraindication knowledge base'

    def add_arguments(self, parser):
        parser.add_argument('--clear',   action='store_true',
            help='Delete all existing records before seeding')
        parser.add_argument('--dry-run', action='store_true',
            help='Show what would be added without saving')

    def handle(self, *args, **options):
        from apps.chronic.models import DrugInteraction, DrugContraindication

        dry_run = options['dry_run']
        suffix  = '  [DRY RUN — nothing saved]' if dry_run else ''

        if options['clear'] and not dry_run:
            di_count = DrugInteraction.objects.count()
            dc_count = DrugContraindication.objects.count()
            DrugInteraction.objects.all().delete()
            DrugContraindication.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f'Cleared {di_count} interactions + {dc_count} contraindications')
            )

        # ── Seed DrugInteraction ──────────────────────────────────────────────
        di_created = di_skipped = 0
        for row in DRUG_INTERACTIONS:
            ing_a, ing_b, severity, effect, mgmt, source = row
            if dry_run:
                self.stdout.write(f'  [DI] {ing_a} ↔ {ing_b} [{severity}]')
                di_created += 1
                continue
            _, created = DrugInteraction.objects.get_or_create(
                ingredient_a = min(ing_a, ing_b),   # canonical order
                ingredient_b = max(ing_a, ing_b),
                defaults={
                    'severity':       severity,
                    'clinical_effect': effect,
                    'management_ar':  mgmt,
                    'source':         source,
                    'is_active':      True,
                },
            )
            if created:
                di_created += 1
            else:
                di_skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'DrugInteraction{suffix}: {di_created} added, {di_skipped} already existed'
        ))

        # ── Seed DrugContraindication ─────────────────────────────────────────
        dc_created = dc_skipped = 0
        for row in DRUG_CONTRAINDICATIONS:
            ingredient, condition, severity, population, desc, source = row
            if dry_run:
                pop = f' [{population}]' if population else ''
                self.stdout.write(f'  [DC] {ingredient} + {condition}{pop} [{severity}]')
                dc_created += 1
                continue
            _, created = DrugContraindication.objects.get_or_create(
                ingredient  = ingredient,
                condition   = condition,
                population  = population,
                defaults={
                    'severity':       severity,
                    'description_ar': desc,
                    'source':         source,
                    'is_active':      True,
                },
            )
            if created:
                dc_created += 1
            else:
                dc_skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'DrugContraindication{suffix}: {dc_created} added, {dc_skipped} already existed'
        ))

        if not dry_run:
            total_di = DrugInteraction.objects.count()
            total_dc = DrugContraindication.objects.count()
            self.stdout.write(self.style.SUCCESS(
                f'\nKnowledge base: {total_di} interactions + {total_dc} contraindications total'
            ))
