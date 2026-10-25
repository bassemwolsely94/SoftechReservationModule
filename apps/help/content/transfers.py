from . import T

# Longer explanations ("more") shared by the screen tours and the module tours.
TR_MORE_NEW_BTN = T(
    'استخدمه لما فرعك محتاج صنف موجود في فرع تاني (لحجز عميل أو نقص عندك).\n'
    '• بيفتح صفحة «طلب تحويل مخزون جديد»: الفرعين، الأصناف بالكميات، والملاحظات.\n'
    '• الطلب نفسه مش بيحرّك مخزون — الحركة الفعلية بتحصل لما الفرع المصدر يصدر التحويل في SOFTECH.',
    'Use it when your branch needs an item that another branch has (for a customer reservation or a shortage).\n'
    '• It opens the "New stock transfer request" page: both branches, items with quantities, and notes.\n'
    '• The request itself moves no stock — the real movement happens when the supplying branch issues the transfer in SOFTECH.')
TR_MORE_TABS = T(
    'كل تبويب حالة بيعرض الطلبات اللي في المرحلة دي:\n'
    '• «مسوداتي»: لسه ما اتقدمتش، و«يحتاج تعديل»: الفرع المصدر رجّعها بملاحظات.\n'
    '• «بانتظار الموافقة»: لو فرعك هو المصدر، دي طلبات فروع تانية مستنياك.\n'
    '• «معتمد» ← «تم الإرسال للـ ERP» ← «مكتمل»، و«ملغي» للي اتلغى.',
    'Each status tab shows the requests at that stage:\n'
    '• "My drafts": not submitted yet, and "Needs revision": the supplying branch sent it back with notes.\n'
    '• "Waiting for approval": if your branch is the supplier, these are other branches waiting on you.\n'
    '• "Approved" → "Sent to ERP" → "Completed", and "Cancelled" for cancelled ones.')
TR_MORE_SEARCH = T(
    'اكتب رقم الطلب عشان توصله على طول.\n'
    '• جنبه فلاتر الفرع الطالب والفرع المصدر والتاريخ لو عايز تضيّق القائمة.',
    'Type the request number to jump straight to it.\n'
    '• Next to it are requesting-branch, supplying-branch and date filters to narrow the list.')
TR_MORE_VIEW = T(
    '• «☰ قائمة»: جدول فيه رقم الطلب والفرعين والأصناف والحالة ومين عمله.\n'
    '• «⬛ كانبان»: أعمدة حسب الحالة، تشوف فيها الشغل ماشي فين بنظرة واحدة.\n'
    'العرض بس اللي بيتغيّر — مفيش حاجة بتتحفظ.',
    '• "☰ List": a table with request number, both branches, items, status and who created it.\n'
    '• "⬛ Kanban": columns by status, to see where the work stands at a glance.\n'
    'Only the view changes — nothing is saved.')
TR_MORE_TABLE = T(
    'كل صف طلب تحويل: الرقم، الفرع الطالب، الفرع المصدر، عدد الأصناف، الحالة ومين عمله.\n'
    '• اضغط الصف عشان تفتح التفاصيل — هناك الأزرار المتاحة لك حسب فرعك والحالة.',
    'Each row is a transfer request: number, requesting branch, supplying branch, item count, status and creator.\n'
    '• Click the row to open its details — the buttons there depend on your branch and the status.')
TR_MORE_OPEN = T(
    'افتح أي طلب عشان تكمّل الجولة على صفحة تفاصيله.\n'
    '• صفحة التفاصيل فيها الفرعين والأصناف وأزرار الخطوة الجاية والمحادثة.\n'
    '• لو القائمة فاضية اضغط «إنهاء».',
    'Open any request to continue the tour on its detail page.\n'
    '• The detail page has both branches, the items, the next-step buttons and the chat.\n'
    '• If the list is empty, press "End".')
TR_MORE_BRANCHES = T(
    '• «الفرع الطالب»: الفرع اللي محتاج الصنف (فرعك عادةً).\n'
    '• «الفرع المصدر (يمتلك المخزون)»: الفرع اللي هيبعت.\n'
    'الاتنين إجباريين ومينفعش يكونوا نفس الفرع. اختار المصدر بدري عشان رصيده يظهر جنب كل صنف.',
    '• "Requesting branch": the branch that needs the item (usually yours).\n'
    '• "Supplying branch (has the stock)": the branch that will send.\n'
    'Both are required and cannot be the same branch. Pick the supplier early so its stock shows next to each item.')
TR_MORE_ITEMS = T(
    'ابحث بالاسم أو الكود أو الباركود (القارئ الضوئي شغال) وضيف كل صنف، واكتب الكمية لكل واحد (إجبارية).\n'
    '• تحت كل صنف بيظهر رصيده في الفرع المصدر وفي باقي الفروع اللي عندها منه.\n'
    '• لو ظهر «لا يوجد مخزون في أي فرع» التحويل مش هيفيد — سجّله طلب ضائع أو نقص للمشتريات.',
    'Search by name, code or barcode (the scanner works), add each item and enter its quantity (required).\n'
    '• Under each item its stock at the supplying branch and other branches that have it is shown.\n'
    '• If "no stock in any branch" appears, a transfer will not help — record lost demand or a shortage for purchasing.')
TR_MORE_NOTES = T(
    'اكتب سبب الطلب أو أي تفاصيل للفرع المصدر (مثلاً: لحجز عميل، نقص متكرر، مستعجل).\n'
    '• اختياري، بس بيساعد الفرع المصدر يقرر بسرعة.',
    'Write the reason or any details for the supplying branch (e.g. for a customer reservation, repeated shortage, urgent).\n'
    '• Optional, but it helps the supplying branch decide quickly.')
TR_MORE_SENDNOW = T(
    '• من غير العلامة: الزر بيبقى «💾 حفظ كمسودة» والطلب بيتحفظ عندك من غير ما يوصل للفرع المصدر.\n'
    '• بالعلامة: الزر بيبقى «📤 حفظ وتقديم» والطلب بيروح «بانتظار الموافقة» عند الفرع المصدر على طول.',
    '• Unticked: the button reads "💾 Save as draft" and the request is kept with you without reaching the supplying branch.\n'
    '• Ticked: the button reads "📤 Save & submit" and the request goes straight to "Waiting for approval" at the supplying branch.')
TR_MORE_SUBMIT = T(
    'بيتأكد من الفرعين والأصناف والكميات قبل الحفظ.\n'
    '• المسودة بترجعك للقائمة، و«حفظ وتقديم» بيفتح صفحة الطلب الجديد.\n'
    '• المسودة تقدر تعدّلها وتقدّمها بعدين بـ «تقديم الطلب».',
    'It checks the branches, items and quantities before saving.\n'
    '• A draft takes you back to the list, and "Save & submit" opens the new request\'s page.\n'
    '• A draft can be edited and submitted later with "Submit".')
TR_MORE_DHEADER = T(
    'رقم الطلب وحالته، وتحتهم من أنهي فرع لأنهي فرع ومين عمله وإمتى.\n'
    '• لو التحويل اتصدر في SOFTECH بيظهر زر «🚛 قيد النقل ← رقم المستند» يفتح الشحنة في شاشة «قيد النقل».',
    'The request number and status, with from which branch to which, who created it and when.\n'
    '• Once the transfer is issued in SOFTECH a "🚛 In transit ← document number" button opens the shipment on the "In transit" screen.')
TR_MORE_DDETAILS = T(
    'الفرع الطالب والمصدر، الحالة، مين أنشأه ومين راجعه، ومرجع ERP لو اتكتب.\n'
    '• تحته قسم «مطابقة مستند ERP» بيقولك المستند في SOFTECH مطابق ولا جزئي ولا مش موجود.',
    'Requesting and supplying branch, status, who created and who reviewed it, and the ERP reference if entered.\n'
    '• Below it the "ERP document match" section tells you whether the SOFTECH document is matched, partial or missing.')
TR_MORE_DITEMS = T(
    'الأصناف بالكمية المطلوبة، والمعتمدة بعد الموافقة، والمستلمة بعد تأكيد الاستلام.\n'
    '• قارن المعتمد بالمستلم — أي فرق محتاج متابعة بين الفرعين.',
    'The items with the requested quantity, the approved quantity after approval, and the received quantity after receipt is confirmed.\n'
    '• Compare approved with received — any gap needs follow-up between the branches.')
