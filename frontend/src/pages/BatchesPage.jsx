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
  return s ? new Date(s).toLocaleDateString('en-GB') : '—'
}
// Latin/English digits everywhere (no Arabic-Indic numerals)
const fmtNum = (n, d = 0) => Number(n ?? 0).toLocaleString('en-US', { maximumFractionDigits: d })
const fmtInt = (n) => Number(n ?? 0).toLocaleString('en-US')
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
  const [mdEnabled, setMdEnabled] = useState(false)  // A5.2 markdown feature flag
  const [mdRequested, setMdReq]   = useState(() => new Set())  // item_codes already requested

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
                           'entry_count', 'stock_age_days', 'expected_loss', 'days_to_expiry',
                           'markdown_discount_pct'])
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
    onSuccess: (data) => { setRows(data.items || []); setMdEnabled(!!data.markdown_enabled); setMdReq(new Set()); setErr(null) },
    onError:   (e)    => setErr(e.response?.data?.detail || 'تعذّر توليد التقرير'),
  })

  const requestMarkdown = useMutation({
    mutationFn: (r) => batchesApi.purchaseExpiryRequestMarkdown({
      item_code: r.item_code, discount_pct: r.markdown_discount_pct,
      days_to_expiry: r.days_to_expiry,
      branch: branch || r.branches_in_stock?.[0] || '',
    }),
    onSuccess: (_res, r) => setMdReq(s => new Set(s).add(r.item_code)),
    onError:   (e) => setErr(e.response?.data?.detail || 'تعذّر إنشاء طلب الخصم'),
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
                : lastRun.status === 'success' ? <span className="text-green-700">ناجحة ({lastRun.lines_upserted?.toLocaleString('en-US')} سطر جديد، {lastRun.suppliers_count} مورد)</span>
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
              قيمة معرّضة للخطر: <b className="text-red-600">{Math.round(totalVar).toLocaleString('en-US')} ج</b>
              {hasRisk && <>
                <span className="mx-2 text-gray-300">·</span>
                خسارة متوقعة: <b className="text-red-700">{Math.round(totalExpLoss).toLocaleString('en-US')} ج</b>
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
                    ['markdown_discount_pct', 'خصم مقترح'],
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
                    <td className="px-3 py-3">{r.current_qty != null ? r.current_qty.toLocaleString('en-US') : '—'}</td>
                    <td className="px-3 py-3 text-gray-600">{r.unit_cost != null ? r.unit_cost.toLocaleString('en-US') : '—'}</td>
                    <td className="px-3 py-3 font-semibold text-red-600">{r.value_at_risk != null ? Math.round(r.value_at_risk).toLocaleString('en-US') : '—'}</td>
                    <td className="px-3 py-3 text-xs">
                      {r.markdown_discount_pct == null ? <span className="text-gray-400">—</span> : (
                        <span className="px-2 py-0.5 rounded-full bg-purple-100 text-purple-700"
                              title={`السعر بعد الخصم: ${r.markdown_net_price} ج · هامش ${r.markdown_margin_pct}%`}>
                          −{r.markdown_discount_pct}%
                        </span>
                      )}
                    </td>
                    {hasRisk && <>
                      <td className="px-3 py-3">
                        {r.risk_tier ? (
                          <span className={`px-2 py-0.5 rounded-full text-xs ${RISK_BADGE[r.risk_tier]?.cls || 'bg-gray-100 text-gray-600'}`}
                                title={r.days_to_sellout != null ? `أيام حتى النفاد (بالمعدل): ${r.days_to_sellout}` : ''}>
                            {RISK_BADGE[r.risk_tier]?.label || r.risk_tier}
                          </span>
                        ) : <span className="text-gray-400 text-xs">—</span>}
                      </td>
                      <td className="px-3 py-3 font-semibold text-red-700">{r.expected_loss != null ? Math.round(r.expected_loss).toLocaleString('en-US') : '—'}</td>
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
                      <div className="flex items-center gap-1">
                        <button onClick={() => setRebal(r)}
                                className="px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50"
                                title="اقتراح إعادة توزيع بين الفروع">↔ تحويل</button>
                        {mdEnabled && r.markdown_discount_pct != null && (
                          mdRequested.has(r.item_code)
                            ? <span className="text-green-600 text-xs">✓ طُلب الخصم</span>
                            : <button
                                onClick={() => {
                                  const below = r.unit_cost != null && r.markdown_net_price != null && r.markdown_net_price < r.unit_cost
                                  if (window.confirm(
                                    `طلب خصم خاص ${r.markdown_discount_pct}% على «${r.item_name}» `
                                    + `(سعر بعد الخصم ${r.markdown_net_price} ج${below ? ' — أقل من التكلفة (تصريف)' : ''}).\n`
                                    + `سيُرسَل للاعتماد في «اعتماد الأسعار» ولن يُطبَّق في SOFTECH إلا بعد الموافقة.`))
                                    requestMarkdown.mutate(r)
                                }}
                                disabled={requestMarkdown.isPending}
                                className="px-2 py-1 text-xs bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
                                title="طلب خصم قرب انتهاء الصلاحية (يتطلب اعتماد)">💲 طلب خصم</button>
                        )}
                      </div>
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
                  <td className="px-3 py-3">{(s.short_dated_lines || 0).toLocaleString('en-US')}</td>
                  <td className="px-3 py-3">{s.avg_shelf_months != null ? `${s.avg_shelf_months} شهر` : '—'}</td>
                  <td className="px-3 py-3 text-gray-600">{s.min_shelf_months != null ? `${s.min_shelf_months} شهر` : '—'}</td>
                  <td className="px-3 py-3">{(s.lines || 0).toLocaleString('en-US')}</td>
                  <td className="px-3 py-3">{(s.items || 0).toLocaleString('en-US')}</td>
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


// ── Live stock-expiry tab (SOFTECH stkbalexpiry mirror, all nodes) ────────────
const _TIER = {
  expired:  { l: 'منتهية',    c: 'bg-red-200 text-red-900' },
  critical: { l: '≤30 يوم',   c: 'bg-red-100 text-red-700' },
  high:     { l: '≤90 يوم',   c: 'bg-amber-100 text-amber-800' },
  watch:    { l: '≤180 يوم',  c: 'bg-yellow-100 text-yellow-800' },
  ok:       { l: '>180 يوم',  c: 'bg-green-100 text-green-700' },
}

function LiveStockExpiryTab({ initialMode = 'near', modeSwitch = false }) {
  const user    = useAuthStore(s => s.user)
  const isAdmin = ['admin', 'supervisor'].includes(user?.role)

  const [mode, setMode]         = useState(initialMode)
  const [within, setWithin]     = useState(180)
  const [branch, setBranch]     = useState('')
  const [includeQ, setIncludeQ] = useState(false)
  const [search, setSearch]     = useState('')
  const [importedOnly, setImp]  = useState(false)
  const [fridgeOnly, setFridge] = useState(false)
  const [medType, setMedType]   = useState('')
  const [sortKey, setSortKey]   = useState('value_at_risk')
  const [sortDir, setSortDir]   = useState('desc')

  const { data: branchesData } = useQuery({
    queryKey: ['branches', 'all-for-expiry'],
    queryFn:  () => branchesApi.list().then(r => r.data),
  })
  const branches = branchesData?.results || branchesData || []

  const { data, isFetching } = useQuery({
    queryKey: ['batches', 'stock-expiry-report', mode, within, branch, includeQ],
    queryFn:  () => batchesApi.stockExpiryReport({
      mode, within_days: within, branches: branch || undefined,
      include_quarantine: includeQ || undefined,
    }).then(r => r.data),
  })
  const rows = data?.items || []

  const { data: runsData } = useQuery({
    queryKey: ['batches', 'stock-expiry-runs'],
    queryFn:  () => batchesApi.stockExpiryRuns().then(r => r.data),
    refetchInterval: (q) => ((q.state.data || []).some(r => r.status === 'running') ? 4000 : false),
  })
  const runs = runsData || []
  const lastRun = runs[0]
  const qc = useQueryClient()
  const sync = useMutation({
    mutationFn: () => batchesApi.stockExpirySync({}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['batches', 'stock-expiry-runs'] }),
  })

  const navigate = useNavigate()
  const [err, setErr] = useState(null)
  const [disposalRow, setDisposalRow] = useState(null)
  const branchLabel = branch
    ? (branches.find(b => b.softech_branch_id === branch)?.name_ar || branch)
    : 'كل الفروع'

  const NUMERIC = new Set(['total_qty', 'unit_cost', 'value_at_risk', 'batch_count', 'days_to_expiry'])
  const arrow = (k) => (sortKey === k ? (sortDir === 'asc' ? ' ▲' : ' ▼') : '')
  const sortBy = (k) => {
    if (k === sortKey) { setSortDir(d => (d === 'asc' ? 'desc' : 'asc')); return }
    setSortKey(k); setSortDir(NUMERIC.has(k) ? 'desc' : 'asc')
  }
  const medOpts = useMemo(
    () => Array.from(new Set(rows.map(r => r.medicine_type).filter(Boolean)))
      .sort((a, b) => String(a).localeCompare(String(b), 'ar')), [rows])

  const view = useMemo(() => {
    const out = rows.filter(r => {
      if (importedOnly && !r.is_imported) return false
      if (fridgeOnly && !r.is_fridge) return false
      if (medType && r.medicine_type !== medType) return false
      if (search) {
        const q = search.toLowerCase()
        if (!((r.item_name || '').toLowerCase().includes(q) || (r.item_code || '').includes(q))) return false
      }
      return true
    })
    const dir = sortDir === 'asc' ? 1 : -1, isNum = NUMERIC.has(sortKey)
    out.sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey]
      const na = va == null || va === '', nb = vb == null || vb === ''
      if (na && nb) return 0; if (na) return 1; if (nb) return -1
      if (isNum) return (va - vb) * dir
      return String(va).localeCompare(String(vb), 'ar') * dir
    })
    return out
  }, [rows, importedOnly, fridgeOnly, medType, search, sortKey, sortDir])

  const totalVar = useMemo(() => view.reduce((s, r) => s + (r.value_at_risk || 0), 0), [view])

  const exportXlsx = useMutation({
    mutationFn: () => batchesApi.stockExpiryExport({ items: view, label: branchLabel, mode }),
    onSuccess: (res) => {
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a')
      a.href = url; a.download = `stock_expiry_${branchLabel}_${mode}.xlsx`
      document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
    },
    onError: (e) => setErr(e.response?.data?.detail || 'تعذّر التصدير'),
  })
  const spawn = useMutation({
    mutationFn: () => batchesApi.stockExpirySpawnCount({ branch, item_codes: view.map(r => r.item_code) }),
    onSuccess: (res) => navigate(`/stock-count?session=${res.data.session_id}`),
    onError: (e) => setErr(e.response?.data?.detail || 'تعذّر إنشاء جلسة الجرد'),
  })

  return (
    <div>
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4 text-sm text-blue-900 leading-relaxed">
        بيانات حية من <b>SOFTECH (stkbalexpiry)</b> — الأرصدة الفعلية بتواريخ صلاحيتها عبر
        <b> كل الفروع والمخازن</b> (تُحدَّث بمزامنة يومية). «قرب الانتهاء» = صالحة وتنتهي خلال المدة،
        و«منتهية» = مضت صلاحيتها ولا تزال بالمخزون (تحتاج إتلاف/مرتجع).
      </div>

      {/* Server-side scope + sync */}
      <div className="flex flex-wrap items-center gap-2 mb-3 text-sm">
        {modeSwitch && (
          <select value={mode} onChange={e => setMode(e.target.value)} className="border rounded-lg px-2 py-1.5">
            <option value="near">قرب الانتهاء</option>
            <option value="expired">منتهية (متبقية)</option>
            <option value="all">الكل</option>
          </select>
        )}
        {mode === 'near' && (
          <select value={within} onChange={e => setWithin(Number(e.target.value))} className="border rounded-lg px-2 py-1.5">
            <option value={30}>خلال 30 يوم</option>
            <option value={90}>خلال 90 يوم</option>
            <option value={180}>خلال 180 يوم</option>
            <option value={365}>خلال سنة</option>
          </select>
        )}
        <select value={branch} onChange={e => setBranch(e.target.value)} className="border rounded-lg px-2 py-1.5 min-w-[9rem]">
          <option value="">كل الفروع</option>
          {branches.map(b => <option key={b.id} value={b.softech_branch_id}>{b.name_ar || b.display_name || b.softech_branch_id}</option>)}
        </select>
        <label className="flex items-center gap-1 text-gray-600">
          <input type="checkbox" checked={includeQ} onChange={e => setIncludeQ(e.target.checked)} /> يشمل العزل/التالف
        </label>
        <span className="text-gray-300">·</span>
        <span className="text-xs text-gray-500">
          آخر مزامنة: {lastRun ? `${_fmtDate(lastRun.started_at)} — ${lastRun.status === 'running' ? 'جارية…' : `${fmtInt(lastRun.rows_synced)} سطر / ${lastRun.nodes_ok}/${lastRun.nodes_total} فرع`}` : 'لم تُنفّذ بعد'}
        </span>
        {isAdmin && (
          <button onClick={() => sync.mutate()} disabled={sync.isPending || lastRun?.status === 'running'}
                  className="px-3 py-1.5 text-xs bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50">
            {sync.isPending || lastRun?.status === 'running' ? 'المزامنة جارية…' : '🔄 مزامنة الآن'}
          </button>
        )}
      </div>

      {/* Client-side filters */}
      <div className="flex flex-wrap items-center gap-2 mb-3 bg-white rounded-xl border border-gray-200 p-3 text-sm">
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="بحث بالاسم / الكود…"
               className="border rounded-lg px-3 py-1.5 flex-1 min-w-[9rem]" />
        <select value={medType} onChange={e => setMedType(e.target.value)} className="border rounded-lg px-2 py-1.5 max-w-[11rem]">
          <option value="">التصنيف العام: الكل</option>
          {medOpts.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <label className="flex items-center gap-1 text-gray-600"><input type="checkbox" checked={importedOnly} onChange={e => setImp(e.target.checked)} /> مستورد</label>
        <label className="flex items-center gap-1 text-gray-600"><input type="checkbox" checked={fridgeOnly} onChange={e => setFridge(e.target.checked)} /> ❄️ ثلاجة</label>
      </div>

      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <p className="text-sm text-gray-600">
          عدد الأصناف: <b>{fmtInt(view.length)}</b>
          <span className="mx-2 text-gray-300">·</span>
          قيمة معرّضة للخطر: <b className="text-red-600">{fmtNum(totalVar)} ج</b>
          {isFetching && <span className="mr-2 text-xs text-gray-400">جاري التحميل…</span>}
        </p>
        <div className="flex items-center gap-2">
          <button onClick={() => exportXlsx.mutate()} disabled={exportXlsx.isPending || view.length === 0}
                  className="px-4 py-2 text-sm bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
            {exportXlsx.isPending ? 'جاري التصدير…' : '⬇️ تصدير Excel'}
          </button>
          <button onClick={() => spawn.mutate()} disabled={spawn.isPending || !branch || view.length === 0}
                  title={!branch ? 'اختر فرعًا لبدء جرد مادي' : ''}
                  className="px-4 py-2 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50">
            {spawn.isPending ? 'جاري الإنشاء…' : '▶️ بدء جرد مادي'}
          </button>
        </div>
      </div>
      {err && <p className="text-red-600 text-sm mb-3">{err}</p>}

      {view.length === 0 ? (
        <div className="text-center py-14 text-gray-400">لا توجد أصناف — تأكد من تشغيل مزامنة صلاحية المخزون.</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 select-none">
                {[
                  ['item_code', 'كود'], ['item_name', 'الصنف'], ['total_qty', 'الكمية'],
                  ['unit_cost', 'تكلفة الوحدة'], ['value_at_risk', 'قيمة معرّضة'],
                  ['earliest_expiry', 'أقرب صلاحية'], ['days_to_expiry', 'الحالة'],
                  ['batch_count', 'دفعات'], ['medicine_type', 'التصنيف العام'], ['origin', 'المنشأ'],
                ].map(([k, label]) => (
                  <th key={k} onClick={() => sortBy(k)}
                      className="px-3 py-3 text-right font-semibold text-gray-600 cursor-pointer hover:text-brand-700"
                      title="اضغط للترتيب">{label}{arrow(k)}</th>
                ))}
                <th className="px-3 py-3 text-right font-semibold text-gray-600">الفروع</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">إجراء</th>
              </tr>
            </thead>
            <tbody>
              {view.map(r => (
                <tr key={r.item_code} className={`border-b border-gray-100 hover:bg-gray-50 ${r.tier === 'expired' ? 'bg-red-50' : ''}`}>
                  <td className="px-3 py-3 font-mono text-xs text-gray-500">{r.item_code}</td>
                  <td className="px-3 py-3 font-medium">
                    {r.item_name || '—'}
                    {r.is_fridge && <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700">❄️</span>}
                    {r.is_imported && <span className="mr-2 px-2 py-0.5 rounded-full text-xs bg-indigo-100 text-indigo-700">مستورد</span>}
                  </td>
                  <td className="px-3 py-3">{fmtNum(r.total_qty, 2)}</td>
                  <td className="px-3 py-3 text-gray-600">{r.unit_cost != null ? fmtNum(r.unit_cost, 2) : '—'}</td>
                  <td className="px-3 py-3 font-semibold text-red-600">{r.value_at_risk != null ? fmtNum(r.value_at_risk) : '—'}</td>
                  <td className="px-3 py-3 text-gray-700 text-xs">{_fmtDate(r.earliest_expiry)}</td>
                  <td className="px-3 py-3">
                    {r.tier && <span className={`px-2 py-0.5 rounded-full text-xs ${_TIER[r.tier]?.c || 'bg-gray-100'}`}
                                     title={r.days_to_expiry != null ? `${r.days_to_expiry} يوم` : ''}>{_TIER[r.tier]?.l || r.tier}</span>}
                  </td>
                  <td className="px-3 py-3">{fmtInt(r.batch_count)}</td>
                  <td className="px-3 py-3 text-gray-500 text-xs">{r.medicine_type || '—'}</td>
                  <td className="px-3 py-3 text-gray-500 text-xs">{r.origin || '—'}</td>
                  <td className="px-3 py-3 text-gray-500 text-xs">{(r.branches || []).join('، ') || '—'}</td>
                  <td className="px-3 py-3">
                    <button onClick={() => setDisposalRow(r)}
                            className="px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50"
                            title="إتلاف / مرتجع">🗑️ إتلاف/مرتجع</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {disposalRow && (
        <DisposalModal row={disposalRow} branch={branch} onClose={() => setDisposalRow(null)} />
      )}
    </div>
  )
}


// ── Disposal / return decision modal (from an expired/near-expiry row) ────────
const _DISP = {
  destroy:         { l: 'إتلاف',         c: 'bg-red-100 text-red-700' },
  return_supplier: { l: 'مرتجع للمورد',  c: 'bg-blue-100 text-blue-700' },
  quarantine:      { l: 'عزل',           c: 'bg-amber-100 text-amber-800' },
  review:          { l: 'مراجعة',        c: 'bg-gray-100 text-gray-600' },
}

function DisposalModal({ row, branch, onClose }) {
  const qc = useQueryClient()
  const bc = branch || row.branches?.[0] || ''
  const [decision, setDecision] = useState(row.tier === 'expired' ? 'destroy' : 'return_supplier')
  const [supplier, setSupplier] = useState('')
  const [qty, setQty]           = useState(row.total_qty)
  const [reason, setReason]     = useState('')
  const [err, setErr]           = useState(null)
  const [done, setDone]         = useState(false)

  const create = useMutation({
    mutationFn: () => batchesApi.expiryDisposalCreate({
      item_code: row.item_code, item_name: row.item_name, branch_code: bc,
      qty: Number(qty), expiry_date: row.earliest_expiry, decision,
      supplier_name: supplier, reason,
    }),
    onSuccess: () => { setDone(true); qc.invalidateQueries({ queryKey: ['batches', 'disposal'] }) },
    onError: (e) => setErr(e.response?.data?.detail || 'تعذّر الحفظ'),
  })

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6">
        <div className="flex items-start justify-between mb-1">
          <h3 className="text-lg font-bold">إتلاف / مرتجع</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
        </div>
        <p className="text-sm text-gray-500 mb-4">{row.item_name} — كود {row.item_code} — فرع {bc || '—'}</p>
        {done ? (
          <div className="text-center py-6">
            <div className="text-green-600 mb-2">✓ سُجِّل القرار (مسودة) — راجعه في تبويب «إتلاف/مرتجع».</div>
            <button onClick={onClose} className="px-4 py-2 text-sm bg-brand-600 text-white rounded-lg">تم</button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 text-sm mb-3">
              <label>القرار
                <select value={decision} onChange={e => setDecision(e.target.value)} className="border rounded-lg px-3 py-2 w-full mt-1">
                  <option value="destroy">إتلاف</option>
                  <option value="return_supplier">مرتجع للمورد</option>
                  <option value="quarantine">عزل</option>
                  <option value="review">مراجعة</option>
                </select>
              </label>
              <label>الكمية
                <input type="number" value={qty} onChange={e => setQty(e.target.value)} className="border rounded-lg px-3 py-2 w-full mt-1" />
              </label>
            </div>
            {decision === 'return_supplier' && (
              <label className="text-sm block mb-3">المورد
                <input value={supplier} onChange={e => setSupplier(e.target.value)} placeholder="اسم المورد" className="border rounded-lg px-3 py-2 w-full mt-1" />
              </label>
            )}
            <label className="text-sm block mb-3">السبب / ملاحظات
              <textarea value={reason} onChange={e => setReason(e.target.value)} className="border rounded-lg px-3 py-2 w-full mt-1 h-20 resize-none" />
            </label>
            <p className="text-xs text-gray-400 mb-3">لا يُخصم من SOFTECH تلقائيًا — هذا سجلّ ومستند للتنفيذ اليدوي/المعتمد.</p>
            {err && <p className="text-red-600 text-sm mb-2">{err}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
              <button onClick={() => create.mutate()} disabled={create.isPending || !bc || !(Number(qty) > 0)}
                      className="px-5 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50">
                {create.isPending ? 'جاري…' : 'تسجيل القرار'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Disposal / return ledger tab ──────────────────────────────────────────────
function DisposalTab() {
  const user = useAuthStore(s => s.user)
  const canApprove = ['admin', 'quality_manager', 'supervisor'].includes(user?.role)
  const qc = useQueryClient()
  const [statusF, setStatusF] = useState('')

  const { data } = useQuery({
    queryKey: ['batches', 'disposal', statusF],
    queryFn:  () => batchesApi.expiryDisposalList({ status: statusF || undefined }).then(r => r.data),
  })
  const rows = data?.items || []
  const totalVal = useMemo(() => rows.reduce((s, r) => s + (r.value || 0), 0), [rows])

  const setStatus = useMutation({
    mutationFn: ({ id, status }) => batchesApi.expiryDisposalStatus(id, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['batches', 'disposal'] }),
  })
  const exp = useMutation({
    mutationFn: () => batchesApi.expiryDisposalExport({ items: rows }),
    onSuccess: (res) => {
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const a = document.createElement('a'); a.href = url; a.download = 'disposal_return.xlsx'
      document.body.appendChild(a); a.click(); a.remove(); window.URL.revokeObjectURL(url)
    },
  })
  const STAT = { draft: 'bg-gray-100 text-gray-600', approved: 'bg-green-100 text-green-700',
                 done: 'bg-indigo-100 text-indigo-700', cancelled: 'bg-red-50 text-red-400' }

  return (
    <div>
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4 text-sm text-blue-900 leading-relaxed">
        سجلّ قرارات <b>الإتلاف / المرتجع</b> للأصناف منتهية الصلاحية — تُنشأ كمسودة من تبويب «أرصدة الصلاحية»،
        ثم <b>تُعتمد</b> (مدير/جودة) وتُطبَّق يدويًا في SOFTECH. لا يخصم النظام المخزون تلقائيًا.
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3 text-sm">
        <div className="flex items-center gap-2">
          <select value={statusF} onChange={e => setStatusF(e.target.value)} className="border rounded-lg px-2 py-1.5">
            <option value="">كل الحالات</option>
            <option value="draft">مسودة</option>
            <option value="approved">معتمد</option>
            <option value="done">منفّذ</option>
            <option value="cancelled">ملغي</option>
          </select>
          <span className="text-gray-600">العدد: <b>{fmtInt(rows.length)}</b> · القيمة: <b className="text-red-600">{fmtNum(totalVal)} ج</b></span>
        </div>
        <button onClick={() => exp.mutate()} disabled={exp.isPending || rows.length === 0}
                className="px-4 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
          ⬇️ تصدير / طباعة
        </button>
      </div>

      {rows.length === 0 ? (
        <div className="text-center py-14 text-gray-400">لا توجد قرارات — أنشئها من «أرصدة الصلاحية» (وضع منتهية).</div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm whitespace-nowrap">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="px-3 py-3 text-right font-semibold text-gray-600">الصنف</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">الفرع</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">الكمية</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">القيمة</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">القرار</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">المورد</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">الحالة</th>
                <th className="px-3 py-3 text-right font-semibold text-gray-600">إجراء</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-3 py-3 font-medium">{r.item_name || r.item_code}</td>
                  <td className="px-3 py-3 text-gray-500">{r.branch_code}</td>
                  <td className="px-3 py-3">{fmtNum(r.qty, 2)}</td>
                  <td className="px-3 py-3 text-red-600">{fmtNum(r.value)}</td>
                  <td className="px-3 py-3"><span className={`px-2 py-0.5 rounded-full text-xs ${_DISP[r.decision]?.c || ''}`}>{_DISP[r.decision]?.l || r.decision}</span></td>
                  <td className="px-3 py-3 text-gray-500 text-xs">{r.supplier_name || '—'}</td>
                  <td className="px-3 py-3"><span className={`px-2 py-0.5 rounded-full text-xs ${STAT[r.status] || ''}`}>{r.status_display}</span></td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-1">
                      {r.status === 'draft' && canApprove &&
                        <button onClick={() => setStatus.mutate({ id: r.id, status: 'approved' })} className="px-2 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700">اعتماد</button>}
                      {r.status === 'approved' && canApprove &&
                        <button onClick={() => setStatus.mutate({ id: r.id, status: 'done' })} className="px-2 py-1 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700">تم التنفيذ</button>}
                      {r.status !== 'cancelled' && r.status !== 'done' &&
                        <button onClick={() => setStatus.mutate({ id: r.id, status: 'cancelled' })} className="px-2 py-1 text-xs bg-white border border-gray-300 rounded hover:bg-gray-50">إلغاء</button>}
                    </div>
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
  const [tab, setTab] = useState('alerts')

  // KPI cards now read the live stkbalexpiry mirror (all nodes).
  const { data: summary } = useQuery({
    queryKey: ['batches', 'stock-expiry-summary'],
    queryFn:  () => batchesApi.stockExpirySummary({}).then(r => r.data),
  })

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">إدارة الدفعات (FEFO)</h1>
        <p className="text-sm text-gray-500 mt-1">مراقبة انتهاء الصلاحية · نظام الصرف الأول انتهاء أولاً</p>
      </div>

      {/* KPI cards — live from the stkbalexpiry mirror (all nodes) */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
          <KpiCard label="أصناف تنتهي خلال 30 يوم"  value={fmtInt(summary.lt_30?.items)}  sub={`${fmtNum(summary.lt_30?.value)} ج`}  color="text-red-600" />
          <KpiCard label="خلال 90 يوم"              value={fmtInt(summary.lt_90?.items)}  sub={`${fmtNum(summary.lt_90?.value)} ج`}  color="text-amber-600" />
          <KpiCard label="خلال 180 يوم"             value={fmtInt(summary.lt_180?.items)} sub={`${fmtNum(summary.lt_180?.value)} ج`} color="text-yellow-600" />
          <KpiCard label="قيمة معرّضة للخطر (≤180ي)" value={`${fmtNum(summary.total_at_risk_value)} ج`} color="text-gray-700" />
          <KpiCard label="منتهية ولا تزال بالمخزون"  value={fmtInt(summary.expired?.items)} sub={`${fmtNum(summary.expired?.value)} ج`} color="text-red-700" />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-6">
        {[
          { key: 'alerts', label: '🚨 قرب الانتهاء' },
          { key: 'list',   label: '📦 أرصدة الصلاحية (كل الفروع)' },
          { key: 'audit',  label: '📅 تدقيق صلاحيات الشراء' },
          { key: 'suppliers', label: '🏭 أداء الموردين (صلاحية)' },
          { key: 'reorder', label: '♻️ مراجعة الشراء' },
          { key: 'disposal', label: '🗑️ إتلاف/مرتجع' },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${
              tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Near-expiry (live stkbalexpiry mirror, all nodes) */}
      {tab === 'alerts' && <LiveStockExpiryTab initialMode="near" />}
      {/* Stock-expiry balances — near / expired / all, with mode switch */}
      {tab === 'list'   && <LiveStockExpiryTab initialMode="all" modeSwitch />}

      {tab === 'audit' && <PurchaseExpiryAuditTab />}
      {tab === 'suppliers' && <SupplierScorecardTab />}
      {tab === 'reorder' && <ProcurementReviewTab />}
      {tab === 'disposal' && <DisposalTab />}
    </div>
  )
}
