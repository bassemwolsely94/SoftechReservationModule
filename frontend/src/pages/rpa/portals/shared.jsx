// Shared labels for /rpa/portals. Display only: every rule (needs a person, locked line, discovery
// stalled, may have ordered) comes from the server as a field.
export { Badge, asList, errText, fmtTime } from '../shared.jsx'

const MUTED = 'bg-surface-2 text-muted'
const BLUE = 'bg-blue-500/10 text-blue-700 dark:text-blue-300'
const GREEN = 'bg-green-500/10 text-green-700 dark:text-green-300'
const AMBER = 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
const RED = 'bg-red-500/10 text-red-700 dark:text-red-300'

export const LIST_STATUS = {
  open: { label: 'مفتوحة', cls: BLUE },
  closed: { label: 'مغلقة', cls: MUTED },
}

export const SOURCE = { pivot: 'البيفوت', isr: 'طلب توريد', upload: 'ملف' }

export const JOB_STATUS = {
  draft: { label: 'مسودة', cls: AMBER },
  approved: { label: 'معتمدة', cls: BLUE },
  cancelled: { label: 'ملغاة', cls: MUTED },
  done: { label: 'انتهت', cls: GREEN },
}

export const BASKET_STATUS = {
  pending: { label: 'تنتظر الأكواد', cls: AMBER },
  ready: { label: 'جاهزة', cls: BLUE },
  in_progress: { label: 'الروبوت يملأ', cls: BLUE },
  dry_run_ok: { label: 'نجحت التجربة', cls: GREEN },
  awaiting_submit: { label: 'راجع واضغط Submit', cls: AMBER },
  submitted: { label: 'أُرسلت', cls: BLUE },
  recorded: { label: 'مسجلة', cls: GREEN },
  needs_person: { label: 'تحتاج موظف', cls: RED },
  cancelled: { label: 'ملغاة', cls: MUTED },
}

export const LINE_STATUS = {
  pending: { label: 'في الانتظار', cls: MUTED },
  ok: { label: 'متاح', cls: GREEN },
  short: { label: 'أقل من المطلوب', cls: AMBER },
  out: { label: 'غير متاح', cls: RED },
  not_found: { label: 'غير موجود', cls: MUTED },
  removed: { label: 'حُذف من الطلب', cls: MUTED },
}

export const FLAG = {
  short_expiry: { label: 'صلاحية قصيرة', cls: AMBER },
  price_jump: { label: 'قفزة سعر', cls: AMBER },
}

export const NEEDS_PERSON = { label: 'تحتاج موظف', cls: RED }

export function NeedsPersonBadge({ show }) {
  if (!show) return null
  return <span className={`inline-block text-xs rounded px-1.5 py-0.5 whitespace-nowrap ${RED}`}>تحتاج موظف</span>
}

export function ModeBadge({ dryRun }) {
  return dryRun
    ? <span className="inline-block text-xs rounded px-1.5 py-0.5 whitespace-nowrap bg-brand-600/10 text-brand-700 dark:text-brand-300">تجربة</span>
    : <span className={`inline-block text-xs rounded px-1.5 py-0.5 whitespace-nowrap ${AMBER}`}>فعلي</span>
}

/** «565 · Pharma Overseas» from the server's suppliers map. */
export function supplierText(suppliers, code) {
  if (!code) return '—'
  const s = suppliers?.[code]
  return s?.name ? `${code} · ${s.name}` : String(code)
}

export function credit(c) {
  if (!c || (!c.credit && !c.limit && !c.consumption)) return 'لا يوجد رصيد مقروء بعد'
  const parts = []
  if (c.credit) parts.push(`المتاح ${c.credit}`)
  if (c.limit) parts.push(`الحد ${c.limit}`)
  if (c.consumption) parts.push(`المستهلك ${c.consumption}`)
  return parts.join(' · ')
}

export function downloadBlob(data, filename) {
  const url = window.URL.createObjectURL(new Blob([data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.URL.revokeObjectURL(url)
}