TR_MORE_DACTIONS = T(
    '«طباعة» و«واتساب» لمشاركة الطلب، وبعدهم أزرار الخطوة الجاية — بتظهر بس اللي مسموح لك حسب فرعك والحالة:\n'
    '• الفرع الطالب: «تقديم الطلب»، «إلغاء الطلب» (قبل الاعتماد)، و«🏁 تأكيد الاستلام».\n'
    '• الفرع المصدر: «اعتماد»، «رفض» بسبب، «✏️ طلب تعديل»، «🚀 إرسال للـ ERP» بعد إصدار التحويل في SOFTECH، و«🚚 تسجيل الإرسال» باسم المندوب.\n'
    '«إرسال للـ ERP» بيسجّل الحالة والمرجع هنا بس — مش بيكتب في SOFTECH.',
    '"Print" and "WhatsApp" to share the request, then the next-step buttons — only those allowed for your branch and the status show:\n'
    '• Requesting branch: "Submit", "Cancel request" (before approval), and "🏁 Confirm receipt".\n'
    '• Supplying branch: "Approve", "Reject" with a reason, "✏️ Request changes", "🚀 Send to ERP" after issuing the transfer in SOFTECH, and "🚚 Record dispatch" with the courier name.\n'
    '"Send to ERP" only records the status and reference here — it does not write to SOFTECH.')
TR_MORE_APPROVE = T(
    'بيفتح نافذة «✅ اعتماد الطلب» فيها كل صنف بالكمية المطلوبة وخانة للكمية المعتمدة (ممكن جزئي).\n'
    '• «تأكيد الاعتماد» بيحوّل الطلب لـ «معتمد» — ومش بيحجز ولا يحرّك مخزون.\n'
    '• بعدها أصدر التحويل في SOFTECH واضغط «🚀 إرسال للـ ERP». متعتمدش أكتر من الموجود فعلاً عندك.',
    'Opens the "✅ Approve request" window with each item\'s requested quantity and a box for the approved quantity (partial allowed).\n'
    '• "Confirm approval" moves the request to "Approved" — it does not reserve or move stock.\n'
    '• Then issue the transfer in SOFTECH and press "🚀 Send to ERP". Do not approve more than you really have.')
TR_MORE_CHATTER = T(
    'محادثة بين الفرعين على نفس الطلب: رسائل، ومرفقات، ورسائل صوتية.\n'
    '• استخدمها بدل التليفون عشان كل حاجة تفضل متسجّلة على الطلب.',
    'A chat between the two branches on the request: messages, attachments and voice notes.\n'
    '• Use it instead of the phone so everything stays recorded on the request.')
TT_MORE_TABS = T(
    'الشريط ده بينقلك بين نصّين التحويل:\n'
    '• «🔀 طلبات التحويل»: الطلب والموافقة جوه النظام.\n'
    '• «🚛 قيد النقل»: الشحنات اللي اتصدرت فعلاً من SOFTECH (مستند 125) ولسه ما اتستلمتش.',
    'This bar switches between the two halves of a transfer:\n'
    '• "🔀 Transfer requests": the request and approval inside the system.\n'
    '• "🚛 In transit": shipments actually issued in SOFTECH (doc 125) and not received yet.')
TT_MORE_KPIS = T(
    '• «قيد النقل» وقيمتها، و«متوسط أيام النقل».\n'
    '• «حرج / طارئ»: الشحنات القديمة اللي محتاجة تدخّل.\n'
    '• «تنتهي مهلة الإلغاء» خلال 24 ساعة، و«تم الاستلام/الإصدار اليوم».\n'
    '• «تباين مع ERP»: شحنات الصرف (125) فيها مختلف عن الاستلام (25).',
    '• "In transit" and its value, and "Average days in transit".\n'
    '• "Critical / urgent": old shipments that need action.\n'
    '• "Cancellation window ending" within 24 hours, and "Received/issued today".\n'
    '• "ERP mismatch": shipments whose issue (125) differs from the receipt (25).')
TT_MORE_FILTERS = T(
    'صفّي بالأولوية (طازج ← مراقبة ← متابعة ← طارئ ← حرج حسب عمر الشحنة)، والحالة، وفرع المصدر، وفرع المستلم، وعدد الأيام.\n'
    '• ابدأ دايماً بالحرج والطارئ.',
    'Filter by priority (fresh → watch → follow-up → urgent → critical, by shipment age), status, supplying branch, receiving branch and days.\n'
    '• Always start with critical and urgent.')
TT_MORE_AWAITING = T(
    'بيعرض الشحنات اللي اتسجّل استلامها هنا ولسه مستند الاستلام (25) ما ظهرش في SOFTECH.\n'
    '• دي اللي لازم الفرع المستلم يسجّل استلامها في SOFTECH.\n'
    '• لو فضلت كده أكتر من عدد الأيام في الإعدادات (افتراضي 3) بيوصل تنبيه يومي. اضغطه تاني عشان ترجع للعرض العادي.',
    'Shows shipments received here whose receipt document (25) has not appeared in SOFTECH yet.\n'
    '• These are the ones the receiving branch must still receive in SOFTECH.\n'
    '• If they stay like that longer than the days set in settings (default 3), a daily alert is sent. Press it again to return to the normal view.')
TT_MORE_GRID = T(
    'كل صف شحنة: رقم المستند، الفرعين، العمر، الأولوية بلون على الجنب، والقيمة — الأقدم فوق.\n'
    '• اضغط الصف عشان تفتح لوحة تفاصيلها، أو علّم أكتر من شحنة لورقة تجميع موحدة.\n'
    '• تقدر ترتّب بأي عمود بالضغط على عنوانه.',
    'Each row is a shipment: document number, both branches, age, priority colour on the side, and value — oldest on top.\n'
    '• Click a row to open its detail panel, or tick several shipments for one combined picking sheet.\n'
    '• Click a column header to sort by it.')
TT_MORE_SCORECARD = T(
    'بيفتح «بطاقة مساءلة الفروع»: أداء كل فرع في استلام التحويلات والمخزون العائم (المصروف ولسه ما اتستلمش).\n'
    '• تختار الفترة (30 أو 90 أو 180 يوم أو سنة). للعرض بس.',
    'Opens the "Branch accountability card": each branch\'s transfer-receiving performance and floating stock (issued but not yet received).\n'
    '• Choose the period (30, 90, 180 days or a year). View only.')
TT_MORE_PICK = T(
    'بينزّل ورقة Excel للفرع المصدر فيها أصناف الشحنة مرتّبة بمسار السير في المخزن (حسب «مناطق التجميع»).\n'
    '• بيتقفل لحد ما بيانات الأصناف توصل من المزامنة.',
    'Downloads an Excel sheet for the supplying branch with the shipment items in warehouse walking order (per "Picking zones").\n'
    '• Disabled until the item data arrives from the sync.')
TT_MORE_STOCK = T(
    'بينزّل ورقة Excel للفرع المستلم بالأصناف مرتّبة حسب رفوفه، عشان الترصيص يبقى أسرع.\n'
    '• الترتيب جاي من إعداد «ترصيص» في «مناطق التجميع».',
    'Downloads an Excel sheet for the receiving branch with the items in its shelf order, so stocking is faster.\n'
    '• The order comes from the "Stocking" setup in "Picking zones".')
TT_MORE_DTABS = T(
    '• «الأصناف»: الكميات والصلاحية والتشغيلات، وتحذير FEFO للأصناف قريبة الانتهاء.\n'
    '• «مطابقة 125↔25»: بتظهر بعد الاستلام في SOFTECH وتقارن الصرف بالاستلام.\n'
    '• «الملاحظات» و«السجل»: ملاحظات الفرعين وكل اللي حصل على الشحنة.',
    '• "Items": quantities, expiry and batches, with a FEFO warning for near-expiry items.\n'
    '• "Reconcile 125↔25": appears after receipt in SOFTECH and compares issue with receipt.\n'
    '• "Notes" and "Timeline": both branches\' notes and everything that happened to the shipment.')
TT_MORE_DITEMS = T(
    'أصناف الشحنة بالكمية والصلاحية والتشغيلة والتكلفة.\n'
    '• لو فيه «🌡️ تحذير FEFO» الأصناف دي صلاحيتها قريبة — رصّها واصرفها الأول.\n'
    '• عدّ الكرتونة على القائمة دي وانت بتستلم.',
    'The shipment items with quantity, expiry, batch and cost.\n'
    '• A "🌡️ FEFO warning" means those items expire soon — shelve and sell them first.\n'
    '• Count the carton against this list while receiving.')
TT_MORE_NOTES = T(
    'اكتب الملاحظة واضغط «إرسال» — بتظهر للفرعين في تبويب الملاحظات باسمك ووقتها.\n'
    '• للنقص أو الكسر أو التأخير أو مكالمة مع الفرع التاني. ملاحظة داخلية — مش بتروح SOFTECH.',
    'Write the note and press "Send" — it shows to both branches in the Notes tab with your name and time.\n'
    '• For missing items, breakage, delays or a call with the other branch. An internal note — it does not go to SOFTECH.')
