from . import T

MODULE = {
    'key': 'batches', 'group': 'inventory', 'icon': '🧪',
    'title': T('الدفعات والصلاحية', 'Batches & expiry'),
    'summary': T(
        'متابعة تواريخ صلاحية المخزون الفعلي في كل الفروع والمخازن (بيانات يومية من SOFTECH) حتى لا نخسر أصنافاً بانتهاء صلاحيتها: '
        'قرب الانتهاء والمنتهي، تدقيق مادي للصلاحيات المسجّلة عند الشراء، أداء الموردين في الصلاحية، مراجعة كميات الشراء، '
        'نقل التشغيلات لفروع تبيعها أسرع قبل انتهائها، وقرارات الإتلاف أو المرتجع. القاعدة: الأقرب انتهاءً يُصرف أولاً (FEFO). '
        'النظام يقترح فقط؛ أي حركة مخزون فعلية تتم في SOFTECH.',
        'Track the expiry dates of actual stock in every branch and store (daily data from SOFTECH) so we do not lose items to expiry: '
        'near-expiry and expired, a physical audit of expiry dates entered at purchase, supplier expiry performance, purchase quantity review, '
        'moving batches to branches that sell them faster before they expire, and disposal or return decisions. The rule: first expiry, first out (FEFO). '
        'The system only suggests; any real stock movement happens in SOFTECH.'),
}

SCREENS = [
    {
        'key': 'batches.main',
        'routes': ['/batches'],
        'title': T('الدفعات والانتهاء', 'Batches & expiry'),
        'summary': T('سبعة تبويبات لإدارة الصلاحية من الرصد حتى القرار.', 'Seven tabs to manage expiry from monitoring to decision.'),
        'audience': T('الصيادلة والجودة والمشتريات والمشرفون.', 'Pharmacists, quality, purchasing and supervisors.'),
        'tabs': [
            {'key': 'alerts', 'title': T('🚨 قرب الانتهاء', '🚨 Near expiry'),
             'body': T('الأرصدة الصالحة التي تنتهي خلال المدة المختارة في كل الفروع، مع التصدير وإنشاء جلسة جرد للتحقق. ابدأ يومك من هنا.', 'Valid stock expiring within the chosen period in every branch, with export and a count session to verify. Start your day here.')},
            {'key': 'list', 'title': T('📦 أرصدة الصلاحية (كل الفروع)', '📦 Expiry balances (all branches)'),
             'body': T('كل الأرصدة بتواريخ صلاحيتها، مع وضع «منتهية» للأصناف التي مضت صلاحيتها وما زالت بالمخزون — منها تُنشأ مسودة قرار إتلاف/مرتجع.', 'All stock with expiry dates, with an "expired" mode for items past expiry still in stock — from there you create a disposal/return draft.')},
            {'key': 'audit', 'title': T('📅 تدقيق صلاحيات الشراء', '📅 Purchase-expiry audit'),
             'body': T('الأصناف الموجودة بالمخزون الآن التي سجّل لها موزّع رئيسي أو مصنع (في أي وقت) تاريخ صلاحية داخل الفترة المحددة، مع التكلفة والقيمة المعرّضة وعمر المخزون في الفرع — لسحبها والتحقق الفعلي على الرف. «إنشاء جلسة جرد» يُنشئ جرد صلاحية.',
                       'Items in stock now for which a main distributor or manufacturer (at any time) recorded an expiry date inside the chosen range, with cost, value at risk and stock age in the branch — to pull and physically check on the shelf. "Create count session" creates an expiry audit count.')},
            {'key': 'suppliers', 'title': T('🏭 أداء الموردين (صلاحية)', '🏭 Supplier expiry performance'),
             'body': T('جودة تواريخ الصلاحية من كل موزّع رئيسي: متوسط الصلاحية المتبقية عند الاستلام ونسبة التوريد «قصير الأجل» — ورقة تفاوض لشروط التوريد والمرتجعات.', 'The expiry quality from each main distributor: average remaining shelf life on receipt and the share of "short-dated" supply — a negotiation sheet for supply and return terms.')},
            {'key': 'reorder', 'title': T('♻️ مراجعة الشراء', '♻️ Purchase review'),
             'body': T('أصناف تُشترى قصيرة الأجل بشكل متكرر مع معدل البيع الشهري — إشارة لتقليل كمية إعادة الطلب أو التفاوض أو تغيير المصدر.', 'Items repeatedly bought short-dated, with monthly sales — a signal to reduce reorder quantity, negotiate or change source.')},
            {'key': 'rebalance', 'title': T('🔁 إنقاذ قبل الانتهاء', '🔁 Rescue before expiry'),
             'body': T('تشغيلات لن تُباع في فرعها قبل انتهائها، والفروع التي تبيع الصنف أسرع وتكفي لتصريفها (الأقدم صلاحية أولاً). الزر يُنشئ «مسودة طلب تحويل» تمر بمسار التحويلات المعتاد. ما «لا يوجد فرع يستوعبه» أو «متأخر للنقل» يحتاج خصماً أو مرتجعاً.',
                       'Batches that will not sell in their branch before expiry, and branches that sell the item faster and can absorb them (oldest expiry first). The button creates a "draft transfer request" that goes through the usual transfer flow. Lines with "no branch can absorb" or "too late to move" need a discount or a return.')},
            {'key': 'disposal', 'title': T('🗑️ إتلاف/مرتجع', '🗑️ Disposal/return'),
             'body': T('سجل قرارات الإتلاف أو المرتجع للأصناف المنتهية: مسودة ← اعتماد (مدير/جودة) ← «تم التنفيذ» بعد تطبيقها يدوياً في SOFTECH. النظام لا يخصم المخزون تلقائياً.',
                       'The log of disposal or return decisions for expired items: draft → approval (manager/quality) → "Done" after applying it manually in SOFTECH. The system never deducts stock automatically.')},
        ],
        'tips': [
            T('اقتراحات الإنقاذ تحتاج تشغيل محرك الطلب لحساب معدلات البيع.', 'Rescue suggestions need the demand engine to have run to compute sales rates.'),
            T('«عزل دفعة» يضع التشغيلة في الحجر مع سبب إلزامي (مثلاً تلف أو سحب من السوق).', '"Quarantine batch" puts a batch in quarantine with a required reason (e.g. damage or a market recall).'),
        ],
        'related': ['stockcount.sessions', 'transfers.new', 'catalog.inventory'],
        'updated': '2026-10-10',
    },
]
