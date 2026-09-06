/**
 * BatchesPage — FEFO Batch Management + Near-Expiry Dashboard
 * Covers: batch list, near-expiry KPIs, active alerts, quarantine action
 */
import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { batchesApi, branchesApi, transfersApi } from '../api/client'
import useAuthStore from '../store/authStore'

// ── date helpers ──────────────────────────────────────────────────────────────
const _iso = (d) => d.toISOString().slice(0, 10)
// Default ENTERED-EXPIRY window: first day of this month → end of +3 months
// (a near-term "what's expiring soon" horizon; the user narrows it as needed).
function _defaultExpiryFrom() {
  const d = new Date(); d.setDate(1)
  return _iso(d)
}
function _defaultExpiryTo() {
  const d = new Date(); d.setMonth(d.getMonth() + 4, 0)   // last day of +3 months
  return _iso(d)
}
function _fmtDate(s) {
  return s ? new Date(s).toLocaleDateString('ar-EG') : '—'
}
const RISK_BADGE = {
  expired:  { label: 'منتهية', cls: 'bg-red-200 text-red-900' },
  critical: { label: 'حرجة',   cls: 'bg-red-100 text-red-700' },
  high:     { label: 'عالية',  cls: 'bg-amber-100 text-amber-800' },
  medium:   { label: 'متوسطة', cls: 'bg-yellow-100 text-yellow-800' },
  low:      { label: 'منخفضة', cls: 'bg-green-100 text-green-700' },
}

