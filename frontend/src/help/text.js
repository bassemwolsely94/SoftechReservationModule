/** Bilingual helpers for help content: every text is { ar, en }. */

export const pick = (t, lang) => {
  if (t == null) return ''
  if (typeof t === 'string') return t
  return (lang === 'en' ? (t.en || t.ar) : (t.ar || t.en)) || ''
}

/** A step / tip is either { ar, en } or { text: { ar, en }, roles: [...] }. */
export const itemText = (it) => (it && it.text ? it.text : it)
export const itemRoles = (it) => (it && Array.isArray(it.roles) ? it.roles : null)

/** UI labels of the help panel itself, in both languages. */
const L = {
  help:          ['المساعدة', 'Help'],
  guide:         ['دليل الاستخدام', 'Help guide'],
  purpose:       ['دور الشاشة', 'What this screen is for'],
  audience:      ['من يستخدمها', 'Who uses it'],
  howto:         ['طريقة الاستخدام', 'How to use it'],
  tabs:          ['التبويبات', 'Tabs'],
  youAreHere:    ['أنت هنا', 'You are here'],
  workflow:      ['دورة العمل', 'Workflow'],
  next:          ['الخطوة التالية', 'Next'],
  tips:          ['ملاحظات مهمة وأخطاء شائعة', 'Good to know & common mistakes'],
  faq:           ['أسئلة متكررة', 'Frequently asked'],
  notes:         ['ملاحظات المدرب', "Trainer's notes"],
  module:        ['عن الموديول', 'About this module'],
  otherScreens:  ['شاشات أخرى في نفس الموديول', 'Other screens in this module'],
  related:       ['شاشات مرتبطة', 'Related screens'],
  wasHelpful:    ['هل كان الشرح مفيداً؟', 'Was this helpful?'],
  yes:           ['مفيد 👍', 'Helpful 👍'],
  no:            ['غير مفيد 👎', 'Not helpful 👎'],
  whatsMissing:  ['إيه اللي مش واضح؟ (اختياري)', 'What is unclear? (optional)'],
  send:          ['إرسال', 'Send'],
  thanks:        ['شكراً — ملاحظتك وصلت للمدرب.', 'Thanks — your note reached the trainer.'],
  noHelp:        ['لا يوجد شرح لهذه الشاشة بعد.', 'There is no help for this screen yet.'],
  openCenter:    ['فتح دليل الاستخدام الكامل', 'Open the full help guide'],
  search:        ['ابحث في الشرح…', 'Search the help…'],
  noResults:     ['لا نتائج', 'No results'],
  back:          ['رجوع لشرح الشاشة الحالية', 'Back to this screen'],
  edit:          ['تعديل الشرح', 'Edit help'],
  editedBy:      ['عدّله', 'Edited by'],
  baseChanged:   ['تنبيه: المطوّرون غيّروا الشرح الأصلي بعد آخر تعديل لك — راجع النسخة الأصلية.',
                  'Note: the developers changed the original text after your last edit — review the original.'],
  updated:       ['آخر تحديث', 'Last updated'],
  newBadge:      ['جديد', 'New'],
  close:         ['إغلاق', 'Close'],
  loading:       ['…جارٍ التحميل', 'Loading…'],
  f1:            ['اضغط F1 من أي شاشة', 'Press F1 on any screen'],
}

export const label = (key, lang) => {
  const v = L[key]
  return v ? (lang === 'en' ? v[1] : v[0]) : key
}
