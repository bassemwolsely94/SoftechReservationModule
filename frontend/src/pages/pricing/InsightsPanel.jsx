/**
 * InsightsPanel — admin dashboards for the pricing module:
 *   #4 Branch health board
 *   #11 Who-changed-what (module vs direct SOFTECH edits)
 *   #5 Auto-repair policy toggle
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../../api/client'

function fmtDate(s) {
  if (!s) return '—'
  return new Date(s).toLocaleString('ar-EG', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

const HEALTH = {
  healthy: { label: 'سليم', cls: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500' },
  lagging: { label: 'متأخر', cls: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500' },
  down:    { label: 'متوقف', cls: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
}

export default function InsightsPanel() {
  const qc = useQueryClient()
  const [days, setDays] = useState(30)

  const { data: health } = useQuery({
    queryKey: ['branch-health'],
    queryFn: () => pricingApprovalsApi.branchHealth().then(r => r.data),
    refetchInterval: 60000,
  })
  const { data: who } = useQuery({
    queryKey: ['who-changed', days],
    queryFn: () => pricingApprovalsApi.whoChangedWhat(days).then(r => r.data),
  })
  const { data: impact } = useQuery({
    queryKey: ['discount-impact', days],
    queryFn: () => pricingApprovalsApi.discountImpact(days).then(r => r.data),
  })
  const { data: policy } = useQuery({
    queryKey: ['repl-policy'],
    queryFn: () => pricingApprovalsApi.policyGet().then(r => r.data),
  })
  const savePolicy = useMutation({
    mutationFn: (d) => pricingApprovalsApi.policySet(d),
    onSuccess: () => qc.invalidateQueries(['repl-policy']),
  })

  return (
    <div className="space-y-5" dir="rtl">

      {/* ── #4 Branch health board ─────────────────────────────────────────── */}
      <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between">
          <h3 className="font-bold text-gray-800 text-sm">صحة الفروع — حالة النسخ المتماثل</h3>
          <span className="text-xs text-gray-400">
            آخر فحص: {health?.latest_scan_at ? fmtDate(health.latest_scan_at) : '— شغّل فحصاً أولاً'}
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 p-4">
          {(health?.branches || []).map(b => {
            const h = HEALTH[b.health] || HEALTH.healthy
            return (
              <div key={b.branch_code} className="border border-gray-200 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${h.dot}`} />
                    <span className="font-mono text-sm">{b.branch_code}</span>
                    <span className="text-xs text-gray-400 truncate max-w-[120px]">{b.branch_name}</span>
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${h.cls}`}>{h.label}</span>
                </div>
                <div className="mt-2 flex gap-4 text-xs text-gray-600">
                  <span>متأخرة: <b className={b.stale_items ? 'text-amber-600' : ''}>{b.stale_items}</b></span>
                  {b.unreachable_items > 0 && <span className="text-red-600">غير متصلة: <b>{b.unreachable_items}</b></span>}
                </div>
                <div className="mt-1 text-[11px] text-gray-400">
                  آخر حالة سليمة: {fmtDate(b.last_clean_scan_at)}
                </div>
              </div>
            )
          })}
          {!health?.branches?.length && (
            <div className="col-span-full text-center text-gray-400 text-sm py-6">
              لا توجد بيانات — شغّل فحص النسخ المتماثل من تبويب التدقيق
            </div>
          )}
        </div>
      </section>

      {/* ── #11 Who-changed-what ───────────────────────────────────────────── */}
      <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b flex items-center justify-between flex-wrap gap-2">
          <h3 className="font-bold text-gray-800 text-sm">من غيّر الأسعار — عبر الوحدة مقابل تعديل مباشر</h3>
          <select value={days} onChange={e => setDays(+e.target.value)}
            className="border border-gray-300 rounded px-2 py-1 text-xs">
            {[7, 14, 30, 60, 90].map(d => <option key={d} value={d}>آخر {d} يوم</option>)}
          </select>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-gray-800">{who?.total_hq_edits ?? '—'}</div>
              <div className="text-xs text-gray-500">إجمالي تعديلات Softech</div>
            </div>
            <div className="bg-blue-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-blue-700">{who?.module_executed ?? '—'}</div>
              <div className="text-xs text-blue-600">عبر الوحدة</div>
            </div>
            <div className="bg-amber-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-amber-700">{who?.module_share_pct ?? 0}%</div>
              <div className="text-xs text-amber-600">نسبة المرور بالموافقات</div>
            </div>
          </div>
          {who && who.module_share_pct < 50 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-800 mb-3">
              ⚠ معظم تعديلات الأسعار ({100 - who.module_share_pct}%) تُجرى مباشرةً في Softech وتتجاوز سير الموافقات.
            </div>
          )}
          <div className="text-xs font-semibold text-gray-500 mb-1">أكثر المعدّلين مباشرةً في Softech</div>
          <table className="w-full text-sm">
            <tbody>
              {(who?.by_user_softech || []).slice(0, 10).map(u => (
                <tr key={u.usercode} className="border-b border-gray-100">
                  <td className="py-1.5 text-gray-700">{u.name}</td>
                  <td className="py-1.5 text-gray-400 text-xs font-mono">{u.usercode}</td>
                  <td className="py-1.5 text-left font-semibold">{u.edits}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── #10 Discount impact ────────────────────────────────────────────── */}
      <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b">
          <h3 className="font-bold text-gray-800 text-sm">أثر الخصومات على المبيعات</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            مقارنة مبيعات الصنف قبل/بعد تغيير الخصم ({days} يوم لكل جانب) — متوسط يومي
          </p>
        </div>
        <div className="p-4">
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="bg-gray-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-gray-800">{impact?.summary?.evaluated ?? '—'}</div>
              <div className="text-xs text-gray-500">تغييرات قابلة للقياس</div>
            </div>
            <div className="bg-emerald-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-emerald-700">
                {impact?.summary?.avg_qty_lift_pct != null ? `${impact.summary.avg_qty_lift_pct}%` : '—'}
              </div>
              <div className="text-xs text-emerald-600">متوسط تغير الكمية</div>
            </div>
            <div className="bg-blue-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-blue-700">
                {impact?.summary ? `${impact.summary.positive_count}↑ / ${impact.summary.negative_count}↓` : '—'}
              </div>
              <div className="text-xs text-blue-600">ارتفاع / انخفاض</div>
            </div>
          </div>
          <table className="w-full text-sm">
            <thead><tr className="text-right text-xs text-gray-500 border-b">
              <th className="py-1.5">الصنف</th><th className="py-1.5">التغيير</th>
              <th className="py-1.5 text-center">قبل/يوم</th><th className="py-1.5 text-center">بعد/يوم</th>
              <th className="py-1.5 text-center">التغير</th><th className="py-1.5"></th>
            </tr></thead>
            <tbody>
              {(impact?.changes || []).slice(0, 12).map(c => {
                const lift = c.qty_lift_pct
                const disc = Object.entries(c.changed).filter(([, v]) => v.is_discount)
                  .map(([k, v]) => `${k.replace('_discp','')}: ${v.old ?? '—'}→${v.new}`).join('، ')
                return (
                  <tr key={c.request_id} className="border-b border-gray-50">
                    <td className="py-1.5">
                      <div className="text-gray-700 break-words max-w-[140px]">{c.item_name}</div>
                      <div className="text-xs text-gray-400 font-mono">{c.item_softech_id}</div>
                    </td>
                    <td className="py-1.5 text-xs text-gray-600">{disc || '—'}</td>
                    <td className="py-1.5 text-center text-xs">{(c.before.qty / c.before.days).toFixed(1)}</td>
                    <td className="py-1.5 text-center text-xs">{c.after.days ? (c.after.qty / c.after.days).toFixed(1) : '—'}</td>
                    <td className="py-1.5 text-center">
                      {lift != null
                        ? <span className={`text-xs font-semibold ${lift > 0 ? 'text-emerald-600' : lift < 0 ? 'text-red-600' : 'text-gray-400'}`}>
                            {lift > 0 ? '+' : ''}{lift}%</span>
                        : <span className="text-xs text-gray-300">—</span>}
                    </td>
                    <td className="py-1.5">
                      {c.maturity === 'too_recent' && <span className="text-[11px] text-amber-500">حديث جداً</span>}
                      {c.maturity === 'no_baseline' && <span className="text-[11px] text-gray-400">بلا أساس</span>}
                    </td>
                  </tr>
                )
              })}
              {!impact?.changes?.length && (
                <tr><td colSpan={6} className="text-center py-6 text-gray-400 text-sm">لا توجد تغييرات منفّذة بعد</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── #5 Auto-repair policy ──────────────────────────────────────────── */}
      <section className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="font-bold text-gray-800 text-sm mb-3">سياسة الإصلاح التلقائي للنسخ المتماثل</h3>
        {policy && (
          <div className="space-y-3">
            <label className="flex items-center justify-between gap-3">
              <span className="text-sm text-gray-700">
                إصلاح تلقائي يومي
                <span className="block text-xs text-gray-400">يُعيد جدولة الفجوات تلقائياً بعد الفحص اليومي (وإلا تنبيه فقط)</span>
              </span>
              <button
                onClick={() => savePolicy.mutate({ auto_repair_enabled: !policy.auto_repair_enabled })}
                className={`relative w-12 h-6 rounded-full transition-colors ${policy.auto_repair_enabled ? 'bg-emerald-500' : 'bg-gray-300'}`}>
                <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${policy.auto_repair_enabled ? 'right-0.5' : 'right-6'}`} />
              </button>
            </label>

            <label className="flex items-center justify-between gap-3">
              <span className="text-sm text-gray-700">حد أقصى للأصناف في المرة (أمان)</span>
              <input type="number" min="1" defaultValue={policy.max_items_per_run}
                onBlur={e => savePolicy.mutate({ max_items_per_run: +e.target.value })}
                className="w-24 border border-gray-300 rounded px-2 py-1 text-sm text-center" />
            </label>

            <label className="flex items-center justify-between gap-3">
              <span className="text-sm text-gray-700">
                فحص أسبوعي شامل
                <span className="block text-xs text-gray-400">فحص عميق لكل الأصناف أسبوعياً (الجمعة 3ص) لاكتشاف الانحراف الصامت</span>
              </span>
              <button
                onClick={() => savePolicy.mutate({ weekly_full_audit: !policy.weekly_full_audit })}
                className={`relative w-12 h-6 rounded-full transition-colors ${policy.weekly_full_audit ? 'bg-emerald-500' : 'bg-gray-300'}`}>
                <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${policy.weekly_full_audit ? 'right-0.5' : 'right-6'}`} />
              </button>
            </label>
            {policy.updated_by && (
              <div className="text-xs text-gray-400 pt-1">آخر تعديل: {policy.updated_by} · {fmtDate(policy.updated_at)}</div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
