/**
 * DemandRecoveryPage.jsx  —  /demand/recovery
 * Phase 1 — Back-in-stock recovery queue + ROI tiles.
 * Worklist of named customers whose wanted item is back in stock, sorted by value.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { demandApi } from '../api/client'
import { tint } from '../theme/theme'
import CanDo from '../components/CanDo'
import { formatDistanceToNow } from 'date-fns'
import { ar } from 'date-fns/locale'

const BRAND = 'rgb(var(--c-brand-600))'
const GREEN = '#10b981'
const BLUE  = '#3b82f6'
const RED   = '#ef4444'
const PURPLE = '#8b5cf6'

const toLatin = s => s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
const egp = v => (Number(v) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 })

const DISQUALIFY_REASONS = [
  { value: 'not_in_egypt',    label: 'غير متوفر في مصر' },
  { value: 'discontinued',    label: 'متوقف عن الإنتاج' },
  { value: 'not_allowed',     label: 'غير مسموح ببيعه في الصيدلية' },
  { value: 'unknown_item',    label: 'صنف غير معروف' },
  { value: 'never_available', label: 'لن يتوفر مطلقاً' },
  { value: 'other',           label: 'أخرى' },
]

const OPT_OUT_REASONS = [
  { value: 'not_needed',       label: 'لم يعد بحاجته' },
  { value: 'moved',            label: 'انتقل / غادر' },
  { value: 'for_other_person', label: 'كان يطلبه لشخص آخر' },
  { value: 'other',            label: 'أخرى' },
]

function timeAgo(d) {
  if (!d) return '—'
  try { return toLatin(formatDistanceToNow(new Date(d), { locale: ar, addSuffix: true })) } catch { return '' }
}

// ── KPI tile ──────────────────────────────────────────────────────────────────
function KpiTile({ icon, label, value, sub, color, bg }) {
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

// ── Reason modal (opt-out / disqualify) ───────────────────────────────────────
function ReasonModal({ title, hint, reasons, confirmLabel, confirmColor, onConfirm, onClose, busy }) {
  const [reason, setReason] = useState(reasons[0].value)
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <h3 className="font-black text-gray-900 text-base mb-1">{title}</h3>
        {hint && <p className="text-xs text-gray-500 mb-4">{hint}</p>}
        <label className="label text-xs">السبب</label>
        <select className="input-field" value={reason} onChange={e => setReason(e.target.value)}>
          {reasons.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
        <div className="flex gap-2 justify-end mt-5">
          <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
          <button onClick={() => onConfirm(reason)} disabled={busy}
            className="text-sm px-4 py-2 rounded-lg text-white font-semibold disabled:opacity-50"
            style={{ background: confirmColor }}>
            {busy ? 'جارٍ...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Recover modal ─────────────────────────────────────────────────────────────
function RecoverModal({ row, onConfirm, onClose, busy }) {
  const [revenue, setRevenue] = useState(row.line_value != null ? String(row.line_value) : '')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md p-6">
        <h3 className="font-black text-gray-900 text-base mb-1">💰 تأكيد استرداد البيعة</h3>
        <p className="text-xs text-gray-500 mb-4">
          {row.display_name} — العميل {row.customer_name || row.phone}
        </p>
        <label className="label text-xs">الإيراد المُسترَد (ج.م)</label>
        <input type="number" min="0" step="0.01" className="input-field" dir="ltr"
          value={revenue} onChange={e => setRevenue(e.target.value)} />
        <p className="text-xs text-gray-400 mt-1">
          القيمة المقترحة محسوبة من السعر المُجمَّد × الكمية. عدّلها لتطابق الفاتورة الفعلية.
        </p>
        <div className="flex gap-2 justify-end mt-5">
          <button onClick={onClose} className="btn-secondary text-sm px-4">إلغاء</button>
          <button onClick={() => onConfirm(revenue === '' ? null : Number(revenue))} disabled={busy}
            className="text-sm px-4 py-2 rounded-lg text-white font-semibold disabled:opacity-50"
            style={{ background: GREEN }}>
            {busy ? 'جارٍ...' : 'تأكيد الاسترداد'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Recovery row ──────────────────────────────────────────────────────────────
function RecoveryRow({ row, onAction }) {
  const value = row.line_value
  const stock = row.stock_at_branch
  return (
    <tr className="border-b border-gray-50 last:border-0 hover:bg-brand-50/40 transition-colors">
      <td className="px-4 py-3">
        <div className="font-semibold text-gray-800 text-sm">{row.customer_name || '—'}</div>
        <div className="text-xs text-gray-500 font-mono" dir="ltr">{row.phone}</div>
        <div className="text-xs text-brand-600 font-mono mt-0.5">{row.demand_number}</div>
      </td>
      <td className="px-4 py-3">
        <div className="font-semibold text-gray-800 text-sm">{row.display_name}</div>
        <div className="text-xs text-gray-400">الكمية: {toLatin(row.quantity)}</div>
      </td>
      <td className="px-4 py-3 text-xs text-gray-600">{row.branch_name}</td>
      <td className="px-4 py-3 text-xs">
        <span className={stock > 0 ? 'text-green-600 font-semibold' : 'text-gray-400'}>
          {stock != null ? `${toLatin(stock)} متاح` : '—'}
        </span>
      </td>
      <td className="px-4 py-3 text-sm font-bold tabular-nums" style={{ color: BRAND }}>
        {value != null ? `${egp(value)} ج.م` : '—'}
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">
        <div>{toLatin(row.days_waiting)} يوم</div>
        {row.notified_customer_at && (
          <div className="text-[11px] text-gray-400">تواصل {timeAgo(row.notified_customer_at)}</div>
        )}
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-1.5 justify-end flex-wrap">
          {row.wa_link && (
            <button onClick={() => onAction('whatsapp', row)}
              className="px-2.5 py-1 rounded-lg text-xs font-semibold text-white"
              style={{ background: GREEN }} title="فتح واتساب وتسجيل التواصل">
              واتساب
            </button>
          )}
          <button onClick={() => onAction('recover', row)}
            className="px-2.5 py-1 rounded-lg text-xs font-semibold text-white"
            style={{ background: BRAND }} title="تأكيد استرداد البيعة">
            استرداد
          </button>
          <CanDo module="reservations" action="create">
            <button onClick={() => onAction('reserve', row)}
              className="px-2.5 py-1 rounded-lg text-xs font-semibold text-white"
              style={{ background: BLUE }} title="تحويل إلى حجز للعميل">
              حجز
            </button>
          </CanDo>
          <button onClick={() => onAction('opt_out', row)}
            className="px-2 py-1 rounded-lg text-xs font-semibold bg-gray-100 text-gray-600"
            title="رفض العميل التواصل بخصوص هذا الصنف">
            🔕
          </button>
          <CanDo module="demand" action="approve">
            <button onClick={() => onAction('disqualify', row)}
              className="px-2 py-1 rounded-lg text-xs font-semibold bg-red-50 text-red-600"
              title="استبعاد من قائمة الاسترداد (يتطلب اعتماد)">
              🚫
            </button>
          </CanDo>
        </div>
      </td>
    </tr>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function DemandRecoveryPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [modal, setModal] = useState(null)   // { type, row }

  const { data: kpis } = useQuery({
    queryKey: ['demand-dashboard-kpis'],
    queryFn: () => demandApi.dashboard().then(r => r.data?.kpis || {}),
    refetchInterval: 120_000,
  })

  const { data: queue = [], isLoading } = useQuery({
    queryKey: ['demand-recovery-queue'],
    queryFn: () => demandApi.recoveryQueue().then(r => r.data.results || r.data),
    refetchInterval: 60_000,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['demand-recovery-queue'] })
    qc.invalidateQueries({ queryKey: ['demand-dashboard-kpis'] })
  }

  const recoverM   = useMutation({ mutationFn: ({ row, revenue }) => demandApi.recoverItem(row.demand_id, row.id, { recovered_revenue: revenue }), onSuccess: () => { invalidate(); setModal(null) } })
  const notifiedM  = useMutation({ mutationFn: ({ row, channel }) => demandApi.markNotified(row.demand_id, row.id, { channel }), onSuccess: invalidate })
  const optOutM    = useMutation({ mutationFn: ({ row, reason }) => demandApi.optOutItem(row.demand_id, row.id, { reason }), onSuccess: () => { invalidate(); setModal(null) } })
  const disqualM   = useMutation({ mutationFn: ({ row, reason }) => demandApi.disqualifyItem(row.demand_id, row.id, { reason }), onSuccess: () => { invalidate(); setModal(null) } })
  const reserveM   = useMutation({
    mutationFn: ({ row }) => demandApi.itemToReservation(row.demand_id, row.id),
    onSuccess: (res) => { invalidate(); if (res?.data?.reservation_id) navigate(`/reservations/${res.data.reservation_id}`) },
  })

  function handleAction(type, row) {
    if (type === 'whatsapp') {
      if (row.wa_link) window.open(row.wa_link, '_blank', 'noopener')
      notifiedM.mutate({ row, channel: 'whatsapp' })
      return
    }
    if (type === 'reserve') {
      reserveM.mutate({ row })
      return
    }
    setModal({ type, row })
  }

  const totalValue = queue.reduce((s, r) => s + (Number(r.line_value) || 0), 0)

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
            <h1 className="text-xl font-black text-gray-900">🔔 قائمة الاسترداد — عاد للمخزون</h1>
            <p className="text-xs text-gray-400 mt-0.5">
              عملاء طلبوا أصنافاً نفدت ثم عادت للمخزون — تواصل معهم لاسترداد البيعة
            </p>
          </div>
          <button onClick={() => navigate('/demand/dashboard')} className="btn-secondary text-sm">
            📊 لوحة الطلب الضائع
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-5">

        {/* ROI tiles */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KpiTile icon="💰" label="إيراد مُسترَد (٣٠ يوم)"
            value={`${egp(kpis?.recovered_revenue_30d)} ج.م`}
            sub={`${toLatin(kpis?.recovered_count_30d ?? 0)} بيعة مُستردة`}
            color={GREEN} bg="#f0fdf4" />
          <KpiTile icon="📈" label="معدل الاسترداد"
            value={`${toLatin(kpis?.recovery_rate ?? 0)}%`}
            sub="من الأصناف التي عادت للمخزون"
            color={BLUE} bg="#eff6ff" />
          <KpiTile icon="🔔" label="فرص مفتوحة"
            value={toLatin(kpis?.open_recovery_count ?? 0)}
            sub="بانتظار التواصل"
            color={PURPLE} bg="#f5f3ff" />
          <KpiTile icon="🎯" label="قيمة الفرص المفتوحة"
            value={`${egp(kpis?.open_recovery_value)} ج.م`}
            sub="إيراد محتمل قابل للاسترداد"
            color={BRAND} bg="rgb(var(--c-brand-50))" />
        </div>

        {/* Queue */}
        {isLoading ? (
          <div className="space-y-2 animate-pulse">
            {[1,2,3,4].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl" />)}
          </div>
        ) : queue.length === 0 ? (
          <div className="bg-white rounded-2xl border border-gray-100 text-center py-16">
            <div className="text-5xl mb-3">🎉</div>
            <div className="text-gray-600 font-semibold">لا توجد فرص استرداد حالياً</div>
            <div className="text-gray-400 text-xs mt-1">
              عندما يعود صنف مطلوب للمخزون، سيظهر العميل هنا تلقائياً بعد المزامنة
            </div>
          </div>
        ) : (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
              <span className="text-sm font-bold text-gray-700">
                {toLatin(queue.length)} فرصة استرداد
              </span>
              <span className="text-xs text-gray-500">
                إجمالي القيمة: <b style={{ color: BRAND }}>{egp(totalValue)} ج.م</b>
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">العميل</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الصنف</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الفرع</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">المخزون</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">القيمة</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">الانتظار</th>
                    <th className="text-right px-4 py-3 text-xs font-semibold text-gray-500">إجراءات</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map(row => (
                    <RecoveryRow key={row.id} row={row} onAction={handleAction} />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      {modal?.type === 'recover' && (
        <RecoverModal row={modal.row} busy={recoverM.isPending}
          onClose={() => setModal(null)}
          onConfirm={revenue => recoverM.mutate({ row: modal.row, revenue })} />
      )}
      {modal?.type === 'opt_out' && (
        <ReasonModal title="🔕 رفض التواصل بخصوص هذا الصنف"
          hint="يُسجَّل بعد أول محاولة تواصل إذا لم يعد العميل راغباً في متابعة هذا الصنف."
          reasons={OPT_OUT_REASONS} confirmLabel="تأكيد" confirmColor={PURPLE}
          busy={optOutM.isPending}
          onClose={() => setModal(null)}
          onConfirm={reason => optOutM.mutate({ row: modal.row, reason })} />
      )}
      {modal?.type === 'disqualify' && (
        <ReasonModal title="🚫 استبعاد من قائمة الاسترداد"
          hint="للأصناف التي لن تكون فرصة استرداد حقيقية (غير متوفرة في مصر، متوقفة، غير مسموح بها…)."
          reasons={DISQUALIFY_REASONS} confirmLabel="استبعاد" confirmColor={RED}
          busy={disqualM.isPending}
          onClose={() => setModal(null)}
          onConfirm={reason => disqualM.mutate({ row: modal.row, reason })} />
      )}
    </div>
  )
}
