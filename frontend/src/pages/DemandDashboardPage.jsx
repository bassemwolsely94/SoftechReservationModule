/**
 * DemandDashboardPage.jsx  —  /demand/dashboard
 * Lost Sales Analytics + Demand Intelligence
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { demandApi } from '../api/client'
import { tint } from '../theme/theme'

const BRAND  = 'rgb(var(--c-brand-600))'
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
    <div className="rounded-2xl p-4 border" style={{ background: bg, borderColor: tint(color, 0.2) }}>
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

  const { data: recon } = useQuery({
    queryKey: ['demand-reconciliation'],
    queryFn: () => demandApi.reconciliation().then(r => r.data),
    refetchInterval: 300_000,
  })

  const { data: suggestions } = useQuery({
    queryKey: ['demand-purchase-suggestions'],
    queryFn: () => demandApi.purchaseSuggestions().then(r => r.data),
    refetchInterval: 300_000,
  })

  const { data: leaderboard } = useQuery({
    queryKey: ['demand-capture-leaderboard', days],
    queryFn: () => demandApi.captureLeaderboard({ days }).then(r => r.data),
    refetchInterval: 300_000,
  })

  const { data: substitution } = useQuery({
    queryKey: ['demand-substitution-analytics'],
    queryFn: () => demandApi.substitutionAnalytics().then(r => r.data),
    refetchInterval: 300_000,
  })

  const { data: priceObj } = useQuery({
    queryKey: ['demand-price-objections'],
    queryFn: () => demandApi.priceObjections().then(r => r.data),
    refetchInterval: 300_000,
  })

  const [pushing, setPushing] = useState(false)
  async function pushSuggestions() {
    setPushing(true)
    try {
      const { data } = await demandApi.pushPurchaseSuggestions({})
      alert(`تم إرسال ${data.created} اقتراح شراء إلى لوحة المشتريات`)
    } catch (e) { alert(e.response?.data?.detail || 'تعذّر الإرسال') }
    finally { setPushing(false) }
  }
  function exportSuggestionsCsv() {
    const rows = suggestions?.suggestions || []
    const head = ['الكود', 'الصنف', 'الكمية المقترحة', 'عدد الطلبات', 'القيمة الضائعة', 'المخزون الحالي']
    const lines = rows.map(r => [r.softech_id || r.item__softech_id || '', (r.item__name || '').replace(/,/g, ' '),
      r.suggested_qty, r.demand_count, r.lost_value, r.network_stock].join(','))
    const csv = '﻿' + [head.join(','), ...lines].join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
    const a = document.createElement('a'); a.href = url; a.download = 'purchase_suggestions.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  const k            = data?.kpis || {}
  const fulfilledPct = k.fulfillment_rate ?? 0
  const lostPct      = k.lost_rate ?? 0
  const topItems     = data?.top_items || []
  const topLost      = data?.top_lost_items || []
  const branches     = data?.branch_performance || []
  const reasons      = data?.lost_by_reason || []
  const chronic      = data?.chronic_items || []
  const maxItem      = Math.max(...topItems.map(i => i.demand_count || 0), 1)
  const maxLostItem  = Math.max(...topLost.map(i => i.count || 0), 1)
  const maxBranch    = Math.max(...branches.map(b => b.total || 0), 1)
  const maxReason    = Math.max(...reasons.map(r => r.count || 0), 1)

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

          <button onClick={() => navigate('/demand')} className="btn-primary text-sm">
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
                value={k.total_30d} sub={`آخر ${days} يوم`}
                color={BRAND} bg="rgb(var(--c-brand-50))" />
              <KpiCard icon="✅" label="تم التوريد"
                value={`${fulfilledPct}%`} sub={`${k.fulfilled_30d ?? 0} طلب`}
                color={GREEN} bg="#f0fdf4" />
              <KpiCard icon="❌" label="بيع ضائع"
                value={k.lost_30d} sub={`${lostPct}% من الإجمالي`}
                color={RED} bg="#fef2f2" />
              <KpiCard icon="💰" label="قيمة مؤكدة ضائعة"
                value={`${(k.lost_value_30d || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م`}
                color={RED} bg="#fef2f2" />
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <KpiCard icon="🔄" label="نشط الآن"
                value={k.active} color={ORANGE} bg="#fffbeb" />
              <KpiCard icon="💰" label="إيراد مُسترَد"
                value={`${(k.recovered_revenue_30d || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م`}
                sub={`${k.recovered_count_30d ?? 0} بيعة`}
                color={GREEN} bg="#f0fdf4" />
              <KpiCard icon="🔔" label="متابعات متأخرة"
                value={k.overdue_followups} color={PURPLE} bg="#f5f3ff" />
              <KpiCard icon="🎯" label="فرص استرداد مفتوحة"
                value={k.open_recovery_count ?? 0}
                sub={`${(k.open_recovery_value || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م`}
                color={BLUE} bg="#eff6ff" />
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
              {topItems.length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد بيانات</div>
              ) : (
                <div className="space-y-3">
                  {topItems.map((item, i) => (
                    <HBar key={i}
                      label={item['item__name']}
                      value={item.demand_count}
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
              {branches.length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد بيانات</div>
              ) : (
                <div className="space-y-3">
                  {branches.map((b, i) => (
                    <div key={i} className="rounded-xl bg-gray-50 px-3 py-2.5">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-semibold text-gray-700 truncate">
                          {b.branch_name}
                        </span>
                        <div className="flex gap-2 text-xs shrink-0">
                          <span className="text-gray-500">{b.total} طلب</span>
                          <span style={{ color: GREEN }}>{b.fulfillment_rate}% توريد</span>
                          {b.lost > 0 && (
                            <span style={{ color: RED }}>❌{b.lost}</span>
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
              {chronic.length === 0 ? (
                <div className="text-center py-6 text-green-300 text-sm">
                  ✅ لا توجد أصناف نقص مزمن
                </div>
              ) : (
                <div className="space-y-2">
                  {chronic.map((item, i) => (
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
                        {item.demand_count_30d} طلب
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {chronic.length > 0 && (
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
                        {item.demand_count_30d} طلب
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

        {/* Lost-value reconciliation: confirmed (named) vs inferred (statistical) */}
        {recon && (
          <Section icon="🧮" title="مطابقة قيمة البيع الضائع — مؤكد مقابل تقديري">
            <div className="grid grid-cols-3 gap-3 mb-4">
              <div className="rounded-xl bg-green-50 border border-green-100 px-3 py-2.5">
                <div className="text-xs text-green-700 font-semibold">مؤكد (طلب باسم عميل)</div>
                <div className="text-lg font-black tabular-nums text-green-700">
                  {(recon.total_confirmed_lost_value || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م
                </div>
              </div>
              <div className="rounded-xl bg-red-50 border border-red-100 px-3 py-2.5">
                <div className="text-xs text-red-700 font-semibold">تقديري (محرك المشتريات)</div>
                <div className="text-lg font-black tabular-nums text-red-700">
                  {(recon.total_inferred_lost_revenue || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })} ج.م
                </div>
              </div>
              <div className="rounded-xl bg-blue-50 border border-blue-100 px-3 py-2.5">
                <div className="text-xs text-blue-700 font-semibold">نسبة الالتقاط</div>
                <div className="text-lg font-black tabular-nums text-blue-700">
                  {recon.overall_coverage_pct != null ? `${recon.overall_coverage_pct}%` : '—'}
                </div>
              </div>
            </div>
            <p className="text-xs text-gray-400 mb-3">
              "نسبة الالتقاط" = كم من الخسارة التقديرية تمكّنّا من ربطها بعميل حقيقي.
              ارتفاعها يعني تحسّن انضباط تسجيل الطلب الضائع.
              {recon.latest_calc_date && ` · أحدث تشغيل للمحرك: ${recon.latest_calc_date}`}
            </p>
            {(recon.items || []).length === 0 ? (
              <div className="text-center py-6 text-gray-300 text-sm">لا توجد بيانات مطابقة</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-100">
                    <tr>
                      <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الصنف</th>
                      <th className="text-left px-3 py-2 text-xs font-semibold text-green-600">مؤكد</th>
                      <th className="text-left px-3 py-2 text-xs font-semibold text-red-600">تقديري</th>
                      <th className="text-left px-3 py-2 text-xs font-semibold text-blue-600">الالتقاط</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recon.items.slice(0, 15).map(r => (
                      <tr key={r.item_id} className="border-b border-gray-50 last:border-0">
                        <td className="px-3 py-2">
                          <div className="text-sm text-gray-800 break-words max-w-[260px]">{r.item_name}</div>
                          <div className="text-[11px] text-gray-400 font-mono">{r.softech_id}</div>
                        </td>
                        <td className="px-3 py-2 text-left tabular-nums text-green-700 font-semibold">
                          {r.confirmed_lost_value.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                        </td>
                        <td className="px-3 py-2 text-left tabular-nums text-red-700">
                          {r.inferred_lost_revenue.toLocaleString('en-US', { maximumFractionDigits: 0 })}
                        </td>
                        <td className="px-3 py-2 text-left tabular-nums">
                          <span className={`badge text-xs ${
                            r.coverage_pct == null ? 'bg-gray-100 text-gray-500'
                            : r.coverage_pct >= 50 ? 'bg-green-100 text-green-700'
                            : r.coverage_pct > 0 ? 'bg-orange-100 text-orange-700'
                            : 'bg-red-100 text-red-700'
                          }`}>
                            {r.coverage_pct != null ? `${r.coverage_pct}%` : '—'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        )}

        {/* Demand-driven purchase suggestions */}
        {suggestions && (suggestions.suggestions || []).length > 0 && (
          <Section icon="🛒" title="اقتراحات الشراء المدفوعة بطلب العملاء">
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <p className="text-xs text-gray-400">
                أصناف طلبها عملاء حقيقيون (مفتوحة + ضائعة) — أعلى إشارة شراء ثقةً. مرتّبة حسب القيمة الضائعة المؤكدة.
              </p>
              <div className="flex gap-2">
                <button onClick={exportSuggestionsCsv} className="btn-secondary text-xs px-3">⬇ تصدير CSV</button>
                <button onClick={pushSuggestions} disabled={pushing}
                  className="text-xs px-3 py-1.5 rounded-lg text-white font-semibold disabled:opacity-50"
                  style={{ background: BRAND }}>
                  {pushing ? 'جارٍ...' : '📦 إرسال للمشتريات'}
                </button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الصنف</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-brand-600">الكمية المقترحة</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500">عدد الطلبات</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-red-600">قيمة ضائعة</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500">المخزون الآن</th>
                  </tr>
                </thead>
                <tbody>
                  {suggestions.suggestions.slice(0, 15).map(r => (
                    <tr key={r.item_id} className="border-b border-gray-50 last:border-0">
                      <td className="px-3 py-2">
                        <div className="text-sm text-gray-800 break-words max-w-[260px]">{r.item__name}</div>
                        <div className="text-[11px] text-gray-400 font-mono">{r.item__softech_id}</div>
                      </td>
                      <td className="px-3 py-2 text-left tabular-nums font-bold" style={{ color: BRAND }}>
                        {Math.round(r.suggested_qty).toLocaleString('en-US')}
                      </td>
                      <td className="px-3 py-2 text-left tabular-nums text-gray-600">{r.demand_count}</td>
                      <td className="px-3 py-2 text-left tabular-nums text-red-700">
                        {Math.round(r.lost_value).toLocaleString('en-US')} ج.م
                      </td>
                      <td className="px-3 py-2 text-left tabular-nums text-gray-500">
                        {Math.round(r.network_stock).toLocaleString('en-US')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {/* Capture leaderboard */}
        {leaderboard && (leaderboard.rows || []).length > 0 && (
          <Section icon="🏅" title={`لوحة تسجيل الطلب — الموظفون (آخر ${days} يوم)`}>
            <p className="text-xs text-gray-400 mb-3">
              مَن يسجّل طلبات العملاء غير المُلباة بدل أن يتركهم ينصرفون بصمت — انضباط البيانات يرفع كل المؤشرات.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">#</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الموظف</th>
                    <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500">الفرع</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-brand-600">طلبات</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-green-600">توريد %</th>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500">قيمة مُسجَّلة</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.rows.slice(0, 20).map((r, i) => (
                    <tr key={r.created_by} className="border-b border-gray-50 last:border-0">
                      <td className="px-3 py-2 text-gray-400 tabular-nums">{i + 1}</td>
                      <td className="px-3 py-2 font-semibold text-gray-800">{r.name}</td>
                      <td className="px-3 py-2 text-xs text-gray-500">{r.branch}</td>
                      <td className="px-3 py-2 text-left tabular-nums font-bold" style={{ color: BRAND }}>{r.total}</td>
                      <td className="px-3 py-2 text-left tabular-nums text-green-700">{r.fulfillment_rate}%</td>
                      <td className="px-3 py-2 text-left tabular-nums text-gray-600">
                        {Math.round(r.captured_value).toLocaleString('en-US')} ج.م
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )}

        {/* Substitution acceptance + Price objections */}
        {!isLoading && (
          <div className="grid md:grid-cols-2 gap-5">
            <Section icon="💊" title="بدائل يقبلها العملاء (نفس المادة الفعّالة)">
              {!substitution || (substitution.pairs || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد بدائل مُسجَّلة بعد</div>
              ) : (
                <>
                  <p className="text-xs text-gray-400 mb-3">
                    إجمالي {substitution.total_substitutions} استبدال — احمل البديل المقبول وفكّر في إيقاف الصنف الراكد.
                  </p>
                  <div className="space-y-2">
                    {substitution.pairs.slice(0, 10).map((p, i) => (
                      <div key={i} className="flex items-center justify-between bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-xs">
                        <div className="min-w-0">
                          <span className="text-gray-500 line-through break-words">{p.substitute_for_item__name}</span>
                          <span className="mx-1 text-blue-500">←</span>
                          <span className="font-semibold text-gray-800 break-words">{p.item__name}</span>
                        </div>
                        <span className="badge bg-blue-100 text-blue-700 shrink-0">{p.times}×</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Section>

            <Section icon="🏷️" title="أصناف فُقدت بسبب السعر">
              {!priceObj || (priceObj.items || []).length === 0 ? (
                <div className="text-center py-6 text-gray-300 text-sm">لا توجد مبيعات ضائعة بسبب السعر</div>
              ) : (
                <>
                  <p className="text-xs text-gray-400 mb-3">
                    {priceObj.total} حالة فقد بسبب اعتراض على السعر — إشارة لمراجعة التسعير.
                  </p>
                  <div className="space-y-2">
                    {priceObj.items.slice(0, 10).map((r, i) => (
                      <div key={i} className="flex items-center justify-between bg-orange-50 border border-orange-100 rounded-lg px-3 py-2 text-xs">
                        <div className="min-w-0">
                          <div className="font-semibold text-gray-800 break-words">{r.item__name}</div>
                          <div className="text-[11px] text-gray-400">سعرنا: {Math.round(r.current_price).toLocaleString('en-US')} ج.م</div>
                        </div>
                        <div className="text-left shrink-0">
                          <span className="badge bg-orange-100 text-orange-700">{r.count}×</span>
                          <div className="text-[11px] text-red-600 mt-0.5">{Math.round(r.lost_value).toLocaleString('en-US')} ج.م</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </Section>
          </div>
        )}

      </div>
    </div>
  )
}
