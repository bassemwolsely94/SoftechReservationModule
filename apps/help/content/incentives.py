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
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول الحوافز', 'A tour of the incentives module'),
            'summary': T('دورة الحافز كاملة: برنامج ← قواعد وأصناف ← معاينة واحتساب من مبيعات SOFTECH ← تقرير وتسويات ← اعتماد نهائي وإيصالات، وبعدين إزاي الموظف بيتابع حوافزه.',
                         'The full incentive cycle: program → rules and items → preview and calculate from SOFTECH sales → report and adjustments → final settlement and receipts, then how an employee follows their incentives.'),
            'roles': ['admin', 'purchasing', 'quality_manager'],
            'steps': [
                {'target': 'nav-incentives', 'nav': '/incentives',
                 'text': T('نبدأ من «التحليلات» ← «الحوافز».',
                           'Start at "Analytics" → "Incentives".'),
                 'more': T('هنا الإدارة بتبني برامج الحوافز وتحسبها وتعتمدها.\n'
                           '• الحوافز بتتحسب من فواتير البيع الفعلية في SOFTECH لكل مندوب — مش بتتكتب يدوي.\n'
                           '• الشاشة للمدير والمشتريات والجودة.',
                           'This is where management builds, calculates and finalizes incentive programs.\n'
                           '• Incentives are calculated from actual SOFTECH sales invoices per salesperson — not typed by hand.\n'
                           '• The screen is for admins, purchasing and quality.')},
                {'target': 'incentives-programs-tabs', 'route': '/incentives',
                 'text': T('التبويبات مرتبة بخطوات الشغل من «البرامج» لـ«سجل الاحتساب».',
                           'The tabs are ordered by work step, from "Programs" to "Calculation log".'),
                 'more': T('الترتيب: 🏆 البرامج ← 📐 القواعد ← ⚡ الاحتساب ← 📊 التقرير ← ✏️ تسويات يدوية ← ✅ التسويات النهائية.\n'
                           '• ⏰ قريب الصلاحية و🧠 اقتراحات ذكية بيساعدوك تختار أصناف الحافز، و📈 عائد الاستثمار بيقيس نجاحه.\n'
                           '• كل التبويبات بعد «البرامج» بتشتغل على البرنامج المختار.',
                           'The order: 🏆 Programs → 📐 Rules → ⚡ Calculate → 📊 Report → ✏️ Manual adjustments → ✅ Final settlements.\n'
                           '• ⏰ Near expiry and 🧠 Smart suggestions help pick incentive items, and 📈 ROI measures success.\n'
                           '• Every tab after "Programs" works on the selected program.')},
                {'target': 'incentives-programs-new', 'route': '/incentives',
                 'text': T('١) «+ برنامج جديد»: الاسم والفترة ودورة الاحتساب.',
                           '1) "+ New program": name, period and calculation cycle.'),
                 'more': T('اختار تاريخ البداية والنهاية ودورة الاحتساب (أسبوعي/شهري/مخصص).\n'
                           '• لو مورد راعي البرنامج، سجّل اسمه ونسبة مساهمته — بيتحفظوا مع البرنامج ويتنسخوا معاه.\n'
                           '• بعد الإنشاء بتتنقل لتبويب «القواعد» على طول.',
                           'Choose the start and end dates and the calculation cycle (weekly/monthly/custom).\n'
                           '• If a supplier sponsors the program, record its name and share — they are saved with the program and copied with it.\n'
                           '• After creating it you move straight to the "Rules" tab.')},
                {'target': 'incentives-programs-list', 'route': '/incentives',
                 'text': T('أو اختار برنامج موجود من القائمة.',
                           'Or pick an existing program from the list.'),
                 'more': T('الضغط على بطاقة البرنامج بيختاره وينقلك لـ«القواعد».\n'
                           '• شارة «نشط» معناها البرنامج شغال ويظهر للموظفين في «حوافزي».\n'
                           '• عدد القواعد على البطاقة بيوضح البرنامج متجهّز ولا لسه فاضي.',
                           'Clicking a program card selects it and takes you to "Rules".\n'
                           '• An "Active" badge means the program is running and shows to employees in "My incentives".\n'
                           '• The rule count on the card shows whether the program is set up or still empty.')},
                {'target': 'incentives-programs-clone', 'route': '/incentives',
                 'text': T('«نسخ» لبرنامج الشهر الجاي بنفس القواعد.',
                           '"Copy" for next month\'s program with the same rules.'),
                 'more': T('بدل ما تدخّل الأصناف من الأول كل شهر، انسخ البرنامج واختار التواريخ الجديدة.\n'
                           '• النسخة بتاخد كل القواعد والأصناف.\n'
                           '• البرنامج الأصلي وحساباته مش بيتلمسوا.',
                           'Instead of entering the items again every month, copy the program and choose the new dates.\n'
                           '• The copy takes all rules and items.\n'
                           '• The original program and its calculations are not touched.')},
                {'target': 'incentives-programs-content', 'route': '/incentives',
                 'text': T('٢) في «القواعد»: الأصناف ونوع الحافز والشروط.',
                           '2) In "Rules": items, incentive type and conditions.'),
                 'more': T('كل قاعدة: أصناف (يدوي أو «📂 رفع CSV») + نوع الحافز: نسبة من صافي البيع، مبلغ لكل وحدة، مبلغ لكل فاتورة، أو سلاب متدرج.\n'
                           '• في السلاب السعر بيتطبّق على إجمالي كمية الفترة (مش تصاعدي).\n'
                           '• الحوافز أرقام محسوبة بقواعد ثابتة؛ ومبتغيّرش سعر البيع للعميل.',
                           'Each rule: items (manual or "📂 Upload CSV") + incentive type: % of net sale, amount per unit, amount per invoice, or a quantity slab.\n'
                           '• In a slab the rate applies to the period\'s total quantity (not progressive).\n'
                           '• Incentives are calculated by fixed rules; they do not change the customer\'s selling price.')},
                {'target': 'incentives-programs-tabs', 'route': '/incentives',
                 'text': T('٣) «⚡ الاحتساب»: معاينة الأول، وبعدين تشغيل.',
                           '3) "⚡ Calculate": preview first, then run.'),
                 'more': T('حدد بداية ونهاية الفترة ← «🔍 معاينة (محاكاة)» بتعرض النتيجة من غير ما تحفظ ← لو مظبوطة «⚡ تشغيل الاحتساب».\n'
                           '• لو ظهر «لم يتم ربط X كود مندوب»، اربط الأكواد بالموظفين الأول وإلا حوافزهم مش هتتحسب.\n'
                           '• الفترة المعتمدة مقفولة؛ «إعادة الاحتساب بالقوة» لحالات استثنائية بس.',
                           'Set the period start and end → "🔍 Preview (simulation)" shows the result without saving → if correct, "⚡ Run calculation".\n'
                           '• If "X salesperson codes not linked" appears, link the codes to employees first or their incentives will not be calculated.\n'
                           '• A finalized period is locked; "Force recalculate" is for exceptional cases only.')},
                {'target': 'incentives-programs-tabs', 'route': '/incentives',
                 'text': T('٤) «📊 التقرير» و«✏️ تسويات يدوية» ثم الاعتماد النهائي.',
                           '4) "📊 Report" and "✏️ Manual adjustments", then final approval.'),
                 'more': T('التقرير لكل مندوب: المبيعات والمرتجعات والحوافز والتسويات والصافي، و«تفصيل» لكل سطر.\n'
                           '• أي إضافة أو خصم يدوي بيتسجّل في «تسويات يدوية» بسبب مكتوب.\n'
                           '• «✅ اعتماد التسويات نهائياً» بيقفل الفترة — مفيش رجوع، فراجع كويس قبله.',
                           'The report per salesperson: sales, returns, incentives, adjustments and net, with "Details" for each row.\n'
                           '• Any manual addition or deduction goes in "Manual adjustments" with a written reason.\n'
                           '• "✅ Finalize settlements" locks the period — no going back, so review carefully first.')},
                {'target': 'incentives-programs-content', 'route': '/incentives',
                 'text': T('٥) «✅ التسويات النهائية»: إيصال لكل مندوب للرواتب.',
                           '5) "✅ Final settlements": a receipt per salesperson for payroll.'),
                 'more': T('بعد الاعتماد كل مندوب ليه تسوية بزرار «🖨 إيصال» يتطبع ويتسلّم للرواتب.\n'
                           '• «🕒 سجل الاحتساب» بيحفظ كل احتساب ومحاكاة: مين ومتى والملخص.\n'
                           '• ده سجل المراجعة لو حد سأل الرقم ده جه منين.',
                           'After finalizing, each salesperson has a settlement with a "🖨 Receipt" button to print and hand to payroll.\n'
                           '• "🕒 Calculation log" keeps every calculation and simulation: who, when and the summary.\n'
                           '• That is the audit trail if anyone asks where a number came from.')},
                {'target': 'nav-my-incentives', 'nav': '/my-incentives',
                 'text': T('والموظف بيتابع نفسه من «حوافزي».',
                           'And employees follow their own progress in "My incentives".'),
                 'more': T('«حوافزي» متاحة لكل الموظفين — كل واحد بيشوف أرقامه هو بس.\n'
                           '• بتعرض البرامج النشطة النهارده، محسوبة من مبيعاته في SOFTECH.\n'
                           '• لازم كود المندوب في SOFTECH يكون مربوط بحسابه.',
                           '"My incentives" is open to every employee — each one sees only their own figures.\n'
                           '• It shows the programs active today, calculated from their SOFTECH sales.\n'
                           '• Their SOFTECH salesperson code must be linked to their account.')},
                {'target': 'incentives-mine-totals', 'route': '/my-incentives',
                 'text': T('المكتسب حتى الآن والمتوقع نهاية الشهر.',
                           'Earned so far and projected by month end.'),
                 'more': T('الرقمين مجموع كل البرامج النشطة.\n'
                           '• ده حساب لحظي للعرض بس ومش بيتحفظ — الرقم الرسمي بييجي من الاحتساب والاعتماد.\n'
                           '• بيحفّز الموظف يعرف هو فين من هدفه.',
                           'Both numbers add up all active programs.\n'
                           '• It is a live display-only calculation and is not saved — the official figure comes from calculation and finalizing.\n'
                           '• It helps employees see where they stand against their target.')},
                {'target': 'incentives-mine-program', 'route': '/my-incentives',
                 'text': T('بطاقة لكل برنامج بتقدّمه وأعلى أصنافه.',
                           'A card per program with its progress and top items.'),
                 'more': T('فيها الفترة والمكتسب وتقدم الأيام والمتوقع والأيام المتبقية.\n'
                           '• للبرامج اللي فيها سلاب، «تفاصيل مستهدفات السلاب» بتقول كام وحدة فاضلة للمستوى الجاي.\n'
                           '• الحافز عمره ما يكون أهم من احتياج المريض وسلامته.',
                           'It holds the period, earnings, day progress, projection and days remaining.\n'
                           '• For slab programs, "Slab target details" says how many units are left to the next level.\n'
                           '• An incentive never comes before the patient\'s need and safety.')},
            ],
        },
    ],
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
        'tour': [
            {'target': 'incentives-programs-tabs', 'text': T('خطوات الحوافز بالترتيب من «البرامج» حتى «سجل الاحتساب»؛ باقي التبويبات تعمل على البرنامج المختار.',
                                              'The incentive steps in order from «البرامج» (Programs) to «سجل الاحتساب» (Calculation log); the other tabs work on the chosen program.'),
             'more': T('امشي على التبويبات من اليمين للشمال: البرنامج ← القواعد ← الاحتساب ← التقرير ← التسويات.\n'
                       '• «قريب الصلاحية» و«عائد الاستثمار» و«اقتراحات ذكية» بتساعدك تختار أصناف الحافز وتقيس نتيجته.\n'
                       '• لو فتحت تبويب من غير ما تختار برنامج، هيقولك «اختر برنامجاً أولاً».',
                       'Go through the tabs in order: program → rules → calculate → report → settlements.\n'
                       '• "Near expiry", "ROI" and "Smart suggestions" help you choose incentive items and measure the result.\n'
                       '• If you open a tab without choosing a program, it says "Choose a program first".')},
            {'target': 'incentives-programs-new', 'text': T('«+ برنامج جديد» يفتح نموذج إنشاء برنامج حوافز.',
                                              '«+ برنامج جديد» (New program) opens the form to create an incentive program.'),
             'more': T('النموذج فيه: اسم البرنامج (إجباري)، الوصف، تاريخ البداية والنهاية (افتراضياً الشهر الحالي)، ودورة الاحتساب (أسبوعي/شهري/مخصص).\n'
                       '• لو مورد بيموّل الحافز، اكتب اسمه ونسبة مساهمته في جزء «برنامج برعاية مورد».\n'
                       '• بعد «إنشاء البرنامج» بيتختار لوحده وينقلك لـ«القواعد» عشان تضيف الأصناف.',
                       'The form has: program name (required), description, start and end date (the current month by default), and the calculation cycle (weekly/monthly/custom).\n'
                       '• If a supplier funds the incentive, enter its name and share in the "Supplier-sponsored program" part.\n'
                       '• After "Create program" it is selected automatically and you move to "Rules" to add the items.')},
            {'target': 'incentives-programs-list', 'text': T('البرامج بفترتها وعدد قواعدها وحالتها؛ الضغط على برنامج يختاره وينقلك لتبويب «القواعد».',
                                              'Programs with their period, rule count and status; clicking one selects it and moves you to «القواعد» (Rules).'),
             'more': T('كل بطاقة برنامج: الاسم والوصف والفترة وعدد القواعد، وشارة «نشط» أو «موقف».\n'
                       '• البرنامج المختار بيتلوّن، وكل التبويبات التانية بتشتغل عليه.\n'
                       '• الأحدث إنشاءً فوق.',
                       'Each program card: name, description, period, rule count, and an "Active" or "Stopped" badge.\n'
                       '• The selected program is highlighted, and every other tab works on it.\n'
                       '• The newest programs are on top.')},
            {'target': 'incentives-programs-clone', 'text': T('«نسخ» ينشئ برنامجاً جديداً من هذا البرنامج بقواعده.',
                                              '«نسخ» (Copy) creates a new program from this one with its rules.'),
             'more': T('أسرع طريقة تعمل بيها برنامج الشهر الجاي بنفس الأصناف والشروط.\n'
                       '• بيسألك عن اسم جديد (اختياري) وتاريخ البداية والنهاية — افتراضياً الشهر الجاي.\n'
                       '• البرنامج القديم ومستحقاته مبيتغيروش؛ النسخة الجديدة بتتختار على طول.',
                       'The quickest way to build next month\'s program with the same items and conditions.\n'
                       '• It asks for a new name (optional) and start and end dates — next month by default.\n'
                       '• The old program and its earnings are not touched; the new copy is selected at once.')},
            {'target': 'incentives-programs-selected', 'text': T('البرنامج المختار حالياً؛ «✕» يلغي الاختيار — يظهر بعد اختيار برنامج.',
                                              'The currently selected program; «✕» clears it — shown after a program is selected.'),
             'more': T('اسم البرنامج هنا بيأكدلك انت شغال على أنهي برنامج قبل ما تحتسب أو تعتمد.\n'
                       '• راجعه دايماً قبل «تشغيل الاحتساب» أو «اعتماد التسويات نهائياً» عشان متشتغلش على برنامج غلط.\n'
                       '• «✕» بيلغي الاختيار بس، مش بيمسح البرنامج.',
                       'The program name here confirms which program you are working on before you calculate or finalize.\n'
                       '• Always check it before "Run calculation" or "Finalize settlements" so you do not work on the wrong program.\n'
                       '• "✕" only clears the selection; it does not delete the program.')},
            {'target': 'incentives-programs-content', 'text': T('محتوى التبويب المفتوح للبرنامج المختار.',
                                              'The open tab\'s content for the selected program.'),
             'more': T('المساحة دي بتتغير حسب التبويب: قائمة البرامج، أو محرر القواعد (أصناف يدوي أو CSV، والسلاب)، أو شاشة الاحتساب، أو التقرير…\n'
                       '• في «الاحتساب» ابدأ دايماً بـ«🔍 معاينة (محاكاة)» — مبتتحفظش — وبعدين «⚡ تشغيل الاحتساب».\n'
                       '• «✅ اعتماد التسويات نهائياً» في «التقرير» بيقفل الفترة ومينفعش يترجع فيه.',
                       'This area changes with the tab: the program list, the rule editor (items manually or by CSV, and slabs), the calculation screen, the report…\n'
                       '• In "Calculate" always start with "🔍 Preview (simulation)" — it is not saved — then "⚡ Run calculation".\n'
                       '• "✅ Finalize settlements" in "Report" locks the period and cannot be undone.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
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
        'tour': [
            {'target': 'incentives-mine-refresh', 'text': T('«تحديث» يعيد تحميل تقدمك في برامج الحوافز.',
                                              '«تحديث» (Refresh) reloads your incentive progress.'),
             'more': T('بيحسب تقدمك من جديد من مبيعاتك في SOFTECH لحد النهارده — الحساب ده للعرض بس ومش بيتحفظ.\n'
                       '• لو ظهرت رسالة إن كود المندوب في SOFTECH مش محدد، كلّم المسؤول يربط كودك بحسابك.\n'
                       '• اسمك وتاريخ «حتى» مكتوبين جنب العنوان.',
                       'Recalculates your progress from your SOFTECH sales up to today — this is for display only and is not saved.\n'
                       '• If you see a message that your SOFTECH salesperson code is not set, ask the admin to link your code to your account.\n'
                       '• Your name and the "as of" date are shown beside the title.')},
            {'target': 'incentives-mine-totals', 'text': T('إجمالي المكتسب حتى الآن والمتوقع نهاية الشهر لكل البرامج — يظهر عند وجود برامج نشطة.',
                                              'Total earned so far and projected by month end across programs — shown when active programs exist.'),
             'more': T('الرقم الأول = مجموع اللي كسبته من كل البرامج النشطة لحد دلوقتي بالجنيه.\n'
                       '• التاني = المتوقع لو كمّلت بنفس معدلك لآخر الشهر.\n'
                       '• المبلغ النهائي بيتحدد بعد ما الإدارة تحتسب وتعتمد التسويات، وممكن تتضاف تسويات يدوية.',
                       'The first number = the total you have earned from all active programs so far, in EGP.\n'
                       '• The second = the projection if you keep the same pace until month end.\n'
                       '• The final amount is set after management calculates and finalizes settlements, and manual adjustments may be added.')},
            {'target': 'incentives-mine-program', 'text': T('بطاقة لكل برنامج: الفترة، المكتسب حتى الآن، وتقدم أيام الفترة.',
                                              'A card per program: period, earned so far and progress through the period\'s days.'),
             'more': T('فوق البطاقة اسم البرنامج وفترته والمكتسب منه، وشريط «تقدم الفترة» بيوضح عدّى كام يوم من كام.\n'
                       '• جوه البطاقة «أعلى الأصناف تحقيقاً» — الأصناف اللي جابتلك أكتر حافز.\n'
                       '• ركّز على أصناف البرنامج وانت بتبيع، من غير ما تقدّمها على احتياج المريض.',
                       'At the top of the card: program name, period and what you earned from it; the "Period progress" bar shows how many days have passed.\n'
                       '• Inside the card, "Top items" — the items that earned you the most.\n'
                       '• Keep the program items in mind while selling, without putting them ahead of the patient\'s need.')},
            {'target': 'incentives-mine-projection', 'text': T('المتوقع نهاية الشهر وعدد الأيام المتبقية.',
                                              'The month-end projection and the days remaining.'),
             'more': T('«المتوقع نهاية الشهر» = متوسطك اليومي لحد النهارده × أيام الفترة كلها.\n'
                       '• «يوم متبقٍ» بيقولك لسه قدامك قد إيه.\n'
                       '• لو المتوقع أقل من اللي عايزه، لسه في وقت تحسّن.',
                       '"Projected by month end" = your daily average so far × all the days of the period.\n'
                       '• "Days remaining" tells you how much time is left.\n'
                       '• If the projection is below what you want, there is still time to improve.')},
            {'target': 'incentives-mine-slabs', 'text': T('«تفاصيل مستهدفات السلاب» تعرض تقدمك نحو المستوى التالي — تظهر للبرامج ذات السلاب.',
                                              '«تفاصيل مستهدفات السلاب» (Slab target details) shows progress to the next level — for programs with slabs.'),
             'more': T('اضغطه يفتح بطاقة لكل قاعدة سلاب: الوحدات اللي بعتها، السعر الحالي، وشريط التقدم للمستوى اللي بعده.\n'
                       '• هتلاقي «تحتاج X وحدة إضافية للوصول لمعدل…»، أو «أنت في أعلى مستوى».\n'
                       '• السعر بيتطبّق على إجمالي كمية الفترة، فلما توصل مستوى أعلى كل الكمية بتاخد سعره.',
                       'Click it to open a card per slab rule: units you sold, the current rate, and a progress bar to the next level.\n'
                       '• You see "You need X more units to reach rate…", or "You are at the top level".\n'
                       '• The rate applies to the period\'s total quantity, so reaching a higher level gives the whole quantity its rate.')},
            {'target': 'incentives-mine-note', 'text': T('التوقعات تعتمد على متوسط يومي خطي وقد تختلف عن النتيجة الفعلية.',
                                              'Projections use a linear daily average and may differ from the actual result.'),
             'more': T('التوقع حساب تقريبي: بيفترض إنك هتبيع كل يوم زي متوسطك لحد دلوقتي.\n'
                       '• المرتجعات والتسويات اليدوية واعتماد الإدارة ممكن يغيّروا الرقم النهائي.\n'
                       '• الرقم الرسمي هو اللي في إيصال التسوية بعد الاعتماد.',
                       'The projection is an estimate: it assumes you will sell every day at your average so far.\n'
                       '• Returns, manual adjustments and management\'s finalizing can change the final figure.\n'
                       '• The official number is the one on the settlement receipt after finalizing.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
