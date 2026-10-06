/**
 * QuickSellGrid — server-backed per-branch top-sellers for the POS Items tab.
 *
 * Complements the manual localStorage favorites with a data-driven "الأكثر مبيعًا"
 * grid from GET /api/items/quick-sell/ (deterministic PG aggregate). Collapsible;
 * renders nothing until a branch is chosen. Additive — does not touch basket logic.
 */
import { useEffect, useState } from 'react'
import { itemsApi } from '../api/client'
import ProductCard from './ProductCard'

export default function QuickSellGrid({ branchId, onSelect, onFindStock }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(() => localStorage.getItem('pos_quicksell_open') !== '0')

  useEffect(() => {
    if (!branchId || !open) return
    let alive = true
    setLoading(true)
    itemsApi.quickSell(branchId, { limit: 12 })
      .then(({ data }) => { if (alive) setRows(data.results || []) })
      .catch(() => { if (alive) setRows([]) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [branchId, open])

  if (!branchId) return null

  const toggle = () => { const v = !open; setOpen(v); localStorage.setItem('pos_quicksell_open', v ? '1' : '0') }

  return (
    <div className="mb-2">
      <button onClick={toggle}
              className="flex items-center gap-1.5 text-[11px] font-bold text-muted mb-1 hover:text-content">
        <span>{open ? '▾' : '▸'}</span>
        <span>🔥 الأكثر مبيعًا بالفرع</span>
        {loading && <span className="text-faint">…</span>}
      </button>
      {open && (
        rows.length === 0
          ? (!loading && <div className="text-[11px] text-faint px-1 pb-1">لا توجد مبيعات حديثة كافية.</div>)
          : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 gap-1.5">
              {rows.map((it) => <ProductCard key={it.id} item={it} onSelect={onSelect} onFindStock={onFindStock} compact />)}
            </div>
          )
      )}
    </div>
  )
}
