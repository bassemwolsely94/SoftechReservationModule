/**
 * ReferralStatsPage (/referral-stats) — referring-doctor performance from committed POS
 * sales. Read-only report: orders, net value, distinct patients, last referral per doctor.
 */
import { useEffect, useState } from 'react'
import api from '../api/client'
import { money } from '../hooks/usePosOrder'

export default function ReferralStatsPage() {
  const [data, setData] = useState(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    api.get('/pos-orders/referral-stats/', { params: { from: from || undefined, to: to || undefined } })
      .then(r => setData(r.data)).catch(() => setData({ results: [], summary: {} }))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])   // eslint-disable-line

  const rows = data?.results || []
  const sum = data?.summary || {}

  return (
    <div className="page-body">
      <div className="mb-4">
        <h1 className="text-lg font-bold text-content">إحصاءات إحالات الأطباء</h1>
        <p className="text-xs text-faint">أداء الأطباء المُحيلين من مبيعات نقطة البيع المُرحَّلة.</p>
      </div>

      <div className="card mb-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-muted">من تاريخ
          <input type="date" value={from} onChange={e => setFrom(e.target.value)} className="input-field mt-0.5" /></label>
        <label className="text-xs text-muted">إلى تاريخ
          <input type="date" value={to} onChange={e => setTo(e.target.value)} className="input-field mt-0.5" /></label>
        <button onClick={load} disabled={loading} className="btn-primary">{loading ? '…' : 'تطبيق'}</button>
      </div>

      {/* summary */}
      <div className="grid grid-cols-3 gap-3 mb-3">
        <Stat label="أطباء مُحيلون" value={sum.doctors ?? '—'} />
        <Stat label="عدد الطلبات" value={sum.orders ?? '—'} />
        <Stat label="إجمالي الصافي" value={sum.total_net != null ? money(sum.total_net) : '—'} />
      </div>

      <div className="card p-0 overflow-x-auto">
        <table className="data-table">
          <thead><tr>
            <th>الطبيب</th><th>الكود</th><th>عدد الطلبات</th><th>إجمالي الصافي</th><th>عدد المرضى</th><th>آخر إحالة</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="font-semibold text-content">{r.doctor_name}</td>
                <td className="mono text-xs text-faint">{r.doctor_code || '—'}</td>
                <td className="tabnum">{r.orders}</td>
                <td className="tabnum">{money(r.total_net)}</td>
                <td className="tabnum">{r.patients}</td>
                <td className="text-xs text-faint">{r.last_referral ? String(r.last_referral).slice(0, 10) : '—'}</td>
              </tr>
            ))}
            {!rows.length && !loading && (
              <tr><td colSpan={6} className="text-center text-faint py-10">لا إحالات في هذه الفترة.</td></tr>)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const Stat = ({ label, value }) => (
  <div className="card">
    <div className="text-[11px] text-faint">{label}</div>
    <div className="text-xl font-bold text-content tabnum">{value}</div>
  </div>
)
