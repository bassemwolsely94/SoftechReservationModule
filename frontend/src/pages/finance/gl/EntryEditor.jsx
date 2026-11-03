/**
 * EntryEditor.jsx — one journal entry in a side panel (used by JournalPage and the
 * account statement).
 *
 * Draft: date, book, description, line grid, live Σ debit / Σ credit / difference
 * (display only — the server decides balance and refuses what it must), save,
 * approve (ledger.approve), delete. Approved: read-only lines + reverse with a reason.
 * Amounts are sent exactly as typed; the server rejects more than 2 decimals.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import BranchSelect from '../../../components/BranchSelect'
import { Spinner } from '../../../components/ui'
import { wildcardMatch } from '../../../utils/wildcard'
import {
  BOOKS, StatusPill, money, errOf, listOf, todayIso, accountOf, useGlBranches,
  inputCls, btnPrimary, btnPlain, ErrorBox,
} from './glUi'

let seq = 0
const blankLine = () => ({
  key: ++seq, account_code: '', account_name: '', branch_id: '', party_code: '',
  debit: '', credit: '', description: '', cheque_no: '', due_date: '',
})
const idOf = (v) => (v && typeof v === 'object' ? v.id : v)

function lineFrom(l) {
  const a = accountOf(l)
  const amt = (v) => (v === null || v === undefined || Number(v) === 0 ? '' : String(v))
  return {
    key: ++seq, account_code: a.code || '', account_name: a.name || '',
    branch_id: l.branch_id ?? idOf(l.branch) ?? '', party_code: l.party_code || '',
    debit: amt(l.debit), credit: amt(l.credit), description: l.description || '',
    cheque_no: l.cheque_no || '', due_date: l.due_date || '',
  }
}

// cents, so the live totals never show float noise (display only)
const cents = (v) => { const n = Number(v); return Number.isFinite(n) ? Math.round(n * 100) : 0 }

// ── Account picker: code / name search over the active posting accounts ──────
function AccountPicker({ value, name, accounts, onPick, disabled }) {
  const [q, setQ] = useState(null)        // null = not typing → show the chosen account
  const [open, setOpen] = useState(false)
  const hits = useMemo(() => {
    if (!q) return accounts.slice(0, 30)
    const exact = accounts.filter(a => String(a.code).startsWith(q))
    const rest = accounts.filter(a => !String(a.code).startsWith(q) && wildcardMatch([a.code, a.name], q))
    return [...exact, ...rest].slice(0, 30)
  }, [q, accounts])
  const pick = (a) => { onPick(a); setQ(null); setOpen(false) }
  return (
    <div className="relative">
      <input className={`${inputCls} w-full`} disabled={disabled}
             value={q ?? (value ? `${value} · ${name}` : '')} placeholder="كود أو اسم الحساب"
             onFocus={() => { setQ(''); setOpen(true) }}
             onChange={e => { setQ(e.target.value); setOpen(true) }}
             onBlur={() => setTimeout(() => { setOpen(false); setQ(null) }, 150)}
             onKeyDown={e => { if (e.key === 'Enter' && hits[0]) { e.preventDefault(); pick(hits[0]) } }} />
      {open && !disabled && (
        <div className="absolute z-30 mt-1 w-80 max-h-64 overflow-auto bg-white border border-gray-200 rounded-lg shadow-lg text-sm">
          {hits.length === 0 && <div className="px-3 py-2 text-gray-400">لا يوجد حساب مطابق</div>}
          {hits.map(a => (
            <button key={a.code} type="button" onMouseDown={e => e.preventDefault()} onClick={() => pick(a)}
                    className="block w-full text-right px-3 py-1.5 hover:bg-green-50">
              <span className="font-mono text-gray-500">{a.code}</span> · {a.name}
              {(a.requires_branch || (a.party_type && a.party_type !== 'none')) && (
                <span className="ms-1 text-[10px] text-amber-700">
                  {a.requires_branch ? 'فرع' : ''}{a.requires_branch && a.party_type !== 'none' ? ' · ' : ''}{a.party_type && a.party_type !== 'none' ? 'طرف' : ''}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function EntryEditor({ entryId, onClose, onChanged }) {
  const qc = useQueryClient()
  const perms = usePermissions('ledger')
  const { branches, labelOf } = useGlBranches()
  const [id, setId] = useState(entryId || null)
  const [form, setForm] = useState(() => ({
    entry_date: todayIso(), book: 'general', branch: '', description: '', notes: '', lines: [blankLine(), blankLine()],
  }))
  const [dirty, setDirty] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [reason, setReason] = useState('')

  useEffect(() => { setId(entryId || null) }, [entryId])
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape' && !dirty) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [dirty, onClose])

  const entryQ = useQuery({
    queryKey: ['gl', 'entry', id],
    queryFn: () => glApi.entry(id).then(r => r.data),
    enabled: !!id,
  })
  const entry = entryQ.data
  useEffect(() => {
    if (!entry || dirty) return
    setForm({
      entry_date: entry.entry_date || todayIso(), book: entry.book || 'general',
      branch: entry.branch_id ?? idOf(entry.branch) ?? '', description: entry.description || '',
      notes: entry.notes || '', lines: (entry.lines || []).map(lineFrom),
    })
  }, [entry])   // eslint-disable-line react-hooks/exhaustive-deps -- reload only when the server copy changes

  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', 'posting'],
    queryFn: () => glApi.accounts({ active: 'true', page_size: 2000 }).then(r => listOf(r.data)),
    staleTime: 5 * 60 * 1000,
  })
  const accounts = useMemo(() => (accountsQ.data || []).filter(a => a.is_posting !== false), [accountsQ.data])
  const accountByCode = useMemo(() => Object.fromEntries(accounts.map(a => [String(a.code), a])), [accounts])

  const status = id ? entry?.status : 'draft'
  const isDraft = status === 'draft'
  const editable = isDraft && !!perms.create
  const isReversal = !!entry?.reverses

  const set = (patch) => { setForm(f => ({ ...f, ...patch })); setDirty(true); setMsg('') }
  const setLine = (key, patch) => set({ lines: form.lines.map(l => (l.key === key ? { ...l, ...patch } : l)) })
  const addLine = () => set({ lines: [...form.lines, blankLine()] })
  const removeLine = (key) => set({ lines: form.lines.filter(l => l.key !== key) })

  const totals = useMemo(() => {
    const d = form.lines.reduce((s, l) => s + cents(l.debit), 0)
    const c = form.lines.reduce((s, l) => s + cents(l.credit), 0)
    return { debit: d / 100, credit: c / 100, diff: (d - c) / 100 }
  }, [form.lines])

  const body = () => ({
    entry_date: form.entry_date, book: form.book, branch: form.branch || null,
    description: form.description, notes: form.notes,
    lines: form.lines
      .filter(l => l.account_code || l.debit || l.credit)
      .map(l => ({
        account_code: l.account_code, debit: (l.debit || '0').trim(), credit: (l.credit || '0').trim(),
        branch_id: l.branch_id || null, party_code: l.party_code.trim(), description: l.description,
        cheque_no: l.cheque_no.trim(), due_date: l.due_date || null,
      })),
  })

  const afterChange = (data, text) => {
    setDirty(false); setErr(''); setMsg(text)
    if (data?.id) setId(data.id)
    qc.invalidateQueries({ queryKey: ['gl', 'entries'] })
    qc.invalidateQueries({ queryKey: ['gl', 'entry'] })
    onChanged?.(data)
  }
  const fail = (e) => { setErr(errOf(e)); setMsg('') }

  const saveDraft = async () => {
    const r = id ? await glApi.entryUpdate(id, body()) : await glApi.entryCreate(body())
    return r.data
  }
  const save = useMutation({ mutationFn: saveDraft, onSuccess: (d) => afterChange(d, 'تم حفظ المسودة'), onError: fail })
  const approve = useMutation({
    mutationFn: async () => {
      let eid = id
      if (dirty || !eid) {
        // keep the saved draft even if the approval is then refused — a retry must not create a second one
        const saved = await saveDraft()
        eid = saved.id
        setId(eid); setDirty(false)
        qc.invalidateQueries({ queryKey: ['gl', 'entries'] })
      }
      return (await glApi.entryApprove(eid)).data
    },
    onSuccess: (d) => afterChange(d, d?.number ? `تم الاعتماد — ${d.number}` : 'تم الاعتماد'),
    onError: (e) => { fail(e); qc.invalidateQueries({ queryKey: ['gl', 'entry', id] }) },
  })
  const del = useMutation({
    mutationFn: () => glApi.entryDelete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['gl', 'entries'] }); onChanged?.(null); onClose() },
    onError: fail,
  })
  const reverse = useMutation({
    mutationFn: () => glApi.entryReverse(id, reason.trim()).then(r => r.data),
    onSuccess: (d) => { setReason(''); afterChange(null, d?.number ? `تم العكس بالقيد ${d.number}` : 'تم عكس القيد') },
    onError: fail,
  })
  const busy = save.isPending || approve.isPending || del.isPending || reverse.isPending

  const cell = 'px-1.5 py-1 align-top'
  return (
    <div className="fixed inset-y-0 left-0 z-40 w-full max-w-[1100px] bg-white shadow-2xl border-e border-gray-200 flex flex-col" dir="rtl">
      {/* header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200">
        <h2 className="text-lg font-bold text-gray-900">
          {id ? (entry?.number || 'مسودة قيد') : 'قيد يدوي جديد'}
        </h2>
        {id && entry && <StatusPill status={entry.status} />}
        {isReversal && <span className="text-xs text-gray-500">قيد عكسي</span>}
        {entry?.source_type && <span className="text-xs text-gray-500">المصدر: {entry.source_type}</span>}
        <button type="button" onClick={onClose} className="ms-auto text-gray-400 hover:text-gray-700 text-xl" title="إغلاق (Esc)">×</button>
      </div>

      {id && entryQ.isLoading ? <div className="p-8 flex justify-center"><Spinner size="md" /></div>
        : id && entryQ.isError ? <div className="p-4"><ErrorBox>{errOf(entryQ.error, 'تعذّر تحميل القيد')}</ErrorBox></div> : (
        <div className="flex-1 overflow-auto p-4 space-y-3">
          {/* entry header */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <label className="space-y-1"><span className="text-xs text-gray-500">التاريخ</span>
              <input type="date" className={`${inputCls} w-full`} value={form.entry_date} disabled={!editable}
                     onChange={e => set({ entry_date: e.target.value })} /></label>
            <label className="space-y-1"><span className="text-xs text-gray-500">الدفتر</span>
              <select className={`${inputCls} w-full`} value={form.book} disabled={!editable} onChange={e => set({ book: e.target.value })}>
                {Object.entries(BOOKS).filter(([k]) => editable ? ['general', 'cash', 'credit'].includes(k) || k === form.book : true)
                  .map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
            <label className="space-y-1"><span className="text-xs text-gray-500">الفرع (اختياري)</span>
              {editable
                ? <BranchSelect size="sm" branches={branches} value={form.branch} allLabel="بدون فرع" onChange={v => set({ branch: v })} />
                : <div className="py-1.5">{labelOf(form.branch, entry?.branch_name) || '—'}</div>}
            </label>
            <div className="space-y-1 text-xs text-gray-500">
              {entry?.created_by_name && <div>أنشأه: {entry.created_by_name}{entry.created_at ? ` · ${String(entry.created_at).slice(0, 16).replace('T', ' ')}` : ''}</div>}
              {entry?.approved_by_name && <div>اعتمده: {entry.approved_by_name}{entry.approved_at ? ` · ${String(entry.approved_at).slice(0, 16).replace('T', ' ')}` : ''}</div>}
            </div>
            <label className="space-y-1 col-span-2 md:col-span-4"><span className="text-xs text-gray-500">البيان</span>
              <input className={`${inputCls} w-full`} value={form.description} disabled={!editable}
                     onChange={e => set({ description: e.target.value })} /></label>
          </div>

          {/* lines */}
          <div className="border border-gray-200 rounded-lg overflow-x-auto" data-tour="finance-gl-entry-lines">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-600">
                <tr>
                  <th className="px-1.5 py-2 text-right w-8">#</th>
                  <th className="px-1.5 py-2 text-right min-w-[220px]">الحساب</th>
                  <th className="px-1.5 py-2 text-right min-w-[150px]">الفرع</th>
                  <th className="px-1.5 py-2 text-right">الطرف</th>
                  <th className="px-1.5 py-2 text-right">مدين</th>
                  <th className="px-1.5 py-2 text-right">دائن</th>
                  <th className="px-1.5 py-2 text-right min-w-[160px]">البيان</th>
                  <th className="px-1.5 py-2 text-right">رقم الشيك</th>
                  <th className="px-1.5 py-2 text-right">الاستحقاق</th>
                  {editable && <th />}
                </tr>
              </thead>
              <tbody>
                {form.lines.map((l, i) => {
                  const acc = accountByCode[String(l.account_code)]
                  const needBranch = acc?.requires_branch && !l.branch_id
                  const needParty = acc?.party_type && acc.party_type !== 'none' && !l.party_code
                  return editable ? (
                    <tr key={l.key} className="border-t border-gray-100">
                      <td className={`${cell} text-gray-400 pt-2.5`}>{i + 1}</td>
                      <td className={cell}>
                        <AccountPicker value={l.account_code} name={l.account_name || acc?.name || ''} accounts={accounts}
                                       onPick={a => setLine(l.key, { account_code: a.code, account_name: a.name })} />
                      </td>
                      <td className={cell}>
                        <BranchSelect size="sm" branches={branches} value={l.branch_id} allLabel="—"
                                      onChange={v => setLine(l.key, { branch_id: v })} />
                        {needBranch && <div className="text-[10px] text-amber-700">الحساب يتطلب فرعاً</div>}
                      </td>
                      <td className={cell}>
                        <input className={`${inputCls} w-24`} value={l.party_code} onChange={e => setLine(l.key, { party_code: e.target.value })} />
                        {needParty && <div className="text-[10px] text-amber-700">الحساب يتطلب طرفاً</div>}
                      </td>
                      <td className={cell}>
                        <input type="number" step="0.01" min="0" dir="ltr" className={`${inputCls} w-28 text-left`} value={l.debit}
                               onChange={e => setLine(l.key, { debit: e.target.value, ...(e.target.value ? { credit: '' } : {}) })} />
                      </td>
                      <td className={cell}>
                        <input type="number" step="0.01" min="0" dir="ltr" className={`${inputCls} w-28 text-left`} value={l.credit}
                               onChange={e => setLine(l.key, { credit: e.target.value, ...(e.target.value ? { debit: '' } : {}) })} />
                      </td>
                      <td className={cell}><input className={`${inputCls} w-full`} value={l.description} onChange={e => setLine(l.key, { description: e.target.value })} /></td>
                      <td className={cell}><input className={`${inputCls} w-24`} value={l.cheque_no} onChange={e => setLine(l.key, { cheque_no: e.target.value })} /></td>
                      <td className={cell}><input type="date" className={inputCls} value={l.due_date} onChange={e => setLine(l.key, { due_date: e.target.value })} /></td>
                      <td className={cell}>
                        <button type="button" className="text-gray-400 hover:text-red-600 px-1 pt-1.5" title="حذف السطر" onClick={() => removeLine(l.key)}>×</button>
                      </td>
                    </tr>
                  ) : (
                    <tr key={l.key} className="border-t border-gray-100">
                      <td className="px-1.5 py-1.5 text-gray-400">{i + 1}</td>
                      <td className="px-1.5 py-1.5"><span className="font-mono text-gray-500">{l.account_code}</span> · {l.account_name || acc?.name}</td>
                      <td className="px-1.5 py-1.5">{labelOf(l.branch_id) || '—'}</td>
                      <td className="px-1.5 py-1.5 font-mono">{l.party_code || '—'}</td>
                      <td className="px-1.5 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(l.debit, { blankZero: true })}</td>
                      <td className="px-1.5 py-1.5 text-left font-mono tabular-nums" dir="ltr">{money(l.credit, { blankZero: true })}</td>
                      <td className="px-1.5 py-1.5">{l.description}</td>
                      <td className="px-1.5 py-1.5 font-mono">{l.cheque_no}</td>
                      <td className="px-1.5 py-1.5">{l.due_date}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {editable && (
              <button type="button" onClick={addLine} className="w-full text-sm text-green-700 hover:bg-green-50 py-1.5 border-t border-gray-100">+ سطر</button>
            )}
          </div>

          {/* totals — display only */}
          <div className="flex flex-wrap gap-4 text-sm bg-gray-50 rounded-lg px-3 py-2" data-tour="finance-gl-entry-totals">
            <span>إجمالي المدين: <b className="font-mono tabular-nums" dir="ltr">{money(totals.debit)}</b></span>
            <span>إجمالي الدائن: <b className="font-mono tabular-nums" dir="ltr">{money(totals.credit)}</b></span>
            <span className={totals.diff === 0 ? 'text-green-700' : 'text-red-600'}>
              الفرق: <b className="font-mono tabular-nums" dir="ltr">{money(totals.diff)}</b>
              {totals.diff === 0 && totals.debit > 0 ? ' ✓ متوازن' : ''}
            </span>
          </div>

          {editable && (
            <label className="block space-y-1 text-sm"><span className="text-xs text-gray-500">ملاحظات</span>
              <textarea rows={2} className={`${inputCls} w-full`} value={form.notes} onChange={e => set({ notes: e.target.value })} /></label>
          )}

          <ErrorBox>{err}</ErrorBox>
          {msg && <div className="text-sm text-green-700">{msg}</div>}

          {/* reverse an approved entry */}
          {status === 'approved' && !isReversal && perms.approve && (
            <div className="border border-gray-200 rounded-lg p-3 space-y-2">
              <div className="text-sm font-medium text-gray-700">عكس القيد</div>
              <p className="text-xs text-gray-500">القيد المعتمد لا يُعدّل. العكس ينشئ قيداً معتمداً بالأطراف المقابلة ويُعلِّم هذا القيد «معكوس».</p>
              <div className="flex gap-2">
                <input className={`${inputCls} flex-1`} placeholder="سبب العكس (مطلوب)" value={reason} onChange={e => setReason(e.target.value)} />
                <button type="button" className={btnPlain} disabled={!reason.trim() || busy} onClick={() => reverse.mutate()}>عكس القيد</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* footer actions */}
      {isDraft && (perms.create || perms.approve) && !(id && entryQ.isLoading) && (
        <div className="flex items-center gap-2 px-4 py-3 border-t border-gray-200 bg-gray-50">
          {perms.create && (
            <button type="button" className={btnPlain} disabled={busy || (!dirty && !!id)} onClick={() => save.mutate()}>
              {save.isPending ? 'جارٍ الحفظ…' : 'حفظ مسودة'}
            </button>
          )}
          {perms.approve && (
            <button type="button" className={btnPrimary} disabled={busy || (!id && !perms.create)} onClick={() => approve.mutate()}>
              {approve.isPending ? 'جارٍ الاعتماد…' : 'اعتماد'}
            </button>
          )}
          {id && perms.create && (
            confirmDelete ? (
              <span className="ms-auto flex items-center gap-2 text-sm">
                حذف المسودة نهائياً؟
                <button type="button" className={`${btnPlain} text-red-600 border-red-300`} disabled={busy} onClick={() => del.mutate()}>نعم، احذف</button>
                <button type="button" className={btnPlain} onClick={() => setConfirmDelete(false)}>لا</button>
              </span>
            ) : (
              <button type="button" className="ms-auto text-sm text-red-600 hover:underline" onClick={() => setConfirmDelete(true)}>حذف المسودة</button>
            )
          )}
        </div>
      )}
    </div>
  )
}
