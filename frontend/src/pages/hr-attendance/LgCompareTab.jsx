/**
 * LgCompareTab — «مقارنة لينكد جيتس»: the Linked Gates trial (design 2026-11-20 §5.4).
 *
 * Punches per machine and day by category, then the employee-days whose figures differ from ours,
 * each with its reason in plain words (the server sends the words with the codes). Display only:
 * the server computes every figure and category; this tab sorts and shows them. The machine
 * mapping (Manage) is an inline select per row with its own «حفظ» — choosing (or arrowing through
 * the list) changes nothing until saved; no modal; the server checks the level and audits.
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useSortableRows from '../../hooks/useSortableRows'
import { BTN, Empty, Notice, TH, blobErrText, clock, download, errText, hm, weekdayOf } from './shared'

const CATEGORIES = ['matched', 'lg_manual', 'missing_from_pull', 'not_yet_in_lg', 'missing_in_lg']
const CAT_TONE = {
  matched: 'text-emerald-700', lg_manual: 'text-gray-600', missing_from_pull: 'text-red-600 font-bold',
  not_yet_in_lg: 'text-gray-500', missing_in_lg: 'text-amber-700 font-bold',
}
const MACHINE_KEYS = ['date', 'name', ...CATEGORIES]
const DAY_KEYS = ['hr_number', 'name_ar', 'date', 'ours_minutes', 'lg_minutes', 'minutes_diff', 'reason']

const dayKey = r => `${r.employee_id}-${r.date}`
const machineKey = r => `${r.device ?? 'none'}-${r.name}-${r.date}`

export default function LgCompareTab({ month, setMonth, access, onOpenDays }) {
  const [exportErr, setExportErr] = useState('')
  const [exporting, setExporting] = useState(false)
  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-attendance', 'lg-compare', month],
    queryFn: () => hrAttendanceApi.lgCompare({ month }).then(r => r.data),
  })

  async function exportXlsx() {
    setExporting(true); setExportErr('')
    try {
      const res = await hrAttendanceApi.exportLgCompare({ month })
      download(res, `attendance-lg-compare-${month}.xlsx`)
    } catch (e) { setExportErr(await blobErrText(e)) }
    setExporting(false)
  }

  if (data && data.enabled === false) {
    return (
      <div className="space-y-4">
        <div className="bg-white rounded-xl border border-gray-200 p-6 text-sm text-gray-500 text-center">
          مقارنة لينكد جيتس متوقفة (المفتاح مغلق). الأيام تُحسب من بصمات ماكيناتنا فقط.
        </div>
        {access.can_manage && <DeviceMapping />}
      </div>
    )
  }

  const official = data?.official
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-2 text-sm">
        <label className="flex flex-col text-xs text-gray-500">الشهر
          <input type="month" value={month} onChange={e => e.target.value && setMonth(e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
        </label>
        {access.can_export && (
          <button type="button" onClick={exportXlsx} disabled={exporting}
            className={`${BTN} bg-white border border-gray-200 text-gray-700 hover:bg-gray-50 py-1.5`}>
            {exporting ? '⏳ جارٍ التجهيز…' : '📥 تصدير Excel'}
          </button>
        )}
        {official && (
          <span className="text-xs text-gray-500">
            المعتمد الآن: <b className="text-gray-800">{official === 'lg' ? 'لينكد جيتس' : 'نظامنا'}</b>
          </span>
        )}
        <Notice>{exportErr}</Notice>
      </div>

      {error && <div className="py-6 text-center text-sm text-red-600">{errText(error)}</div>}
      {isLoading && <Empty>جاري التحميل…</Empty>}
      {data?.enabled && (
        <>
          <MachinesGrid rows={data.machines} labels={data.categories} />
          <DaysGrid rows={data.days} reasons={data.reasons} noReason={data.no_reason} official={official}
            onOpenDays={onOpenDays} />
        </>
      )}
      {access.can_manage && <DeviceMapping />}
    </div>
  )
}

function MachinesGrid({ rows, labels }) {
  const { sorted, headerProps } = useSortableRows(rows, {
    defaultSort: { key: 'date', dir: 'asc', type: 'date' }, persistKey: 'hr-attendance-lg-machines', keys: MACHINE_KEYS })
  return (
    <section>
      <h2 className="text-sm font-bold text-gray-800 mb-1.5">البصمات حسب الماكينة واليوم</h2>
      <div data-tour="hr-attendance-lg-machines" className="bg-white rounded-xl border border-gray-200 overflow-x-auto max-h-[28rem]">
        <table className="w-full text-sm">
          <thead className="sticky top-0">
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <SortTh className={TH} {...headerProps('date', 'date')}>اليوم</SortTh>
              <SortTh className={TH} {...headerProps('name', 'text')}>الماكينة</SortTh>
              {CATEGORIES.map(c => (
                <SortTh key={c} className={TH} {...headerProps(c, 'number')}>{labels?.[c]?.ar || c}</SortTh>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => (
              <tr key={machineKey(r)} className="border-b border-gray-100">
                <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date} <span className="text-gray-400 text-xs">{weekdayOf(r.date)}</span></td>
                <td className="px-3 py-1.5">{r.name}</td>
                {CATEGORIES.map(c => (
                  <td key={c} className={`px-3 py-1.5 tabular-nums ${r[c] ? CAT_TONE[c] : 'text-gray-300'}`}>{r[c]}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <Empty>لا توجد بصمات في هذا الشهر</Empty>}
      </div>
    </section>
  )
}

function DaysGrid({ rows, reasons, noReason, official, onOpenDays }) {
  const reasonText = useCallback(
    r => (r.reasons.length ? r.reasons.map(c => reasons?.[c]?.ar || c).join('، ') : ''), [reasons])
  const getValue = useCallback((r, key) => {
    if (key === 'ours_minutes') return r.ours.minutes
    if (key === 'lg_minutes') return r.lg.minutes
    if (key === 'reason') return reasonText(r)
    return r[key]
  }, [reasonText])
  const { sorted, headerProps } = useSortableRows(rows, {
    defaultSort: { key: 'date', dir: 'asc', type: 'date' }, getValue, persistKey: 'hr-attendance-lg-days', keys: DAY_KEYS })
  const kb = useGridKeyboard({ rows: sorted, getKey: dayKey, onConfirm: r => onOpenDays(r.employee_id) })
  const tag = side => (official === side ? <span className="ms-1 text-[10px] font-bold text-primary">المعتمد</span> : null)
  const lgCols = (
    <>
      <th className={TH}>لينكد جيتس{tag('lg')}</th>
      <SortTh className={TH} {...headerProps('lg_minutes', 'number')}>ساعاته</SortTh>
    </>
  )
  const ourCols = (
    <>
      <th className={TH}>نظامنا{tag('ours')}</th>
      <SortTh className={TH} {...headerProps('ours_minutes', 'number')}>ساعاتنا</SortTh>
    </>
  )
  const span = (side, r) => {
    const v = r[side]
    return (
      <>
        <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{clock(v.in)} → {clock(v.out)}</td>
        <td className="px-3 py-1.5 tabular-nums">{hm(v.minutes)}</td>
      </>
    )
  }
  return (
    <section>
      <h2 className="text-sm font-bold text-gray-800 mb-1.5">الأيام المختلفة ({rows.length})</h2>
      <div {...kb.containerProps} data-tour="hr-attendance-lg-days"
        className={`bg-white rounded-xl border border-gray-200 overflow-x-auto max-h-[32rem] ${kb.containerProps.className}`}>
        <table className="w-full text-sm">
          <thead className="sticky top-0">
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <SortTh className={TH} {...headerProps('hr_number', 'text')}>الرقم الوظيفي</SortTh>
              <SortTh className={TH} {...headerProps('name_ar', 'text')}>الاسم</SortTh>
              <SortTh className={TH} {...headerProps('date', 'date')}>اليوم</SortTh>
              {official === 'ours' ? <>{ourCols}{lgCols}</> : <>{lgCols}{ourCols}</>}
              <SortTh className={TH} {...headerProps('minutes_diff', 'number')}>الفرق</SortTh>
              <SortTh className={TH} {...headerProps('reason', 'text')}>السبب</SortTh>
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const { className, ...rest } = kb.rowProps(r)
              const why = reasonText(r)
              return (
                <tr key={dayKey(r)} {...rest} onDoubleClick={() => onOpenDays(r.employee_id)}
                  className={`border-b border-gray-100 hover:bg-gray-50 cursor-pointer ${className}`} title="Enter يفتح أيام الموظف">
                  <td className="px-3 py-1.5 tabular-nums">{r.hr_number}</td>
                  <td className="px-3 py-1.5 font-medium text-gray-900">{r.name_ar}</td>
                  <td className="px-3 py-1.5 tabular-nums whitespace-nowrap">{r.date} <span className="text-gray-400 text-xs">{weekdayOf(r.date)}</span></td>
                  {official === 'ours' ? <>{span('ours', r)}{span('lg', r)}</> : <>{span('lg', r)}{span('ours', r)}</>}
                  <td className="px-3 py-1.5 tabular-nums" dir="ltr">{r.minutes_diff > 0 ? '+' : ''}{r.minutes_diff < 0 ? '-' : ''}{hm(Math.abs(r.minutes_diff))}</td>
                  <td className={`px-3 py-1.5 text-xs ${why ? 'text-gray-700' : 'text-gray-400'}`}>{why || noReason?.ar}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && <Empty>لا يوجد اختلاف في هذا الشهر</Empty>}
      </div>
      <p className="mt-1 text-[11px] text-gray-400">⌨ ↑↓ تنقل · Enter يفتح أيام الموظف · الفرق = ساعاتنا − ساعات لينكد جيتس</p>
    </section>
  )
}

/** Manage only (the server checks too): tie each Linked Gates machine to one of ours. Audited. */
function DeviceMapping() {
  const qc = useQueryClient()
  const [msg, setMsg] = useState({})
  const [draft, setDraft] = useState({})   // lg_device_id -> chosen '' | id (string), not yet saved
  const lg = useQuery({ queryKey: ['hr-attendance', 'lg-devices'],
                        queryFn: () => hrAttendanceApi.lgDevices().then(r => r.data.rows) })
  const ours = useQuery({ queryKey: ['hr-attendance', 'devices'],
                          queryFn: () => hrAttendanceApi.devices().then(r => r.data) })
  const options = useMemo(() => ours.data?.rows || [], [ours.data])
  const map = useMutation({
    mutationFn: ({ lgId, deviceId }) => hrAttendanceApi.mapLgDevice(lgId, deviceId),
    onSuccess: (_r, v) => {
      setMsg(m => ({ ...m, [v.lgId]: { ok: 'حُفظ' } }))
      setDraft(d => { const next = { ...d }; delete next[v.lgId]; return next })
      qc.invalidateQueries({ queryKey: ['hr-attendance'] })
    },
    onError: (e, v) => setMsg(m => ({ ...m, [v.lgId]: { err: errText(e) } })),
  })
  const rows = lg.data || []
  const { sorted, headerProps } = useSortableRows(rows, {
    defaultSort: { key: 'lg_device_id', dir: 'asc', type: 'number' }, persistKey: 'hr-attendance-lg-map',
    keys: ['lg_device_id', 'name', 'device_name'] })
  return (
    <section>
      <h2 className="text-sm font-bold text-gray-800 mb-1.5">ربط ماكينات لينكد جيتس بماكيناتنا</h2>
      <div data-tour="hr-attendance-lg-map" className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <SortTh className={TH} {...headerProps('lg_device_id', 'number')}>رقمها في لينكد جيتس</SortTh>
              <SortTh className={TH} {...headerProps('name', 'text')}>اسمها هناك</SortTh>
              <SortTh className={TH} {...headerProps('device_name', 'text')}>ماكينتنا</SortTh>
              <th className={TH}></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => {
              const saved = r.device == null ? '' : String(r.device)
              const chosen = draft[r.lg_device_id] ?? saved
              const changed = chosen !== saved
              const save = () => map.mutate({ lgId: r.lg_device_id, deviceId: chosen ? Number(chosen) : null })
              return (
              <tr key={r.lg_device_id} className="border-b border-gray-100">
                <td className="px-3 py-1.5 tabular-nums">{r.lg_device_id}</td>
                <td className="px-3 py-1.5">{r.name || '—'}{!r.lg_status && <span className="ms-1 text-xs text-gray-400">(غير فعّالة هناك)</span>}</td>
                <td className="px-3 py-1.5">
                  <select value={chosen} disabled={map.isPending}
                    onChange={e => {
                      const value = e.target.value
                      setDraft(d => ({ ...d, [r.lg_device_id]: value }))
                      setMsg(m => ({ ...m, [r.lg_device_id]: {} }))
                    }}
                    onKeyDown={e => { if (e.key === 'Enter' && changed) save() }}
                    className="border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
                    <option value="">— غير مربوطة —</option>
                    {options.map(d => <option key={d.id} value={String(d.id)}>{d.name}{d.is_active ? '' : ' (مغلقة)'}</option>)}
                  </select>
                </td>
                <td className="px-3 py-1.5 whitespace-nowrap">
                  {changed && (
                    <>
                      <button type="button" onClick={save} disabled={map.isPending}
                        className="px-2 py-1 rounded-md bg-primary text-white text-xs disabled:opacity-50">حفظ</button>
                      <button type="button" disabled={map.isPending}
                        onClick={() => setDraft(d => { const next = { ...d }; delete next[r.lg_device_id]; return next })}
                        className="ms-1 px-2 py-1 rounded-md text-gray-500 text-xs hover:bg-gray-100">تراجع</button>
                    </>
                  )}
                  <Notice kind="ok">{msg[r.lg_device_id]?.ok}</Notice>
                  <Notice>{msg[r.lg_device_id]?.err}</Notice>
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
        {lg.isLoading && <Empty>جاري التحميل…</Empty>}
        {lg.error && <div className="py-6 text-center text-sm text-red-600">{errText(lg.error)}</div>}
        {!lg.isLoading && !lg.error && rows.length === 0 && <Empty>لم تصل ماكينات لينكد جيتس بعد</Empty>}
      </div>
    </section>
  )
}
