/**
 * PrintReceiptModal.jsx
 *
 * Renders a clean printable receipt for Reservation and Transfer documents.
 *
 * Print strategy: CSS @media print — no window.open(), no external font
 * requests, no hangs. The overlay is hidden on print; only the receipt card
 * is shown. A stable <style> tag is injected into <head> for the print media
 * query, then removed immediately after window.print() returns.
 *
 * Receipt format: narrow card (~360px) — NOT A4.
 */
import { useState, useEffect, useRef } from 'react'
import { reservationsApi, transfersApi } from '../api/client'

const fmt = (n, dp = 2) =>
  Number(n || 0).toLocaleString('ar-EG', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })

const fmtDate = (iso) => {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('ar-EG', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

const STATUS_COLORS = {
  pending:        'bg-gray-100 text-gray-700',
  available:      'bg-orange-100 text-orange-800',
  contacted:      'bg-blue-100 text-blue-800',
  confirmed:      'bg-indigo-100 text-indigo-800',
  fulfilled:      'bg-green-100 text-green-800',
  cancelled:      'bg-red-100 text-red-800',
  expired:        'bg-red-100 text-red-800',
  draft:          'bg-gray-100 text-gray-700',
  approved:       'bg-blue-100 text-blue-800',
  rejected:       'bg-red-100 text-red-800',
  needs_revision: 'bg-yellow-100 text-yellow-800',
  sent_to_erp:    'bg-purple-100 text-purple-800',
  completed:      'bg-green-100 text-green-800',
}

// ── Shared sub-components ──────────────────────────────────────────────────────

function Row({ label, value, bold = false }) {
  return (
    <div className="flex justify-between items-start gap-2 text-sm py-0.5">
      <span className="text-gray-500 shrink-0 text-xs">{label}:</span>
      <span className={`text-right text-xs ${bold ? 'font-bold text-gray-900' : 'text-gray-700'}`}>
        {value ?? '—'}
      </span>
    </div>
  )
}

function SectionCard({ title, children }) {
  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden mb-3">
      {title && (
        <div className="bg-gray-50 px-3 py-1.5 text-xs font-semibold text-gray-500 border-b">
          {title}
        </div>
      )}
      <div className="p-3">{children}</div>
    </div>
  )
}

function ReceiptHeader({ subtitle }) {
  return (
    <div className="text-center mb-4">
      <div className="text-lg font-black text-gray-900 leading-tight">صيدليات الرزيقي</div>
      <div className="text-xs text-gray-400 mt-0.5">{subtitle}</div>
      <div className="border-t border-dashed border-gray-300 mt-3" />
    </div>
  )
}

function ReceiptFooter({ data }) {
  return (
    <div className="text-center text-xs text-gray-400 mt-4 pt-3 border-t border-dashed border-gray-200">
      <div>طُبع بواسطة: {data.printed_by}</div>
      <div>{fmtDate(data.printed_at)}</div>
    </div>
  )
}

// ── Reservation Receipt ────────────────────────────────────────────────────────

function ReservationReceipt({ data }) {
  return (
    <div dir="rtl" className="text-sm text-gray-800">
      <ReceiptHeader subtitle="إيصال طلب حجز" />

      <SectionCard>
        <Row label="رقم الطلب"  value={`#${data.doc_number}`} bold />
        <Row label="الحالة" value={
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[data.status] || 'bg-gray-100 text-gray-700'}`}>
            {data.status_label}
          </span>
        } />
        <Row label="الفرع"       value={data.branch_name} />
        <Row label="موظف الحجز"  value={data.created_by} />
        <Row label="تاريخ الحجز" value={fmtDate(data.created_at)} />
        {data.expected_arrival_date && (
          <Row label="موعد الوصول" value={fmtDate(data.expected_arrival_date)} />
        )}
      </SectionCard>

      {(data.customer_name !== '—' || data.customer_phone !== '—') && (
        <SectionCard title="بيانات العميل">
          <Row label="الاسم"  value={data.customer_name} />
          <Row label="الهاتف" value={<span dir="ltr">{data.customer_phone}</span>} />
        </SectionCard>
      )}

      <SectionCard title="الصنف المطلوب">
        <div className="font-semibold text-gray-900 text-sm leading-tight">{data.item?.name}</div>
        {data.item?.scientific && (
          <div className="text-xs text-gray-400 italic mt-0.5">{data.item.scientific}</div>
        )}
        {data.item?.softech_id && (
          <div className="text-xs font-mono text-gray-400">كود: {data.item.softech_id}</div>
        )}
        <div className="mt-1.5 flex items-center justify-between">
          <span className="text-xs text-gray-500">الكمية المطلوبة</span>
          <span className="font-bold text-gray-900">{data.item?.quantity} وحدة</span>
        </div>
      </SectionCard>

      {data.downpayments?.length > 0 && (
        <SectionCard title="الدفعات المقدمة">
          {data.downpayments.map((dp, i) => (
            <div key={i} className="flex justify-between items-center py-0.5 text-xs border-b last:border-0">
              <span className="text-gray-500">{dp.payment_method}</span>
              <span className="font-semibold text-gray-800">{fmt(dp.amount)} ج.م</span>
            </div>
          ))}
          <div className="flex justify-between items-center mt-2 pt-1 border-t font-bold text-sm">
            <span>الإجمالي المدفوع</span>
            <span className="text-green-700">{fmt(data.total_paid)} ج.م</span>
          </div>
        </SectionCard>
      )}

      {data.notes && (
        <SectionCard title="ملاحظات">
          <p className="text-xs text-gray-600 leading-relaxed">{data.notes}</p>
        </SectionCard>
      )}

      <ReceiptFooter data={data} />
    </div>
  )
}

// ── Transfer Receipt ───────────────────────────────────────────────────────────

function TransferReceipt({ data }) {
  return (
    <div dir="rtl" className="text-sm text-gray-800">
      <ReceiptHeader subtitle="طلب تحويل مخزون" />

      <SectionCard>
        <Row label="رقم الطلب"     value={data.request_number} bold />
        <Row label="الحالة" value={
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[data.status] || 'bg-gray-100 text-gray-700'}`}>
            {data.status_label}
          </span>
        } />
        <Row label="الفرع الطالب"  value={data.requesting_branch} />
        <Row label="الفرع المصدر"  value={data.supplying_branch} />
        <Row label="أنشئ بواسطة"   value={data.created_by} />
        {data.reviewed_by && <Row label="اعتمد بواسطة"   value={data.reviewed_by} />}
        {data.erp_reference && <Row label="مرجع ERP"     value={<span className="font-mono">{data.erp_reference}</span>} />}
        {data.delivery_person_name && <Row label="مندوب التوصيل" value={data.delivery_person_name} />}
        <Row label="تاريخ الإنشاء"  value={fmtDate(data.created_at)} />
        {data.submitted_at  && <Row label="تاريخ التقديم"  value={fmtDate(data.submitted_at)} />}
        {data.reviewed_at   && <Row label="تاريخ الاعتماد" value={fmtDate(data.reviewed_at)} />}
        {data.dispatched_at && <Row label="تاريخ الإرسال"  value={fmtDate(data.dispatched_at)} />}
        {data.completed_at  && <Row label="تاريخ الإغلاق"  value={fmtDate(data.completed_at)} />}
      </SectionCard>

      <SectionCard title={`الأصناف (${data.total_items})`}>
        <div className="divide-y divide-gray-100">
          {data.items?.map((item, i) => (
            <div key={i} className="py-1.5 flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="font-medium text-xs text-gray-800 leading-tight">{item.item_name}</div>
                {item.item_scientific && (
                  <div className="text-xs text-gray-400 italic truncate">{item.item_scientific}</div>
                )}
                {item.item_code && (
                  <div className="text-xs font-mono text-gray-400">{item.item_code}</div>
                )}
                {item.notes && item.notes !== '—' && (
                  <div className="text-xs text-gray-400">{item.notes}</div>
                )}
              </div>
              <div className="font-bold text-gray-900 text-sm shrink-0">{item.quantity}</div>
            </div>
          ))}
        </div>
      </SectionCard>

      {data.notes && (
        <SectionCard title="ملاحظات">
          <p className="text-xs text-gray-600 leading-relaxed">{data.notes}</p>
        </SectionCard>
      )}
      {data.rejection_reason && (
        <SectionCard title="سبب الرفض">
          <p className="text-xs text-red-700 leading-relaxed">{data.rejection_reason}</p>
        </SectionCard>
      )}

      <ReceiptFooter data={data} />
    </div>
  )
}

