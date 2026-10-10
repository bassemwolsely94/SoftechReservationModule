from . import T

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
        'updated': '2026-10-10',
    },
]
