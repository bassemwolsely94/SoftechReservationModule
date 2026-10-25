from . import T

# Longer explanations ("more") shared by the screen tour and the module tour.
INV_MORE_NEW = T(
    'استخدمه لما توصلك فاتورة شراء ورقية أو PDF من مورد بدل ما تكتبها بإيدك في SOFTECH.\n'
    '• بيفتح نافذة «فاتورة مورد جديدة»: الفرع (إجباري)، اسم المورد، رقم الفاتورة، التاريخ، وصورة أو PDF الفاتورة.\n'
    '• بعد الحفظ الفاتورة بتتفتح على طول، والنظام بيقرأ الصورة (OCR) ويطابق كل سطر بصنف من الكتالوج.\n'
    '• لسه مفيش أي حاجة اتكتبت في SOFTECH في الخطوة دي.',
    'Use it when a paper or PDF purchase invoice arrives from a supplier, instead of typing it into SOFTECH by hand.\n'
    '• It opens the "New supplier invoice" window: branch (required), supplier name, invoice number, date, and the invoice image or PDF.\n'
    '• After saving, the invoice opens straight away and the system reads the image (OCR) and matches each line to a catalog item.\n'
    '• Nothing is written to SOFTECH at this step.')
INV_MORE_FILTERS = T(
    'اختار فرع و/أو حالة عشان تركّز على شغلك.\n'
    '• «قيد المراجعة»: فواتير محتاجة حد يراجع سطورها.\n'
    '• «مُأكَّدة» و«فشل الترحيل»: جاهزة للمعاينة والترحيل أو محتاجة إعادة محاولة.\n'
    '• «مُرحّلة إلى ERP»: خلصت وبقت مستند في SOFTECH.',
    'Pick a branch and/or a status to focus on your work.\n'
    '• "In review": invoices whose lines need checking.\n'
    '• "Confirmed" and "Posting failed": ready for the preview and posting, or need a retry.\n'
    '• "Posted to ERP": done and now a SOFTECH document.')
INV_MORE_LIST = T(
    'كل كارت فاتورة فيه المورد والحالة ونسبة السطور المؤكدة من إجمالي السطور.\n'
    '• اضغط الكارت عشان تفتح الفاتورة في نفس الصفحة وتراجعها.\n'
    '• النسبة الواطية معناها لسه فيه سطور الصنف بتاعها محتاج تأكيد.',
    'Each invoice card shows the supplier, the status and how many lines are confirmed out of all lines.\n'
    '• Click a card to open the invoice on the same page and review it.\n'
    '• A low percentage means some lines still need their item confirmed.')
INV_MORE_ACTIONS = T(
    'الأزرار هنا بتظهر حسب حالة الفاتورة:\n'
    '• «⚠ فحص الانحرافات» يطلع تقرير بالسطور المشكوك فيها (سعر بعيد عن الكتالوج، خصم عالي، صنف مكرر…)، و«🔄 إعادة OCR» لو القراءة وحشة.\n'
    '• «✓ تأكيد الفاتورة» بيغيّر الحالة لـ «مُأكَّدة» بس — مش بيكتب في SOFTECH.\n'
    '• «🛡 فحص التحقق» ثم «⇪ ترحيل إلى ERP» بيفتح معاينة: الأخطاء بتمنع الترحيل والتحذيرات محتاجة «راجعت التحذيرات وأريد المتابعة». الترحيل للمدير والمشتريات والمشرف، ولو الفاتورة اترحّلت قبل كده مش بتتكتب تاني.',
    'The buttons here depend on the invoice status:\n'
    '• "⚠ Check deviations" lists suspicious lines (price far from the catalog, high discount, duplicated item…), and "🔄 Re-run OCR" helps when the reading is poor.\n'
    '• "✓ Confirm invoice" only changes the status to "Confirmed" — it does not write to SOFTECH.\n'
    '• "🛡 Validation check" then "⇪ Post to ERP" opens a preview: errors block posting and warnings need "I reviewed the warnings". Posting is for admin, purchasing and supervisors, and an invoice already posted is never written twice.')
