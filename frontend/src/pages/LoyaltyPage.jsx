/**
 * LoyaltyPage.jsx
 *
 * Customer Loyalty Engine management page.
 *
 * Two-column layout:
 *   Left  — customer search + account summary card + transaction ledger
 *   Right — reward catalog + pending redemptions
 *
 * Staff actions:
 *   - Adjust points (manual credit / debit with reason)
 *   - Approve pending redemption requests
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { loyaltyApi } from '../api/client'
import CustomerSearchWidget from '../components/CustomerSearchWidget'

// ── helpers ───────────────────────────────────────────────────────────────────
const TIER_COLOR = {
  bronze: 'bg-amber-100 text-amber-800',
  silver: 'bg-gray-100 text-gray-700',
  gold:   'bg-yellow-100 text-yellow-800',
  vip:    'bg-purple-100 text-purple-800',
}

const TX_COLOR = {
  earn:    'text-green-600',
  redeem:  'text-red-600',
  adjust:  'text-blue-600',
  expire:  'text-gray-500',
}

const fmtDt = (dt) => dt ? new Date(dt).toLocaleDateString('ar-EG', {
  year: 'numeric', month: 'short', day: 'numeric',
}) : '—'



// ── Account Card ──────────────────────────────────────────────────────────────
function AccountCard({ customerId, onAdjust }) {
  const { data, isLoading } = useQuery({
    queryKey: ['loyalty-account', customerId],
    queryFn: () => loyaltyApi.account(customerId).then(r => r.data),
  })

  if (isLoading) return <div className="bg-gray-50 rounded-xl p-6 text-center text-gray-400 text-sm">جاري التحميل...</div>
  if (!data) return null

  const tierClass = TIER_COLOR[data.tier?.name] || 'bg-gray-100 text-gray-700'
  const hasPic    = !!data.softech_pic

  return (
    <div className="rounded-xl overflow-hidden shadow-sm" dir="rtl">
      {/* SOFTECH balance — primary / authoritative */}
      <div className="bg-gradient-to-br from-green-600 to-green-800 p-5 text-white">
        <div className="flex items-start justify-between mb-3">
          <div>
            <p className="text-green-200 text-xs mb-0.5">رصيد SOFTECH (الأساسي)</p>
            <p className="text-4xl font-bold">{(data.softech_points_balance || 0).toLocaleString()}</p>
            <p className="text-green-200 text-xs mt-1">نقطة</p>
          </div>
          <div className="text-right">
            <span className={`px-2 py-1 rounded-full text-xs font-bold ${tierClass}`}>
              {data.tier?.icon || ''} {data.tier?.name_ar || 'برونزي'}
            </span>
            {!hasPic && (
              <p className="text-yellow-300 text-xs mt-1">⚠ لا يوجد PIC</p>
            )}
          </div>
        </div>
        {hasPic && (
          <p className="text-green-300 text-xs font-mono">{data.softech_pic}</p>
        )}
      </div>

      {/* Supplemental Django points (referrals / campaigns) */}
      {data.points_balance > 0 && (
        <div className="bg-blue-600 px-5 py-3 text-white flex items-center justify-between text-sm">
          <span className="text-blue-200">نقاط إضافية (إحالات / حملات)</span>
          <span className="font-bold">+{data.points_balance.toLocaleString()}</span>
        </div>
      )}

      {/* Actions */}
      <div className="bg-gray-50 px-5 py-3 flex gap-2">
        <button
          onClick={onAdjust}
          disabled={!hasPic}
          className="flex-1 bg-green-600 text-white rounded-lg px-3 py-2 text-sm font-medium
                     disabled:opacity-40 disabled:cursor-not-allowed hover:bg-green-700 transition-colors"
          title={!hasPic ? 'العميل لا يملك PIC' : ''}
        >
          تعديل نقاط SOFTECH
        </button>
      </div>
    </div>
  )
}


