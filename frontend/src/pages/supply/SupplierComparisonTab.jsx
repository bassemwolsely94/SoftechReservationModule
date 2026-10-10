/**
 * SupplierComparisonTab.jsx — «مقارنة الموردين»: every item offered in the suppliers' daily
 * «الوارد» lists over the last N days (default 14), one column per supplier (medicine
 * warehouses in their own column), the estimated cost at TODAY's public price, the need, and
 * which supplier to buy from. Backend: apps/supply/comparison.py — it computes every number
 * and the decision; this screen only displays them. Read-only (no orders, no SOFTECH writes).
 */
import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import ProgressBar from '../../components/ProgressBar'
import { wildcardMatch } from '../../utils/wildcard'
import { Chip, btnGhost, downloadBlob, errText, inputCls, money, q } from './supplyUi'

const STATE = {
  buy: ['اشترِ', 'emerald'], compare: ['قارن يدوياً', 'amber'], not_needed: ['غير مطلوب', 'gray'],
}
// Every cost comes from OUR purchase history (the list only says THAT the supplier sells
// the item, plus its bonus) — owner 2026-10-08.
const BASIS = {
  history: 'آخر شراء فعلي من نفس المورد', group_history: 'آخر شراء من حساب آخر لنفس الشركة',
  producer: 'متوسط خصم المورد على نفس الشركة المنتجة',
}
const BASIS_TAG = { history: 'آخر شراء', group_history: 'حساب آخر', producer: 'متوسط الشركة' }
const FLAG = {
  warehouse_cheaper: ['مخزن أرخص', 'violet'], quota_short: ['الكوتة لا تكفي', 'amber'],
}
const VERDICT_TONE = {
  best: 'bg-emerald-50 border-emerald-400', cheaper: 'bg-violet-50 border-violet-300',
  similar: 'border-line', other_bonus: 'border-line', pricier: 'border-line opacity-70',
  no_price: 'border-dashed border-line', no_compare: 'border-line',
}
const fmtPct = (v) => (v === null || v === undefined ? '—' : `${Number(v).toFixed(1).replace(/\.0$/, '')}%`)
const day = (iso) => (iso ? String(iso).slice(0, 10) : '—')

function Tile({ label, value, tone = '', active, onClick }) {
  return (
    <button type="button" onClick={onClick}
      className={`rounded-lg border px-3 py-2 min-w-[8rem] text-right transition ${active ? 'border-primary bg-primary/5' : 'border-line bg-surface hover:border-primary/40'} ${tone}`}>
      <div className="text-[11px] text-content/60">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-content">{value ?? 0}</div>
    </button>
  )
}

// One supplier's offer for one item.
function OfferCell({ c }) {
  if (!c) return <td className="px-2 py-1 text-center text-content/25">—</td>
  const title = [c.raw_text, c.basis ? `أساس التكلفة: ${BASIS[c.basis] || c.basis}` : 'لم نشترِ من هذا المورد (أو شركته) من قبل — لا تكلفة للمقارنة',
    c.confirmed ? 'مطابقة مؤكدة' : 'مطابقة غير مؤكدة بعد'].join('\n')
  return (
    <td className="px-1 py-1 align-top">
      <div title={title} className={`rounded border px-1.5 py-1 space-y-0.5 min-w-[8.5rem] ${VERDICT_TONE[c.verdict] || 'border-line'}`}>
        <div className="flex items-center gap-1">
          <span className={`font-semibold tabular-nums ${c.verdict === 'best' ? 'text-emerald-700' : 'text-content'}`}>
            {c.discount_pct != null ? fmtPct(c.discount_pct) : 'لا شراء سابق'}</span>
          {c.basis && <span className="text-[10px] text-content/45" title={BASIS[c.basis]}>{BASIS_TAG[c.basis]}</span>}
          {c.verdict === 'best' && <span className="text-[10px] text-emerald-700">✔ الأفضل</span>}
          {c.verdict === 'pricier' && c.gap_pct != null && <span className="text-[10px] text-content/50">+{fmtPct(c.gap_pct)}</span>}
          {c.verdict === 'cheaper' && <span className="text-[10px] text-violet-700">أرخص</span>}
          {!c.confirmed && <span className="text-[10px] text-amber-700" title="مطابقة الصنف لم تُؤكد بعد">؟</span>}
        </div>
        <div className="flex flex-wrap gap-1">
          {c.bonus && <Chip tone="emerald">بونص {c.bonus}</Chip>}
          {c.quota != null && <Chip tone="amber">كوتة {q(c.quota)}</Chip>}
          {c.promo && <Chip tone="teal">{c.promo}</Chip>}
          {(c.signals || []).map(s => <Chip key={s}>{s}</Chip>)}
          {c.is_main && <Chip tone="blue" title="المورد الأساسي في SOFTECH">أساسي</Chip>}
        </div>
        {c.last_buy && (
          <div className="text-[10px] text-content/55">
            آخر شراء {day(c.last_buy.date)}{c.basis === 'group_history' ? ` (${c.last_buy.supplier_code})` : ''} · {fmtPct(c.last_buy.discount_pct)}
            {c.last_buy.old_price && <span className="text-rose-600"> · سعر قديم</span>}
          </div>
        )}
      </div>
    </td>
  )
}

