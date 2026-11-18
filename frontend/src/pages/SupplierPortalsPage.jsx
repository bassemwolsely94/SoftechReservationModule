/**
 * SupplierPortalsPage.jsx — مواقع الموردين (supplier-portal robot, /rpa/portals)
 *
 * Buy lists → a supplier per line → robot jobs on the supplier's site (Pharma Overseas) → baskets.
 * The robot runs on the buyer's PC, fills the cart and stops at the review page: the person reviews
 * and presses Submit. Tabs:
 *   buylists قوائم الشراء · discovery الأكواد · baskets السلال · remainders الباقي · accounts الحسابات (admin)
 * The page makes no decisions: every button calls the API; the server owns the rules.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { rpaPortalApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useHelpTab from '../help/useHelpTab'
import BuyListTab from './rpa/portals/BuyListTab'
import DiscoveryTab from './rpa/portals/DiscoveryTab'
import BasketsTab from './rpa/portals/BasketsTab'
import RemaindersTab from './rpa/portals/RemaindersTab'
import AccountsTab from './rpa/portals/AccountsTab'
import { ModeBadge } from './rpa/portals/shared.jsx'

const TABS = [
  { key: 'buylists', label: 'قوائم الشراء' },
  { key: 'discovery', label: 'الأكواد' },
  { key: 'baskets', label: 'السلال' },
  { key: 'remainders', label: 'الباقي' },
  { key: 'accounts', label: 'الحسابات', adminOnly: true },
]

function StatusStrip() {
  const q = useQuery({ queryKey: ['rpa-portal', 'portals'], queryFn: () => rpaPortalApi.portals().then(r => r.data),
                       refetchInterval: 60000 })
  const s = q.data
  return (
    <div data-tour="rpa-portals-status" className="card p-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
      {q.isLoading && <span className="text-muted">جارٍ التحميل…</span>}
      {q.isError && <span className="text-red-600">تعذّر قراءة حالة الروبوت.</span>}
      {s && (s.switch_on
        ? <span className="text-green-700 dark:text-green-300 font-semibold">الروبوت شغّال</span>
        : <span className="text-red-700 dark:text-red-300 font-semibold">الروبوت متوقف من الإعدادات</span>)}
      {(s?.portals || []).map(p => (
        <span key={p.key} className="flex items-center gap-1.5">
          <span className="font-medium">{p.title}</span>
          {p.enabled ? <ModeBadge dryRun={!p.live} /> : <span className="text-xs text-muted">غير مفعّل</span>}
        </span>
      ))}
      <span className="text-muted text-xs">الروبوت لا يضغط Submit أبداً — راجع ثم اضغطه بنفسك.</span>
    </div>
  )
}

export default function SupplierPortalsPage() {
  const isAdmin = useAuthStore(s => s.user?.role) === 'admin'
  const tabs = TABS.filter(t => !t.adminOnly || isAdmin)
  const [tab, setTab] = useState('buylists')
  useHelpTab(tab)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">🛒 مواقع الموردين</h1>
        <p className="text-sm text-muted">
          قائمة الشراء تُقسَّم على الموردين؛ الروبوت يملأ سلة موقع المورد على جهازك، وأنت تراجع وتضغط Submit بنفسك.
        </p>
      </div>

      <StatusStrip />

      <div data-tour="rpa-portals-tabs" className="flex flex-wrap gap-1 border-b border-line">
        {tabs.map(t => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)}
                  className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === t.key ? 'border-brand-600 text-brand-600 font-semibold' : 'border-transparent text-muted'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'buylists' && <BuyListTab />}
      {tab === 'discovery' && <DiscoveryTab />}
      {tab === 'baskets' && <BasketsTab />}
      {tab === 'remainders' && <RemaindersTab />}
      {tab === 'accounts' && isAdmin && <AccountsTab />}
    </div>
  )
}
