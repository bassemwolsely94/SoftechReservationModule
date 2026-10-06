/**
 * CustomerDrawer — global Customer-360 side-drawer for the POS (and anywhere).
 *
 * Opens on `window` event `customer360:open` with `{ detail: { id } }`, so it
 * never steals focus from the basket. Renders the compact /pos-summary payload,
 * with clinical safety flags (allergies, pregnancy, chronic) surfaced FIRST —
 * an upsell must never bury them (rule 4). Read-only display; theme-aware.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { customersApi } from '../api/client'

export default function CustomerDrawer() {
  const [id, setId] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    const onOpen = (e) => setId(e?.detail?.id ?? null)
    const onKey = (e) => { if (e.key === 'Escape') setId(null) }
    window.addEventListener('customer360:open', onOpen)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('customer360:open', onOpen); window.removeEventListener('keydown', onKey) }
  }, [])

  useEffect(() => {
    if (!id) { setData(null); return }
    let alive = true
    setLoading(true)
    customersApi.posSummary(id)
      .then(({ data }) => { if (alive) setData(data) })
      .catch(() => { if (alive) setData(null) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [id])

  if (!id) return null
  const h = data?.health
  const dangers = []
  if (h?.allergies?.length) dangers.push({ t: `حساسية: ${h.allergies.join('، ')}`, sev: 'block' })
  if (h?.pregnancy) dangers.push({ t: 'حامل', sev: 'warn' })
  if (h?.lactation) dangers.push({ t: 'مُرضعة', sev: 'warn' })
  if (h?.pediatric) dangers.push({ t: 'طفل', sev: 'warn' })
  if (h?.polypharmacy) dangers.push({ t: 'تعدد أدوية', sev: 'warn' })

  return (
    <div className="fixed inset-0 z-[9997] flex justify-start" onMouseDown={() => setId(null)}>
      <div className="absolute inset-0 bg-black/30" />
      <aside dir="rtl"
             className="relative w-full max-w-sm h-full bg-surface border-e border-line shadow-2xl overflow-y-auto animate-slide-left"
             onMouseDown={(e) => e.stopPropagation()}>
        <div className="sticky top-0 bg-surface border-b border-line px-4 py-3 flex items-center justify-between">
          <div className="font-bold text-content">ملف العميل</div>
          <button onClick={() => setId(null)} className="text-faint hover:text-content text-lg leading-none">×</button>
        </div>

        {loading && <div className="p-6 text-center text-faint text-sm">…جارٍ التحميل</div>}
        {!loading && data && (
          <div className="p-4 space-y-4 text-sm">
            {/* identity */}
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold text-content">{data.crm.name}</span>
                {data.crm.is_guest && <span className="text-[10px] bg-amber-100 text-amber-800 rounded px-1">زائر</span>}
                {data.crm.segment_label && <span className="text-[10px] bg-brand-50 text-brand-700 rounded px-1">{data.crm.segment_label}</span>}
              </div>
              <div className="text-xs text-muted">{data.crm.phone}{data.crm.softech_pic ? ` · ${data.crm.softech_pic}` : ''}</div>
              <div className="text-[11px] text-faint">{data.crm.customer_type_label}</div>
            </div>

            {/* SAFETY — surfaced first */}
            {dangers.length > 0 && (
              <div className="rounded-xl border border-red-200 bg-red-50 p-2 space-y-1">
                <div className="text-[11px] font-bold text-red-700">⚠️ تنبيهات دوائية</div>
                <div className="flex flex-wrap gap-1">
                  {dangers.map((d, i) => (
                    <span key={i} className={`text-[10px] rounded px-1.5 py-0.5 border
                      ${d.sev === 'block' ? 'bg-red-100 text-red-700 border-red-300' : 'bg-amber-100 text-amber-800 border-amber-300'}`}>
                      {d.t}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* CRM stats */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <Stat label="LTV" value={data.crm.ltv != null ? Math.round(data.crm.ltv) : '—'} />
              <Stat label="مشتريات ٩٠ي" value={data.crm.purchase_count_90d} />
              <Stat label="آخر زيارة (يوم)" value={data.crm.days_since_last_visit ?? '—'} />
            </div>

            {/* health conditions */}
            {h?.conditions?.length > 0 && (
              <Section title="حالات مزمنة">
                <div className="flex flex-wrap gap-1">
                  {h.conditions.map((c, i) => <span key={i} className="text-[11px] bg-surface-2 border border-line rounded px-1.5 py-0.5 text-muted">{c}</span>)}
                </div>
              </Section>
            )}

            {/* loyalty */}
            {data.loyalty?.enrolled && (
              <Section title="الولاء">
                <div className="text-content"><span className="tabnum font-bold">{data.loyalty.points_balance}</span> نقطة</div>
              </Section>
            )}

            {/* purchases */}
            <Section title="المشتريات">
              <div className="text-xs text-muted">
                {data.purchases.total_count} فاتورة · إجمالي {Math.round(data.purchases.total_amount)} ج.م
                {data.purchases.last_invoice_date && ` · آخر فاتورة ${data.purchases.last_invoice_date.slice(0, 10)}`}
              </div>
            </Section>

            {/* open reservations */}
            {data.reservations.open_count > 0 && (
              <Section title={`حجوزات مفتوحة (${data.reservations.open_count})`}>
                <div className="space-y-1">
                  {data.reservations.recent.map((r) => (
                    <div key={r.id} className="text-[11px] text-muted flex justify-between">
                      <span className="truncate">{r.item_name}</span>
                      <span className="text-faint">{r.status_label}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            <button onClick={() => { navigate(`/customers/${data.crm.id}`); setId(null) }}
                    className="w-full mt-2 text-xs text-brand-600 border border-brand-200 rounded-lg py-2 hover:bg-brand-50">
              فتح الملف الكامل ←
            </button>
          </div>
        )}
      </aside>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="bg-surface-2 rounded-lg py-1.5">
      <div className="text-sm font-bold text-content tabnum">{value}</div>
      <div className="text-[10px] text-faint">{label}</div>
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div>
      <div className="text-[11px] font-bold text-faint mb-1">{title}</div>
      {children}
    </div>
  )
}
