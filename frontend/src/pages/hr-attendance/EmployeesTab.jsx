/**
 * EmployeesTab — the employee list, what the machines call each ID, and the login-link review.
 *
 * Link suggestions are by NAME only (never a phone or number) and nothing links until a person
 * confirms. The review grid is keyboard-driven (useGridKeyboard): ↑↓ move, Enter confirms the first
 * suggestion of the active row. Controls for Manage-level actions are hidden without can_manage;
 * the server checks the level again on every call.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import useServerSort from '../../hooks/useServerSort'
import { BTN, Empty, Notice, ReasonRow, TH, errText } from './shared'

const SORT_KEYS = ['hr_number', 'name_ar', 'department', 'branch', 'status', 'employee_type']
const getKey = r => r.id
const STATUS = { active: 'على رأس العمل', left: 'ترك العمل' }
const TYPE = { payroll: 'في كشف الرواتب', non_payroll: 'خارج كشف الرواتب' }
const GENERIC_MSG = 'مشترك'

export default function EmployeesTab({ access, onOpenDays }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('active')
  const [linked, setLinked] = useState('')
  const [ordering, setOrdering] = useState('')
  const [msg, setMsg] = useState({})             // { [employeeId]: { text, staff } }
  const [asking, setAsking] = useState(null)     // { id, kind: 'hold' | 'notgeneric', staff? }
  const { headerProps } = useServerSort(ordering, setOrdering, { allowed: SORT_KEYS })
  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-attendance', 'employees', q, status, linked, ordering],
    queryFn: () => hrAttendanceApi.employees({ q: q || undefined, status: status || undefined,
      linked: linked || undefined, ordering: ordering || undefined }).then(r => r.data),
  })
  const rows = useMemo(() => data?.rows || [], [data])
  const done = () => qc.invalidateQueries({ queryKey: ['hr-attendance'] })
  const fail = (id, staff) => e => setMsg(m => ({ ...m, [id]: { text: errText(e), staff } }))
  const clear = id => setMsg(m => { const n = { ...m }; delete n[id]; return n })

  const link = useMutation({
    mutationFn: ({ id, staff }) => hrAttendanceApi.link(id, staff),
    onSuccess: (_r, v) => { clear(v.id); done() }, onError: (e, v) => fail(v.id, v.staff)(e) })
  const reject = useMutation({
    mutationFn: ({ id, staff }) => hrAttendanceApi.rejectLink(id, staff),
    onSuccess: (_r, v) => { clear(v.id); done() }, onError: (e, v) => fail(v.id)(e) })
  const unlink = useMutation({
    mutationFn: ({ id }) => hrAttendanceApi.unlink(id),
    onSuccess: (_r, v) => { clear(v.id); done() }, onError: (e, v) => fail(v.id)(e) })
  const generic = useMutation({
    mutationFn: ({ staff }) => hrAttendanceApi.genericLogin(staff),
    onSuccess: (_r, v) => { clear(v.id); done() }, onError: (e, v) => fail(v.id)(e) })
  const hold = useMutation({
    mutationFn: ({ id, hold: on, reason }) => hrAttendanceApi.hold(id, { hold: on, reason }),
    onSuccess: (_r, v) => { setAsking(null); clear(v.id); done() }, onError: (e, v) => fail(v.id)(e) })
  const notGeneric = useMutation({
    mutationFn: ({ staff, reason }) => hrAttendanceApi.notGenericLogin({ staff, reason }),
    onSuccess: (_r, v) => { setAsking(null); clear(v.id); done() }, onError: (e, v) => fail(v.id)(e) })

  const canManage = access.can_manage
  const kb = useGridKeyboard({
    rows, getKey, enabled: canManage,
    onConfirm: r => { const s = r.suggestions?.[0]; if (s && !r.staff) link.mutate({ id: r.id, staff: s.staff_id }) },
  })

  return (
    <div>
      <div className="flex flex-wrap items-end gap-2 mb-3 text-sm" data-tour="hr-attendance-employees-filters">
        <label className="flex flex-col text-xs text-gray-500">بحث
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="الاسم أو الرقم الوظيفي"
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white" />
        </label>
        <label className="flex flex-col text-xs text-gray-500">الحالة
          <select value={status} onChange={e => setStatus(e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
            <option value="active">على رأس العمل</option>
            <option value="left">تركوا العمل</option>
            <option value="">الكل</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-gray-500">ربط الحساب
          <select value={linked} onChange={e => setLinked(e.target.value)}
            className="mt-0.5 border border-gray-200 rounded-md px-2 py-1 text-sm bg-white">
            <option value="">الكل</option>
            <option value="no">غير مرتبط (للمراجعة)</option>
            <option value="yes">مرتبط</option>
          </select>
        </label>
      </div>

      <div {...kb.containerProps} data-tour="hr-attendance-employees-grid"
        className={`bg-white rounded-xl border border-gray-200 overflow-x-auto ${kb.containerProps.className}`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <SortTh className={TH} {...headerProps('hr_number', 'text')}>الرقم الوظيفي</SortTh>
              <SortTh className={TH} {...headerProps('name_ar', 'text')}>الاسم / الاسم على الماكينة</SortTh>
              <SortTh className={TH} {...headerProps('department', 'text')}>القسم</SortTh>
              <SortTh className={TH} {...headerProps('branch', 'text')}>الفرع</SortTh>
              <SortTh className={TH} {...headerProps('status', 'text')}>الحالة</SortTh>
              <th className={TH}>حساب الدخول</th>
              <th className={TH}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const m = msg[r.id]
              const isAsking = asking?.id === r.id
              return (
                <EmployeeRow key={r.id} r={r} canManage={canManage} m={m} rowProps={kb.rowProps(r)}
                  isAsking={isAsking} asking={asking} setAsking={setAsking}
                  onOpenDays={onOpenDays}
                  actions={{ link, reject, unlink, generic, hold, notGeneric }} />
              )
            })}
          </tbody>
        </table>
        {isLoading && <Empty>جاري التحميل…</Empty>}
        {error && <div className="py-10 text-center text-sm text-red-600">{errText(error)}</div>}
        {!isLoading && !error && rows.length === 0 && <Empty>لا يوجد موظفون بهذه الفلاتر</Empty>}
      </div>
      {canManage && <p className="mt-2 text-[11px] text-gray-400">⌨ ↑↓ تنقل · Enter يربط أول اقتراح في الصف</p>}
    </div>
  )
}

function EmployeeRow({ r, canManage, m, rowProps, isAsking, asking, setAsking, onOpenDays, actions }) {
  const { link, reject, unlink, generic, hold, notGeneric } = actions
  const busy = [link, reject, unlink, generic, hold, notGeneric].some(a => a.isPending)
  const genericRefused = m?.staff && m.text.includes(GENERIC_MSG)
  const { className, ...rest } = rowProps
  return (
    <>
      <tr {...rest} className={`border-b border-gray-100 align-top ${className}`}>
        <td className="px-3 py-2 tabular-nums">{r.hr_number}</td>
        <td className="px-3 py-2">
          <button type="button" onClick={() => onOpenDays(r.id)} className="font-medium text-gray-900 hover:text-primary text-start">
            {r.name_ar}</button>
          {r.machine_names.length > 0 && (
            <div className="text-xs text-gray-500">على الماكينة: {r.machine_names.join('، ')}</div>
          )}
          {r.conflict && (
            <div className={`text-xs ${r.conflict_confirmed ? 'text-gray-400' : 'text-amber-700'}`}>
              {r.conflict_confirmed ? 'تعارض أسماء — مؤكد' : 'تعارض أسماء — القرار في تبويب «مشاكل»'}</div>
          )}
          {r.hold_resolution && <div className="text-xs text-amber-700">بصماته معلّقة: {r.hold_reason}</div>}
        </td>
        <td className="px-3 py-2 text-gray-600">{r.department || '—'}</td>
        <td className="px-3 py-2 text-gray-600">{r.branch_name || '—'}</td>
        <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">{STATUS[r.status] || r.status}
          <div className="text-gray-400">{TYPE[r.employee_type] || ''}</div></td>
        <td className="px-3 py-2">
          {r.staff
            ? <span className="text-emerald-700">{r.staff.name}</span>
            : r.suggestions.length === 0
              ? <span className="text-xs text-gray-400">لا اقتراح</span>
              : (
                <ul className="space-y-1">
                  {r.suggestions.map(s => (
                    <li key={s.staff_id} className="flex flex-wrap items-center gap-1 text-xs">
                      <span className="font-medium">{s.name}</span>
                      <span className="text-gray-400">({s.reason})</span>
                      {canManage && (
                        <>
                          <button type="button" disabled={busy} onClick={() => link.mutate({ id: r.id, staff: s.staff_id })}
                            className={`${BTN} bg-primary text-white`}>ربط</button>
                          <button type="button" disabled={busy} onClick={() => reject.mutate({ id: r.id, staff: s.staff_id })}
                            className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>ليس هو</button>
                          <button type="button" disabled={busy} onClick={() => generic.mutate({ id: r.id, staff: s.staff_id })}
                            title="حساب يستخدمه أكثر من شخص — لا يُربط بموظف"
                            className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>حساب مشترك</button>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
              )}
          {m && <div><Notice>{m.text}</Notice></div>}
          {canManage && genericRefused && !isAsking && (
            <button type="button" onClick={() => setAsking({ id: r.id, kind: 'notgeneric', staff: m.staff })}
              className={`${BTN} mt-1 bg-white border border-gray-200 hover:bg-gray-50`}>هذا الحساب لشخص واحد…</button>
          )}
        </td>
        <td className="px-3 py-2 whitespace-nowrap">
          {canManage && (
            <span className="flex gap-1">
              {r.staff && (
                <button type="button" disabled={busy} onClick={() => unlink.mutate({ id: r.id })}
                  className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>فك الربط</button>
              )}
              {r.hold_resolution
                ? <button type="button" disabled={busy} onClick={() => hold.mutate({ id: r.id, hold: false })}
                    className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>إفراج عن البصمات</button>
                : <button type="button" disabled={busy} onClick={() => setAsking({ id: r.id, kind: 'hold' })}
                    className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>تعليق البصمات…</button>}
            </span>
          )}
        </td>
      </tr>
      {isAsking && (
        <tr className="bg-gray-50/70 border-b border-gray-100">
          <td colSpan={7} className="px-3 py-2">
            {asking.kind === 'hold'
              ? <ReasonRow placeholder="سبب تعليق البصمات (مطلوب)" confirmLabel="تعليق" busy={hold.isPending}
                  error={hold.isError ? errText(hold.error) : ''}
                  onConfirm={reason => hold.mutate({ id: r.id, hold: true, reason })} onCancel={() => setAsking(null)} />
              : <ReasonRow placeholder="لماذا هذا الحساب لشخص واحد؟ (مطلوب)" confirmLabel="تأكيد" busy={notGeneric.isPending}
                  error={notGeneric.isError ? errText(notGeneric.error) : ''}
                  onConfirm={reason => notGeneric.mutate({ id: r.id, staff: asking.staff, reason })} onCancel={() => setAsking(null)} />}
          </td>
        </tr>
      )}
    </>
  )
}
