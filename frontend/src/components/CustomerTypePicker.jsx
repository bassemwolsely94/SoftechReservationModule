/*
 * CustomerTypePicker — SOFTECH's two-level customer selection:
 *   نوع العميل (type) → إسم العميل (entity, searchable).
 * Backed by /pos-orders/customer-types + /customer-entities (live). Shared web + mobile.
 * `compact` renders the two selects stacked for mobile.
 */
import { useState } from 'react'

export default function CustomerTypePicker({ P, compact = false }) {
  const [open, setOpen] = useState(false)
  const inp = 'w-full border rounded px-2 py-1.5 text-sm'
  return (
    <div className={compact ? 'space-y-2' : 'grid grid-cols-2 gap-2'}>
      <label className="text-[11px] text-gray-600 block">نوع العميل
        <select value={P.custType} onChange={e => P.setCustType(e.target.value)} className={inp + ' mt-0.5'}>
          {(P.custTypes || []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </label>

      <label className="text-[11px] text-gray-600 block">إسم العميل
        <div className="relative mt-0.5">
          <input
            value={P.customer?.name || P.entityQuery}
            onChange={e => { P.setEntityQuery(e.target.value); if (P.customer) P.selectEntity(null) }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            placeholder="ابحث / اختر العميل…"
            className={inp + (P.customer ? ' bg-green-50 border-green-300' : '')} />
          {P.customer && (
            <button onMouseDown={e => { e.preventDefault(); P.selectEntity(null); P.setEntityQuery('') }}
                    className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400">✕</button>
          )}
          {open && !P.customer && (P.entities || []).length > 0 && (
            <div className="absolute z-30 top-full inset-x-0 mt-0.5 bg-white border rounded shadow-lg max-h-56 overflow-auto text-xs">
              {P.entities.map(e => (
                <button key={e.personcode || e.name}
                        onMouseDown={e2 => { e2.preventDefault(); P.selectEntity(e); P.setEntityQuery(''); setOpen(false) }}
                        className="block w-full text-right px-2 py-1.5 border-b last:border-0 hover:bg-indigo-50">
                  {e.name}{e.pic ? <span className="text-gray-400 font-mono"> · {e.pic}</span> : ''}
                </button>
              ))}
            </div>
          )}
        </div>
      </label>

      {/* PIC + discount source hint */}
      <div className="text-[11px] text-gray-500 col-span-full flex gap-3">
        {P.customer?.softech_pic && <span>PIC: <b className="font-mono">{P.customer.softech_pic}</b></span>}
        {P.typeCfg && <span>الخصم من: {P.typeCfg.discount === 'b2b' ? 'تعاقد B2B' : 'حدود الخصم + الصنف'}</span>}
      </div>
    </div>
  )
}
