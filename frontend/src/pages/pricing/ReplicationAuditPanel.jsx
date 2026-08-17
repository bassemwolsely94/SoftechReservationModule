/**
 * ReplicationAuditPanel — audits HQ↔branch item replication over the last N days.
 * Catches changes made via the module AND direct SOFTECH edits that a down
 * branch missed, shows the source of each change, and force-repairs gaps.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../../api/client'

function fmtDate(s) {
  if (!s) return '—'
  return new Date(s).toLocaleString('ar-EG', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

const SRC_STYLE = {
  module: 'bg-blue-100 text-blue-700 border-blue-200',
  direct: 'bg-purple-100 text-purple-700 border-purple-200',
}
const STATUS_STYLE = {
  stale:       'bg-amber-100 text-amber-800',
  unreachable: 'bg-red-100 text-red-700',
  repaired:    'bg-emerald-100 text-emerald-700',
}
const STATUS_LABEL = { stale: 'متأخر', unreachable: 'فرع متوقف', repaired: 'تم الإصلاح' }

export default function ReplicationAuditPanel() {
  const qc = useQueryClient()
  const [days, setDays] = useState(30)
  const [activeScan, setActiveScan] = useState(null)
  const [filter, setFilter] = useState({ status: '', source_channel: '', branch_code: '' })
  const [selected, setSelected] = useState(new Set())
  const [toast, setToast] = useState(null)   // { type, msg }

  function showToast(type, msg) {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 7000)
  }

  const { data: scans } = useQuery({
    queryKey: ['repl-scans'],
    queryFn: () => pricingApprovalsApi.scans().then(r => r.data),
  })

  const { data: detail, isFetching } = useQuery({
    queryKey: ['repl-scan', activeScan, filter],
    queryFn: () => pricingApprovalsApi.scanDetail(activeScan, filter).then(r => r.data),
    enabled: !!activeScan,
  })

  const runScan = useMutation({
    mutationFn: () => pricingApprovalsApi.runScan(days),
    onSuccess: (r) => {
      qc.invalidateQueries(['repl-scans']); setActiveScan(r.data.id)
      showToast('info', `اكتمل الفحص #${r.data.id}: ${r.data.items_with_gaps} صنف بها فجوات من ${r.data.items_checked} مفحوص`)
    },
  })

  const repair = useMutation({
    mutationFn: (body) => pricingApprovalsApi.repair(body),
    onSuccess: (r) => {
      qc.invalidateQueries(['repl-scan', activeScan]); setSelected(new Set())
      const d = r.data || {}
      const requeued = d.items_repaired_attempted ?? 0
      const confirmed = d.gaps_confirmed_repaired ?? 0
      let msg = `✓ تمت إعادة جدولة ${requeued} ${requeued === 1 ? 'صنف' : 'أصناف'} للدورة التالية (~٣٠ د)`
      if (confirmed > 0) msg += ` — وتأكدت ${confirmed} فجوة فوراً`
      msg += '. أعد الفحص بعد الدورة للتأكيد النهائي.'
      showToast('success', msg)
    },
    onError: () => showToast('error', 'تعذّر تنفيذ إعادة المزامنة — حاول مرة أخرى'),
  })

  const gaps = detail?.gaps || []

  function toggle(id) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  return (
    <div className="space-y-4" dir="rtl">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[60] max-w-md w-[92%]">
          <div className={`rounded-xl shadow-lg border px-4 py-3 text-sm flex items-start gap-2 ${
            toast.type === 'success' ? 'bg-emerald-600 text-white border-emerald-700' :
            toast.type === 'error'   ? 'bg-red-600 text-white border-red-700' :
                                       'bg-blue-600 text-white border-blue-700'}`}>
            <span className="flex-1 leading-relaxed">{toast.msg}</span>
            <button onClick={() => setToast(null)} className="text-white/80 hover:text-white text-lg leading-none">✕</button>
          </div>
        </div>
      )}
      {/* Run scan */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex items-center gap-3 flex-wrap">
        <span className="text-sm font-semibold text-gray-700">تدقيق النسخ المتماثل لآخر</span>
        <select value={days} onChange={e => setDays(+e.target.value)}
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm">
          {[7, 14, 30, 60, 90].map(d => <option key={d} value={d}>{d} يوم</option>)}
        </select>
        <button onClick={() => runScan.mutate()} disabled={runScan.isPending}
          className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg disabled:opacity-60">
          {runScan.isPending ? 'جاري الفحص…' : 'تشغيل الفحص الآن'}
        </button>
        <span className="text-xs text-gray-400">
          يكتشف تعديلات الوحدة <b>والتعديلات المباشرة في Softech</b> التي لم تصل لكل الفروع
        </span>
      </div>

      {/* Scan history */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead><tr className="bg-gray-50 text-right border-b">
            <th className="px-3 py-2 text-xs text-gray-500">الفحص</th>
            <th className="px-3 py-2 text-xs text-gray-500">النافذة</th>
            <th className="px-3 py-2 text-xs text-gray-500">مفحوصة</th>
            <th className="px-3 py-2 text-xs text-gray-500">متطابقة</th>
            <th className="px-3 py-2 text-xs text-gray-500">بها فجوات</th>
            <th className="px-3 py-2 text-xs text-gray-500">فروع متوقفة</th>
            <th className="px-3 py-2 text-xs text-gray-500">الوقت</th>
          </tr></thead>
          <tbody>
            {(scans || []).map(s => (
              <tr key={s.id} onClick={() => setActiveScan(s.id)}
                className={`border-b border-gray-100 cursor-pointer hover:bg-blue-50 ${activeScan === s.id ? 'bg-blue-50' : ''}`}>
                <td className="px-3 py-2">#{s.id} {s.is_scheduled && <span className="text-xs text-gray-400">(مجدول)</span>}</td>
                <td className="px-3 py-2">{s.days_window}ي</td>
                <td className="px-3 py-2">{s.items_checked}</td>
                <td className="px-3 py-2 text-emerald-600">{s.items_ok}</td>
                <td className="px-3 py-2 font-semibold text-amber-700">{s.items_with_gaps}</td>
                <td className="px-3 py-2">{s.branches_down?.length ? <span className="text-red-600">{s.branches_down.join(', ')}</span> : '—'}</td>
                <td className="px-3 py-2 text-xs text-gray-500">{fmtDate(s.started_at)}</td>
              </tr>
            ))}
            {!scans?.length && <tr><td colSpan={7} className="text-center py-8 text-gray-400 text-sm">لا توجد فحوصات — شغّل الفحص أعلاه</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Gaps of selected scan */}
      {activeScan && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div className="p-3 border-b border-gray-100 flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-bold text-gray-800">فجوات الفحص #{activeScan}</h3>
            <select value={filter.source_channel} onChange={e => setFilter(f => ({ ...f, source_channel: e.target.value }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs">
              <option value="">كل المصادر</option>
              <option value="direct">تعديل مباشر Softech</option>
              <option value="module">وحدة الموافقات</option>
            </select>
            <select value={filter.status} onChange={e => setFilter(f => ({ ...f, status: e.target.value }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs">
              <option value="">كل الحالات</option>
              <option value="stale">متأخر</option>
              <option value="unreachable">فرع متوقف</option>
              <option value="repaired">تم الإصلاح</option>
            </select>
            <div className="flex-1" />
            {selected.size > 0 && (
              <>
                <button onClick={() => repair.mutate({ gap_ids: [...selected], mode: 'restamp' })}
                  disabled={repair.isPending}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-60">
                  إعادة المزامنة المحددة ({selected.size}) — الدورة التالية
                </button>
                <button onClick={() => repair.mutate({ gap_ids: [...selected], mode: 'both' })}
                  disabled={repair.isPending}
                  className="bg-blue-600 hover:bg-blue-700 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-60">
                  إصلاح فوري + الدورة
                </button>
              </>
            )}
            <button onClick={() => repair.mutate({ scan_id: activeScan, mode: 'restamp' })}
              disabled={repair.isPending}
              className="bg-amber-600 hover:bg-amber-700 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-60">
              إعادة مزامنة كل الفجوات
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 text-right border-b">
                <th className="px-3 py-2 w-8"></th>
                <th className="px-3 py-2 text-xs text-gray-500">الصنف</th>
                <th className="px-3 py-2 text-xs text-gray-500">الفرع</th>
                <th className="px-3 py-2 text-xs text-gray-500">مصدر التعديل</th>
                <th className="px-3 py-2 text-xs text-gray-500">الفروق</th>
                <th className="px-3 py-2 text-xs text-gray-500">HQ / الفرع</th>
                <th className="px-3 py-2 text-xs text-gray-500">الحالة</th>
              </tr></thead>
              <tbody>
                {isFetching && <tr><td colSpan={7} className="text-center py-6 text-gray-400 text-sm">جاري التحميل…</td></tr>}
                {!isFetching && gaps.map(g => (
                  <tr key={g.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-3 py-2">
                      {g.status !== 'repaired' &&
                        <input type="checkbox" checked={selected.has(g.id)} onChange={() => toggle(g.id)} />}
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-800 break-words max-w-[160px]">{g.item_name}</div>
                      <div className="text-xs text-gray-400 font-mono">{g.item_softech_id}</div>
                    </td>
                    <td className="px-3 py-2">
                      <span className="font-mono text-xs">{g.branch_code}</span>
                      <div className="text-xs text-gray-400 truncate max-w-[120px]">{g.branch_name}</div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full border ${SRC_STYLE[g.source_channel]}`}>
                        {g.source_display}
                      </span>
                      <div className="text-xs text-gray-500 mt-0.5">{g.source_user}</div>
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {Object.keys(g.diff_summary || {}).filter(k => k !== '_missing').join('، ') || (g.diff_summary?._missing ? 'الصنف غير موجود بالفرع' : '—')}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">
                      <div>{fmtDate(g.hq_itemlastupdate)}</div>
                      <div className="text-red-500">{fmtDate(g.branch_itemlastupdate)}</div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLE[g.status]}`}>
                        {STATUS_LABEL[g.status]}
                      </span>
                    </td>
                  </tr>
                ))}
                {!isFetching && !gaps.length &&
                  <tr><td colSpan={7} className="text-center py-8 text-emerald-600 text-sm">✓ لا توجد فجوات — كل الفروع متزامنة</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