TT_MORE_RECEIVED = T(
    'للفرع المستلم (أو المدير والمشتريات): بيسجّل إن الشحنة وصلت — هنا بس.\n'
    '• مش بيكتب في SOFTECH: الشحنة بتفضل «⏳ مستلم محلياً — في انتظار تأكيد SOFTECH» لحد ما مستند الاستلام (25) يتسجّل هناك.\n'
    '• بعدها المزامنة بتطابق الكميات، ولو فيه فرق بيظهر «تباين مع ERP». للحالات الاستثنائية فيه «🔒 إغلاق قسري» بسبب مكتوب (10 أحرف على الأقل).',
    'For the receiving branch (or admin and purchasing): records that the shipment arrived — here only.\n'
    '• It does not write to SOFTECH: the shipment stays "⏳ Received locally — awaiting SOFTECH" until the receipt document (25) is recorded there.\n'
    '• The sync then reconciles quantities, and a difference shows as "ERP mismatch". For exceptions there is "🔒 Force close" with a written reason (at least 10 characters).')
PZ_MORE_PURPOSE = T(
    '• «🚚 تجميع — مخزن المصدر»: ترتيب الأصناف في ورقة التجميع حسب مسار السير في المخزن اللي بيصرف.\n'
    '• «🗄️ ترصيص — أرفف الفرع»: ترتيب ورقة الترصيص للفرع المستلم، وبيُستخدم كمان في أوراق الجرد.\n'
    'كل غرض ليه مناطق وقواعد لوحده.',
    '• "🚚 Picking — source store": item order on the picking sheet by the walking path of the issuing store.\n'
    '• "🗄️ Stocking — branch shelves": order of the receiving branch\'s stocking sheet, also used on stock-count sheets.\n'
    'Each purpose has its own zones and rules.')
PZ_MORE_LOCATION = T(
    'كل مخزن أو فرع ممكن يبقى له إعداده الخاص؛ اللي ملوش إعداد بيمشي على «الإعداد الافتراضي».\n'
    '• لو اخترت موقع ملوش إعداد، بيظهر زر «📋 نسخ الإعداد المطبق حالياً كنقطة بداية» تبدأ منه وتعدّل.',
    'Each store or branch can have its own setup; one without a setup follows the "Default setup".\n'
    '• If you pick a location without a setup, a "📋 Copy the setup currently applied as a starting point" button appears so you can start from it and edit.')
PZ_MORE_TABS = T(
    '• «المناطق»: الممرات والرفوف بترتيب المسار.\n'
    '• «القواعد»: بتحط الصنف في منطقة بكلمات في الاسم أو أعمدة الكتالوج — أول قاعدة تطابق تكسب.\n'
    '• «غير مصنف»: أصناف ما طابقتش أي قاعدة.\n'
    '• «تخصيصات الأصناف»: صنف معيّن في منطقة يدوي، وبيتغلب على كل القواعد.',
    '• "Zones": aisles and shelves in path order.\n'
    '• "Rules": put an item in a zone by words in its name or catalog columns — the first matching rule wins.\n'
    '• "Uncategorized": items that matched no rule.\n'
    '• "Item assignments": a specific item placed in a zone by hand, beating all rules.')
PZ_MORE_SETTINGS = T(
    '• «حد سعر الغوالي (ج.م)»: عام لكل المخازن؛ الصنف بسعر أعلى أو يساويه بيروح منطقة الغوالي.\n'
    '• الأدوار الخاصة: أنهي منطقة هي «غوالي» وأنهي «ثلاجة» وأنهي «غير مصنف».\n'
    '• ترتيب التصنيف: تخصيص يدوي ← ثلاجة ← حد الغوالي ← القواعد ← غير مصنف. التعديل للإدارة والمشتريات.',
    '• "High-value price threshold (EGP)": global for all stores; items priced at or above it go to the high-value zone.\n'
    '• Special roles: which zone is "high-value", which is "fridge" and which is "uncategorized".\n'
    '• Classification order: manual assignment → fridge → high-value threshold → rules → uncategorized. Editing is for admin and purchasing.')
PZ_MORE_ZONES = T(
    'كل صف منطقة: ترتيب المسار، الاسم، الموقع/الرف، الأدوار الخاصة، عدد القواعد والتخصيصات، والتفعيل.\n'
    '• الرقم الأصغر بيتجمّع الأول — رتّبهم زي ما الموظف بيمشي فعلاً في المخزن.',
    'Each zone row: path order, name, location/shelf, special roles, number of rules and assignments, and on/off.\n'
    '• The lowest number is picked first — order them the way staff actually walk the store.')
TM_MORE_NEW = T(
    'بيفتح «طلب تحويل جديد» على الموبايل: الفرعين، الأصناف بالكميات، والملاحظات.\n'
    '• في الآخر تختار «حفظ كمسودة» أو «✅ حفظ وتقديم».',
    'Opens "New transfer request" on the phone: both branches, items with quantities, and notes.\n'
    '• At the end choose "Save as draft" or "✅ Save & submit".')
TM_MORE_FILTERS = T(
    'شرائح الحالة: «بانتظار الموافقة» (الافتراضي)، الكل، مسودة، معتمد، يحتاج تعديل، أُرسل للـ ERP، مكتمل، مرفوض.\n'
    '• لو فرعك مصدر، «بانتظار الموافقة» هي اللي مستنياك.',
    'Status chips: "Waiting for approval" (the default), all, draft, approved, needs revision, sent to ERP, completed, rejected.\n'
    '• If your branch supplies, "Waiting for approval" is what is waiting on you.')
TM_MORE_CARD = T(
    'الكارت فيه رقم الطلب، ومن أنهي فرع لأنهي فرع، والحالة.\n'
    '• اضغطه يفتح التفاصيل والإجراءات المتاحة لك.',
    'The card shows the request number, from which branch to which, and the status.\n'
    '• Tap it to open the details and the actions available to you.')