// ── Transaction Ledger ────────────────────────────────────────────────────────
function TransactionLedger({ customerId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['loyalty-transactions', customerId],
    queryFn: () => loyaltyApi.transactions(customerId).then(r => r.data),
  })
  const txs = data?.results || data || []

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" dir="rtl">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="font-semibold text-gray-800 text-sm">سجل المعاملات</h3>
      </div>
      <div className="divide-y divide-gray-50 max-h-72 overflow-y-auto">
        {isLoading ? (
          <p className="text-center py-6 text-gray-400 text-sm">جاري التحميل...</p>
        ) : txs.length === 0 ? (
          <p className="text-center py-6 text-gray-400 text-sm">لا توجد معاملات</p>
        ) : txs.map(tx => (
          <div key={tx.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <div className="min-w-0 flex-1">
              <p className="text-gray-700 truncate">{tx.reason}</p>
              <p className="text-xs text-gray-400">{fmtDt(tx.created_at)} · {tx.source_type}</p>
            </div>
            <div className="text-right shrink-0 mr-3">
              <p className={`font-bold ${TX_COLOR[tx.transaction_type] || 'text-gray-700'}`}>
                {tx.points > 0 ? '+' : ''}{tx.points?.toLocaleString()}
              </p>
              <p className="text-xs text-gray-400">{tx.balance_after?.toLocaleString()}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}


// ── Adjust Points Modal (SOFTECH procedure) ───────────────────────────────────
function AdjustModal({ customerId, onClose }) {
  const [points, setPoints] = useState('')
  const [reason, setReason] = useState('')
  const qc = useQueryClient()

  const mut = useMutation({
    mutationFn: () => loyaltyApi.adjust(customerId, { points: Number(points), reason }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['loyalty-account', customerId] })
      qc.invalidateQueries({ queryKey: ['softech-log', customerId] })
      onClose()
    },
  })

  const delta = Number(points) || 0

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="bg-white rounded-xl p-6 w-96 shadow-xl" onClick={e => e.stopPropagation()} dir="rtl">
        <h3 className="font-bold text-gray-800 mb-1">تعديل نقاط SOFTECH</h3>
        <p className="text-xs text-gray-400 mb-4">
          سيتم تنفيذ التعديل عبر إجراء SOFTECH مباشرة — يؤثر على رصيد جميع الفروع.
        </p>

        <label className="block text-sm text-gray-600 mb-1">النقاط (موجب = إضافة، سالب = خصم)</label>
        <input
          type="number"
          value={points}
          onChange={e => setPoints(e.target.value)}
          placeholder="مثال: 100 أو -50"
          className="w-full border border-gray-200 rounded px-3 py-2 text-sm mb-3 focus:outline-none focus:border-green-400"
        />

        <label className="block text-sm text-gray-600 mb-1">السبب (إلزامي)</label>
        <input
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder="سبب التعديل..."
          className="w-full border border-gray-200 rounded px-3 py-2 text-sm mb-4 focus:outline-none focus:border-green-400"
        />

        {delta !== 0 && (
          <div className={`mb-4 rounded-lg px-3 py-2 text-sm font-medium
            ${delta > 0 ? 'bg-green-50 text-green-700 border border-green-200'
                        : 'bg-red-50 text-red-700 border border-red-200'}`}>
            {delta > 0 ? `إضافة ${delta.toLocaleString()} نقطة` : `خصم ${Math.abs(delta).toLocaleString()} نقطة`}
          </div>
        )}

        <div className="flex gap-2">
          <button
            onClick={() => mut.mutate()}
            disabled={!points || delta === 0 || !reason.trim() || mut.isPending}
            className="flex-1 bg-green-600 text-white rounded px-4 py-2 text-sm disabled:opacity-50 hover:bg-green-700"
          >
            {mut.isPending ? 'جاري التنفيذ...' : 'تنفيذ في SOFTECH'}
          </button>
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500">إلغاء</button>
        </div>
        {mut.isError && (
          <p className="text-red-500 text-xs mt-2">
            {mut.error?.response?.data?.detail || 'فشل التعديل — تحقق من الاتصال بـ SOFTECH'}
          </p>
        )}
      </div>
    </div>
  )
}