INV_MORE_HEADER = T(
    'دي بيانات رأس الفاتورة زي ما اتقرت: المورد، رقم وتاريخ الفاتورة، الخصم العام (نسبة أو مبلغ) والإجمالي.\n'
    '• قارنها بالورقة الأصلية قبل التأكيد.\n'
    '• «تعديل» بيظهر بس طول ما الفاتورة لسه قابلة للتعديل (قبل التأكيد).',
    'This is the invoice header as it was read: supplier, invoice number and date, global discount (percent or amount) and total.\n'
    '• Compare it with the paper original before confirming.\n'
    '• "Edit" shows only while the invoice can still be edited (before confirming).')
INV_MORE_LINES = T(
    'كل سطر: الصنف اللي النظام طابقه، الكمية، سعر الوحدة والخصم، ودرجة ثقة القراءة.\n'
    '• السطور منخفضة الثقة أو اللي الاسم العربي والعلمي فيها أشاروا لصنفين مختلفين محتاجة انتباهك.\n'
    '• بالكيبورد: ↑↓ للتنقل، Enter يأكّد الصنف المقترح وينقلك للسطر اللي بعده، M يعرض اقتراحات المطابقة.',
    'Each line: the item the system matched, quantity, unit price and discount, and the reading confidence.\n'
    '• Lines with low confidence, or where the Arabic and scientific names point to different items, need your attention.\n'
    '• Keyboard: ↑↓ to move, Enter confirms the suggested item and moves to the next line, M shows match suggestions.')

