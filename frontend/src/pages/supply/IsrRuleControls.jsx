// «طلب توريد جديد» — SOFTECH's rule + the owner's safeguards (apps/purchasing/isr_softech.py).
// The server owns the rule and the defaults (GET isr/filter-options/ → defaults); this file
// only collects the settings and shows what the server decided.
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'

const box = 'border border-line rounded px-2 py-1 text-sm bg-surface text-content'

export function useIsrRuleSettings() {
  const optsQ = useQuery({
    queryKey: ['isr-filter-options'], staleTime: 30 * 60 * 1000,
    queryFn: () => supplyApi.isrFilterOptions().then(r => r.data),
  })
  const [st, setSt] = useState(null)
  useEffect(() => { if (optsQ.data && st === null) setSt({ ...optsQ.data.defaults }) }, [optsQ.data, st])
  const reset = () => optsQ.data && setSt({ ...optsQ.data.defaults })
  return { opts: optsQ.data, loading: optsQ.isLoading, st, setSt, reset }
}

// a long code list (suppliers, producers) — type a code or a name, pick from the list
function PickList({ label, value, onChange, options = [], width = 'w-44' }) {
  const id = useMemo(() => `pick-${label}`.replace(/\s/g, '-'), [label])
  const shown = value ? (options.find(o => o[0] === value)?.join(' · ') || value) : ''
  const [text, setText] = useState(shown)
  useEffect(() => { setText(shown) }, [shown])
  return (
    <label className="flex flex-col gap-1 text-xs text-content/60">
      {label}
      <input list={id} value={text} placeholder="الكل" className={`${box} ${width}`}
        onChange={e => {
          const v = e.target.value
          setText(v)
          if (!v.trim()) return onChange('')
          const code = v.split(' · ')[0].trim()
          if (options.some(o => o[0] === code)) onChange(code)
        }} />
      <datalist id={id}>{options.map(([c, l]) => <option key={c} value={l ? `${c} · ${l}` : c} />)}</datalist>
    </label>
  )
}

function Pick({ label, value, onChange, options = [], all = 'الكل' }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-content/60">
      {label}
      <select value={value} onChange={e => onChange(e.target.value)} className={box}>
        <option value="">{all}</option>
        {options.map(([c, l]) => <option key={c} value={c}>{l || c}</option>)}
      </select>
    </label>
  )
}

const FILTER_KEYS = ['medicine_type', 'supplier', 'producer', 'category', 'family', 'store_classif',
  'origin', 'fridge', 'stock', 'name']
const FILTER_LABELS = {
  medicine_type: 'التصنيف العام', supplier: 'المورد', producer: 'الشركة المنتجة', category: 'الشكل الصيدلي',
  family: 'العائلة', store_classif: 'تصنيف الخصم', origin: 'المنشأ', fridge: 'ثلاجة', stock: 'رصيد الفرع',
  name: 'اسم الصنف',
}