// ── SOFTECH Adjustment Log ────────────────────────────────────────────────────
function SoftechLog({ customerId }) {
  const { data, isLoading } = useQuery({
    queryKey: ['softech-log', customerId],
    queryFn: () => loyaltyApi.softechLog(customerId).then(r => r.data),
  })
  const logs = data?.results || data || []

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" dir="rtl">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="font-semibold text-gray-800 text-sm">سجل تعديلات SOFTECH</h3>
      </div>
      <div className="divide-y divide-gray-50 max-h-72 overflow-y-auto">
        {isLoading ? (
          <p className="text-center py-6 text-gray-400 text-sm">جاري التحميل...</p>
        ) : logs.length === 0 ? (
          <p className="text-center py-6 text-gray-400 text-sm">لا توجد تعديلات</p>
        ) : logs.map(log => (
          <div key={log.id} className="flex items-center justify-between px-4 py-2.5 text-sm">
            <div className="min-w-0 flex-1">
              <p className="text-gray-700 truncate">{log.reason || '—'}</p>
              <p className="text-xs text-gray-400">
                {log.created_by_name || 'النظام'} · {fmtDt(log.created_at)}
              </p>
            </div>
            <div className="text-right shrink-0 mr-3">
              <p className={`font-bold ${log.delta > 0 ? 'text-green-600' : 'text-red-600'}`}>
                {log.delta > 0 ? '+' : ''}{log.delta?.toLocaleString()}
              </p>
              <p className="text-xs text-gray-400">→ {log.balance_after?.toLocaleString()}</p>
              {!log.success && <p className="text-xs text-red-500">✗ فشل</p>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}


// ── Reward Catalog ────────────────────────────────────────────────────────────
function RewardCatalog() {
  const { data } = useQuery({
    queryKey: ['loyalty-rewards'],
    queryFn: () => loyaltyApi.rewards().then(r => r.data),
  })
  const rewards = data?.results || data || []

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" dir="rtl">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="font-semibold text-gray-800 text-sm">كتالوج المكافآت</h3>
      </div>
      <div className="divide-y divide-gray-50">
        {rewards.map(r => (
          <div key={r.id} className="flex items-center justify-between px-4 py-3 text-sm">
            <div>
              <p className="font-medium text-gray-800">{r.name_ar || r.name}</p>
              <p className="text-xs text-gray-400">{r.description}</p>
            </div>
            <span className="text-blue-700 font-bold text-xs bg-blue-50 px-2 py-1 rounded-full">
              {r.points_cost?.toLocaleString()} نقطة
            </span>
          </div>
        ))}
        {rewards.length === 0 && (
          <p className="text-center py-6 text-gray-400 text-sm">لا توجد مكافآت متاحة</p>
        )}
      </div>
    </div>
  )
}


// ── Pending Redemptions ───────────────────────────────────────────────────────
function PendingRedemptions() {
  const qc = useQueryClient()

  // We can't load all pending redemptions without a global endpoint — show tiers instead
  const { data } = useQuery({
    queryKey: ['loyalty-tiers'],
    queryFn: () => loyaltyApi.tiers().then(r => r.data),
  })
  const tiers = data?.results || data || []

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden" dir="rtl">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="font-semibold text-gray-800 text-sm">درجات الولاء</h3>
      </div>
      <div className="divide-y divide-gray-50">
        {tiers.map(t => (
          <div key={t.id} className="flex items-center justify-between px-4 py-3 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-lg">{t.icon}</span>
              <div>
                <p className="font-medium text-gray-800">{t.name_ar}</p>
                <p className="text-xs text-gray-400">{t.min_points?.toLocaleString()} نقطة فأكثر</p>
              </div>
            </div>
            <span className="text-xs text-gray-500">{t.earn_multiplier}×</span>
          </div>
        ))}
      </div>
    </div>
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────
export default function LoyaltyPage() {
  const [customer, setCustomer] = useState(null)
  const [showAdjust, setShowAdjust] = useState(false)

  return (
    <div className="p-6 max-w-6xl mx-auto" dir="rtl">
      <h1 className="text-xl font-bold text-gray-800 mb-6">نظام النقاط والولاء</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left column */}
        <div className="space-y-4">
          <CustomerSearchWidget
            selected={customer}
            onSelect={setCustomer}
            onClear={() => setCustomer(null)}
            placeholder="ابحث عن عميل باسم أو رقم هاتف أو كود PIC..."
          />
          {customer ? (
            <>
              <div className="flex items-center gap-2 text-sm text-gray-600 bg-gray-50 rounded-lg px-3 py-2">
                <span className="font-medium text-gray-800">{customer.name}</span>
                <span className="text-gray-400">{customer.phone}</span>
                <button onClick={() => setCustomer(null)} className="mr-auto text-gray-400 hover:text-red-500">×</button>
              </div>
              <AccountCard customerId={customer.id} onAdjust={() => setShowAdjust(true)} />
              <TransactionLedger customerId={customer.id} />
              <SoftechLog customerId={customer.id} />
            </>
          ) : (
            <div className="bg-gray-50 rounded-xl p-12 text-center text-gray-400">
              <p className="text-3xl mb-2">🏆</p>
              <p className="text-sm">ابحث عن عميل لعرض حسابه</p>
            </div>
          )}
        </div>

        {/* Right column */}
        <div className="space-y-4">
          <RewardCatalog />
          <PendingRedemptions />
        </div>
      </div>

      {showAdjust && customer && (
        <AdjustModal customerId={customer.id} onClose={() => setShowAdjust(false)} />
      )}
    </div>
  )
}
