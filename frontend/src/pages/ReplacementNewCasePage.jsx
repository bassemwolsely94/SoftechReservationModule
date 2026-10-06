/**
 * ReplacementNewCasePage — open a live بدل case (doc 25 Phase 1).
 *
 * One calm page: type + settlement → patient → pick the prescription (recent contract sales of
 * the patient) and the items being replaced, or add items by search → create. All money is
 * computed later by the server (Calculate step in the case workspace); this page only collects
 * the facts. Authorization (role + per-employee grant) is enforced by the API.
 */
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { branchesApi, replacementApi } from '../api/client'
import useAuthStore from '../store/authStore'
import ItemSearchInput from '../components/ItemSearchInput'
import { Chip, errText, money } from './supply/supplyUi'

const SOURCES = [
  ['insurance_rx', 'روشتة تأمين من صرفنا'],
  ['insurance_external', 'أدوية تأمين من خارج صرفنا'],
  ['client_buyback', 'عميل غير تأمين يبيع أدوية'],
]
const MODES = [['products', 'منتجات'], ['cash', 'نقدي'], ['mixed', 'مختلط']]

function Seg({ value, options, onChange }) {
  return (
    <div className="inline-flex rounded-lg border border-gray-300 overflow-hidden">
      {options.map(([v, l]) => (
        <button key={v} type="button" onClick={() => onChange(v)}
                className={`px-3 py-1.5 text-sm ${value === v ? 'bg-blue-600 text-white' : 'bg-white text-gray-700'}`}>
          {l}
        </button>
      ))}
    </div>
  )
}

