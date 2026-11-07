# Attendance agent / برنامج جمع البصمات

## English

A small program for an always-on office PC. It reads punches from the ZK fingerprint
machines and sends them to the ERP. It has no Django dependency and uses only the Python
standard library.

**It only reads.** It can connect, disconnect, read options, read sizes, read the time,
read the user table, read the attendance log and free its read buffer. It has no code for
clearing logs, pausing a machine, changing its clock, restarting it, writing or deleting
users, or reading fingerprint templates. `ZkClient._send` enforces this list.

### Install

1. Install Python 3.11 or newer on the office PC.
2. Copy the `attendance_agent` folder to the PC, for example to `C:\ElRezeiky\agent\attendance_agent`.

### First run: test one machine before all of them

The log read was never tried on a real machine; only user tables were. Before any
scheduled run, on one reachable machine:

1. Connect with the ZK program open at the same time, and confirm both keep working.
2. Have a staff member punch during the read, and confirm the machine accepts the punch.
3. Compare the number of punches read with the count the machine shows.
4. Check that user codes in the log are real ID numbers. A code like `uid-5` means the
   machine's log holds its internal slot rather than the ID, and this needs a decision
   before going further.

### Comm key

Machines probed so far need no comm key. If a machine answers that it needs one, the run
reports `CommKeyRequired`. The key then goes in the agent's local configuration only,
never in the ERP.

## العربية

برنامج صغير يعمل على جهاز مكتبي يظل قيد التشغيل دائمًا. يقرأ البصمات من أجهزة البصمة ZK
ويرسلها إلى النظام. لا يعتمد على Django ويستخدم مكتبات بايثون القياسية فقط.

**البرنامج يقرأ فقط.** يمكنه الاتصال وقطع الاتصال وقراءة الإعدادات وقراءة الأحجام وقراءة
الوقت وقراءة جدول المستخدمين وقراءة سجل البصمات وتحرير ذاكرة القراءة. ولا يحتوي على أي
كود لمسح السجلات أو إيقاف الجهاز أو تغيير ساعته أو إعادة تشغيله أو كتابة المستخدمين أو
حذفهم أو قراءة قوالب البصمة. والدالة `ZkClient._send` هي التي تفرض هذه القائمة.

### التثبيت

1. ثبّت Python 3.11 أو أحدث على الجهاز المكتبي.
2. انسخ مجلد `attendance_agent` إلى الجهاز، مثلًا إلى `C:\ElRezeiky\agent\attendance_agent`.

### التشغيل الأول: اختبر جهاز بصمة واحدًا قبل الباقي

قراءة سجل البصمات لم تُجرَّب على جهاز حقيقي؛ جُرّبت جداول المستخدمين فقط. قبل أي تشغيل
مجدول، وعلى جهاز واحد يمكن الوصول إليه:

1. اتصل وبرنامج ZK مفتوح في الوقت نفسه، وتأكد من أن كليهما يستمر في العمل.
2. اطلب من أحد الموظفين أن يبصم أثناء القراءة، وتأكد من أن الجهاز يقبل البصمة.
3. قارن عدد البصمات المقروءة بالعدد الذي يعرضه الجهاز.
4. تأكد من أن أكواد الموظفين في السجل أرقام حقيقية. الكود الذي يشبه `uid-5` يعني أن سجل الجهاز
   يحتفظ برقمه الداخلي بدلًا من رقم الموظف، وهذا يحتاج إلى قرار قبل الاستمرار.

### مفتاح الاتصال (Comm key)

الأجهزة التي فُحصت حتى الآن لا تحتاج إلى مفتاح. إذا طلب أحد الأجهزة مفتاحًا فسيعرض التشغيل
الخطأ `CommKeyRequired`، ويوضع المفتاح حينها في إعدادات البرنامج المحلية فقط، ولا يوضع في
النظام أبدًا.
