/**
 * InTransitTab.jsx
 *
 * "Transfers In Transit" tab — embedded inside TransfersPage.
 * Shows SOFTECH doccode=125 inter-branch transfers that have been issued
 * but not yet received, pulled from the local InTransitTransfer cache.
 *
 * Features:
 *  - Priority-colored grid (green/yellow/orange/red/critical)
 *  - Filters: branch, status, priority, date range
 *  - Dashboard KPI strip (total, value, critical, expiring)
 *  - Detail side-panel with items, notes, timeline, actions
 *  - Mark Received / Add Note / Force Close actions
 *  - FEFO badge for near-expiry items
 *  - Manual SOFTECH sync trigger
 */
import { useState, useEffect, Fragment } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { transitsApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

const toLatinDigits = s =>
  s ? s.replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s

// Exact SOFTECH value — groups thousands but NEVER rounds/pads the decimals.
// e.g. 172.9462 → "172.9462", 49950 → "49,950", "78.29" → "78.29".
function fmtExact(value) {
  if (value === null || value === undefined || value === '') return '—'
  const str = String(value).trim()
  if (str === '') return '—'
  const neg = str.startsWith('-')
  const [intPart, decPart] = str.replace(/^-/, '').split('.')
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return (neg ? '-' : '') + (decPart !== undefined ? `${grouped}.${decPart}` : grouped)
}

// ── Priority config ───────────────────────────────────────────────────────────

const PRIORITY = {
  green:    { label: 'طازج',          bg: '#f0fdf4', text: '#166534', dot: '#10b981', ring: '#bbf7d0' },
  yellow:   { label: 'مراقبة',        bg: '#fefce8', text: '#713f12', dot: '#f59e0b', ring: '#fde68a' },
  orange:   { label: 'متابعة',        bg: '#fff7ed', text: '#9a3412', dot: '#f97316', ring: '#fed7aa' },
  red:      { label: 'طارئ',          bg: '#fef2f2', text: '#991b1b', dot: '#ef4444', ring: '#fecaca' },
  critical: { label: 'حرج',           bg: '#450a0a', text: '#fca5a5', dot: '#7f1d1d', ring: '#7f1d1d' },
}

const STATUS_LABEL = {
  in_transit:      { label: 'قيد النقل',              icon: '🚛', color: '#3b82f6' },
  received:        { label: 'مستلم',                  icon: '✅', color: '#10b981' },
  erp_mismatch:    { label: 'تباين مع ERP',           icon: '⚠️', color: '#dc2626' },
  cancelled:       { label: 'ملغي',                   icon: '↩️', color: '#9ca3af' },
  expired_pending: { label: 'منتهي المهلة — معلق',   icon: '⏰', color: '#f59e0b' },
  force_closed:    { label: 'مغلق قسراً',             icon: '🔒', color: '#6b7280' },
}

function timeAgo(dt) {
  if (!dt) return '—'
  try {
    return toLatinDigits(
      formatDistanceToNow(new Date(dt), { locale: ar, addSuffix: true })
    )
  } catch { return '' }
}

function fmtDate(dt) {
  if (!dt) return '—'
  try { return format(new Date(dt), 'yyyy/MM/dd') } catch { return dt }
}

// Save a blob API response as a file (filename from Content-Disposition)
function saveExportResponse(res, fallbackName) {
  const cd    = res.headers['content-disposition'] || ''
  const match = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
  const fname = match ? match[1].replace(/['"]/g, '') : fallbackName
  const url = URL.createObjectURL(res.data)
  const a = document.createElement('a')
  a.href = url
  a.download = fname
  a.click()
  URL.revokeObjectURL(url)
}

// ── Priority Badge ────────────────────────────────────────────────────────────

function PriorityBadge({ priority }) {
  const p = PRIORITY[priority] || PRIORITY.green
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold"
      style={{
        background: p.bg,
        color: p.text,
        border: `1px solid ${p.ring}`,
      }}
    >
      <span
        className="w-2 h-2 rounded-full flex-shrink-0 animate-pulse"
        style={{ background: p.dot }}
      />
      {p.label}
    </span>
  )
}

// ── Status Badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const s = STATUS_LABEL[status] || STATUS_LABEL.in_transit
  return (
    <span className="inline-flex items-center gap-1 text-xs font-semibold"
      style={{ color: s.color }}>
      {s.icon} {s.label}
    </span>
  )
}

// ── KPI Strip ─────────────────────────────────────────────────────────────────

function KpiStrip({ data }) {
  if (!data) return null
  const kpis = [
    {
      label: 'قيد النقل',
      value: data.total_in_transit,
      sub: `إجمالي القيمة: ${data.total_value ? Number(data.total_value).toLocaleString('ar-EG', { maximumFractionDigits: 0 }) : '—'} ج.م`,
      color: '#3b82f6',
      icon: '🚛',
    },
    {
      label: 'متوسط أيام النقل',
      value: data.avg_days_in_transit ? `${data.avg_days_in_transit} يوم` : '—',
      color: '#6366f1',
      icon: '⏱️',
    },
    {
      label: 'حرج / طارئ',
      value: data.critical_count + data.red_count,
      sub: `${data.critical_count} حرج · ${data.red_count} طارئ`,
      color: data.critical_count > 0 ? '#ef4444' : '#f97316',
      icon: '🚨',
    },
    {
      label: 'تنتهي مهلة الإلغاء',
      value: data.cancellation_expiring,
      sub: 'خلال 24 ساعة',
      color: data.cancellation_expiring > 0 ? '#f59e0b' : '#10b981',
      icon: '⏳',
    },
    {
      label: 'تم الاستلام اليوم',
      value: data.received_today,
      color: '#10b981',
      icon: '✅',
    },
    {
      label: 'تم الإصدار اليوم',
      value: data.issued_today,
      color: '#8b5cf6',
      icon: '📤',
    },
    {
      label: 'تباين مع ERP',
      value: data.erp_mismatch_count ?? 0,
      sub: '125 ≠ 25',
      color: data.erp_mismatch_count > 0 ? '#dc2626' : '#10b981',
      icon: '⚠️',
    },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 px-6 py-3 bg-white border-b border-gray-100">
      {kpis.map((k, i) => (
        <div key={i} className="bg-gray-50 rounded-xl p-3 border border-gray-100">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-base">{k.icon}</span>
            <span className="text-xs text-gray-500 font-medium">{k.label}</span>
          </div>
          <div className="text-xl font-black tabular-nums" style={{ color: k.color }}>
            {toLatinDigits(String(k.value ?? '—'))}
          </div>
          {k.sub && <div className="text-[10px] text-gray-400 mt-0.5">{k.sub}</div>}
        </div>
      ))}
    </div>
  )
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function DetailPanel({ transit, onClose, onAction }) {
  const { user } = useAuthStore()
  const qc = useQueryClient()
  const [noteText, setNoteText] = useState('')
  const [closeReason, setCloseReason] = useState('')
  const [exporting, setExporting] = useState('') // '' | 'picking' | 'stocking'
  const [tab, setTab] = useState('items') // items | notes | timeline

  // picking = supplying-warehouse walk; stocking = receiving-branch shelf order
  async function handleExportSheet(mode) {
    setExporting(mode)
    try {
      const res = mode === 'stocking'
        ? await transitsApi.exportStocking(transit.id)
        : await transitsApi.exportPicking(transit.id)
      saveExportResponse(res, `${mode}_${transit.erp_doc_number}.xlsx`)
    } catch {
      alert(mode === 'stocking' ? 'خطأ في تصدير ورقة الترصيص' : 'خطأ في تصدير ورقة التجميع')
    } finally {
      setExporting('')
    }
  }

  const isAdmin      = user?.role === 'admin' || user?.role === 'purchasing'
  const isReceivingBranch = user?.branch_id === transit.receiving_branch

  const markReceived = useMutation({
    mutationFn: (note) => transitsApi.markReceived(transit.id, { note }),
    onSuccess: () => { qc.invalidateQueries(['in-transit']); onAction('received') },
  })

  const addNote = useMutation({
    mutationFn: () => transitsApi.addNote(transit.id, noteText),
    onSuccess: () => { qc.invalidateQueries(['in-transit']); setNoteText('') },
  })

  const forceClose = useMutation({
    mutationFn: () => transitsApi.forceClose(transit.id, closeReason),
    onSuccess: () => { qc.invalidateQueries(['in-transit']); onAction('force_closed') },
  })

  const p = PRIORITY[transit.priority] || PRIORITY.green

  const recon = transit.reconciliation || {}
  const reconCount = (recon.missing_items?.length || 0)
    + (recon.qty_diffs?.length || 0)
    + (recon.extra_items?.length || 0)
  const hasRecon = transit.transit_status === 'erp_mismatch'
    || transit.transit_status === 'received'
    || reconCount > 0
    || (transit.received_items_snapshot?.length || 0) > 0

  return (
    <div className="fixed inset-0 z-40 flex">
      {/* Backdrop */}
      <div className="flex-1 bg-black/30" onClick={onClose} />

      {/* Panel */}
      <div
        className="w-full max-w-2xl bg-white shadow-2xl overflow-y-auto flex flex-col"
        dir="rtl"
      >
        {/* Header */}
        <div
          className="px-6 py-4 border-b flex items-start gap-3"
          style={{ background: p.bg, borderColor: p.ring }}
        >
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-black text-gray-900 font-mono text-lg">
                {transit.erp_doc_number}
              </span>
              <PriorityBadge priority={transit.priority} />
              {transit.has_near_expiry && (
                <span className="bg-amber-100 text-amber-800 text-[10px] font-bold px-2 py-0.5 rounded-full border border-amber-200">
                  🌡️ منتهية الصلاحية قريباً
                </span>
              )}
              {transit.has_discrepancy && (
                <span className="bg-red-100 text-red-800 text-[10px] font-bold px-2 py-0.5 rounded-full border border-red-200">
                  ⚠️ تباين 125↔25
                </span>
              )}
            </div>
            <div className="text-sm text-gray-600">
              <span className="font-semibold">{transit.supplying_branch_name}</span>
              <span className="text-gray-400 mx-2">→</span>
              <span className="font-semibold">{transit.receiving_branch_name}</span>
            </div>
            <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
              <span>📅 {fmtDate(transit.issue_date)}</span>
              <span>⏱️ {toLatinDigits(String(transit.days_in_transit))} يوم في النقل</span>
              {transit.doc_value != null && transit.doc_value !== '' && (
                <span dir="ltr">
                  💰 {toLatinDigits(fmtExact(transit.doc_value))} ج.م
                </span>
              )}
            </div>
          </div>
          <button onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none p-1">
            ✕
          </button>
        </div>

        {/* Status row */}
        <div className="px-6 py-2 bg-gray-50 border-b border-gray-100 flex items-center gap-4 flex-wrap text-sm">
          <StatusBadge status={transit.transit_status} />
          {transit.cancellation_available && (
            <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full font-semibold">
              ↩️ الإلغاء متاح حتى {fmtDate(transit.cancellation_expires_at)}
            </span>
          )}
          {!transit.cancellation_available && transit.transit_status === 'in_transit' && (
            <span className="text-xs text-red-600 bg-red-50 px-2 py-0.5 rounded-full font-semibold">
              ⛔ انتهت مهلة الإلغاء — يجب الاستلام
            </span>
          )}
          {transit.linked_request_number && (
            transit.linked_request_detail?.id ? (
              <Link
                to={`/transfers/${transit.linked_request_detail.id}`}
                className="text-xs text-brand-700 bg-brand-50 hover:bg-brand-100 px-2 py-0.5 rounded-full font-semibold transition-colors"
                title="فتح طلب التحويل المرتبط"
              >
                🔗 الطلب المرتبط ← {transit.linked_request_number}
              </Link>
            ) : (
              <span className="text-xs text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">
                🔗 مرتبط بطلب {transit.linked_request_number}
              </span>
            )
          )}
          <div className="flex-1" />
          <button
            onClick={() => handleExportSheet('picking')}
            disabled={!!exporting || !transit.item_count}
            title={!transit.item_count ? 'لا توجد بيانات أصناف بعد — انتظر المزامنة' : 'ورقة التجميع — بمسار مخزن المصدر (Excel)'}
            className="btn-secondary text-xs px-3 py-1 flex items-center gap-1.5 disabled:opacity-40"
          >
            <span>🚚</span>
            {exporting === 'picking' ? 'جارٍ التصدير...' : 'ورقة التجميع'}
          </button>
          <button
            onClick={() => handleExportSheet('stocking')}
            disabled={!!exporting || !transit.item_count}
            title={!transit.item_count ? 'لا توجد بيانات أصناف بعد — انتظر المزامنة' : 'ورقة الترصيص — بترتيب أرفف الفرع المستلم (Excel)'}
            className="text-xs px-3 py-1 flex items-center gap-1.5 rounded-lg font-semibold text-teal-700 bg-teal-50 hover:bg-teal-100 border border-teal-200 transition-colors disabled:opacity-40"
          >
            <span>🗄️</span>
            {exporting === 'stocking' ? 'جارٍ التصدير...' : 'ورقة الترصيص'}
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-100 px-6 gap-4">
          {[
            { key: 'items',    label: `الأصناف (${transit.item_count})` },
            ...(hasRecon ? [{ key: 'recon', label: `مطابقة 125↔25${reconCount ? ` (${reconCount})` : ''}` }] : []),
            { key: 'notes',    label: 'الملاحظات' },
            { key: 'timeline', label: 'السجل' },
          ].map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`py-2.5 text-sm font-semibold border-b-2 transition-colors ${
                tab === t.key
                  ? 'border-brand-600 text-brand-700'
                  : 'border-transparent text-gray-400 hover:text-gray-600'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto">

          {/* Items tab */}
          {tab === 'items' && (
            <div className="px-6 py-4">
              {transit.fefo_warning?.length > 0 && (
                <div className="mb-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
                  <div className="font-bold text-amber-800 text-sm mb-1">
                    🌡️ تحذير FEFO — أصناف تنتهي صلاحيتها قريباً
                  </div>
                  {transit.fefo_warning.map((f, i) => (
                    <div key={i} className="text-xs text-amber-700">
                      {f.itemname} — تنتهي {fmtDate(f.expiry)}
                      {' '}({toLatinDigits(String(f.days_left))} يوم)
                    </div>
                  ))}
                </div>
              )}

              {!transit.items_snapshot?.length ? (
                <div className="text-center py-8 text-gray-400 text-sm">
                  لا توجد بيانات أصناف — ستظهر بعد المزامنة التالية
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 rounded-xl">
                    <tr>
                      <th className="text-right px-3 py-2 text-xs text-gray-500 font-semibold">الصنف</th>
                      <th className="text-right px-3 py-2 text-xs text-gray-500 font-semibold">ت الصلاحية</th>
                      <th className="text-right px-3 py-2 text-xs text-gray-500 font-semibold">الكمية</th>
                      <th className="text-right px-3 py-2 text-xs text-gray-500 font-semibold">التكلفة</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {transit.items_snapshot.map((item, i) => {
                      // SOFTECH lists an item's batches on separate lines — do the
                      // same here when a line spans >1 batch. Exports stay aggregated.
                      const batches = item.batches || []
                      const multi = batches.length > 1
                      return (
                        <Fragment key={i}>
                          <tr className="hover:bg-gray-50">
                            <td className="px-3 py-2">
                              <div className="font-semibold text-gray-800">{item.itemname}</div>
                              <div className="text-xs text-gray-400 font-mono">
                                {item.itemcode}
                                {multi && (
                                  <span className="mr-2 text-[10px] bg-indigo-50 text-indigo-700 px-1.5 py-0.5 rounded-full font-semibold">
                                    {toLatinDigits(String(batches.length))} تشغيلات
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-3 py-2 text-xs text-gray-500 tabular-nums" dir="ltr">
                              {multi ? '—' : (item.expiry ? fmtDate(item.expiry) : '—')}
                            </td>
                            <td className="px-3 py-2 tabular-nums" dir="ltr">
                              {/* both techniques: exact decimal + spelled-out packs */}
                              <div className="font-bold text-brand-700">
                                {item.qty != null ? toLatinDigits(fmtExact(item.qty)) : '—'}
                              </div>
                              {item.is_partial && item.qty_text && (
                                <div className="text-[10px] font-bold text-amber-700 bg-amber-50 rounded px-1.5 py-0.5 mt-0.5 inline-block"
                                  title="كمية جزئية — عبوات + وحدات">
                                  {toLatinDigits(item.qty_text)}
                                </div>
                              )}
                            </td>
                            <td className="px-3 py-2 tabular-nums text-gray-600" dir="ltr">
                              {item.extended_cost != null && item.extended_cost !== ''
                                ? `${toLatinDigits(fmtExact(item.extended_cost))} ج.م`
                                : '—'}
                            </td>
                          </tr>
                          {multi && batches.map((b, j) => (
                            <tr key={`${i}-${j}`} className="bg-indigo-50/30 text-xs">
                              <td className="px-3 py-1.5 pr-8 text-gray-500">
                                <span className="text-indigo-400">↳</span>{' '}
                                {/* batches differ by lot number OR expiry — label
                                    by the lot when present, else number them */}
                                {b.batch
                                  ? `تشغيلة ${b.batch}`
                                  : `تشغيلة ${toLatinDigits(String(j + 1))}`}
                                {b.near_expiry && (
                                  <span className="mr-1.5 text-[9px] bg-amber-100 text-amber-700 px-1 rounded">🌡️</span>
                                )}
                              </td>
                              <td className="px-3 py-1.5 text-gray-500 tabular-nums" dir="ltr">
                                {b.expiry ? fmtDate(b.expiry) : '—'}
                              </td>
                              <td className="px-3 py-1.5 tabular-nums" dir="ltr">
                                <span className="font-semibold text-gray-700">
                                  {b.qty != null ? toLatinDigits(fmtExact(b.qty)) : '—'}
                                </span>
                                {b.is_partial && b.qty_text && (
                                  <span className="mr-1.5 text-[9px] font-bold text-amber-700">
                                    ({toLatinDigits(b.qty_text)})
                                  </span>
                                )}
                              </td>
                              <td className="px-3 py-1.5 tabular-nums text-gray-500" dir="ltr">
                                {b.extended_cost != null && b.extended_cost !== ''
                                  ? `${toLatinDigits(fmtExact(b.extended_cost))} ج.م`
                                  : '—'}
                              </td>
                            </tr>
                          ))}
                        </Fragment>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* Reconciliation tab (125 issued ↔ 25 received) */}
          {tab === 'recon' && (
            <div className="px-6 py-4 space-y-4">
              {/* Summary banner */}
              <div className={`rounded-xl px-4 py-3 border ${
                transit.has_discrepancy
                  ? 'bg-red-50 border-red-200'
                  : 'bg-emerald-50 border-emerald-200'
              }`}>
                <div className={`font-bold text-sm mb-1 ${
                  transit.has_discrepancy ? 'text-red-800' : 'text-emerald-800'
                }`}>
                  {transit.has_discrepancy
                    ? '⚠️ يوجد تباين بين الصرف (125) والاستلام (25)'
                    : '✅ الكميات المستلمة تطابق الكميات المصروفة'}
                </div>
                <div className="grid grid-cols-3 gap-2 text-xs mt-2">
                  <div>
                    <div className="text-gray-500">قيمة الصرف</div>
                    <div className="font-bold tabular-nums" dir="ltr">{toLatinDigits(fmtExact(recon.sent_value ?? 0))} ج.م</div>
                  </div>
                  <div>
                    <div className="text-gray-500">قيمة الاستلام</div>
                    <div className="font-bold tabular-nums" dir="ltr">{toLatinDigits(fmtExact(recon.received_value ?? 0))} ج.م</div>
                  </div>
                  <div>
                    <div className="text-gray-500">فرق القيمة</div>
                    <div className={`font-bold tabular-nums ${Number(recon.value_diff || 0) < 0 ? 'text-red-700' : 'text-emerald-700'}`} dir="ltr">
                      {toLatinDigits(fmtExact(recon.value_diff ?? 0))} ج.م
                    </div>
                  </div>
                </div>
              </div>

              {/* Missing items */}
              {recon.missing_items?.length > 0 && (
                <div>
                  <div className="text-sm font-bold text-red-700 mb-2">🚫 أصناف ناقصة ({recon.missing_items.length})</div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50"><tr>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">الصنف</th>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">مصروف</th>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">مستلم</th>
                    </tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {recon.missing_items.map((it, i) => (
                        <tr key={i} className="bg-red-50/40">
                          <td className="px-3 py-1.5"><span className="font-medium text-gray-800">{it.itemname}</span> <span className="text-xs text-gray-400 font-mono">{it.itemcode}</span></td>
                          <td className="px-3 py-1.5 tabular-nums font-bold text-blue-700">{toLatinDigits(String(it.sent_qty))}</td>
                          <td className="px-3 py-1.5 tabular-nums text-red-700 font-bold">{toLatinDigits(String(it.received_qty))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Qty diffs */}
              {recon.qty_diffs?.length > 0 && (
                <div>
                  <div className="text-sm font-bold text-amber-700 mb-2">⚖️ فروق الكميات ({recon.qty_diffs.length})</div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50"><tr>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">الصنف</th>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">مصروف</th>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">مستلم</th>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">الفرق</th>
                    </tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {recon.qty_diffs.map((it, i) => (
                        <tr key={i} className="bg-amber-50/40">
                          <td className="px-3 py-1.5"><span className="font-medium text-gray-800">{it.itemname}</span> <span className="text-xs text-gray-400 font-mono">{it.itemcode}</span></td>
                          <td className="px-3 py-1.5 tabular-nums text-blue-700">{toLatinDigits(String(it.sent_qty))}</td>
                          <td className="px-3 py-1.5 tabular-nums text-green-700">{toLatinDigits(String(it.received_qty))}</td>
                          <td className="px-3 py-1.5 tabular-nums font-bold text-amber-700">{it.diff > 0 ? '+' : ''}{toLatinDigits(String(it.diff))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Extra items */}
              {recon.extra_items?.length > 0 && (
                <div>
                  <div className="text-sm font-bold text-purple-700 mb-2">➕ أصناف زائدة في الاستلام ({recon.extra_items.length})</div>
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50"><tr>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">الصنف</th>
                      <th className="text-right px-3 py-1.5 text-xs text-gray-500">مستلم</th>
                    </tr></thead>
                    <tbody className="divide-y divide-gray-50">
                      {recon.extra_items.map((it, i) => (
                        <tr key={i} className="bg-purple-50/40">
                          <td className="px-3 py-1.5"><span className="font-medium text-gray-800">{it.itemname}</span> <span className="text-xs text-gray-400 font-mono">{it.itemcode}</span></td>
                          <td className="px-3 py-1.5 tabular-nums font-bold text-purple-700">{toLatinDigits(String(it.received_qty))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!transit.received_items_snapshot?.length && (
                <div className="text-center py-6 text-gray-400 text-xs">
                  لم تُستلم بعد في SOFTECH — ستظهر المطابقة بعد ظهور مستند الاستلام (doccode=25)
                </div>
              )}
            </div>
          )}

          {/* Notes tab */}
          {tab === 'notes' && (
            <div className="px-6 py-4 space-y-3">
              {/* Add note form */}
              <div className="flex gap-2">
                <textarea
                  className="flex-1 border border-gray-200 rounded-xl p-2.5 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-brand-200"
                  rows={2}
                  placeholder="أضف ملاحظة داخلية..."
                  value={noteText}
                  onChange={e => setNoteText(e.target.value)}
                />
                <button
                  disabled={!noteText.trim() || addNote.isPending}
                  onClick={() => addNote.mutate()}
                  className="btn-primary text-sm px-4 self-start disabled:opacity-50"
                >
                  {addNote.isPending ? '...' : 'إرسال'}
                </button>
              </div>

              {/* Notes list */}
              {!transit.notes?.length ? (
                <div className="text-center py-6 text-gray-400 text-sm">لا توجد ملاحظات</div>
              ) : (
                transit.notes.map(note => (
                  <div
                    key={note.id}
                    className={`rounded-xl p-3 border ${
                      note.note_type === 'alert' ? 'bg-amber-50 border-amber-100' :
                      note.note_type === 'system' ? 'bg-gray-50 border-gray-100' :
                      'bg-blue-50 border-blue-100'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm">{note.type_icon}</span>
                      <span className="text-xs font-bold text-gray-700">{note.created_by_name}</span>
                      <span className="text-xs text-gray-400 mr-auto">{timeAgo(note.created_at)}</span>
                    </div>
                    <div className="text-sm text-gray-700">{note.body}</div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Timeline tab */}
          {tab === 'timeline' && (
            <div className="px-6 py-4">
              {!transit.audit_events?.length ? (
                <div className="text-center py-6 text-gray-400 text-sm">لا يوجد سجل</div>
              ) : (
                <div className="space-y-2">
                  {transit.audit_events.map(ev => (
                    <div key={ev.id} className="flex gap-3 items-start text-sm">
                      <div className="w-2 h-2 rounded-full bg-brand-400 mt-1.5 flex-shrink-0" />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-gray-700">{ev.actor_name}</span>
                          <span className="text-xs text-gray-400">{timeAgo(ev.created_at)}</span>
                        </div>
                        {ev.detail && (
                          <div className="text-xs text-gray-500 mt-0.5">{ev.detail}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Actions footer */}
        {transit.transit_status === 'in_transit' && (
          <div className="px-6 py-4 border-t border-gray-100 bg-gray-50 space-y-3">

            {/* Mark Received (receiving branch or admin) */}
            {(isAdmin || isReceivingBranch) && (
              <button
                onClick={() => markReceived.mutate('')}
                disabled={markReceived.isPending}
                className="w-full bg-emerald-600 hover:bg-emerald-700 text-white font-bold py-2.5 rounded-xl text-sm transition-colors disabled:opacity-50"
              >
                {markReceived.isPending ? '...' : '✅ تسجيل الاستلام'}
              </button>
            )}

            {/* Force Close (admin only) */}
            {isAdmin && (
              <div className="space-y-1.5">
                <textarea
                  className="w-full border border-gray-200 rounded-xl p-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-red-200"
                  rows={2}
                  placeholder="سبب الإغلاق القسري (مطلوب — 10 أحرف على الأقل)..."
                  value={closeReason}
                  onChange={e => setCloseReason(e.target.value)}
                />
                <button
                  onClick={() => forceClose.mutate()}
                  disabled={closeReason.trim().length < 10 || forceClose.isPending}
                  className="w-full bg-red-50 hover:bg-red-100 text-red-700 font-bold py-2 rounded-xl text-sm border border-red-200 transition-colors disabled:opacity-40"
                >
                  {forceClose.isPending ? '...' : '🔒 إغلاق قسري'}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Filters Bar ───────────────────────────────────────────────────────────────

function FiltersBar({ filters, setFilters, branches }) {
  return (
    <div className="flex gap-2 px-6 py-3 border-b border-gray-100 bg-white flex-wrap items-center">
      {/* Priority filter */}
      <select
        className="input-field text-xs w-36"
        value={filters.priority || ''}
        onChange={e => setFilters(f => ({ ...f, priority: e.target.value }))}
      >
        <option value="">كل الأولويات</option>
        {Object.entries(PRIORITY).map(([k, v]) => (
          <option key={k} value={k}>{v.label}</option>
        ))}
      </select>

      {/* Status filter */}
      <select
        className="input-field text-xs w-44"
        value={filters.transit_status || ''}
        onChange={e => setFilters(f => ({ ...f, transit_status: e.target.value }))}
      >
        <option value="">كل الحالات</option>
        {Object.entries(STATUS_LABEL).map(([k, v]) => (
          <option key={k} value={k}>{v.icon} {v.label}</option>
        ))}
      </select>

      {/* Supplying branch */}
      <select
        className="input-field text-xs w-44"
        value={filters.supplying_branch || ''}
        onChange={e => setFilters(f => ({ ...f, supplying_branch: e.target.value }))}
      >
        <option value="">فرع المصدر (الكل)</option>
        {branches.map(b => (
          <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
        ))}
      </select>

      {/* Receiving branch */}
      <select
        className="input-field text-xs w-44"
        value={filters.receiving_branch || ''}
        onChange={e => setFilters(f => ({ ...f, receiving_branch: e.target.value }))}
      >
        <option value="">فرع المستلم (الكل)</option>
        {branches.map(b => (
          <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
        ))}
      </select>

      {/* Min days */}
      <select
        className="input-field text-xs w-36"
        value={filters.min_days || ''}
        onChange={e => setFilters(f => ({ ...f, min_days: e.target.value }))}
      >
        <option value="">كل الأعمار</option>
        <option value="3">3+ أيام</option>
        <option value="5">5+ أيام</option>
        <option value="7">7+ أيام</option>
        <option value="10">10+ أيام</option>
      </select>

      {/* Clear */}
      {Object.values(filters).some(Boolean) && (
        <button
          onClick={() => setFilters({})}
          className="btn-secondary text-xs px-3"
        >
          مسح الفلاتر
        </button>
      )}
    </div>
  )
}

// ── Main Grid ─────────────────────────────────────────────────────────────────

// Grid column → backend ordering key (must match the viewset's ordering_fields)
const SORT_COLUMNS = [
  { key: 'doc_number_num',         label: 'رقم المستند' },
  { key: 'priority_rank',          label: 'الأولوية' },
  { key: 'supply_sort',            label: 'فرع المصدر' },
  { key: 'recv_sort',              label: 'فرع المستلم' },
  { key: 'issue_date',             label: 'تاريخ الإصدار' },
  { key: 'days_in_transit',        label: 'أيام النقل' },
  { key: 'item_count',             label: 'الأصناف' },
  { key: 'doc_value',              label: 'القيمة' },
  { key: 'transit_status',         label: 'الحالة' },
  { key: 'cancellation_available', label: 'الإلغاء' },
]

function SortHeader({ col, sort, onSort }) {
  const active = sort.field === col.key
  const arrow = !active ? '↕' : (sort.dir === 'asc' ? '▲' : '▼')
  return (
    <th
      onClick={() => onSort(col.key)}
      title="اضغط للترتيب — تصاعدي / تنازلي"
      className={`text-right px-4 py-3 text-xs font-semibold cursor-pointer select-none whitespace-nowrap
        transition-colors ${active ? 'text-brand-700 bg-brand-50/60' : 'text-gray-500 hover:text-gray-700'}`}
    >
      {col.label}
      <span className={`mr-1 ${active ? 'text-brand-600' : 'text-gray-300'}`}>{arrow}</span>
    </th>
  )
}

function TransitGrid({ items, onRowClick, checkedIds, onToggleCheck, onToggleAll,
                       sort, onSort }) {
  if (!items.length) {
    return (
      <div className="px-6 py-16 text-center">
        <div className="text-5xl mb-3">🚛</div>
        <div className="text-gray-600 font-semibold">لا توجد تحويلات قيد النقل</div>
        <div className="text-gray-400 text-xs mt-1">
          ستظهر هنا التحويلات الصادرة من SOFTECH (doccode=125) التي لم تُستلم بعد
        </div>
      </div>
    )
  }

  return (
    <div className="px-6 py-4">
      <div className="card p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              <th className="px-3 py-3 w-8">
                <input
                  type="checkbox"
                  className="accent-brand-600 cursor-pointer"
                  title="تحديد الكل (لتصدير ورقة تجميع موحدة)"
                  checked={items.length > 0 && items.every(i => checkedIds.has(i.id))}
                  onChange={onToggleAll}
                />
              </th>
              {SORT_COLUMNS.map(col => (
                <SortHeader key={col.key} col={col} sort={sort} onSort={onSort} />
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {items.map(tr => {
              const p = PRIORITY[tr.priority] || PRIORITY.green
              return (
                <tr
                  key={tr.id}
                  onClick={() => onRowClick(tr)}
                  className="cursor-pointer hover:bg-brand-50 transition-colors"
                  style={{ borderRight: `3px solid ${p.dot}` }}
                >
                  <td className="px-3 py-3" onClick={e => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      className="accent-brand-600 cursor-pointer"
                      checked={checkedIds.has(tr.id)}
                      onChange={() => onToggleCheck(tr.id)}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-black text-gray-900 font-mono">{tr.erp_doc_number}</div>
                    {tr.has_near_expiry && (
                      <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                        🌡️ FEFO
                      </span>
                    )}
                    {tr.has_discrepancy && (
                      <span className="text-[10px] bg-red-100 text-red-700 px-1.5 py-0.5 rounded mr-1">
                        ⚠️ تباين
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <PriorityBadge priority={tr.priority} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="bg-brand-50 text-brand-700 px-2 py-0.5 rounded text-xs font-medium">
                      {tr.supplying_branch_name}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="bg-purple-50 text-purple-700 px-2 py-0.5 rounded text-xs font-medium">
                      {tr.receiving_branch_name}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-600 tabular-nums">
                    {fmtDate(tr.issue_date)}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className="font-black tabular-nums text-base"
                      style={{ color: p.dot }}
                    >
                      {toLatinDigits(String(tr.days_in_transit))}
                    </span>
                    <span className="text-gray-400 text-xs mr-1">يوم</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 tabular-nums">
                    {tr.item_count} صنف
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-700 tabular-nums" dir="ltr">
                    {tr.doc_value != null && tr.doc_value !== ''
                      ? `${toLatinDigits(fmtExact(tr.doc_value))} ج.م`
                      : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={tr.transit_status} />
                  </td>
                  <td className="px-4 py-3">
                    {tr.cancellation_available ? (
                      <span className="text-[10px] bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full font-semibold">
                        ↩️ متاح
                      </span>
                    ) : (
                      <span className="text-[10px] text-gray-300">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Accountability Scorecard ──────────────────────────────────────────────────

function ScoreList({ title, rows, valueKey, fmtVal, icon, accent }) {
  return (
    <div className="card">
      <div className="text-sm font-bold text-gray-700 mb-3 flex items-center gap-1.5">
        <span>{icon}</span>{title}
      </div>
      {!rows?.length ? (
        <div className="text-xs text-gray-400 text-center py-4">لا توجد بيانات كافية</div>
      ) : (
        <ol className="space-y-1.5">
          {rows.map((r, i) => (
            <li key={r.branch_id} className="flex items-center gap-2 text-sm">
              <span className="w-5 h-5 rounded-full bg-gray-100 text-gray-500 text-xs flex items-center justify-center flex-shrink-0 font-bold">
                {toLatinDigits(String(i + 1))}
              </span>
              <span className="flex-1 truncate text-gray-800">{r.branch_name}</span>
              <span className={`font-black tabular-nums ${accent}`}>{fmtVal(r[valueKey])}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function ScorecardModal({ onClose }) {
  const [days, setDays] = useState(90)
  const { data, isLoading } = useQuery({
    queryKey: ['transit-scorecard', days],
    queryFn: () => transitsApi.scorecard({ days }).then(r => r.data),
    staleTime: 120_000,
  })

  const fmtMoney = v => `${Number(v || 0).toLocaleString('ar-EG', { maximumFractionDigits: 0 })} ج.م`
  const fmtDays  = v => v != null ? `${toLatinDigits(String(v))} يوم` : '—'
  const fmtCount = v => toLatinDigits(String(v ?? 0))

  return (
    <div className="fixed inset-0 z-40 flex" dir="rtl">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <div className="w-full max-w-3xl bg-gray-50 shadow-2xl overflow-y-auto">
        <div className="px-6 py-4 bg-white border-b border-gray-200 flex items-center gap-3 sticky top-0 z-10">
          <div className="flex-1">
            <h2 className="text-lg font-black text-gray-900">بطاقة مساءلة الفروع</h2>
            <p className="text-xs text-gray-400">أداء استلام التحويلات والمخزون العائم</p>
          </div>
          <select value={days} onChange={e => setDays(Number(e.target.value))} className="input-field text-xs w-32">
            <option value={30}>آخر 30 يوم</option>
            <option value={90}>آخر 90 يوم</option>
            <option value={180}>آخر 180 يوم</option>
            <option value={365}>آخر سنة</option>
          </select>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl leading-none p-1">✕</button>
        </div>

        <div className="p-6">
          {isLoading ? (
            <div className="grid sm:grid-cols-2 gap-4 animate-pulse">
              {[1,2,3,4].map(i => <div key={i} className="h-40 bg-gray-100 rounded-xl" />)}
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 gap-4">
              <ScoreList title="الأسرع استلاماً" rows={data?.fastest_receivers}
                valueKey="avg_receive_days" fmtVal={fmtDays} icon="⚡" accent="text-emerald-700" />
              <ScoreList title="الأبطأ استلاماً" rows={data?.slowest_receivers}
                valueKey="avg_receive_days" fmtVal={fmtDays} icon="🐢" accent="text-red-700" />
              <ScoreList title="أعلى مخزون عائم" rows={data?.highest_floating}
                valueKey="floating_value" fmtVal={fmtMoney} icon="💰" accent="text-amber-700" />
              <ScoreList title="أكثر التباينات (125↔25)" rows={data?.most_mismatches}
                valueKey="mismatch_count" fmtVal={fmtCount} icon="⚠️" accent="text-red-700" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function InTransitTab({ openId = null, onOpenConsumed }) {
  const { user } = useAuthStore()
  const qc       = useQueryClient()
  const [filters, setFilters] = useState({ transit_status: 'in_transit' })
  // Deep-link: open a specific document straight into the detail panel
  // (e.g. arriving from a transfer request's "قيد النقل ←" link).
  const [selected, setSelected] = useState(openId ? { id: openId } : null)
  const [toast, setToast]       = useState('')
  const [showScorecard, setShowScorecard] = useState(false)
  const [checkedIds, setCheckedIds] = useState(new Set())
  const [exporting, setExporting]   = useState('') // '' | 'picking' | 'stocking'
  // column sort — { field: <ordering key>, dir: 'asc' | 'desc' }
  const [sort, setSort] = useState({ field: 'days_in_transit', dir: 'desc' })

  // React to a changing deep-link id (navigating between two transit links)
  useEffect(() => {
    if (openId) {
      setSelected({ id: openId })
      onOpenConsumed?.()
    }
  }, [openId])   // eslint-disable-line react-hooks/exhaustive-deps

  function handleSort(field) {
    setSort(prev =>
      prev.field === field
        ? { field, dir: prev.dir === 'asc' ? 'desc' : 'asc' }   // toggle direction
        : { field, dir: 'asc' })                                // new column → ascending
  }
  const orderingParam = `${sort.dir === 'desc' ? '-' : ''}${sort.field}`

  // Load branches for filter dropdowns
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
    staleTime: 300_000,
  })

  // Dashboard KPIs
  const { data: dashboard } = useQuery({
    queryKey: ['transit-dashboard'],
    queryFn: () => transitsApi.dashboard().then(r => r.data),
    refetchInterval: 60_000,
  })

  // Main grid data
  const { data: items = [], isLoading, isFetching } = useQuery({
    queryKey: ['in-transit', filters, orderingParam],
    queryFn: () => transitsApi.list({
      ...filters,
      page_size: 200,
      ordering: orderingParam,
    }).then(r => r.data.results || r.data),
    refetchInterval: 60_000,
  })

  // Load full detail when a row is selected
  const { data: detail } = useQuery({
    queryKey: ['in-transit-detail', selected?.id],
    queryFn: () => transitsApi.get(selected.id).then(r => r.data),
    enabled: !!selected?.id,
  })

  const syncMutation = useMutation({
    mutationFn: transitsApi.sync,
    onSuccess: () => {
      qc.invalidateQueries(['in-transit'])
      qc.invalidateQueries(['transit-dashboard'])
      showToast('بدأت المزامنة مع SOFTECH')
    },
  })

  function showToast(msg) {
    setToast(msg)
    setTimeout(() => setToast(''), 4000)
  }

  function toggleCheck(id) {
    setCheckedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleAll() {
    setCheckedIds(prev =>
      items.every(i => prev.has(i.id))
        ? new Set()
        : new Set(items.map(i => i.id))
    )
  }

  // mode: 'picking' (مسار مخزن المصدر) | 'stocking' (أرفف الفرع المستلم)
  async function exportSheetBulk(mode) {
    const ids = [...checkedIds]
    if (!ids.length) return
    const label = mode === 'stocking' ? 'ورقة الترصيص' : 'ورقة التجميع'
    setExporting(mode)
    try {
      const res = mode === 'stocking'
        ? await transitsApi.exportStockingBulk(ids)
        : await transitsApi.exportPickingBulk(ids)
      saveExportResponse(res, `${mode}_${ids.length}_orders.xlsx`)
      showToast(`📋 تم تصدير ${label} (${ids.length} إذن)`)
      setCheckedIds(new Set())
    } catch {
      showToast(`❌ خطأ في تصدير ${label}`)
    } finally {
      setExporting('')
    }
  }

  const inTransitCount  = items.filter(i => i.transit_status === 'in_transit').length
  const criticalCount   = items.filter(i => i.priority === 'critical').length
  const isAdmin = user?.role === 'admin' || user?.role === 'purchasing'

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">

      {/* Toast */}
      {toast && (
        <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 bg-emerald-600 text-white px-6 py-3 rounded-xl shadow-xl text-sm font-semibold">
          {toast}
        </div>
      )}

      {/* KPI strip */}
      <KpiStrip data={dashboard} />

      {/* Sub-header: counts + sync button */}
      <div className="bg-white border-b border-gray-100 px-6 py-2.5 flex items-center gap-3">
        <div className="text-sm text-gray-600">
          <span className="font-bold text-gray-900">{inTransitCount}</span> قيد النقل
          {criticalCount > 0 && (
            <span className="text-red-600 font-bold mr-3">· {criticalCount} حرج 🚨</span>
          )}
          {isFetching && <span className="text-gray-400 text-xs mr-2">(يتم التحديث...)</span>}
        </div>
        <div className="flex-1" />
        {checkedIds.size > 0 && (
          <>
            <button
              onClick={() => exportSheetBulk('picking')}
              disabled={!!exporting}
              title="بمسار مخزن المصدر"
              className="text-xs px-3 py-1.5 flex items-center gap-1.5 rounded-lg font-bold text-white bg-brand-600 hover:bg-brand-700 transition-colors disabled:opacity-50"
            >
              <span>🚚</span>
              {exporting === 'picking'
                ? 'جارٍ التصدير...'
                : `ورقة التجميع (${toLatinDigits(String(checkedIds.size))})`}
            </button>
            <button
              onClick={() => exportSheetBulk('stocking')}
              disabled={!!exporting}
              title="بترتيب أرفف الفرع المستلم"
              className="text-xs px-3 py-1.5 flex items-center gap-1.5 rounded-lg font-bold text-white bg-teal-600 hover:bg-teal-700 transition-colors disabled:opacity-50"
            >
              <span>🗄️</span>
              {exporting === 'stocking'
                ? 'جارٍ التصدير...'
                : `ورقة الترصيص (${toLatinDigits(String(checkedIds.size))})`}
            </button>
          </>
        )}
        <Link
          to="/pick-zones"
          className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
          title="إدارة مناطق التجميع وقواعد التصنيف"
        >
          <span>📍</span>
          مناطق التجميع
        </Link>
        <button
          onClick={() => setShowScorecard(true)}
          className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
        >
          <span>🏆</span>
          بطاقة المساءلة
        </button>
        {isAdmin && (
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
          >
            <span className={syncMutation.isPending ? 'animate-spin' : ''}>🔄</span>
            {syncMutation.isPending ? 'جارٍ المزامنة...' : 'مزامنة SOFTECH'}
          </button>
        )}
      </div>

      {/* Filters */}
      <FiltersBar filters={filters} setFilters={setFilters} branches={branches} />

      {/* Grid */}
      {isLoading ? (
        <div className="px-6 py-5 space-y-2 animate-pulse">
          {[1,2,3,4,5].map(i => (
            <div key={i} className="h-14 bg-gray-100 rounded-xl" />
          ))}
        </div>
      ) : (
        <TransitGrid
          items={items}
          onRowClick={row => setSelected(row)}
          checkedIds={checkedIds}
          onToggleCheck={toggleCheck}
          onToggleAll={toggleAll}
          sort={sort}
          onSort={handleSort}
        />
      )}

      {/* Detail panel */}
      {selected && (
        <DetailPanel
          transit={detail || selected}
          onClose={() => setSelected(null)}
          onAction={(action) => {
            setSelected(null)
            qc.invalidateQueries(['in-transit'])
            qc.invalidateQueries(['transit-dashboard'])
            const msgs = {
              received:     '✅ تم تسجيل الاستلام',
              force_closed: '🔒 تم الإغلاق القسري',
            }
            if (msgs[action]) showToast(msgs[action])
          }}
        />
      )}

      {/* Accountability scorecard */}
      {showScorecard && <ScorecardModal onClose={() => setShowScorecard(false)} />}
    </div>
  )
}