export default function ReplacementNewCasePage() {
  const nav = useNavigate()
  const user = useAuthStore((s) => s.user)
  const [branch, setBranch] = useState(user?.branch_id || '')
  const [source, setSource] = useState('insurance_rx')
  const [mode, setMode] = useState('products')
  const [shortage, setShortage] = useState(false)
  const [pic, setPic] = useState('')
  const [lookupPic, setLookupPic] = useState('')
  const [sale, setSale] = useState(null)
  const [picked, setPicked] = useState({})        // itemcode → {item_id, qty, max, name, price}
  const [extra, setExtra] = useState([])          // manually added items
  const [refs, setRefs] = useState({ prescription_no: '', approval_no: '', notes: '' })
  const [err, setErr] = useState('')

  const branches = useQuery({ queryKey: ['branches-list'], queryFn: () => branchesApi.list().then((r) => r.data.results || r.data) })
  const sales = useQuery({
    queryKey: ['patient-sales', lookupPic, branch], enabled: !!lookupPic,
    queryFn: () => replacementApi.patientSales({ pic: lookupPic, branch }).then((r) => r.data.results),
  })

  const items = useMemo(() => [
    ...Object.values(picked).filter((p) => Number(p.qty) > 0).map((p) => ({ item_id: p.item_id, qty: p.qty })),
    ...extra.filter((e) => Number(e.qty) > 0).map((e) => ({ item_id: e.item_id, qty: e.qty })),
  ], [picked, extra])
  const publicValue = [...Object.values(picked), ...extra].reduce((s, p) => s + Number(p.qty || 0) * Number(p.price || 0), 0)

  const create = useMutation({
    mutationFn: () => replacementApi.create({
      branch, source_type: source, settlement_mode: mode, softech_pic: pic.trim(), is_shortage_item: shortage,
      contract_personcode: sale?.contract || '', from_sale: sale?.id || null, items, ...refs,
    }),
    onSuccess: (r) => nav(`/replacement/${r.data.id}`),
    onError: (e) => setErr(errText(e, 'تعذّر إنشاء الحالة')),
  })

  const toggle = (l) => setPicked((p) => {
    const n = { ...p }
    if (n[l.itemcode]) delete n[l.itemcode]
    else n[l.itemcode] = { item_id: l.item_id, qty: l.qty, max: Number(l.qty), name: l.name, price: l.public_price }
    return n
  })

  return (
    <div className="p-4 space-y-4 max-w-5xl" dir="rtl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">➕ حالة بدل جديدة</h1>
        <p className="text-xs text-gray-500">الحساب والاعتماد والترحيل يتم في صفحة الحالة بعد الإنشاء — القيم المالية يحسبها السيرفر فقط.</p>
      </div>

      <section className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <div className="flex flex-wrap gap-4 items-center">
          <label className="text-sm text-gray-600">الفرع
            <select value={branch} onChange={(e) => setBranch(e.target.value)} className="mr-2 border border-gray-300 rounded-lg px-2 py-1 text-sm">
              <option value="">—</option>
              {(branches.data || []).map((b) => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
            </select>
          </label>
          <Seg value={source} options={SOURCES} onChange={(v) => { setSource(v); if (v !== 'insurance_rx') setShortage(false) }} />
          <Seg value={mode} options={MODES} onChange={setMode} />
          {source === 'insurance_rx' && (
            <label className="text-sm flex items-center gap-1">
              <input type="checkbox" checked={shortage} onChange={(e) => setShortage(e.target.checked)} />
              الصنف ناقص / لا يمكن توفيره
            </label>
          )}
        </div>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <div className="flex gap-2 items-center flex-wrap">
          <input value={pic} onChange={(e) => setPic(e.target.value)} placeholder="كود المريض PIC"
                 className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono w-48" />
          <button type="button" onClick={() => { setLookupPic(pic.trim()); setSale(null); setPicked({}) }}
                  className="text-sm px-3 py-1.5 rounded-lg border border-gray-300">عرض روشتات التعاقد للمريض</button>
          {sales.isFetching && <span className="text-xs text-gray-400">جارٍ البحث…</span>}
        </div>
        {sales.data && !sales.data.length && <div className="text-xs text-gray-500">لا توجد فواتير تعاقد خلال 60 يوماً — يمكنك إضافة الأصناف يدوياً.</div>}
        <div className="grid md:grid-cols-2 gap-2">
          {(sales.data || []).map((s) => (
            <button key={s.id} type="button" onClick={() => { setSale(s); setPicked({}) }}
                    className={`text-right border rounded-lg p-2 text-sm ${sale?.id === s.id ? 'border-blue-500 bg-blue-50' : 'border-gray-200'}`}>
              <div className="font-mono">{s.branchcode}/{s.docnumber} · {s.date}</div>
              <div className="text-xs text-gray-500">تعاقد {s.contract} · {s.lines.length} صنف · {money(s.total)}</div>
            </button>
          ))}
        </div>
        {sale && (
          <table className="w-full text-sm">
            <thead className="text-[11px] text-gray-500 bg-gray-50"><tr>
              {['', 'الصنف', 'كمية الروشتة', 'كمية البدل', 'سعر الجمهور'].map((h) => <th key={h} className="px-2 py-1 text-right">{h}</th>)}
            </tr></thead>
            <tbody>
              {sale.lines.map((l) => {
                const p = picked[l.itemcode]
                return (
                  <tr key={l.itemcode} className={`border-t border-gray-100 ${p ? 'bg-amber-50' : ''}`}>
                    <td className="px-2 py-1"><input type="checkbox" checked={!!p} onChange={() => toggle(l)} disabled={!l.item_id} /></td>
                    <td className="px-2 py-1">{l.name} <span className="text-[11px] text-gray-400 font-mono">{l.itemcode}</span></td>
                    <td className="px-2 py-1 tabular-nums">{l.qty}</td>
                    <td className="px-2 py-1">
                      {p && <input type="number" min="0" max={p.max} step="any" value={p.qty}
                                   onChange={(e) => setPicked((x) => ({ ...x, [l.itemcode]: { ...p, qty: e.target.value } }))}
                                   className="border border-gray-300 rounded px-2 py-0.5 w-20 text-sm" />}
                    </td>
                    <td className="px-2 py-1 tabular-nums">{money(l.public_price)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
        <div className="text-sm text-gray-700">إضافة أصناف أخرى (بدون روشتة / من خارج صرفنا)</div>
        <ItemSearchInput placeholder="ابحث عن الصنف…" onSelect={(it) => it?.item_id && setExtra((x) =>
          x.some((e) => e.item_id === it.item_id) ? x : [...x, { item_id: it.item_id, name: it.name, price: it.pack_price, qty: 1 }])} />
        {extra.map((e, i) => (
          <div key={e.item_id} className="flex items-center gap-2 text-sm">
            <span className="flex-1">{e.name}</span>
            <input type="number" min="0" step="any" value={e.qty}
                   onChange={(ev) => setExtra((x) => x.map((y, j) => (j === i ? { ...y, qty: ev.target.value } : y)))}
                   className="border border-gray-300 rounded px-2 py-0.5 w-20" />
            <span className="tabular-nums text-gray-500 w-24">{money(e.price)}</span>
            <button type="button" onClick={() => setExtra((x) => x.filter((_, j) => j !== i))} className="text-rose-600 text-xs">حذف</button>
          </div>
        ))}
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-4 grid md:grid-cols-3 gap-2">
        {[['prescription_no', 'رقم الروشتة'], ['approval_no', 'رقم الموافقة'], ['notes', 'ملاحظات']].map(([k, l]) => (
          <input key={k} value={refs[k]} onChange={(e) => setRefs((r) => ({ ...r, [k]: e.target.value }))} placeholder={l}
                 className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm" />
        ))}
      </section>

      {err && <div className="bg-rose-50 border border-rose-200 text-rose-700 text-sm rounded-lg px-3 py-2">{err}</div>}
      <div className="flex items-center gap-3">
        <button disabled={!branch || !items.length || create.isPending} onClick={() => { setErr(''); create.mutate() }}
                className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-40">إنشاء الحالة</button>
        <Chip tone="gray">{items.length} صنف للاستبدال</Chip>
        <Chip tone="gray">قيمة الجمهور التقريبية {money(publicValue)}</Chip>
      </div>
    </div>
  )
}