MODULE = {
    'key': 'invoices', 'group': 'purchasing', 'icon': '🧾',
    'title': T('فواتير الموردين', 'Supplier invoices'),
    'summary': T(
        'إدخال فواتير الشراء من الموردين (ومرتجعاتها) بدل كتابتها يدوياً في SOFTECH: ارفع صورة/PDF الفاتورة ← النظام يقرأها (OCR) ويطابق كل سطر بصنف من الكتالوج ← '
        'تراجع السطور منخفضة الثقة وتؤكد الفاتورة ← معاينة الترحيل تتحقق من قواعد الحفظ في SOFTECH (أخطاء تمنع، تحذيرات تحتاج تأكيداً) ← الترحيل إلى SOFTECH '
        '(عند تفعيله) ثم التحقق أن المستند موجود فعلاً.',
        'Enter supplier purchase invoices (and returns) instead of typing them into SOFTECH: upload the invoice photo/PDF → the system reads it (OCR) and matches each line to a catalog item → '
        'review low-confidence lines and confirm the invoice → the posting preview checks SOFTECH saving rules (errors block, warnings need confirmation) → post to SOFTECH '
        '(when enabled) then verify the document really exists.'),
    'workflows': [{
        'title': T('مراحل الفاتورة', 'Invoice stages'),
        'model': 'invoices.SupplierInvoice', 'field': 'status',
        'states': [
            {'key': 'pending', 'label': T('في الانتظار', 'Pending'), 'desc': T('رُفعت ولم تُقرأ بعد.', 'Uploaded, not read yet.'), 'next': ['processing']},
            {'key': 'processing', 'label': T('جاري المعالجة', 'Processing'), 'desc': T('القراءة الآلية (OCR) والمطابقة جارية.', 'Automatic reading (OCR) and matching in progress.'), 'next': ['review']},
            {'key': 'review', 'label': T('قيد المراجعة', 'In review'), 'desc': T('راجع السطور والمطابقات والأسعار والخصومات.', 'Review lines, matches, prices and discounts.'), 'next': ['confirmed', 'rejected']},
            {'key': 'confirmed', 'label': T('مُأكَّدة', 'Confirmed'), 'desc': T('البيانات صحيحة وجاهزة لمعاينة الترحيل.', 'Data correct and ready for the posting preview.'), 'next': ['queued', 'pushing']},
            {'key': 'rejected', 'label': T('مرفوضة', 'Rejected'), 'desc': T('فاتورة خاطئة أو مكررة.', 'Wrong or duplicate invoice.')},
            {'key': 'queued', 'label': T('بانتظار الترحيل', 'Queued for posting'), 'desc': T('تنتظر الترحيل لـ SOFTECH.', 'Waiting to be posted to SOFTECH.'), 'next': ['pushing']},
            {'key': 'pushing', 'label': T('جارٍ الترحيل', 'Posting'), 'desc': T('تُكتب الآن في SOFTECH.', 'Being written to SOFTECH.'), 'next': ['finalized', 'push_failed']},
            {'key': 'finalized', 'label': T('مُرحَّلة إلى ERP', 'Posted to ERP'), 'desc': T('أصبحت مستند شراء في SOFTECH برقم مستند. «تم التحقق» يؤكد وجوده.', 'It is now a purchase document in SOFTECH with a number. "Verified" confirms it exists.')},
            {'key': 'push_failed', 'label': T('فشل الترحيل', 'Posting failed'), 'desc': T('لم يكتمل — راجع السبب ثم أعد المحاولة.', 'Did not complete — check the reason and retry.'), 'next': ['pushing']},
        ],
    }],
    'flows': [
        {
            'key': 'overview',
            'title': T('جولة في موديول فواتير الموردين', 'A tour of the Supplier invoices module'),
            'summary': T('من صورة فاتورة المورد لحد ما تبقى مستند شراء في SOFTECH: الرفع، القراءة والمطابقة، المراجعة والتأكيد، ثم المعاينة والترحيل والتحقق.',
                         'From the supplier invoice photo to a purchase document in SOFTECH: upload, reading and matching, review and confirm, then preview, posting and verification.'),
            'roles': ['admin', 'purchasing'],
            'steps': [
                {'target': 'nav-invoices', 'nav': '/invoices',
                 'text': T('«المشتريات» ← «فواتير الموردين».', '"Purchasing" → "Supplier invoices".'),
                 'more': T('هنا بتدخل فواتير الشراء اللي جاية من الموردين بدل ما تتكتب يدوي في SOFTECH.\n'
                           '• الموديول ظاهر للمدير والمشتريات.\n'
                           '• الرحلة: رفع الصورة ← قراءة ومطابقة ← مراجعة وتأكيد ← معاينة وترحيل لـ SOFTECH ← تحقق.',
                           'This is where purchase invoices from suppliers are entered instead of being typed into SOFTECH by hand.\n'
                           '• The module is shown to admin and purchasing.\n'
                           '• The journey: upload the image → reading and matching → review and confirm → preview and post to SOFTECH → verify.')},
                {'target': 'invoices-main-filters', 'route': '/invoices',
                 'text': T('ابدأ يومك بفلتر الحالة: إيه اللي مستني مراجعة وإيه اللي جاهز للترحيل.',
                           'Start your day with the status filter: what needs review and what is ready to post.'),
                 'more': INV_MORE_FILTERS},
                {'target': 'invoices-main-new', 'route': '/invoices',
                 'text': T('«+ فاتورة جديدة» هي أول خطوة لكل فاتورة.', '"+ New invoice" is the first step for every invoice.'),
                 'more': INV_MORE_NEW},
                {'target': 'invoices-main-list', 'route': '/invoices',
                 'text': T('افتح أي فاتورة من الكروت وبعدين اضغط «التالي». لو مفيش فواتير اضغط «إنهاء».',
                           'Open any invoice from the cards, then press "Next". If there are none, press "End".'),
                 'more': INV_MORE_LIST},
                {'target': 'invoices-main-header-card', 'route': '/invoices',
                 'text': T('راجع رأس الفاتورة الأول: المورد والرقم والتاريخ والخصم العام.',
                           'Check the invoice header first: supplier, number, date and global discount.'),
                 'more': INV_MORE_HEADER},
                {'target': 'invoices-main-lines', 'route': '/invoices',
                 'text': T('بعدين السطور: أكّد الصنف المطابق لكل سطر.', 'Then the lines: confirm the matched item on each line.'),
                 'more': INV_MORE_LINES},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('لما السطور تبقى سليمة: «⚠ فحص الانحرافات» ثم «✓ تأكيد الفاتورة».',
                           'When the lines are right: "⚠ Check deviations", then "✓ Confirm invoice".'),
                 'more': T('«فحص الانحرافات» بيطلع تقرير: سطور من غير صنف مطابق، سعر أو كمية صفر، خصم فوق 50%، سعر بعيد عن سعر الكتالوج، صنف مكرر، أو إجمالي مختلف عن إجمالي الفاتورة.\n'
                           '• «✓ تأكيد الفاتورة» بيحوّلها لـ «مُأكَّدة» وبيقفل تعديل السطور، ولسه مفيش حاجة في SOFTECH.\n'
                           '• لو الفاتورة غلط أو مكررة متأكدهاش.',
                           '"Check deviations" reports: lines with no matched item, zero price or quantity, discount above 50%, a price far from the catalog price, a duplicated item, or a total that differs from the invoice total.\n'
                           '• "✓ Confirm invoice" moves it to "Confirmed" and locks line editing; still nothing in SOFTECH.\n'
                           '• If the invoice is wrong or a duplicate, do not confirm it.')},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('بعد التأكيد: «🛡 فحص التحقق» و«⇪ ترحيل إلى ERP».', 'After confirming: "🛡 Validation check" and "⇪ Post to ERP".'),
                 'more': T('«فحص التحقق» بيشغّل قواعد الحفظ بتاعة SOFTECH (حد الائتمان، الأصناف المسموحة، حدود السعر، الصلاحية…) من غير ما يكتب حاجة.\n'
                           '• «ترحيل إلى ERP» بيفتح معاينة للمستند: صحّح كل الأخطاء، وعلّم «راجعت التحذيرات وأريد المتابعة»، ثم «⇪ تأكيد الترحيل».\n'
                           '• الترحيل للمدير والمشتريات والمشرف. لو الترحيل مش مفعّل بيشتغل «وضع المعاينة» بس، ولو الفاتورة مرحّلة قبل كده مش بتتكتب تاني.',
                           '"Validation check" runs SOFTECH\'s saving rules (credit limit, allowed items, price limits, expiry…) without writing anything.\n'
                           '• "Post to ERP" opens a preview of the document: fix every error, tick "I reviewed the warnings and want to continue", then "⇪ Confirm posting".\n'
                           '• Posting is for admin, purchasing and supervisors. If posting is not enabled it works in "preview mode" only, and an invoice already posted is never written twice.')},
                {'target': 'invoices-main-actions', 'route': '/invoices',
                 'text': T('بعد الترحيل: رقم المستند و«🔄 تحقق» و«↩ إنشاء مرتجع».',
                           'After posting: the document number, "🔄 Verify" and "↩ Create return".'),
                 'more': T('الفاتورة المرحّلة بيظهر عليها «✓ مُرحّلة — مستند #…» برقم مستند SOFTECH.\n'
                           '• «🔄 تحقق» بيتأكد إن المستند موجود فعلاً في SOFTECH.\n'
                           '• «↩ إنشاء مرتجع» (لفواتير الشراء) بيعمل مسودة مرتجع مورد مربوطة بنفس المستند، تعدّل كمياتها وبعدين تأكدها وترحّلها بنفس الطريقة.\n'
                           '• لو ظهر «فشل الترحيل» اقرأ السبب واضغط «↻ إعادة الترحيل».',
                           'A posted invoice shows "✓ Posted — document #…" with the SOFTECH document number.\n'
                           '• "🔄 Verify" checks the document really exists in SOFTECH.\n'
                           '• "↩ Create return" (purchase invoices) makes a supplier-return draft linked to the same document; trim its quantities, then confirm and post it the same way.\n'
                           '• If "Posting failed" shows, read the reason and press "↻ Retry posting".')},
            ],
        },
    ],
}

