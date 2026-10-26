/**
 * PurchasePricesTab.jsx — «مقارنة أسعار الشراء»: the accredited suppliers compared on what we
 * really paid them (saved purchase invoices), not on the incoming «الوارد» lists.
 * The server computes every number (apps/supply/price_history.py); this screen filters,
 * sorts and drills down only.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import { wildcardMatch } from '../../utils/wildcard'
import { FreshnessBar } from './AvailabilityControls'
import { Chip, btnGhost, downloadBlob, errText, inputCls, money, q, SortTh, useSort } from './supplyUi'

const STATE_TONE = { cheaper: 'amber', best: 'emerald', single: 'gray', warehouse_only: 'gray' }
const PAGE = 300

function Buy({ b, warn = true }) {
  if (!b) return <span className="text-content/40">—</span>
  return (
    <span className="whitespace-nowrap" title={`${b.name} · ${b.date}${b.bonus_qty ? ` · بونص ${q(b.bonus_qty)}` : ''}`}>
      <b>{q(b.discount_pct)}%</b> <span className="text-content/70">{b.name}</span>
      <span className="text-content/50 text-[11px]"> {b.date}</span>
      {warn && b.stale && <span className="ms-1 text-[10px] text-amber-700">قديم</span>}
      {warn && b.old_price && <span className="ms-1 text-[10px] text-amber-700">سعر قديم</span>}
    </span>
  )
}

function ItemHistory({ code }) {
  const hq = useQuery({ queryKey: ['purchase-price-item', code], queryFn: () => supplyApi.purchasePriceItem(code).then(r => r.data) })
  const lines = hq.data?.lines || []
  const grid = useSort(lines, {
    date: l => l.date, company: l => l.company, tier: l => l.tier_label, branch: l => l.branch, doc: l => l.doc_number,
    qty: l => l.qty, bonus: l => l.bonus_qty, cost: l => l.unit_cost, disc: l => l.discount_pct, pp: l => l.public_price,
  })
  if (hq.isLoading) return <div className="text-xs text-content/50 p-2">جارٍ تحميل المشتريات…</div>
  if (hq.isError) return <div className="text-xs text-rose-600 p-2">{errText(hq.error)}</div>
  return (
    <div className="max-h-72 overflow-auto rounded border border-line bg-surface">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface-2 text-content/70">
          <tr>{[['date', 'التاريخ'], ['company', 'المورد'], ['tier', 'الفئة'], ['branch', 'الفرع'], ['doc', 'الفاتورة'],
            ['qty', 'الكمية'], ['bonus', 'بونص'], ['cost', 'التكلفة/عبوة'], ['disc', 'الخصم %'], ['pp', 'سعر الجمهور وقتها']]
            .map(([k, h]) => <SortTh key={k} k={k} {...grid} className="px-2 py-1 text-center font-medium">{h}</SortTh>)}</tr>
        </thead>
        <tbody>
          {grid.sorted.map((l, i) => (
            <tr key={i} className="border-t border-line/60 text-center">
              <td className="px-2 py-1">{l.date}</td>
              <td className="px-2 py-1 text-start">{l.company} <span className="text-content/40">{l.account}</span></td>
              <td className="px-2 py-1">{l.tier_label}</td>
              <td className="px-2 py-1">{l.branch}</td>
              <td className="px-2 py-1 font-mono">{l.doc_number}</td>
              <td className="px-2 py-1">{q(l.qty)}</td>
              <td className="px-2 py-1">{l.bonus_qty ? q(l.bonus_qty) : '—'}</td>
              <td className="px-2 py-1">{money(l.unit_cost)}</td>
              <td className="px-2 py-1 font-semibold">{q(l.discount_pct)}%</td>
              <td className="px-2 py-1">{money(l.public_price)}{l.old_price && <span className="ms-1 text-amber-700">سعر قديم</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SupplierCells({ row }) {
  const grid = useSort(row.suppliers, {
    name: c => c.name, tier: c => c.tier_label, disc: c => c.discount_pct, date: c => c.date, best: c => c.best_pct,
    buys: c => c.buys, qty: c => c.total_qty, now: c => c.cost_now,
  }, { key: 'disc', dir: -1 })
  return (
    <table className="w-full text-xs rounded border border-line bg-surface">
      <thead className="bg-surface-2 text-content/70">
        <tr>{[['name', 'المورد'], ['tier', 'الفئة'], ['disc', 'آخر خصم %'], ['date', 'تاريخه'], ['best', 'أفضل خصم في الفترة'],
          ['buys', 'عدد الفواتير'], ['qty', 'الكمية'], ['now', 'التكلفة بسعر اليوم']]
          .map(([k, h]) => <SortTh key={k} k={k} {...grid} className="px-2 py-1 text-center font-medium">{h}</SortTh>)}</tr>
      </thead>
      <tbody>
        {grid.sorted.map(c => (
          <tr key={c.key} className={`border-t border-line/60 text-center ${row.best?.key === c.key ? 'bg-emerald-50/60' : ''}`}>
            <td className="px-2 py-1 text-start">{c.name}{row.main_supplier === c.key && <span className="ms-1 text-[10px] text-primary">رئيسي</span>}</td>
            <td className="px-2 py-1">{c.tier_label}</td>
            <td className="px-2 py-1 font-semibold">{q(c.discount_pct)}%</td>
            <td className="px-2 py-1">{c.date}{c.stale && <span className="ms-1 text-amber-700">قديم</span>}</td>
            <td className="px-2 py-1">{q(c.best_pct)}%</td>
            <td className="px-2 py-1">{c.buys}</td>
            <td className="px-2 py-1">{q(c.total_qty)}</td>
            <td className="px-2 py-1">{money(c.cost_now)}{c.old_price && <span className="ms-1 text-amber-700">سعر قديم</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SuppliersView({ suppliers }) {
  const grid = useSort(suppliers, {
    name: s => s.name, tier: s => s.tier_label, items: s => s.items, best: s => s.best_in,
    cheaper: s => s.cheaper_than_last, avg: s => s.avg_discount_pct, value: s => s.value,
  })
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-sm">
        <thead className="bg-surface-2 text-content/70 text-xs">
          <tr>{[['name', 'المورد'], ['tier', 'الفئة'], ['items', 'أصناف اشترينا منه'], ['best', 'الأفضل في'],
            ['cheaper', 'أرخص مما ندفع في'], ['avg', 'متوسط آخر خصم %'], ['value', 'قيمة المشتريات']]
            .map(([k, h]) => <SortTh key={k} k={k} {...grid} className="px-2 py-2 text-center font-medium">{h}</SortTh>)}</tr>
        </thead>
        <tbody>
          {grid.sorted.map(s => (
            <tr key={s.key} className="border-t border-line text-center">
              <td className="px-2 py-1.5 text-start">{s.name}</td>
              <td className="px-2 py-1.5">{s.tier_label}</td>
              <td className="px-2 py-1.5">{s.items}</td>
              <td className="px-2 py-1.5 font-semibold">{s.best_in}</td>
              <td className="px-2 py-1.5">{s.cheaper_than_last}</td>
              <td className="px-2 py-1.5">{q(s.avg_discount_pct)}%</td>
              <td className="px-2 py-1.5">{money(Math.round(s.value))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function PurchasePricesTab() {
  const [days, setDays] = useState(180)
  const [all, setAll] = useState(false)
  const [state, setState] = useState('')
  const [search, setSearch] = useState('')
  const [supplier, setSupplier] = useState('')
  const [producer, setProducer] = useState('')
  const [view, setView] = useState('items')
  const [open, setOpen] = useState(null)
  const [shown, setShown] = useState(PAGE)
  const params = { days, ...(all ? { all: 1 } : {}) }
  const bq = useQuery({
    queryKey: ['purchase-prices', days, all],
    queryFn: () => supplyApi.purchasePrices(params).then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })
  const xlsM = useMutation({
    // the filters on screen go with the export — the file holds exactly the rows shown
    mutationFn: () => supplyApi.purchasePricesExcel({ ...params, state, supplier, producer, q: search.trim() }),
    onSuccess: (res) => downloadBlob(res.data, `purchase_prices_${days}d.xlsx`),
  })
  const d = bq.data
  const producers = useMemo(() => [...new Set((d?.items || []).map(r => r.producer).filter(Boolean))].sort(), [d])
  const rows = useMemo(() => (d?.items || []).filter(r =>
    (!state || r.state === state)
    && (!supplier || r.suppliers.some(c => c.key === supplier))
    && (!producer || r.producer === producer)
    && (!search.trim() || wildcardMatch(`${r.code} ${r.name}`, search))), [d, state, supplier, producer, search])
  const grid = useSort(rows, {
    code: r => r.code, name: r => r.name, producer: r => r.producer, price: r => r.public_price, rate: r => r.monthly_rate,
    n: r => r.n_suppliers, paid: r => r.paid_pct, last: r => r.last?.discount_pct, best: r => r.best?.discount_pct,
    gap: r => r.gap_pct, saving: r => r.saving_month, state: r => r.state_label,
  })
  const t = d?.totals
  return (
    <div className="space-y-3">
      <FreshnessBar domains={['purchases', 'rates']} onRefreshed={() => bq.refetch()} />
      <div className="text-xs text-content/70 leading-6 rounded border border-line bg-surface p-2">
        مقارنة الموردين المعتمدين على ما دفعناه فعلاً (فواتير الشراء المحفوظة) — غير مقارنة «الوارد».
        الخصم = 1 − التكلفة بعد البونص ÷ سعر الجمهور وقت الشراء، فتُقارن الأسعار بعدل رغم تغيّر سعر الجمهور.
        الموزعون والشركات المنتجة معاً، والمخازن عمود مستقل. «يوجد أرخص» = أفضل مورد حديث (آخر {d?.stale_days ?? 90} يوماً)
        يعطي خصماً أعلى من متوسط خصمنا الفعلي بأكثر من {d?.better_pct ?? 1} نقطة.
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-content/60">الفترة
          <select value={days} onChange={e => { setDays(Number(e.target.value)); setShown(PAGE) }} className={inputCls}>
            {[90, 180, 365].map(n => <option key={n} value={n}>آخر {n} يوماً</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content/60">بحث
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="كود أو اسم — * أو %" className={`${inputCls} w-48`} />
        </label>
        <label className="flex flex-col gap-1 text-xs text-content/60">المورد
          <select value={supplier} onChange={e => setSupplier(e.target.value)} className={`${inputCls} max-w-52`}>
            <option value="">الكل</option>
            {(d?.suppliers || []).map(s => <option key={s.key} value={s.key}>{s.name} ({s.items})</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-content/60">الشركة المنتجة
          <input list="pp-producers" value={producer} onChange={e => setProducer(e.target.value)} placeholder="الكل" className={`${inputCls} w-44`} />
          <datalist id="pp-producers">{producers.map(p => <option key={p} value={p} />)}</datalist>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-content/70 mb-1.5 cursor-pointer">
          <input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} />
          اعرض الأصناف ذات المورد الواحد
        </label>
        <button type="button" className={btnGhost} disabled={xlsM.isPending || !d} onClick={() => xlsM.mutate()}>
          {xlsM.isPending ? '…' : '⬇ Excel'}
        </button>
        <div className="flex gap-1 ms-auto">
          {[['items', 'حسب الصنف'], ['suppliers', 'حسب المورد']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setView(k)}
              className={`px-3 py-1 rounded text-sm border ${view === k ? 'border-primary bg-primary/10 text-primary' : 'border-line text-content/70'}`}>{l}</button>
          ))}
        </div>
      </div>

      {bq.isLoading && <div className="text-sm text-content/50">جارٍ الحساب من فواتير الشراء…</div>}
      {bq.isError && <div className="text-sm text-rose-600">{errText(bq.error)}</div>}
      {t && (
        <div className="flex flex-wrap gap-2 text-xs">
          <button type="button" onClick={() => setState('')}><Chip tone={state ? 'gray' : 'blue'}>كل الأصناف {t.items}</Chip></button>
          <button type="button" onClick={() => setState('cheaper')}><Chip tone={state === 'cheaper' ? 'amber' : 'gray'}>يوجد أرخص {t.cheaper}</Chip></button>
          <button type="button" onClick={() => setState('best')}><Chip tone={state === 'best' ? 'emerald' : 'gray'}>نشتري من الأفضل {t.best}</Chip></button>
          <Chip tone="amber" title="الفرق × سعر الجمهور الحالي × معدل البيع الشهري للشبكة">توفير محتمل/شهر {money(Math.round(t.saving_month))} ج</Chip>
          <span className="text-content/50">من {money(t.lines)} سطر شراء · {d.since} ← {d.today}</span>
        </div>
      )}

      {d && view === 'suppliers' && <SuppliersView suppliers={d.suppliers} />}
      {d && view === 'items' && (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-content/70 text-xs sticky top-0">
              <tr>{[['code', 'الكود'], ['name', 'الصنف'], ['producer', 'الشركة المنتجة'], ['price', 'سعر الجمهور'],
                ['rate', 'بيع/شهر'], ['n', 'موردين'], ['paid', 'متوسط خصمنا'], ['last', 'آخر شراء'], ['best', 'الأفضل حديثاً'],
                ['gap', 'الفرق'], ['saving', 'توفير/شهر'], ['state', 'الحالة']].map(([k, h]) =>
                <SortTh key={k} k={k} {...grid} className="px-2 py-2 text-center font-medium">{h}</SortTh>)}</tr>
            </thead>
            <tbody>
              {grid.sorted.slice(0, shown).map(r => (
                <FragmentRow key={r.item_id} r={r} open={open === r.item_id} onToggle={() => setOpen(open === r.item_id ? null : r.item_id)} />
              ))}
            </tbody>
          </table>
          {rows.length > shown && (
            <button type="button" className="w-full p-2 text-xs text-primary" onClick={() => setShown(s => s + PAGE)}>
              عرض المزيد ({rows.length - shown} صنف)
            </button>
          )}
          {rows.length === 0 && <div className="p-3 text-sm text-content/50">لا توجد أصناف بهذه الفلاتر.</div>}
        </div>
      )}
    </div>
  )
}

function FragmentRow({ r, open, onToggle }) {
  return (
    <>
      <tr onClick={onToggle} className={`border-t border-line text-center cursor-pointer hover:bg-surface-2/50 ${open ? 'bg-surface-2/60' : ''}`}>
        <td className="px-2 py-1.5 font-mono text-xs">{r.code}</td>
        <td className="px-2 py-1.5 text-start">{r.name}</td>
        <td className="px-2 py-1.5 text-xs text-content/70">{r.producer}</td>
        <td className="px-2 py-1.5">{money(r.public_price)}</td>
        <td className="px-2 py-1.5">{q(r.monthly_rate)}</td>
        <td className="px-2 py-1.5">{r.n_suppliers}{r.n_warehouses ? <span className="text-content/50 text-[11px]"> +{r.n_warehouses} مخزن</span> : ''}</td>
        <td className="px-2 py-1.5">{r.paid_pct != null ? `${q(r.paid_pct)}%` : '—'}</td>
        <td className="px-2 py-1.5 text-start"><Buy b={r.last} /></td>
        <td className="px-2 py-1.5 text-start">
          <Buy b={r.best} />
          {r.old_best && <div className="text-[11px] text-content/50">كان أرخص: {q(r.old_best.discount_pct)}% {r.old_best.name} ({r.old_best.date})</div>}
        </td>
        <td className="px-2 py-1.5 font-semibold">{r.gap_pct ? `+${q(r.gap_pct)}` : '—'}</td>
        <td className="px-2 py-1.5">{r.saving_month ? money(Math.round(r.saving_month)) : '—'}</td>
        <td className="px-2 py-1.5"><Chip tone={STATE_TONE[r.state]}>{r.state_label}</Chip></td>
      </tr>
      {open && (
        <tr className="bg-surface-2/40">
          <td colSpan={12} className="p-2 space-y-2">
            <SupplierCells row={r} />
            <div className="text-xs text-content/60">كل فواتير الشراء لهذا الصنف (سنة):</div>
            <ItemHistory code={r.code} />
          </td>
        </tr>
      )}
    </>
  )
}
