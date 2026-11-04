/**
 * PhoneAlertStatusChip — where the WhatsApp alert for a record stands (أُرسل / وصل / قُرئ / استلم /
 * صُعّد / انتهى …) and, once acknowledged, the person's remark. Renders nothing without a status.
 */
export const PHONE_ALERT_STATUS = {
  queued:       { label: 'في الانتظار', cls: 'bg-gray-100 text-gray-600' },
  sent:         { label: 'أُرسل',       cls: 'bg-blue-50 text-blue-700' },
  delivered:    { label: 'وصل',         cls: 'bg-sky-50 text-sky-700' },
  read:         { label: 'قُرئ',        cls: 'bg-indigo-50 text-indigo-700' },
  acknowledged: { label: 'استلم',       cls: 'bg-emerald-50 text-emerald-700' },
  escalated:    { label: 'صُعّد',       cls: 'bg-amber-50 text-amber-800' },
  expired:      { label: 'انتهى',       cls: 'bg-gray-100 text-gray-500' },
  failed:       { label: 'فشل',         cls: 'bg-red-50 text-red-700' },
}

export default function PhoneAlertStatusChip({ status, remark }) {
  const s = PHONE_ALERT_STATUS[status]
  if (!s) return null
  return (
    <span title={remark ? `ملاحظة: ${remark}` : 'حالة تنبيه الموبايل'}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${s.cls}`}>
      📲 {s.label}
      {remark ? <span className="max-w-[14rem] truncate font-normal">· {remark}</span> : null}
    </span>
  )
}
