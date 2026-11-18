// Shared labels + helpers for the /rpa screen. Display only: every decision comes from the server.

export const JOB_STATUS = {
  uploaded: { label: 'بانتظار الاعتماد', cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  approved: { label: 'معتمد', cls: 'bg-blue-500/10 text-blue-700 dark:text-blue-300' },
  cancelled: { label: 'ملغي', cls: 'bg-surface-2 text-muted' },
  done: { label: 'تم', cls: 'bg-green-500/10 text-green-700 dark:text-green-300' },
}

export const DOC_STATUS = {
  pending: { label: 'في الانتظار', cls: 'bg-surface-2 text-muted' },
  approved: { label: 'معتمد', cls: 'bg-blue-500/10 text-blue-700 dark:text-blue-300' },
  in_progress: { label: 'قيد التشغيل', cls: 'bg-blue-500/10 text-blue-700 dark:text-blue-300' },
  dry_run_ok: { label: 'نجحت التجربة', cls: 'bg-green-500/10 text-green-700 dark:text-green-300' },
  posted: { label: 'تم الحفظ', cls: 'bg-green-500/10 text-green-700 dark:text-green-300' },
  needs_person: { label: 'يحتاج مراجعة', cls: 'bg-red-500/10 text-red-700 dark:text-red-300' },
  cancelled: { label: 'ملغي', cls: 'bg-surface-2 text-muted' },
}

export const LINE_STATUS = {
  matched: { label: 'مطابق', cls: 'text-green-700 dark:text-green-300' },
  unmatched: { label: 'غير مطابق', cls: 'text-amber-700 dark:text-amber-300' },
  error: { label: 'خطأ', cls: 'text-red-700 dark:text-red-300' },
}

export const OUTCOME = {
  '': 'مفتوحة',
  dry_run_ok: 'نجحت التجربة',
  saved: 'تم الحفظ',
  stopped_by_operator: 'أوقفها المشغّل',
  wrong_window: 'نافذة خاطئة',
  unknown_popup: 'نافذة منبثقة غير معروفة',
  timeout: 'انتهت المهلة',
  error: 'خطأ',
}

export const RECIPE_STATUS = {
  draft: { label: 'مسودة', cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300' },
  approved: { label: 'معتمدة', cls: 'bg-green-500/10 text-green-700 dark:text-green-300' },
  retired: { label: 'متقاعدة', cls: 'bg-surface-2 text-muted' },
}

export const SCREEN_LABEL = { issue_125: 'إذن صرف للفروع' }

export function Badge({ map, value }) {
  const m = map[value] || { label: value || '—', cls: 'bg-surface-2 text-muted' }
  return <span className={`inline-block text-xs rounded px-1.5 py-0.5 whitespace-nowrap ${m.cls}`}>{m.label}</span>
}

export const DRY_RUN_TEXT = 'تجربة بدون حفظ'

export const asList = d => (Array.isArray(d) ? d : (d?.results || d?.rows || []))

export function errText(e) {
  // A server message (Arabic: four-eyes refusals, branch scope…) beats the generic text; DRF's own
  // English 401/403 default never reaches the user because it is replaced below.
  const status = e?.response?.status
  const d = e?.response?.data
  const ENGLISH = /^[ -~\s]+$/
  const own = (v) => (typeof v === 'string' && v && v.length < 300 && !v.includes('<') && !ENGLISH.test(v)) ? v : ''
  const fromServer = own(typeof d === 'string' ? d : d?.detail)
    || (d && typeof d === 'object' ? own(Object.values(d).flat().find(v => own(v))) : '')
  if (fromServer) return fromServer
  if (status === 401) return 'انتهت الجلسة — سجّل الدخول مرة أخرى.'
  if (status === 403) return 'ليس لديك صلاحية لهذا الإجراء'
  return 'تعذّر تنفيذ الطلب — حاول مرة أخرى.'
}

export const fmtTime = v => {
  if (!v) return '—'
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' })
}

/** Branch label from a row: «code · name» via useBranchLabels when a code is known, else the server's name. */
export function branchText(bl, row, key) {
  const code = row?.[`${key}_code`] ?? row?.[`${key}_softech_id`]
  if (code) return bl(code)
  const name = row?.[`${key}_name`]
  if (name) return name
  const obj = row?.[key]
  if (obj && typeof obj === 'object') return obj.softech_branch_id ? bl(obj.softech_branch_id) : (obj.name_ar || obj.name || '—')
  return '—'
}

export const screenTitle = row => row?.screen_title
  || (typeof row?.screen === 'object' ? (row.screen?.title_ar || SCREEN_LABEL[row.screen?.key]) : SCREEN_LABEL[row?.screen])
  || '—'
