/**
 * TaxInvoicingPage — الفواتير الضريبية (doc 36). Route /tax-invoicing.
 *
 * ETA e-invoices for finalized insurance claims and e-receipts for branch sales. The server decides
 * everything (classification, blockers, totals, who may do what); this page shows the result and
 * sends the user's choices. No modals: actions and forms open in place.
 *
 * The tab, and the document or item it points at, live in the URL, so a link from the claim screen
 * or another tab opens the right place: ?tab=documents&doc=12 · ?tab=items&q=1234 · ?tab=receipts&status=held
 */
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { taxInvoicingApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import ClaimsTab from './taxinvoicing/ClaimsTab'
import DocumentsTab from './taxinvoicing/DocumentsTab'
import ExceptionsTab from './taxinvoicing/ExceptionsTab'
import ImportTab from './taxinvoicing/ImportTab'
import ItemsTab from './taxinvoicing/ItemsTab'
import PrintTab from './taxinvoicing/PrintTab'
import ReceiptsTab from './taxinvoicing/ReceiptsTab'
import SettingsTab from './taxinvoicing/SettingsTab'
import { Failed, Loading } from './taxinvoicing/ui'

const TABS = [
  { key: 'claims',     label: '🏥 المطالبات' },
  { key: 'documents',  label: '📄 المستندات' },
  { key: 'print',      label: '🖨️ الفاتورة المطبوعة' },
  { key: 'exceptions', label: '⚠️ الاستثناءات' },
  { key: 'items',      label: '🏷️ الأصناف' },
  { key: 'import',     label: '📥 استيراد الأصناف' },
  { key: 'receipts',   label: '🧾 الإيصالات' },
  { key: 'settings',   label: '⚙️ الإعدادات' },
]

export default function TaxInvoicingPage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(t => t.key === params.get('tab')) ? params.get('tab') : 'claims'
  useHelpTab(tab)
  const me = useQuery({ queryKey: ['tax-invoicing', 'me'], queryFn: () => taxInvoicingApi.me().then(r => r.data), retry: false })

  // Going somewhere replaces the query string: each link names everything it needs.
  const go = (nextTab, extra = {}) => {
    const next = { tab: nextTab }
    Object.entries(extra).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') next[k] = String(v) })
    setParams(next)
  }

  if (me.isLoading) return <div className="p-6" dir="rtl"><Loading /></div>
  if (me.error?.response?.status === 403) {
    return (
      <div className="p-6 max-w-3xl mx-auto text-center" dir="rtl">
        <div className="text-4xl mb-2">🔒</div>
        <p className="text-gray-600">هذه الشاشة لمن يملك صلاحية الفواتير الضريبية.</p>
      </div>
    )
  }
  if (me.error) return <div className="p-6" dir="rtl"><Failed error={me.error} /></div>
  const access = me.data

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" dir="rtl">
      <div className="mb-3 no-print">
        <h1 className="text-2xl font-bold text-gray-900">الفواتير الضريبية</h1>
        <p className="text-sm text-gray-500 mt-1">
          فواتير مصلحة الضرائب للمطالبات المقفلة، وإيصالات مبيعات الفروع. البند المحجوز يوقف المستند كله.
        </p>
      </div>
      {!access.submit_enabled && (
        <div className="mb-3 text-xs text-gray-600 bg-white border border-gray-200 rounded-lg px-3 py-2 no-print" data-tour="tax-invoicing-main-sending-off">
          🔕 الإرسال الفعلي للمصلحة مغلق. كل ما هنا مراجعة ومعاينة، ولا يخرج شيء للمصلحة.
        </div>
      )}
      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-4 no-print" data-tour="tax-invoicing-main-tabs">
        {TABS.map(t => (
          <button key={t.key} type="button" onClick={() => go(t.key)}
            className={`px-3 py-2 rounded-md text-sm font-medium transition ${tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'claims' && <ClaimsTab me={access} go={go} />}
      {tab === 'documents' && <DocumentsTab me={access} docId={params.get('doc')} go={go} />}
      {tab === 'print' && <PrintTab docId={params.get('doc')} go={go} />}
      {tab === 'exceptions' && <ExceptionsTab go={go} />}
      {tab === 'items' && <ItemsTab key={`${params.get('q') || ''}|${params.get('new') || ''}`} me={access} initialQ={params.get('q') || ''} newCode={params.get('new') || ''} go={go} />}
      {tab === 'import' && <ImportTab me={access} />}
      {tab === 'receipts' && <ReceiptsTab key={params.get('status') || ''} me={access} initialStatus={params.get('status') || ''} />}
      {tab === 'settings' && <SettingsTab me={access} />}
    </div>
  )
}
