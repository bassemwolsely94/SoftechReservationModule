/**
 * DemandDashboardPage.jsx  —  /demand/dashboard
 * Lost Sales Analytics + Demand Intelligence
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { demandApi } from '../api/client'

const BRAND  = '#1B6B3A'
const GREEN  = '#10b981'
const ORANGE = '#f59e0b'
const RED    = '#ef4444'
const PURPLE = '#8b5cf6'
const BLUE   = '#3b82f6'
const GRAY   = '#9ca3af'

const LOST_REASON_LABELS = {
  no_stock:     'لا يوجد مخزون',
  delayed:      'تأخر — اشترى من مكان آخر',
  discontinued: 'متوقف',
  no_response:  'لا يوجد رد',
  price:        'رفض السعر',
  other:        'أخرى',
}

// ── Simple horizontal bar chart (pure CSS) ────────────────────────────────────

function HBar({ label, value, max, color, subLabel }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="group">
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-gray-600 font-medium truncate flex-1">{label}</span>
        <span className="font-bold tabular-nums mr-2" style={{ color }}>
          {value}{subLabel ? ` ${subLabel}` : ''}
        </span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  )
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({ icon, label, value, sub, color, bg }) {
  return (
    <div className="rounded-2xl p-4 border" style={{ background: bg, borderColor: color + '33' }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold" style={{ color }}>{label}</span>
        <span className="text-xl">{icon}</span>
      </div>
      <div className="text-3xl font-black tabular-nums" style={{ color }}>{value ?? '—'}</div>
      {sub && <div className="text-xs mt-1 opacity-60" style={{ color }}>{sub}</div>}
    </div>
  )
}

// ── Section title ─────────────────────────────────────────────────────────────

function Section({ icon, title, children }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
      <h3 className="text-sm font-bold text-gray-700 flex items-center gap-2 mb-4">
        <span className="w-1 h-4 rounded-full inline-block" style={{ background: BRAND }} />
        <span>{icon}</span>{title}
      </h3>
      {children}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function DemandDashboardPage() {
  const navigate = useNavigate()
  const [days, setDays] = useState(30)

  const { data, isLoading } = useQuery({
    queryKey: ['demand-dashboard', days],
    queryFn: () => demandApi.dashboard({ days }).then(r => r.data),
    refetchInterval: 120_000,
  })

  const fulfilledPct = data?.fulfillment_rate ?? 0
  const lostPct      = data?.total ? Math.round(data.lost / data.total * 100) : 0
  const maxItem      = Math.max(...(data?.top_demanded_items || []).map(i => i.count), 1)
  const maxLostItem  = Math.max(...(data?.top_lost_items || []).map(i => i.count), 1)
  const maxBranch    = Math.max(...(data?.by_branch || []).map(b => b.total), 1)
  const maxReason    = Math.max(...(data?.lost_by_reason || []).map(r => r.count), 1)

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto flex items-center gap-4 flex-wrap">
          <button onClick={() => navigate('/demand')}
            className="text-gray-400 hover:text-gray-700 p-1 rounded-lg hover:bg-gray-100 shrink-0">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="flex-1">
            <h1 className="text-xl font-black text-gray-900">
              📊 لوحة الطلب الضائع والتحليلات
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">
              رؤية الطلب غير المُستوفى · تحسين المشتريات · رفع الإيرادات
            </p>
          </div>

          {/* Window selector */}
          <div className="flex items-center gap-1 border border-gray-200 rounded-lg overflow-hidden text-xs">
            {[7, 14, 30, 60, 90].map(d => (
              <button key={d} onClick={() => setDays(d)}
                className="px-3 py-1.5 font-semibold transition-colors"
                style={days === d ? { background: BRAND, color: 'white' } : { color: '#6b7280' }}>
                {d} يوم
              </button>
            ))}
          </div>

          <button onClick={() => navigate('/demand/new')} className="btn-primary text-sm">
            + تسجيل طلب جديد
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-5">

        {/* KPI strip */}
        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[1,2,3,4].map(i => (
              <div key={i} className="h-24 bg-gray-100 rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard icon="📋" label="إجمالي الطلبات"
                value={data?.total} sub={`آخر ${days} يوم`}
                color={BRAND} bg="#f0f9f4" />
              <KpiCard icon="✅" label="تم التوريد"
                value={`${fulfilledPct}%`} sub={`${data?.fulfilled} طلب`}
                color={GREEN} bg="#f0fdf4" />
              <KpiCard icon="❌" label="بيع ضائع"
                value={data?.lost} sub={`${lostPct}% من الإجمالي`}
                color={RED} bg="#fef2f2" />
              <KpiCard icon="💰" label="قيمة مقدرة ضائعة"
                value={`${(data?.lost_value_egp || 0).toLocaleString('ar-EG', { maximumFractionDigits: 0 })} ج.م`}
                color={RED} bg="#fef2f2" />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard icon="🔄" label="نشط الآن"
                value={data?.active} color={ORANGE} bg="#fffbeb" />
              <KpiCard icon="⚠️" label="تجاوز SLA"
                value={data?.sla_breaches} color={RED} bg="#fef2f2" />
              <KpiCard icon="🔔" label="متابعات متأخرة"
                value={data?.overdue_followups} color={PURPLE} bg="#f5f3ff" />
              <KpiCard icon="💊" label="أصناف نقص مزمن"
                value={data?.chronic_shortages?.length ?? 0} color={ORANGE} bg="#fffbeb" />
            </div>
          </>
        )}

        {/* Top lost items + top demanded items */}
        {!isLoading && (
          <div className="grid md:grid-cols-2 gap-5">
            <Section icon="❌" title="الأصناف الأكثر تسجيلاً كبيع ضائع">
              {(data?.top_lost_items || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">
                  🎉 لا توجد مبيعات ضائعة!
                </div>
              ) : (
                <div className="space-y-3">
                  {data.top_lost_items.map((item, i) => (
                    <HBar key={i}
                      label={item['item__name']}
                      value={item.count}
                      max={maxLostItem}
                      color={RED}
                      subLabel="مرة" />
                  ))}
                </div>
              )}
            </Section>

            <Section icon="📋" title="الأصناف الأكثر طلباً (كل الحالات)">
              {(data?.top_demanded_items || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد بيانات</div>
              ) : (
                <div className="space-y-3">
                  {data.top_demanded_items.map((item, i) => (
                    <HBar key={i}
                      label={item['item__name']}
                      value={item.count}
                      max={maxItem}
                      color={BRAND}
                      subLabel="طلب" />
                  ))}
                </div>
              )}
            </Section>
          </div>
        )}

        {/* Lost by reason + branch performance */}
        {!isLoading && (
          <div className="grid md:grid-cols-2 gap-5">
            <Section icon="🔍" title="أسباب البيع الضائع">
              {(data?.lost_by_reason || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد بيانات</div>
              ) : (
                <div className="space-y-3">
                  {data.lost_by_reason.map((r, i) => (
                    <HBar key={i}
                      label={LOST_REASON_LABELS[r.lost_reason] || r.lost_reason}
                      value={r.count}
                      max={maxReason}
                      color={RED}
                      subLabel="حالة" />
                  ))}
                </div>
              )}
            </Section>

            <Section icon="🏥" title="أداء الفروع">
              {(data?.by_branch || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد بيانات</div>
              ) : (
                <div className="space-y-3">
                  {data.by_branch.map((b, i) => (
                    <div key={i} className="rounded-xl bg-gray-50 px-3 py-2.5">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-semibold text-gray-700 truncate">
                          {b.branch_name}
                        </span>
                        <div className="flex gap-2 text-xs shrink-0">
                          <span className="text-gray-500">{b.total} طلب</span>
                          <span style={{ color: GREEN }}>{b.fulfillment_rate}% توريد</span>
                          {b.sla_breach > 0 && (
                            <span style={{ color: RED }}>⚠{b.sla_breach}</span>
                          )}
                        </div>
                      </div>
                      <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div className="h-full rounded-full"
                          style={{
                            width: `${Math.round(b.total / maxBranch * 100)}%`,
                            background: BRAND,
                          }} />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          </div>
        )}

        {/* Chronic shortages + discontinued */}
        {!isLoading && (
          <div className="grid md:grid-cols-2 gap-5">
            <Section icon="⏳" title="أصناف نقص مزمن (طلب متكرر غير مُستوفى)">
              {(data?.chronic_shortages || []).length === 0 ? (
                <div className="text-center py-6 text-green-300 text-sm">
                  ✅ لا توجد أصناف نقص مزمن
                </div>
              ) : (
                <div className="space-y-2">
                  {data.chronic_shortages.map((item, i) => (
                    <div key={i} className="flex items-center justify-between
                      bg-orange-50 border border-orange-100 rounded-lg px-3 py-2">
                      <div>
                        <div className="text-sm font-semibold text-gray-800">
                          {item['item__name']}
                        </div>
                        <div className="text-xs text-gray-400 font-mono">
                          {item['item__softech_id']}
                        </div>
                      </div>
                      <span className="badge bg-orange-100 text-orange-700 text-xs">
                        {item.count} طلب نشط
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {(data?.chronic_shortages || []).length > 0 && (
                <div className="mt-3 text-xs text-orange-600 bg-orange-50 border border-orange-100 rounded-lg px-3 py-2">
                  💡 يُنصح بإضافة هذه الأصناف للأوردر الدوري أو طلب تحويل مخزون
                </div>
              )}
            </Section>

            <Section icon="🚫" title="أصناف متوقفة مع طلب نشط">
              {(data?.discontinued || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">
                  لا توجد أصناف متوقفة بطلب نشط
                </div>
              ) : (
                <div className="space-y-2">
                  {data.discontinued.map((item, i) => (
                    <div key={i} className="flex items-center justify-between
                      bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                      <div>
                        <div className="text-sm font-semibold text-gray-800">
                          {item['item__name']}
                        </div>
                        <div className="text-xs text-gray-400 font-mono">
                          {item['item__softech_id']}
                        </div>
                      </div>
                      <span className="badge bg-red-100 text-red-700 text-xs">
                        {item.count} طلب
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {(data?.discontinued || []).length > 0 && (
                <div className="mt-3 text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">
                  ⚠️ يجب إغلاق هذه الطلبات أو إبلاغ العملاء بعدم التوفر
                </div>
              )}
            </Section>
          </div>
        )}

      </div>
    </div>
  )
}
