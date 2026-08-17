/**
 * BranchPointsPage.jsx
 *
 * Read-only points balance lookup for branch staff.
 *
 * Use case: walk-in customer asks "كام عندي نقاط؟" at the counter.
 * Branch user searches by name/phone → card shows live SOFTECH balance.
 *
 * No adjustments — this page is display-only.
 * Adjustments are handled exclusively by call-center agents via LoyaltyPage.
 */
import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { loyaltyApi } from '../api/client'
import CustomerSearchWidget from '../components/CustomerSearchWidget'

const fmtDt = (dt) =>
  dt ? new Date(dt).toLocaleString('ar-EG', { dateStyle: 'short', timeStyle: 'short' }) : '—'

// ── Balance Card ──────────────────────────────────────────────────────────────
function BalanceCard({ customer }) {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['branch-softech-balance', customer.id],
    queryFn: () => loyaltyApi.softechBalance(customer.id).then(r => r.data),
    staleTime: 0,   // always re-fetch when a new customer is selected
  })

  const balance     = data?.softech_points_balance ?? 0
  const hasPic      = !!data?.softech_pic
  const warning     = data?.warning
  const loading     = isLoading || isFetching

  return (
    <div className="w-full max-w-md" dir="rtl">
      {/* Customer header */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        <div className="bg-gray-800 px-6 py-4 text-white flex items-center justify-between">
          <div>
            <p className="text-lg font-bold">{customer.name}</p>
            <p className="text-gray-300 text-sm">{customer.phone}</p>
          </div>
          {hasPic && (
            <span className="text-gray-400 font-mono text-xs bg-gray-700 px-2 py-1 rounded">
              {data.softech_pic}
            </span>
          )}
        </div>

        {/* Balance display */}
        <div className="px-6 py-8 text-center">
          {loading ? (
            <div className="py-4">
              <p className="text-gray-400 text-sm animate-pulse">جاري جلب الرصيد من SOFTECH...</p>
            </div>
          ) : warning ? (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4">
              <p className="text-yellow-700 text-sm">{warning}</p>
            </div>
          ) : (
            <>
              <p className="text-gray-400 text-sm mb-2">رصيد النقاط</p>
              <p className="text-6xl font-black text-green-600 mb-1">
                {balance.toLocaleString()}
              </p>
              <p className="text-gray-400">نقطة</p>
            </>
          )}
        </div>

        {/* Refresh */}
        {!warning && (
          <div className="border-t border-gray-100 px-6 py-3 flex items-center justify-between">
            <button
              onClick={() => refetch()}
              disabled={loading}
              className="text-sm text-green-600 hover:text-green-700 disabled:opacity-40 font-medium"
            >
              {loading ? 'جاري التحديث...' : '↻ تحديث من SOFTECH'}
            </button>
            {data && (
              <p className="text-xs text-gray-400">
                آخر تحديث: {fmtDt(new Date().toISOString())}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Messaging tip for the branch agent */}
      {!warning && !loading && (
        <div className="mt-3 bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 text-sm text-blue-700" dir="rtl">
          <p>
            <span className="font-semibold">للعميل:</span>{' '}
            رصيدك الحالي هو{' '}
            <span className="font-bold text-green-700">{balance.toLocaleString()}</span>{' '}
            نقطة. للاستفادة بالنقاط، يرجى التواصل مع خدمة العملاء.
          </p>
        </div>
      )}
    </div>
  )
}


// ── Main Page ─────────────────────────────────────────────────────────────────
export default function BranchPointsPage() {
  const [customer, setCustomer] = useState(null)

  return (
    <div className="min-h-full bg-gray-50 flex flex-col items-center px-4 py-12" dir="rtl">
      <div className="w-full max-w-md mb-8 text-center">
        <h1 className="text-2xl font-bold text-gray-800 mb-1">استعلام عن نقاط العميل</h1>
        <p className="text-gray-500 text-sm">للعملاء الزائرين للفرع</p>
      </div>

      <CustomerSearchWidget
        selected={customer}
        onSelect={c => setCustomer(c)}
        onClear={() => setCustomer(null)}
        placeholder="ابحث باسم العميل أو رقم الهاتف أو كود PIC..."
        className="w-full max-w-md"
      />

      {customer && (
        <div className="mt-6 w-full flex flex-col items-center">
          <BalanceCard customer={customer} />
          <button
            onClick={() => setCustomer(null)}
            className="mt-4 text-sm text-gray-400 hover:text-gray-600"
          >
            ← بحث عن عميل آخر
          </button>
        </div>
      )}

      {!customer && (
        <div className="mt-16 text-center text-gray-300">
          <p className="text-6xl mb-3">🏆</p>
          <p className="text-sm">ابدأ بالبحث عن العميل</p>
        </div>
      )}
    </div>
  )
}
