/**
 * OrderPanel.jsx — build, copy, share and record a supplier order list (doc 24 §17).
 *
 * Owner decision: external purchasing produces a WhatsApp / Excel order list only —
 * nothing is written to SOFTECH. "تسجيل الطلب" records the order as expected incoming so
 * the same need is never ordered twice. The backend decides what the need is; this panel
 * only shows it, and asks for a reason where the operator buys more than the need.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import WhatsAppShareButton from '../../components/WhatsAppShareButton'
import { btnGhost, btnPrimary, downloadBlob, errText, inputCls, money, newKey, q } from './supplyUi'

function toPayload(ls) {
  return ls.filter(l => Number(l.qty) > 0).map(l => ({
    item_id: l.item_id, availability_line_id: l.availability_line_id || undefined,
    case_id: l.case_id || undefined, branch_id: l.branch_id ?? undefined,
    qty: Number(l.qty), reason: (l.reason || '').trim() || undefined,
  }))
}

export default function OrderPanel({ lines: initialLines, supplierId, supplierName, onClose, onCommitted }) {
  const [lines, setLines] = useState(() => initialLines.map(l => ({ ...l, reason: '' })))
  const [lang, setLang] = useState('ar')
  const [key] = useState(newKey)                    // one key for this panel → safe re-clicks
  const [copied, setCopied] = useState(false)
  const [debounced, setDebounced] = useState(lines)

  useEffect(() => { const t = setTimeout(() => setDebounced(lines), 350); return () => clearTimeout(t) }, [lines])

  // Preview follows a debounced copy (quiet while typing); commit / Excel always use the
  // CURRENT lines so a reason typed just before clicking is never lost.
  const payloadLines = useMemo(() => toPayload(debounced), [debounced])

  const previewQ = useQuery({
    queryKey: ['supply-order-preview', payloadLines, lang],
    queryFn: () => supplyApi.orderPreview({ lines: payloadLines, lang }).then(r => r.data),
    enabled: payloadLines.length > 0,
    placeholderData: prev => prev,
  })

  const commitM = useMutation({
    mutationFn: () => supplyApi.orderCommit({
      lines: toPayload(lines), idempotency_key: key, lang,
      supplier: supplierId || undefined, supplier_name: supplierName || '',
    }).then(r => r.data),
    onSuccess: (data) => onCommitted?.(data),
  })

  const excelM = useMutation({
    mutationFn: () => supplyApi.orderExcel({ lines: toPayload(lines), supplier_name: supplierName || '' }),
    onSuccess: (res) => downloadBlob(res.data, `order_${(supplierName || 'supplier').replace(/\s+/g, '_')}.xlsx`),
  })

  const preview = previewQ.data
  const byItem = useMemo(() => Object.fromEntries((preview?.lines || []).map(r => [r.item_id, r])), [preview])
  const text = commitM.data?.text || preview?.text || ''
  const missingReason = lines.some(l => byItem[l.item_id]?.exceeds_need && !l.reason.trim())

  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { /* clipboard blocked — the text stays selectable below */ }
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); copy() }
    if (e.key === 'Escape') onClose?.()
  }

  const setLine = (i, patch) => setLines(ls => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)))

  return (
    <div className="rounded-lg border border-primary/40 bg-surface p-3 space-y-3" onKeyDown={onKey}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-bold text-content">طلب شراء{supplierName ? ` — ${supplierName}` : ''}</h3>
        <span className="text-[11px] text-content/50">لا يُرسل شيء إلى SOFTECH — التسجيل يحفظ الطلب كوارد متوقع ويمنع تكراره</span>
        <div className="mr-auto flex items-center gap-2">
          <select value={lang} onChange={e => setLang(e.target.value)} className={`${inputCls} text-xs`}>
            <option value="ar">عنوان عربي</option>
            <option value="en">English header</option>
          </select>
          <button type="button" onClick={onClose} className="text-xs text-content/50 hover:text-primary">إغلاق ✕</button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-xs text-content/60 border-b border-line">
            <tr>
              <th className="text-right py-1 px-2">الصنف</th>
              <th className="py-1 px-2 w-24">الكمية</th>
              <th className="py-1 px-2" title="الاحتياج الحالي بعد المخزون والتحويلات والطلبات المفتوحة">الاحتياج</th>
              <th className="py-1 px-2">السعر</th>
              <th className="py-1 px-2">القيمة</th>
              <th className="text-right py-1 px-2">ملاحظة</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const r = byItem[l.item_id]
              return (
                <tr key={l.key} className="border-b border-line/60 align-top">
                  <td className="py-1.5 px-2 text-content">{l.label}</td>
                  <td className="py-1.5 px-2">
                    <input type="number" min="0" step="1" value={l.qty} disabled={!!commitM.data}
                      onChange={e => setLine(i, { qty: e.target.value })}
                      className={`${inputCls} w-20 text-center`} />
                  </td>
                  <td className="py-1.5 px-2 text-center text-content/70">{r ? q(r.recommended_qty) : '…'}</td>
                  <td className="py-1.5 px-2 text-center text-content/70">{r ? money(r.unit_price) : '…'}</td>
                  <td className="py-1.5 px-2 text-center text-content/70">{r ? money(r.line_value) : '…'}</td>
                  <td className="py-1.5 px-2">
                    {r?.exceeds_need && !commitM.data && (
                      <input value={l.reason} onChange={e => setLine(i, { reason: e.target.value })}
                        placeholder="الكمية أكبر من الاحتياج — اذكر السبب"
                        className={`${inputCls} w-full text-xs border-amber-300`} />
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <pre dir="auto" className="whitespace-pre-wrap text-sm bg-primary/5 border border-line rounded p-2 text-content select-all min-h-[3rem]">
        {text || (previewQ.isFetching ? 'جارٍ التحضير…' : '—')}
      </pre>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={copy} disabled={!text} className={btnGhost} title="Ctrl+Enter">
          {copied ? 'تم النسخ ✓' : 'نسخ النص'}
        </button>
        <WhatsAppShareButton text={text} size="md" label="إرسال عبر واتساب" />
        <button type="button" onClick={() => excelM.mutate()} disabled={!payloadLines.length || excelM.isPending}
          className={btnGhost}>{excelM.isPending ? 'جارٍ التصدير…' : 'Excel'}</button>
        {!commitM.data ? (
          <button type="button" onClick={() => commitM.mutate()}
            disabled={!payloadLines.length || commitM.isPending || missingReason} className={btnPrimary}>
            {commitM.isPending ? 'جارٍ التسجيل…' : 'تسجيل الطلب'}
          </button>
        ) : (
          <span className="text-sm text-emerald-700">
            ✓ سُجّل الطلب ({commitM.data.decisions.length} صنف){commitM.data.replayed ? ' — مسجّل سابقاً' : ''}
          </span>
        )}
        {preview && <span className="text-xs text-content/60">
          إجمالي {q(preview.total_qty)} وحدة · قيمة تقديرية {money(preview.estimated_value)}
        </span>}
        {missingReason && <span className="text-xs text-amber-700">اذكر سبب الكميات الأكبر من الاحتياج قبل التسجيل</span>}
        {(commitM.isError || previewQ.isError || excelM.isError) && (
          <span className="text-xs text-rose-600">{errText(commitM.error || previewQ.error || excelM.error)}</span>
        )}
      </div>
    </div>
  )
}
