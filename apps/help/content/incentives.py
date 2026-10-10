from . import T

MODULE = {
    'key': 'incentives', 'group': 'analytics', 'icon': '💰',
    'title': T('الحوافز', 'Sales incentives'),
    'summary': T(
        'محرك حوافز البيع على الأصناف: «برنامج» لفترة (أسبوعي/شهري/مخصص، ويمكن أن يرعاه مورد) فيه «قواعد» تحدد الأصناف المستهدفة وطريقة الحافز '
        '(نسبة من صافي البيع، مبلغ لكل وحدة، مبلغ لكل فاتورة، أو سلاب متدرج بالكمية) بشروط (حد أدنى، مندوب، فرع، محلي/مستورد، صلاحية…). '
        'يُحتسب من مبيعات SOFTECH لكل مندوب، تُضاف التسويات اليدوية، ثم «تُعتمد» نهائياً فتُقفل الفترة. الحركات المحتسبة لا تُعدَّل أبداً بعد الاعتماد.',
        'An item-based sales incentive engine: a "program" for a period (weekly/monthly/custom, optionally sponsored by a supplier) holds "rules" that set the target items and the incentive '
        '(% of net sale, amount per unit, amount per invoice, or a quantity slab) with conditions (minimum, salesperson, branch, local/imported, expiry…). '
        'It is calculated from SOFTECH sales per salesperson, manual adjustments are added, then it is "finalized", locking the period. Calculated entries are never edited after finalizing.'),
}

SCREENS = [
    {
        'key': 'incentives.programs',
        'routes': ['/incentives'],
        'title': T('إدارة الحوافز', 'Incentive management'),
        'summary': T('كل خطوات الحوافز في تبويبات، بالترتيب من البرنامج حتى التسوية النهائية. اختر البرنامج أولاً من «البرامج» — باقي التبويبات تعمل على البرنامج المختار.',
                     'Every incentive step in tabs, in order from the program to the final settlement. Pick the program first in "Programs" — the other tabs work on the chosen program.'),
        'audience': T('المدير والمشتريات والجودة.', 'Admins, purchasing and quality.'),
        'tabs': [
            {'key': 'programs', 'title': T('🏆 البرامج', '🏆 Programs'), 'body': T('إنشاء برنامج (الاسم، الوصف، البداية والنهاية، دورة الاحتساب، المورد الراعي ونسبة مساهمته) أو «نسخ البرنامج» بقواعده، واختيار البرنامج للعمل عليه.', 'Create a program (name, description, start and end, cycle, sponsoring supplier and its share) or "Copy program" with its rules, and select the program to work on.')},
            {'key': 'rules', 'title': T('📐 القواعد', '📐 Rules'), 'body': T('قواعد البرنامج: الأصناف (إضافة يدوية أو استيراد CSV)، نوع الحافز، السلاب المتدرج (من-إلى وحدة والسعر — يُطبَّق على إجمالي كمية الفترة)، والشروط.', 'The program\'s rules: items (manual or CSV import), incentive type, the slab (from-to units and rate — applied to the period\'s total quantity), and conditions.')},
            {'key': 'calculate', 'title': T('⚡ الاحتساب', '⚡ Calculate'), 'body': T('حدد الفترة ← «معاينة (محاكاة)» بدون حفظ ← «تشغيل الاحتساب». الفترة المُعتمدة مقفلة إلا بـ «إعادة الاحتساب بالقوة».', 'Set the period → "Preview (simulation)" without saving → "Run calculation". A finalized period is locked unless you "force recalculate".')},
            {'key': 'report', 'title': T('📊 التقرير', '📊 Report'), 'body': T('لكل مندوب: المبيعات والمرتجعات وإجمالي الحوافز والتسويات اليدوية والصافي. «اعتماد التسويات نهائياً» لا يمكن التراجع عنه.', 'Per salesperson: sales, returns, total incentives, manual adjustments and net. "Finalize settlements" cannot be undone.')},
            {'key': 'near-expiry', 'title': T('⏰ قريب الصلاحية', '⏰ Near expiry'), 'body': T('مخزون قريب الانتهاء من SOFTECH مباشرة (مخازن الحجر 102/103/105 مستبعدة) — مرشح لحافز يسرّع بيعه.', 'Near-expiry stock straight from SOFTECH (quarantine stores 102/103/105 excluded) — a candidate for an incentive to sell it faster.')},
            {'key': 'roi', 'title': T('📈 عائد الاستثمار', '📈 ROI'), 'body': T('تكلفة الحوافز مقابل الإيراد الإضافي ومعدل البيع اليومي قبل وأثناء البرنامج: ممتاز، مقبول، أو أقل من التعادل.', 'Incentive cost vs extra revenue and daily sales rate before and during the program: excellent, acceptable or below break-even.')},
            {'key': 'suggestions', 'title': T('🧠 اقتراحات ذكية', '🧠 Smart suggestions'), 'body': T('أصناف مرشحة لبرامج الحوافز (مثلاً قريبة الصلاحية) يمكن إضافتها لقاعدة في البرنامج.', 'Items suggested for incentive programs (e.g. near expiry) that can be added to a rule.')},
            {'key': 'adjustments', 'title': T('✏️ تسويات يدوية', '✏️ Manual adjustments'), 'body': T('إضافة أو خصم يدوي لمندوب في فترة بسبب مكتوب. لا يمكن الحذف بعد اعتماد الفترة.', 'A manual addition or deduction for a salesperson in a period with a written reason. Cannot be deleted after the period is finalized.')},
            {'key': 'settlements', 'title': T('✅ التسويات النهائية', '✅ Final settlements'), 'body': T('التسويات المُعتمدة لكل مندوب مع إيصال قابل للطباعة للرواتب.', 'Finalized settlements per salesperson with a printable payroll receipt.')},
            {'key': 'history', 'title': T('🕒 سجل الاحتساب', '🕒 Calculation log'), 'body': T('كل عمليات الاحتساب والمحاكاة: من، متى، الملخص، وأكواد مندوبين غير مرتبطة بموظفين (اربطها).', 'Every calculation and simulation: who, when, summary, and salesperson codes not linked to employees (link them).')},
        ],
        'tips': [T('اربط كود SOFTECH لكل مندوب بحسابه وإلا لن تظهر حوافزه.', 'Link each salesperson\'s SOFTECH code to their account, otherwise their incentives will not show.')],
        'related': ['incentives.mine', 'analytics.performance'],
        'updated': '2026-10-10',
    },
    {
        'key': 'incentives.mine',
        'routes': ['/my-incentives', '/m/my-incentives'],
        'title': T('حوافزي', 'My incentives'),
        'summary': T('تقدمك اللحظي في برامج الحوافز النشطة: المكتسب حتى الآن والمتوقع نهاية الشهر، نسبة الإنجاز، التقدم نحو المستوى التالي في السلاب، والأصناف الأعلى تحقيقاً.',
                     'Your live progress in active incentive programs: earned so far and projected by month end, completion %, progress to the next slab level, and your top items.'),
        'audience': T('كل الموظفين.', 'Every employee.'),
        'tips': [T('التوقع خطي من متوسطك اليومي — قد يختلف عن النتيجة النهائية بعد الاحتساب والاعتماد.', 'The projection is linear from your daily average — it may differ from the final result after calculation and finalizing.')],
        'related': ['incentives.programs'],
        'updated': '2026-10-10',
    },
]
