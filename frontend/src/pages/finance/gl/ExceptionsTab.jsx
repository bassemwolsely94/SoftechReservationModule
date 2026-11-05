/**
 * ExceptionsTab.jsx — «الاستثناءات»: SOFTECH documents the drafting engine could not turn into a
 * draft (unmapped party / account, no or clashing rule, closed-period change…).
 *
 * Grouped by kind; each row offers the fix for ITS kind inline (confirm/create the party, map the
 * value, open the rule editor prefilled, or just ignore with a note). «إعادة الترحيل» re-runs the
 * engine for the selected documents. Nothing is decided here — the server resolves every fix.
 * closed_period_change is read-only in Plan 2 (the correction button arrives with the period close).
 * An accountant-edited entry SOFTECH changed (ledger_error / edited_by_user, Ruling P23) shows both
 * versions side by side with «اعتماد نسخة سوفتيك» / «إبقاء تعديلي» (ledger.approve).
 */
import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import useSortableRows from '../../../hooks/useSortableRows'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../../hooks/useGridKeyboard'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import { AccountPicker } from './EntryEditor'
import RuleEditor, { SOURCE_TYPES, MAP_KINDS } from './RuleEditor'
import { amountsText } from './SourcePanel'
import {
  money, errOf, listOf, useGlBranches, inputCls, btnPrimary, btnPlain, ErrorBox,
} from './glUi'

export const KIND_LABEL = {
  unmapped_party: 'طرف غير مربوط', unmapped_account: 'حساب غير مربوط', no_rule: 'لا توجد قاعدة',
  ambiguous_rule: 'قاعدتان متعارضتان', unbalanced_rule: 'قاعدة غير متوازنة',
  closed_period_change: 'تغيير في فترة مغلقة', duplicate_source_key: 'مفتاح مصدر مكرر', ledger_error: 'خطأ في الدفتر',
}
const KIND_ORDER = Object.keys(KIND_LABEL)
const CUSTOMER_SOURCES = new Set(['credit_sales', 'customer_collections'])
const MAIN_AMOUNT = ['net', 'amount', 'value', 'sales', 'credit']

const mainAmount = (a) => { const k = MAIN_AMOUNT.find(x => a?.[x] !== undefined); return k ? a[k] : null }
const refOf = (d) => [d.attrs?.docnumber, d.attrs?.cheqno, d.attrs?.cheqsno].filter(Boolean).join(' / ') || d.source_key

