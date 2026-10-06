/**
 * FocAnalysisPage.jsx
 *
 * Free-of-Charge (FOC) & Cost Intelligence Analysis:
 *   - Network FOC rate + trend
 *   - Top FOC suppliers (generosity ranking)
 *   - Effective cost vs nominal cost comparison
 *   - Expiry return analysis
 *   - Tax burden summary
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { procurementIntelApi } from '../api/client'
import { useProcurementFilters } from '../components/ProcurementFilters'

const fmt  = (n, dp = 2) => n == null ? '—' : Number(n).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
const fmtK = (n)          => n == null ? '—' : `${(Number(n) / 1000).toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}K`

const DAYS_OPTIONS = [
  { value: 30,  label: '30 يوم' },
  { value: 90,  label: '90 يوم' },
  { value: 180, label: '180 يوم' },
  { value: 365, label: '365 يوم' },
]

function KpiCard({ icon, label, value, sub, valueClass = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs text-gray-500 font-medium mb-1">{label}</div>
          <div className={`text-2xl font-bold ${valueClass}`}>{value}</div>
          {sub && <div className="text-xs text-gray-400 mt-0.5">{sub}</div>}
        </div>
        <div className="text-2xl opacity-70">{icon}</div>
      </div>
    </div>
  )
}

function MiniBar({ value, max, colorClass = 'bg-brand-500' }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-gray-100 rounded-full h-1.5">
        <div className={`h-1.5 rounded-full ${colorClass}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right dir-ltr">{fmt(value, 1)}%</span>
    </div>
  )
}

function SimpleBarChart({ data, labelKey, valueKey, colorClass, maxValue }) {
  const max = maxValue ?? Math.max(...data.map(d => d[valueKey] || 0), 1)
  return (
    <div className="space-y-2">
      {data.map((row, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="text-xs text-gray-600 w-32 truncate text-right">{row[labelKey]}</div>
          <div className="flex-1 bg-gray-100 rounded-full h-4 overflow-hidden">
            <div
              className={`h-full rounded-full flex items-center justify-end pr-2 ${colorClass}`}
              style={{ width: `${Math.max(4, (row[valueKey] / max) * 100)}%` }}>
              <span className="text-xs text-white font-medium">{fmt(row[valueKey], 1)}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default function FocAnalysisPage() {
  const { params } = useProcurementFilters()
  const [activeTab, setActiveTab] = useState('foc')

  const focQ = useQuery({
    queryKey: ['foc-analysis', params],
    queryFn:  () => procurementIntelApi.focAnalysis(params).then(r => r.data),
    keepPreviousData: true,
  })

  const expiryQ = useQuery({
    queryKey: ['expiry-returns', params],
    queryFn:  () => procurementIntelApi.expiryReturns(params).then(r => r.data),
    keepPreviousData: true,
  })

  const taxQ = useQuery({
    queryKey: ['tax-burden', params],
    queryFn:  () => procurementIntelApi.taxBurden(params).then(r => r.data),
    keepPreviousData: true,
  })

  const foc    = focQ.data
  const expiry = expiryQ.data
  const tax    = taxQ.data

  const TABS = [
    { id: 'foc',    label: '🎁 تحليل FOC',      data: foc },
    { id: 'expiry', label: '⚠️ مرتجعات التالف', data: expiry },
    { id: 'tax',    label: '🧾 العبء الضريبي',   data: tax },
  ]

  return (
    <div className="p-6 space-y-5" dir="rtl">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">تحليل التكلفة الفعلية والكفاءة الشرائية</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            FOC · مرتجعات التالف · الضرائب · التكلفة الحقيقية — حسب الفلاتر أعلاه
          </p>
        </div>
      </div>

      {/* Quick KPIs row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          icon="🎁"
          label="البضاعة المجانية (بونص)"
          value={`${fmt(foc?.overall?.bonus_units, 0)}`}
          sub={`وحدة مجانية · ${fmt(foc?.overall?.bonus_unit_pct, 1)}% من الكمية · ${fmt(foc?.overall?.bonus_lines)} سطر`}
          valueClass={foc?.overall?.bonus_units > 0 ? 'text-emerald-600' : 'text-gray-900'}
        />
        <KpiCard
          icon="⚠️"
          label="مرتجعات التالف"
          value={`${fmt(expiry?.summary?.expiry_pct, 1)}%`}
          sub={`${fmt(expiry?.summary?.expiry_returns)} من ${fmt(expiry?.summary?.total_returns)} مرتجع`}
          valueClass={expiry?.summary?.expiry_pct > 30 ? 'text-red-600' : 'text-gray-900'}
        />
        <KpiCard
          icon="🧾"
          label="نسبة الضريبة (VAT)"
          value={`${fmt(tax?.overall?.tax_rate_pct, 2)}%`}
          sub={`إجمالي ضريبة: ${fmtK(tax?.overall?.total_vat)} ج.م`}
          valueClass={tax?.overall?.tax_rate_pct > 5 ? 'text-amber-600' : 'text-gray-900'}
        />
        <KpiCard
          icon="📊"
          label="فرق التكلفة الفعلية"
          value={foc?.overall ? `${fmt(((foc.overall.avg_effective_cost - foc.overall.avg_unit_price) / (foc.overall.avg_unit_price || 1)) * 100, 1)}%` : '—'}
          sub="تكلفة فعلية مقارنة بسعر الوحدة"
          valueClass="text-gray-900"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
        {TABS.map(tab => (
          <button key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.id
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* FOC Tab */}
      {activeTab === 'foc' && (
        <div className="grid md:grid-cols-2 gap-4">

          {/* Top FOC suppliers */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">🎁 أكثر الموردين كرمًا (أعلى بونص)</h3>
            {focQ.isLoading ? (
              <div className="animate-pulse space-y-2">
                {[...Array(6)].map((_, i) => <div key={i} className="h-6 bg-gray-100 rounded" />)}
              </div>
            ) : (
              <div className="space-y-2.5">
                {(foc?.top_foc_suppliers ?? []).slice(0, 10).map((s, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className="w-5 text-xs text-gray-400 text-center">{i + 1}</div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-800 truncate">
                        {s.supplier_name || s.supplier_code}
                      </div>
                      <div className="text-xs text-gray-400">
                        {fmt(s.bonus_units, 0)} وحدة بونص · {fmt(s.foc_lines)} سطر FOC
                      </div>
                    </div>
                    <MiniBar value={s.foc_rate_pct} max={100} colorClass="bg-emerald-500" />
                  </div>
                ))}
                {(foc?.top_foc_suppliers ?? []).length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-6">
                    لا يوجد بيانات FOC في هذه الفترة
                  </p>
                )}
              </div>
            )}
          </div>

          {/* FOC monthly trend */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">📈 اتجاه FOC الشهري</h3>
            {focQ.isLoading ? (
              <div className="animate-pulse h-48 bg-gray-100 rounded" />
            ) : (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {(foc?.monthly_trend ?? []).map((m, i) => (
                  <div key={i} className="flex items-center gap-3 text-sm">
                    <div className="w-16 text-xs text-gray-500">{m.month}</div>
                    <div className="flex-1">
                      <div className="bg-gray-100 rounded-full h-3 overflow-hidden">
                        <div className="bg-emerald-400 h-full rounded-full"
                          style={{ width: `${Math.min(100, m.foc_rate)}%` }} />
                      </div>
                    </div>
                    <div className="w-16 text-xs text-gray-600 text-left dir-ltr">
                      {fmt(m.foc_rate, 1)}%
                      <span className="text-gray-400 mr-1">({m.foc_lines}/{m.total_lines})</span>
                    </div>
                  </div>
                ))}
                {(foc?.monthly_trend ?? []).length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-6">لا توجد بيانات</p>
                )}
              </div>
            )}
          </div>

          {/* Effective cost comparison */}
          <div className="md:col-span-2 bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">⚖️ مقارنة التكلفة: الاسمية vs الفعلية</h3>
            {foc?.overall && (
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center p-4 bg-blue-50 rounded-xl">
                  <div className="text-xs text-gray-500 mb-1">متوسط سعر الوحدة (اسمي)</div>
                  <div className="text-2xl font-bold text-blue-700">{fmt(foc.overall.avg_unit_price, 4)}</div>
                  <div className="text-xs text-gray-400">ج.م / وحدة</div>
                </div>
                <div className="text-center p-4 bg-emerald-50 rounded-xl">
                  <div className="text-xs text-gray-500 mb-1">التكلفة الفعلية (بعد FOC + ضريبة)</div>
                  <div className="text-2xl font-bold text-emerald-700">{fmt(foc.overall.avg_effective_cost, 4)}</div>
                  <div className="text-xs text-gray-400">ج.م / وحدة</div>
                </div>
                <div className="text-center p-4 bg-gray-50 rounded-xl">
                  <div className="text-xs text-gray-500 mb-1">الفرق (تأثير FOC)</div>
                  <div className={`text-2xl font-bold ${
                    foc.overall.avg_effective_cost < foc.overall.avg_unit_price
                      ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {foc.overall.avg_unit_price > 0
                      ? `${fmt(((foc.overall.avg_effective_cost - foc.overall.avg_unit_price) / foc.overall.avg_unit_price) * 100, 2)}%`
                      : '—'}
                  </div>
                  <div className="text-xs text-gray-400">
                    {foc.overall.avg_effective_cost <= foc.overall.avg_unit_price
                      ? '✅ تكلفة أقل من الاسمي' : '⚠️ تكلفة أعلى من الاسمي'}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Expiry Returns Tab */}
      {activeTab === 'expiry' && (
        <div className="grid md:grid-cols-2 gap-4">

          {/* Summary */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">⚠️ ملخص مرتجعات التالف</h3>
            {expiryQ.isLoading ? (
              <div className="animate-pulse space-y-2">
                {[...Array(4)].map((_, i) => <div key={i} className="h-10 bg-gray-100 rounded" />)}
              </div>
            ) : (
              <div className="space-y-3">
                {[
                  { label: 'إجمالي المرتجعات', value: fmt(expiry?.summary?.total_returns) },
                  { label: 'مرتجعات التالف', value: fmt(expiry?.summary?.expiry_returns), className: 'text-red-600' },
                  { label: 'مرتجعات عادية', value: fmt(expiry?.summary?.normal_returns), className: 'text-blue-600' },
                  { label: 'نسبة التالف', value: `${fmt(expiry?.summary?.expiry_pct, 1)}%`, className: expiry?.summary?.expiry_pct > 30 ? 'text-red-600 font-bold' : 'text-gray-800' },
                  { label: 'قيمة مرتجعات التالف', value: `${fmtK(expiry?.summary?.expiry_value)} ج.م`, className: 'text-red-600' },
                ].map(row => (
                  <div key={row.label} className="flex justify-between items-center py-2 border-b border-gray-50">
                    <span className="text-sm text-gray-600">{row.label}</span>
                    <span className={`font-semibold ${row.className || 'text-gray-800'}`}>{row.value}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Monthly trend */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">📅 الاتجاه الشهري للمرتجعات</h3>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {(expiry?.monthly_trend ?? []).map((m, i) => {
                const total = (m.expiry || 0) + (m.normal || 0)
                const expiryPct = total > 0 ? (m.expiry / total) * 100 : 0
                return (
                  <div key={i} className="flex items-center gap-3 text-sm">
                    <div className="w-16 text-xs text-gray-500">{m.month}</div>
                    <div className="flex-1 flex gap-0.5 h-4 rounded overflow-hidden bg-gray-100">
                      {m.expiry > 0 && (
                        <div className="bg-red-400" style={{ width: `${expiryPct}%` }}
                          title={`تالف: ${m.expiry}`} />
                      )}
                      {m.normal > 0 && (
                        <div className="bg-blue-300" style={{ width: `${100 - expiryPct}%` }}
                          title={`عادي: ${m.normal}`} />
                      )}
                    </div>
                    <div className="text-xs text-gray-500 w-20 text-left dir-ltr">
                      <span className="text-red-500">{m.expiry}</span>
                      <span className="text-gray-400"> / </span>
                      <span className="text-blue-500">{m.normal}</span>
                    </div>
                  </div>
                )
              })}
            </div>
            <div className="flex gap-3 mt-2 text-xs text-gray-500">
              <span><span className="inline-block w-3 h-3 bg-red-400 rounded mr-1" />تالف</span>
              <span><span className="inline-block w-3 h-3 bg-blue-300 rounded mr-1" />عادي</span>
            </div>
          </div>

          {/* Top items returned as expired */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">📦 أكثر الأصناف إرجاعًا كتالف</h3>
            {expiryQ.isLoading ? (
              <div className="animate-pulse space-y-2">
                {[...Array(5)].map((_, i) => <div key={i} className="h-6 bg-gray-100 rounded" />)}
              </div>
            ) : (
              <SimpleBarChart
                data={(expiry?.top_items ?? []).slice(0, 12)}
                labelKey="item_code"
                valueKey="expiry_count"
                colorClass="bg-red-400"
              />
            )}
          </div>

          {/* Top branches with expiry returns */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">🏪 أكثر الفروع في مرتجعات التالف</h3>
            {expiryQ.isLoading ? (
              <div className="animate-pulse space-y-2">
                {[...Array(5)].map((_, i) => <div key={i} className="h-6 bg-gray-100 rounded" />)}
              </div>
            ) : (
              <SimpleBarChart
                data={(expiry?.top_branches ?? []).slice(0, 10)}
                labelKey="branch_code"
                valueKey="expiry_count"
                colorClass="bg-amber-400"
              />
            )}
          </div>
        </div>
      )}

      {/* Tax Burden Tab */}
      {activeTab === 'tax' && (
        <div className="grid md:grid-cols-2 gap-4">

          {/* Summary */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">🧾 ملخص العبء الضريبي</h3>
            {taxQ.isLoading ? (
              <div className="animate-pulse space-y-2">
                {[...Array(4)].map((_, i) => <div key={i} className="h-10 bg-gray-100 rounded" />)}
              </div>
            ) : (
              <div className="space-y-3">
                {[
                  { label: 'إجمالي قيمة المشتريات', value: `${fmtK(tax?.overall?.total_purchase_value)} ج.م` },
                  { label: 'إجمالي الضريبة (VAT)', value: `${fmtK(tax?.overall?.total_vat)} ج.م`, className: 'text-amber-700' },
                  { label: 'نسبة الضريبة', value: `${fmt(tax?.overall?.tax_rate_pct, 3)}%`, className: tax?.overall?.tax_rate_pct > 5 ? 'text-red-600 font-bold' : 'text-gray-800' },
                  { label: 'فواتير بضريبة', value: fmt(tax?.overall?.lines_with_vat) },
                ].map(row => (
                  <div key={row.label} className="flex justify-between items-center py-2 border-b border-gray-50">
                    <span className="text-sm text-gray-600">{row.label}</span>
                    <span className={`font-semibold ${row.className || 'text-gray-800'}`}>{row.value}</span>
                  </div>
                ))}
                {tax?.overall?.total_vat === 0 && (
                  <div className="text-sm text-gray-400 text-center py-4">
                    💡 لا يوجد بيانات ضريبة — قد لا يدعم نظام SOFTECH حقل docvat في نسختك
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Monthly tax trend */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">📅 الاتجاه الشهري للضريبة</h3>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {(tax?.monthly_trend ?? []).map((m, i) => (
                <div key={i} className="flex items-center gap-3 text-sm">
                  <div className="w-16 text-xs text-gray-500">{m.month}</div>
                  <div className="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
                    <div className="bg-amber-400 h-full rounded-full"
                      style={{ width: `${Math.min(100, m.tax_rate_pct * 10)}%` }} />
                  </div>
                  <div className="text-xs text-amber-700 w-16 text-left dir-ltr font-medium">
                    {fmt(m.tax_rate_pct, 2)}%
                  </div>
                </div>
              ))}
              {(tax?.monthly_trend ?? []).length === 0 && (
                <p className="text-sm text-gray-400 text-center py-6">لا توجد بيانات ضريبة</p>
              )}
            </div>
          </div>

          {/* Top suppliers by tax burden */}
          <div className="md:col-span-2 bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <h3 className="font-semibold text-gray-800 mb-3">🏆 أعلى الموردين من حيث العبء الضريبي</h3>
            {taxQ.isLoading ? (
              <div className="animate-pulse space-y-2">
                {[...Array(5)].map((_, i) => <div key={i} className="h-8 bg-gray-100 rounded" />)}
              </div>
            ) : (tax?.by_supplier ?? []).length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-8">
                لا توجد بيانات ضريبة متاحة — قد يحتاج تفعيل حقل docvat في نظام SOFTECH
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b border-gray-100">
                    <tr>
                      {['المورد', 'إجمالي الشراء', 'إجمالي الضريبة', 'نسبة الضريبة'].map(h => (
                        <th key={h} className="px-3 py-2 text-right text-xs font-semibold text-gray-600">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {(tax?.by_supplier ?? []).map((s, i) => (
                      <tr key={i} className="hover:bg-gray-50">
                        <td className="px-3 py-2">
                          <div className="font-medium text-gray-800">{s.supplier_name || s.supplier_code}</div>
                          <div className="text-xs text-gray-400">{s.supplier_code}</div>
                        </td>
                        <td className="px-3 py-2 text-left dir-ltr text-gray-700">{fmtK(s.total_value)} ج.م</td>
                        <td className="px-3 py-2 text-left dir-ltr text-amber-700 font-medium">{fmtK(s.total_vat)} ج.م</td>
                        <td className="px-3 py-2 text-left dir-ltr">
                          <span className={`font-medium ${s.tax_rate_pct > 5 ? 'text-red-600' : 'text-gray-700'}`}>
                            {fmt(s.tax_rate_pct, 2)}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
