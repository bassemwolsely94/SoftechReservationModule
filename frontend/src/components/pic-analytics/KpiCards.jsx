/**
 * KpiCards — the Overview tab of PIC Analytics (doc 33 §6): KPI cards, the «بدون PIC» line,
 * the new-PIC reliability warning and the monthly trend. The server decides every number and
 * which keys exist: GP only when the user may see cost, call cards only for management.
 */
export const fmt = (n, d = 0) => (n === null || n === undefined || n === '' || Number.isNaN(Number(n)))
  ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
export const fmtPct = n => (n === null || n === undefined) ? '—' : `${fmt(n, 1)}%`
export const fmtDate = d => d ? String(d).slice(0, 10) : '—'
export const fmtDateTime = d => d ? String(d).slice(0, 16).replace('T', ' ') : '—'
export const fmtDuration = s => {
  if (s === null || s === undefined) return '—'
  const m = Math.round(Number(s) / 60)
  return m >= 60 ? `${Math.floor(m / 60)}س ${m % 60}د` : `${m}د`
}

const TONES = {
  brand: 'bg-brand-50 border-brand-200 text-brand-700',
  green: 'bg-green-50 border-green-200 text-green-700',
  blue:  'bg-blue-50 border-blue-200 text-blue-700',
  amber: 'bg-amber-50 border-amber-200 text-amber-700',
  red:   'bg-red-50 border-red-200 text-red-700',
  gray:  'bg-gray-50 border-gray-200 text-gray-600',
}

export function KpiCard({ label, value, sub, tone = 'brand' }) {
  return (
    <div className={`rounded-xl border p-3 ${TONES[tone] || TONES.brand}`}>
      <p className="text-xs text-gray-500 mb-1 truncate" title={label}>{label}</p>
      <p className="text-xl font-black tabular-nums">{value}</p>
      {sub && <p className="text-xs mt-0.5 opacity-75">{sub}</p>}
    </div>
  )
}

export function BarRow({ label, value, max, sub, color = 'bg-brand-500' }) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex items-center gap-3 py-1">
      <div className="w-20 text-xs text-gray-600 shrink-0 tabular-nums">{label}</div>
      <div className="flex-1 h-3 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="w-24 text-left text-xs font-bold tabular-nums text-gray-700">{fmt(value)}</div>
      {sub !== undefined && <div className="w-36 text-left text-xs text-gray-500 tabular-nums">{sub}</div>}
    </div>
  )
}

export default function KpiCards({ data }) {
  if (!data) return null
  const hasGp = 'gp' in data
  const hasCalls = 'calls_in' in data
  const months = data.by_month || []
  const maxNet = Math.max(...months.map(m => Number(m.net) || 0), 1)
  return (
    <div className="space-y-4">
      {data.new_reliable_from && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠ عدد العملاء الجدد موثوق من {fmtDate(data.new_reliable_from)}
        </div>
      )}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3" data-tour="pic-analytics-kpis">
        <KpiCard label="عملاء (PIC) مميّزون" value={fmt(data.distinct_pics)} />
        <KpiCard label="جدد" value={fmt(data.new)} tone="green" />
        <KpiCard label="عائدون" value={fmt(data.returning)} tone="blue" sub={`منهم مُعاد تنشيطهم ${fmt(data.reactivated)}`} />
        <KpiCard label="زيارات" value={fmt(data.visits)} sub={`فواتير ${fmt(data.invoices)}`} />
        <KpiCard label="صافي المبيعات" value={fmt(data.net)} tone="green" sub={`بدون PIC: ${fmt(data.no_pic_net)}`} />
        {hasGp && <KpiCard label="إجمالي الربح" value={fmt(data.gp)} tone="amber" sub={`هامش ${fmtPct(data.gp_pct)}`} />}
        <KpiCard label="متوسط السلة (صافي)" value={fmt(data.basket_net, 2)} sub={`أصناف ${fmt(data.basket_units, 1)} · فئات ${fmt(data.basket_categories, 1)}`} />
        <KpiCard label="زيارات لكل عميل" value={fmt(data.visits_per_pic, 2)} />
        <KpiCard label="الاحتفاظ بالعملاء" value={fmtPct(data.retention_pct)} tone="blue" sub="من الفترة السابقة" />
        <KpiCard label="إجمالي الأصناف" value={fmt(data.units)} tone="gray" />
      </div>

      {hasCalls && (
        <div data-tour="pic-analytics-calls">
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
            <KpiCard label="مكالمات واردة" value={fmt(data.calls_in)} tone="gray" />
            <KpiCard label="مكالمات صادرة" value={fmt(data.calls_out)} tone="gray" />
            <KpiCard label="فائتة لم يُردّ عليها" value={fmt(data.missed_not_returned)} tone="red" />
          </div>
          <p className="text-xs text-gray-400 mt-1">كل مكالمات العملاء</p>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-4" data-tour="pic-analytics-trend">
        <h3 className="text-sm font-bold text-gray-700 mb-2">الاتجاه الشهري</h3>
        {months.length === 0 && <p className="text-xs text-gray-400">لا بيانات في الفترة</p>}
        {months.map(m => (
          <BarRow key={m.month} label={m.month} value={Number(m.net) || 0} max={maxNet}
                  sub={`${fmt(m.distinct_pics)} عميل · ${fmt(m.new)} جديد`} />
        ))}
      </div>
    </div>
  )
}
