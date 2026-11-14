/**
 * Filters — the PIC Analytics filter bar (doc 33 §6). Values live in the URL (set by the
 * page). A named branch manager gets the branch filter locked to his own branches — the
 * server enforces it anyway; the lock only avoids offering choices that would be refused.
 *
 * Every list filter is a multi-select: the URL keeps a comma list (?salesperson=u1,u2), so an old
 * single-value link still pre-fills one tick. Nothing ticked = no filter.
 */
import MultiSelectFilter from '../MultiSelectFilter'
import BranchMultiSelect from '../BranchMultiSelect'

const listOf = (v) => String(v || '').split(',').map(s => s.trim()).filter(Boolean)

// A multi-select fed by the options endpoint. A value that is in the URL but not offered (e.g. an old
// link) stays visible as its raw code so the filter is never silently hidden.
function Pick({ cls, value, onChange, all, rows }) {
  const list = rows || []
  const selected = listOf(value)
  const missing = selected.filter(v => !list.some(r => r.code === v))
  const options = [...missing.map(v => ({ code: v, name: v })), ...list.map(r => ({ code: r.code, name: r.label }))]
  return (
    <MultiSelectFilter className={cls} showCode={false} allLabel={all} menuClassName="min-w-[240px]"
      options={options} selected={selected} onChange={codes => onChange(codes.join(','))} />
  )
}

export default function Filters({ values, onChange, onClear, branches, showClosed, closedToggle, access, options, children }) {
  const opts = options || {}
  const locked = !!access?.branch_manager
  const allowed = access?.branch_ids
  const branchOptions = (branches || []).filter(b => !locked || (allowed || []).includes(b.id))
  const input = 'input-field text-xs py-1.5'
  const set = k => e => onChange(k, e.target.value)
  const setList = k => v => onChange(k, v)
  const branchSel = listOf(values.branch).map(Number).filter(n => Number.isInteger(n) && n > 0)
  return (
    <div className="flex flex-wrap gap-2 items-center" data-tour="pic-analytics-filters">
      <input type="date" className={`${input} w-36`} value={values.from || ''} onChange={set('from')} title="من" />
      <input type="date" className={`${input} w-36`} value={values.to || ''} onChange={set('to')} title="إلى" />
      <BranchMultiSelect className="w-44" branches={branchOptions} showClosed={showClosed} selected={branchSel}
        onChange={ids => onChange('branch', ids.join(','))}
        allLabel={locked ? 'كل فروعي' : 'كل الفروع'}
        disabled={locked && branchOptions.length <= 1} dataTour="pic-analytics-branch-filter" />
      {closedToggle}
      <Pick cls="w-36" value={values.salesperson} onChange={setList('salesperson')} all="كل البائعين" rows={opts.salespeople} />
      <Pick cls="w-32" value={values.channel} onChange={setList('channel')} all="كل القنوات" rows={opts.channels} />
      <Pick cls="w-32" value={values.category} onChange={setList('category')} all="كل الفئات" rows={opts.categories} />
      <Pick cls="w-28" value={values.segment} onChange={setList('segment')} all="كل الشرائح" rows={opts.segments} />
      <Pick cls="w-32" value={values.customer_type} onChange={setList('customer_type')} all="كل أنواع العملاء" rows={opts.customer_types} />
      <Pick cls="w-36" value={values.frequency} onChange={setList('frequency')} all="كل دورات الشراء" rows={opts.frequency} />
      {opts.agents && (
        <Pick cls="w-40" value={values.agent} onChange={setList('agent')} all="كل موظفي الاتصال" rows={opts.agents.map(a => ({ code: a.ext, label: a.label }))} />
      )}
      <button onClick={onClear} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-clear">مسح</button>
      {children}
    </div>
  )
}
