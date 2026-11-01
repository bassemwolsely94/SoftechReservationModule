/**
 * CancelReasonPicker — «سبب الإلغاء» for a reservation: a ready list + optional free text.
 * The server refuses a cancel without a reason (apps/reservations/views.py CANCEL_REASON_REQUIRED);
 * cancelNote() turns the choice into the status note it stores.
 */
export const RESERVATION_CANCEL_REASONS = [
  'العميل لم يعد يحتاج الصنف',
  'العميل اشترى الصنف من مكان آخر',
  'تعذّر التواصل مع العميل',
  'الصنف غير متوفر لدى الموردين',
  'السعر غير مناسب للعميل',
  'حجز مكرر',
  'خطأ في الإدخال',
  'أخرى',
]

export const EMPTY_CANCEL = { reason: '', text: '' }

/** The note sent with the cancel — '' until a reason is chosen («أخرى» needs the text). */
export function cancelNote({ reason, text } = EMPTY_CANCEL) {
  const t = (text || '').trim()
  if (!reason || (reason === 'أخرى' && !t)) return ''
  return t ? `سبب الإلغاء: ${reason} — ${t}` : `سبب الإلغاء: ${reason}`
}

export default function CancelReasonPicker({ value = EMPTY_CANCEL, onChange, autoFocus, compact }) {
  const set = (patch) => onChange({ ...value, ...patch })
  const cls = compact ? 'input-field text-xs py-1' : 'input-field text-sm'
  return (
    <div className="space-y-1.5" data-tour="reservations-cancel-reason">
      <select className={cls} value={value.reason} autoFocus={autoFocus}
        onChange={e => set({ reason: e.target.value })}>
        <option value="">— اختر سبب الإلغاء —</option>
        {RESERVATION_CANCEL_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
      </select>
      <input className={cls} value={value.text} onChange={e => set({ text: e.target.value })}
        placeholder={value.reason === 'أخرى' ? 'اكتب السبب (مطلوب)' : 'تفاصيل إضافية (اختياري)'} />
    </div>
  )
}
