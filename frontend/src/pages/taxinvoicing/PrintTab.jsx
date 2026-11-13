/**
 * The customer-facing layout from documents/<id>/print/. The server decides its rows: one summary
 * line for a buyer on summary, the items otherwise, and never patient or internal data.
 * Print rules: `.tax-print-sheet` in index.css.
 */
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { Btn, Failed, Field, fmt, fmtDate, fmtTime, INPUT, Loading, Notice } from './ui'

function Party({ title, party }) {
  return (
    <div>
      <div className="text-xs text-gray-500">{title}</div>
      <div className="font-bold text-gray-900">{party.name || '—'}</div>
      <div className="text-xs text-gray-700">الرقم الضريبي: {party.tax_id || '—'}</div>
      <div className="text-xs text-gray-700">{[party.street, party.region_city].filter(Boolean).join('، ') || '—'}</div>
    </div>
  )
}

function Sheet({ p }) {
  return (
    <div className="tax-print-sheet bg-white border border-gray-200 rounded-xl p-6 max-w-3xl mx-auto text-gray-900" dir="rtl" data-tour="tax-invoicing-main-print-sheet">
      {!p.is_official && (
        <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-center text-sm font-bold text-amber-900">
          نسخة غير رسمية · الحالة: {p.status_label}
        </div>
      )}
      <div className="flex items-start justify-between gap-3 border-b border-gray-300 pb-3 mb-3">
        <div>
          <h2 className="text-xl font-bold">{p.doc_type_label}</h2>
          <div className="text-sm">رقم {p.internal_id}</div>
        </div>
        <div className="text-xs text-left text-gray-700">
          <div>تاريخ الإصدار: {fmtTime(p.date_time_issued)}</div>
          <div>المطالبة: {p.claim_number}</div>
          <div>الفترة: {fmtDate(p.period_from)} ← {fmtDate(p.period_to)}</div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4 mb-4">
        <Party title="البائع" party={p.issuer} />
        <Party title="المشتري" party={p.buyer} />
      </div>
      {p.original_internal_id && (
        <div className="text-sm mb-3">
          إشعار على الفاتورة رقم {p.original_internal_id}{p.reason ? ` · السبب: ${p.reason}` : ''}
        </div>
      )}
      <table className="w-full text-sm border border-gray-300">
        <thead>
          <tr className="bg-gray-50 text-xs">
            <th className="border border-gray-300 px-2 py-1 text-right">البيان</th>
            <th className="border border-gray-300 px-2 py-1 text-right">الكمية</th>
            <th className="border border-gray-300 px-2 py-1 text-right">الصافي</th>
            {!p.no_vat_due && <th className="border border-gray-300 px-2 py-1 text-right">الضريبة</th>}
            <th className="border border-gray-300 px-2 py-1 text-right">الإجمالي</th>
          </tr>
        </thead>
        <tbody>
          {p.rows.map((r, i) => (
            <tr key={i}>
              <td className="border border-gray-300 px-2 py-1" dir="auto">{r.description}</td>
              <td className="border border-gray-300 px-2 py-1">{fmt(r.quantity, 3)}</td>
              <td className="border border-gray-300 px-2 py-1">{fmt(r.net)}</td>
              {!p.no_vat_due && <td className="border border-gray-300 px-2 py-1">{fmt(r.vat)}</td>}
              <td className="border border-gray-300 px-2 py-1">{fmt(r.total)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 ms-auto w-full max-w-xs text-sm space-y-0.5">
        <div className="flex justify-between"><span>الصافي</span><span>{fmt(p.totals.net)}</span></div>
        <div className="flex justify-between"><span>الضريبة</span><span>{fmt(p.totals.vat)}</span></div>
        <div className="flex justify-between font-bold border-t border-gray-300 pt-1"><span>الإجمالي</span><span>{fmt(p.totals.total)}</span></div>
      </div>
      {p.no_vat_due && (
        <div className="mt-3 rounded-md border border-gray-300 px-3 py-1.5 text-center text-sm font-bold">
          لا توجد ضريبة قيمة مضافة مستحقة على هذا المستند
        </div>
      )}
      {p.eta_uuid && (
        <div className="mt-4 pt-2 border-t border-gray-200 text-[11px] text-gray-600">
          رقم المصلحة: <span dir="ltr" className="font-mono break-all">{p.eta_uuid}</span>
          {p.eta_long_id && <> · <span dir="ltr" className="font-mono break-all">{p.eta_long_id}</span></>}
        </div>
      )}
    </div>
  )
}

export default function PrintTab({ docId, go }) {
  const list = useQuery({ queryKey: ['tax-invoicing', 'documents', {}], queryFn: () => taxInvoicingApi.documents({}).then(r => r.data) })
  const sheet = useQuery({
    queryKey: ['tax-invoicing', 'print', String(docId)],
    queryFn: () => taxInvoicingApi.print(docId).then(r => r.data),
    enabled: !!docId,
  })
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2 no-print">
        <Field label="المستند">
          <select value={docId || ''} onChange={e => go('print', { doc: e.target.value })} className={`${INPUT} min-w-[280px]`} data-tour="tax-invoicing-main-print-pick">
            <option value="">اختر مستنداً…</option>
            {(list.data || []).map(d => <option key={d.id} value={d.id}>{d.internal_id} · {d.claim_number} · {d.status_label}</option>)}
          </select>
        </Field>
        {sheet.data && <Btn variant="primary" onClick={() => window.print()} data-tour="tax-invoicing-main-print-button">🖨️ طباعة</Btn>}
        {docId && <Btn onClick={() => go('documents', { doc: docId })}>← تفاصيل المستند</Btn>}
      </div>
      {!docId && <Notice tone="gray">اختر مستنداً لعرض نسخته المطبوعة.</Notice>}
      {docId && sheet.isLoading && <Loading />}
      {docId && sheet.error && <Failed error={sheet.error} />}
      {sheet.data && <Sheet p={sheet.data} />}
    </div>
  )
}
