/**
 * ReplacementCasesPage — بدل الروشتة / شراء أدوية العملاء (doc 25, Phase 0).
 *
 * One row per virtual-supplier purchase (the native entitlement), reconstructed read-only
 * from the SOFTECH mirrors. The outstanding split separates balances that probably were paid
 * by a voucher SOFTECH never linked from balances that are genuinely still owed.
 * Display only — every figure is computed by the backend.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { replacementApi } from '../api/client'
import { Chip, money } from './supply/supplyUi'

export const STATUS_TONE = {
  entitlement_active: 'amber', settled: 'blue', reconciled: 'emerald', closed: 'gray',
  reversed: 'rose', cancelled: 'gray',
}
export const SEV_TONE = { info: 'blue', warning: 'amber', high: 'rose', critical: 'rose' }
export const SEV_LABEL = { info: 'معلومة', warning: 'تحذير', high: 'مرتفع', critical: 'حرج' }
const SUPPLIERS = [['4472', '25%'], ['4471', '30%'], ['4470', '40%'], ['4469', '50%'], ['3068', 'عام'], ['4069', 'عام 50%']]

function Kpi({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 min-w-[150px] flex-1">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`text-xl font-bold tabular-nums ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-500 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function ReplacementCasesPage() {
  const nav = useNavigate()
  const [f, setF] = useState({ q: '', branch: '', supplier: '', status: '', open_balance: '', has_exceptions: '',
                               exception_type: '', page: 1 })
  const set = (k, v) => setF((s) => ({ ...s, [k]: v, page: k === 'page' ? v : 1 }))
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== '' && v !== null))
  const { page, ...filterOnly } = params

  const summary = useQuery({ queryKey: ['replacement-summary', filterOnly],
                             queryFn: () => replacementApi.summary(filterOnly).then((r) => r.data) })
  const list = useQuery({ queryKey: ['replacement-list', params], keepPreviousData: true,
                          queryFn: () => replacementApi.list(params).then((r) => r.data) })
  const s = summary.data
  const t = s?.totals || {}
  const split = s?.outstanding_split || {}
  const rows = list.data?.results || []
  const pages = Math.max(1, Math.ceil((list.data?.count || 0) / 50))

  return (
    <div className="p-4 space-y-4" dir="rtl">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900">🔁 بدل الروشتة وشراء أدوية العملاء</h1>
          <p className="text-xs text-gray-500">
            كل حالة = فاتورة شراء من مورد شركات/مورد عام (الرصيد) + فاتورة التعاقد + سندات الصرف + فواتير المنتجات.
            إعادة بناء من بيانات SOFTECH — للقراءة فقط.
          </p>
        </div>
        <button onClick={() => nav('/replacement/new')} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm">➕ حالة جديدة</button>
        {s?.last_run && (
          <span className="text-[11px] text-gray-500">
            آخر إعادة بناء: {String(s.last_run.finished_at || s.last_run.started_at).slice(0, 16).replace('T', ' ')}
            {' · '}{s.last_run.counts?.invoices ?? 0} فاتورة
          </span>
        )}
      </div>

      <div className="flex gap-3 flex-wrap">
        <Kpi label="عدد الحالات" value={t.n ?? '—'} sub={`قيمة الأرصدة ${money(t.entitlement)}`} />
        <Kpi label="صُرف منتجات" value={money(t.redeemed_products)} tone="text-emerald-700" />
        <Kpi label="صُرف نقداً" value={money(t.redeemed_cash)} tone="text-indigo-700" />
        <Kpi label="صرف غير مصنّف" value={money(t.redeemed_unclassified)} tone="text-amber-700"
             sub="سندات تحتاج تأكيد فواتير المنتجات" />
        <Kpi label="رصيد قائم فعلاً" value={money(split.genuinely_open)} tone="text-rose-700"
             sub={`${split.open_cases ?? 0} حالة برصيد`} />
        <Kpi label="قائم — يُحتمل سداده بسند غير مربوط" value={money(split.likely_paid_unlinked)} tone="text-sky-700"
             sub="انظر «سداد الموردين»" />
      </div>

      {!!s?.exceptions?.length && (
        <div className="flex gap-2 flex-wrap items-center">
          <span className="text-xs text-gray-500">الاستثناءات المفتوحة:</span>
          {s.exceptions.map((e) => (
            <button key={`${e.exception_type}-${e.severity}`} onClick={() => set('exception_type',
              f.exception_type === e.exception_type ? '' : e.exception_type)}>
              <Chip tone={f.exception_type === e.exception_type ? 'violet' : SEV_TONE[e.severity]}>
                {e.label} · {e.n}
              </Chip>
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2 flex-wrap items-center bg-white border border-gray-200 rounded-xl p-3">
        <input value={f.q} onChange={(e) => set('q', e.target.value)} placeholder="بحث: رقم حالة، PIC، اسم، موبايل، أي رقم مستند، كود صنف…"
               className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm flex-1 min-w-[260px]" />
        <input value={f.branch} onChange={(e) => set('branch', e.target.value)} placeholder="فرع"
               className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm w-20" />
        <select value={f.supplier} onChange={(e) => set('supplier', e.target.value)}
                className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm">
          <option value="">كل الموردين</option>
          {SUPPLIERS.map(([c, l]) => <option key={c} value={c}>{c} — {l}</option>)}
        </select>
        <select value={f.status} onChange={(e) => set('status', e.target.value)}
                className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm">
          <option value="">كل الحالات</option>
          <option value="entitlement_active">رصيد قائم</option>
          <option value="settled">مستهلكة (تحتاج مراجعة)</option>
          <option value="reconciled">مطابقة</option>
        </select>
        <label className="text-xs flex items-center gap-1">
          <input type="checkbox" checked={f.open_balance === '1'} onChange={(e) => set('open_balance', e.target.checked ? '1' : '')} />
          برصيد فقط
        </label>
        <label className="text-xs flex items-center gap-1">
          <input type="checkbox" checked={f.has_exceptions === '1'} onChange={(e) => set('has_exceptions', e.target.checked ? '1' : '')} />
          باستثناءات فقط
        </label>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-[11px] text-gray-500">
            <tr>
              {['الحالة', 'المريض', 'الفرع', 'المورد', 'فاتورة الشراء', 'الرصيد', 'منتجات', 'نقدي', 'غير مصنّف', 'المتبقي', 'الوضع', 'الثقة', '⚠'].map((h) => (
                <th key={h} className="px-3 py-2 text-right font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.isLoading && <tr><td colSpan={13} className="p-6 text-center text-gray-400">جارٍ التحميل…</td></tr>}
            {!list.isLoading && !rows.length && (
              <tr><td colSpan={13} className="p-6 text-center text-gray-400">لا توجد حالات — شغّل إعادة البناء أو غيّر الفلاتر.</td></tr>
            )}
            {rows.map((c) => (
              <tr key={c.id} onClick={() => nav(`/replacement/${c.id}`)}
                  className="border-t border-gray-100 hover:bg-gray-50 cursor-pointer">
                <td className="px-3 py-2 font-mono text-xs whitespace-nowrap">{c.number}</td>
                <td className="px-3 py-2">
                  <div className="text-gray-900">{c.patient_name || <span className="text-gray-400">غير معروف</span>}</div>
                  <div className="text-[11px] text-gray-500 font-mono">{c.softech_pic}</div>
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap">{c.branch_name}</td>
                <td className="px-3 py-2 text-xs whitespace-nowrap" title={c.supplier_name}>
                  {c.supplier_personcode}
                  {c.applied_deduction_pct != null && <span className="text-gray-500"> · خصم {Number(c.applied_deduction_pct).toFixed(1)}%</span>}
                </td>
                <td className="px-3 py-2 text-xs whitespace-nowrap font-mono">{c.purchase_docnumber} <span className="text-gray-400">{c.purchase_date}</span></td>
                <td className="px-3 py-2 tabular-nums">{money(c.entitlement)}</td>
                <td className="px-3 py-2 tabular-nums text-emerald-700">{money(c.redeemed_products)}</td>
                <td className="px-3 py-2 tabular-nums text-indigo-700">{money(c.redeemed_cash)}</td>
                <td className="px-3 py-2 tabular-nums text-amber-700">{Number(c.redeemed_unclassified) ? money(c.redeemed_unclassified) : '—'}</td>
                <td className={`px-3 py-2 tabular-nums font-semibold ${Number(c.outstanding) > 0.01 ? 'text-rose-700' : 'text-gray-400'}`}>{money(c.outstanding)}</td>
                <td className="px-3 py-2"><Chip tone={STATUS_TONE[c.status]}>{c.status_label}</Chip></td>
                <td className="px-3 py-2 text-xs">{{ high: 'عالية', medium: 'متوسطة', low: 'منخفضة' }[c.link_confidence] || '—'}</td>
                <td className="px-3 py-2">{c.open_exceptions ? <Chip tone={SEV_TONE[c.max_severity]}>{c.open_exceptions}</Chip> : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center gap-2 justify-center text-sm">
        <button disabled={f.page <= 1} onClick={() => set('page', f.page - 1)} className="px-3 py-1 border rounded-lg disabled:opacity-40">السابق</button>
        <span className="text-gray-600">صفحة {f.page} من {pages} · {list.data?.count ?? 0} حالة</span>
        <button disabled={f.page >= pages} onClick={() => set('page', f.page + 1)} className="px-3 py-1 border rounded-lg disabled:opacity-40">التالي</button>
      </div>
    </div>
  )
}