// ── Print CSS injector ─────────────────────────────────────────────────────────

const PRINT_STYLE_ID = 'receipt-print-style'

function injectPrintStyle() {
  document.getElementById(PRINT_STYLE_ID)?.remove()
  const style = document.createElement('style')
  style.id = PRINT_STYLE_ID
  style.textContent = `
    @media print {
      body > *:not(#receipt-print-root) { display: none !important; }
      #receipt-print-root {
        display: flex !important;
        position: fixed !important;
        inset: 0 !important;
        z-index: 9999 !important;
        background: white !important;
        padding: 0 !important;
        margin: 0 !important;
        align-items: flex-start !important;
        justify-content: center !important;
      }
      .print-hide { display: none !important; }
      .receipt-modal-box {
        box-shadow: none !important;
        border-radius: 0 !important;
        width: 100% !important;
        max-height: none !important;
        background: white !important;
      }
      .receipt-scroll-area {
        overflow: visible !important;
        background: white !important;
        padding: 0 !important;
      }
      .receipt-card {
        box-shadow: none !important;
        border: none !important;
        width: 80mm !important;
        max-width: 80mm !important;
        margin: 0 auto !important;
        padding: 8mm !important;
        font-size: 11pt !important;
      }
      @page {
        size: 80mm auto;
        margin: 0;
      }
    }
  `
  document.head.appendChild(style)
}

