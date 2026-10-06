/**
 * CommerceAllocationGrid — the Option-A allocation matrix editor.
 * Rows = items (shared unit price), columns = the recipient's branches, cells =
 * editable per-branch quantities.  Row total = Σ cells; document total = Σ(row qty × price).
 */
import { useState, useEffect } from 'react'
import { commerceApi } from '../api/client'

const fmt = n => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const inp = 'border border-gray-300 rounded px-2 py-1.5 text-sm'

export default function CommerceAllocationGrid({ doc, onTotals }) {
  const id = doc.id
  const [grid, setGrid]   = useState(null)
  const [draft, setDraft] = useState({ item_name: '', unit_price: '' })
  const [newBranch, setNewBranch] = useState('')
  const [busy, setBusy]   = useState(false)

  const load = () => commerceApi.grid(id).then(r => {
    setGrid(r.data)
    onTotals && onTotals(r.data.total)
  })
  useEffect(() => { load() }, [id])

  const addBranch = async () => {
    if (!newBranch.trim() || !doc.recipient) return
    setBusy(true)
    try { await commerceApi.addLocation(doc.recipient, { name: newBranch.trim() }); setNewBranch(''); await load() }
    finally { setBusy(false) }
  }

  const addItem = async () => {
    if (!draft.item_name.trim()) return
    setBusy(true)
    try {
      await commerceApi.addLine(id, { item_name: draft.item_name.trim(), unit_price: draft.unit_price || 0, quantity: 0 })
      setDraft({ item_name: '', unit_price: '' }); await load()
    } finally { setBusy(false) }
  }

  const setCell = async (lineId, locId, value) => {
    await commerceApi.setCell(id, lineId, { location: locId, quantity: value || 0 })
    await load()
  }
  const patchPrice = async (lineId, price) => { await commerceApi.editLine(id, lineId, { unit_price: price }); await load() }
  const delItem = async (lineId) => { if (window.confirm('حذف الصنف؟')) { await commerceApi.deleteLine(id, lineId); await load() } }

  if (!doc.recipient) return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
      شبكة التوزيع تحتاج جهة (مستشفى) لها فروع. عيّن جهة للمستند أولاً.
    </div>
  )
  if (!grid) return <div className="text-gray-400 text-sm py-6 text-center">جارٍ التحميل…</div>

  const locs = grid.locations

  return (
    <div>
      {/* Branch manager */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-xs text-gray-500">الفروع ({locs.length}):</span>
        {locs.map(l => <span key={l.id} className="text-xs bg-gray-100 text-gray-700 rounded px-2 py-0.5">{l.name}</span>)}
        <input className={`${inp} w-32`} placeholder="+ فرع جديد" value={newBranch}
          onChange={e => setNewBranch(e.target.value)} onKeyDown={e => e.key === 'Enter' && addBranch()} />
        <button onClick={addBranch} disabled={busy || !newBranch.trim()}
          className="text-xs px-2 py-1 bg-sky-600 text-white rounded hover:bg-sky-700 disabled:opacity-50">إضافة فرع</button>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              <th className="text-right px-3 py-2 text-xs font-semibold text-gray-500 sticky right-0 bg-gray-50">الصنف</th>
              <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500 whitespace-nowrap">سعر الوحدة</th>
              {locs.map(l => <th key={l.id} className="text-center px-2 py-2 text-xs font-semibold text-sky-700 whitespace-nowrap">{l.name}</th>)}
              <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500">إجمالى الكمية</th>
              <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500">القيمة</th>
              <th></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {grid.rows.length === 0 && (
              <tr><td colSpan={locs.length + 5} className="text-center py-8 text-gray-400">أضف أصنافاً ثم وزّع الكميات على الفروع</td></tr>
            )}
            {grid.rows.map(row => (
              <tr key={row.line_id}>
                <td className="px-3 py-2 font-medium text-gray-800 sticky right-0 bg-white whitespace-nowrap">{row.item_name}</td>
                <td className="px-3 py-2">
                  <input type="number" step="any" className={`${inp} w-24 text-left`} defaultValue={row.unit_price}
                    onBlur={e => Number(e.target.value) !== Number(row.unit_price) && patchPrice(row.line_id, e.target.value)} />
                </td>
                {locs.map(l => (
                  <td key={l.id} className="px-1 py-2 text-center">
                    <input type="number" step="1" className={`${inp} w-16 text-center`} defaultValue={row.cells[l.id] || 0}
                      onBlur={e => Number(e.target.value) !== Number(row.cells[l.id] || 0) && setCell(row.line_id, l.id, e.target.value)} />
                  </td>
                ))}
                <td className="px-3 py-2 text-left font-mono font-semibold">{fmt(row.total_qty)}</td>
                <td className="px-3 py-2 text-left font-mono font-semibold text-gray-900">{fmt(row.line_total)}</td>
                <td className="px-2 py-2 text-left"><button onClick={() => delItem(row.line_id)} className="text-red-500 hover:text-red-700 text-xs">حذف</button></td>
              </tr>
            ))}
            {/* Add-item row */}
            <tr className="bg-blue-50/40">
              <td className="px-3 py-2 sticky right-0 bg-blue-50/40">
                <input className={`${inp} w-36`} placeholder="اسم الصنف…" value={draft.item_name}
                  onChange={e => setDraft(d => ({ ...d, item_name: e.target.value }))} onKeyDown={e => e.key === 'Enter' && addItem()} />
              </td>
              <td className="px-3 py-2">
                <input type="number" step="any" className={`${inp} w-24 text-left`} placeholder="السعر" value={draft.unit_price}
                  onChange={e => setDraft(d => ({ ...d, unit_price: e.target.value }))} />
              </td>
              <td colSpan={locs.length + 2} className="px-3 py-2 text-gray-400 text-xs">أضف الصنف ثم وزّع الكميات على الفروع</td>
              <td className="px-2 py-2 text-left">
                <button onClick={addItem} disabled={busy || !draft.item_name.trim()}
                  className="px-3 py-1 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 disabled:opacity-50">إضافة</button>
              </td>
            </tr>
          </tbody>
          <tfoot>
            <tr className="bg-gray-50 border-t-2 border-gray-200 font-semibold">
              <td className="px-3 py-2 sticky right-0 bg-gray-50">الإجمالى</td>
              <td></td>
              {locs.map(l => {
                const colSum = grid.rows.reduce((s, r) => s + Number(r.cells[l.id] || 0), 0)
                return <td key={l.id} className="px-2 py-2 text-center font-mono text-xs text-gray-600">{fmt(colSum)}</td>
              })}
              <td></td>
              <td className="px-3 py-2 text-left font-mono text-gray-900">{fmt(grid.total)}</td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  )
}