function KpiCard({ label, value, sub, color = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function QuarantineModal({ batch, onClose }) {
  const qc    = useQueryClient()
  const [reason, setReason] = useState('')
  const [err, setErr]       = useState(null)

  const mutation = useMutation({
    mutationFn: () => batchesApi.quarantine(batch.id, reason),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['batches'] }); onClose() },
    onError:   e  => setErr(e.response?.data?.detail || 'حدث خطأ'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-1">عزل دفعة</h3>
        <p className="text-sm text-gray-500 mb-4">
          {batch.item_name} — دفعة {batch.batch_number}
        </p>
        <textarea
          value={reason} onChange={e => setReason(e.target.value)}
          placeholder="سبب العزل (مطلوب)..."
          className="w-full border rounded-lg p-3 text-sm resize-none h-24 mb-4"
        />
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending || !reason.trim()}
            className="px-5 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {mutation.isPending ? 'جاري...' : 'تأكيد العزل'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Inter-branch rebalancing modal (A4) ───────────────────────────────────────
function RebalanceModal({ row, fromBranch, onClose }) {
  const [done, setDone] = useState({})   // to_branch -> true once transfer created
  const [err, setErr]   = useState(null)

  const { data, isLoading } = useQuery({
    queryKey: ['rebalance', row.item_code, fromBranch, row.days_to_expiry],
    queryFn: () => batchesApi.purchaseExpiryRebalanceSuggest({
      item_code: row.item_code,
      from_branch: fromBranch || undefined,
      days_to_expiry: row.days_to_expiry ?? 0,
    }).then(r => r.data),
  })

  const createTransfer = useMutation({
    mutationFn: (p) => transfersApi.create({
      requesting_branch: p.to_branch_id,
      supplying_branch:  data.from_branch_id,
      notes: `إعادة توزيع لتفادي انتهاء الصلاحية — ${row.item_name} (كود ${row.item_code})`,
      items: [{ item: data.item_id, quantity: p.qty }],
    }),
    onSuccess: (_res, p) => setDone(d => ({ ...d, [p.to_branch]: true })),
    onError: (e) => setErr(e.response?.data?.detail || 'تعذّر إنشاء طلب التحويل'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl p-6 max-h-[85vh] overflow-y-auto">
        <div className="flex items-start justify-between mb-1">
          <h3 className="text-lg font-bold">إعادة توزيع بين الفروع</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        <p className="text-sm text-gray-500 mb-4">{row.item_name} — كود {row.item_code}</p>

        {isLoading ? (
          <div className="text-center py-10 text-gray-400">جاري حساب الاقتراح…</div>
        ) : !data ? (
          <div className="text-center py-10 text-gray-400">تعذّر الحساب.</div>
        ) : (
          <>
            <div className="bg-gray-50 rounded-lg p-3 text-sm mb-4 grid grid-cols-2 gap-2">
              <div>الفرع المصدر: <b>{data.from_branch_name}</b></div>
              <div>الرصيد بالمصدر: <b>{data.source_qty}</b></div>
              <div>معدل البيع/يوم بالمصدر: <b>{data.source_velocity_per_day}</b></div>
              <div>أيام حتى الصلاحية: <b>{data.days_to_expiry}</b></div>
              <div className="col-span-2">الفائض المعرّض للانتهاء: <b className="text-red-600">{data.source_surplus}</b> وحدة</div>
            </div>

            {!data.velocity_known ? (
              <div className="text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm">
                معدلات البيع غير متاحة — شغّل محرك الطلب (demand engine) أولًا لحساب الاقتراح.
              </div>
            ) : data.plan.length === 0 ? (
              <div className="text-gray-500 bg-gray-50 border rounded-lg p-3 text-sm">
                لا يوجد فرع يستوعب الفائض قبل انتهاء الصلاحية (أو لا يوجد فائض). قد تكون الخيارات الأنسب: خصم لتسريع البيع أو مرتجع للمورد.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b">
                    <th className="px-2 py-2 text-right">إلى فرع</th>
                    <th className="px-2 py-2 text-right">الكمية المقترحة</th>
                    <th className="px-2 py-2 text-right">رصيده الآن</th>
                    <th className="px-2 py-2 text-right">معدل بيعه/يوم</th>
                    <th className="px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {data.plan.map(p => (
                    <tr key={p.to_branch} className="border-b border-gray-100">
                      <td className="px-2 py-2 font-medium">{p.to_branch_name}</td>
                      <td className="px-2 py-2 font-semibold text-green-700">{p.qty}</td>
                      <td className="px-2 py-2 text-gray-600">{p.target_qty}</td>
                      <td className="px-2 py-2 text-gray-600">{p.velocity_per_day}</td>
                      <td className="px-2 py-2">
                        {done[p.to_branch] ? (
                          <span className="text-green-600 text-xs">✓ تم إنشاء الطلب</span>
                        ) : (
                          <button
                            onClick={() => createTransfer.mutate(p)}
                            disabled={createTransfer.isPending}
                            className="px-3 py-1 text-xs bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50">
                            إنشاء طلب تحويل
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {err && <p className="text-red-600 text-sm mt-3">{err}</p>}
          </>
        )}
        <div className="flex justify-end mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إغلاق</button>
        </div>
      </div>
    </div>
  )
}

// ── Purchase-Expiry Physical Audit tab ────────────────────────────────────────
function PurchaseExpiryAuditTab() {
  const navigate = useNavigate()
  const user     = useAuthStore(s => s.user)
  const isAdmin  = ['admin', 'supervisor'].includes(user?.role)

  const [from, setFrom]           = useState(_defaultExpiryFrom())
  const [to, setTo]               = useState(_defaultExpiryTo())
  const [branch, setBranch]       = useState('')          // '' = all branches
  const [onlyInStock, setOnly]    = useState(true)
  const [rows, setRows]           = useState(null)
  const [err, setErr]             = useState(null)
  const [rebalanceRow, setRebal]  = useState(null)   // row being rebalanced (A4 modal)

  // Client-side filters/sort (operate on the fetched rows — no SOFTECH re-hit)
  const [search, setSearch]       = useState('')
  const [importedOnly, setImp]    = useState(false)
  const [fridgeOnly, setFridge]   = useState(false)
  const [passedOnly, setPassed]   = useState(false)
  const [minVar, setMinVar]       = useState('')
  const [minQ, setMinQ]           = useState('')
  const [medType, setMedType]     = useState('')
  const [origin, setOrigin]       = useState('')
  const [shape, setShape]         = useState('')
  const [producer, setProducer]   = useState('')
  const [riskFilter, setRiskFilter] = useState('')     // '' | 'atrisk' | 'critical'
  const [sortKey, setSortKey]     = useState('value_at_risk')
  const [sortDir, setSortDir]     = useState('desc')

  // Column meta drives BOTH the grid and the sortable headers.
  const NUMERIC = new Set(['current_qty', 'unit_cost', 'value_at_risk', 'retail_value',
                           'entry_count', 'stock_age_days', 'expected_loss', 'days_to_expiry'])
  const RISK_RANK = { expired: 4, critical: 3, high: 2, medium: 1, low: 0 }

  function sortBy(key) {
    if (key === sortKey) { setSortDir(d => (d === 'desc' ? 'asc' : 'desc')); return }
    setSortKey(key)
    setSortDir((NUMERIC.has(key) || key === 'risk_tier') ? 'desc' : 'asc')   // numbers/risk: big-first; text/dates: A→Z / soonest
  }
  const arrow = (k) => (sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')

  // Distinct dropdown options built from the fetched rows.
  const distinct = (key) => Array.from(
    new Set((rows || []).map(r => r[key]).filter(Boolean))
  ).sort((a, b) => String(a).localeCompare(String(b), 'ar'))
  const opts = useMemo(() => ({
    medType:  distinct('medicine_type'),
    origin:   distinct('origin'),
    shape:    distinct('shape'),
    producer: distinct('producer'),
  }), [rows])

  const displayRows = useMemo(() => {
    if (!rows) return null
    const out = rows.filter(r => {
      if (importedOnly && !r.is_imported) return false
      if (fridgeOnly && !r.is_fridge) return false
      if (passedOnly && !r.has_entered_expiry_passed) return false
      if (riskFilter === 'atrisk' && !['expired', 'critical', 'high'].includes(r.risk_tier)) return false
      if (riskFilter === 'critical' && !['expired', 'critical'].includes(r.risk_tier)) return false
      if (medType && r.medicine_type !== medType) return false
      if (origin && r.origin !== origin) return false
      if (shape && r.shape !== shape) return false
      if (producer && r.producer !== producer) return false
      if (minVar && (r.value_at_risk || 0) < Number(minVar)) return false
      if (minQ && (r.current_qty || 0) < Number(minQ)) return false
      if (search) {
        const q = search.toLowerCase()
        if (!((r.item_name || '').toLowerCase().includes(q) ||
              (r.item_code || '').includes(q))) return false
      }
      return true
    })
    const dir = sortDir === 'asc' ? 1 : -1
    const isRisk = sortKey === 'risk_tier'
    const isNum = NUMERIC.has(sortKey) || isRisk
    out.sort((a, b) => {
      const va = isRisk ? RISK_RANK[a.risk_tier] : a[sortKey]
      const vb = isRisk ? RISK_RANK[b.risk_tier] : b[sortKey]
      const na = va === null || va === undefined || va === ''
      const nb = vb === null || vb === undefined || vb === ''
      if (na && nb) return 0
      if (na) return 1            // missing values always last
      if (nb) return -1
      if (isNum) return (va - vb) * dir
      return String(va).localeCompare(String(vb), 'ar') * dir
    })
    return out
  }, [rows, importedOnly, fridgeOnly, passedOnly, riskFilter, medType, origin, shape, producer,
      minVar, minQ, search, sortKey, sortDir])

  const totalVar = useMemo(
    () => (displayRows || []).reduce((s, r) => s + (r.value_at_risk || 0), 0),
    [displayRows],
  )
  const totalExpLoss = useMemo(
    () => (displayRows || []).reduce((s, r) => s + (r.expected_loss || 0), 0),
    [displayRows],
  )
  const hasRisk = useMemo(() => (rows || []).some(r => r.risk_tier), [rows])

  const { data: branchesData } = useQuery({
    queryKey: ['branches', 'all-for-audit'],
    queryFn:  () => branchesApi.list().then(r => r.data),
  })
  const branches = branchesData?.results || branchesData || []

  const { data: runsData } = useQuery({
    queryKey: ['batches', 'purchase-expiry-runs'],
    queryFn:  () => batchesApi.purchaseExpiryRuns().then(r => r.data),
    refetchInterval: (q) => {
      const list = q.state.data?.results || q.state.data || []
      return list.some(r => r.status === 'running') ? 4000 : false
    },
  })
  const runs      = runsData?.results || runsData || []
  const lastRun   = runs[0]
  const isRunning = runs.some(r => r.status === 'running')

  const candidates = useMutation({
    mutationFn: () => batchesApi.purchaseExpiryCandidates({
      from, to,
      branches: branch ? [branch] : undefined,
      only_in_stock: onlyInStock,
    }).then(r => r.data),
    onSuccess: (data) => { setRows(data.items || []); setErr(null) },
    onError:   (e)    => setErr(e.response?.data?.detail || 'تعذّر توليد التقرير'),
  })

  const sync = useMutation({
    // Backfill is always chain-wide (all branches) — branch is a report-time filter only.
    mutationFn: () => batchesApi.purchaseExpirySync({ from, to }),
    onError:   (e) => setErr(e.response?.data?.detail || 'تعذّر بدء المزامنة'),
  })

  const spawn = useMutation({
    // Spawn a count for exactly the rows currently shown (after client filters).
    mutationFn: () => batchesApi.purchaseExpirySpawnCount({
      branch, from, to,
      item_codes: (displayRows || []).map(r => r.item_code),
    }).then(r => r.data),
    onSuccess: (data) => navigate(`/stock-count?session=${data.session_id}`),
    onError:   (e) => setErr(e.response?.data?.detail || 'تعذّر إنشاء جلسة الجرد'),
  })

  const branchLabel = branch
    ? (branches.find(b => b.softech_branch_id === branch)?.name_ar || branch)
    : 'كل الفروع'

  const exportXlsx = useMutation({
    mutationFn: () => batchesApi.purchaseExpiryExport({
      items: displayRows || [], from, to, branch_label: branchLabel,
    }),
    onSuccess: (res) => {
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url
      a.download = `expiry_audit_${branchLabel}_${from}_${to}.xlsx`
      document.body.appendChild(a); a.click(); a.remove()
      window.URL.revokeObjectURL(url)
    },
    onError: (e) => setErr(e.response?.data?.detail || 'تعذّر تصدير الملف'),
  })

  return (
    <div>
      {/* Explanation */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-5 text-sm text-blue-900 leading-relaxed">
        يعرض هذا التقرير الأصناف <b>الموجودة بالمخزون حاليًا</b> التي سجّل لها
        <b> موزّع رئيسي / مصنع</b> — عند الشراء في <b>أي وقت</b> —
        <b> تاريخ صلاحية يقع ضمن الفترة المحددة أدناه</b> (نطاق الصلاحية، وليس تاريخ الشراء)،
        لسحبها ماديًا والتحقق من صلاحيتها الفعلية على الرف.
        <span className="text-blue-700"> (لا يُشترط أن يحمل المخزون الحالي نفس هذه الصلاحية — البيان مجرد إشارة للفحص.)</span>
      </div>

      {/* Backfill status + admin sync */}
      <div className="flex flex-wrap items-center gap-3 mb-4 bg-white rounded-xl border border-gray-200 p-4">
        <div className="text-sm text-gray-600 flex-1">
          {lastRun ? (
            <>آخر مزامنة: <b>{_fmtDate(lastRun.started_at)}</b> —{' '}
              {lastRun.status === 'running' ? <span className="text-amber-600">جارية…</span>
                : lastRun.status === 'success' ? <span className="text-green-700">ناجحة ({lastRun.lines_upserted?.toLocaleString('ar-EG')} سطر جديد، {lastRun.suppliers_count} مورد)</span>
                : <span className="text-red-600">فشلت</span>}
            </>
          ) : <span className="text-gray-400">لم تُنفّذ مزامنة بعد — شغّل المزامنة لجلب بيانات الشراء (٣ سنوات).</span>}
        </div>
        {isAdmin && (
          <button
            onClick={() => sync.mutate()}
            disabled={sync.isPending || isRunning}
            className="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
          >
            {sync.isPending || isRunning ? 'المزامنة جارية…' : '🔄 مزامنة بيانات الشراء (٣ سنوات)'}
          </button>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-3 mb-5">
        <label className="text-sm">
          <span className="block text-gray-500 mb-1">الصلاحية من</span>
          <input type="date" value={from} onChange={e => setFrom(e.target.value)}
                 className="border rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="text-sm">
          <span className="block text-gray-500 mb-1">الصلاحية إلى</span>
          <input type="date" value={to} onChange={e => setTo(e.target.value)}
                 className="border rounded-lg px-3 py-2 text-sm" />
        </label>
        <label className="text-sm">
          <span className="block text-gray-500 mb-1">الفرع</span>
          <select value={branch} onChange={e => setBranch(e.target.value)}
                  className="border rounded-lg px-3 py-2 text-sm min-w-[10rem]">
            <option value="">كل الفروع</option>
            {branches.map(b => (
              <option key={b.id} value={b.softech_branch_id}>
                {b.name_ar || b.display_name || b.softech_branch_id}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm flex items-center gap-2 pb-2">
          <input type="checkbox" checked={onlyInStock} onChange={e => setOnly(e.target.checked)} />
          <span className="text-gray-600">الموجود بالمخزون فقط</span>
        </label>
        <button
          onClick={() => candidates.mutate()}
          disabled={candidates.isPending || !from || !to}
          className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        >
          {candidates.isPending ? 'جاري التحميل…' : 'توليد التقرير'}
        </button>
      </div>

      {err && <p className="text-red-600 text-sm mb-3">{err}</p>}

      {/* Results */}
      {rows === null ? (
        <div className="text-center py-14 text-gray-400">حدّد الفترة والفرع ثم اضغط «توليد التقرير».</div>
      ) : rows.length === 0 ? (
        <div className="text-center py-14 text-gray-400">لا توجد أصناف مطابقة للمعايير.</div>
      ) : (
        <>
          {/* Client-side filters (no re-query) */}
          <div className="flex flex-wrap items-center gap-2 mb-3 bg-white rounded-xl border border-gray-200 p-3 text-sm">
            <input value={search} onChange={e => setSearch(e.target.value)}
                   placeholder="بحث بالاسم / الكود…"
                   className="border rounded-lg px-3 py-1.5 flex-1 min-w-[9rem]" />
            {hasRisk && (
              <select value={riskFilter} onChange={e => setRiskFilter(e.target.value)}
                      className="border rounded-lg px-2 py-1.5">
                <option value="">الخطورة: الكل</option>
                <option value="critical">حرجة / منتهية</option>
                <option value="atrisk">عالية فأعلى</option>
              </select>
            )}
            <select value={medType} onChange={e => setMedType(e.target.value)}
                    className="border rounded-lg px-2 py-1.5 max-w-[11rem]">
              <option value="">التصنيف العام: الكل</option>
              {opts.medType.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
            <select value={origin} onChange={e => setOrigin(e.target.value)}
                    className="border rounded-lg px-2 py-1.5 max-w-[10rem]">
              <option value="">المنشأ: الكل</option>
              {opts.origin.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
            <select value={shape} onChange={e => setShape(e.target.value)}
                    className="border rounded-lg px-2 py-1.5 max-w-[10rem]">
              <option value="">الشكل: الكل</option>
              {opts.shape.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
            <select value={producer} onChange={e => setProducer(e.target.value)}
                    className="border rounded-lg px-2 py-1.5 max-w-[11rem]">
              <option value="">المنتج: الكل</option>
              {opts.producer.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
            <label className="flex items-center gap-1 text-gray-600">
              <input type="checkbox" checked={importedOnly} onChange={e => setImp(e.target.checked)} />
              مستورد
            </label>
            <label className="flex items-center gap-1 text-gray-600">
              <input type="checkbox" checked={fridgeOnly} onChange={e => setFridge(e.target.checked)} />
              ❄️ ثلاجة
            </label>
            <label className="flex items-center gap-1 text-gray-600">
              <input type="checkbox" checked={passedOnly} onChange={e => setPassed(e.target.checked)} />
              منتهية فقط
            </label>
            <input type="number" value={minVar} onChange={e => setMinVar(e.target.value)}
                   placeholder="أدنى قيمة خطر" className="border rounded-lg px-2 py-1.5 w-28" />
            <input type="number" value={minQ} onChange={e => setMinQ(e.target.value)}
                   placeholder="أدنى كمية" className="border rounded-lg px-2 py-1.5 w-24" />
          </div>

          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <p className="text-sm text-gray-600">
              عدد الأصناف: <b>{displayRows.length}</b>
              <span className="mx-2 text-gray-300">·</span>
              قيمة معرّضة للخطر: <b className="text-red-600">{Math.round(totalVar).toLocaleString('ar-EG')} ج</b>
              {hasRisk && <>
                <span className="mx-2 text-gray-300">·</span>
                خسارة متوقعة: <b className="text-red-700">{Math.round(totalExpLoss).toLocaleString('ar-EG')} ج</b>
              </>}
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => exportXlsx.mutate()}
                disabled={exportXlsx.isPending || displayRows.length === 0}
                className="px-4 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
              >
                {exportXlsx.isPending ? 'جاري التصدير…' : '⬇️ تصدير Excel'}
              </button>
              <button
                onClick={() => spawn.mutate()}
                disabled={spawn.isPending || !branch || displayRows.length === 0}
                title={!branch ? 'اختر فرعًا لبدء جرد مادي' : ''}
                className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
              >
                {spawn.isPending ? 'جاري الإنشاء…' : '▶️ بدء جرد مادي لهذه الأصناف'}
              </button>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 select-none">
                  {[
                    ['item_code', 'كود'],
                    ['item_name', 'الصنف'],
                    ['current_qty', 'الكمية'],
                    ['unit_cost', 'تكلفة الوحدة'],
                    ['value_at_risk', 'قيمة معرّضة للخطر'],
                    ...(hasRisk ? [
                      ['risk_tier', 'الخطورة'],
                      ['expected_loss', 'خسارة متوقعة'],
                      ['days_to_expiry', 'أيام للصلاحية'],
                    ] : []),
                    ['stock_age_days', 'عمر بالفرع'],
                    ['medicine_type', 'التصنيف العام'],
                    ['origin', 'المنشأ'],
                    ['shape', 'الشكل'],
                    ['producer', 'المنتج'],
                    ['branches_in_stock', 'الفروع'],
                    ['earliest_entered_expiry', 'صلاحية مُدخَلة'],
                    ['entry_count', 'إدخالات'],
                  ].map(([k, label]) => (
                    <th key={k} onClick={() => sortBy(k)}
                        className="px-3 py-3 text-right font-semibold text-gray-600 cursor-pointer hover:text-brand-700"
                        title="اضغط للترتيب">
                      {label}{arrow(k)}
                    </th>
                  ))}
                  <th className="px-3 py-3 text-right font-semibold text-gray-600">إجراء</th>
                </tr>
              </thead>
              <tbody>
                {displayRows.map(r => (
                  <tr key={r.item_code} className={`border-b border-gray-100 hover:bg-gray-50 ${r.has_entered_expiry_passed ? 'bg-red-50' : ''}`}>
                    <td className="px-3 py-3 font-mono text-xs text-gray-500">{r.item_code}</td>
                    <td className="px-3 py-3 font-medium">
                      {r.item_name || '—'}
                      {r.is_fridge &&
                        <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700">❄️ ثلاجة</span>}
                      {r.is_imported &&
                        <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-indigo-100 text-indigo-700">مستورد</span>}
                      {r.has_entered_expiry_passed &&
                        <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">منتهية</span>}
                    </td>
                    <td className="px-3 py-3">{r.current_qty != null ? r.current_qty.toLocaleString('ar-EG') : '—'}</td>
                    <td className="px-3 py-3 text-gray-600">{r.unit_cost != null ? r.unit_cost.toLocaleString('ar-EG') : '—'}</td>
                    <td className="px-3 py-3 font-semibold text-red-600">{r.value_at_risk != null ? Math.round(r.value_at_risk).toLocaleString('ar-EG') : '—'}</td>
                    {hasRisk && <>
                      <td className="px-3 py-3">
                        {r.risk_tier ? (
                          <span className={`px-2 py-0.5 rounded-full text-xs ${RISK_BADGE[r.risk_tier]?.cls || 'bg-gray-100 text-gray-600'}`}
                                title={r.days_to_sellout != null ? `أيام حتى النفاد (بالمعدل): ${r.days_to_sellout}` : ''}>
                            {RISK_BADGE[r.risk_tier]?.label || r.risk_tier}
                          </span>
                        ) : <span className="text-gray-400 text-xs">—</span>}
                      </td>
                      <td className="px-3 py-3 font-semibold text-red-700">{r.expected_loss != null ? Math.round(r.expected_loss).toLocaleString('ar-EG') : '—'}</td>
                      <td className="px-3 py-3 text-xs">
                        {r.days_to_expiry == null ? '—'
                          : r.days_to_expiry <= 0 ? <span className="text-red-700 font-semibold">منتهية</span>
                          : <span className={r.days_to_expiry <= 30 ? 'text-red-600' : r.days_to_expiry <= 90 ? 'text-amber-600' : 'text-gray-600'}>{r.days_to_expiry} يوم</span>}
                      </td>
                    </>}
                    <td className="px-3 py-3 text-xs" title={r.oldest_arrival_date ? `أقدم وصول: ${_fmtDate(r.oldest_arrival_date)}${r.oldest_arrival_branch ? ' — فرع ' + r.oldest_arrival_branch : ''}` : ''}>
                      {r.stock_age_days == null ? <span className="text-gray-400">—</span> : (
                        <span className={r.stock_age_days >= 270 ? 'text-red-600 font-semibold'
                              : r.stock_age_days >= 180 ? 'text-amber-600' : 'text-gray-600'}>
                          {r.stock_age_days >= 60
                            ? `~${Math.round(r.stock_age_days / 30)} شهر`
                            : `${r.stock_age_days} يوم`}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{r.medicine_type || '—'}</td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{r.origin || '—'}</td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{r.shape || '—'}</td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{r.producer || '—'}</td>
                    <td className="px-3 py-3 text-gray-500 text-xs">{(r.branches_in_stock || []).join('، ') || '—'}</td>
                    <td className="px-3 py-3 text-gray-700 text-xs">
                      {_fmtDate(r.earliest_entered_expiry)} → {_fmtDate(r.latest_entered_expiry)}
                    </td>
                    <td className="px-3 py-3">{r.entry_count}</td>
                    <td className="px-3 py-3">
                      <button onClick={() => setRebal(r)}
                              className="px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50"
                              title="اقتراح إعادة توزيع بين الفروع">↔ تحويل</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {rebalanceRow && (
        <RebalanceModal
          row={rebalanceRow}
          fromBranch={branch || rebalanceRow.branches_in_stock?.[0] || ''}
          onClose={() => setRebal(null)}
        />
      )}
    </div>
  )
}


// ── Supplier dating scorecard tab (B2) ────────────────────────────────────────
function SupplierScorecardTab() {
  const [shortDated, setShortDated] = useState(6)
  const [monthsBack, setMonthsBack] = useState('')

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['batches', 'supplier-scorecard', shortDated, monthsBack],
    queryFn: () => batchesApi.purchaseExpirySupplierScorecard({
      short_dated_months: shortDated,
      months_back: monthsBack || undefined,
    }).then(r => r.data),
  })
  const rows = data?.suppliers || []

  return (
    <div>
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-5 text-sm text-blue-900 leading-relaxed">
        يقيس هذا الجدول <b>جودة تواريخ الصلاحية</b> التي يورّدها كل موزّع رئيسي —
        <b> مدة الصلاحية المتبقية عند الاستلام</b> (تاريخ الصلاحية المُدخَل − تاريخ الشراء).
        الموردون ذوو النسبة الأعلى من التوريد <b>قصير الأجل</b> يتصدّرون القائمة —
        ورقة تفاوض لتحسين شروط التوريد والمرتجعات.
      </div>

      <div className="flex flex-wrap items-end gap-3 mb-4 text-sm">
        <label>
          <span className="block text-gray-500 mb-1">حد «قصير الأجل» (شهور)</span>
          <input type="number" value={shortDated} min={1}
                 onChange={e => setShortDated(Number(e.target.value) || 6)}
                 className="border rounded-lg px-3 py-2 w-24" />
        </label>
        <label>
          <span className="block text-gray-500 mb-1">آخر (شهور) — فارغ = الكل</span>
          <input type="number" value={monthsBack} min={1}
                 onChange={e => setMonthsBack(e.target.value)}
                 placeholder="الكل" className="border rounded-lg px-3 py-2 w-28" />
        </label>
        <button onClick={() => refetch()} disabled={isFetching}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50">
          {isFetching ? 'جاري…' : 'تحديث'}
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="text-center py-14 text-gray-400">
          لا توجد بيانات — شغّل مزامنة صلاحيات الشراء أولًا من تبويب التدقيق.
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-3 py-3 text-right font-semibold text-gray-600">المورد</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">التصنيف</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">% قصير الأجل</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">أسطر قصيرة</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">متوسط الصلاحية عند الاستلام</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">أقل صلاحية</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">عدد الأسطر</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">أصناف</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(s => (
                <tr key={s.supplier_code} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-3 py-3 font-medium">{s.supplier_name || s.supplier_code}</td>
                  <td className="px-3 py-3 text-gray-500 text-xs">{s.category}</td>
                  <td className="px-3 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                      s.pct_short_dated >= 30 ? 'bg-red-100 text-red-700'
                        : s.pct_short_dated >= 15 ? 'bg-amber-100 text-amber-800'
                        : 'bg-green-100 text-green-700'}`}>
                      {s.pct_short_dated}%
                    </span>
                  </td>
                  <td className="px-3 py-3">{(s.short_dated_lines || 0).toLocaleString('ar-EG')}</td>
                  <td className="px-3 py-3">{s.avg_shelf_months != null ? `${s.avg_shelf_months} شهر` : '—'}</td>
                  <td className="px-3 py-3 text-gray-600">{s.min_shelf_months != null ? `${s.min_shelf_months} شهر` : '—'}</td>
                  <td className="px-3 py-3">{(s.lines || 0).toLocaleString('ar-EG')}</td>
                  <td className="px-3 py-3">{(s.items || 0).toLocaleString('ar-EG')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


// ── Procurement review tab (C2 — expiry-prone items) ──────────────────────────
function ProcurementReviewTab() {
  const [monthsBack, setMonthsBack] = useState(12)
  const [shortDated, setShortDated] = useState(6)
  const [minPct, setMinPct]         = useState(30)
  const [reviewOnly, setReviewOnly] = useState(false)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['batches', 'expiry-prone', monthsBack, shortDated, minPct],
    queryFn: () => batchesApi.purchaseExpiryProneItems({
      months_back: monthsBack, short_dated_months: shortDated, min_short_pct: minPct,
    }).then(r => r.data),
  })
  const rows = (data?.items || []).filter(r => !reviewOnly || r.reorder_review)

  return (
    <div>
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-5 text-sm text-blue-900 leading-relaxed">
        الأصناف التي <b>تُشترى قصيرة الأجل بشكل متكرر</b> من الموردين الرئيسيين
        (نسبة عالية من مشترياتها تصل بصلاحية أقل من الحد) — إشارة لـ
        <b> تقليل كمية إعادة الطلب</b>، التفاوض على تواريخ أفضل، أو تغيير المصدر.
        تُعرض مع <b>معدل البيع الشهري</b> لتمييز البطيء قصير الأجل.
      </div>

      <div className="flex flex-wrap items-end gap-3 mb-4 text-sm">
        <label><span className="block text-gray-500 mb-1">آخر (شهور)</span>
          <input type="number" value={monthsBack} min={1} onChange={e => setMonthsBack(Number(e.target.value) || 12)}
                 className="border rounded-lg px-3 py-2 w-24" /></label>
        <label><span className="block text-gray-500 mb-1">حد «قصير الأجل» (شهور)</span>
          <input type="number" value={shortDated} min={1} onChange={e => setShortDated(Number(e.target.value) || 6)}
                 className="border rounded-lg px-3 py-2 w-24" /></label>
        <label><span className="block text-gray-500 mb-1">حد المراجعة % قصير الأجل</span>
          <input type="number" value={minPct} min={1} onChange={e => setMinPct(Number(e.target.value) || 30)}
                 className="border rounded-lg px-3 py-2 w-28" /></label>
        <label className="flex items-center gap-1 text-gray-600 pb-2">
          <input type="checkbox" checked={reviewOnly} onChange={e => setReviewOnly(e.target.checked)} />
          للمراجعة فقط
        </label>
        <button onClick={() => refetch()} disabled={isFetching}
                className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50">
          {isFetching ? 'جاري…' : 'تحديث'}
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="text-center py-14 text-gray-400">لا توجد أصناف مطابقة — شغّل مزامنة صلاحيات الشراء أولًا.</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-3 py-3 text-right font-semibold text-gray-600">كود</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">الصنف</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">% قصير الأجل</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">أسطر قصيرة / إجمالي</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">معدل البيع الشهري</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">موردون</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">توصية</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.item_code} className={`border-b border-gray-100 hover:bg-gray-50 ${r.reorder_review ? 'bg-amber-50' : ''}`}>
                  <td className="px-3 py-3 font-mono text-xs text-gray-500">{r.item_code}</td>
                  <td className="px-3 py-3 font-medium">{r.item_name || '—'}</td>
                  <td className="px-3 py-3">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                      r.pct_short_dated >= 50 ? 'bg-red-100 text-red-700'
                        : r.pct_short_dated >= 30 ? 'bg-amber-100 text-amber-800'
                        : 'bg-gray-100 text-gray-600'}`}>{r.pct_short_dated}%</span>
                  </td>
                  <td className="px-3 py-3 text-gray-600">{r.short_dated_lines} / {r.lines}</td>
                  <td className="px-3 py-3">{r.monthly_velocity}</td>
                  <td className="px-3 py-3 text-gray-500">{r.suppliers}</td>
                  <td className="px-3 py-3">
                    {r.reorder_review
                      ? <span className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-800">قلّل إعادة الطلب</span>
                      : <span className="text-gray-400 text-xs">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}


export default function BatchesPage() {
  const [tab, setTab]           = useState('alerts')
  const [quarantineBatch, setQ] = useState(null)
  const [filters, setFilters]   = useState({ expiring_in_days: 180 })

  const { data: summary } = useQuery({
    queryKey: ['batches', 'near-expiry-summary'],
    queryFn:  () => batchesApi.nearExpirySummary({}).then(r => r.data),
  })

  const { data: alertsData, isLoading: alertsLoading } = useQuery({
    queryKey: ['batches', 'alerts'],
    queryFn:  () => batchesApi.alerts({}).then(r => r.data),
    enabled:  tab === 'alerts',
  })

  const { data: batchData, isLoading: batchLoading } = useQuery({
    queryKey: ['batches', 'list', filters],
    queryFn:  () => batchesApi.list(filters).then(r => r.data),
    enabled:  tab === 'list',
  })

  const alerts  = alertsData?.results || alertsData || []
  const batches = batchData?.results  || batchData  || []

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">إدارة الدفعات (FEFO)</h1>
        <p className="text-sm text-gray-500 mt-1">مراقبة انتهاء الصلاحية · نظام الصرف الأول انتهاء أولاً</p>
      </div>

      {/* KPI cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <KpiCard label="دفعات تنتهي خلال 30 يوم"  value={summary.lt_30?.batches}  sub={`${summary.lt_30?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`}  color="text-red-600" />
          <KpiCard label="دفعات تنتهي خلال 90 يوم"  value={summary.lt_90?.batches}  sub={`${summary.lt_90?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`}  color="text-amber-600" />
          <KpiCard label="دفعات تنتهي خلال 180 يوم" value={summary.lt_180?.batches} sub={`${summary.lt_180?.qty?.toLocaleString('ar-EG') ?? 0} وحدة`} color="text-yellow-600" />
          <KpiCard label="قيمة البضاعة المعرضة للخطر" value={summary.total_at_risk_value != null ? `${Math.round(summary.total_at_risk_value).toLocaleString('ar-EG')} ج` : '—'} color="text-gray-700" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'alerts', label: '🚨 تنبيهات الانتهاء' },
          { key: 'list',   label: '📦 قائمة الدفعات'   },
          { key: 'audit',  label: '📅 تدقيق صلاحيات الشراء' },
          { key: 'suppliers', label: '🏭 أداء الموردين (صلاحية)' },
          { key: 'reorder', label: '♻️ مراجعة الشراء' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Alerts tab */}
      {tab === 'alerts' && (
        alertsLoading ? (
          <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
        ) : alerts.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-4xl mb-3">✅</div>
            <p>لا توجد تنبيهات انتهاء صلاحية نشطة</p>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الفرع</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">رقم الدفعة</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ الانتهاء</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الكمية</th>
                  <th className="px-4 py-3 text-right font-semibold text-gray-600">الحد (أيام)</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map(a => (
                  <tr key={a.id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium">{a.batch?.item_name || a.item_name || '—'}</td>
                    <td className="px-4 py-3 text-gray-500">{a.batch?.branch_name || '—'}</td>
                    <td className="px-4 py-3 text-gray-500 font-mono text-xs">{a.batch?.batch_number || '—'}</td>
                    <td className="px-4 py-3 text-red-600 font-medium">
                      {a.batch?.expiry_date ? new Date(a.batch.expiry_date).toLocaleDateString('ar-EG') : '—'}
                    </td>
                    <td className="px-4 py-3">{a.batch?.current_qty ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className="px-2 py-0.5 rounded-full text-xs bg-amber-100 text-amber-800">
                        {a.threshold_days} يوم
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {/* Batch list tab */}
      {tab === 'list' && (
        <>
          <div className="flex gap-3 mb-4">
            <select
              value={filters.expiring_in_days}
              onChange={e => setFilters(f => ({ ...f, expiring_in_days: e.target.value }))}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              <option value={30}>تنتهي خلال 30 يوم</option>
              <option value={90}>تنتهي خلال 90 يوم</option>
              <option value={180}>تنتهي خلال 180 يوم</option>
              <option value={365}>تنتهي خلال سنة</option>
            </select>
            <select
              value={filters.is_quarantined || ''}
              onChange={e => setFilters(f => ({ ...f, is_quarantined: e.target.value || undefined }))}
              className="border rounded-lg px-3 py-2 text-sm"
            >
              <option value="">الكل</option>
              <option value="false">غير معزول</option>
              <option value="true">في العزل</option>
            </select>
          </div>

          {batchLoading ? (
            <div className="text-center py-16 text-gray-400">جاري التحميل...</div>
          ) : batches.length === 0 ? (
            <div className="text-center py-16 text-gray-400">لا توجد دفعات بهذه المعايير</div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الصنف</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الفرع</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">رقم الدفعة</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">تاريخ الانتهاء</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الكمية</th>
                    <th className="px-4 py-3 text-right font-semibold text-gray-600">الحالة</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {batches.map(b => (
                    <tr key={b.id} className="border-b border-gray-100 hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium">{b.item_name || b.item?.name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500">{b.branch_name || b.branch?.name || '—'}</td>
                      <td className="px-4 py-3 text-gray-500 font-mono text-xs">{b.batch_number}</td>
                      <td className="px-4 py-3 text-gray-700">
                        {b.expiry_date ? new Date(b.expiry_date).toLocaleDateString('ar-EG') : '—'}
                      </td>
                      <td className="px-4 py-3">{b.current_qty}</td>
                      <td className="px-4 py-3">
                        {b.is_quarantined ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">معزول</span>
                        ) : b.is_expired ? (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-600">منتهي</span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">نشط</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {!b.is_quarantined && !b.is_expired && (
                          <button
                            onClick={() => setQ(b)}
                            className="text-xs text-red-600 hover:underline"
                          >
                            عزل
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === 'audit' && <PurchaseExpiryAuditTab />}
      {tab === 'suppliers' && <SupplierScorecardTab />}
      {tab === 'reorder' && <ProcurementReviewTab />}

      {quarantineBatch && <QuarantineModal batch={quarantineBatch} onClose={() => setQ(null)} />}
    </div>
  )
}