function removePrintStyle() {
  document.getElementById(PRINT_STYLE_ID)?.remove()
}

// ── Main modal ─────────────────────────────────────────────────────────────────

export default function PrintReceiptModal({ type, docId, onClose }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')
  const receiptRef            = useRef(null)

  useEffect(() => {
    const fetcher = type === 'reservation'
      ? () => reservationsApi.printReceipt(docId)
      : () => transfersApi.printReceipt(docId)

    setLoading(true)
    fetcher()
      .then(({ data }) => setData(data))
      .catch(() => setError('تعذّر تحميل بيانات الإيصال'))
      .finally(() => setLoading(false))
  }, [type, docId])

  // Clean up print style if modal is unmounted mid-print
  useEffect(() => () => removePrintStyle(), [])

  const handlePrint = () => {
    if (!receiptRef.current) return
    injectPrintStyle()
    // afterprint fires when the print dialog closes — clean up then
    window.addEventListener('afterprint', removePrintStyle, { once: true })
    requestAnimationFrame(() => window.print())
  }

  return (
    <div
      id="receipt-print-root"
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
    >
      {/* Backdrop — hidden during print so it can't cover the receipt */}
      <div
        className="print-hide absolute inset-0 bg-black/50"
        onClick={onClose}
      />

      {/* Modal box — receipt-modal-box loses its chrome in print */}
      <div
        className="receipt-modal-box relative bg-white rounded-2xl shadow-2xl flex flex-col"
        style={{ width: '400px', maxHeight: '90vh' }}
      >
        {/* Header — hidden during print */}
        <div className="print-hide flex items-center justify-between px-4 py-3 border-b shrink-0">
          <h2 className="font-bold text-gray-800 text-sm">
            {type === 'reservation' ? '🖨️ إيصال الحجز' : '🖨️ إيصال التحويل'}
          </h2>
          <div className="flex items-center gap-2">
            {data && !loading && (
              <button
                onClick={handlePrint}
                className="flex items-center gap-1.5 bg-gray-800 text-white text-xs font-medium px-3 py-1.5 rounded-lg hover:bg-gray-900 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" />
                </svg>
                طباعة
              </button>
            )}
            <button onClick={onClose}
              className="text-gray-400 hover:text-gray-600 p-1 rounded-lg hover:bg-gray-100">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Receipt preview — receipt-scroll-area becomes visible overflow in print */}
        <div className="receipt-scroll-area flex-1 overflow-y-auto p-4 bg-gray-50">
          {loading && (
            <div className="flex items-center justify-center py-10">
              <div className="w-6 h-6 border-4 border-gray-200 border-t-gray-600 rounded-full animate-spin" />
            </div>
          )}
          {error && (
            <div className="text-red-600 bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-center">
              {error}
            </div>
          )}
          {data && !loading && (
            /* Receipt card — the ONLY thing printed. Not inside any print-hide ancestor. */
            <div
              ref={receiptRef}
              className="receipt-card bg-white rounded-xl shadow-sm border border-gray-200 p-5 mx-auto"
              style={{ maxWidth: '360px' }}
            >
              {type === 'reservation'
                ? <ReservationReceipt data={data} />
                : <TransferReceipt data={data} />
              }
            </div>
          )}
        </div>

        {/* Footer hint — hidden during print */}
        {data && !loading && (
          <div className="print-hide px-4 py-2 border-t bg-gray-50 text-xs text-gray-400 text-center rounded-b-2xl shrink-0">
            تنسيق الإيصال: 80mm — مناسب للطابعات الحرارية
          </div>
        )}
      </div>
    </div>
  )
}