SCREENS = [
    {
        'key': 'invoices.main',
        'routes': ['/invoices'],
        'title': T('فواتير الموردين', 'Supplier invoices'),
        'summary': T('قائمة الفواتير بحالاتها، وإدخال فاتورة جديدة، ومراجعة سطورها وترحيلها، وإنشاء مسودة مرتجع مورد من فاتورة.',
                     'The invoice list by status, entering a new invoice, reviewing its lines and posting it, and creating a supplier-return draft from an invoice.'),
        'audience': T('المشتريات والمدير.', 'Purchasing and admins.'),
        'steps': [
            T('«فاتورة جديدة»: الفرع والمورد ونوع المستند (شراء أو مرتجع) وارفع الصورة.', '"New invoice": branch, supplier and document type (purchase or return), and upload the image.'),
            T('راجع بيانات الرأس (المورد، رقم وتاريخ الفاتورة، الخصم العام).', 'Check the header (supplier, invoice number and date, global discount).'),
            T('لكل سطر: تحقق من الصنف المطابق والكمية وسعر الوحدة والخصم. السطور ذات «ثقة استخراج OCR» المنخفضة أو «الاسم العربي والعلمي أشارا لصنفين مختلفين» تحتاج انتباهاً. «إعادة OCR» لو القراءة سيئة.',
              'For each line: check the matched item, quantity, unit price and discount. Lines with low "OCR confidence" or "Arabic and scientific names point to different items" need attention. "Re-run OCR" if the reading is poor.'),
            T('«فحص الانحرافات» ثم «تأكيد» الفاتورة.', '"Check deviations" then "Confirm" the invoice.'),
            T('«معاينة الترحيل إلى ERP»: صحّح كل الأخطاء، راجع التحذيرات وعلّم «راجعت التحذيرات»، ثم «تأكيد الترحيل».', '"Preview ERP posting": fix every error, review warnings and tick "I reviewed the warnings", then "Confirm posting".'),
        ],
        'tips': [
            T('لو ظهر «سيتغيّر كود المورد لهذا الصنف» فهذا تعارض في ربط كود المورد بالأصناف — اعتمده فقط لو متأكد.', 'If "this item\'s supplier code will change" appears, it is a supplier-code mapping conflict — approve only if you are sure.'),
            T('لو الترحيل غير مُفعّل تعمل الشاشة في «وضع المعاينة» فقط.', 'If posting is not enabled, the screen works in "preview mode" only.'),
        ],
        'related': ['purchasing.history', 'finance.reconciliation'],
        'tour': [
            {'target': 'invoices-main-new', 'text': T('«+ فاتورة جديدة»: الفرع والمورد ورقم وتاريخ الفاتورة، وارفع صورتها.',
                                              '"+ New invoice": branch, supplier, invoice number and date, and upload its image.'),
             'more': INV_MORE_NEW},
            {'target': 'invoices-main-filters', 'text': T('صفِّ الفواتير بالفرع والحالة.',
                                              'Filter invoices by branch and status.'),
             'more': INV_MORE_FILTERS},
            {'target': 'invoices-main-list', 'text': T('الفواتير مع حالتها وعدد السطور المؤكدة؛ اضغط فاتورة لفتحها.',
                                              'Invoices with status and confirmed lines; click one to open it.'),
             'more': INV_MORE_LIST},
            {'target': 'invoices-main-actions', 'text': T('داخل الفاتورة: أزرار تتغير بالحالة مثل «⚠ فحص الانحرافات» و«✓ تأكيد الفاتورة»؛ الترحيل لـ ERP بمعاينة وصلاحية.',
                                              'Inside an invoice: buttons change with status, e.g. "⚠ Check deviations" and "✓ Confirm"; ERP posting needs a preview and permission.'),
             'more': INV_MORE_ACTIONS},
            {'target': 'invoices-main-header-card', 'text': T('داخل الفاتورة: بيانات الرأس (المورد، الرقم، التاريخ، الخصم، الإجمالي) و«تعديل» لو قابلة للتعديل.',
                                              'Inside an invoice: the header (supplier, number, date, discount, total) and "Edit" when editable.'),
             'more': INV_MORE_HEADER},
            {'target': 'invoices-main-lines', 'text': T('داخل الفاتورة: سطورها؛ راجع الصنف المطابق والكمية والسعر لكل سطر.',
                                              'Inside an invoice: its lines; check the matched item, quantity and price on each.'),
             'more': INV_MORE_LINES},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