// Who supplies the item: SOFTECH's main supplier + who we really bought from (12 months).
function NetworkPanel({ r }) {
  const b = r.network?.bought || []
  return (
    <div className="grid md:grid-cols-[16rem_1fr] gap-3 text-xs">
      <div className="space-y-1">
        <div><span className="text-content/60">المورد الأساسي (SOFTECH): </span>
          {r.main_supplier ? `${r.main_supplier.name} (${r.main_supplier.code})` : '—'}</div>
        <div><span className="text-content/60">موردون يحملون الصنف (SOFTECH): </span>{r.network?.carriers ?? 0}</div>
        {(r.network?.offered_by || []).length > 0 && (
          <div><span className="text-content/60">عرضوه في قوائم الوارد: </span>
            {r.network.offered_by.map(o => `${o.name} (${day(o.last_offered)}${o.times > 1 ? ` · ${o.times} مرات` : ''})`).join('، ')}</div>)}
        <div><span className="text-content/60">سعر الجمهور الحالي: </span>{money(r.public_price)}</div>
        {r.bought_elsewhere && (
          <div className="text-violet-700">اشترينا من {r.bought_elsewhere.name} بخصم {fmtPct(r.bought_elsewhere.discount_pct)} ({day(r.bought_elsewhere.date)}) — لم يعرض هذا الصنف في قوائم الفترة</div>)}
        {(r.allocation || []).length > 1 && (
          <div className="text-amber-700">الكوتة لا تغطي الاحتياج كله عند الأفضل — التقسيم: {r.allocation.map(a => `${a.supplier_name} ${q(a.qty)}`).join(' + ')}</div>)}
        {r.uncovered > 0 && <div className="text-rose-600">غير مغطى: {q(r.uncovered)}</div>}
      </div>
      <div>
        <div className="text-content/60 mb-1">مشتريات آخر 12 شهراً (الخصم الفعلي بعد البونص من سعر الجمهور وقت الشراء)</div>
        {b.length === 0 ? <div className="text-content/50">لا مشتريات مسجلة.</div> : (
          <table className="w-full bg-surface rounded border border-line">
            <thead className="bg-surface-2 text-content/60">
              <tr><th className="px-2 py-1 text-right">المورد</th><th className="px-2 py-1">النوع</th><th className="px-2 py-1">آخر شراء</th>
                <th className="px-2 py-1">الخصم الفعلي</th><th className="px-2 py-1">أفضل خصم</th><th className="px-2 py-1">تكلفته اليوم</th>
                <th className="px-2 py-1">كمية 12 شهر</th></tr>
            </thead>
            <tbody>
              {b.map(x => (
                <tr key={x.code} className="border-t border-line">
                  <td className="px-2 py-1">{x.name} <span className="text-content/40">({x.code})</span></td>
                  <td className="px-2 py-1 text-center">{{ distributor: 'موزع', manufacturer: 'شركة', warehouse: 'مخزن', other: 'مورد' }[x.tier]}</td>
                  <td className="px-2 py-1 text-center tabular-nums">{day(x.last.date)}{x.old_price && <span className="text-rose-600"> · سعر قديم</span>}</td>
                  <td className="px-2 py-1 text-center tabular-nums">{fmtPct(x.last.discount_pct)}</td>
                  <td className="px-2 py-1 text-center tabular-nums">{fmtPct(x.best.discount_pct)}</td>
                  <td className="px-2 py-1 text-center tabular-nums">{money(x.cost_now)}</td>
                  <td className="px-2 py-1 text-center tabular-nums">{q(x.qty_12m)}</td>
                </tr>))}
            </tbody>
          </table>)}
      </div>
    </div>
  )
}

