/**
 * «✍️ إدخال طلب» — a platform order typed in by hand (phone / platform panel). Keyboard-first, no modal:
 * pick item (the unified item search) → Enter → qty → Enter adds the line and returns to the search.
 * The server validates everything (store of the branch, item, qty, duplicates by platform order no.)
 * and runs the same intake as a platform webhook.
 */
import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { marketplaceApi } from '../../api/client'
import ItemSearchWidget from '../../components/ItemSearchWidget'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import useBranchLabels from '../../hooks/useBranchLabels'
import { PAY_LABEL, btnPrimary, btnQuiet, errText, inputCls, money, rowsOf, useChannels, useNotice } from './shared'

const EMPTY = { external_id: '', customer_name: '', customer_phone: '', address: '', payment_mode: 'platform_paid' }

export default function ManualIntakeTab({ canCreate, onSaved }) {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [noticeBar, toast] = useNotice()
  const channels = useChannels()
  const [channel, setChannel] = useState('')
  const [branch, setBranch] = useState('')
  const [form, setForm] = useState(EMPTY)
  const [lines, setLines] = useState([])
  const [picked, setPicked] = useState(null)
  const [qty, setQty] = useState('1')
  const [price, setPrice] = useState('')
  const searchBox = useRef(null)
  const qtyRef = useRef(null)
  const pickedId = useRef(null)   // the item a late price answer must still match

  const stores = useQuery({
    queryKey: ['marketplace', 'stores', { channel }],
    queryFn: () => marketplaceApi.stores({ channel }).then(r => rowsOf(r.data)),
    enabled: !!channel,
  })
  const activeStores = useMemo(() => (stores.data || []).filter(s => s.is_active), [stores.data])
  const table = useSortableRows(lines, { keys: ['name', 'qty', 'unit_price'] })

  const focusSearch = () => setTimeout(() => searchBox.current?.querySelector('input')?.focus(), 0)
  const pick = (item) => {
    if (!item?.item_id) { toast.error('الصنف غير موجود في كتالوج النظام — اختر صنفًا آخر.'); return }
    setPicked(item)
    pickedId.current = item.item_id
    setQty('1')
    setPrice('')
    setTimeout(() => { qtyRef.current?.focus(); qtyRef.current?.select() }, 0)
    // the platform price comes from the server (apps/marketplace/availability.platform_price)
    marketplaceApi.listings({ channel, item: item.item_id })
      .then(r => {
        if (pickedId.current !== item.item_id) return   // another item was picked meanwhile
        const row = rowsOf(r.data)[0]
        if (row) setPrice(p => (p === '' ? String(row.price) : p))
        else toast.error('الصنف غير مضاف لهذه المنصة — اكتب سعر المنصة يدويًا، والطلب لن يُقبل قبل إضافته واعتماده.')
      })
      .catch(() => {})
  }
  const addLine = () => {
    if (!picked) return
    const n = Number(qty)
    if (!(n > 0)) { toast.error('اكتب كمية صحيحة.'); return }
    if (price.trim() === '' || !(Number(price) >= 0)) { toast.error('اكتب سعر المنصة.'); return }
    setLines(ls => [...ls, { key: `${picked.item_id}-${Date.now()}`, item_id: picked.item_id, name: picked.name,
                             code: picked.softech_id, qty: String(n), unit_price: price.trim() }])
    setPicked(null)
    pickedId.current = null
    focusSearch()
  }
  const save = useMutation({
    mutationFn: () => marketplaceApi.manualOrder({
      ...form, channel: Number(channel), branch: Number(branch),
      lines: lines.map(l => ({ item_id: l.item_id, qty: l.qty, unit_price: l.unit_price })),
    }).then(r => r),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['marketplace', 'orders'] })
      toast.ok(r.status === 201 ? `تم حفظ الطلب ${r.data.external_id} — راجعه واقبله من تبويب الطلبات.`
        : `الطلب ${r.data.external_id} موجود من قبل — لم يُنشأ طلب جديد.`)
      setForm(EMPTY); setLines([])
      onSaved?.(r.data)
    },
    onError: (e) => toast.error(errText(e)),
  })
  const total = lines.reduce((s, l) => s + Number(l.qty) * Number(l.unit_price || 0), 0)
  const ready = canCreate && channel && branch && form.external_id.trim() && lines.length > 0
  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }))

  if (!canCreate) return <div className="py-10 text-center text-gray-500">إدخال الطلبات ليس ضمن صلاحياتك.</div>
  return (
    <div className="space-y-3 max-w-4xl" data-tour="marketplace-manual-form">
      {noticeBar}
      <div className="bg-white rounded-xl border p-3 grid sm:grid-cols-3 gap-2">
        <label className="flex flex-col text-sm text-gray-600">المنصة
          <select autoFocus value={channel} onChange={e => { setChannel(e.target.value); setBranch('') }} className={inputCls}>
            <option value="">اختر…</option>
            {(channels.data || []).filter(c => c.is_active).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-sm text-gray-600">الفرع
          <select value={branch} onChange={e => setBranch(e.target.value)} className={inputCls} disabled={!channel}>
            <option value="">{channel && !stores.isLoading && activeStores.length === 0 ? 'لا يوجد فرع مفعّل لهذه المنصة' : 'اختر…'}</option>
            {activeStores.map(s => <option key={s.id} value={s.branch}>{bl(s.branch_code) || s.branch_name}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-sm text-gray-600">رقم الطلب عند المنصة
          <input value={form.external_id} onChange={set('external_id')} className={inputCls} dir="ltr" />
        </label>
        <label className="flex flex-col text-sm text-gray-600">اسم العميل
          <input value={form.customer_name} onChange={set('customer_name')} className={inputCls} />
        </label>
        <label className="flex flex-col text-sm text-gray-600">هاتف العميل
          <input value={form.customer_phone} onChange={set('customer_phone')} className={inputCls} dir="ltr" inputMode="tel" />
        </label>
        <label className="flex flex-col text-sm text-gray-600">طريقة الدفع
          <select value={form.payment_mode} onChange={set('payment_mode')} className={inputCls}>
            {Object.entries(PAY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        <label className="flex flex-col text-sm text-gray-600 sm:col-span-3">العنوان
          <input value={form.address} onChange={set('address')} className={inputCls} />
        </label>
      </div>

      <div className="bg-white rounded-xl border p-3 space-y-2">
        <div className="flex flex-wrap items-end gap-2">
          <div ref={searchBox} className="flex-1 min-w-[16rem]">
            <ItemSearchWidget mode="list" onSelect={pick} branchId={branch ? Number(branch) : null}
              placeholder="ابحث عن الصنف ثم Enter (* أو % بين الأجزاء)" />
          </div>
          {picked && <>
            <span className="text-sm font-medium" dir="ltr">{picked.name}</span>
            <label className="flex flex-col text-xs text-gray-500">الكمية
              <input ref={qtyRef} value={qty} onChange={e => setQty(e.target.value)} inputMode="decimal"
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addLine() } if (e.key === 'Escape') { setPicked(null); pickedId.current = null; focusSearch() } }}
                className={`${inputCls} w-20`} />
            </label>
            <label className="flex flex-col text-xs text-gray-500">سعر المنصة
              <input value={price} onChange={e => setPrice(e.target.value)} inputMode="decimal"
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addLine() } }}
                className={`${inputCls} w-24`} />
            </label>
            <button onClick={addLine} disabled={price.trim() === ''} className={btnQuiet}>إضافة (Enter)</button>
          </>}
        </div>
        {lines.length > 0 && (
          <table className="w-full text-sm">
            <thead className="text-gray-500 text-xs">
              <tr>
                <SortTh {...table.headerProps('name')} className="text-start px-2 py-1">الصنف</SortTh>
                <SortTh {...table.headerProps('qty', 'number')} className="text-start px-2 py-1">الكمية</SortTh>
                <SortTh {...table.headerProps('unit_price', 'number')} className="text-start px-2 py-1">سعر المنصة</SortTh>
                <th />
              </tr>
            </thead>
            <tbody>
              {table.sorted.map(l => (
                <tr key={l.key} className="border-t">
                  <td className="px-2 py-1" dir="ltr">{l.name} <span className="text-xs text-gray-400">{l.code}</span></td>
                  <td className="px-2 py-1">{l.qty}</td>
                  <td className="px-2 py-1">{money(l.unit_price)}</td>
                  <td className="px-2 py-1 text-end">
                    <button onClick={() => setLines(ls => ls.filter(x => x.key !== l.key))} className="text-xs text-red-600">حذف</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">إجمالي المنصة: <b className="text-gray-900">{money(total)}</b></span>
          <button disabled={!ready || save.isPending} onClick={() => save.mutate()} className={`${btnPrimary} ms-auto`}>حفظ الطلب</button>
        </div>
        <p className="text-[11px] text-gray-400">الطلب يدخل «جديد» ويحتاج قبولًا؛ القبول يحوّله مسودة في نقطة البيع على حساب المنصة، والكاشير يسويها.</p>
      </div>
    </div>
  )
}
