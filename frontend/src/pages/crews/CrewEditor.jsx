/**
 * Crews tab (الأطقم), right side: the selected crew's editor.
 *   header   name / type / description (PATCH), «حذف / أرشفة» (server answers deleted|archived), unarchive
 *   rules    dated rules; add, «تعديل» (= replace from the date), «إنهاء» (server voids — «إلغاء من بدايته» — a row starting on or after the date)
 *   preview  every picker change → POST /preview/ (400 ms debounce): who the crew would hold from the date
 *   manual   dated include / exclude rows: an employee, or «خارج كشف الرواتب» by user code and/or extension
 * One «تاريخ التطبيق» drives every change (default today, min first of this month — the server still decides).
 * Ended / voided rows stay visible, faded, with their dates. Edit controls only with crews edit.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { crewsApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { CREW_TYPES } from './CrewList'
import {
  BTN, BTN_PRIMARY, ChipPicker, INPUT, OffPayrollBadge, StatusChip, TD, TH,
  errText, fmtDate, isFaded, monthStartIso, todayIso,
} from './util'

const EMPTY_RULE = { job_titles: [], branch_ids: [], departments: [], sections: [], note: '' }
const hasCriteria = r => r.job_titles.length + r.branch_ids.length + r.departments.length + r.sections.length > 0
const ruleBody = r => ({ job_titles: r.job_titles, branch_ids: r.branch_ids, departments: r.departments, sections: r.sections })
const appliesOn = (row, d) => row.status !== 'voided' && row.valid_from <= d && (!row.valid_to || row.valid_to >= d)
const asOptions = list => (list || []).map(v => ({ value: v, label: v }))
/** Sort value for the manual table; module level so useSortableRows gets a stable getValue. */
const getWho = (r, k) => (k === 'who' ? (r.employee_name || r.label || r.softech_usercode || r.pbx_extension) : r[k])

