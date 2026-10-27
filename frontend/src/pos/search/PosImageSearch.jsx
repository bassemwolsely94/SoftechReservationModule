/**
 * PosImageSearch — full-screen image grid for choosing an item by its picture (F6).
 * 5 columns on desktop, 2 on mobile. Same search endpoint/rules as the dropdown (network stock);
 * tiles show image, name + strength, the big this-branch stock box and the best other-branch pill. Display only —
 * stock/next-action come from the server. Pick → onPick(item) then onClose.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { itemsApi } from '../../api/client'
import { BranchStockPill, Icon } from '../design'
import useBranchNames from './useBranchNames'
import StockAge from './StockAge'
import PosItemPreview from './PosItemPreview'
import { ItemBadges, HereStock } from './PosResultRow'

export default function PosImageSearch({ open, onClose, branchId, customerId, initialQuery = '', onPick }) {
  const nameOf = useBranchNames()
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [hover, setHover] = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setQ(initialQuery); setDq(initialQuery); setHover(null)
    setTimeout(() => inputRef.current?.focus(), 0)
  }, [open])   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = setTimeout(() => setDq(q.trim()), 250); return () => clearTimeout(t) }, [q])

  const { data, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['item-search-widget', dq, branchId, 'pos'],      // shares the dropdown's cache
    queryFn: () => itemsApi.wildcardSearch(dq, branchId, { network: true, noLive: true })
      .then(r => ({ rows: r.data.results || [], asOf: r.data.stock_as_of ?? null })),
    enabled: open && dq.length >= 2,
    staleTime: 15_000,
    keepPreviousData: true,
  })
  const rows = data?.rows || []

  const pick = (item) => { onPick?.(item); onClose?.() }
  // Enter while the debounce/fetch still shows the OLDER query's tiles → queued for the typed text;
  // it picks the first tile of THAT query once its rows arrive (never the previous result's tile).
  const typed = q.trim()
  const stale = typed !== dq || isFetching || !!isPlaceholderData
  const [enterFor, setEnterFor] = useState(null)
  useEffect(() => {
    if (enterFor == null) return
    if (typed !== enterFor) { setEnterFor(null); return }
    if (stale) return
    setEnterFor(null)
    if (rows[0]) pick(rows[0])
  }, [enterFor, typed, stale, rows])   // eslint-disable-line react-hooks/exhaustive-deps
  if (!open) return null

  return (
    <div dir="rtl" className="fixed inset-0 z-[70] bg-white flex flex-col"
         onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose?.() } }}>
      <div className="flex items-center gap-2 p-2 border-b bg-gray-50">
        <Icon name="image" size={18} className="text-gray-500" />
        <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
               onKeyDown={e => {
                 if (e.key !== 'Enter') return
                 e.preventDefault()
                 if (stale) { if (typed.length >= 2) setEnterFor(typed) }
                 else if (rows[0]) pick(rows[0])
               }}
               placeholder="ابحث بالاسم / الكود… (Enter يضيف أول صنف · Esc إغلاق)"
               className="flex-1 border rounded px-3 py-2 text-sm" />
        {data?.asOf != null && <StockAge asOf={data.asOf} />}
        <button type="button" onClick={onClose} title="إغلاق (Esc)"
                className="p-2 rounded hover:bg-gray-200 text-gray-600"><Icon name="x" size={18} /></button>
      </div>
      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 overflow-y-auto p-3">
          {dq.length < 2 && <div className="text-center text-gray-400 text-sm py-10">اكتب حرفين على الأقل لعرض الصور</div>}
          {dq.length >= 2 && !rows.length && !isFetching && <div className="text-center text-gray-400 text-sm py-10">لا توجد نتائج</div>}
          <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
            {rows.map(item => {
              const here = item.qty_at_branch
              const best = (item.branch_stock || [])
                .filter(b => String(b.branch_id) !== String(branchId) && Number(b.qty) > 0)
                .sort((a, b) => Number(b.qty) - Number(a.qty))[0]
              return (
                <button key={item.softech_id ?? item.id} type="button"
                        onClick={() => pick(item)} onMouseEnter={() => setHover(item)}
                        className="text-start border rounded-lg bg-white hover:border-brand-400 hover:shadow p-2 flex flex-col gap-1.5 focus:outline-none focus:ring-2 focus:ring-brand-300">
                  {item.thumb
                    ? <img src={item.thumb} alt="" loading="lazy" className="w-full h-28 object-contain rounded bg-gray-50" />
                    : <div className="w-full h-28 rounded bg-gray-100 text-gray-300 flex items-center justify-center"><Icon name="package" size={36} /></div>}
                  <div className="text-sm font-semibold text-gray-900 leading-snug line-clamp-2">{item.name}</div>
                  <div className="flex items-center gap-1 flex-wrap">
                    {item.strength && <span className="text-[11px] font-bold px-1.5 rounded bg-[#022871] text-white">{item.strength}</span>}
                    <ItemBadges item={item} />
                  </div>
                  <div className="flex items-center gap-1 flex-wrap mt-auto">
                    {here != null && <HereStock qty={here} branchName={nameOf(branchId)} />}
                    {best && <BranchStockPill size="xs" name={nameOf(best.branch_id) || `#${best.branch_id}`} qty={best.qty} />}
                  </div>
                </button>
              )
            })}
          </div>
        </div>
        <aside className="hidden lg:block w-72 border-s overflow-y-auto bg-white">
          <PosItemPreview item={hover} hereBranchId={branchId} customerId={customerId} />
        </aside>
      </div>
    </div>
  )
}
