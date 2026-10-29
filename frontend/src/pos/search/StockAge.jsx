/** «المخزون منذ N دقيقة» — how old the mirrored branch stock is. Amber past 30 min; null → «غير معروف». */
import { Icon } from '../design'

export function stockAgeMinutes(asOf) {
  if (!asOf) return null
  const t = new Date(asOf).getTime()
  return Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null
}

export default function StockAge({ asOf, className = '' }) {
  const m = stockAgeMinutes(asOf)
  const stale = m == null || m > 30
  const text = m == null ? 'المخزون: غير معروف'
    : m < 1 ? 'المخزون محدّث الآن'
    : m < 120 ? `المخزون منذ ${m} دقيقة`
    : `المخزون منذ ${Math.round(m / 60)} ساعة`
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] ${stale ? 'text-amber-700 font-medium' : 'text-gray-400'} ${className}`}
          title="آخر مزامنة ناجحة لأرصدة الفروع (كل 5 دقائق تقريبًا)">
      <Icon name="clock" size={11} />{text}
    </span>
  )
}