export function IsrRulePanel({ opts, st, setSt, reset }) {
  if (!opts || !st) return <div className="text-xs text-content/50">جارٍ تحميل الإعدادات…</div>
  const set = k => v => setSt(s => ({ ...s, [k]: v && v.target ? (v.target.type === 'checkbox' ? v.target.checked : v.target.value) : v }))
  const active = FILTER_KEYS.filter(k => st[k] && st[k] !== 'all' && st[k] !== opts.defaults[k]).length
  const changed = Object.keys(opts.defaults).some(k => String(st[k] ?? '') !== String(opts.defaults[k] ?? ''))
  return (
    <div className="w-full space-y-3 rounded-md border border-line/70 bg-surface-2/40 p-3">
      {/* the rule, in words, always visible */}
      <div className="text-xs text-content/70 leading-6">
        <b className="text-content">القاعدة (مثل SOFTECH):</b>{' '}
        الكمية = {st.target === 'order_point' ? <>معدل البيع × <b>{st.order_months}</b> شهر (حد الطلب)</> : <>الحد الأقصى</>}
        {' '}− رصيد الفرع − الرصيد بالطريق. أقل من <b>{opts.min_pack_fraction}</b> عبوة = لا شيء، وغير ذلك تُقرَّب
        لأعلى لعبوة كاملة. المعدل والحد الأقصى والأرصدة تُقرأ لحظياً من سيرفر 100.
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <fieldset className="flex flex-col gap-1 text-xs text-content/60">
          <legend className="mb-1">اطلب حتى</legend>
          <label className="flex items-center gap-1.5 text-content cursor-pointer">
            <input type="radio" checked={st.target === 'order_point'} onChange={() => set('target')('order_point')} />
            حد الطلب: المعدل ×
            <input type="number" step="0.1" min="0.1" max="12" value={st.order_months}
              onChange={set('order_months')} className={`${box} w-16`} /> شهر
            <span className="text-content/50">(SOFTECH يستخدم 0.8)</span>
          </label>
          <label className="flex items-center gap-1.5 text-content cursor-pointer">
            <input type="radio" checked={st.target === 'max'} onChange={() => set('target')('max')} />
            الحد الأقصى
            <input type="number" step="0.25" min="0.25" max="12" value={st.coverage_months} disabled={st.target !== 'max'}
              onChange={set('coverage_months')} placeholder="المخزَّن" title="فارغ = الحد الأقصى المخزَّن في SOFTECH (المعدل × التغطية المرفوعة)؛ أو اكتب عدد شهور"
              className={`${box} w-20 disabled:opacity-40`} /> شهر
          </label>
          {st.target === 'max' && (
            <label className="flex items-center gap-1.5 text-content/80 cursor-pointer">
              <input type="checkbox" checked={!!st.below_order_point} onChange={set('below_order_point')} />
              فقط الأصناف التي رصيدها تحت حد الطلب
            </label>
          )}
        </fieldset>

        <fieldset className="flex flex-col gap-1 text-xs">
          <legend className="mb-1 text-content/60">الرئيسي 100</legend>
          <label className="flex items-center gap-1.5 text-content cursor-pointer">
            <input type="checkbox" checked={!!st.hq_only} onChange={set('hq_only')} />
            فقط ما يوجد بالرئيسي (عبوة كاملة على الأقل)
          </label>
          <label className="flex items-center gap-1.5 text-content cursor-pointer">
            <input type="checkbox" checked={!!st.cap_hq} onChange={set('cap_hq')} />
            لا تتجاوز رصيد الرئيسي
          </label>
        </fieldset>
        {changed && <button type="button" onClick={reset} className="text-xs text-primary underline mb-1">إعدادات SOFTECH الافتراضية</button>}
      </div>

      <details open={active > 0}>
        <summary className="cursor-pointer text-xs text-content/70 select-none">
          فلاتر مثل شاشة SOFTECH «طلبيات الأصناف بناءا على حد الطلب»{active ? ` · ${active} مفعّل` : ''}
        </summary>
        <div className="mt-2 flex flex-wrap items-end gap-3">
          <Pick label="التصنيف العام" value={st.medicine_type} onChange={set('medicine_type')} options={opts.medicine_type} />
          <PickList label="المورد" value={st.supplier} onChange={set('supplier')} options={opts.supplier} />
          <PickList label="الشركة المنتجة" value={st.producer} onChange={set('producer')} options={opts.producer} />
          <Pick label="الشكل الصيدلي" value={st.category} onChange={set('category')} options={opts.category} />
          <PickList label="العائلة" value={st.family} onChange={set('family')} options={opts.family} width="w-36" />
          <Pick label="تصنيف الخصم" value={st.store_classif} onChange={set('store_classif')} options={opts.store_classif} />
          <Pick label="المنشأ" value={st.origin} onChange={set('origin')} options={[['local', 'محلي'], ['imported', 'مستورد']]} />
          <Pick label="ثلاجة" value={st.fridge} onChange={set('fridge')} options={[['yes', 'ثلاجة فقط'], ['no', 'بدون ثلاجة']]} />
          <Pick label="رصيد الفرع" value={st.stock === 'all' ? '' : st.stock} onChange={v => set('stock')(v || 'all')}
            options={[['with', 'به رصيد'], ['zero', 'رصيده صفر']]} />
          <label className="flex flex-col gap-1 text-xs text-content/60">
            اسم الصنف
            <input value={st.name} onChange={set('name')} placeholder="* أو % للبحث الجزئي" className={`${box} w-40`} />
          </label>
        </div>
      </details>
    </div>
  )
}

// on a proposal: how its lines were chosen + what was left out and why
export function IsrParamsSummary({ push }) {
  const p = push.params || {}
  if (p.rule !== 'softech') {
    return p.rule === 'engine'
      ? <div className="px-3 py-1.5 text-[11px] text-content/50 border-b border-line">القاعدة: فجوة المحرك (القديمة)</div>
      : null
  }
  const s = p.settings || {}
  const labels = push.stat_labels || {}
  const stats = p.stats || {}
  const order = ['considered', 'lines', 'no_need', 'below_fraction', 'hq_none', 'capped', 'above_order_point',
    'stock_filter', 'not_orderable']
  return (
    <div className="px-3 py-2 border-b border-line space-y-1.5 text-[11px]">
      <div className="flex flex-wrap gap-1.5">
        <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary">قاعدة SOFTECH</span>
        <span className="px-1.5 py-0.5 rounded bg-surface-2 text-content/70">
          {s.target === 'max' ? `حتى الحد الأقصى${s.coverage ? ` (${s.coverage} شهر)` : ' (المخزَّن)'}` : `حتى حد الطلب ${s.order_months} شهر`}
        </span>
        {s.hq_only && <span className="px-1.5 py-0.5 rounded bg-surface-2 text-content/70">فقط ما بالرئيسي</span>}
        {s.cap_hq && <span className="px-1.5 py-0.5 rounded bg-surface-2 text-content/70">لا تتجاوز رصيد الرئيسي</span>}
        {FILTER_KEYS.filter(k => s[k] && s[k] !== 'all').map(k => (
          <span key={k} className="px-1.5 py-0.5 rounded bg-amber-50 text-amber-800 border border-amber-200">{FILTER_LABELS[k]}: {String(s[k])}</span>
        ))}
        {p.as_of && <span className="text-content/50">أرصدة سيرفر 100 حتى {p.as_of}</span>}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-content/60">
        {order.filter(k => stats[k]).map(k => <span key={k}>{labels[k] || k}: <b className="text-content">{stats[k].toLocaleString('ar-EG')}</b></span>)}
      </div>
    </div>
  )
}
