/**
 * MobileCustomersPage.jsx — customer lookup + loyalty + reward redemption
 * (route: /m/customers).
 *
 * Counter flow: scan the customer's QR (BarcodeDetector) OR search by
 * name/phone/PIC → profile, loyalty points (CRM + live SOFTECH balance), recent
 * reservations, and one-tap reward redemption. Reuses customers/loyalty APIs.
 */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { customersApi, loyaltyApi } from '../../api/client'
import CustomerSearchWidget from '../../components/CustomerSearchWidget'
import QrScanner from '../../components/QrScanner'
import { StatusBadge } from '../../components/StatusBadge'
import { MobileLoading } from '../../components/mobileUi'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}

export default function MobileCustomersPage() {
  const qc = useQueryClient()
  const [cust, setCust]       = useState(null)
  const [scanning, setScan]   = useState(false)
  const [msg, setMsg]         = useState('')
  const [redeeming, setRedeeming] = useState(null)
  const id = cust?.id

  const loyalty = useQuery({
    queryKey: ['m-cust-loyalty', id],
    queryFn: () => loyaltyApi.account(id).then(r => r.data).catch(() => null),
    enabled: !!id, retry: false,
  })
  const softech = useQuery({
    queryKey: ['m-cust-softech', id],
    queryFn: () => loyaltyApi.softechBalance(id).then(r => r.data).catch(() => null),
    enabled: !!id, retry: false,
  })
  const rewards = useQuery({
    queryKey: ['m-loyalty-rewards'],
    queryFn: () => loyaltyApi.rewards().then(r => r.data?.results || r.data).catch(() => []),
    enabled: !!id,
  })
  const resv = useQuery({
    queryKey: ['m-cust-resv', id],
    queryFn: () => customersApi.reservations(id).then(r => r.data),
    enabled: !!id,
  })

  const acct        = loyalty.data
  const crmPoints   = acct?.points_balance ?? 0
  const softPoints  = softech.data?.softech_points_balance ?? acct?.softech_points_balance ?? 0
  const tier        = acct?.tier
  const reservations = Array.isArray(resv.data) ? resv.data : (resv.data?.results || [])
  const rewardList   = (Array.isArray(rewards.data) ? rewards.data : []).filter(r => r.is_available)

  async function resolveCode(code) {
    setScan(false); setMsg('')
    let q = String(code || '').trim()
    const m = q.match(/pic=([^&\s/]+)/i)
    if (m) q = m[1]
    else if (q.includes('/')) q = q.split('/').filter(Boolean).pop()
    try {
      const r = await customersApi.list({ search: q, page_size: 1 })
      const rows = r.data?.results || r.data
      if (rows && rows.length) setCust(rows[0])
      else setMsg('لم يُعثر على عميل بهذا الرمز')
    } catch { setMsg('تعذّر البحث عن العميل') }
  }

  async function redeem(reward) {
    setRedeeming(reward.id); setMsg('')
    try {
      await loyaltyApi.redeem(id, { reward_id: reward.id })
      setMsg(`تم إنشاء طلب استبدال «${reward.name_ar || reward.name}» (بانتظار الاعتماد)`)
      qc.invalidateQueries({ queryKey: ['m-cust-loyalty', id] })
    } catch (e) {
      setMsg(e.response?.data?.detail || 'تعذّر الاستبدال')
    } finally { setRedeeming(null) }
  }

  return (
    <div className="p-3 space-y-3">
      {scanning && <QrScanner onScan={resolveCode} onClose={() => setScan(false)} />}

      <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-2.5">
        <h2 className="font-semibold text-gray-700 text-sm">👥 بحث عن عميل</h2>
        <CustomerSearchWidget selected={cust} onSelect={setCust} allowManual={false} />
        {!cust && (
          <button onClick={() => setScan(true)}
            className="w-full text-center text-sm bg-brand-50 text-brand-700 border border-brand-200 rounded-xl py-2.5 font-medium">
            📷 مسح رمز العميل (QR)
          </button>
        )}
      </div>

      {msg && <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-2xl px-4 py-3">{msg}</div>}

      {cust && cust.id && (
        <>
          {/* Loyalty */}
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold text-gray-700 text-sm">🏆 الولاء</h2>
              {tier?.name_ar && (
                <span className="text-xs px-2 py-1 rounded-lg border" style={{ borderColor: tier.color || '#ddd', color: tier.color || '#666' }}>
                  {tier.icon ? `${tier.icon} ` : ''}{tier.name_ar}
                </span>
              )}
            </div>
            {loyalty.isLoading ? (
              <div className="text-xs text-gray-400">جارٍ التحميل...</div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <div className="text-center bg-gray-50 rounded-xl py-3">
                  <div className="text-xl font-bold text-brand-700">{toLatin(softPoints)}</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">نقاط الشراء (SOFTECH)</div>
                </div>
                <div className="text-center bg-gray-50 rounded-xl py-3">
                  <div className="text-xl font-bold text-gray-700">{toLatin(crmPoints)}</div>
                  <div className="text-[11px] text-gray-400 mt-0.5">نقاط الإحالة</div>
                </div>
              </div>
            )}
          </div>

          {/* Rewards / redeem */}
          {rewardList.length > 0 && (
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <h2 className="font-semibold text-gray-700 text-sm mb-2.5">🎁 استبدال النقاط</h2>
              <div className="space-y-2">
                {rewardList.map(rw => {
                  const afford = crmPoints >= rw.points_cost
                  return (
                    <div key={rw.id} className="flex items-center justify-between gap-2 border-b border-gray-50 last:border-0 pb-2 last:pb-0">
                      <div className="min-w-0">
                        <div className="text-sm text-gray-800 truncate">{rw.name_ar || rw.name}</div>
                        <div className="text-[11px] text-gray-400">{toLatin(rw.points_cost)} نقطة</div>
                      </div>
                      <button
                        onClick={() => redeem(rw)}
                        disabled={!afford || redeeming === rw.id}
                        className="shrink-0 text-xs font-medium rounded-lg px-3 py-1.5 disabled:opacity-40 bg-brand-600 text-white"
                      >
                        {redeeming === rw.id ? '...' : afford ? 'استبدال' : 'رصيد غير كافٍ'}
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Recent reservations */}
          <div className="bg-white rounded-2xl border border-gray-200 p-4">
            <h2 className="font-semibold text-gray-700 text-sm mb-2.5">📋 آخر الحجوزات</h2>
            {resv.isLoading ? (
              <MobileLoading />
            ) : reservations.length === 0 ? (
              <div className="text-xs text-gray-400 py-2">لا توجد حجوزات سابقة</div>
            ) : (
              <div className="space-y-2">
                {reservations.slice(0, 10).map(r => (
                  <div key={r.id} className="flex items-center justify-between gap-2 text-sm border-b border-gray-50 last:border-0 pb-2 last:pb-0">
                    <span className="text-gray-700 break-words flex-1 min-w-0">{r.item_name || r.manual_item_name || '—'}</span>
                    {r.status && <StatusBadge status={r.status} />}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
