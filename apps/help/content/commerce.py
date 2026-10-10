from . import T

MODULE = {
    'key': 'commerce', 'group': 'finance', 'icon': '🧩',
    'title': T('المستندات التجارية', 'Commercial documents'),
    'summary': T(
        'إصدار مستندات تجارية خارج نقطة البيع: عروض أسعار، فواتير بيع لعميل تجزئة/توصيل، و«شبكات توزيع» للمستشفيات والجهات متعددة الفروع '
        '(صنف بسعر موحّد وكمية لكل فرع من فروع الجهة). الأسعار شاملة الضريبة، ويُحسب جزء ضريبة 14% تلقائياً للأصناف الخاضعة. التصدير Excel. لا يكتب في SOFTECH.',
        'Issue commercial documents outside the POS: quotations, sales invoices for a retail/delivery customer, and "allocation grids" for hospitals and multi-branch clients '
        '(an item at one unit price with a quantity per client branch). Prices include VAT; the 14% VAT portion is calculated automatically for taxable items. Export to Excel. Nothing is written to SOFTECH.'),
}

SCREENS = [
    {
        'key': 'commerce.documents',
        'routes': ['/commerce'],
        'title': T('المستندات التجارية', 'Commercial documents'),
        'summary': T('قائمة المستندات (عروض أسعار، فواتير بيع، شبكات توزيع المستشفيات) بالنوع والجهة والتاريخ والحالة والبنود والإجمالي، وإنشاء مستند جديد.', 'The document list (quotations, sales invoices, hospital allocation grids) with type, client, date, status, lines and total, and creating a new document.'),
        'audience': T('المدير والمشتريات.', 'Admins and purchasing.'),
        'steps': [
            T('«مستند جديد»: اختر النوع، والجهة (أو «جهة جديدة» مثل مستشفى)، والتاريخ ← «إنشاء وفتح».', '"New document": choose the type, the client (or "new client" such as a hospital) and the date → "Create and open".'),
        ],
        'tips': [T('لو ظهر «وحدة المستندات التجارية غير مُفعَّلة» يجب تفعيلها من إعدادات الخادم.', 'If "commercial documents module is not enabled" shows, it must be enabled in the server settings.')],
        'related': ['commerce.editor'],
        'updated': '2026-10-10',
    },
    {
        'key': 'commerce.editor',
        'routes': ['/commerce/documents/:id'],
        'title': T('تحرير المستند التجاري', 'Edit a commercial document'),
        'summary': T('إضافة البنود (اسم الصنف، الكمية، سعر الوحدة شامل الضريبة، خاضع للضريبة أم لا) مع إجماليات حية: قبل الضريبة، الضريبة، وشامل الضريبة. في «شبكة التوزيع»: الصفوف أصناف بسعر موحّد والأعمدة فروع الجهة، وكل خلية كمية الفرع.',
                     'Add lines (item name, quantity, unit price including VAT, taxable or not) with live totals: before VAT, VAT and including VAT. In an "allocation grid": rows are items at one price and columns are the client\'s branches, each cell is that branch\'s quantity.'),
        'audience': T('المدير والمشتريات.', 'Admins and purchasing.'),
        'steps': [T('أضف البنود ثم «تصدير Excel».', 'Add the lines, then "Export Excel".')],
        'tips': [T('الضريبة لا تُضاف فوق السعر؛ السعر المكتوب شامل، ويُستخرج منه جزء 14% للأصناف المعلَّمة.', 'VAT is not added on top; the entered price already includes it, and the 14% portion is extracted for flagged items.')],
        'related': ['commerce.documents'],
        'updated': '2026-10-10',
    },
]
