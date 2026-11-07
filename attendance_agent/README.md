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

3. Copy `agent.ini.example` to `agent.ini` outside the program folder and fill in the ERP
   address and the secret printed by `manage.py issue_attendance_agent <name>`. Never commit
   the filled copy.
4. Restrict `agent.ini` and the state folder to the account that runs the agent, because the
   secret is in one and names are in the other. For example:
   `icacls C:\ElRezeiky\agent\agent.ini /inheritance:r /grant:r "<account>:(R)"`
5. Turn off sleep and hibernation on the PC, because the agent can't read machines while it sleeps.

### Run it

From the folder that holds `attendance_agent`:

```
python -m attendance_agent C:\ElRezeiky\agent\agent.ini
```

To run one pass and exit, printing what it did, add `--once`. To read only one machine, add
`--once --serial <machine serial>`. Without `--serial`, a pass reads every assigned machine.

**Windows Task Scheduler:**

1. Create a task named "ElRezeiky Attendance Agent" and choose "Run whether user is logged on or not".
2. Trigger: **At startup**.
3. Action: program: the full path to `python.exe` (a per-user install may not be found otherwise), arguments `-m attendance_agent C:\ElRezeiky\agent\agent.ini`, start in `C:\ElRezeiky\agent`.
4. Settings: turn off "Stop the task if it runs longer than", choose "If the task fails, restart every 1 minute" with a high attempt count such as 999, and for "If the task is already running" choose **Do not start a new instance**.

### What it does

It asks the ERP for its machines every 60 seconds, and reads each machine hourly or when
"collect now" is pressed. Each read goes to disk before anything is sent, and a file is
removed only after the ERP accepts it. If the ERP is down, collection continues from the
saved machine list and everything is sent when it returns.

The state folder (`agent_state` next to `agent.ini`, unless `state_dir` is set) holds:

