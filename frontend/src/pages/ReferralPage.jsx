/**
 * ReferralPage.jsx
 *
 * Referral system management page.
 *
 * Tabs:
 *   - Lead queue  : all referral leads with status filter + staff actions (validate / invite)
 *   - My code     : show the authenticated user's referral QR + URL
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { referralApi } from '../api/client'

// ── helpers ───────────────────────────────────────────────────────────────────
const STATUS_META = {
  pending:    { label: 'بانتظار الدعوة', color: 'bg-yellow-100 text-yellow-800' },
  invited:    { label: 'تم الإرسال',     color: 'bg-blue-100 text-blue-700' },
  registered: { label: 'سجَّل',          color: 'bg-teal-100 text-teal-700' },
  validated:  { label: 'تم التحقق',      color: 'bg-green-100 text-green-700' },
  rewarded:   { label: 'مكافأة',         color: 'bg-purple-100 text-purple-700' },
  rejected:   { label: 'مرفوض',          color: 'bg-red-100 text-red-600' },
  frozen:     { label: 'مجمَّد',          color: 'bg-gray-100 text-gray-600' },
}

const StatusBadge = ({ status }) => {
  const m = STATUS_META[status] || { label: status, color: 'bg-gray-100 text-gray-500' }
  return <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>{m.label}</span>
}

const fmtDt = (dt) => dt ? new Date(dt).toLocaleDateString('ar-EG', {
  year: 'numeric', month: 'short', day: 'numeric',
}) : '—'

const STATUS_TABS = [
  { key: '',           label: 'الكل' },
  { key: 'pending',    label: 'بانتظار' },
  { key: 'invited',    label: 'مدعو' },
  { key: 'registered', label: 'مسجَّل' },
  { key: 'validated',  label: 'محقق' },
]


// ── Lead Row ──────────────────────────────────────────────────────────────────
function LeadRow({ lead, onInvite, onValidate, onShowEvents }) {
  return (
    <tr className="hover:bg-gray-50 text-sm" dir="rtl">
      <td className="px-3 py-2">
        <p className="font-medium text-gray-800">{lead.lead_name}</p>
        <p className="text-xs text-gray-400">{lead.lead_phone}</p>
      </td>
      <td className="px-3 py-2 text-gray-600 text-xs">
        {lead.referrer_name || '—'}
      </td>
      <td className="px-3 py-2">
        <StatusBadge status={lead.status} />
      </td>
      <td className="px-3 py-2 text-xs text-gray-500">
        {lead.fraud_score > 0 && (
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium
            ${lead.fraud_score >= 80 ? 'bg-red-100 text-red-700' :
              lead.fraud_score >= 40 ? 'bg-yellow-100 text-yellow-700' :
              'bg-gray-100 text-gray-600'}`}>
            {lead.fraud_score}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-gray-400 text-xs">{fmtDt(lead.created_at)}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          {lead.status === 'pending' && (
            <button
              onClick={() => onInvite(lead)}
              className="px-2 py-1 bg-green-50 text-green-700 hover:bg-green-100 rounded text-xs"
            >
              دعوة
            </button>
          )}
          {lead.status === 'registered' && (
            <button
              onClick={() => onValidate(lead)}
              className="px-2 py-1 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded text-xs"
            >
              تحقق
            </button>
          )}
          <button
            onClick={() => onShowEvents(lead)}
            className="px-2 py-1 bg-gray-50 text-gray-600 hover:bg-gray-100 rounded text-xs"
          >
            الأحداث
          </button>
        </div>
      </td>
    </tr>
  )
}


// ── Validate Modal ────────────────────────────────────────────────────────────
function ValidateModal({ lead, onClose }) {
  const [points, setPoints] = useState('100')
  const qc = useQueryClient()
  const mut = useMutation({
    mutationFn: () => referralApi.validate(lead.id, { points_reward: Number(points) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['referral-leads'] })
      onClose()
    },
  })

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-xl p-6 w-80 shadow-xl" onClick={e => e.stopPropagation()} dir="rtl">
        <h3 className="font-bold text-gray-800 mb-1">تحقق من الإحالة</h3>
        <p className="text-sm text-gray-500 mb-4">{lead.lead_name} — {lead.lead_phone}</p>
        <label className="block text-sm text-gray-600 mb-1">نقاط المكافأة للمُحيل</label>
        <input
          type="number"
          value={points}
          onChange={e => setPoints(e.target.value)}
          className="w-full border border-gray-200 rounded px-3 py-2 text-sm mb-4 focus:outline-none focus:border-blue-400"
        />
        <div className="flex gap-2">
          <button
            onClick={() => mut.mutate()}
            disabled={mut.isPending}
            className="flex-1 bg-blue-600 text-white rounded px-4 py-2 text-sm disabled:opacity-50"
          >
            {mut.isPending ? 'جاري...' : 'تأكيد التحقق'}
          </button>
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500">إلغاء</button>
        </div>
        {mut.isError && <p className="text-red-500 text-xs mt-2">فشلت العملية</p>}
      </div>
    </div>
  )
}


// ── Events Drawer ─────────────────────────────────────────────────────────────
function EventsDrawer({ lead, onClose }) {
  const { data } = useQuery({
    queryKey: ['referral-events', lead.id],
    queryFn: () => referralApi.leadEvents(lead.id).then(r => r.data),
  })
  const events = data?.results || data || []

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end sm:items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-t-2xl sm:rounded-xl w-full sm:w-96 p-5 shadow-xl max-h-96 overflow-y-auto"
           onClick={e => e.stopPropagation()} dir="rtl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-gray-800">أحداث الإحالة: {lead.lead_name}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">×</button>
        </div>
        <div className="space-y-2">
          {events.map(e => (
            <div key={e.id} className="flex gap-3 text-sm">
              <div className="w-2 h-2 bg-blue-400 rounded-full mt-1.5 shrink-0" />
              <div>
                <p className="font-medium text-gray-700">{e.event_type_display || e.event_type}</p>
                <p className="text-gray-500 text-xs">{e.message}</p>
                <p className="text-gray-400 text-xs">{fmtDt(e.created_at)}</p>
              </div>
            </div>
          ))}
          {events.length === 0 && <p className="text-center text-gray-400 py-4">لا توجد أحداث</p>}
        </div>
      </div>
    </div>
  )
}


// ── Lead Queue Tab ────────────────────────────────────────────────────────────
function LeadQueueTab() {
  const [tab, setTab] = useState('')
  const [inviteLead, setInviteLead] = useState(null)
  const [validateLead, setValidateLead] = useState(null)
  const [eventLead, setEventLead] = useState(null)
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['referral-leads', tab],
    queryFn: () => referralApi.leads({ status: tab || undefined }).then(r => r.data),
    refetchInterval: 30_000,
  })

  const inviteMut = useMutation({
    mutationFn: (lead) => referralApi.invite(lead.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['referral-leads'] })
      setInviteLead(null)
    },
  })

  const leads = data?.results || data || []

  return (
    <>
      {/* Status tabs */}
      <div className="flex gap-1 mb-4 overflow-x-auto" dir="rtl">
        {STATUS_TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-full text-sm whitespace-nowrap transition-colors
              ${tab === t.key
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-gray-500 text-xs uppercase">
              <th className="px-3 py-2 text-right">الإحالة</th>
              <th className="px-3 py-2 text-right">المُحيل</th>
              <th className="px-3 py-2 text-right">الحالة</th>
              <th className="px-3 py-2 text-right">الاحتيال</th>
              <th className="px-3 py-2 text-right">التاريخ</th>
              <th className="px-3 py-2 text-right">إجراءات</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading ? (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-gray-400">جاري التحميل...</td></tr>
            ) : leads.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-8 text-center text-gray-400">لا توجد إحالات</td></tr>
            ) : leads.map(l => (
              <LeadRow
                key={l.id}
                lead={l}
                onInvite={setInviteLead}
                onValidate={setValidateLead}
                onShowEvents={setEventLead}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* Invite confirm */}
      {inviteLead && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
          <div className="bg-white rounded-xl p-6 w-80 shadow-xl" dir="rtl">
            <h3 className="font-bold mb-2">إرسال دعوة واتساب</h3>
            <p className="text-sm text-gray-600 mb-4">
              هل تريد إرسال دعوة واتساب إلى <strong>{inviteLead.lead_name}</strong> ({inviteLead.lead_phone})؟
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => inviteMut.mutate(inviteLead)}
                disabled={inviteMut.isPending}
                className="flex-1 bg-green-600 text-white rounded px-4 py-2 text-sm disabled:opacity-50"
              >
                {inviteMut.isPending ? 'جاري...' : 'إرسال'}
              </button>
              <button onClick={() => setInviteLead(null)} className="px-4 py-2 text-sm text-gray-500">إلغاء</button>
            </div>
          </div>
        </div>
      )}

      {validateLead && (
        <ValidateModal lead={validateLead} onClose={() => setValidateLead(null)} />
      )}
      {eventLead && (
        <EventsDrawer lead={eventLead} onClose={() => setEventLead(null)} />
      )}
    </>
  )
}