// ── unmapped_party: confirm the proposal, or create a confirmed party ────────
function PartyFix({ ex, onDone }) {
  const { doc, detail } = ex
  const personcode = String(detail?.personcode || doc.personcode || '')
  const type = detail?.party_type || (CUSTOMER_SOURCES.has(doc.source_type) ? 'customer' : 'supplier')
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [err, setErr] = useState('')
  const found = useQuery({
    queryKey: ['gl', 'parties', 'by-person', personcode],
    queryFn: () => glApi.parties({ q: personcode }).then(r => listOf(r.data).find(p => String(p.softech_personcode) === personcode) || null),
    enabled: !!personcode,
  })
  const confirm = useMutation({
    mutationFn: (p) => glApi.partyConfirm(p.id, personcode),
    onSuccess: () => { setErr(''); onDone('تم تأكيد الطرف — اضغط «إعادة الترحيل»') },
    onError: (e) => setErr(errOf(e, 'تعذّر التأكيد')),
  })
  const create = useMutation({
    mutationFn: () => glApi.partyCreate({ type, code: code.trim(), personcode, name: name.trim() }),
    onSuccess: () => { setErr(''); onDone('تم إنشاء الطرف وتأكيده — اضغط «إعادة الترحيل»') },
    onError: (e) => setErr(errOf(e, 'تعذّر إنشاء الطرف')),
  })
  const p = found.data
  return (
    <div className="space-y-1.5 text-sm">
      <div className="text-xs text-gray-600">شخص SOFTECH <span className="font-mono">{personcode || '—'}</span> ({type === 'customer' ? 'عميل' : 'مورد'})</div>
      {found.isLoading ? <div className="text-xs text-gray-500">جاري البحث…</div>
        : p && p.status === 'confirmed' ? (
          <div className="text-green-700">الطرف {p.code} مؤكد بالفعل — أعد الترحيل</div>
        ) : p ? (
          <div className="flex items-center gap-2">
            <span>{p.status === 'rejected' ? 'طرف مرفوض سابقاً' : 'الطرف المقترح'}: <b>{p.code}</b> · {p.name}</span>
            <button type="button" className={btnPrimary} disabled={confirm.isPending} onClick={() => confirm.mutate(p)}>
              {p.status === 'rejected' ? 'إعادة تأكيد الطرف' : 'تأكيد الطرف'}
            </button>
          </div>
        ) : (
          <form className="flex flex-wrap items-center gap-2" onSubmit={e => { e.preventDefault(); if (code.trim()) create.mutate() }}>
            <input className={`${inputCls} w-32`} placeholder="كود الطرف (مالية)" value={code} onChange={e => setCode(e.target.value)} />
            <input className={`${inputCls} w-56`} placeholder="الاسم (اختياري)" value={name} onChange={e => setName(e.target.value)} />
            <button type="submit" className={btnPrimary} disabled={!code.trim() || create.isPending}>إنشاء وتأكيد</button>
          </form>
        )}
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

// ── unmapped_account with a (kind, value): map it now ────────────────────────
function MapFix({ ex, onDone }) {
  const { branches, labelOf } = useGlBranches()
  const kind = ex.detail?.kind
  const value = String(ex.detail?.value ?? ex.detail?.key ?? '')
  const [account, setAccount] = useState('')
  const [branch, setBranch] = useState('')
  const [err, setErr] = useState('')
  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', 'posting'],
    queryFn: () => glApi.accounts({ active: 'true', page_size: 2000 }).then(r => listOf(r.data)),
    staleTime: 5 * 60 * 1000,
  })
  const accounts = useMemo(() => (accountsQ.data || []).filter(a => a.is_posting !== false), [accountsQ.data])
  const name = accounts.find(a => String(a.code) === String(account))?.name || ''
  const needBranch = ex.detail?.reason === 'map has no branch' || kind === 'bank' || kind === 'card_clearing' || kind === 'intercompany'
  const save = useMutation({
    mutationFn: () => glApi.mapPut(kind, value, { account_code: account, branch_id: branch ? Number(branch) : null, note: '' }),
    onSuccess: () => { setErr(''); onDone('تم الربط — اضغط «إعادة الترحيل»') },
    onError: (e) => setErr(errOf(e, 'تعذّر الحفظ')),
  })
  return (
    <div className="space-y-1.5 text-sm">
      <div className="text-xs text-gray-600">ربط {MAP_KINDS[kind] || kind}: <span className="font-mono">{value}</span></div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-72"><AccountPicker value={account} name={name} accounts={accounts} onPick={a => setAccount(a.code)} /></div>
        <select className={inputCls} value={branch} onChange={e => setBranch(e.target.value)}>
          <option value="">{needBranch ? '— اختر فرعاً —' : 'بدون فرع'}</option>
          {branches.map(b => <option key={b.id} value={b.id}>{labelOf(b.id)}</option>)}
        </select>
        <button type="button" className={btnPrimary} disabled={!account || (needBranch && !branch) || save.isPending} onClick={() => save.mutate()}>حفظ الربط</button>
      </div>
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

function IgnoreBox({ ex, canCreate, onDone }) {
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const ignore = useMutation({
    mutationFn: () => glApi.exceptionIgnore(ex.id, note.trim()),
    onSuccess: () => { setErr(''); onDone('تم التجاهل', true) },
    onError: (e) => setErr(errOf(e, 'تعذّر التجاهل')),
  })
  if (!canCreate) return null
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        <input className={`${inputCls} flex-1 max-w-md`} placeholder="سبب التجاهل (مطلوب)" value={note} onChange={e => setNote(e.target.value)} />
        <button type="button" className={btnPlain} disabled={!note.trim() || ignore.isPending} onClick={() => ignore.mutate()}>تجاهل</button>
      </div>
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

// ── ledger_error / edited_by_user (Ruling P23): the accountant's edit vs the new SOFTECH lines ──
const s_ = (v) => String(v ?? '')
const amt = (v) => Number(v || 0).toFixed(2)
const matchKey = (l) => [s_(l?.account_code), s_(l?.branch_id), s_(l?.party_code)].join('|')
const CMP = [
  ['debit', (l) => amt(l.debit)], ['credit', (l) => amt(l.credit)], ['description', (l) => s_(l.description)],
  ['cheque_no', (l) => s_(l.cheque_no)], ['due_date', (l) => s_(l.due_date).slice(0, 10)],
]

/** Pair lines by (account, branch, party) — not by position — so an inserted line does not shift
 *  every row after it. -> [{mine, theirs}] in the order of «mine», then lines only SOFTECH has. */
function pairLines(mine, theirs) {
  const pool = new Map()
  theirs.forEach((l, i) => { const k = matchKey(l); pool.set(k, [...(pool.get(k) || []), i]) })
  const used = new Set()
  const rows = mine.map((l) => {
    const q = pool.get(matchKey(l)) || []
    const i = q.shift()
    if (i === undefined) return { mine: l, theirs: null }
    used.add(i)
    return { mine: l, theirs: theirs[i] }
  })
  theirs.forEach((l, i) => { if (!used.has(i)) rows.push({ mine: null, theirs: l }) })
  return rows
}

function DiffTable({ rows, labelOf, accountName }) {
  const hl = 'bg-amber-100 font-bold'
  const side = (l, o, extraRow) => {
    if (!l) return <td colSpan={5} className="px-2 py-1 text-gray-400 border-e border-gray-200">— لا يوجد —</td>
    const ch = (j) => (extraRow || (o && CMP[j][1](o) !== CMP[j][1](l)) ? hl : '')
    const meta = [l.description, l.cheque_no && `شيك ${l.cheque_no}`, l.due_date && `استحقاق ${s_(l.due_date).slice(0, 10)}`].filter(Boolean)
    const metaChanged = [2, 3, 4].some(j => ch(j))
    return (
      <>
        <td className={`px-2 py-1 ${extraRow ? hl : ''}`}><span className="font-mono">{l.account_code}</span> {l.account_name || accountName(l.account_code)}</td>
        <td className={`px-2 py-1 ${extraRow ? hl : ''}`}>{labelOf(l.branch_id, l.branch_name) || '—'}{l.party_code ? <> · <span className="font-mono">{l.party_code}</span></> : null}</td>
        <td className={`px-2 py-1 text-left font-mono tabular-nums ${ch(0)}`} dir="ltr">{money(l.debit, { blankZero: true })}</td>
        <td className={`px-2 py-1 text-left font-mono tabular-nums ${ch(1)}`} dir="ltr">{money(l.credit, { blankZero: true })}</td>
        <td className={`px-2 py-1 text-gray-600 border-e border-gray-200 ${metaChanged ? hl : ''}`}>{meta.join(' · ') || '—'}</td>
      </>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs bg-white border border-gray-200 rounded">
        <thead className="bg-gray-50 text-gray-500">
          <tr>
            <th colSpan={5} className="text-right px-2 py-1 border-e border-gray-200 text-gray-700">القيد بعد تعديلك</th>
            <th colSpan={5} className="text-right px-2 py-1 text-gray-700">نسخة سوفتيك الجديدة</th>
          </tr>
          <tr>
            {[0, 1].map(k => (
              <Fragment key={k}>
                <th className="text-right px-2 py-1">الحساب</th><th className="text-right px-2 py-1">الفرع · الطرف</th>
                <th className="text-left px-2 py-1">مدين</th><th className="text-left px-2 py-1">دائن</th>
                <th className="text-right px-2 py-1 border-e border-gray-200">البيان · شيك · استحقاق</th>
              </Fragment>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-gray-100">
              {side(r.mine, r.theirs, !r.theirs)}
              {side(r.theirs, r.mine, !r.mine)}
            </tr>
          ))}
          {!rows.length && <tr><td colSpan={10} className="px-2 py-2 text-gray-500">لا أسطر</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

function EditDecision({ ex, perms, onDone, onRunStarted, onBusy }) {
  const { labelOf } = useGlBranches()
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')
  const d = ex.detail || {}
  const entryId = d.entry_id
  const entryQ = useQuery({
    queryKey: ['gl', 'entry', entryId],
    queryFn: () => glApi.entry(entryId).then(r => r.data),
    enabled: !!entryId,
  })
  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', 'posting'],
    queryFn: () => glApi.accounts({ active: 'true', page_size: 2000 }).then(r => listOf(r.data)),
    staleTime: 5 * 60 * 1000,
  })
  const accountName = (code) => (accountsQ.data || []).find(a => String(a.code) === String(code))?.name || ''
  const entry = entryQ.data
  const softech = Array.isArray(ex.proposed_lines) ? ex.proposed_lines : []
  const rows = useMemo(() => pairLines(entry?.lines || [], softech), [entry, softech])
  const dateChanged = entry && d.proposed_entry_date && s_(entry.entry_date).slice(0, 10) !== d.proposed_entry_date
  const descChanged = entry && d.proposed_description !== undefined && s_(entry.description) !== s_(d.proposed_description)
  const fail = (e, fallback) => {
    if (e?.response?.status === 409 && e?.response?.data?.code === 'busy') onBusy?.()
    setErr(errOf(e, fallback))
  }
  const body = () => ({ note: note.trim(), version: ex.proposal_version })
  const accept = useMutation({
    mutationFn: () => glApi.exceptionAcceptSoftech(ex.id, body()).then(r => r.data),
    onSuccess: (r) => { setErr(''); onRunStarted?.(r.run_id); onDone('اعتُمدت نسخة سوفتيك — يُعاد ترحيل المجموعة الآن', true) },
    onError: (e) => fail(e, 'تعذّر اعتماد نسخة سوفتيك'),
  })
  const keep = useMutation({
    mutationFn: () => glApi.exceptionKeepEdit(ex.id, body()),
    onSuccess: () => { setErr(''); onDone('أُبقي تعديلك — لن يتغير القيد حتى يتغير مستند سوفتيك مرة أخرى', true) },
    onError: (e) => fail(e, 'تعذّر إبقاء التعديل'),
  })
  const busy = accept.isPending || keep.isPending
  return (
    <div className="space-y-2 text-sm">
      <div className="text-xs text-gray-600">
        عدّل محاسب القيد <Link className="text-green-700 hover:underline" to={`/finance/journal?entry=${entryId}&tab=entries`}>#{entry?.number || entryId}</Link>
        {d.entry_status === 'approved' ? ' (معتمد — الاعتماد يعكسه ويُنشئ مسودة جديدة)' : ' (مسودة)'} ثم تغير مستند سوفتيك. الفروق مظللة.
      </div>
      {(dateChanged || descChanged) && (
        <div className="text-xs bg-amber-50 border border-amber-200 rounded px-2 py-1 space-y-0.5">
          {dateChanged && <div>التاريخ: {s_(entry.entry_date).slice(0, 10)} ← في سوفتيك <b>{d.proposed_entry_date}</b></div>}
          {descChanged && <div>البيان: «{entry.description}» ← في سوفتيك <b>«{d.proposed_description}»</b></div>}
        </div>
      )}
      {entryQ.isLoading ? <div className="text-xs text-gray-500">جاري تحميل القيد…</div>
        : <DiffTable rows={rows} labelOf={labelOf} accountName={accountName} />}
      {!softech.length && <div className="text-xs text-gray-600">نسخة سوفتيك: لا شيء يُرحّل لهذه المجموعة الآن (المسودة تُحذف أو المعتمد يُعكس).</div>}
      {d.held_out > 0 && (
        <div className="text-xs text-amber-700">ملاحظة: نسخة سوفتيك لا تشمل {d.held_out} مستند(ات) من المجموعة محجوزة باستثناءات خاصة بها — عالجها وستدخل القيد عند إعادة الترحيل.</div>
      )}
      {perms.approve ? (
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${inputCls} flex-1 max-w-md`} placeholder="ملاحظة (اختياري)" value={note} onChange={e => setNote(e.target.value)} />
          <button type="button" className={btnPrimary} disabled={busy || !ex.proposal_version} onClick={() => accept.mutate()}>اعتماد نسخة سوفتيك</button>
          <button type="button" className={btnPlain} disabled={busy || !ex.proposal_version} onClick={() => keep.mutate()}>إبقاء تعديلي</button>
        </div>
      ) : <div className="text-xs text-gray-500">القرار يحتاج صلاحية الاعتماد</div>}
      <ErrorBox>{err || (entryQ.isError ? errOf(entryQ.error, 'تعذّر تحميل القيد') : '')}</ErrorBox>
    </div>
  )
}

function RowActions({ ex, perms, onDone, onOpenRule, onRunStarted, onBusy }) {
  const { kind, doc, detail } = ex
  let fix
  if (kind === 'ledger_error' && detail?.code === 'edited_by_user') {
    fix = <EditDecision ex={ex} perms={perms} onDone={onDone} onRunStarted={onRunStarted} onBusy={onBusy} />
  } else if (kind === 'unmapped_party') {
    fix = perms.approve ? <PartyFix ex={ex} onDone={onDone} /> : <div className="text-xs text-gray-500">تأكيد الطرف يحتاج صلاحية الاعتماد</div>
  } else if (kind === 'unmapped_account') {
    if (detail?.kind && (detail?.value !== undefined || detail?.key !== undefined)) {
      fix = perms.edit ? <MapFix ex={ex} onDone={onDone} /> : <div className="text-xs text-gray-500">الربط يحتاج صلاحية التعديل</div>
    } else if (detail?.account) {
      fix = <div className="text-xs text-gray-600">الحساب <span className="font-mono">{detail.account}</span> غير موجود أو غير نشط أو ليس حساب ترحيل — صححه من <Link className="text-green-700 hover:underline" to="/finance/coa">دليل الحسابات</Link> أو عدّل القاعدة.</div>
    } else {
      fix = <div className="text-xs text-gray-600">الفرع غير موجود بين فروعنا — أضفه ثم أعد الترحيل.</div>
    }
  } else if (kind === 'no_rule' || kind === 'ambiguous_rule') {
    fix = (
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {kind === 'ambiguous_rule' && detail?.rules && <span className="text-xs text-gray-600">القواعد المتعارضة: {detail.rules.join('، ')}</span>}
        {perms.edit
          ? <button type="button" className={btnPrimary} onClick={() => onOpenRule(ex)}>فتح محرر القاعدة</button>
          : <span className="text-xs text-gray-500">تعديل القواعد يحتاج صلاحية التعديل</span>}
      </div>
    )
  } else if (kind === 'closed_period_change') {
    fix = (
      <div className="text-sm text-gray-700">
        يُصحح في أول شهر مفتوح.
        {ex.original_entry && <> القيد الأصلي: <Link className="text-green-700 hover:underline" to={`/finance/journal?entry=${ex.original_entry}&tab=entries`}>#{ex.original_entry}</Link></>}
      </div>
    )
  } else if (kind === 'unbalanced_rule') {
    fix = <div className="text-xs text-gray-600">مدين {detail?.debit} ≠ دائن {detail?.credit} — راجع أسطر القاعدة في «قواعد الترحيل».</div>
  } else {
    fix = <div className="text-xs text-gray-600">{ex.message}</div>
  }
  return (
    <div className="space-y-2">
      {fix}
      <IgnoreBox ex={ex} canCreate={!!perms.create} onDone={onDone} />
      <div className="text-[11px] text-gray-400 font-mono" dir="ltr">{doc.source_key}</div>
    </div>
  )
}

export default function ExceptionsTab({ filters, perms, onRunStarted, onBusy }) {
  const qc = useQueryClient()
  const { branches, labelOf } = useGlBranches()
  const branchName = (code) => {
    const b = branches.find(x => String(x.softech_branch_id) === String(code))
    return b ? labelOf(b.id) : '—'
  }
  const [kindFilter, setKindFilter] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const [openRow, setOpenRow] = useState(null)
  const [ruleFor, setRuleFor] = useState(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const params = useMemo(() => Object.fromEntries(Object.entries({
    kind: kindFilter, source_type: filters.source_type, date_from: filters.date_from,
    date_to: filters.date_to, branch: filters.branch,
  }).filter(([, v]) => v)), [kindFilter, filters])
  const listQ = useInfiniteQuery({
    queryKey: ['gl', 'exceptions', params],
    queryFn: ({ pageParam }) => (pageParam ? glApi.exceptionsPage(pageParam) : glApi.exceptions(params)).then(r => r.data),
    initialPageParam: null,
    getNextPageParam: (last) => last?.next ?? undefined,
  })
  const rows = useMemo(() => (listQ.data?.pages || []).flatMap(listOf).map(e => ({
    ...e, _date: e.source_date, _branch: branchName(e.doc?.branch_code),
    _source: SOURCE_TYPES[e.doc?.source_type] || e.doc?.source_type,
    _ref: refOf(e.doc), _amount: mainAmount(e.doc?.amounts),
  })), [listQ.data, branches]) // eslint-disable-line react-hooks/exhaustive-deps
  const { sorted, headerProps } = useSortableRows(rows, {
    persistKey: 'gl-exceptions', defaultSort: { key: '_date', dir: 'desc', type: 'date' },
  })
  const groups = useMemo(() => KIND_ORDER.map(k => ({ kind: k, items: sorted.filter(r => r.kind === k) })).filter(g => g.items.length), [sorted])
  const flat = useMemo(() => groups.flatMap(g => g.items), [groups])
  const selectable = useMemo(() => flat.filter(r => r.kind !== 'closed_period_change'), [flat])
  const countsQ = useQuery({
    queryKey: ['gl', 'exceptions', 'counts', filters.source_type || 'all'],
    queryFn: () => glApi.exceptionsCounts({ source_type: filters.source_type || undefined }).then(r => r.data),
  })
  const byKind = countsQ.data?.by_kind || {}

  useEffect(() => { setSelected(new Set()) }, [params])
  // keep only selections still in the loaded rows (after a redraft / ignore reload)
  useEffect(() => {
    setSelected(s => {
      const live = new Set(selectable.map(r => r.id))
      const n = new Set([...s].filter(id => live.has(id)))
      return n.size === s.size ? s : n
    })
  }, [selectable])
  const refresh = () => { qc.invalidateQueries({ queryKey: ['gl', 'exceptions'] }) }
  const toggle = (r) => r.kind !== 'closed_period_change' && setSelected(s => { const n = new Set(s); n.has(r.id) ? n.delete(r.id) : n.add(r.id); return n })
  const selectAll = () => setSelected(s => (s.size === selectable.length ? new Set() : new Set(selectable.map(r => r.id))))
  const kb = useGridKeyboard({
    rows: flat, getKey: r => r.id, onToggle: toggle, onSelectAll: selectAll,
    onConfirm: (r) => setOpenRow(o => (o === r.id ? null : r.id)), onClose: () => setOpenRow(null),
  })

  const redraft = useMutation({
    mutationFn: () => glApi.exceptionsRedraft([...selected]).then(r => r.data),
    onSuccess: (d) => { setErr(''); setMsg(''); setSelected(new Set()); onRunStarted(d.run_id) },
    onError: (e) => {
      if (e?.response?.status === 409) { setErr('يعمل بالفعل — هناك ترحيل جارٍ الآن'); onBusy?.() } else setErr(errOf(e, 'تعذّرت إعادة الترحيل'))
    },
  })
  const done = (text, closeRow) => { setMsg(text); setErr(''); if (closeRow) setOpenRow(null); refresh() }
  const openRule = (ex) => {
    const d = ex.doc
    const conditions = { branch_in: [String(d.branch_code)] }
    if (d.kind) conditions.kind_in = [d.kind]
    setRuleFor({ key: ex.id, source_type: d.source_type, conditions })
  }

  const canSelect = !!perms.create
  const colSpan = 7 + (canSelect ? 1 : 0)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {KIND_ORDER.filter(k => byKind[k] || k === kindFilter).map(k => (
          <button key={k} type="button" onClick={() => setKindFilter(x => (x === k ? '' : k))}
                  className={`px-2.5 py-1 rounded-full border text-xs ${kindFilter === k ? 'bg-green-600 text-white border-green-600' : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}`}>
            {KIND_LABEL[k]} · {byKind[k] ?? 0}
          </button>
        ))}
        {canSelect && (
          <button type="button" className={`${btnPrimary} ms-auto`} disabled={!selected.size || redraft.isPending} onClick={() => redraft.mutate()}>
            {redraft.isPending ? 'جاري البدء…' : `إعادة الترحيل${selected.size ? ` (${selected.size})` : ''}`}
          </button>
        )}
      </div>
      {msg && <div className="text-sm text-green-700">{msg}</div>}
      <ErrorBox>{err || (listQ.isError ? errOf(listQ.error, 'تعذّر تحميل الاستثناءات') : '')}</ErrorBox>

      <div className={ruleFor ? 'grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] items-start' : ''}>
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="finance-gl-exceptions-grid" {...kb.containerProps}>
          {listQ.isLoading ? <SkeletonTable rows={6} cols={7} /> : !flat.length ? (
            <EmptyState title="لا توجد استثناءات مفتوحة" sub="كل مستندات SOFTECH المقروءة رُحّلت كمسودات" />
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-gray-600 text-xs">
                <tr>
                  {canSelect && <th className="px-2 py-2 w-8"><input type="checkbox" checked={!!selectable.length && selected.size === selectable.length} onChange={selectAll} title="تحديد الكل" /></th>}
                  <SortTh {...headerProps('_date', 'date')} className="text-right px-3 py-2">التاريخ</SortTh>
                  <SortTh {...headerProps('_branch')} className="text-right px-3 py-2">الفرع</SortTh>
                  <SortTh {...headerProps('_source')} className="text-right px-3 py-2">المصدر</SortTh>
                  <SortTh {...headerProps('_ref')} className="text-right px-3 py-2">مرجع SOFTECH</SortTh>
                  <SortTh {...headerProps('_amount', 'number')} className="text-left px-3 py-2">المبلغ</SortTh>
                  <SortTh {...headerProps('message')} className="text-right px-3 py-2">السبب</SortTh>
                  <th className="px-3 py-2 w-16" />
                </tr>
              </thead>
              {groups.map(g => (
                <tbody key={g.kind}>
                  <tr className="bg-gray-100/70"><td colSpan={colSpan} className="px-3 py-1 text-xs font-bold text-gray-700">{KIND_LABEL[g.kind]} ({g.items.length})</td></tr>
                  {g.items.map(r => {
                    const kbp = kb.rowProps(r)
                    const isOpen = openRow === r.id
                    return (
                      <Fragment key={r.id}>
                        <tr {...kbp} className={`border-t border-gray-100 cursor-pointer hover:bg-gray-50 ${selected.has(r.id) ? 'bg-green-50/60' : ''} ${isOpen ? 'bg-blue-50/60' : ''} ${kbp.className}`}
                            onClick={() => setOpenRow(isOpen ? null : r.id)}>
                          {canSelect && <td className="px-2 py-1.5" onClick={e => e.stopPropagation()}><input type="checkbox" disabled={r.kind === 'closed_period_change'} checked={selected.has(r.id)} onChange={() => toggle(r)} /></td>}
                          <td className="px-3 py-1.5 whitespace-nowrap">{r._date}</td>
                          <td className="px-3 py-1.5">{r._branch}</td>
                          <td className="px-3 py-1.5">{r._source}</td>
                          <td className="px-3 py-1.5 font-mono text-xs" dir="ltr" title={amountsText(r.doc?.amounts)}>{r._ref}</td>
                          <td className="px-3 py-1.5 text-left font-mono tabular-nums" dir="ltr">{r._amount === null ? '—' : money(r._amount)}</td>
                          <td className="px-3 py-1.5 text-xs text-gray-700">{r.message}</td>
                          <td className="px-3 py-1.5 text-xs text-green-700">{isOpen ? 'إغلاق' : 'معالجة'}</td>
                        </tr>
                        {isOpen && (
                          <tr className="bg-gray-50/70"><td colSpan={colSpan} className="px-4 py-3" onClick={e => e.stopPropagation()}>
                            <RowActions ex={r} perms={perms} onDone={done} onOpenRule={openRule} onRunStarted={onRunStarted} onBusy={onBusy} />
                          </td></tr>
                        )}
                      </Fragment>
                    )
                  })}
                </tbody>
              ))}
            </table>
          )}
        </div>
        {ruleFor && (
          <RuleEditor rule={null} prefill={ruleFor} canEdit={!!perms.edit} onClose={() => setRuleFor(null)}
                      onSaved={() => { setMsg('تم حفظ القاعدة — اضغط «إعادة الترحيل» للمستندات المعنية'); refresh() }} />
        )}
      </div>
      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span>{GRID_KEYS_HINT.replace('Enter تأكيد · M مطابقة', 'Enter معالجة')}</span>
        {listQ.hasNextPage && (
          <button type="button" className={`${btnPlain} ms-auto`} disabled={listQ.isFetchingNextPage} onClick={() => listQ.fetchNextPage()}>
            {listQ.isFetchingNextPage ? 'جارٍ التحميل…' : 'تحميل المزيد'}
          </button>
        )}
      </div>
    </div>
  )
}
