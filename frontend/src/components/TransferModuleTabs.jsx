/**
 * TransferModuleTabs.jsx
 *
 * Shared top-of-page switcher between the two phases of the inter-branch
 * transfer pipeline, which live on SEPARATE pages but stay visually linked:
 *
 *   🔀 طلبات التحويل   /transfers   — the internal request/approval workflow
 *   🚛 قيد النقل        /transits    — the SOFTECH-issued shipments in transit
 *
 * Rendered at the top of both pages; `active` marks the current one.
 */
import { useNavigate } from 'react-router-dom'

const TABS = [
  { key: 'requests', to: '/transfers', icon: '🔀', label: 'طلبات التحويل' },
  { key: 'transit',  to: '/transits',  icon: '🚛', label: 'قيد النقل' },
]

export default function TransferModuleTabs({ active }) {
  const navigate = useNavigate()
  return (
    <div className="flex items-center gap-0 border-b border-gray-100 px-6">
      {TABS.map(t => (
        <button
          key={t.key}
          onClick={() => { if (t.key !== active) navigate(t.to) }}
          className={`flex items-center gap-1.5 px-4 py-3 text-sm font-bold border-b-2 transition-colors ${
            active === t.key
              ? 'border-brand-600 text-brand-700'
              : 'border-transparent text-gray-400 hover:text-gray-700'
          }`}
        >
          <span>{t.icon}</span>
          <span>{t.label}</span>
        </button>
      ))}
    </div>
  )
}
