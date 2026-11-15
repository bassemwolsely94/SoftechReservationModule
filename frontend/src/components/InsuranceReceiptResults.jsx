/**
 * «بحث برقم الروشتة / باسم المريض» results on مطالبات التأمين: one block per receipt (number · branch · date ·
 * patient · net), one line per claim it sits in — active or excluded, and how it came in — plus
 * the SOFTECH motalba it belongs to (cache, ~90 days). Read-only; «فتح ↗» opens the claim
 * filtered to that receipt. Receipt numbers repeat across branches, so the branch always shows.
 */
import { useNavigate } from 'react-router-dom'
import useBranchLabels from '../hooks/useBranchLabels'

const ORIGIN = {
  import: (a) => a.softech_motalba_no ? `مستوردة مع مطالبة سوفتك ${a.softech_motalba_no}` : 'مستوردة مع المطالبة',
  manual: (a) => `إضافة يدوية${a.origin_by ? ` — ${a.origin_by}` : ''}${a.origin_reason ? ` «${a.origin_reason}»` : ''}`,
  resync: () => 'أُضيفت بمزامنة سوفتك',
}

const fmtNet = (v) => v == null ? '' : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export default function InsuranceReceiptResults({ loading, error, query, results, more = false, mode = 'receipt' }) {
  const navigate = useNavigate()
  const BL = useBranchLabels()

  const byName = mode === 'patient'
  if (loading) return <div className="mx-6 mb-3 text-sm text-gray-400">جارٍ البحث عن {byName ? 'روشتات المريض' : 'الروشتة'} {query}…</div>
  if (error) return <div className="mx-6 mb-3 text-sm text-red-600">{error}</div>
  if (!results) return null
  if (!results.length) {
    return <div className="mx-6 mb-3 px-4 py-3 rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-500">
      {byName
        ? <>لا توجد روشتة لمريض باسم «{query}» في أي مطالبة.</>
        : <>لا توجد روشتة بالرقم {query} في أي مطالبة ولا في كاش مطالبات سوفتك (آخر 90 يوماً).</>}
    </div>
  }

  const open = (r, a) => navigate(`/insurance/claims/${a.claim_id}?rx=${encodeURIComponent(r.docnumber)}`)

  return (
    <div className="mx-6 mb-3 space-y-2" data-tour="insurance-claims-receipt-results">
      {byName && (
        <div className="text-xs text-gray-500">
          {results.length} روشتة باسم «{query}» — الأحدث أولاً{more ? '. توجد نتائج أكثر: اكتب الاسم كاملاً لتضييق البحث.' : '.'}
        </div>
      )}
      {results.map(r => (
        <div key={`${r.docnumber}-${r.branch}`} className="rounded-lg border border-blue-200 bg-white">
          <div className="px-4 py-2 border-b border-blue-100 bg-blue-50/60 text-sm flex flex-wrap gap-x-3 gap-y-1">
            <span className="font-semibold font-mono">روشتة {r.docnumber}</span>
            <span className="text-gray-600">فرع {BL(r.branch)}</span>
            {r.docdate && <span className="text-gray-500 font-mono">{r.docdate}</span>}
            {r.patient_name && <span className="text-gray-700">{r.patient_name}</span>}
            {r.net != null && <span className="font-mono text-gray-700">{fmtNet(r.net)}</span>}
          </div>
          <div className="divide-y divide-gray-100">
            {r.appearances.map(a => (
              <div key={`${a.kind}-${a.claim_id}`} className={`px-4 py-2 text-sm flex flex-wrap items-center gap-x-3 gap-y-1 ${a.active ? '' : 'text-gray-500'}`}>
                <span className="font-mono font-semibold text-blue-700">{a.claim_number}</span>
                <span className="text-gray-600">{a.client_name}{a.subclient_name ? ` — ${a.subclient_name}` : ''}</span>
                <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{a.claim_status_label}</span>
                {a.active
                  ? <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">نشطة</span>
                  : <span className="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-700 border border-red-200">
                      مستثناة{a.excluded_reason ? ` «${a.excluded_reason}»` : ''}{a.excluded_by ? ` — ${a.excluded_by}` : ''}{a.excluded_at ? ` ${a.excluded_at.slice(0, 10)}` : ''}
                    </span>}
                <span className="text-xs text-gray-500">{(ORIGIN[a.origin] || ORIGIN.import)(a)}</span>
                <button onClick={() => open(r, a)} className="ms-auto text-xs px-2 py-1 rounded border border-blue-200 text-blue-700 hover:bg-blue-50">
                  فتح ↗
                </button>
              </div>
            ))}
            {r.softech.length > 0 && (
              <div className="px-4 py-2 text-xs text-gray-600 bg-amber-50/50">
                في سوفتك: {r.softech.map(s => `مطالبة رقم ${s.motalbano} (عميل ${s.personcode})`).join('، ')}
                {r.appearances.length === 0 && ' — لم تُستورد عندنا في أي مطالبة'}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
