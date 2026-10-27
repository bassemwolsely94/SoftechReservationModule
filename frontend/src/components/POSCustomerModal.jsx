import { useState, useEffect } from 'react'
import api, { customersApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'

/*
 * POSCustomerModal — the SOFTECH "Individual Customers Pop-Up" reached from the POS
 * إسم العميل « … » button. Two tabs:
 *   • إستعلام (Query)   — search by name / phone / PIC → results grid → select
 *   • إضافة جديد (Add)  — quick-create a customer (reuses the customers CRUD API)
 * The exhaustive clinical/contract master (multiple phones, blood type, classification,
 * age stage, …) lives in the Customers module; the fields persisted here are the ones
 * the POS needs to identify/bill the customer.
 */

const blankForm = () => ({
  name: '', phone: '', phone_alt: '', email: '', address: '',
  date_of_birth: '', discount_percent: 0, special_discount: false,
  point_system: false, contract_max: '', pic: '',
  area: '', district: '', landmark: '',
})

export default function POSCustomerModal({ onSelect, onClose, initialPhone = '' }) {
  // initialPhone (call screen-pop «عميل جديد بهذا الرقم»): open on the add form with the phone filled
  const [tab, setTab] = useState(initialPhone ? 'add' : 'query')
  useHelpTab(tab)
  const [q, setQ] = useState('')
  const [rows, setRows] = useState([])
  const [searching, setSearching] = useState(false)
  const [form, setForm] = useState(() => ({ ...blankForm(), phone: initialPhone }))
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [phoneHits, setPhoneHits] = useState([])   // existing customers with this phone
  const [nameHits, setNameHits] = useState([])     // existing customers with a similar name

  // Phone first: from 8 digits, offer the existing customers before anything is created.
  const phoneDigits = form.phone.replace(/\D/g, '')
  useEffect(() => {
    if (tab !== 'add' || phoneDigits.length < 8) { setPhoneHits([]); return }
    let live = true
    const t = setTimeout(async () => {
      try { const r = await customersApi.recognize(form.phone); if (live) setPhoneHits(r.data.matches || []) }
      catch { if (live) setPhoneHits([]) }
    }, 250)
    return () => { live = false; clearTimeout(t) }
  }, [form.phone, tab])

  useEffect(() => {
    const n = form.name.trim()
    if (tab !== 'add' || n.length < 3) { setNameHits([]); return }
    let live = true
    const t = setTimeout(async () => {
      try { const r = await customersApi.recognize(n); if (live) setNameHits(r.data.matches || []) }
      catch { if (live) setNameHits([]) }
    }, 300)
    return () => { live = false; clearTimeout(t) }
  }, [form.name, tab])

  function useExisting(c) {
    onSelect({ id: c.id, name: c.name, phone: c.phone, softech_pic: c.softech_pic })
    onClose()
  }

  async function runQuery() {
    setSearching(true); setErr('')
    try {
      const r = await customersApi.list({ search: q, page_size: 25 })
      setRows(r.data.results || r.data)
    } catch (e) { setErr('تعذّر تنفيذ الاستعلام.') } finally { setSearching(false) }
  }

  async function save() {
    if (!form.name.trim()) { setErr('الإسم مطلوب.'); return }
    if (phoneDigits.length < 8) { setErr('رقم التليفون مطلوب.'); return }
    setSaving(true); setErr('')
    try {
      const { data } = await api.post('/customers/', {
        name: form.name, phone: form.phone, phone_alt: form.phone_alt,
        email: form.email,
        address: [form.address, form.landmark, form.district, form.area].filter(Boolean).join('، '),
        date_of_birth: form.date_of_birth || null,
      })
      // best-effort: persist the special discount if entered (PATCH, ignore failure)
      if (Number(form.discount_percent) > 0) {
        try { await api.patch(`/customers/${data.id}/`, { discount_percent: Number(form.discount_percent) }) } catch {}
      }
      onSelect({ id: data.id, name: data.name, phone: data.phone, softech_pic: data.softech_pic || form.pic })
      onClose()
    } catch (e) {
      setErr('تعذّر حفظ العميل: ' + (e.response?.data?.detail || JSON.stringify(e.response?.data || {}) || e.message))
    } finally { setSaving(false) }
  }

  const F = (k, v) => setForm({ ...form, [k]: v })

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-[60]" onClick={onClose}>
      <div dir="rtl" className="bg-white rounded-lg w-[52rem] max-h-[88vh] overflow-auto" onClick={e => e.stopPropagation()}>
        <div className="px-4 py-2 border-b bg-gray-50 font-bold">Individual Customers Pop-Up — بحث / إضافة عميل</div>
        <div className="flex border-b">
          <Tab id="query" tab={tab} setTab={setTab} label="إستعلام" />
          <Tab id="add" tab={tab} setTab={setTab} label="إضافة جديد / تعديل" />
        </div>

        {err && <div className="m-3 text-xs bg-red-50 text-red-700 rounded p-2">{err}</div>}

        {tab === 'query' && (
          <div className="p-3">
            <div className="flex gap-2 mb-3">
              <input autoFocus value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && runQuery()}
                     placeholder="بحث بالإسم أو رقم التليفون أو PIC…" className="flex-1 border rounded px-3 py-2" />
              <button onClick={runQuery} disabled={searching} className="px-4 rounded bg-blue-600 text-white">{searching ? '...' : 'تنفيذ إستعلام (F8)'}</button>
            </div>
            <table className="w-full text-xs border">
              <thead className="bg-sky-700 text-white">
                <tr><th className="px-2 py-1">الإسم</th><th>PIC</th><th>اللقب</th><th>رقم التليفون</th><th>النوع</th><th></th></tr>
              </thead>
              <tbody>
                {rows.map(c => (
                  <tr key={c.id} className="border-b hover:bg-indigo-50">
                    <td className="px-2 py-1">{c.name}</td>
                    <td className="text-center font-mono">{c.softech_pic || '—'}</td>
                    <td className="text-center">{c.person_type_label || ''}</td>
                    <td className="text-center">{c.phone || '—'}</td>
                    <td className="text-center">{c.person_classif_label || ''}</td>
                    <td className="text-center"><button onClick={() => { onSelect({ id: c.id, name: c.name, phone: c.phone, softech_pic: c.softech_pic }); onClose() }} className="text-blue-600">اختيار</button></td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan="6" className="text-center text-gray-400 py-6">نفّذ استعلاماً لعرض العملاء</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'add' && (
          <div className="p-4 grid grid-cols-3 gap-x-4 gap-y-2">
            <Sec>البيانات الأساسية</Sec>
            <L l="رقم التليفون *">
              <input autoFocus value={form.phone} onChange={e => F('phone', e.target.value)} className="cin" inputMode="tel" />
            </L>
            <L l="الإسم *"><input value={form.name} onChange={e => F('name', e.target.value)} className="cin" /></L>
            <L l="PIC"><input value={form.pic} onChange={e => F('pic', e.target.value)} className="cin" placeholder="يُسند من SOFTECH" /></L>
            <Hits rows={phoneHits} title="عملاء بنفس الرقم — استخدم الموجود بدل إنشاء مكرر" onUse={useExisting} />
            <Hits rows={phoneHits.length ? [] : nameHits} title="أسماء مشابهة" onUse={useExisting} />

            <Sec>العنوان (اختياري)</Sec>
            <L l="المنطقة"><AddrInput field="area" value={form.area} onChange={v => F('area', v)} /></L>
            <L l="الحي"><AddrInput field="district" area={form.area} value={form.district} onChange={v => F('district', v)} /></L>
            <L l="علامة مميزة / شارع"><AddrInput field="landmark" area={form.area} value={form.landmark} onChange={v => F('landmark', v)} /></L>
            <L l="العنوان التفصيلي" wide3><input value={form.address} onChange={e => F('address', e.target.value)} className="cin" /></L>

            <Sec>بيانات إضافية (اختياري)</Sec>
            <L l="رقم تليفون آخر"><input value={form.phone_alt} onChange={e => F('phone_alt', e.target.value)} className="cin" /></L>
            <L l="بريد إلكترونى"><input value={form.email} onChange={e => F('email', e.target.value)} className="cin" /></L>
            <L l="تاريخ الميلاد"><input type="date" value={form.date_of_birth} onChange={e => F('date_of_birth', e.target.value)} className="cin" /></L>

            <Sec>نظام النقاط والخصم / التعاقد</Sec>
            <L l="خصم خاص %"><input type="number" step="0.5" value={form.discount_percent} onChange={e => F('discount_percent', e.target.value)} className="cin" /></L>
            <L l="أقصى مبلغ تحمّل (تعاقد)"><input type="number" step="any" value={form.contract_max} onChange={e => F('contract_max', e.target.value)} className="cin" /></L>
            <div className="flex items-end gap-3 text-xs">
              <label className="flex items-center gap-1"><input type="checkbox" checked={form.special_discount} onChange={e => F('special_discount', e.target.checked)} /> خصم خاص</label>
              <label className="flex items-center gap-1"><input type="checkbox" checked={form.point_system} onChange={e => F('point_system', e.target.checked)} /> نظام نقاط</label>
            </div>
            <div className="col-span-3 text-[11px] text-gray-500">
              الحقول الإكلينيكية الكاملة (فصيلة الدم، تليفونات متعددة، التصنيف…) تُدار من وحدة العملاء.
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 px-4 py-3 border-t bg-gray-50">
          <button onClick={onClose} className="px-4 py-1.5 rounded border">خروج (Ctrl+E)</button>
          {tab === 'add' && <button onClick={save} disabled={saving} className="px-4 py-1.5 rounded bg-green-600 text-white">{saving ? '...' : 'تخزين (Ctrl+S)'}</button>}
        </div>
        <style>{`.cin{width:100%;border:1px solid #d1d5db;border-radius:.3rem;padding:.25rem .5rem;font-size:12px}`}</style>
      </div>
    </div>
  )
}

function Tab({ id, tab, setTab, label }) {
  return <button onClick={() => setTab(id)} className={`px-4 py-2 text-sm ${tab === id ? 'border-b-2 border-indigo-600 text-indigo-700 font-semibold' : 'text-gray-500'}`}>{label}</button>
}
function Sec({ children }) { return <div className="col-span-3 text-xs font-bold text-indigo-700 border-b mt-1">{children}</div> }
function L({ l, children, wide3 }) { return <label className={`text-[11px] text-gray-600 block ${wide3 ? 'col-span-3' : ''}`}>{l}{children}</label> }

// Existing-customer matches shown above the form so the cashier reuses a PIC instead of duplicating.
function Hits({ rows, title, onUse }) {
  if (!rows.length) return null
  return (
    <div className="col-span-3 rounded border border-amber-300 bg-amber-50 p-2 text-xs">
      <div className="font-semibold text-amber-800 mb-1">{title}</div>
      {rows.map(c => (
        <div key={c.id} className="flex items-center gap-3 py-0.5">
          <span className="flex-1">{c.name}</span>
          <span className="font-mono text-gray-600">{c.softech_pic || '—'}</span>
          <span className="text-gray-500">{c.phone || ''}</span>
          <button type="button" onClick={() => onUse(c)} className="px-2 py-0.5 rounded bg-blue-600 text-white">استخدم هذا العميل</button>
        </div>
      ))}
    </div>
  )
}

// Text input that suggests values already stored (area / district / landmark).
function AddrInput({ field, value, onChange, area = '' }) {
  const [opts, setOpts] = useState([])
  const listId = `addr-${field}`
  useEffect(() => {
    let live = true
    const t = setTimeout(async () => {
      try { const r = await customersApi.addressSuggest(field, value, area); if (live) setOpts(r.data.results || []) }
      catch { if (live) setOpts([]) }
    }, 200)
    return () => { live = false; clearTimeout(t) }
  }, [field, value, area])
  return (
    <>
      <input value={value} onChange={e => onChange(e.target.value)} list={listId} className="cin" />
      <datalist id={listId}>{opts.map(o => <option key={o} value={o} />)}</datalist>
    </>
  )
}