export default function SupplierComparisonTab() {
  const [days, setDays] = useState(14)
  const [state, setState] = useState('')
  const [flag, setFlag] = useState('')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(null)
  const bq = useQuery({ queryKey: ['supply-comparison', days],
    queryFn: () => supplyApi.comparison(days).then(r => r.data) })
  const xl = useMutation({
    mutationFn: () => supplyApi.comparisonExcel(days),
    onSuccess: (res) => downloadBlob(res.data, `supplier_comparison_${days}d.xlsx`),
  })
  const d = bq.data
  const sups = d?.suppliers || []
  const rows = useMemo(() => (d?.rows || []).filter(r =>
    (!state || r.state === state) && (!flag || r.flags.includes(flag))
    && (!search.trim() || wildcardMatch(`${r.item_code} ${r.item_name}`, search))), [d, state, flag, search])
  const s = d?.summary || {}
  const whCount = (d?.rows || []).filter(r => r.flags.includes('warehouse_cheaper')).length

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold text-content">مقارنة عروض الموردين</h3>
        <select value={days} onChange={e => setDays(Number(e.target.value))} className={`${inputCls} text-xs w-32`}>
          {[7, 14, 30].map(n => <option key={n} value={n}>عروض آخر {n} يوم</option>)}
        </select>
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="بحث بالصنف أو الكود… (* أو %)"
          className={`${inputCls} text-xs w-56`} />
        <button type="button" className={btnGhost} disabled={!d || xl.isPending} onClick={() => xl.mutate()}>
          {xl.isPending ? 'جارٍ التجهيز…' : 'تصدير Excel'}</button>
        <span className="text-[11px] text-content/50 ms-auto">
          التكلفة من مشترياتنا الفعلية (خصم من سعر الجمهور الحالي) + بونص القائمة · الأفضل أرخص بأكثر من {d?.better_pct ?? 1}% أو ببونص
        </span>
      </div>
      {bq.isLoading && <ProgressBar label="تجميع العروض ومقارنتها" />}
      {xl.isPending && <ProgressBar since={xl.submittedAt} label="تجهيز ملف Excel" />}
      {bq.isError && <div className="text-xs text-rose-600">{errText(bq.error, 'تعذّر تحميل المقارنة')}</div>}
      {d && (
        <>
          <div className="flex flex-wrap gap-2">
            <Tile label="أصناف معروضة" value={s.items} active={!state && !flag} onClick={() => { setState(''); setFlag('') }} />
            <Tile label="اشترِ" value={s.buy} active={state === 'buy'} onClick={() => setState(state === 'buy' ? '' : 'buy')} />
            <Tile label="قارن يدوياً (لا شراء سابق)" value={s.compare} active={state === 'compare'}
              onClick={() => setState(state === 'compare' ? '' : 'compare')} />
            <Tile label="غير مطلوب الآن" value={s.not_needed} active={state === 'not_needed'}
              onClick={() => setState(state === 'not_needed' ? '' : 'not_needed')} />
            <Tile label="مخزن أرخص" value={whCount} active={flag === 'warehouse_cheaper'}
              onClick={() => setFlag(flag === 'warehouse_cheaper' ? '' : 'warehouse_cheaper')} />
          </div>
          {rows.length === 0 ? (
            <div className="text-sm text-content/50 py-6 text-center">
              {(d.rows || []).length === 0 ? `لا توجد قوائم وارد في آخر ${days} يوم — أضفها من «صندوق الإتاحة».` : 'لا أصناف تطابق التصفية.'}
            </div>
          ) : (
            <div className="overflow-auto border border-line rounded max-h-[70vh]">
              <table className="text-xs w-full">
                <thead className="bg-surface-2 text-content/70 sticky top-0 z-10">
                  <tr>
                    <th className="px-2 py-2 text-right min-w-[16rem] sticky right-0 bg-surface-2">الصنف</th>
                    <th className="px-2 py-2" title="معدل البيع الشهري (كل الفروع)">المعدل</th>
                    <th className="px-2 py-2">الرصيد</th>
                    <th className="px-2 py-2">بالطريق</th>
                    <th className="px-2 py-2 font-bold" title="الاحتياج الصافي للشركة بعد التغطية الداخلية من فروع فوق الهدف">الاحتياج</th>
                    <th className="px-2 py-2 min-w-[10rem]">القرار</th>
                    {sups.map(x => (
                      <th key={x.key} className="px-2 py-2 min-w-[9rem]">{x.name}
                        <div className="text-[10px] font-normal text-content/45">{x.tier_label} · {x.items} صنف</div></th>))}
                    {(d.warehouses || []).length > 0 && (
                      <th className="px-2 py-2 min-w-[10rem]">المخازن<div className="text-[10px] font-normal text-content/45">
                        {d.warehouses.map(w => w.name).join('، ')}</div></th>)}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(r => {
                    const by = Object.fromEntries(r.cells.map(c => [c.supplier, c]))
                    const wh = r.cells.filter(c => c.tier === 'warehouse')
                      .sort((a, b) => (a.effective_cost ?? 1e12) - (b.effective_cost ?? 1e12))
                    const [sl, tone] = STATE[r.state]
                    return (
                      <Fragment key={r.item_id}>
                        <tr className="border-t border-line hover:bg-surface-2/50 cursor-pointer"
                          onClick={() => setOpen(o => (o === r.item_id ? null : r.item_id))}>
                          <td className="px-2 py-1 align-top sticky right-0 bg-surface">
                            <div className="font-medium text-content">{r.item_name}</div>
                            <div className="text-[10px] text-content/50 font-mono">{r.item_code} · جمهور {money(r.public_price)}</div>
                            <div className="flex flex-wrap gap-1 mt-0.5">
                              {r.flags.map(f => FLAG[f] && <Chip key={f} tone={FLAG[f][1]}>{FLAG[f][0]}</Chip>)}
                            </div>
                          </td>
                          <td className="px-2 py-1 text-center tabular-nums align-top">{q(r.monthly_rate)}</td>
                          <td className="px-2 py-1 text-center tabular-nums align-top">{q(r.stock)}</td>
                          <td className="px-2 py-1 text-center tabular-nums align-top">{q(r.in_transit)}</td>
                          <td className="px-2 py-1 text-center tabular-nums align-top font-bold">{q(r.need)}</td>
                          <td className="px-2 py-1 align-top">
                            <Chip tone={tone}>{sl}</Chip>
                            {r.best && r.state !== 'not_needed' && (
                              <div className="mt-0.5">{r.best.supplier_name}
                                {r.best.discount_pct != null && <span className="text-content/60"> · {fmtPct(r.best.discount_pct)}</span>}</div>)}
                            {r.allocation?.length > 0 && <div className="text-[10px] text-content/55">
                              {r.allocation.map(a => `${a.supplier_name}: ${q(a.qty)}`).join(' + ')}</div>}
                          </td>
                          {sups.map(x => <OfferCell key={x.key} c={by[x.key]} />)}
                          {(d.warehouses || []).length > 0 && (
                            wh.length ? <OfferCell c={{ ...wh[0], signals: [...(wh[0].signals || []), wh[0].supplier_name] }} />
                              : <td className="px-2 py-1 text-center text-content/25">—</td>)}
                        </tr>
                        {open === r.item_id && (
                          <tr className="bg-surface-2/40"><td colSpan={7 + sups.length} className="px-3 py-2"><NetworkPanel r={r} /></td></tr>)}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="text-[11px] text-content/45">
            انقر صنفاً لعرض المورد الأساسي ومن عرضه في الوارد ومشتريات آخر 12 شهراً. أسعار وخصومات نص القائمة لا تُستخدم —
            التكلفة من آخر شراء فعلي من نفس المورد، وإلا من حساب آخر لنفس الشركة (المصرية / أخناتون)، وإلا متوسط خصمه على نفس الشركة المنتجة؛ البونص من القائمة.
            الموردون الافتراضيون/التعاقدات لا يدخلون المقارنة. «؟» = مطابقة الصنف لم تُؤكد بعد في صندوق الإتاحة.
          </div>
        </>
      )}
    </div>
  )
}
