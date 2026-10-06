/*
 * CustomerTypePicker — SOFTECH's customer selection as ONE three-level cascade:
 *   ① نوع العميل (type)  →  ② إسم العميل (account, searchable)  →  ③ العميل الفعلي / PIC (individual).
 *
 * Level 3 is part of the SAME selector, not a detached row. It COLLAPSES into level 2
 * when the account is itself a named person (the account's own softech_pic is the PIC);
 * for contract/delivery the account is generic and a distinct individual is picked. The
 * PIC is mandatory only for delivery (P.needsPicCustomer).
 *
 * Backed by /pos-orders/customer-types + /customer-entities (live). Shared web + mobile.
 * Pass `onOpenPic` to enable stage ③ (opens the Individual-Customers directory). `compact`
 * stacks the controls for mobile.
 */
import { useState } from 'react'

export default function CustomerTypePicker({ P, compact = false, dense = false, onOpenPic, flow = null }) {
  const [open, setOpen] = useState(false)
  const inp = 'w-full border rounded px-2 py-1.5 text-sm'
  // Effective PIC = an explicitly chosen individual, else the account's own person (collapse).
  const explicitPic = P.picCustomer
  const accountPic = !explicitPic && P.customer?.softech_pic
    ? { name: P.customer.name, softech_pic: P.customer.softech_pic, fromAccount: true } : null
  const pic = explicitPic || accountPic
  const picRequired = P.needsPicCustomer

  // Entity search dropdown, shared by dense + full layouts.
  const entityDropdown = open && !P.customer && (P.entities || []).length > 0 && (
    <div className="absolute z-30 top-full inset-x-0 mt-0.5 bg-white border rounded shadow-lg max-h-56 overflow-auto text-xs">
      {P.entities.map(e => (
        <button key={e.personcode || e.name}
                onMouseDown={e2 => { e2.preventDefault(); P.selectEntity(e); P.setEntityQuery(''); setOpen(false) }}
                className="block w-full text-right px-2 py-1.5 border-b last:border-0 hover:bg-indigo-50">
          {e.name}{e.pic ? <span className="text-gray-400 font-mono"> · {e.pic}</span> : ''}
        </button>
      ))}
    </div>
  )

  // ── dense: the whole cascade on ONE line (icon-driven, minimal) for the desktop header ──
  if (dense) {
    return (
      <div className="flex items-center gap-1.5 text-xs">
        <select value={P.custType} onChange={e => P.setCustType(e.target.value)} title="① نوع العميل"
                data-pos-flow="custtype" {...(flow?.type || {})}
                className="h-8 border rounded px-1.5 text-xs bg-white shrink-0 max-w-[9rem]">
          {(P.custTypes || []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
        <div className="relative flex-1 min-w-[7rem]">
          <input value={P.customer?.name || P.entityQuery}
                 onChange={e => { P.setEntityQuery(e.target.value); if (P.customer) P.selectEntity(null) }}
                 onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
                 placeholder="② إسم العميل…" title="② إسم العميل"
                 data-pos-flow="custname" {...(flow?.name || {})}
                 className={'h-8 w-full border rounded px-2 text-xs' + (P.customer ? ' bg-green-50 border-green-300' : '')} />
          {P.customer && (
            <button onMouseDown={e => { e.preventDefault(); P.selectEntity(null); P.setEntityQuery('') }}
                    className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400">✕</button>
          )}
          {entityDropdown}
        </div>
        {onOpenPic && (pic ? (
          <span title={`③ العميل الفعلي (PIC)${pic.fromAccount ? ' — من الحساب' : ''}`}
                className={`h-8 flex items-center gap-1 rounded px-2 text-xs shrink-0 max-w-[13rem] ${pic.fromAccount ? 'bg-sky-50 border border-sky-200 text-sky-700' : 'bg-green-50 border border-green-300'}`}>
            🪪 <span className="truncate font-medium">{pic.name}</span>
            {pic.softech_pic && <span className="font-mono text-[10px] text-gray-500">{pic.softech_pic}</span>}
            {explicitPic && <button onClick={() => P.setPicCustomer(null)} className="text-gray-400 hover:text-red-500">✕</button>}
          </span>
        ) : (
          <button onClick={onOpenPic} title={picRequired ? '③ العميل الفعلي (PIC) — مطلوب قبل الإرسال' : '③ العميل الفعلي (PIC) — اختياري (لسحب التاريخ والاقتراحات)'}
                  data-pos-flow="pic" {...(flow?.pic || {})}
                  className={`h-8 px-2 rounded text-xs border shrink-0 ${picRequired ? 'text-red-700 border-red-300 bg-red-50 font-semibold' : 'text-gray-600 bg-white hover:bg-gray-50'}`}>
            🪪 PIC{picRequired ? ' *' : ''}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className={compact ? 'space-y-2' : 'grid grid-cols-2 gap-2'}>
      {/* ① نوع العميل */}
      <label className="text-[11px] text-gray-600 block">
        <span className="text-gray-400 font-mono">①</span> نوع العميل
        <select value={P.custType} onChange={e => P.setCustType(e.target.value)} className={inp + ' mt-0.5'}>
          {(P.custTypes || []).map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
        </select>
      </label>

      {/* ② إسم العميل */}
      <label className="text-[11px] text-gray-600 block">
        <span className="text-gray-400 font-mono">②</span> إسم العميل
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
          {entityDropdown}
        </div>
      </label>

      {/* ③ العميل الفعلي (PIC) — third stage of the same selector */}
      {onOpenPic && (
        <div className="col-span-full">
          <div className="text-[11px] text-gray-600 mb-0.5 flex items-center gap-1.5">
            <span><span className="text-gray-400 font-mono">③</span> 🪪 العميل الفعلي (PIC) — الشخص</span>
            {picRequired
              ? <span className="text-[10px] font-semibold text-red-600 bg-red-50 border border-red-200 rounded px-1">مطلوب قبل الإرسال</span>
              : <span className="text-[10px] text-gray-400">اختياري — لسحب تاريخه واقتراحاته</span>}
          </div>
          <div className="flex items-center gap-2">
            {explicitPic ? (
              <div className="flex-1 flex items-center gap-2 bg-green-50 border border-green-300 rounded px-2 py-1.5 text-sm">
                <span className="font-medium">{explicitPic.name}</span>
                {explicitPic.softech_pic && <span className="font-mono text-xs text-gray-500">PIC: {explicitPic.softech_pic}</span>}
                {explicitPic.phone && <span className="text-xs text-gray-500">☎ {explicitPic.phone}</span>}
                <button onClick={() => P.setPicCustomer(null)} className="ml-auto text-gray-400 hover:text-red-500">✕</button>
              </div>
            ) : accountPic ? (
              <div className="flex-1 flex items-center gap-2 bg-sky-50 border border-sky-200 rounded px-2 py-1.5 text-sm">
                <span className="text-sky-700 text-[11px]">↳ من الحساب</span>
                <span className="font-medium">{accountPic.name}</span>
                <span className="font-mono text-xs text-gray-500">PIC: {accountPic.softech_pic}</span>
              </div>
            ) : (
              <div className={`flex-1 text-sm rounded px-2 py-1.5 border ${picRequired ? 'text-amber-700 bg-amber-50 border-amber-200' : 'text-gray-500 bg-gray-50 border-gray-200'}`}>
                {picRequired ? 'لم يُحدد عميل PIC بعد' : 'اختر الشخص لسحب مشترياته السابقة واقتراحاته'}
              </div>
            )}
            <button onClick={onOpenPic} className="px-3 py-1.5 rounded text-white text-sm shrink-0" style={{ background: '#022871' }}>
              {accountPic ? '🔍 شخص مختلف' : '🔍 بحث / اختيار / إضافة'}
            </button>
          </div>
        </div>
      )}

      {/* discount-source hint */}
      <div className="text-[11px] text-gray-500 col-span-full flex gap-3">
        {P.typeCfg && <span>الخصم من: {P.typeCfg.discount === 'b2b' ? 'تعاقد B2B' : 'حدود الخصم + الصنف'}</span>}
        {pic?.fromAccount && <span className="text-gray-400">العميل الفعلي = الحساب نفسه (فرد)</span>}
      </div>
    </div>
  )
}
