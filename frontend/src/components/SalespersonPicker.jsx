import { useState } from 'react'

/*
 * SalespersonPicker — مسئول البيع chosen by usercode OR name (searches SOFTECH `users`).
 * Displays "usercode — name"; only the usercode is ever sent to the ERP (P.salesperson).
 */
export default function SalespersonPicker({ P, className = '' }) {
  const [open, setOpen] = useState(false)
  const cls = className || 'w-full border rounded px-2 py-1.5 text-sm'
  const display = P.salesperson
    ? `${P.salesperson}${P.salespersonName ? ' — ' + P.salespersonName : ''}`
    : ''
  // only privileged roles may change the seller — everyone else sees their own, locked
  const locked = !(P.ref?.can_change_seller)
  if (locked) {
    return <input value={display || '—'} readOnly title="مقفول على المستخدم الحالى"
                  className={cls + ' bg-gray-100 text-gray-600 cursor-not-allowed'} />
  }
  return (
    <div className="relative">
      <input
        value={open ? P.salespersonQuery : display}
        onChange={e => P.setSalespersonQuery(e.target.value)}
        onFocus={() => { setOpen(true); P.setSalespersonQuery('') }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="كود أو اسم البائع…"
        className={cls + (P.salesperson && !open ? ' bg-green-50 border-green-300' : '')} />
      {open && (P.salespeople || []).length > 0 && (
        <div className="absolute z-30 top-full inset-x-0 mt-0.5 bg-white border rounded shadow-lg max-h-56 overflow-auto text-xs">
          {P.salespeople.map(p => (
            <button key={p.usercode}
                    onMouseDown={e => { e.preventDefault(); P.selectSalesperson(p); setOpen(false) }}
                    className="block w-full text-right px-2 py-1.5 border-b last:border-0 hover:bg-indigo-50">
              <span className="font-mono text-gray-500">{p.usercode}</span> — {p.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