function useDebounced(value, ms) {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

// ── header: name / type / description, delete-or-archive, unarchive ───────────

function CrewHeader({ crew, canEdit, onGone }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ name: crew.name, type: crew.type, description: crew.description || '' })
  const [confirm, setConfirm] = useState(false)
  const [answer, setAnswer] = useState('')
  const dirty = form.name !== crew.name || form.type !== crew.type || form.description !== (crew.description || '')
  const refresh = () => qc.invalidateQueries({ queryKey: ['crews'] })
  const save = useMutation({ mutationFn: () => crewsApi.update(crew.id, form), onSuccess: refresh })
  const remove = useMutation({
    mutationFn: () => crewsApi.remove(crew.id).then(r => r.data),
    onSuccess: data => {
      setConfirm(false)
      setAnswer(data.result === 'deleted' ? 'حُذف الطاقم — لم يكن له أعضاء قط.' : 'أُرشف الطاقم — له تاريخ محفوظ فلا يُحذف.')
      refresh()
      if (data.result === 'deleted') onGone()
    },
  })
  const unarchive = useMutation({ mutationFn: () => crewsApi.unarchive(crew.id), onSuccess: () => { setAnswer(''); refresh() } })
  const editable = canEdit && !crew.is_archived

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${INPUT} w-56 font-semibold`} value={form.name} disabled={!editable}
               onChange={e => setForm({ ...form, name: e.target.value })} aria-label="اسم الطاقم" />
        <select className={INPUT} value={form.type} disabled={!editable} onChange={e => setForm({ ...form, type: e.target.value })} aria-label="النوع">
          {CREW_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        {crew.is_archived && <span className="rounded bg-gray-200 text-gray-700 px-2 py-0.5 text-xs">مؤرشف</span>}
        <span className="text-xs text-gray-500">الأعضاء اليوم: {crew.member_count}</span>
      </div>
      <textarea className={`${INPUT} w-full`} rows={2} placeholder="وصف (اختياري)" value={form.description} disabled={!editable}
                onChange={e => setForm({ ...form, description: e.target.value })} />
      {canEdit && (
        <div className="flex flex-wrap items-center gap-2">
          {editable && <button type="button" className={BTN_PRIMARY} disabled={!dirty || save.isPending} onClick={() => save.mutate()}>حفظ البيانات</button>}
          {editable && !confirm && <button type="button" className={BTN} onClick={() => { setConfirm(true); setAnswer('') }}>حذف / أرشفة</button>}
          {editable && confirm && (
            <span className="flex items-center gap-2 text-xs">
              يُحذف إن لم يكن له أعضاء قط، وإلا يُؤرشف. متأكد؟
              <button type="button" className={BTN} disabled={remove.isPending} onClick={() => remove.mutate()}>نعم</button>
              <button type="button" className={BTN} onClick={() => setConfirm(false)}>لا</button>
            </span>
          )}
          {crew.is_archived && <button type="button" className={BTN} disabled={unarchive.isPending} onClick={() => unarchive.mutate()}>إلغاء الأرشفة</button>}
          {answer && <span className="text-xs text-emerald-700">{answer}</span>}
          {[save, remove, unarchive].map((m, i) => m.isError && <span key={i} className="text-xs text-red-600">{errText(m.error)}</span>)}
        </div>
      )}
    </div>
  )
}

// ── rules ─────────────────────────────────────────────────────────────────────

function RulesTable({ rules, canChange, onEdit, onEnd, editingId, busy }) {
  const { sorted, headerProps: h } = useSortableRows(rules, { persistKey: 'crews-rules' })
  if (!rules.length) return <p className="text-xs text-gray-500">لا توجد قواعد بعد.</p>
  const list = v => (v && v.length ? v.join('، ') : <span className="text-gray-400">الكل</span>)
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50"><tr>
          <SortTh {...h('status', 'text')} className={TH}>الحالة</SortTh>
          <SortTh {...h('valid_from', 'date')} className={TH}>من</SortTh>
          <SortTh {...h('valid_to', 'date')} className={TH}>إلى</SortTh>
          <th className={TH}>الوظائف</th>
          <th className={TH}>الفروع</th>
          <th className={TH}>الأقسام / الإدارات</th>
          <th className={TH}>ملاحظة</th>
          {canChange && <th className={TH}><span className="sr-only">إجراءات</span></th>}
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => (
            <tr key={r.id} className={`${isFaded(r) ? 'opacity-50' : ''} ${editingId === r.id ? 'bg-amber-50' : ''}`}>
              <td className={TD}><StatusChip status={r.status} /></td>
              <td className={`${TD} whitespace-nowrap`}>{fmtDate(r.valid_from)}</td>
              <td className={`${TD} whitespace-nowrap`}>{r.valid_to ? fmtDate(r.valid_to) : 'مفتوحة'}</td>
              <td className={`${TD} text-xs`}>{list(r.job_titles)}</td>
              <td className={`${TD} text-xs`}>{list(r.branch_labels)}</td>
              <td className={`${TD} text-xs`}>{list([...(r.departments || []), ...(r.sections || [])])}</td>
              <td className={`${TD} text-xs text-gray-500`}>{r.note}</td>
              {canChange && (
                <td className={`${TD} whitespace-nowrap`}>
                  {!isFaded(r) && (
                    <span className="flex gap-1">
                      <button type="button" className={BTN} onClick={() => onEdit(r)}>تعديل</button>
                      <button type="button" className={BTN} disabled={busy} onClick={() => onEnd(r)}>إنهاء</button>
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RulePreview({ crew, draft, editingId, on }) {
  const rules = useMemo(() => {
    const kept = (crew.rules || []).filter(r => r.id !== editingId && appliesOn(r, on)).map(ruleBody)
    return hasCriteria(draft) ? [...kept, ruleBody(draft)] : kept
  }, [crew.rules, draft, editingId, on])
  const payload = useDebounced(JSON.stringify({ rules, date: on, crew_id: crew.id }), 400)
  const q = useQuery({
    queryKey: ['crews', 'preview', payload],
    queryFn: () => crewsApi.preview(JSON.parse(payload)).then(r => r.data),
    enabled: !!on,
    placeholderData: prev => prev,
  })
  const people = q.data || []
  return (
    <div className="rounded-md border border-dashed border-brand-200 bg-brand-50/40 p-2 space-y-1" data-tour="crews-editor-preview">
      <div className="text-xs font-semibold text-gray-700">
        معاينة: من {fmtDate(on)} سيكون في الطاقم {q.isFetching && !q.data ? '…' : people.length} شخصًا
        {q.isFetching && q.data && <span className="ms-1 text-gray-400">(تحديث…)</span>}
      </div>
      {q.isError && <p className="text-xs text-red-600">{errText(q.error)}</p>}
      <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
        {people.map(p => (
          <span key={p.key} className="rounded bg-white border border-gray-200 px-1.5 py-0.5 text-xs">
            {p.name || p.key}{p.off_payroll && <OffPayrollBadge />}
          </span>
        ))}
      </div>
    </div>
  )
}

function RulesSection({ crew, options, canChange, on }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(EMPTY_RULE)
  const [editingId, setEditingId] = useState(null)
  const refresh = () => qc.invalidateQueries({ queryKey: ['crews'] })
  const save = useMutation({
    mutationFn: () => (editingId
      ? crewsApi.replaceRule(crew.id, editingId, { ...draft, on })
      : crewsApi.addRule(crew.id, { ...draft, valid_from: on })),
    onSuccess: () => { setDraft(EMPTY_RULE); setEditingId(null); refresh() },
  })
  const end = useMutation({ mutationFn: r => crewsApi.endRule(crew.id, r.id, on), onSuccess: refresh })
  const startEdit = r => {
    setEditingId(r.id)
    setDraft({ job_titles: r.job_titles || [], branch_ids: r.branch_ids || [], departments: r.departments || [],
               sections: r.sections || [], note: r.note || '' })
  }
  const branchOptions = useMemo(() => (options?.branches || []).map(b => ({ value: b.id, label: b.label })), [options])
  const set = k => v => setDraft(d => ({ ...d, [k]: v }))

  return (
    <section className="space-y-2" data-tour="crews-editor-rules">
      <h3 className="text-sm font-bold text-gray-800">القواعد</h3>
      <RulesTable rules={crew.rules || []} canChange={canChange} onEdit={startEdit} onEnd={r => end.mutate(r)}
                  editingId={editingId} busy={end.isPending} />
      {end.isError && <p className="text-xs text-red-600">{errText(end.error)}</p>}
      {canChange && (
        <div className="rounded-md border border-gray-200 p-2 space-y-2">
          <div className="text-xs font-semibold text-gray-700">
            {editingId ? `تعديل القاعدة: تنتهي الحالية في اليوم السابق لـ ${fmtDate(on)} وتبدأ الجديدة منه` : 'قاعدة جديدة'}
          </div>
          {!options ? <p className="text-xs text-gray-500">جارٍ تحميل الاختيارات…</p> : (
            <div className="grid gap-2 md:grid-cols-2">
              <ChipPicker label="الوظائف" options={asOptions(options.job_titles)} value={draft.job_titles} onChange={set('job_titles')} />
              <ChipPicker label="الفروع" options={branchOptions} value={draft.branch_ids} onChange={set('branch_ids')} />
              <ChipPicker label="الإدارات" options={asOptions(options.departments)} value={draft.departments} onChange={set('departments')} />
              <ChipPicker label="الأقسام" options={asOptions(options.sections)} value={draft.sections} onChange={set('sections')} />
            </div>
          )}
          <input className={`${INPUT} w-full`} placeholder="ملاحظة (اختياري)" value={draft.note} onChange={e => set('note')(e.target.value)} />
          <RulePreview crew={crew} draft={draft} editingId={editingId} on={on} />
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={BTN_PRIMARY} disabled={!hasCriteria(draft) || save.isPending} onClick={() => save.mutate()}>
              {editingId ? 'تطبيق التعديل من التاريخ' : 'إضافة القاعدة'}
            </button>
            {(editingId || hasCriteria(draft)) && (
              <button type="button" className={BTN} onClick={() => { setEditingId(null); setDraft(EMPTY_RULE); save.reset() }}>إلغاء</button>
            )}
            {save.isError && <span className="text-xs text-red-600">{errText(save.error)}</span>}
          </div>
        </div>
      )}
    </section>
  )
}

// ── manual rows ───────────────────────────────────────────────────────────────

function ManualTable({ rows, canChange, onEnd, busy }) {
  const { sorted, headerProps: h } = useSortableRows(rows, { persistKey: 'crews-manual', getValue: getWho })
  if (!rows.length) return <p className="text-xs text-gray-500">لا توجد إضافات أو استبعادات يدوية.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50"><tr>
          <SortTh {...h('status', 'text')} className={TH}>الحالة</SortTh>
          <SortTh {...h('mode_label', 'text')} className={TH}>النوع</SortTh>
          <SortTh {...h('who', 'text')} className={TH}>الشخص</SortTh>
          <SortTh {...h('valid_from', 'date')} className={TH}>من</SortTh>
          <SortTh {...h('valid_to', 'date')} className={TH}>إلى</SortTh>
          <th className={TH}>السبب</th>
          {canChange && <th className={TH}><span className="sr-only">إجراءات</span></th>}
        </tr></thead>
        <tbody className="divide-y divide-gray-100">
          {sorted.map(r => (
            <tr key={r.id} className={isFaded(r) ? 'opacity-50' : ''}>
              <td className={TD}><StatusChip status={r.status} /></td>
              <td className={TD}>{r.mode_label}</td>
              <td className={TD}>
                {r.employee_id ? <>{r.employee_name} <span className="text-xs text-gray-500">{r.hr_number}</span></> : (
                  <>
                    {r.label || r.softech_usercode || r.pbx_extension}
                    <span className="ms-1 text-xs text-gray-500" dir="ltr">
                      {[r.softech_usercode && `كود ${r.softech_usercode}`, r.pbx_extension && `داخلي ${r.pbx_extension}`].filter(Boolean).join(' · ')}
                    </span>
                    {r.off_payroll && <OffPayrollBadge />}
                  </>
                )}
              </td>
              <td className={`${TD} whitespace-nowrap`}>{fmtDate(r.valid_from)}</td>
              <td className={`${TD} whitespace-nowrap`}>{r.valid_to ? fmtDate(r.valid_to) : 'مفتوح'}</td>
              <td className={`${TD} text-xs text-gray-500`}>{r.reason}</td>
              {canChange && (
                <td className={TD}>
                  {!isFaded(r) && <button type="button" className={BTN} disabled={busy} onClick={() => onEnd(r)}>إنهاء</button>}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const EMPTY_MANUAL = { mode: 'include', employee: null, softech_usercode: '', pbx_extension: '', label: '', reason: '' }

function ManualForm({ crew, options, on, onDone }) {
  const [f, setF] = useState(EMPTY_MANUAL)
  const [offPayroll, setOffPayroll] = useState(false)
  const [q, setQ] = useState('')
  const matches = useMemo(() => {
    const needle = q.trim().toLowerCase()
    if (!needle) return []
    return (options?.employees || []).filter(e => [e.name, e.hr_number, e.softech_usercode]
      .some(v => String(v || '').toLowerCase().includes(needle))).slice(0, 8)
  }, [q, options])
  const save = useMutation({
    mutationFn: () => crewsApi.addManual(crew.id, offPayroll
      ? { mode: f.mode, softech_usercode: f.softech_usercode.trim(), pbx_extension: f.pbx_extension.trim(),
          label: f.label.trim(), reason: f.reason.trim(), valid_from: on }
      : { mode: f.mode, employee_id: f.employee?.id, reason: f.reason.trim(), valid_from: on }),
    onSuccess: () => { setF(EMPTY_MANUAL); setQ(''); onDone() },
  })
  const who = offPayroll ? (f.softech_usercode.trim() || f.pbx_extension.trim()) : f.employee
  const ready = who && f.reason.trim()

  return (
    <div className="rounded-md border border-gray-200 p-2 space-y-2">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <select className={INPUT} value={f.mode} onChange={e => setF({ ...f, mode: e.target.value })} aria-label="النوع">
          <option value="include">إضافة للطاقم</option>
          <option value="exclude">استبعاد من الطاقم</option>
        </select>
        <label className="flex items-center gap-1"><input type="radio" checked={!offPayroll} onChange={() => setOffPayroll(false)} /> موظف</label>
        <label className="flex items-center gap-1"><input type="radio" checked={offPayroll} onChange={() => setOffPayroll(true)} /> خارج كشف الرواتب</label>
      </div>
      {!offPayroll ? (
        <div className="space-y-1">
          {f.employee ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="font-semibold">{f.employee.name}</span>
              <span className="text-xs text-gray-500">{f.employee.hr_number} · {f.employee.job_title}</span>
              <button type="button" className="text-xs text-brand-700 hover:underline" onClick={() => setF({ ...f, employee: null })}>تغيير</button>
            </div>
          ) : (
            <>
              <input className={`${INPUT} w-full`} placeholder="ابحث بالاسم أو الرقم الوظيفي أو كود المستخدم" value={q} onChange={e => setQ(e.target.value)} />
              {matches.length > 0 && (
                <ul className="border border-gray-200 rounded-md divide-y divide-gray-100 max-h-48 overflow-y-auto">
                  {matches.map(e => (
                    <li key={e.id}>
                      <button type="button" className="w-full text-right px-2 py-1 text-sm hover:bg-gray-50"
                              onClick={() => { setF({ ...f, employee: e }); setQ('') }}>
                        {e.name} <span className="text-xs text-gray-500">{e.hr_number} · {e.job_title}{e.softech_usercode ? ` · كود ${e.softech_usercode}` : ''}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {q.trim() && matches.length === 0 && <p className="text-xs text-gray-500">لا يوجد موظف مطابق — جرّب «خارج كشف الرواتب».</p>}
            </>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <input className={`${INPUT} w-32`} dir="ltr" placeholder="كود المستخدم" value={f.softech_usercode} onChange={e => setF({ ...f, softech_usercode: e.target.value })} />
          <input className={`${INPUT} w-28`} dir="ltr" placeholder="رقم داخلي" value={f.pbx_extension} onChange={e => setF({ ...f, pbx_extension: e.target.value })} />
          <input className={`${INPUT} flex-1 min-w-40`} placeholder="الاسم الظاهر" value={f.label} onChange={e => setF({ ...f, label: e.target.value })} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <input className={`${INPUT} flex-1 min-w-48`} placeholder="السبب (إلزامي)" value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} />
        <button type="button" className={BTN_PRIMARY} disabled={!ready || save.isPending} onClick={() => save.mutate()}>حفظ من {fmtDate(on)}</button>
      </div>
      {save.isError && <p className="text-xs text-red-600">{errText(save.error)}</p>}
    </div>
  )
}

function ManualSection({ crew, options, canChange, on }) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['crews'] })
  const end = useMutation({ mutationFn: r => crewsApi.endManual(crew.id, r.id, on), onSuccess: refresh })
  return (
    <section className="space-y-2" data-tour="crews-editor-manual">
      <h3 className="text-sm font-bold text-gray-800">إضافة / استبعاد يدوي</h3>
      <ManualTable rows={crew.manual || []} canChange={canChange} onEnd={r => end.mutate(r)} busy={end.isPending} />
      {end.isError && <p className="text-xs text-red-600">{errText(end.error)}</p>}
      {canChange && <ManualForm crew={crew} options={options} on={on} onDone={refresh} />}
    </section>
  )
}

// ── the editor ────────────────────────────────────────────────────────────────

export default function CrewEditor({ crewId, canEdit, onGone }) {
  const detail = useQuery({ queryKey: ['crews', 'detail', crewId], queryFn: () => crewsApi.get(crewId).then(r => r.data) })
  const options = useQuery({
    queryKey: ['crews-options'], queryFn: () => crewsApi.options().then(r => r.data),
    enabled: canEdit, staleTime: 5 * 60 * 1000,
  })
  const [on, setOn] = useState(todayIso())

  if (detail.isLoading) return <div className="card p-4 text-sm text-gray-500">جارٍ التحميل…</div>
  if (detail.isError) return <div className="card p-4 text-sm text-red-600">{errText(detail.error)}</div>
  const crew = detail.data
  const canChange = canEdit && !crew.is_archived

  return (
    <div className="card p-3 space-y-4">
      <CrewHeader key={`${crew.id}-${crew.name}-${crew.type}-${crew.description}`} crew={crew} canEdit={canEdit} onGone={onGone} />
      {canChange && (
        <label className="flex flex-wrap items-center gap-2 text-sm bg-gray-50 rounded-md p-2">
          <span className="font-semibold text-gray-700">تاريخ التطبيق</span>
          <input type="date" className={INPUT} value={on} min={monthStartIso()} onChange={e => setOn(e.target.value || todayIso())} />
          <span className="text-xs text-gray-500">كل إضافة أو تعديل أو إنهاء يبدأ من هذا اليوم، ولا يبدأ قبل أول الشهر الحالي.</span>
        </label>
      )}
      <RulesSection crew={crew} options={options.data} canChange={canChange} on={on} />
      <ManualSection crew={crew} options={options.data} canChange={canChange} on={on} />
    </div>
  )
}
