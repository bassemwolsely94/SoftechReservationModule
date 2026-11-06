/**
 * SendCardDrawer — «إرسال إرشادات الاستخدام» (Project 4). An inline side drawer, not a modal:
 * staff tick the bought items that have a pharmacist-approved sheet, check the phone and send.
 * The server decides everything (approved versions only, opt-out, 7-day repeat, daily cap); the
 * idempotency key is made once per drawer open so a double tap sends once. While sending is
 * switched off the drawer is a preview only.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { counsellingApi } from '../api/client'
import { Icon } from '../pos/design'
import GuidanceBlock from './GuidanceBlock'
import useCounsellingStatus from './useCounsellingStatus'

const newKey = () => (globalThis.crypto?.randomUUID?.() || `k${Date.now()}${Math.random().toString(16).slice(2)}`)

export default function SendCardDrawer({ customerId, itemIds, branchId, source = 'pos', onClose }) {
  const { cards } = useCounsellingStatus()
  const [phoneIndex, setPhoneIndex] = useState(0)      // which of the customer's numbers on record
  const [resend, setResend] = useState(false)
  const [picked, setPicked] = useState(null)          // null = server's default (all with guidance)
  const [key] = useState(newKey)
  const ids = useMemo(() => [...new Set((itemIds || []).filter(Boolean))], [itemIds])

  const preview = useQuery({
    queryKey: ['counsel-card-preview', customerId || null, ids.join(','), phoneIndex],
    queryFn: () => counsellingApi.previewCard({ customer_id: customerId, item_ids: ids, phone_index: phoneIndex })
      .then(r => r.data),
    enabled: ids.length > 0,
    staleTime: 30_000,
  })
  const p = preview.data
  const chosen = picked ?? (p ? p.lines.filter(l => l.has_guidance).map(l => l.item_id) : [])
  const anyRecent = p?.lines.some(l => l.recently_sent && chosen.includes(l.item_id))

  const send = useMutation({
    mutationFn: () => counsellingApi.sendCard({
      customer_id: customerId, item_ids: chosen, branch_id: branchId, phone_index: phoneIndex, source,
      idempotency_key: key, resend,
    }).then(r => r.data),
  })
  const err = send.error?.response?.data
  const errText = err && (err.detail || Object.values(err).flat().join(' · '))

  const toggle = id => setPicked(prev => {
    const cur = prev ?? chosen
    return cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]
  })

  return (
    <div dir="rtl" className="fixed top-14 bottom-0 left-0 z-[65] w-[24rem] max-w-full bg-white border-e shadow-2xl flex flex-col"
         onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); onClose?.() } }} data-tour="counsel-send-drawer">
      <div className="flex items-center gap-2 p-3 border-b bg-gray-50">
        <Icon name="chat" size={16} className="text-gray-500" />
        <div className="font-semibold text-sm flex-1">إرسال إرشادات الاستخدام</div>
        <button type="button" onClick={onClose} autoFocus className="p-1.5 rounded hover:bg-gray-200" title="إغلاق (Esc)">
          <Icon name="x" size={16} />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3 text-sm">
        {!p && <div className="text-center text-gray-400 py-6">جارٍ التحضير…</div>}
        {p && (
          <>
            <label className="block">
              <span className="text-[11px] text-gray-500">رقم واتساب العميل (من بيانات العميل)</span>
              {p.phones?.length > 1 ? (
                <select value={phoneIndex} onChange={e => setPhoneIndex(Number(e.target.value))}
                        className="mt-0.5 w-full rounded-lg border border-gray-300 px-2 py-1.5" dir="ltr">
                  {p.phones.map(o => <option key={o.index} value={o.index}>{o.label}</option>)}
                </select>
              ) : (
                <div className="mt-0.5 rounded-lg border border-gray-200 bg-gray-50 px-2 py-1.5" dir="ltr">{p.phone || '—'}</div>
              )}
              {p.blocked_reason === 'no_customer' && <span className="text-xs text-red-600">اختر العميل أولاً — الإرشادات تُرسل لرقم مسجّل على العميل فقط</span>}
              {(p.blocked_reason === 'no_phone' || p.blocked_reason === 'bad_phone') && <span className="text-xs text-red-600">لا يوجد موبايل مصري مسجّل على العميل — أضفه في بيانات العميل أولاً</span>}
              {p.blocked_reason === 'not_on_record' && <span className="text-xs text-red-600">الرقم غير مسجّل على هذا العميل</span>}
              {p.blocked_reason === 'opted_out' && <span className="text-xs text-red-600">العميل أوقف رسائل الإرشادات</span>}
            </label>

            <div className="space-y-1">
              {p.lines.map(l => (
                <label key={l.item_id} className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 ${l.has_guidance ? 'bg-white' : 'bg-gray-50 text-gray-400'}`}>
                  <input type="checkbox" disabled={!l.has_guidance} checked={chosen.includes(l.item_id)}
                         onChange={() => toggle(l.item_id)} />
                  <span className="flex-1">{l.name}</span>
                  {!l.has_guidance && <span className="text-[11px]">لا يوجد إرشاد معتمد</span>}
                  {l.recently_sent && <span className="text-[11px] text-amber-700">أُرسل مؤخراً</span>}
                </label>
              ))}
            </div>
            {anyRecent && (
              <label className="flex items-center gap-2 text-xs text-amber-800">
                <input type="checkbox" checked={resend} onChange={e => setResend(e.target.checked)} /> إعادة الإرسال
              </label>
            )}

            <div className="rounded-lg bg-gray-50 border p-2 text-xs text-gray-700">
              <div className="text-[11px] text-gray-500 mb-1">نص الرسالة (لا يذكر اسم الدواء)</div>
              {p.message_preview}
            </div>
            {p.page_preview.filter(c => chosen.includes(c.item_id)).map(c => (
              <div key={c.item_id} className="rounded-lg border p-2">
                <div className="font-semibold text-xs mb-1">{c.name}</div>
                <GuidanceBlock content={c} compact />
              </div>
            ))}
          </>
        )}
      </div>

      <div className="p-3 border-t space-y-1.5">
        {send.data && (
          <div className={`text-sm ${send.data.status === 'sent' ? 'text-emerald-700' : 'text-red-700'}`}>
            {send.data.status_label}{send.data.fail_reason ? ` — ${send.data.fail_reason}` : ''}
          </div>
        )}
        {errText && <div className="text-sm text-red-700">{errText}</div>}
        <button type="button" data-tour="counsel-send-button"
                disabled={!cards || !p || !!p?.blocked_reason || !chosen.length || send.isPending || !!send.data || !branchId}
                onClick={() => send.mutate()}
                className="w-full rounded-lg bg-brand-600 text-white py-2 font-medium disabled:opacity-50">
          {!cards ? 'معاينة فقط — الإرسال غير مفعّل' : send.isPending ? 'جارٍ الإرسال…' : `إرسال (${chosen.length})`}
        </button>
      </div>
    </div>
  )
}