| Item | Meaning |
|---|---|
| `spool\` | Data waiting for the ERP. Roster files in it hold names, so keep the folder to the agent's account. Don't delete files by hand: they may be the only copy. |
| `spool\quarantine\` | Attendance logs that couldn't be decoded. Keep these and report them: they may be the only copy. |
| `devices.json` | Last known machine list. |
| `agent.log` | Counts and serials only, no names, codes or secrets. |

If uploads stop while the machines stay readable, files keep building up in `spool\`,
about one full copy of each machine's log per hour (roughly 60 MB a day at today's log
sizes). This takes months to fill a disk, but there is no limit: once the disk is full, new
reads can't be saved, so watch free space during a long outage.

If the ERP refuses one file (for example, a machine is no longer assigned to this agent),
that file stays in `spool\` and is tried again every pass, while other files keep going.
`agent.log` shows the reason on an `upload:` line. Files that stay for long mean the ERP needs
attention: fix the cause there, and the file goes by itself.

### First run: test one machine before all of them

The log read was never tried on a real machine; only user tables were. Before any
scheduled run, on one reachable machine:

1. Run `python -m attendance_agent <ini> --once --serial <machine serial>` with the ZK program
   open at the same time, and confirm both keep working.
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

3. انسخ `agent.ini.example` إلى `agent.ini` خارج مجلد البرنامج، واكتب فيه عنوان النظام والرمز
   السري الذي يطبعه الأمر `manage.py issue_attendance_agent <name>`. لا تضف النسخة المعبأة إلى
   المستودع أبدًا.
4. اجعل `agent.ini` ومجلد الحالة متاحين للحساب الذي يشغّل البرنامج فقط، لأن الرمز السري في الأول
   والأسماء في الثاني. مثال:
   `icacls C:\ElRezeiky\agent\agent.ini /inheritance:r /grant:r "<account>:(R)"`
5. أوقف وضع السكون والإسبات على الجهاز، لأن البرنامج لا يقرأ أجهزة البصمة أثناء السكون.

### التشغيل

من المجلد الذي يحتوي على `attendance_agent`:

```
python -m attendance_agent C:\ElRezeiky\agent\agent.ini
```

للتشغيل مرة واحدة ثم الخروج مع عرض ما حدث، أضف `--once`. ولقراءة جهاز بصمة واحد فقط، أضف
`--once --serial <الرقم التسلسلي للجهاز>`. وبدون `--serial` يقرأ التشغيل كل الأجهزة المخصصة له.

**جدولة المهام في ويندوز (Task Scheduler):**

1. أنشئ مهمة باسم "ElRezeiky Attendance Agent" واختر "Run whether user is logged on or not".
2. المشغّل: **At startup**.
3. الإجراء: البرنامج: المسار الكامل إلى `python.exe` (قد لا يُعثر على التثبيت الخاص بالمستخدم بغير ذلك)، والوسائط `-m attendance_agent C:\ElRezeiky\agent\agent.ini`، وابدأ في `C:\ElRezeiky\agent`.
4. الإعدادات: ألغِ "Stop the task if it runs longer than"، واختر "If the task fails, restart every 1 minute" مع عدد محاولات كبير مثل 999، ومن "If the task is already running" اختر **Do not start a new instance**.

### ما يفعله البرنامج

يسأل النظام عن أجهزته كل 60 ثانية، ويقرأ كل جهاز كل ساعة أو عند الضغط على "جمع الآن". تُحفظ كل
قراءة على القرص قبل إرسال أي شيء، ولا يُحذف الملف إلا بعد قبول النظام له. وإذا توقف النظام
يستمر الجمع من قائمة الأجهزة المحفوظة، ويُرسل كل شيء عند عودته.

يحتوي مجلد الحالة (`agent_state` بجوار `agent.ini`، ما لم يُحدَّد `state_dir`) على:

| العنصر | المعنى |
|---|---|
| `spool\` | بيانات تنتظر الإرسال إلى النظام. ملفات قوائم المستخدمين فيها تحتوي على أسماء، لذا اجعل المجلد متاحًا لحساب البرنامج فقط. لا تحذف الملفات يدويًا، فقد تكون النسخة الوحيدة. |
| `spool\quarantine\` | سجلات بصمة تعذّرت قراءتها. احتفظ بها وأبلغ عنها، فقد تكون النسخة الوحيدة. |
| `devices.json` | آخر قائمة أجهزة معروفة. |
| `agent.log` | أعداد وأرقام أجهزة فقط، بلا أسماء أو أكواد أو أسرار. |

إذا توقف الإرسال وظلت الأجهزة تُقرأ، تتراكم الملفات في `spool\` بمعدل نسخة كاملة تقريبًا من سجل
كل جهاز كل ساعة (نحو 60 ميجابايت يوميًا بأحجام السجلات الحالية). يستغرق امتلاء القرص شهورًا، لكن
لا يوجد حد: وعند امتلائه لا يمكن حفظ القراءات الجديدة، لذا راقب المساحة الخالية أثناء الانقطاع الطويل.

إذا رفض النظام ملفًا واحدًا (مثلًا لأن جهاز البصمة لم يعد مخصصًا لهذا البرنامج)، يبقى الملف في
`spool\` ويُعاد إرساله في كل دورة، بينما تستمر بقية الملفات. يعرض `agent.log` السبب في سطر `upload:`.
وبقاء الملفات مدة طويلة يعني أن النظام يحتاج إلى مراجعة: عالج السبب هناك وسيُرسل الملف تلقائيًا.

### التشغيل الأول: اختبر جهاز بصمة واحدًا قبل الباقي

قراءة سجل البصمات لم تُجرَّب على جهاز حقيقي؛ جُرّبت جداول المستخدمين فقط. قبل أي تشغيل
مجدول، وعلى جهاز واحد يمكن الوصول إليه:

1. شغّل `python -m attendance_agent <ini> --once --serial <الرقم التسلسلي للجهاز>` وبرنامج ZK
   مفتوح في الوقت نفسه، وتأكد من أن كليهما يستمر في العمل.
2. اطلب من أحد الموظفين أن يبصم أثناء القراءة، وتأكد من أن الجهاز يقبل البصمة.
3. قارن عدد البصمات المقروءة بالعدد الذي يعرضه الجهاز.
4. تأكد من أن أكواد الموظفين في السجل أرقام حقيقية. الكود الذي يشبه `uid-5` يعني أن سجل الجهاز
   يحتفظ برقمه الداخلي بدلًا من رقم الموظف، وهذا يحتاج إلى قرار قبل الاستمرار.

### مفتاح الاتصال (Comm key)

الأجهزة التي فُحصت حتى الآن لا تحتاج إلى مفتاح. إذا طلب أحد الأجهزة مفتاحًا فسيعرض التشغيل
الخطأ `CommKeyRequired`، ويوضع المفتاح حينها في إعدادات البرنامج المحلية فقط، ولا يوضع في
النظام أبدًا.
