/* SOFTECH "Q" — partial-pack quantity entry («مبيعات صنف — كمية جزئية من العبوة»). Enter the sale
 * in loose UNITS (strips/vials/amps/patches); the pack-fraction line qty is computed SOFTECH-exact
 * via stripsToQty = round(strips / packqty, 5) — VERIFIED against real stktrans (see the Python
 * mirror strips_to_qty + apps/tests/test_pos_quantity.py). packqty («العبوة — عدد») is overridable
 * in case the item's SOFTECH packqty is missing/wrong. Shared desktop + mobile. */
import { useState } from 'react'
import { stripsToQty, qtyToStrips } from '../hooks/usePosOrder'

export default function UnitsQtyModal({ P, i, onClose, onApply }) {
  const line = P.lines[i]
  const [packN, setPackN] = useState(String(Math.max(1, Number(line.pack_qty) || 1)))
  const [strips, setStrips] = useState(() => String(qtyToStrips(line.qty, Number(line.pack_qty) || 1) || 1))
  const N = Math.max(1, Math.floor(Number(packN) || 1))
  const K = Math.max(0, Math.round(Number(strips) || 0))
  const qty = stripsToQty(K, N)
  const full = Math.floor(K / N)
  const rem = K - full * N
  const unit = line.unit_name || 'وحدة'
  const apply = () => { P.setLine(i, 'qty', qty); onClose(); onApply?.() }
  const onKey = e => { if (e.key === 'Enter') { e.preventDefault(); apply() } else if (e.key === 'Escape') { e.preventDefault(); onClose() } }
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-3" onClick={onClose}>
      <div dir="rtl" className="bg-white rounded-lg p-4 w-[26rem] max-w-[95vw]" onClick={e => e.stopPropagation()}>
        <div className="font-bold mb-2 flex items-center gap-2" style={{ color: '#022871' }}>
          مبيعات صنف — كمية جزئية من العبوة <kbd className="text-[10px] bg-gray-100 border rounded px-1 font-mono">Q</kbd>
        </div>
        {/* item header — mirrors SOFTECH's كود / الوحدة / الصنف */}
        <div className="grid grid-cols-[1fr_auto] gap-x-3 text-xs mb-3 bg-gray-50 border rounded p-2">
          <div className="text-gray-500">الصنف</div>
          <div className="font-medium text-gray-800 truncate max-w-[16rem] text-left" title={line.item_name}>{line.item_name}</div>
          <div className="text-gray-500">الكود</div><div className="font-mono text-gray-700 text-left">{line.softech_itemcode}</div>
          <div className="text-gray-500">الوحدة</div><div className="text-gray-700 text-left">{unit}</div>
        </div>
        {/* البيع-عدد  /  العبوة-عدد   (strips sold / units-per-pack) */}
        <div className="flex items-end justify-center gap-2">
          <label className="text-xs text-gray-600 text-center">البيع — عدد
            <input autoFocus type="number" min="0" step="1" value={strips} onKeyDown={onKey}
                   onChange={e => setStrips(e.target.value)}
                   className="mt-1 w-24 border rounded px-2 py-2 text-center text-lg font-bold tabular-nums" />
          </label>
          <span className="text-2xl text-gray-400 pb-2">/</span>
          <label className="text-xs text-gray-600 text-center">العبوة — عدد
            <input type="number" min="1" step="1" value={packN} onKeyDown={onKey}
                   onChange={e => setPackN(e.target.value)}
                   className="mt-1 w-24 border rounded px-2 py-2 text-center text-lg tabular-nums" />
          </label>
        </div>
        <div className="mt-3 rounded-lg bg-gray-50 border p-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">الكمية <span className="font-mono">Q</span> (عبوات) → SOFTECH</span>
            <span className="font-bold text-xl tabular-nums" style={{ color: '#022871' }}>{qty.toFixed(5)}</span>
          </div>
          <div className="text-[11px] text-gray-500 mt-1">
            {N > 1
              ? <span>{K} {unit} ÷ {N} بالعبوة{full > 0 ? ` — ${full} عبوة${rem > 0 ? ` و ${rem} ${unit}` : ' كاملة'}` : ''}</span>
              : <span>وحدة كاملة (بلا تجزئة)</span>}
          </div>
          {N > 1 && <div className="text-[10px] text-gray-400 mt-1">Q = round(البيع ÷ العبوة، 5 خانات) — مطابق SOFTECH تمامًا.</div>}
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2 rounded border">إلغاء</button>
          <button onClick={apply} className="flex-1 py-2 rounded text-white font-semibold" style={{ background: '#022871' }}>تطبيق</button>
        </div>
      </div>
    </div>
  )
}
