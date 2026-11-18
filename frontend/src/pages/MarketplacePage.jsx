/**
 * pages/MarketplacePage.jsx — «المنصات والتطبيقات» (/marketplace, doc 38 M1): delivery-app orders,
 * manual intake, the items approved per platform, platform + branch setup with the stock push, and
 * payout files.
 *
 * Every rule lives in apps/marketplace (flag MARKETPLACE_ENABLED, RBAC module `marketplace`,
 * eligibility, prices, status moves, matching). Nothing here or there writes to SOFTECH: accepting an
 * order creates a POS draft on the platform's SOFTECH account that the cashier completes. While
 * MARKETPLACE_PUSH_ENABLED is off nothing is sent to any platform (dry run, logged only).
 * The buttons shown follow the permission matrix; the server is the real guard.
 */
import { useState } from 'react'
import useHelpTab from '../help/useHelpTab'
import useAuthStore from '../store/authStore'
import { usePermissions } from '../hooks/usePermission'
import OrdersTab from './marketplace/OrdersTab'
import ManualIntakeTab from './marketplace/ManualIntakeTab'
import ListingsTab from './marketplace/ListingsTab'
import ChannelsTab from './marketplace/ChannelsTab'
import SettlementTab from './marketplace/SettlementTab'

const TABS = [
  { key: 'orders', label: '📦 الطلبات' },
  { key: 'manual', label: '✍️ إدخال طلب' },
  { key: 'listings', label: '🏷️ الأصناف المعروضة' },
  { key: 'channels', label: '🔌 المنصات والفروع' },
  { key: 'settlement', label: '💰 التسويات' },
]

export default function MarketplacePage() {
  const [tab, setTab] = useState('orders')
  useHelpTab(tab)
  const user = useAuthStore(s => s.user)
  const perms = usePermissions('marketplace')

  if (user && !user.can_marketplace) {
    return (
      <div className="p-6 max-w-3xl mx-auto text-center" dir="rtl">
        <div className="text-4xl mb-2">🔒</div>
        <p className="text-gray-600">هذه الشاشة غير مفعّلة أو ليست ضمن صلاحياتك.</p>
      </div>
    )
  }
  const canCreate = !!perms.create
  const canApprove = !!perms.approve
  const canEdit = !!perms.edit
  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" dir="rtl">
      <div className="mb-3">
        <h1 className="text-2xl font-bold text-gray-900">المنصات والتطبيقات</h1>
        <p className="text-sm text-gray-500 mt-1">
          طلبات تطبيقات التوصيل. القبول ينشئ مسودة في نقطة البيع على حساب المنصة والكاشير يكمّلها؛
          لا يُرسل شيء لأي منصة طالما مفتاح الإرسال مقفول، ولا يُعرض صنف بدون اعتماد مشرف.
        </p>
      </div>
      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-4" role="tablist" data-tour="marketplace-tabs">
        {TABS.map(t => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'orders' && <OrdersTab canCreate={canCreate} />}
      {tab === 'manual' && <ManualIntakeTab canCreate={canCreate} />}
      {tab === 'listings' && <ListingsTab canCreate={canCreate} canApprove={canApprove} />}
      {tab === 'channels' && <ChannelsTab canEdit={canEdit} />}
      {tab === 'settlement' && <SettlementTab canEdit={canEdit} />}
    </div>
  )
}
