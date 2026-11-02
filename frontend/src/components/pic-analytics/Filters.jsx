/**
 * Filters — the PIC Analytics filter bar (doc 33 §6). Values live in the URL (set by the
 * page). A named branch manager gets the branch filter locked to his own branches — the
 * server enforces it anyway; the lock only avoids offering choices that would be refused.
 */
const CHANNELS = [
  ['cash', 'نقدي'], ['delivery', 'توصيل'], ['regular', 'عادي'], ['credit', 'آجل'],
  ['insurance', 'تأمين'], ['other', 'أخرى'], ['exclude', 'مستبعدة من مؤشرات KPI'],
]
const SEGMENTS = [
  ['vip', 'VIP'], ['loyal', 'مخلص'], ['regular', 'عادي'], ['at_risk', 'في خطر'],
  ['dormant', 'نائم'], ['new', 'جديد'], ['churned', 'مفقود'],
]
const FREQUENCY = [
  ['m1', 'كل شهر أو أقل'], ['m2', 'كل شهرين'], ['m3', 'كل 3 شهور'],
  ['m4_6', 'كل 4–6 شهور'], ['m7_12', 'كل 7–12 شهر'], ['y1plus', 'سنة أو أكثر'],
]

export default function Filters({ values, onChange, onClear, branches, access, children }) {
  const locked = !!access?.branch_manager
  const allowed = access?.branch_ids
  const branchOptions = (branches || []).filter(b => !locked || (allowed || []).includes(b.id))
  const input = 'input-field text-xs py-1.5'
  const set = k => e => onChange(k, e.target.value)
  return (
    <div className="flex flex-wrap gap-2 items-center" data-tour="pic-analytics-filters">
      <input type="date" className={`${input} w-36`} value={values.from || ''} onChange={set('from')} title="من" />
      <input type="date" className={`${input} w-36`} value={values.to || ''} onChange={set('to')} title="إلى" />
      <select className={`${input} w-44`} value={values.branch || ''} onChange={set('branch')}
              disabled={locked && branchOptions.length <= 1} data-tour="pic-analytics-branch-filter"
              title={locked ? 'فروعك فقط' : undefined}>
        {!locked && <option value="">كل الفروع</option>}
        {locked && branchOptions.length > 1 && <option value="">كل فروعي</option>}
        {branchOptions.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
      </select>
      <input className={`${input} w-28`} placeholder="البائع (كود)" value={values.salesperson || ''} onChange={set('salesperson')} />
      <select className={`${input} w-32`} value={values.channel || ''} onChange={set('channel')}>
        <option value="">كل القنوات</option>
        {CHANNELS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <input className={`${input} w-24`} placeholder="كود الفئة" value={values.category || ''} onChange={set('category')} />
      <select className={`${input} w-28`} value={values.segment || ''} onChange={set('segment')}>
        <option value="">كل الشرائح</option>
        {SEGMENTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <input className={`${input} w-28`} placeholder="نوع العميل (كود)" value={values.customer_type || ''} onChange={set('customer_type')} />
      <select className={`${input} w-36`} value={values.frequency || ''} onChange={set('frequency')}>
        <option value="">كل دورات الشراء</option>
        {FREQUENCY.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <button onClick={onClear} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-clear">مسح</button>
      {children}
    </div>
  )
}
