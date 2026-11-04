/**
 * DailyCountTab.jsx — «الجرد اليومي» tab on /stock-count (Project 2, small daily counts).
 *
 * For reviewers: named branch managers (own branches) and the central auditor (management, all
 * branches). Who finished today's list, the open differences (expected vs counted, value, why the
 * item was picked), and per-difference actions inline — recount (same or another salesperson, still
 * blind), accept with a reason (+ «needs a SOFTECH adjustment» reminder), or escalate to the auditor.
 * Escalated differences are the auditor's. The server decides every rule; nothing writes to SOFTECH.
 */
import { Fragment, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { dailyCountApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import useGridKeyboard from '../../hooks/useGridKeyboard'
import SortTh from '../../components/SortTh'

const STATE = {
  done:        ['خلّص', 'bg-green-50 text-green-700'],
  partial:     ['جزئي', 'bg-amber-50 text-amber-700'],
  not_started: ['لم يبدأ', 'bg-gray-100 text-gray-600'],
  missed:      ['لم يُنجز', 'bg-red-50 text-red-700'],
}
const fmt = (v, d = 2) => (v == null ? '—' : Number(v).toLocaleString('en-US', { maximumFractionDigits: d }))

function todayCairo() {
  try { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Cairo' }).format(new Date()) } catch { return '' }
}

function ActionPanel({ row, reasons, onDone }) {
  const [mode, setMode]       = useState(null)
  const [reason, setReason]   = useState('')
  const [note, setNote]       = useState('')
  const [adjust, setAdjust]   = useState(false)
  const [assignee, setAssignee] = useState('')
  const [busy, setBusy]       = useState(false)
  const [error, setError]     = useState('')
  const staff = useQuery({
    queryKey: ['daily-count-staff', row.branch_code],
    queryFn: () => dailyCountApi.staff(row.branch_code).then(r => r.data),
    enabled: mode === 'recount',
  })

  async function run(fn) {
    setBusy(true); setError('')
    try { await fn(); onDone() } catch (e) { setError(e.response?.data?.detail || 'تعذّر التنفيذ') } finally { setBusy(false) }
  }

  if (!row.can_act) {
    return <p className="text-xs text-gray-500">{row.escalated ? 'محال للمراجع المركزي — هو اللي يقرر.' : 'لا يوجد إجراء متاح.'}</p>
  }
  return (
    <div className="space-y-2 text-sm">
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => setMode('recount')} className={`btn-secondary ${mode === 'recount' ? 'ring-2 ring-brand-300' : ''}`}>🔁 إعادة جرد</button>
        <button type="button" onClick={() => setMode('accept')} className={`btn-secondary ${mode === 'accept' ? 'ring-2 ring-brand-300' : ''}`}>✔ اعتماد الفرق</button>
        {!row.escalated && (
          <button type="button" onClick={() => setMode('escalate')} className={`btn-secondary ${mode === 'escalate' ? 'ring-2 ring-brand-300' : ''}`}>⬆ إحالة للمراجع</button>
        )}
      </div>
      {mode === 'recount' && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-gray-600">بواسطة
            <select className="input-field mt-1 block" value={assignee} onChange={e => setAssignee(e.target.value)}>
              <option value="">نفس الشخص ({row.assigned_to})</option>
              {(staff.data || []).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <button type="button" disabled={busy} className="btn-primary"
            onClick={() => run(() => dailyCountApi.recount(row.pick_id, { assignee_id: assignee || undefined, note }))}>اطلب إعادة الجرد</button>
        </div>
      )}
      {mode === 'accept' && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-gray-600">سبب الفرق
            <select className="input-field mt-1 block" value={reason} onChange={e => setReason(e.target.value)}>
              <option value="">اختر...</option>
              {Object.entries(reasons || {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-600 flex items-center gap-1.5 mb-2">
            <input type="checkbox" checked={adjust} onChange={e => setAdjust(e.target.checked)} />
            يحتاج تسوية في SOFTECH (يدوياً)
          </label>
          <button type="button" disabled={busy || !reason} className="btn-primary"
            onClick={() => run(() => dailyCountApi.accept(row.pick_id, { reason, note, needs_softech_adjustment: adjust }))}>اعتماد</button>
        </div>
      )}
      {mode === 'escalate' && (
        <button type="button" disabled={busy} className="btn-primary"
          onClick={() => run(() => dailyCountApi.escalate(row.pick_id, { note }))}>أحِل للمراجع المركزي</button>
      )}
      {mode && (
        <input className="input-field w-full" placeholder="ملاحظة (اختياري)" value={note} onChange={e => setNote(e.target.value)} />
      )}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

function Report() {
  const [days, setDays] = useState(7)
  const [busy, setBusy] = useState(false)
  const q = useQuery({ queryKey: ['daily-count-report', days], queryFn: () => dailyCountApi.report({ days }).then(r => r.data) })
  const rows = q.data?.rows || []
  const { sorted, headerProps } = useSortableRows(rows, { persistKey: 'daily-count-report' })

  async function xlsx() {
    setBusy(true)
    try {
      const r = await dailyCountApi.reportXlsx({ days })
      const url = URL.createObjectURL(r.data)
      const a = document.createElement('a')
      a.href = url; a.download = `daily-counts-${days}d.xlsx`; a.click()
      URL.revokeObjectURL(url)
    } finally { setBusy(false) }
  }

  return (
    <section data-tour="dailycount-report" className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <h3 className="font-bold text-gray-900 text-sm">الإنجاز والفروق</h3>
        {[7, 30].map(d => (
          <button key={d} type="button" onClick={() => setDays(d)}
            className={`text-xs px-3 py-1 rounded-full border ${days === d ? 'bg-brand-50 border-brand-300 text-brand-700' : 'border-gray-200 text-gray-600'}`}>
            آخر {d} يوم
          </button>
        ))}
        <button type="button" onClick={xlsx} disabled={busy || !rows.length} className="btn-secondary text-xs ms-auto">⬇ Excel</button>
      </div>
      {rows.length === 0 ? <p className="text-sm text-gray-400">لا توجد بيانات بعد.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 border-b">
              <tr>
                <SortTh {...headerProps('branch_name', 'text')} className="px-2 py-2 text-right">الفرع</SortTh>
                <SortTh {...headerProps('staff_name', 'text')} className="px-2 py-2 text-right">الموظف</SortTh>
                <SortTh {...headerProps('assigned', 'number')} className="px-2 py-2">المطلوب</SortTh>
                <SortTh {...headerProps('completion_pct', 'number')} className="px-2 py-2">الإنجاز %</SortTh>
                <SortTh {...headerProps('missed', 'number')} className="px-2 py-2">لم يُنجز</SortTh>
                <SortTh {...headerProps('differences', 'number')} className="px-2 py-2">فروق</SortTh>
                <SortTh {...headerProps('value_egp', 'number')} className="px-2 py-2">قيمة الفروق</SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <tr key={i} className="border-b border-gray-50">
                  <td className="px-2 py-1.5">{r.branch_name}</td>
                  <td className="px-2 py-1.5">{r.staff_name}</td>
                  <td className="px-2 py-1.5 text-center tabular-nums">{r.assigned}</td>
                  <td className={`px-2 py-1.5 text-center tabular-nums ${r.completion_pct < 80 ? 'text-red-600 font-semibold' : ''}`}>{r.completion_pct}</td>
                  <td className="px-2 py-1.5 text-center tabular-nums">{r.missed}</td>
                  <td className="px-2 py-1.5 text-center tabular-nums">{r.differences}</td>
                  <td className="px-2 py-1.5 text-center tabular-nums">{fmt(r.value_egp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {(q.data?.reasons || []).length > 0 && (
        <p className="text-xs text-gray-500">
          أسباب الفروق المعتمدة: {q.data.reasons.map(r => `${r.label} (${r.count})`).join(' · ')}
        </p>
      )}
    </section>
  )
}

// «توزيع الآن» — management hands out today's lists for one pilot branch on demand (normally the
// hourly job does it after 07:00). The server is idempotent: people who already have a list keep it.
function DistributeNow({ branches, onDone }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg]   = useState('')
  async function go() {
    setBusy(true); setMsg('')
    try {
      const r = await dailyCountApi.generate({ branch_code: code })
      setMsg(r.data.created ? `تم توزيع ${r.data.created} صنف على موظفي الفرع.` : 'كل موظفي الفرع عندهم قوائم النهارده بالفعل.')
      onDone()
    } catch (e) {
      setMsg(e.response?.data?.detail || 'تعذّر التوزيع')
    } finally { setBusy(false) }
  }
  return (
    <div data-tour="dailycount-distribute" className="flex items-center gap-2 flex-wrap">
      <select className="input-field" value={code} onChange={e => { setCode(e.target.value); setMsg('') }}>
        <option value="">اختر فرعاً...</option>
        {branches.map(b => <option key={b.code} value={b.code}>{b.name}</option>)}
      </select>
      <button type="button" className="btn-primary" disabled={!code || busy} onClick={go}>
        {busy ? 'جارٍ التوزيع...' : '📋 توزيع قوائم اليوم الآن'}
      </button>
      {msg && <span className="text-xs text-gray-600">{msg}</span>}
    </div>
  )
}

export default function DailyCountTab() {
  const qc = useQueryClient()
  const [date, setDate] = useState(todayCairo())
  const [openId, setOpenId] = useState(null)
  const q = useQuery({
    queryKey: ['daily-count-board', date],
    queryFn: () => dailyCountApi.board({ date }).then(r => r.data),
  })
  const people = q.data?.people || []
  const diffs = q.data?.differences || []
  const ppl = useSortableRows(people, { persistKey: 'daily-count-people' })
  const dif = useSortableRows(diffs, { persistKey: 'daily-count-diffs', defaultSort: { key: 'value_egp', dir: 'desc', type: 'number' } })
  const kb = useGridKeyboard({
    rows: dif.sorted, getKey: r => r.pick_id,
    onOpen: r => setOpenId(id => (id === r.pick_id ? null : r.pick_id)),
    onConfirm: r => setOpenId(r.pick_id),
  })

  function refresh() {
    setOpenId(null)
    qc.invalidateQueries({ queryKey: ['daily-count-board'] })
    qc.invalidateQueries({ queryKey: ['daily-count-report'] })
  }

  if (q.isError) return <p className="text-sm text-red-600">تعذّر تحميل الجرد اليومي.</p>

  return (
    <div className="space-y-4" dir="rtl">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-sm text-gray-600 flex items-center gap-2">اليوم
          <input type="date" className="input-field" value={date} onChange={e => setDate(e.target.value)} />
        </label>
        <span className="text-xs text-gray-400">الموظف بيجرد من غير ما يشوف الكمية المتوقعة. أي تسوية بتتعمل يدوياً في SOFTECH.</span>
        {(q.data?.pilot_branches || []).length > 0 && (
          <div className="ms-auto"><DistributeNow branches={q.data.pilot_branches} onDone={refresh} /></div>
        )}
      </div>

      <section data-tour="dailycount-people" className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="font-bold text-gray-900 text-sm mb-2">مين خلّص جرده</h3>
        {q.isLoading ? <p className="text-sm text-gray-400">جارٍ التحميل...</p>
          : people.length === 0 ? <p className="text-sm text-gray-400">لا توجد قوائم جرد لهذا اليوم.</p> : (
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 border-b">
              <tr>
                <SortTh {...ppl.headerProps('branch_name', 'text')} className="px-2 py-2 text-right">الفرع</SortTh>
                <SortTh {...ppl.headerProps('staff_name', 'text')} className="px-2 py-2 text-right">الموظف</SortTh>
                <SortTh {...ppl.headerProps('done', 'number')} className="px-2 py-2">تم</SortTh>
                <SortTh {...ppl.headerProps('state', 'text')} className="px-2 py-2">الحالة</SortTh>
              </tr>
            </thead>
            <tbody>
              {ppl.sorted.map(p => {
                const [label, cls] = STATE[p.state] || ['', '']
                return (
                  <tr key={p.session_id} className="border-b border-gray-50">
                    <td className="px-2 py-1.5">{p.branch_name}</td>
                    <td className="px-2 py-1.5">{p.staff_name}</td>
                    <td className="px-2 py-1.5 text-center tabular-nums">{p.done} / {p.total}</td>
                    <td className="px-2 py-1.5 text-center"><span className={`text-xs px-2 py-0.5 rounded-full ${cls}`}>{label}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section data-tour="dailycount-differences" className="bg-white rounded-xl border border-gray-200 p-4">
        <h3 className="font-bold text-gray-900 text-sm mb-2">الفروق المفتوحة {diffs.length > 0 && <span className="text-gray-400 font-normal">({diffs.length})</span>}</h3>
        {diffs.length === 0 ? <p className="text-sm text-gray-400">لا توجد فروق مفتوحة.</p> : (
          <div className="overflow-x-auto" {...kb.containerProps}>
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-500 border-b">
                <tr>
                  <SortTh {...dif.headerProps('item_name', 'text')} className="px-2 py-2 text-right">الصنف</SortTh>
                  <SortTh {...dif.headerProps('branch_name', 'text')} className="px-2 py-2 text-right">الفرع</SortTh>
                  <SortTh {...dif.headerProps('counted_by', 'text')} className="px-2 py-2 text-right">جرده</SortTh>
                  <SortTh {...dif.headerProps('expected_qty', 'number')} className="px-2 py-2">المتوقع</SortTh>
                  <SortTh {...dif.headerProps('counted_qty', 'number')} className="px-2 py-2">المعدود</SortTh>
                  <SortTh {...dif.headerProps('difference', 'number')} className="px-2 py-2">الفرق</SortTh>
                  <SortTh {...dif.headerProps('value_egp', 'number')} className="px-2 py-2">القيمة</SortTh>
                  <SortTh {...dif.headerProps('status_label', 'text')} className="px-2 py-2">الحالة</SortTh>
                </tr>
              </thead>
              <tbody>
                {dif.sorted.map(r => {
                  const rp = kb.rowProps(r)
                  return (
                  <Fragment key={r.pick_id}>
                    <tr {...rp}
                      onClick={() => setOpenId(id => (id === r.pick_id ? null : r.pick_id))}
                      className={`border-b border-gray-50 cursor-pointer hover:bg-gray-50 ${rp.className}`}>
                      <td className="px-2 py-1.5">
                        <div className="text-gray-900">{r.item_name}</div>
                        <div className="text-[11px] text-gray-400">{(r.reasons || []).join(' · ')}</div>
                      </td>
                      <td className="px-2 py-1.5">{r.branch_name}</td>
                      <td className="px-2 py-1.5">{r.counted_by}{r.attempts > 1 && <span className="text-[11px] text-gray-400"> · {r.attempts} مرات</span>}</td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {fmt(r.expected_qty, 3)}
                        {r.expected_source === 'mirror' && <span title="SOFTECH لم يرد وقت الجرد — المتوقع من النسخة المحلية" className="text-amber-600"> *</span>}
                      </td>
                      <td className="px-2 py-1.5 text-center tabular-nums">{fmt(r.counted_qty, 3)}</td>
                      <td className={`px-2 py-1.5 text-center tabular-nums font-semibold ${r.difference < 0 ? 'text-red-600' : 'text-amber-600'}`} dir="ltr">{fmt(r.difference, 3)}</td>
                      <td className="px-2 py-1.5 text-center tabular-nums">{fmt(r.value_egp)}</td>
                      <td className="px-2 py-1.5 text-center">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${r.escalated ? 'bg-red-50 text-red-700' : 'bg-gray-100 text-gray-700'}`}>{r.status_label}</span>
                      </td>
                    </tr>
                    {openId === r.pick_id && (
                      <tr className="bg-gray-50">
                        <td colSpan={8} className="px-3 py-3">
                          {r.escalation_reason && <p className="text-xs text-red-700 mb-2">سبب الإحالة: {r.escalation_reason}</p>}
                          {r.physical_expiry && <p className="text-xs text-gray-600 mb-2">الصلاحية على الرف: {r.physical_expiry}</p>}
                          <ActionPanel row={r} reasons={q.data?.reasons} onDone={refresh} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                  )
                })}
              </tbody>
            </table>
            <p className="text-[11px] text-gray-400 mt-2">⌨ ↑↓ تنقل · Enter أو M فتح الإجراءات · اضغط الصف للإجراءات</p>
          </div>
        )}
      </section>

      <Report />
    </div>
  )
}
