/**
 * Filters — the PIC Analytics filter bar (doc 33 §6). Values live in the URL (set by the
 * page). A named branch manager gets the branch filter locked to his own branches — the
 * server enforces it anyway; the lock only avoids offering choices that would be refused.
 */
// A select fed by the options endpoint. A value that is in the URL but not offered (e.g. an old
// link) stays visible as its raw code so the filter is never silently hidden.
function Pick({ cls, value, onChange, all, rows }) {
  const list = rows || []
  const missing = value && !list.some(r => r.code === value)
  return (
    <select className={cls} value={value || ''} onChange={onChange}>
      <option value="">{all}</option>
      {missing && <option value={value}>{value}</option>}
      {list.map(r => <option key={r.code} value={r.code}>{r.label}</option>)}
    </select>
  )
}

export default function Filters({ values, onChange, onClear, branches, access, options, children }) {
  const opts = options || {}
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
      <Pick cls={`${input} w-36`} value={values.salesperson} onChange={set('salesperson')} all="كل البائعين" rows={opts.salespeople} />
      <Pick cls={`${input} w-32`} value={values.channel} onChange={set('channel')} all="كل القنوات" rows={opts.channels} />
      <Pick cls={`${input} w-32`} value={values.category} onChange={set('category')} all="كل الفئات" rows={opts.categories} />
      <Pick cls={`${input} w-28`} value={values.segment} onChange={set('segment')} all="كل الشرائح" rows={opts.segments} />
      <Pick cls={`${input} w-32`} value={values.customer_type} onChange={set('customer_type')} all="كل أنواع العملاء" rows={opts.customer_types} />
      <Pick cls={`${input} w-36`} value={values.frequency} onChange={set('frequency')} all="كل دورات الشراء" rows={opts.frequency} />
      {opts.agents && (
        <Pick cls={`${input} w-40`} value={values.agent} onChange={set('agent')} all="كل موظفي الاتصال" rows={opts.agents.map(a => ({ code: a.ext, label: a.label }))} />
      )}
      <button onClick={onClear} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-clear">مسح</button>
      {children}
    </div>
  )
}
