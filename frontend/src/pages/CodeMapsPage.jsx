/**
 * CodeMapsPage.jsx — ترميزات SOFTECH (admin only, piece 4 — item & channel codes)
 *
 * What each SOFTECH code means to the system, in two editable tables:
 *   • قنوات البيع    — customer-type codes (ChannelBucketMap, person_type '10'):
 *                      group · بيع تعاقد · أولوية المتابعة. The KPI bucket shows read-only.
 *   • تصنيف الأصناف  — item-category codes (MedicineTypeMap): group · دواء · مستبعد من التخطيط.
 *
 * Every select / checkbox saves on change (PATCH) — no save button, no modal. The row shows
 * «جارٍ الحفظ…» while it saves and the server's Arabic refusal under it (e.g. the last
 * «دواء» category). The server owns every rule: the group list comes from the list response
 * (`choices.groups`), validation and the audit log live in apps/config/code_maps.py.
 * «غير مصنف» rows (a new SOFTECH code nobody classified) stay pinned on top whatever the sort.
 *
 * Keys (useGridKeyboard): ↑↓ move · Enter / M jump to the row's group select.
 */
import { Fragment, useCallback, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { codeMapsApi } from '../api/client'
import useGridKeyboard from '../hooks/useGridKeyboard'
import useSortableRows from '../hooks/useSortableRows'
import SortTh from '../components/SortTh'
import useHelpTab from '../help/useHelpTab'

const TABS = [
  { key: 'channels', label: 'قنوات البيع' },
  { key: 'item-types', label: 'تصنيف الأصناف' },
]
const UNCLASSIFIED = 'unclassified'
const RANKS = [1, 2, 3, 4]
const HINT = '⌨ ↑↓ تنقل · Enter أو M تعديل المجموعة · كل تغيير يُحفظ فورًا'
const num = v => (v == null ? '—' : Number(v).toLocaleString('en-US'))

function errText(e) {
  // status first: DRF's own 401 / 403 detail text is English — never show it
  const status = e?.response?.status
  if (status === 401) return 'انتهت الجلسة — سجّل الدخول مرة أخرى.'
  if (status === 403) return 'ليس لديك صلاحية لهذا الإجراء'
  const d = e?.response?.data
  if (d?.detail && typeof d.detail === 'string') return d.detail
  return 'تعذّر الحفظ — حاول مرة أخرى.'
}

const QUERIES = {
  'channels': { key: ['code-maps', 'channels'], list: codeMapsApi.channels, patch: codeMapsApi.patchChannel },
  'item-types': { key: ['code-maps', 'item-types'], list: codeMapsApi.itemTypes, patch: codeMapsApi.patchItemType },
}

/** Save-on-change for one table: per-row pending values (shown while the PATCH runs),
 *  per-row error text, and the confirmed row written back into the query cache. */
function useRowSaver(which) {
  const qc = useQueryClient()
  const { key, patch } = QUERIES[which]
  const [pending, setPending] = useState({})   // id -> { field: value } not yet confirmed
  const [errors, setErrors] = useState({})     // id -> server message
  const busy = useRef(new Set())               // rows with a PATCH in flight (sync guard)

  // A change on a row that is still saving is ignored (the controlled input snaps back);
  // the control stays enabled so focus — and the grid keyboard — stay where they were.
  const save = useCallback(async (row, data) => {
    if (busy.current.has(row.id)) return
    busy.current.add(row.id)
    setPending(p => ({ ...p, [row.id]: { ...p[row.id], ...data } }))
    setErrors(e => ({ ...e, [row.id]: '' }))
    try {
      const r = await patch(row.id, data)
      qc.setQueryData(key, old => (old ? { ...old, rows: old.rows.map(x => (x.id === row.id ? r.data : x)) } : old))
    } catch (e) {
      setErrors(er => ({ ...er, [row.id]: errText(e) }))
    } finally {
      busy.current.delete(row.id)
      setPending(p => {
        const cur = { ...p[row.id] }
        Object.keys(data).forEach(f => { delete cur[f] })
        const next = { ...p }
        if (Object.keys(cur).length) next[row.id] = cur; else delete next[row.id]
        return next
      })
    }
  }, [patch, qc, key])

  const value = useCallback((row, field) => {
    const p = pending[row.id]
    return p && field in p ? p[field] : row[field]
  }, [pending])

  return { save, value, saving: id => !!pending[id], error: id => errors[id] || '' }
}

/** «غير مصنف» rows pinned on top; the rest sorted by the clicked header. */
function usePinnedSort(rows, getValue, persistKey) {
  const pinned = useMemo(() => rows.filter(r => r.group === UNCLASSIFIED), [rows])
  const rest = useMemo(() => rows.filter(r => r.group !== UNCLASSIFIED), [rows])
  const { sorted, headerProps } = useSortableRows(rest, { getValue, persistKey })
  const display = useMemo(() => [...pinned, ...sorted], [pinned, sorted])
  return { display, headerProps }
}

function focusGroup(id) {
  document.querySelector(`[data-code-map-group="${id}"]`)?.focus()
}

function CodeCell({ row }) {
  return (
    <td className="p-2 whitespace-nowrap">
      <span className="font-mono" dir="ltr">{row.code || '—'}</span>
      {row.group === UNCLASSIFIED && (
        <span className="ms-2 inline-block text-xs rounded px-1.5 py-0.5 bg-amber-500/10 text-amber-700 dark:text-amber-300">
          غير مصنف
        </span>
      )}
    </td>
  )
}

function GroupSelect({ row, groups, saver }) {
  const current = saver.value(row, 'group')
  return (
    <select className="input py-1" value={current}
            data-code-map-group={row.id} aria-label={`مجموعة الكود ${row.code}`}
            onChange={e => saver.save(row, { group: e.target.value })}>
      {groups.filter(g => g.value !== UNCLASSIFIED || current === UNCLASSIFIED)
        .map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
    </select>
  )
}

function Check({ row, field, saver, label }) {
  return (
    <input type="checkbox" className="accent-brand-600 cursor-pointer" aria-label={`${label} — ${row.code}`}
           checked={!!saver.value(row, field)}
           onChange={e => saver.save(row, { [field]: e.target.checked })} />
  )
}

function StatusCell({ row, saver }) {
  return <td className="p-2 text-xs text-muted whitespace-nowrap">{saver.saving(row.id) ? 'جارٍ الحفظ…' : ''}</td>
}

function ErrorRow({ row, saver, colSpan }) {
  const msg = saver.error(row.id)
  if (!msg) return null
  return <tr><td colSpan={colSpan} className="px-3 pb-2 text-xs text-red-600">{msg}</td></tr>
}

function Shell({ query, kb, children, empty }) {
  if (query.isLoading) return <div className="card p-6 text-center text-muted">جارٍ التحميل…</div>
  if (query.isError) return <div className="card p-6 text-center text-red-600">تعذّر تحميل الأكواد.</div>
  return (
    <div data-tour="code-maps-main-table" className="card p-0 overflow-x-auto" {...kb.containerProps}>
      <table className="w-full text-sm">{children}</table>
      {empty && <div className="p-6 text-center text-muted">لا توجد أكواد.</div>}
    </div>
  )
}

// sort values: groups / buckets by their Arabic label, ticks as 1 / 0 (booleans don't sort as numbers)
const sortValue = (r, k) => {
  const v = k === 'group' ? r.group_label : k === 'bucket' ? r.bucket_label : r[k]
  return typeof v === 'boolean' ? Number(v) : v
}

function ChannelsTable({ query }) {
  const saver = useRowSaver('channels')
  const rows = useMemo(() => query.data?.rows || [], [query.data])
  const groups = query.data?.choices?.groups || []
  const { display, headerProps } = usePinnedSort(rows, sortValue, 'code-maps-channels')
  const kb = useGridKeyboard({ rows: display, getKey: r => r.id,
    onConfirm: r => focusGroup(r.id), onOpen: r => focusGroup(r.id) })
  const COLS = 8
  return (
    <Shell query={query} kb={kb} empty={!display.length}>
      <thead>
        <tr className="text-muted border-b border-line">
          <SortTh {...headerProps('code')} className="p-2 text-start">الكود</SortTh>
          <SortTh {...headerProps('label')} className="p-2 text-start">الاسم في SOFTECH</SortTh>
          <SortTh {...headerProps('group')} data-tour="code-maps-main-group" className="p-2 text-start">المجموعة</SortTh>
          <SortTh {...headerProps('is_contract_sale', 'number')} className="p-2 text-center">بيع تعاقد</SortTh>
          <SortTh {...headerProps('followup_rank', 'number')} className="p-2 text-start">أولوية المتابعة</SortTh>
          <SortTh {...headerProps('bucket')} data-tour="code-maps-main-kpi" className="p-2 text-start"
                  title="للعرض فقط — بنود KPI لا تُعدّل من هنا">بند KPI</SortTh>
          <SortTh {...headerProps('sales_90d', 'number')} className="p-2 text-end">مبيعات 90 يوم</SortTh>
          <th className="p-2" />
        </tr>
      </thead>
      <tbody>
        {display.map(r => {
          const rp = kb.rowProps(r)
          const rank = saver.value(r, 'followup_rank')
          return (
            <Fragment key={r.id}>
              <tr {...rp} aria-busy={saver.saving(r.id) || undefined} className={`border-b border-line ${rp.className}`}>
                <CodeCell row={r} />
                <td className="p-2">{r.label || '—'}</td>
                <td className="p-2"><GroupSelect row={r} groups={groups} saver={saver} /></td>
                <td className="p-2 text-center"><Check row={r} field="is_contract_sale" saver={saver} label="بيع تعاقد" /></td>
                <td className="p-2">
                  <select className="input py-1 w-20" value={rank ?? ''}
                          aria-label={`أولوية المتابعة — ${r.code}`}
                          onChange={e => saver.save(r, { followup_rank: e.target.value === '' ? null : Number(e.target.value) })}>
                    <option value="">—</option>
                    {RANKS.map(n => <option key={n} value={n}>{n}</option>)}
                  </select>
                </td>
                <td className="p-2 text-muted">{r.bucket_label || '—'}</td>
                <td className="p-2 text-end tabular-nums">{num(r.sales_90d)}</td>
                <StatusCell row={r} saver={saver} />
              </tr>
              <ErrorRow row={r} saver={saver} colSpan={COLS} />
            </Fragment>
          )
        })}
      </tbody>
    </Shell>
  )
}

function ItemTypesTable({ query }) {
  const saver = useRowSaver('item-types')
  const rows = useMemo(() => query.data?.rows || [], [query.data])
  const groups = query.data?.choices?.groups || []
  const { display, headerProps } = usePinnedSort(rows, sortValue, 'code-maps-item-types')
  const kb = useGridKeyboard({ rows: display, getKey: r => r.id,
    onConfirm: r => focusGroup(r.id), onOpen: r => focusGroup(r.id) })
  const COLS = 7
  return (
    <Shell query={query} kb={kb} empty={!display.length}>
      <thead>
        <tr className="text-muted border-b border-line">
          <SortTh {...headerProps('code')} className="p-2 text-start">الكود</SortTh>
          <SortTh {...headerProps('label')} className="p-2 text-start">الاسم في SOFTECH</SortTh>
          <SortTh {...headerProps('group')} data-tour="code-maps-main-group" className="p-2 text-start">المجموعة</SortTh>
          <SortTh {...headerProps('is_medicine', 'number')} data-tour="code-maps-main-medicine" className="p-2 text-center">دواء</SortTh>
          <SortTh {...headerProps('excluded_from_planning', 'number')} className="p-2 text-center">مستبعد من التخطيط</SortTh>
          <SortTh {...headerProps('item_count', 'number')} className="p-2 text-end">عدد الأصناف</SortTh>
          <th className="p-2" />
        </tr>
      </thead>
      <tbody>
        {display.map(r => {
          const rp = kb.rowProps(r)
          return (
            <Fragment key={r.id}>
              <tr {...rp} aria-busy={saver.saving(r.id) || undefined} className={`border-b border-line ${rp.className}`}>
                <CodeCell row={r} />
                <td className="p-2">{r.label || '—'}</td>
                <td className="p-2"><GroupSelect row={r} groups={groups} saver={saver} /></td>
                <td className="p-2 text-center"><Check row={r} field="is_medicine" saver={saver} label="دواء" /></td>
                <td className="p-2 text-center"><Check row={r} field="excluded_from_planning" saver={saver} label="مستبعد من التخطيط" /></td>
                <td className="p-2 text-end tabular-nums">{num(r.item_count)}</td>
                <StatusCell row={r} saver={saver} />
              </tr>
              <ErrorRow row={r} saver={saver} colSpan={COLS} />
            </Fragment>
          )
        })}
      </tbody>
    </Shell>
  )
}

export default function CodeMapsPage() {
  const [tab, setTab] = useState('channels')
  useHelpTab(tab)
  const channels = useQuery({ queryKey: QUERIES.channels.key, queryFn: () => QUERIES.channels.list().then(r => r.data) })
  const itemTypes = useQuery({ queryKey: QUERIES['item-types'].key, queryFn: () => QUERIES['item-types'].list().then(r => r.data) })
  const unclassified = {
    'channels': (channels.data?.rows || []).filter(r => r.group === UNCLASSIFIED).length,
    'item-types': (itemTypes.data?.rows || []).filter(r => r.group === UNCLASSIFIED).length,
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">🏷️ ترميزات SOFTECH</h1>
        <p className="text-sm text-muted">
          معنى كل كود قناة بيع وتصنيف صنف من SOFTECH. الأسماء تأتي من SOFTECH؛ أي تغيير هنا يُحفظ فورًا ويُسجّل.
        </p>
      </div>

      <div data-tour="code-maps-main-tabs" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
                  className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === t.key ? 'border-brand-600 text-brand-600 font-semibold' : 'border-transparent text-muted'}`}>
            {t.label}
            {unclassified[t.key] > 0 && (
              <span className="ms-1 text-xs text-amber-700 dark:text-amber-300">({unclassified[t.key]} غير مصنف)</span>
            )}
          </button>
        ))}
      </div>

      {tab === 'channels' ? <ChannelsTable query={channels} /> : <ItemTypesTable query={itemTypes} />}

      <div className="text-xs text-faint">{HINT}</div>
    </div>
  )
}
