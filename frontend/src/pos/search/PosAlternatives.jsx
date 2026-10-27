/**
 * PosAlternatives — verified alternatives (same APPROVED active ingredients) for the highlighted
 * search row (F7). Side panel on desktop, bottom sheet on mobile (`sheet`). Display only: the list
 * comes from the server (approved composition only — never name_scientific); picking calls
 * onPick(item), which the page wires to the normal add-line path. Nothing is replaced automatically
 * and every alternative needs the pharmacist's confirmation.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { posAlternativesApi } from '../../api/client'
import { Badge, BranchStockPill, Icon } from '../design'
import useBranchNames from './useBranchNames'

// DrugEye has no documented search parameter we can verify from here, so the default is:
// open the base page + copy the name to the clipboard. The owner can set the query-parameter name
// below once checked (e.g. 'q'); when empty the clipboard fallback is used.
const DRUGEYE_URL = 'https://www.drugeye.pharorg.com/drugeyeapp/android-search/drugeye-android-live-go.aspx'
export const DRUGEYE_QUERY_PARAM = ''

function openDrugEye(name, setNote) {
  if (DRUGEYE_QUERY_PARAM) {
    window.open(`${DRUGEYE_URL}?${DRUGEYE_QUERY_PARAM}=${encodeURIComponent(name)}`, '_blank', 'noopener')
    return
  }
  window.open(DRUGEYE_URL, '_blank', 'noopener')
  try {
    navigator.clipboard.writeText(name).then(() => setNote('تم نسخ الاسم'), () => setNote(''))
  } catch { setNote('') }
}

const money = v => (v == null || v === '' ? '' : Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 }))

function Card({ it, hereBranchId, nameOf, onPick, original = false }) {
  const others = (it.branch_stock || []).filter(b => String(b.branch_id) !== String(hereBranchId) && Number(b.qty) > 0).slice(0, 3)
  const here = it.here_qty ?? it.qty_at_branch
  return (
    <div className={`rounded-lg border p-2 flex gap-2 ${original ? 'bg-gray-50 border-gray-200' : 'bg-white border-gray-200'}`}>
      {it.thumb
        ? <img src={it.thumb} alt="" loading="lazy" className="w-12 h-12 object-contain rounded bg-gray-50 shrink-0" />
        : <div className="w-12 h-12 rounded bg-gray-100 text-gray-300 flex items-center justify-center shrink-0"><Icon name="package" size={22} /></div>}
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-gray-900 leading-snug">{it.name}</div>
        <div className="flex items-center gap-1 flex-wrap mt-0.5">
          {it.strength && <span className="text-[11px] font-bold px-1.5 rounded bg-[#022871] text-white">{it.strength}</span>}
          {(it.dosage_form || it.form) && <span className="text-[10px] text-gray-500">{it.dosage_form || it.form}</span>}
          {it.pack_price != null && <span className="text-xs font-bold text-emerald-700 tabnum">{money(it.pack_price)}</span>}
        </div>
        <div className="flex items-center gap-1 flex-wrap mt-1">
          {here != null && <BranchStockPill name="هنا" qty={here} className="font-bold" />}
          {others.map(b => <BranchStockPill key={b.branch_id} name={nameOf(b.branch_id) || `#${b.branch_id}`} qty={b.qty} />)}
        </div>
      </div>
      {onPick && (
        <button type="button" onClick={() => onPick(it)}
                className="self-center shrink-0 rounded-lg bg-brand-600 text-white px-2.5 py-1.5 text-xs font-medium hover:bg-brand-700">إضافة</button>
      )}
    </div>
  )
}

export default function PosAlternatives({ item, branchId, onPick, onClose, sheet = false }) {
  const nameOf = useBranchNames()
  const [note, setNote] = useState('')
  const itemId = item?.item_id ?? item?.id
  const { data, isLoading, isError } = useQuery({
    queryKey: ['pos-alternatives', itemId, branchId || null],
    queryFn: () => posAlternativesApi.get(itemId, branchId).then(r => r.data),
    enabled: !!itemId,
    staleTime: 60_000,
  })
  useEffect(() => { setNote('') }, [itemId])
  if (!item) return null

  const body = (
    <div dir="rtl" className="flex flex-col h-full" onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose?.() } }}>
      <div className="flex items-center gap-2 p-3 border-b bg-gray-50">
        <Icon name="repeat" size={16} className="text-gray-500" />
        <div className="font-semibold text-sm flex-1">بدائل مؤكدة (نفس المادة الفعّالة)</div>
        <button type="button" onClick={onClose} title="إغلاق (Esc)" autoFocus
                className="p-1.5 rounded hover:bg-gray-200 text-gray-600"><Icon name="x" size={16} /></button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        <div>
          <div className="text-[11px] text-gray-500 mb-1">الصنف الأصلي</div>
          <Card it={item} hereBranchId={branchId} nameOf={nameOf} original />
        </div>
        {isLoading && <div className="text-center text-sm text-gray-400 py-6">جارٍ التحميل…</div>}
        {isError && <div className="text-center text-sm text-red-600 py-4">تعذّر تحميل البدائل</div>}
        {data && !data.verified && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 text-amber-800 text-sm p-3">
            غير متاح — بيانات المادة الفعالة غير معتمدة لهذا الصنف
          </div>
        )}
        {data?.verified && (
          <>
            <Badge tone="warn" icon="alert" label="يتطلب تأكيد الصيدلي" className="w-full justify-center" />
            <Section title="نفس المادة والتركيز والشكل" rows={data.same} hereBranchId={branchId} nameOf={nameOf} onPick={onPick} />
            <Section title="نفس المادة — تركيز أو شكل مختلف" rows={data.other} hereBranchId={branchId} nameOf={nameOf} onPick={onPick} />
            {!data.same.length && !data.other.length && (
              <div className="text-center text-sm text-gray-400 py-4">لا توجد بدائل معتمدة لهذا الصنف</div>
            )}
          </>
        )}
      </div>
      <div className="p-3 border-t flex items-center gap-2">
        <button type="button" onClick={() => openDrugEye(item.name, setNote)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50">
          <Icon name="search" size={14} /> ابحث في DrugEye
        </button>
        {note && <span className="text-xs text-emerald-700">{note}</span>}
      </div>
    </div>
  )

  if (sheet) {
    return (
      <div className="fixed inset-0 z-[70] flex items-end bg-black/30" onMouseDown={onClose}>
        <div className="w-full bg-white rounded-t-2xl h-[80vh]" onMouseDown={e => e.stopPropagation()}>{body}</div>
      </div>
    )
  }
  return (
    <div className="fixed top-14 bottom-0 left-0 z-[60] w-[26rem] max-w-full bg-white border-e shadow-2xl">{body}</div>
  )
}

function Section({ title, rows, hereBranchId, nameOf, onPick }) {
  if (!rows?.length) return null
  return (
    <div>
      <div className="text-[11px] text-gray-500 mb-1">{title} ({rows.length})</div>
      <div className="space-y-1.5">
        {rows.map(r => <Card key={r.item_id} it={r} hereBranchId={hereBranchId} nameOf={nameOf} onPick={onPick} />)}
      </div>
    </div>
  )
}
