/* POS Speed Wave §6 — the line chip of an automatic FEFO split (one row = N batch lines).
 * Shows «N تشغيلات» + the expiries in small text, the shortfall chip «ناقص X — حجز الباقي» (the ONLY
 * way a shortfall becomes a حجز line) and «تغيير التشغيلة» (reopens the batch modal). The split itself
 * is decided server-side (POST /pos-orders/fefo-split/); this only renders it. Desktop + mobile. */
import { BatchBadge, Badge, Icon } from '../design'

export default function FefoGroupChip({ g, P, className = '' }) {
  if (!g) return null
  const label = g.stale ? 'بدون تشغيلة' : `${g.count} ${g.count === 1 ? 'تشغيلة' : 'تشغيلات'}`
  const exp = g.expiries.map(e => e || '—').join(' · ')
  const stop = (fn) => (e) => { e.stopPropagation(); fn() }
  return (
    <span className={`inline-flex items-center gap-1 flex-wrap ${className}`}>
      {g.stale
        ? <Badge tone="warn" icon="alert" size="xs" label={label} title="تغيّر الفرع/المخزن — أعد اختيار التشغيلة" />
        : <BatchBadge label={label} title={`توزيع تلقائي — الأقرب انتهاءً أولاً: ${exp}`} />}
      {!g.stale && <span className="text-[10px] text-gray-500 tabular-nums" dir="ltr">{exp}</span>}
      {g.shortfall > 0 && (
        <button type="button" onClick={stop(() => P.reserveRemainder(g.group))}
                title="المتاح أقل من المطلوب — اضغط لإضافة الباقي كسطر حجز">
          <Badge tone="warn" icon="bookmark" size="xs" label={`ناقص ${g.shortfall} — حجز الباقي`} />
        </button>
      )}
      <button type="button" onClick={stop(() => P.openBatchModal(g.group))}
              title="تغيير التشغيلة يدويًا"
              className="inline-flex items-center gap-0.5 text-[10px] text-sky-700 hover:underline">
        <Icon name="package" size={10} />تغيير التشغيلة
      </button>
    </span>
  )
}