// ── My Code Tab ───────────────────────────────────────────────────────────────
function MyCodeTab() {
  const { data, isLoading } = useQuery({
    queryKey: ['my-referral-code'],
    queryFn: () => referralApi.myCode().then(r => r.data),
  })

  if (isLoading) return <p className="text-center py-12 text-gray-400">جاري التحميل...</p>
  if (!data) return <p className="text-center py-12 text-gray-400">لا يوجد كود إحالة</p>

  return (
    <div className="max-w-md mx-auto text-center py-8" dir="rtl">
      <div className="bg-white rounded-2xl border border-gray-200 p-8 shadow-sm">
        {/* QR SVG */}
        {data.qr_code && (
          <div
            className="w-48 h-48 mx-auto mb-4"
            dangerouslySetInnerHTML={{ __html: data.qr_code }}
          />
        )}
        <p className="text-2xl font-mono font-bold text-gray-800 mb-2 tracking-widest">{data.code}</p>
        <p className="text-sm text-gray-500 mb-4">شارك هذا الكود مع أصدقائك</p>
        {data.referral_url && (
          <a
            href={data.referral_url}
            target="_blank"
            rel="noopener noreferrer"
            className="block text-xs text-blue-600 hover:underline break-all mb-4"
          >
            {data.referral_url}
          </a>
        )}
        <div className="grid grid-cols-3 gap-3 text-center text-sm border-t border-gray-100 pt-4">
          <div>
            <p className="font-bold text-gray-800 text-lg">{data.total_leads || 0}</p>
            <p className="text-gray-400 text-xs">إجمالي الإحالات</p>
          </div>
          <div>
            <p className="font-bold text-green-700 text-lg">{data.validated_leads || 0}</p>
            <p className="text-gray-400 text-xs">تحويلات ناجحة</p>
          </div>
          <div>
            <p className="font-bold text-blue-700 text-lg">{data.total_points_earned || 0}</p>
            <p className="text-gray-400 text-xs">نقاط مكتسبة</p>
          </div>
        </div>
      </div>
    </div>
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────
export default function ReferralPage() {
  const [tab, setTab] = useState('leads')

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-bold text-gray-800">نظام الإحالات</h1>
        <div className="flex gap-2">
          {[
            { key: 'leads', label: 'قائمة الإحالات' },
            { key: 'mycode', label: 'كودي' },
          ].map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors
                ${tab === t.key
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'leads' ? <LeadQueueTab /> : <MyCodeTab />}
    </div>
  )
}
