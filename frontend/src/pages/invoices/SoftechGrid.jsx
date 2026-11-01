/**
 * SoftechGrid.jsx — the editable SofTech-mirror grid for a supplier invoice.
 *
 * Columns mirror the native «مشتريات من الموردين» screen (RTL). The BACKEND owns
 * every number: editing a cell sends it to /recompute-line/ and the server returns
 * the consistent row (base price, cost ⟷ discounts, VAT, total) exactly as SofTech
 * would. On top of SofTech it adds: the catalog match + one-click re-pick, the
 * review / new-price flags, and inline FOC (10+1 → two lines).
 *
 * Edits recompute live (debounced) and persist on blur (updateLine).
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../hooks/useGridKeyboard'
import { invoicesApi } from '../../api/client'
import ItemSearchInput from '../../components/ItemSearchInput'

const n = (v, d = 3) => (v === null || v === undefined || v === '' ? '' : Number(v).toFixed(d))

// Stored expiry is YYYY-MM-DD; SofTech shows and takes it day first.
const fmtExpiry = v => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v || '')
  return m ? `${m[3]}/${m[2]}/${m[1]}` : (v || '')
}

// SofTech-style cell movement inside the grid: ↑/↓ stay in the same column,
// Tab / Shift+Tab walk the row's editable cells and wrap to the next / previous line.
// Only inputs marked data-nav take part (buttons and pickers are skipped).
function navKeyDown(e) {
  const t = e.target
  if (!(t instanceof HTMLInputElement) || !t.dataset.nav) return
  const table = t.closest('table')
  if (!table) return
  if (e.key === 'Tab') {
    const all = Array.from(table.querySelectorAll('input[data-nav]'))
    const next = all[all.indexOf(t) + (e.shiftKey ? -1 : 1)]
    if (next) { e.preventDefault(); next.focus() }
    return
  }
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
  const tr = t.closest('tr[data-line]')
  if (!tr) return
  let td = t.closest('td')
  while (td && td.parentElement !== tr) td = td.parentElement?.closest('td')
  const col = Array.from(tr.children).indexOf(td)
  const lines = Array.from(table.querySelectorAll('tr[data-line]'))
  const target = lines[lines.indexOf(tr) + (e.key === 'ArrowDown' ? 1 : -1)]
  const inp = target?.children[col]?.querySelector('input[data-nav]')
  e.preventDefault()
  inp?.focus()
}

const selectOnFocus = e => e.target.select?.()

// Grid-cell key → the model field saved via updateLine.
const SAVE_FIELD = {
  public_price: 'public_price', quantity: 'quantity', disc_pct: 'discount_pct',
  extra_disc_pct: 'extra_discount_pct', special_disc_pct: 'special_discount_pct',
  vat_pct: 'vat_pct', net_cost: 'unit_price', bonus_qty: 'bonus_qty',
}
// NOTE: unit_price stores the NET (before the folded distributor margin). Saving
// unit_cost here would store net + margin and add the margin again on the next load.

// Numeric cell. MUST be a module-level component, NOT defined inside SoftechGrid:
// when it was nested, every keystroke re-rendered the grid, React saw a brand-new
// component type and remounted the <input>, so it lost focus after a single digit
// (the "can only type one digit then it freezes" bug).
function Cell({ row, k, w = 'w-20', dec = 3, ro = false, editable, onEdit, onSave }) {
  const raw = row._rawEdit?.[k]
  const val = raw !== undefined ? raw : (row.cells[k] ?? '')
  if (ro || !editable) {
    return <td className="px-2 py-1 text-center tabular-nums text-gray-600">{n(row.cells[k], dec)}</td>
  }
  return (
    <td className="px-1 py-0.5">
      <input
        className={`${w} text-center tabular-nums rounded border border-gray-200 bg-white px-1 py-0.5 text-sm
          focus:outline-none focus:ring-2 focus:ring-brand-400 focus:border-brand-400`}
        value={raw !== undefined ? raw : n(val, dec)}
        onChange={e => onEdit(row.line_id, k, e.target.value)}
        onBlur={() => onSave(row.line_id)}
        onFocus={selectOnFocus}
        data-nav="1"
        inputMode="decimal"
      />
    </td>
  )
}

// Editable numeric cell for a value that lives on the ROW (not in cells) and changes
// the posted cost — net cost (→unit_price) or the two margins. Saves on blur and the
// parent reloads so cost-to-post and totals recompute server-side. Module-level so the
// input keeps focus while typing.
function NumEditCell({ row, field, value, w = 'w-16', dec = 2, editable, onSaveNum, title }) {
  const [v, setV] = useState(value == null ? '' : String(value))
  useEffect(() => { setV(value == null ? '' : String(value)) }, [value])
  if (!editable) {
    return <td className="px-2 py-1 text-center tabular-nums text-gray-600" title={title}>{n(value, dec)}</td>
  }
  return (
    <td className="px-1 py-0.5" title={title}>
      <input
        className={`${w} text-center tabular-nums rounded border border-gray-200 bg-white px-1 py-0.5 text-sm
          focus:outline-none focus:ring-2 focus:ring-brand-400 focus:border-brand-400`}
        value={v}
        onChange={e => setV(e.target.value)}
        onBlur={() => { if (String(value ?? '') !== v) onSaveNum(row.line_id, field, v) }}
        onFocus={selectOnFocus}
        data-nav="1"
        inputMode="decimal"
      />
    </td>
  )
}

// Free-text cell (batch number, expiry date — both CharFields). Saved directly via
// updateLine on blur (these are not recomputed numeric cells). Also module-level so it
// keeps focus while typing. Local state so the field is freely editable mid-typing.
function TextCell({ row, field, value, placeholder, editable, onSaveText, display = x => x }) {
  const shown = display(value ?? '')
  const [v, setV] = useState(shown)
  useEffect(() => { setV(shown) }, [shown])
  const err = row._err?.[field]
  if (!editable) {
    return <td className="px-2 py-1 text-center text-xs text-gray-500 font-mono">{shown || '—'}</td>
  }
  return (
    <td className="px-1 py-0.5">
      <input
        type="text"
        value={v}
        placeholder={placeholder}
        onChange={e => setV(e.target.value)}
        onBlur={() => { if ((v ?? '') !== shown) onSaveText(row.line_id, field, v) }}
        onFocus={selectOnFocus}
        data-nav="1"
        title={err || undefined}
        className={`w-24 text-center text-xs font-mono rounded border ${err ? 'border-red-400 bg-red-50' : 'border-gray-200 bg-white'} px-1 py-0.5
          focus:outline-none focus:ring-2 focus:ring-brand-400 focus:border-brand-400`}
      />
    </td>
  )
}

export default function SoftechGrid({ invoiceId, editable = true, onChanged }) {
  const [rows, setRows]   = useState(null)
  const [busy, setBusy]   = useState(false)
  const [summary, setSummary]   = useState(null)   // {total_pre_tax, tax_outside_cost, total_final}
  const [declared, setDeclared] = useState(null)   // printed invoice total (paper)
  const [pickFor, setPickFor] = useState(null)   // line_id whose picker is open
  const timers = useRef({})

  const load = useCallback(async () => {
    const r = await invoicesApi.grid(invoiceId)
    setRows(r.data.rows)
    setSummary(r.data.tax_summary || null)
    setDeclared(r.data.declared_total ?? null)
  }, [invoiceId])

  // refresh just the totals (no SOFTECH stock round-trip) after an edit
  const refreshTotals = useCallback(async () => {
    try {
      const r = await invoicesApi.grid(invoiceId, { stock: 0 })
      setSummary(r.data.tax_summary || null)
    } catch { /* non-fatal */ }
  }, [invoiceId])

  useEffect(() => { load() }, [load])

  // live recompute (debounced) when a numeric cell changes
  const onEdit = (lineId, key, value) => {
    setRows(rs => rs.map(row => {
      if (row.line_id !== lineId) return row
      const cells = { ...row.cells, [key]: value === '' ? 0 : Number(value) }
      return { ...row, cells, _dirty: true, _editing: key, _rawEdit: { ...(row._rawEdit || {}), [key]: value } }
    }))
    clearTimeout(timers.current[lineId])
    timers.current[lineId] = setTimeout(async () => {
      const row = (rows || []).find(r => r.line_id === lineId)
      const cells = { ...(row?.cells || {}), [key]: value === '' ? 0 : Number(value) }
      try {
        const r = await invoicesApi.recomputeLine(invoiceId, { cells, changed: key, tax_rate: cells.tax_rate })
        setRows(rs => rs.map(x => x.line_id === lineId
          ? { ...x, cells: r.data.cells, foc: r.data.foc, _dirty: true } : x))
      } catch { /* keep local */ }
    }, 250)
  }

  // persist on blur
  const save = async (lineId) => {
    const row = (rows || []).find(r => r.line_id === lineId)
    if (!row || !row._dirty) return
    const payload = {}
    for (const [k, f] of Object.entries(SAVE_FIELD)) payload[f] = row.cells[k] ?? 0
    setBusy(true)
    try {
      await invoicesApi.updateLine(invoiceId, lineId, payload)
      setRows(rs => rs.map(x => x.line_id === lineId ? { ...x, _dirty: false, _rawEdit: {}, _saveErr: null } : x))
      refreshTotals()
      onChanged?.()
    } catch (e) {
      // never lose an edit silently: keep the row dirty and say why it wasn't saved
      const d = e?.response?.data
      const msg = d && typeof d === 'object'
        ? Object.entries(d).map(([k, v]) => `${k}: ${[].concat(v).join(' ')}`).join(' · ')
        : 'تعذّر الحفظ'
      setRows(rs => rs.map(x => x.line_id === lineId ? { ...x, _saveErr: msg } : x))
    } finally { setBusy(false) }
  }

  const pick = async (lineId, item) => {
    await invoicesApi.updateLine(invoiceId, lineId, { item: item.item_id })
    setPickFor(null)
    load()
    onChanged?.()
  }

  // Save a free-text field (batch number / expiry date) directly — no recompute.
  const saveText = async (lineId, field, value) => {
    setBusy(true)
    try {
      const r = await invoicesApi.updateLine(invoiceId, lineId, { [field]: value })
      const saved = r?.data?.[field] ?? value
      setRows(rs => rs.map(x => x.line_id === lineId
        ? { ...x, [field]: saved, _err: { ...(x._err || {}), [field]: null } } : x))
      onChanged?.()
    } catch (e) {
      const msg = e?.response?.data?.[field]?.[0] || 'تعذّر الحفظ'
      setRows(rs => rs.map(x => x.line_id === lineId ? { ...x, _err: { ...(x._err || {}), [field]: msg } } : x))
    } finally { setBusy(false) }
  }

  // Reload rows + totals from the server (recomputes cost-to-post / margins / totals),
  // without the SOFTECH stock round-trip.
  const reloadRows = useCallback(async () => {
    try {
      const r = await invoicesApi.grid(invoiceId, { stock: 0 })
      setRows(rs => (r.data.rows || []).map(nr => {
        const old = (rs || []).find(o => o.line_id === nr.line_id)
        return old?.current_stock != null ? { ...nr, current_stock: old.current_stock } : nr
      }))
      setSummary(r.data.tax_summary || null)
    } catch { /* non-fatal */ }
  }, [invoiceId])

  // Save a numeric field that changes the posted cost (net cost / distributor margin /
  // pharmacist margin), then reload so cost-to-post and totals recompute server-side.
  const saveNum = async (lineId, field, value) => {
    setBusy(true)
    try {
      await invoicesApi.updateLine(invoiceId, lineId, { [field]: value === '' ? 0 : Number(value) })
      await reloadRows()
      onChanged?.()
    } finally { setBusy(false) }
  }

  const setPriceAction = async (lineId, action) => {
    await invoicesApi.updateLine(invoiceId, lineId, { price_action: action })
    setRows(rs => rs.map(x => x.line_id === lineId ? { ...x, price_action: action } : x))
  }

  // الضريبة من التكلفة checkbox: toggle the VAT base (cost vs base price), recompute, save
  const toggleTaxFromCost = async (lineId) => {
    const row = (rows || []).find(r => r.line_id === lineId)
    const next = !(row?.cells?.tax_from_cost)
    const cells = { ...(row?.cells || {}), tax_from_cost: next }
    setRows(rs => rs.map(x => x.line_id === lineId ? { ...x, cells, _dirty: true } : x))
    try {
      const r = await invoicesApi.recomputeLine(invoiceId, { cells, changed: 'tax_from_cost' })
      setRows(rs => rs.map(x => x.line_id === lineId ? { ...x, cells: r.data.cells } : x))
      await invoicesApi.updateLine(invoiceId, lineId, { tax_from_cost: next })
      onChanged?.()
    } catch { /* keep local */ }
  }

  // keyboard-first review: ↑↓ navigate, M open item picker, Enter save + advance
  const kb = useGridKeyboard({
    rows: rows || [], getKey: r => r.line_id, enabled: editable,
    onOpen: r => setPickFor(r.line_id),
    onConfirm: r => save(r.line_id), advanceOnConfirm: true,
  })

  if (!rows) return <div className="py-10 text-center text-gray-400 animate-pulse">جارٍ تحميل الجدول…</div>

  return (
    <div {...kb.containerProps}
      className={`overflow-x-auto border border-gray-200 rounded-xl ${kb.containerProps.className}`} dir="rtl">
      {editable && (
        <div className="px-3 py-1 flex items-center justify-between border-b border-gray-100">
          <span className="text-[11px] text-gray-400">
            داخل الخانة: ↑↓ نفس العمود · Tab التالي · Shift+Tab السابق — {GRID_KEYS_HINT}
          </span>
          {(() => {
            const need = rows.filter(r => r.needs_review ?? (r.match_review || r.needs_pick || !r.item_id)).length
            return need > 0
              ? <span className="text-[11px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">⚠ {need} من {rows.length} يحتاج مراجعة</span>
              : <span className="text-[11px] font-medium text-green-700 bg-green-50 border border-green-200 rounded-full px-2 py-0.5">✓ كل السطور جاهزة</span>
          })()}
        </div>
      )}
      <table className="min-w-full text-sm border-collapse" onKeyDown={navKeyDown}>
        <thead className="bg-brand-700 text-white sticky top-0 z-10">
          <tr className="text-[11px] whitespace-nowrap">
            <th className="px-2 py-2 font-semibold">كود</th>
            <th className="px-2 py-2 font-semibold text-right">اسم الصنف</th>
            <th className="px-2 py-2 font-semibold" title="رصيد المخزن الحالي">رصيد حالي</th>
            <th className="px-2 py-2 font-semibold">الكمية</th>
            <th className="px-2 py-2 font-semibold">هدية</th>
            <th className="px-2 py-2 font-semibold">الصلاحية</th>
            <th className="px-2 py-2 font-semibold">الباتش</th>
            <th className="px-2 py-2 font-semibold">سعر الجمهور</th>
            <th className="px-2 py-2 font-semibold">السعر الأساسي</th>
            <th className="px-2 py-2 font-semibold">خصم أساسي %</th>
            <th className="px-2 py-2 font-semibold">خصم إضافي %</th>
            <th className="px-2 py-2 font-semibold">خصم خاص %</th>
            <th className="px-2 py-2 font-semibold">ض.ق.م %</th>
            <th className="px-2 py-2 font-semibold">مبلغ الضريبة</th>
            <th className="px-2 py-2 font-semibold" title="الضريبة محسوبة من التكلفة">ض.تكلفة</th>
            <th className="px-2 py-2 font-semibold" title="تكلفة الوحدة كما قُرئت من الفاتورة (صافي بدون ضريبة وبدون هامش)">تكلفة الوحدة (صافي)</th>
            <th className="px-2 py-2 font-semibold text-amber-200" title="تكلفة الوحدة + هامش الموزع — هذه هي القيمة التي تُرحَّل إلى SofTech">التكلفة للترحيل ⇪</th>
            <th className="px-2 py-2 font-semibold">إجمالي الوحدة (بالضريبة)</th>
            <th className="px-2 py-2 font-semibold">الإجمالي بدون ضريبة</th>
            <th className="px-2 py-2 font-semibold">الإجمالي</th>
            <th className="px-2 py-2 font-semibold text-indigo-200" title="هامش ربح ثابت للصيدلى — قابل للتعديل، عرض فقط لا يُرحَّل">هامش صيدلى</th>
            <th className="px-2 py-2 font-semibold text-amber-200" title="هامش ربح ثابت للموزع — قابل للتعديل؛ يُضاف لتكلفة الترحيل لموردي الهامش (مثل فارما أوفرسيز)، وعرض فقط لغيرهم (مثل رامكو)">هامش موزع</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(row => {
            const flagged = row.needs_review ?? (row.match_review || row.needs_pick || !row.item_id)
            const priceChanged = row.price?.changed
            const rp = kb.rowProps(row)
            return (
              <>
                <tr key={row.line_id} data-line={row.line_id} ref={rp.ref} onMouseDown={rp.onMouseDown} data-kb-active={rp['data-kb-active']}
                  className={`border-t border-gray-100 ${flagged ? 'bg-amber-50/50' : row._dirty ? 'bg-blue-50/40' : 'bg-white'} ${rp.className}`}>
                  <td className="px-2 py-1 text-center font-mono text-xs text-gray-500">{row.softech_id || '—'}</td>
                  <td className="px-2 py-1 text-right max-w-[22rem]">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {(row.needs_review ?? (row.needs_pick || !row.item_id)) &&
                        <span title={(row.review_reasons || ['يحتاج مراجعة']).join('، ')}>⚠️</span>}
                      <span className="text-gray-800">{row.item_name}</span>
                      {row.item_id && typeof row.match_score === 'number' && (
                        <span className={`text-[10px] px-1 rounded ${row.match_score >= 0.85 ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                          {Math.round(row.match_score * 100)}%
                        </span>
                      )}
                      {editable && (
                        <button onClick={() => setPickFor(pickFor === row.line_id ? null : row.line_id)}
                          className="text-[11px] text-brand-600 hover:text-brand-700 font-medium">
                          {row.item_id ? 'تغيير' : '🔍 اختر'}
                        </button>
                      )}
                      <div className="text-[10px] text-gray-400 w-full truncate">{row.raw_name}</div>
                    </div>
                  </td>
                  <td className="px-2 py-1 text-center text-xs text-gray-400 tabular-nums">{row.current_stock != null ? n(row.current_stock, 0) : '—'}</td>
                  <Cell row={row} k="quantity" w="w-16" dec={0} editable={editable} onEdit={onEdit} onSave={save} />
                  <Cell row={row} k="bonus_qty" w="w-12" dec={0} editable={editable} onEdit={onEdit} onSave={save} />
                  <TextCell row={row} field="expiry_date" value={row.expiry_date} display={fmtExpiry} placeholder="يوم/شهر/سنة" editable={editable} onSaveText={saveText} />
                  <TextCell row={row} field="batch_number" value={row.batch_number} placeholder="الباتش" editable={editable} onSaveText={saveText} />
                  <td className="px-1 py-0.5">
                    <Cell row={row} k="public_price" editable={editable} onEdit={onEdit} onSave={save} />
                    {priceChanged && (
                      <div className="mt-0.5 flex items-center gap-1 justify-center">
                        <span className="text-[9px] text-gray-400 line-through">{n(row.price.catalog_price, 2)}</span>
                        <button onClick={() => setPriceAction(row.line_id, row.price_action === 'use_new' ? 'keep_old' : 'use_new')}
                          className={`text-[9px] px-1 rounded ${row.price_action === 'use_new' ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-500'}`}
                          title="تحديث سعر البيع للجمهور في الكتالوج (قرار فقط — يُنفَّذ لاحقاً باعتماد)">
                          {row.price_action === 'use_new' ? '✓ سعر جديد' : 'سعر جديد؟'}
                        </button>
                      </div>
                    )}
                  </td>
                  <Cell row={row} k="base_price" dec={3} ro editable={editable} onEdit={onEdit} onSave={save} />
                  <Cell row={row} k="disc_pct" w="w-14" dec={2} editable={editable} onEdit={onEdit} onSave={save} />
                  <Cell row={row} k="extra_disc_pct" w="w-14" dec={2} editable={editable} onEdit={onEdit} onSave={save} />
                  <Cell row={row} k="special_disc_pct" w="w-14" dec={2} editable={editable} onEdit={onEdit} onSave={save} />
                  <Cell row={row} k="vat_pct" w="w-14" dec={2} editable={editable} onEdit={onEdit} onSave={save} />
                  <Cell row={row} k="vat_amount" w="w-16" dec={2} editable={editable} onEdit={onEdit} onSave={save} />
                  <td className="px-1 py-1 text-center">
                    {editable
                      ? <input type="checkbox" checked={!!row.cells.tax_from_cost} onChange={() => toggleTaxFromCost(row.line_id)} className="accent-brand-600" />
                      : <span>{row.cells.tax_from_cost ? '✓' : ''}</span>}
                  </td>
                  {/* تكلفة الوحدة (صافي) — live: editing it back-solves خصم أساسي, editing a
                      discount updates it (server recompute). Saves unit_price. */}
                  <Cell row={row} k="net_cost" dec={3} editable={editable} onEdit={onEdit} onSave={save} />
                  {/* التكلفة للترحيل = net + distributor margin — the value posted to SofTech */}
                  <td className="px-2 py-1 text-center font-bold tabular-nums text-amber-700 bg-amber-50/60"
                    title="تكلفة الوحدة + هامش الموزع — هذه القيمة هي التي تُرحَّل إلى SofTech">
                    {n(row.cells.unit_cost ?? row.cost_to_post, 3)}
                  </td>
                  <Cell row={row} k="unit_cost_incl_tax" dec={3} ro editable={editable} onEdit={onEdit} onSave={save} />
                  <td className="px-2 py-1 text-center tabular-nums text-gray-600">{n(row.cells.cost_total, 2)}</td>
                  <td className="px-2 py-1 text-center font-semibold tabular-nums text-gray-800">{n(row.cells.cost_total_incl_tax, 2)}</td>
                  <NumEditCell row={row} field="pharmacist_margin_amt" value={row.pharmacist_margin_amt} w="w-14" dec={2}
                    editable={editable} onSaveNum={saveNum} title="هامش ثابت للصيدلى — عرض فقط، لا يُرحَّل" />
                  <NumEditCell row={row} field="distributor_margin_amt" value={row.distributor_margin_amt} w="w-14" dec={2}
                    editable={editable} onSaveNum={saveNum} title="هامش ثابت للموزع — يُضاف لتكلفة الترحيل لموردي الهامش" />
                </tr>
                {row._saveErr && (
                  <tr className="bg-red-50 text-[11px] text-red-700 border-t border-red-200">
                    <td></td>
                    <td className="px-2 py-0.5 text-right" colSpan={21}>
                      ⛔ لم يُحفظ هذا السطر — {row._saveErr}
                    </td>
                  </tr>
                )}
                {row.bonus_qty > 0 && (
                  <tr className="bg-emerald-50/40 text-[11px] text-emerald-700 border-t border-dashed border-emerald-200">
                    <td></td>
                    <td className="px-2 py-0.5 text-right" colSpan={21}>
                      ↳ سيُضاف سطر بونص: {n(row.bonus_qty, 0)} عبوة مجاناً (تكلفة 0) — يُرحَّل كسطرين في SofTech
                    </td>
                  </tr>
                )}
                {pickFor === row.line_id && (
                  <tr><td colSpan={22} className="px-3 py-2 bg-gray-50 border-t border-gray-200">
                    <ItemSearchInput onSelect={item => pick(row.line_id, item)}
                      placeholder="ابحث واختر الصنف الصحيح…" />
                  </td></tr>
                )}
              </>
            )
          })}
        </tbody>
      </table>
      {/* SofTech bottom totals (Method 1 — VAT outside cost; distributor margin added
          for هامش vendors), matched to the native «مشتريات من الموردين» footer */}
      {summary && (
        <div className="px-3 py-2 border-t border-gray-200 bg-gray-50 flex flex-wrap items-center justify-end gap-x-6 gap-y-1 text-xs">
          <span className="text-gray-500">الإجمالي بدون ضريبة: <strong className="tabular-nums text-gray-800">{n(summary.total_net, 2)}</strong></span>
          {summary.margin_total > 0 && (
            <span className="text-amber-600">قيمة هامش الموزع: <strong className="tabular-nums text-amber-700">{n(summary.margin_total, 2)}</strong></span>
          )}
          <span className="text-gray-500">خارج التكلفة (ض.ق.م): <strong className="tabular-nums text-gray-800">{n(summary.tax_outside_cost, 2)}</strong></span>
          <span className="text-gray-700 font-semibold">الإجمالي النهائي: <strong className="tabular-nums text-brand-700">{n(summary.total_final, 2)}</strong></span>
          {declared != null && (() => {
            const gap = Math.round((declared - summary.total_final) * 100) / 100
            const ok = Math.abs(gap) < 0.5
            return (
              <span className={`px-2 py-0.5 rounded-full font-medium ${ok ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}
                title="فاتورة الورق مقابل إجمالي SofTech">
                فاتورة الورق: {n(declared, 2)} {ok ? '✓ مطابق' : `(فرق ${n(gap, 2)})`}
              </span>
            )
          })()}
        </div>
      )}
      {busy && <div className="px-3 py-1 text-[11px] text-gray-400">جارٍ الحفظ…</div>}
    </div>
  )
}