MODULE = {
    'key': 'transfers', 'group': 'operations', 'icon': '🔀',
    'title': T('التحويلات بين الفروع', 'Inter-branch transfers'),
    'summary': T(
        'التحويل له نصفان مرتبطان:\n'
        '1) «طلبات التحويل»: فرع يحتاج صنفاً يطلبه من فرع آخر (الفرع المصدر)، والفرع المصدر يعتمد أو يرفض أو يطلب تعديلاً، '
        'ثم يُصدر التحويل في SOFTECH. هذا النظام لا يحرّك المخزون بنفسه — الحركة الفعلية تتم في SOFTECH.\n'
        '2) «قيد النقل»: مستندات التحويل الصادرة فعلاً من SOFTECH (مستند 125) التي لم تُستلم بعد في الفرع المستلم (مستند 25)، '
        'مع أولوية حسب عمر الشحنة، ومطابقة الصرف بالاستلام، وأوراق التجميع والترصيص.',
        'A transfer has two linked halves:\n'
        '1) "Transfer requests": a branch that needs an item requests it from another branch (the supplying branch), which approves, '
        'rejects or asks for changes, then the transfer is issued in SOFTECH. This system never moves stock itself — the actual '
        'movement happens in SOFTECH.\n'
        '2) "In transit": transfer documents actually issued in SOFTECH (doc 125) that the receiving branch has not received yet (doc 25), '
        'with priority by shipment age, issue-vs-receipt reconciliation, and picking and stocking sheets.'),
    'workflows': [{
        'title': T('مراحل طلب التحويل', 'Transfer request stages'),
        'model': 'transfers.TransferRequest', 'field': 'status',
        'intro': T('الفرع الطالب يُنشئ ويقدّم ويلغي؛ الفرع المصدر (أو المشرف) يعتمد ويرفض ويطلب التعديل ويُرسل للـ ERP.',
                   'The requesting branch creates, submits and cancels; the supplying branch (or a supervisor) approves, rejects, asks for changes and sends to ERP.'),
        'states': [
            {'key': 'draft', 'label': T('مسودة', 'Draft'),
             'desc': T('الطلب محفوظ ولم يُقدَّم. يمكن تعديل الأصناف. «تقديم الطلب» يرسله للفرع المصدر.',
                       'Saved but not submitted. Items can still change. "Submit" sends it to the supplying branch.'),
             'next': ['pending', 'cancelled']},
            {'key': 'pending', 'label': T('بانتظار الموافقة', 'Waiting for approval'),
             'desc': T('عند الفرع المصدر ليراجعه: يعتمد (كلياً أو كمية جزئية)، أو يرفض بسبب، أو يطلب تعديلاً.',
                       'With the supplying branch to review: approve (fully or a partial quantity), reject with a reason, or ask for changes.'),
             'next': ['approved', 'rejected', 'needs_revision', 'cancelled']},
            {'key': 'needs_revision', 'label': T('يحتاج تعديل', 'Needs revision'),
             'desc': T('الفرع المصدر طلب تعديلاً (اقرأ ملاحظاته). عدّل ثم قدّم مرة أخرى.',
                       'The supplying branch asked for a change (read its notes). Edit and submit again.'),
             'next': ['pending', 'cancelled']},
            {'key': 'approved', 'label': T('معتمد', 'Approved'),
             'desc': T('تمت الموافقة بالكميات المعتمدة. المطلوب الآن: إصدار التحويل في SOFTECH ثم «إرسال للـ ERP» بمرجع المستند.',
                       'Approved with the approved quantities. Now: issue the transfer in SOFTECH, then "Send to ERP" with the document reference.'),
             'next': ['sent_to_erp']},
            {'key': 'sent_to_erp', 'label': T('تم الإرسال للـ ERP', 'Sent to ERP'),
             'desc': T('أُصدر في SOFTECH وهو في الطريق. النظام يتحقق تلقائياً كل 30 دقيقة من مستند ERP. الفرع الطالب «يؤكد الاستلام» بالكميات المستلمة فعلاً.',
                       'Issued in SOFTECH and on its way. The system checks the ERP document every 30 minutes. The requesting branch "confirms receipt" with the quantities actually received.'),
             'next': ['completed']},
            {'key': 'completed', 'label': T('مكتمل', 'Completed'), 'desc': T('تم الاستلام وأُغلق الطلب.', 'Received and closed.')},
            {'key': 'rejected', 'label': T('مرفوض', 'Rejected'), 'desc': T('رفضه الفرع المصدر مع ذكر السبب. مرحلة نهائية.', 'Rejected by the supplying branch with a reason. Final.')},
            {'key': 'cancelled', 'label': T('ملغي', 'Cancelled'), 'desc': T('ألغاه الفرع الطالب قبل الاعتماد. مرحلة نهائية.', 'Cancelled by the requesting branch before approval. Final.')},
        ],
    }],
    'flows': [
        {
            'key': 'lifecycle',
            'title': T('دورة طلب التحويل', 'A transfer request, start to finish'),
            'summary': T('من القائمة لطلب جديد، وبعدين الموافقة والمتابعة في صفحة التفاصيل.',
                         'From the menu to a new request, then approval and follow-up on the detail page.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor'],
            'steps': [
                {'target': 'nav-transfers', 'nav': '/transfers',
                 'text': T('طلبات التحويل من القائمة: «العمليات» ← «طلبات التحويل».',
                           'Transfer requests from the menu: "Operations" → "Transfer requests".'),
             'more': T('هنا الفرع اللي محتاج صنف بيطلبه من فرع تاني، والفرع التاني بيعتمد أو يرفض.\n'
                           '• الطلب هنا مش بيحرّك مخزون — الحركة بتتعمل في SOFTECH، وبعد الإصدار الشحنة بتظهر في «قيد النقل».\n'
                           '• المسار: مسودة ← بانتظار الموافقة ← معتمد ← تم الإرسال للـ ERP ← مكتمل.',
                           'Here a branch that needs an item requests it from another branch, which approves or rejects.\n'
                           '• The request moves no stock — the movement is done in SOFTECH, and once issued the shipment shows under "In transit".\n'
                           '• The path: draft → waiting for approval → approved → sent to ERP → completed.')},
                {'target': 'transfers-list-tabs', 'route': '/transfers',
                 'text': T('تبويبات الحالة: مسودة ← بانتظار الموافقة ← موافق عليه ← اتبعت لـ SOFTECH.',
                           'Status tabs: draft → waiting for approval → approved → sent to SOFTECH.'),
             'more': TR_MORE_TABS},
                {'target': 'transfers-list-new', 'route': '/transfers', 'wait': '/transfers/new',
                 'text': T('اضغط «+ طلب تحويل جديد».',
                           'Click "+ New transfer request".'),
             'more': TR_MORE_NEW_BTN},
                {'target': 'transfers-new-branches', 'route': '/transfers/new',
                 'text': T('الفرع الطالب والفرع المصدر.',
                           'The requesting and supplying branches.'),
             'more': TR_MORE_BRANCHES},
                {'target': 'transfers-new-items', 'route': '/transfers/new',
                 'text': T('الأصناف والكميات.',
                           'The items and quantities.'),
             'more': TR_MORE_ITEMS},
                {'target': 'transfers-new-send-now', 'route': '/transfers/new',
                 'text': T('علّم هنا عشان يتقدّم على طول بدل المسودة.',
                           'Tick this to submit right away instead of a draft.'),
             'more': TR_MORE_SENDNOW},
                {'target': 'transfers-new-submit', 'route': '/transfers/new',
                 'text': T('حفظ أو «حفظ وتقديم». (في الجولة مش هنحفظ.)',
                           'Save, or "Save & submit". (In this tour we will not save.)'),
             'more': TR_MORE_SUBMIT},
                {'target': 'transfers-list-table', 'route': '/transfers', 'wait': '/transfers/:id',
                 'text': T('افتح أي طلب عشان نشوف الموافقة والمتابعة. لو القائمة فاضية اضغط «إنهاء».',
                           'Open any request to see approval and follow-up. If the list is empty, press "End".'),
             'more': TR_MORE_OPEN},
                {'target': 'transfers-detail-header', 'route': '/transfers/:id',
                 'text': T('رقم الطلب وحالته.',
                           'The request number and status.'),
             'more': TR_MORE_DHEADER},
                {'target': 'transfers-detail-approve', 'route': '/transfers/:id',
                 'text': T('الفرع المصدر (أو المشرف) يضغط «اعتماد» — حسب الصلاحية.',
                           'The supplying branch (or a supervisor) presses "Approve" — depending on permission.'),
             'more': TR_MORE_APPROVE},
                {'target': 'transfers-detail-chatter', 'route': '/transfers/:id',
                 'text': T('التواصل بين الفرعين على نفس الطلب.',
                           'Communication between the two branches on the request.'),
             'more': TR_MORE_CHATTER},
            ],
        },
        {
            'key': 'mobile',
            'title': T('طلب التحويل من الموبايل', 'A transfer request on mobile'),
            'summary': T('طلب صنف من فرع تاني ومتابعته من الموبايل.',
                         'Requesting an item from another branch and following it on mobile.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'salesperson', 'supervisor'],
            'mobile': True,
            'steps': [
                {'target': 'mshell-tabs',
                 'text': T('الشاشات في الشريط اللي تحت. اللي مش ظاهر تلاقيه في «المزيد».',
                           'Screens are in the bottom bar. Anything not shown is under "More".'),
             'more': T('شاشات الموبايل في الشريط اللي تحت؛ لو «التحويلات» مش ظاهرة هتلاقيها في «المزيد».\n'
                           '• من الموبايل تقدر تطلب وتعتمد وتتابع من غير كمبيوتر.',
                           'Mobile screens are in the bottom bar; if "Transfers" is not shown, it is under "More".\n'
                           '• On the phone you can request, approve and follow up without a computer.')},
                {'target': 'mnav-transfers',
                 'text': T('«التحويلات».',
                           '"Transfers".'),
             'more': T('بيفتح قائمة طلبات التحويل على الموبايل، وأول ما تفتح بتعرض «بانتظار الموافقة».',
                           'Opens the transfer requests list on the phone; it opens on "Waiting for approval".')},
                {'target': 'transfers-mobile-list-filters', 'route': '/m/transfers',
                 'text': T('فلتر الحالة.',
                           'Status filter.'),
             'more': TM_MORE_FILTERS},
                {'target': 'transfers-mobile-list-new', 'route': '/m/transfers', 'wait': '/m/transfers/new',
                 'text': T('زر «+» لطلب جديد.',
                           'The "+" button for a new request.'),
             'more': TM_MORE_NEW},
                {'target': 'transfers-mnew-branches', 'route': '/m/transfers/new',
                 'text': T('الفرع الطالب والمصدر.',
                           'The requesting and supplying branches.'),
             'more': T('«الفرع الطالب» (فرعك، وبعض الأدوار تقدر تغيّره) و«الفرع المصدر» اللي عنده المخزون.\n'
                           '• الاتنين إجباريين ولازم يختلفوا.',
                           '"Requesting branch" (yours; some roles can change it) and the "Supplying branch" that has the stock.\n'
                           '• Both are required and must differ.')},
                {'target': 'transfers-mnew-items', 'route': '/m/transfers/new',
                 'text': T('الأصناف والكميات.',
                           'The items and quantities.'),
             'more': T('ابحث عن الصنف أو امسح الباركود وضيفه، وعدّل الكمية (بتبدأ بـ 1).\n'
                           '• تقدر تضيف كذا صنف في نفس الطلب، وتشيل أي صنف قبل الحفظ.',
                           'Search or scan the item and add it, then adjust the quantity (it starts at 1).\n'
                           '• You can add several items to one request and remove any before saving.')},
                {'target': 'transfers-mnew-submit', 'route': '/m/transfers/new',
                 'text': T('«حفظ كمسودة» أو «حفظ وتقديم». (في الجولة مش هنحفظ.)',
                           '"Save as draft" or "Save & submit". (In this tour we will not save.)'),
             'more': T('• «حفظ كمسودة»: بيتحفظ عندك ولسه ما وصلش للفرع المصدر.\n'
                           '• «✅ حفظ وتقديم»: بيتحفظ ويتقدّم «بانتظار الموافقة».\n'
                           'في الحالتين بيفتح صفحة الطلب؛ ولو التقديم فشل تقدر تقدّمه من هناك.',
                           '• "Save as draft": kept with you, not yet sent to the supplying branch.\n'
                           '• "✅ Save & submit": saved and submitted as "Waiting for approval".\n'
                           'Either way the request page opens; if submitting fails you can submit from there.')},
                {'target': 'transfers-mobile-list-card', 'route': '/m/transfers', 'wait': '/m/transfers/:id',
                 'text': T('افتح أي طلب. لو القائمة فاضية اضغط «إنهاء».',
                           'Open any request. If the list is empty, press "End".'),
             'more': TM_MORE_CARD},
                {'target': 'transfers-mdetail-header', 'route': '/m/transfers/:id',
                 'text': T('رقم الطلب وحالته والفروع.',
                           'The request number, status and branches.'),
             'more': T('رقم الطلب وحالته والفرعين.\n'
                           '• تحته الأصناف بالكميات، والمحادثة مع الفرع التاني.',
                           'The request number, status and both branches.\n'
                           '• Below it the items with quantities, and the chat with the other branch.')},
                {'target': 'transfers-mdetail-actions', 'route': '/m/transfers/:id',
                 'text': T('الإجراءات المتاحة لك (اعتماد، رفض…) حسب صلاحيتك.',
                           'The actions available to you (approve, reject…) per your permission.'),
             'more': T('الأزرار هنا جاية من السيرفر حسب فرعك والحالة: تقديم للموافقة، اعتماد، رفض، طلب تعديل، إرسال للـ ERP، تسجيل الإرسال، إغلاق الطلب، إلغاء.\n'
                           '• الرفض وطلب التعديل واسم المندوب محتاجين تكتب سبب/اسم، وكل إجراء بيتأكد قبل التنفيذ.\n'
                           '• الاعتماد من الموبايل بيعتمد الكميات المطلوبة كاملة؛ للاعتماد الجزئي استخدم الكمبيوتر.',
                           'The buttons here come from the server per your branch and the status: submit, approve, reject, request changes, send to ERP, record dispatch, close request, cancel.\n'
                           '• Reject, request changes and the courier name need a reason/name, and every action asks for confirmation.\n'
                           '• Approving on the phone approves the full requested quantities; for a partial approval use the desktop.')},
            ],
        },
        {
            'key': 'receiving',
            'title': T('التحويلات قيد النقل ← الاستلام', 'Transfers in transit → receiving'),
            'summary': T('الشحنات اللي اتصرفت من SOFTECH ولسه ما اتستلمتش: التجميع والترصيص، والملاحظات، ومتابعة الاستلام.',
                         'Shipments issued in SOFTECH but not yet received: picking and stocking sheets, notes, and following the receipt.'),
            'roles': ['admin', 'call_center', 'pharmacist', 'salesperson', 'purchasing', 'supervisor', 'viewer', 'quality_manager'],
            'steps': [
                {'target': 'nav-transits', 'nav': '/transits',
                 'text': T('«العمليات» ← «التحويلات قيد النقل».',
                           '"Operations" → "Transfers in transit".'),
             'more': T('«قيد النقل» هي النص التاني من التحويل: الشحنات اللي الفرع المصدر أصدرها فعلاً في SOFTECH (مستند 125).\n'
                           '• بتفضل هنا لحد ما الفرع المستلم يستلمها في SOFTECH (مستند 25).\n'
                           '• منها بتطلع أوراق التجميع والترصيص وبتتابع الاستلام والفروق.',
                           '"In transit" is the second half of a transfer: shipments the supplying branch actually issued in SOFTECH (doc 125).\n'
                           '• They stay here until the receiving branch receives them in SOFTECH (doc 25).\n'
                           '• From here come the picking and stocking sheets, and you follow receipt and differences.')},
                {'target': 'transfers-transits-kpis', 'route': '/transits',
                 'text': T('ملخص الشحنات قيد النقل.',
                           'A summary of shipments in transit.'),
             'more': TT_MORE_KPIS},
                {'target': 'transfers-transits-filters', 'route': '/transits',
                 'text': T('فلتر الأولوية والفرع.',
                           'Filter by priority and branch.'),
             'more': TT_MORE_FILTERS},
                {'target': 'transfers-transits-row', 'route': '/transits',
                 'text': T('اضغط على شحنة تفتح تفاصيلها، وبعدين «التالي». لو مفيش شحنات اضغط «إنهاء».',
                           'Click a shipment to open its details, then "Next". If there are none, press "End".'),
             'more': T('اضغط الشحنة عشان تفتح لوحة تفاصيلها على نفس الصفحة، وبعدين «التالي».\n'
                           '• اللون على جنب الصف هو الأولوية حسب عمر الشحنة.\n'
                           '• لو مفيش شحنات اضغط «إنهاء».',
                           'Click the shipment to open its detail panel on the same page, then "Next".\n'
                           '• The colour on the row side is the priority by shipment age.\n'
                           '• If there are no shipments, press "End".')},
                {'target': 'transfers-transit-print', 'route': '/transits',
                 'text': T('«ورقة التجميع» للفرع المصدر — مرتّبة بمسار المخزن.',
                           '"Picking sheet" for the supplying branch — in warehouse walking order.'),
             'more': TT_MORE_PICK},
                {'target': 'transfers-transit-print-stocking', 'route': '/transits',
                 'text': T('«ورقة الترصيص» للفرع المستلم — مرتّبة حسب رفوفه.',
                           '"Stocking sheet" for the receiving branch — in its shelf order.'),
             'more': TT_MORE_STOCK},
                {'target': 'transfers-transit-tabs', 'route': '/transits',
                 'text': T('الأصناف، مطابقة الصرف مع الاستلام (125↔25)، الملاحظات، والسجل.',
                           'Items, issue-vs-receipt reconciliation (125↔25), notes and the log.'),
             'more': TT_MORE_DTABS},
                {'target': 'transfers-transit-items', 'route': '/transits',
                 'text': T('الأصناف والكميات — راجعها وانت بتستلم.',
                           'The items and quantities — check them while receiving.'),
             'more': TT_MORE_DITEMS},
                {'target': 'transfers-transit-notes', 'route': '/transits',
                 'text': T('أي ملاحظة (نقص، كسر، تأخير) اكتبها هنا عشان الفرعين يشوفوها.',
                           'Any note (missing, broken, delayed) goes here so both branches see it.'),
             'more': TT_MORE_NOTES},
                {'target': 'transfers-transit-mark-received', 'route': '/transits',
                 'text': T('«✅ تسجيل الاستلام» للفرع المستلم بيسجّله هنا ويظهر «⏳ مستلم محلياً — في انتظار تأكيد SOFTECH» لحد ما مستند الاستلام (25) يتسجّل في SOFTECH، وبعدها المطابقة بتظهر.',
                           '"✅ Record receipt" (receiving branch) records it here and shows "⏳ Received locally — awaiting SOFTECH" until the receipt document (25) is in SOFTECH; then the reconciliation appears.'),
             'more': TT_MORE_RECEIVED},
            ],
        },
    ],
}

_NEW_STEPS = [
    T('اختر «الفرع الطالب» (فرعك عادةً) و«الفرع المصدر» الذي لديه المخزون — لا يمكن أن يكونا نفس الفرع.',
      'Choose the "requesting branch" (usually yours) and the "supplying branch" that has the stock — they cannot be the same.'),
    T('ابحث عن الأصناف بالاسم أو الكود أو الباركود وأدخل الكمية لكل صنف؛ يظهر بجانب كل صنف مخزونه في الفرع المصدر.',
      'Search items by name, code or barcode and enter a quantity for each; each item shows its stock at the supplying branch.'),
    T('اكتب سبب الطلب في الملاحظات (مثلاً: لحجز عميل، نقص متكرر).', 'Write the reason in the notes (e.g. for a customer reservation, repeated shortage).'),
    T('«حفظ كمسودة» لو ستراجعه لاحقاً، أو «حفظ وتقديم» لإرساله للفرع المصدر مباشرةً.',
      '"Save as draft" to review later, or "Save and submit" to send it to the supplying branch now.'),
]

SCREENS = [
    {
        'key': 'transfers.list',
        'routes': ['/transfers'],
        'title': T('طلبات التحويل', 'Transfer requests'),
        'summary': T(
            'كل طلبات التحويل الداخلية بين الفروع حسب الحالة، كقائمة أو كانبان، مع البحث والفلترة بالفرع الطالب والمصدر. '
            'الشريط العلوي ينقلك بين «طلبات التحويل» و«قيد النقل».',
            'All internal transfer requests between branches by status, as a list or Kanban, with search and filters by requesting and supplying branch. '
            'The switcher at the top moves between "Transfer requests" and "In transit".'),
        'audience': T('الصيادلة والمشتريات والمشرفون ومركز الاتصال.', 'Pharmacists, purchasing, supervisors and the call center.'),
        'steps': [
            T('شرائح الحالة أعلى القائمة (مسودة، بانتظار الموافقة، معتمد…) تعرض ما في كل مرحلة. «مسوداتي» تعرض ما لم تقدّمه بعد.',
              'The status chips (draft, waiting, approved…) show what is in each stage. "My drafts" shows what you have not submitted yet.'),
            T('لو فرعك هو المصدر: راجع «بانتظار الموافقة» أولاً — هذه طلبات فروع أخرى تنتظرك.',
              'If your branch is the supplier: check "Waiting for approval" first — other branches are waiting on you.'),
            T('«طلب تحويل جديد» لإنشاء طلب.', '"New transfer request" to create one.'),
            T('اضغط رقم الطلب لفتح تفاصيله واتخاذ الإجراء.', 'Click a request number to open it and act.'),
        ],
        'tips': [
            T('الطلب لا يؤثر على المخزون حتى يُصدر فعلاً في SOFTECH.', 'A request does not affect stock until it is actually issued in SOFTECH.'),
        ],
        'related': ['transfers.new', 'transfers.detail', 'transfers.transits'],
        'tour': [
            {'target': 'transfers-list-new', 'text': T('«+ طلب تحويل جديد» لطلب صنف من فرع تاني.',
                                              '"+ New transfer request" to request an item from another branch.'),
             'more': TR_MORE_NEW_BTN},
            {'target': 'transfers-list-tabs', 'text': T('تبويبات الحالة: مسوداتك، اللي مستني موافقة، وهكذا.',
                                              'Status tabs: your drafts, waiting for approval, and so on.'),
             'more': TR_MORE_TABS},
            {'target': 'transfers-list-search', 'text': T('ابحث برقم الطلب.',
                                              'Search by request number.'),
             'more': TR_MORE_SEARCH},
            {'target': 'transfers-list-view', 'text': T('بدّل بين «قائمة» و«كانبان».',
                                              'Switch between "List" and "Kanban".'),
             'more': TR_MORE_VIEW},
            {'target': 'transfers-list-table', 'text': T('الطلبات — افتح أي طلب للموافقة أو الرفض أو المتابعة حسب دورك.',
                                              'The requests — open one to approve, reject or follow up, depending on your role.'),
             'more': TR_MORE_TABLE},
            {'target': 'transfers-list-table', 'wait': '/transfers/:id',
             'text': T('افتح أي طلب من القائمة — الجولة هتكمّل على صفحة تفاصيله. لو القائمة فاضية اضغط «إنهاء».',
                       'Open any request from the list — the tour continues on its detail page. If the list is empty, press "End".'),
             'more': TR_MORE_OPEN},
        ],
        'tour_continue': 'transfers.detail',
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'transfers.new',
        'routes': ['/transfers/new', '/m/transfers/new'],
        'title': T('طلب تحويل جديد', 'New transfer request'),
        'summary': T('نموذج طلب أصناف من فرع آخر، بعدة أصناف في طلب واحد.', 'The form to request items from another branch, several items per request.'),
        'audience': T('الفرع الذي يحتاج الصنف، أو المشرف.', 'The branch that needs the item, or a supervisor.'),
        'steps': _NEW_STEPS,
        'tips': [
            T('لو صنف «لا يوجد مخزون في أي فرع» فالتحويل لن يفيد — سجّله كطلب ضائع أو نقص للمشتريات.',
              'If an item shows "no stock in any branch", a transfer will not help — record it as lost demand or a shortage for purchasing.'),
        ],
        'related': ['transfers.list', 'demand.list', 'shortage.list'],
        'tour': [
            {'target': 'transfers-new-branches', 'text': T('حدد الفرع الطالب والفرع المصدر.',
                                              'Choose the requesting branch and the supplying branch.'),
             'more': TR_MORE_BRANCHES},
            {'target': 'transfers-new-items', 'text': T('ابحث عن الأصناف وضيفها بالكميات المطلوبة.',
                                              'Search the items and add them with the quantities needed.'),
             'more': TR_MORE_ITEMS},
            {'target': 'transfers-new-notes', 'text': T('ملاحظات للفرع المصدر (اختياري).',
                                              'Notes for the supplying branch (optional).'),
             'more': TR_MORE_NOTES},
            {'target': 'transfers-new-send-now', 'text': T('علّم هنا لو عايز تقدّم الطلب على طول بدل ما يتحفظ مسودة.',
                                              'Tick this to submit right away instead of saving a draft.'),
             'more': TR_MORE_SENDNOW},
            {'target': 'transfers-new-submit', 'text': T('احفظ كمسودة أو «حفظ وتقديم».',
                                              'Save as draft, or "Save & submit".'),
             'more': TR_MORE_SUBMIT},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'transfers.detail',
        'routes': ['/transfers/:id', '/m/transfers/:id'],
        'title': T('تفاصيل طلب التحويل', 'Transfer request details'),
        'summary': T(
            'طلب تحويل واحد: الفرعان، الأصناف بالكميات المطلوبة والمعتمدة والمستلمة ومخزونها في الفروع، مسار الطلب (إنشاء ← تقديم ← مراجعة ← إرسال ERP ← اكتمال)، '
            'المحادثة، ومطابقة مستند SOFTECH. الأزرار المعروضة هي فقط المسموح لك بها حسب فرعك والحالة.',
            'One transfer request: both branches, items with requested, approved and received quantities and their stock, the request path '
            '(created → submitted → reviewed → sent to ERP → completed), the chat, and the SOFTECH document match. Only the buttons you are allowed to use '
            'for your branch and the current status are shown.'),
        'audience': T('الفرع الطالب والفرع المصدر والمشرف.', 'The requesting branch, the supplying branch and supervisors.'),
        'steps': [
            T('الفرع الطالب: أضف/عدّل الأصناف في المسودة ثم «تقديم الطلب».', 'Requesting branch: add/edit items in the draft, then "Submit".'),
            T('الفرع المصدر: «اعتماد» وأدخل الكمية المعتمدة لكل صنف (يمكن جزئياً)، أو «رفض» بسبب، أو «طلب تعديل» بملاحظات.',
              'Supplying branch: "Approve" with the approved quantity per item (partial allowed), or "Reject" with a reason, or "Request changes" with notes.'),
            T('بعد الاعتماد: أصدر التحويل في SOFTECH ثم «إرسال للـ ERP» واكتب مرجع المستند. يمكنك «تسجيل الإرسال» باسم مندوب التوصيل.',
              'After approval: issue the transfer in SOFTECH, then "Send to ERP" with the document reference. You can "Record dispatch" with the courier name.'),
            T('الفرع الطالب عند وصول الشحنة: «تأكيد الاستلام» بالكمية المستلمة فعلاً لكل صنف — هذا يغلق الطلب.',
              'Requesting branch when the shipment arrives: "Confirm receipt" with the quantity actually received per item — this closes the request.'),
            T('قسم «مطابقة مستند ERP» يعرض هل المستند في SOFTECH مطابق أو جزئي أو غير موجود، ويُفحص تلقائياً كل 30 دقيقة.',
              'The "ERP document match" section shows whether the SOFTECH document is matched, partial or missing; it is checked every 30 minutes.'),
        ],
        'tips': [
            T('لو الطلب مرتبط بشحنة «قيد النقل» يظهر رابط «قيد النقل ←» لفتحها مباشرة.', 'If the request is linked to an in-transit shipment, a "In transit ←" link opens it.'),
            T('لا تعتمد كمية أكبر من المتاح فعلاً في فرعك.', 'Do not approve more than you actually have.'),
        ],
        'related': ['transfers.list', 'transfers.transits'],
        'tour': [
            {'target': 'transfers-detail-header', 'text': T('رقم الطلب وحالته.',
                                              'The request number and its status.'),
             'more': TR_MORE_DHEADER},
            {'target': 'transfers-detail-details', 'text': T('التفاصيل: الفرع الطالب والمصدر والتواريخ.',
                                              'Details: requesting and supplying branch, dates.'),
             'more': TR_MORE_DDETAILS},
            {'target': 'transfers-detail-items', 'text': T('الأصناف والكميات.',
                                              'The items and quantities.'),
             'more': TR_MORE_DITEMS},
            {'target': 'transfers-detail-actions', 'text': T('طباعة وواتساب وأزرار الخطوة التالية.',
                                              'Print, WhatsApp and the next-step buttons.'),
             'more': TR_MORE_DACTIONS},
            {'target': 'transfers-detail-approve', 'text': T('«اعتماد» للفرع المصدر (لو عندك الصلاحية).',
                                              '"Approve" for the supplying branch (if you have permission).'),
             'more': TR_MORE_APPROVE},
            {'target': 'transfers-detail-chatter', 'text': T('التواصل بين الفرعين على الطلب.',
                                              'Communication between the two branches on the request.'),
             'more': TR_MORE_CHATTER},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'transfers.transits',
        'routes': ['/transits'],
        'title': T('التحويلات قيد النقل', 'Transfers in transit'),
        'summary': T(
            'الشحنات التي صدرت فعلاً من SOFTECH بين الفروع (مستند 125) ولم تُستلم بعد. كل شحنة لها لون أولوية حسب عمرها '
            '(طازج ← مراقبة ← متابعة ← طارئ ← حرج)، ومهلة إلغاء، وتنبيه للأصناف قريبة الانتهاء (FEFO). '
            'منها تُصدَّر «ورقة التجميع» للمخزن المصدر و«ورقة الترصيص» للفرع المستلم.',
            'Shipments actually issued in SOFTECH between branches (doc 125) that have not been received yet. Each has a priority colour by age '
            '(fresh → watch → follow-up → urgent → critical), a cancellation deadline, and a warning for near-expiry items (FEFO). '
            'From here you export the "picking sheet" for the supplying store and the "stocking sheet" for the receiving branch.'),
        'audience': T('الفروع (الإرسال والاستلام)، المخزن، المشتريات، المشرفون.', 'Branches (sending and receiving), the warehouse, purchasing, supervisors.'),
        'tabs': [
            {'key': 'items', 'title': T('الأصناف', 'Items'),
             'body': T('أصناف الشحنة المختارة: الكمية، تاريخ الصلاحية، التشغيلات، والتكلفة. الأصناف قريبة الانتهاء تظهر بتحذير FEFO — استلمها وصرّفها أولاً.',
                       'Items of the selected shipment: quantity, expiry date, batches and cost. Near-expiry items carry a FEFO warning — receive and sell them first.')},
            {'key': 'recon', 'title': T('مطابقة 125↔25', 'Reconcile 125↔25'),
             'body': T('يظهر بعد استلام الشحنة في SOFTECH: يقارن الصرف (125) بالاستلام (25) — أصناف ناقصة، فروق كميات، أصناف زائدة، وفرق القيمة. أي تباين يحتاج تحقيقاً.',
                       'Shows once the shipment is received in SOFTECH: compares the issue (125) with the receipt (25) — missing items, quantity differences, extra items and the value gap. Any mismatch needs investigation.')},
            {'key': 'notes', 'title': T('الملاحظات', 'Notes'),
             'body': T('ملاحظات داخلية على الشحنة (تأخير، نقص في الكرتونة، مكالمة مع الفرع).', 'Internal notes on the shipment (delay, missing carton, call with the branch).')},
            {'key': 'timeline', 'title': T('السجل', 'Timeline'),
             'body': T('سجل كل ما حدث على الشحنة: الإصدار، الملاحظات، الاستلام، الإغلاق.', 'Everything that happened: issue, notes, receipt, closing.')},
        ],
        'steps': [
            T('شريط المؤشرات أعلى الصفحة: عدد الشحنات وقيمتها، الحرج/الطارئ، ما تنتهي مهلة إلغائه خلال 24 ساعة، وما استُلم وصدر اليوم.',
              'The KPI strip at the top: number and value of shipments, critical/urgent, those whose cancellation window ends within 24 hours, and today\'s receipts and issues.'),
            T('رتّب وصفِّ بالأولوية والحالة وفرع المصدر والمستلم والعمر. ابدأ بالحرج.', 'Sort and filter by priority, status, source and receiving branch and age. Start with critical.'),
            T('اضغط شحنة لفتح لوحة تفاصيلها (التبويبات أعلاه).', 'Click a shipment to open its detail panel (tabs above).'),
            T('«ورقة التجميع» (Excel): بمسار مخزن المصدر لتجهيز الشحنة. حدد عدة شحنات لورقة تجميع موحدة.',
              '"Picking sheet" (Excel): ordered by the supplying store\'s walk path to prepare the shipment. Select several shipments for one combined sheet.'),
            T('«ورقة الترصيص» (Excel): بترتيب أرفف الفرع المستلم لتسريع وضع الأصناف على الأرفف.',
              '"Stocking sheet" (Excel): in the receiving branch\'s shelf order to put items away faster.'),
            T('«تسجيل الاستلام» عند الاستلام، أو «إغلاق قسري» بسبب مكتوب (10 أحرف على الأقل) للحالات الاستثنائية.',
              '"Record receipt" on arrival, or "Force close" with a written reason (at least 10 characters) for exceptional cases.'),
        ],
        'tips': [
            T('لو تحويل اتسجّل استلامه هنا ومستند الاستلام (25) ما ظهرش في SOFTECH بعد عدد الأيام المحدد في الإعدادات (افتراضي 3)، بيوصل تنبيه يومي للفرع المستلم والإدارة. زر «⏳ بانتظار تأكيد SOFTECH» يعرضهم كلهم.',
              'If a transfer was received here and its receipt document (25) has not appeared in SOFTECH after the number of days set in settings (default 3), a daily alert goes to the receiving branch and admins. The "⏳ Awaiting SOFTECH" button lists them all.'),
            T('«تسجيل الاستلام» هنا ما بيكتبش في SOFTECH: الشحنة بتفضل «مستلم محلياً — في انتظار تأكيد SOFTECH» لحد ما مستند الاستلام (25) يتسجّل هناك، وساعتها المزامنة بتطابق الكميات (ولو فيه فرق تظهر «تباين مع ERP»).',
              '"Record receipt" here does not write to SOFTECH: the shipment stays "received locally — awaiting SOFTECH" until the receipt document (25) is recorded there; the sync then reconciles quantities (a difference shows as "ERP mismatch").'),
            T('الشحنة يجب أن تُستلم في SOFTECH قبل انتهاء مهلة الإلغاء، وإلا تظهر «انتهت مهلة الإلغاء — يجب الاستلام».',
              'The shipment must be received in SOFTECH before its cancellation window ends, otherwise "cancellation window over — must receive" appears.'),
            T('«بطاقة مساءلة الفروع» أسفل الصفحة تعرض أداء كل فرع في الاستلام والمخزون العائم.', 'The "branch accountability card" at the bottom shows each branch\'s receiving performance and floating stock.'),
        ],
        'related': ['transfers.list', 'transfers.pick_zones'],
        'tour': [
            {'target': 'transfers-transits-tabs', 'text': T('تبويبات موديول التحويلات.',
                                              'The transfers module tabs.'),
             'more': TT_MORE_TABS},
            {'target': 'transfers-transits-kpis', 'text': T('ملخص التحويلات قيد النقل.',
                                              'A summary of transfers in transit.'),
             'more': TT_MORE_KPIS},
            {'target': 'transfers-transits-filters', 'text': T('فلتر الأولوية والفرع وغيرها.',
                                              'Filter by priority, branch and more.'),
             'more': TT_MORE_FILTERS},
            {'target': 'transfers-transits-awaiting-erp', 'text': T('«⏳ بانتظار تأكيد SOFTECH»: اللي اتسجّل استلامها هنا ولسه مستند الاستلام (25) ما ظهرش في SOFTECH.',
                                              '"⏳ Awaiting SOFTECH": shipments received here whose receipt document (25) is not in SOFTECH yet.'),
             'more': TT_MORE_AWAITING},
            {'target': 'transfers-transits-grid', 'text': T('الشحنات اللي اتصرفت ولسه ما اتستلمتش — الأقدم أولاً.',
                                              'Shipments issued but not yet received — oldest first.'),
             'more': TT_MORE_GRID},
            {'target': 'transfers-transits-scorecard', 'text': T('«🏆 بطاقة المساءلة» لأداء الفروع في الاستلام.',
                                              '"🏆 Accountability card" for branches\' receiving performance.'),
             'more': TT_MORE_SCORECARD},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'transfers.pick_zones',
        'routes': ['/pick-zones'],
        'title': T('مناطق التجميع والترصيص', 'Picking & stocking zones'),
        'summary': T(
            'إعداد كيف تُرتَّب الأصناف في «ورقة التجميع» (مسار السير في المخزن المورد) و«ورقة الترصيص» (ترتيب أرفف الفرع المستلم، ويُستخدم أيضاً في أوراق الجرد). '
            'كل صنف يُصنَّف في منطقة بهذا الترتيب: تخصيص يدوي للصنف ← ثلاجة ← حد الغوالي ← القواعد بالترتيب (أول تطابق يفوز) ← غير مصنف.',
            'Configure how items are ordered on the "picking sheet" (the walk path in the supplying store) and the "stocking sheet" (the receiving branch\'s shelf order, also used on stock-count sheets). '
            'Each item gets a zone in this order: manual item assignment → fridge → high-value threshold → rules in order (first match wins) → uncategorized.'),
        'audience': T('الجميع يرى؛ التعديل للمدير والمشتريات.', 'Everyone can view; admin and purchasing edit.'),
        'tabs': [
            {'key': 'zones', 'title': T('المناطق', 'Zones'),
             'body': T('المناطق (مثل: ممر 2، رف B) بترتيب المسار — الأصغر يُجمَّع أولاً. لكل منطقة موقع وتفعيل وأدوار خاصة: «غوالي» (الأصناف فوق حد السعر)، «ثلاجة»، «غير مصنف».',
                       'Zones (e.g. aisle 2, shelf B) in path order — the lowest is picked first. Each has a location, an on/off switch and special roles: "high-value" (items above the price threshold), "fridge", "uncategorized".')},
            {'key': 'rules', 'title': T('القواعد', 'Rules'),
             'body': T('قواعد تضع الصنف في منطقة: بكلمات في اسم الصنف أو بأعمدة الكتالوج (شكل الصنف، نوع الدواء، العائلة، الشركة، المنشأ، الوحدة). '
                       'الترتيب مهم (أول قاعدة تتطابق تفوز) — استخدم الأسهم لإعادة الترتيب، و«اختبار التصنيف الحي» لتجربة اسم صنف.',
                       'Rules that put an item in a zone: by words in the item name or by catalog columns (form, drug type, family, company, origin, unit). '
                       'Order matters (the first matching rule wins) — use the arrows to reorder, and the "live classification test" to try an item name.')},
            {'key': 'uncategorized', 'title': T('❓ غير مصنف', '❓ Uncategorized'),
             'body': T('أصناف الكتالوج التي لم تطابق أي قاعدة — خصّص لها منطقة أو أضف قاعدة تغطيها.', 'Catalog items that matched no rule — assign them a zone or add a rule that covers them.')},
            {'key': 'overrides', 'title': T('التخصيصات', 'Item assignments'),
             'body': T('تخصيص صنف معيّن لمنطقة يدوياً (يتغلب على كل القواعد) مع وسوم وموقع.', 'Manually assign a specific item to a zone (beats all rules), with tags and a location.')},
        ],
        'steps': [
            T('اختر الغرض: «تجميع» (مخزن المصدر) أو «ترصيص» (أرفف الفرع).', 'Choose the purpose: "Picking" (supplying store) or "Stocking" (branch shelves).'),
            T('اختر الموقع: الإعداد الافتراضي أو مخزن/فرع بعينه. «نسخ الإعداد الافتراضي» يبدأ إعداد فرع من الافتراضي.',
              'Choose the location: the default setup or a specific store/branch. "Copy default setup" starts a branch setup from the default.'),
            T('حدد «حد سعر الغوالي» (ج.م): الأصناف بسعر أعلى أو يساويه تذهب لمنطقة الغوالي.', 'Set the "high-value price threshold" (EGP): items priced at or above it go to the high-value zone.'),
        ],
        'related': ['transfers.transits', 'stockcount.sessions'],
        'tour': [
            {'target': 'transfers-pick-zones-purpose', 'text': T('اختار الغرض: «🚚 تجميع — مخزن المصدر» أو «🗄️ ترصيص — أرفف الفرع» (وبيُستخدم كمان في الجرد).',
                                              'Choose the purpose: "🚚 Picking — source store" or "🗄️ Stocking — branch shelves" (also used for stock counts).'),
             'more': PZ_MORE_PURPOSE},
            {'target': 'transfers-pick-zones-location', 'text': T('اختار الموقع: «🏠 الإعداد الافتراضي (عام)» أو مخزن/فرع له إعداده الخاص.',
                                              'Choose the location: "🏠 Default setup (general)" or a store/branch with its own setup.'),
             'more': PZ_MORE_LOCATION},
            {'target': 'transfers-pick-zones-tabs', 'text': T('التبويبات: «📍 المناطق»، «📐 القواعد»، «❓ غير مصنف»، «🏷️ تخصيصات الأصناف».',
                                              'Tabs: "📍 Zones", "📐 Rules", "❓ Uncategorized", "🏷️ Item assignments".'),
             'more': PZ_MORE_TABS},
            {'target': 'transfers-pick-zones-settings', 'text': T('في تبويب «المناطق»: «إعدادات التصنيف» فيها حد سعر الغوالي (عام لكل المخازن) والأدوار الخاصة — التعديل للإدارة والمشتريات.',
                                              'In the "Zones" tab: "Classification settings" holds the high-value price threshold (global) and special roles — editing is for admin and purchasing.'),
             'more': PZ_MORE_SETTINGS},
            {'target': 'transfers-pick-zones-zones', 'text': T('جدول المناطق بترتيب المسار: الأصغر يُجمَّع الأول، مع الموقع/الرف والأدوار والتفعيل.',
                                              'The zones table in path order: the lowest is picked first, with location/shelf, roles and on/off.'),
             'more': PZ_MORE_ZONES},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
    {
        'key': 'transfers.mobile_list',
        'routes': ['/m/transfers'],
        'title': T('طلبات التحويل (موبايل)', 'Transfer requests (mobile)'),
        'summary': T('طلبات التحويل التي فرعك طالب فيها أو مصدر لها، على الموبايل، مع شرائح الحالة.',
                     'Transfer requests where your branch is requesting or supplying, on the phone, with status chips.'),
        'audience': T('العاملون في الفرع.', 'Branch staff.'),
        'steps': [
            T('اضغط طلباً لعرضه والقيام بالإجراء المتاح لك (تقديم، اعتماد، رفض، استلام…).', 'Tap a request to view it and take the action available to you (submit, approve, reject, receive…).'),
            T('زر «+» لطلب تحويل جديد.', 'The "+" button creates a new transfer request.'),
        ],
        'related': ['transfers.new', 'transfers.detail'],
        'tour': [
            {'target': 'transfers-mobile-list-new', 'text': T('زر «+» لطلب تحويل جديد.',
                                              'The "+" button makes a new transfer request.'),
             'more': TM_MORE_NEW},
            {'target': 'transfers-mobile-list-filters', 'text': T('فلتر الحالة: بانتظار الموافقة، الكل، مسودة…',
                                              'Status filter: waiting for approval, all, draft…'),
             'more': TM_MORE_FILTERS},
            {'target': 'transfers-mobile-list-list', 'text': T('طلبات التحويل حسب الفلتر.',
                                              'The transfer requests matching the filter.'),
             'more': T('قائمة طلبات التحويل اللي بتطابق الفلتر، والأحدث فوق.\n'
                           '• «تحميل المزيد» في الآخر لو فيه طلبات أكتر.',
                           'The transfer requests matching the filter, newest on top.\n'
                           '• "Load more" at the end when there are more requests.')},
            {'target': 'transfers-mobile-list-card', 'text': T('كل كارت: رقم الطلب ومن أي فرع لأي فرع — اضغطه للتفاصيل.',
                                              'Each card: request number and from which branch to which — tap it for details.'),
             'more': TM_MORE_CARD},
            {'target': 'transfers-mobile-list-status', 'text': T('حالة الطلب الحالية.',
                                              'The request\'s current status.'),
             'more': T('حالة الطلب الحالية بلونها: مسودة، بانتظار الموافقة، معتمد، يحتاج تعديل، أُرسل للـ ERP، مكتمل، مرفوض أو ملغي.\n'
                           '• الحالة بتحدد الأزرار اللي هتلاقيها جوه.',
                           'The request\'s current status with its colour: draft, waiting for approval, approved, needs revision, sent to ERP, completed, rejected or cancelled.\n'
                           '• The status decides which buttons you find inside.')},
        ],
        'change_note': T('شرح أوضح لكل زر في جولة «اعرض لي»', 'Clearer explanation of every button in the "Show me" tour'),
        'updated': '2026-10-25',
    },
]
