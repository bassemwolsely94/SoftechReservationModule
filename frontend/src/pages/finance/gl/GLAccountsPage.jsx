/**
 * GLAccountsPage.jsx — «دليل الحسابات»
 * Route: /finance/coa
 *
 * Finance's own 4-digit chart of accounts (replaces SOFTECH's unused template).
 * Group tree ↔ flat list, server-side wildcard search, balance to date from the
 * trial balance. Import (dry-run preview → confirm) and inline edit need ledger.edit.
 */
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { glApi } from '../../../api/client'
import { usePermissions } from '../../../hooks/usePermission'
import useSortableRows from '../../../hooks/useSortableRows'
import SortTh from '../../../components/SortTh'
import { SkeletonTable, EmptyState } from '../../../components/ui'
import {
  OPENING_DATE, money, errOf, listOf, todayIso, NATURE, SECTION,
  inputCls, btnPrimary, btnPlain, ErrorBox,
} from './glUi'

const PARTY = { none: '—', supplier: 'مورد', customer: 'عميل', employee: 'موظف', partner: 'شريك' }
const SECTION_ORDER = ['balance_sheet', 'trading', 'pl']

const groupOf = (a) => (a.group && typeof a.group === 'object' ? a.group : { id: a.group, name: a.group_name || '' })

function getValue(row, key) {
  if (key === 'group') return groupOf(row).name
  if (key === 'balance') return row._balance
  return row[key]
}

function useDebounced(v, ms = 300) {
  const [d, setD] = useState(v)
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t) }, [v, ms])
  return d
}

// ── Import: dry-run preview, then confirm ─────────────────────────────────────
function ImportBox({ onDone }) {
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [err, setErr] = useState('')
  const run = useMutation({
    mutationFn: ({ dry }) => glApi.accountsImport(file, dry).then(r => ({ dry, data: r.data })),
    onSuccess: ({ dry, data }) => {
      setErr('')
      if (dry) setPreview(data)
      else { setPreview(null); setFile(null); if (fileRef.current) fileRef.current.value = ''; onDone(data) }
    },
    onError: (e) => setErr(errOf(e, 'تعذّر قراءة الملف')),
  })
  const unknown = preview?.unknown_groups || []
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 space-y-2" data-tour="finance-gl-accounts-import">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-gray-700">استيراد من ميزان المراجعة (Excel)</span>
        <input ref={fileRef} type="file" accept=".xlsx" className="text-xs"
               onChange={e => { setFile(e.target.files?.[0] || null); setPreview(null); setErr('') }} />
        <button type="button" className={btnPlain} disabled={!file || run.isPending}
                onClick={() => run.mutate({ dry: true })}>معاينة</button>
        {preview && (
          <button type="button" className={btnPrimary} disabled={run.isPending}
                  onClick={() => run.mutate({ dry: false })}>تأكيد الاستيراد</button>
        )}
      </div>
      {preview && (
        <div className="text-sm text-gray-700">
          جديد: <b>{preview.created ?? 0}</b> · تحديث: <b>{preview.updated ?? 0}</b>
          {unknown.length > 0 && (
            <span className="text-amber-700"> · مجموعات غير معروفة لن تُستورد: {unknown.join('، ')}</span>
          )}
        </div>
      )}
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

// ── One account row (view or inline edit) ─────────────────────────────────────
function AccountRow({ a, canEdit, editing, onEdit, onCancel, onStatement }) {
  const qc = useQueryClient()
  const [form, setForm] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    if (editing) setForm({
      name: a.name || '', statement_line: a.statement_line || '', is_active: !!a.is_active,
      requires_branch: !!a.requires_branch, party_type: a.party_type || 'none',
    })
  }, [editing])   // eslint-disable-line react-hooks/exhaustive-deps -- a refetch must not wipe what is being typed
  const save = useMutation({
    mutationFn: () => glApi.accountUpdate(a.code, form),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['gl', 'accounts'] }); onCancel() },
    onError: (e) => setErr(errOf(e, 'تعذّر الحفظ')),
  })
  const bal = a._balance
  const cell = 'px-3 py-1.5'
  if (editing && form) {
    const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
    return (
      <tr className="bg-green-50/40">
        <td className={`${cell} font-mono`}>{a.code}</td>
        <td className={cell}><input className={`${inputCls} w-full`} value={form.name} onChange={set('name')} /></td>
        <td className={cell}>{groupOf(a).name}</td>
        <td className={cell}>{NATURE[a.nature] || a.nature}</td>
        <td className={cell}><input className={`${inputCls} w-28`} value={form.statement_line} onChange={set('statement_line')} /></td>
        <td className={cell}>
          <select className={inputCls} value={form.party_type} onChange={set('party_type')}>
            {Object.entries(PARTY).map(([k, l]) => <option key={k} value={k}>{k === 'none' ? 'بدون' : l}</option>)}
          </select>
          <label className="block text-xs mt-1"><input type="checkbox" checked={form.requires_branch} onChange={set('requires_branch')} /> يتطلب فرعاً</label>
        </td>
        <td className={cell}><input type="checkbox" checked={form.is_active} onChange={set('is_active')} /></td>
        <td className={cell} colSpan={2}>
          <div className="flex gap-1">
            <button type="button" className={btnPrimary} disabled={save.isPending} onClick={() => save.mutate()}>حفظ</button>
            <button type="button" className={btnPlain} onClick={onCancel}>إلغاء</button>
          </div>
          {err && <div className="text-xs text-red-600 mt-1">{err}</div>}
        </td>
      </tr>
    )
  }
  return (
    <tr className={`border-t border-gray-100 hover:bg-gray-50 ${a.is_active ? '' : 'text-gray-400'}`}>
      <td className={`${cell} font-mono`}>{a.code}</td>
      <td className={cell}>
        {a.name}
        {a.is_system && <span className="ms-1 text-[10px] text-blue-600">(نظام)</span>}
        {a.is_posting === false && <span className="ms-1 text-[10px] text-gray-500">(تجميعي)</span>}
      </td>
      <td className={cell}>{groupOf(a).name}</td>
      <td className={cell}>{NATURE[a.nature] || a.nature}</td>
      <td className={`${cell} text-xs font-mono text-gray-500`}>{a.statement_line || '—'}</td>
      <td className={`${cell} text-xs`}>
        {PARTY[a.party_type || 'none']}{a.requires_branch && <span className="block text-gray-500">يتطلب فرعاً</span>}
      </td>
      <td className={cell}>{a.is_active ? '✓' : '✗'}</td>
      <td className={`${cell} text-left font-mono tabular-nums ${bal < 0 ? 'text-red-600' : ''}`} dir="ltr">
        {bal === undefined ? '—' : (
          <button type="button" className="hover:underline" onClick={() => onStatement(a.code)} title="كشف حساب">
            {money(Math.abs(bal))} {bal === 0 ? '' : bal > 0 ? 'Dr' : 'Cr'}
          </button>
        )}
      </td>
      <td className={cell}>
        {canEdit && <button type="button" className="text-xs text-green-700 hover:underline" onClick={onEdit}>تعديل</button>}
      </td>
    </tr>
  )
}

export default function GLAccountsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const perms = usePermissions('ledger')
  const [view, setView] = useState('tree')
  const [q, setQ] = useState('')
  const [group, setGroup] = useState('')
  const [active, setActive] = useState('true')
  const [editing, setEditing] = useState(null)
  const [collapsed, setCollapsed] = useState({})
  const [importMsg, setImportMsg] = useState('')
  const dq = useDebounced(q)

  const groupsQ = useQuery({
    queryKey: ['gl', 'groups'],
    queryFn: () => glApi.groups().then(r => listOf(r.data)),
  })
  const accountsQ = useQuery({
    queryKey: ['gl', 'accounts', dq, group, active],
    queryFn: () => glApi.accounts({ q: dq || undefined, group: group || undefined, active: active || undefined, page_size: 2000 })
      .then(r => listOf(r.data)),
    placeholderData: (prev) => prev,
  })
  // balance to date = closing column of the trial balance from the opening date to today
  const today = todayIso()
  const tbQ = useQuery({
    queryKey: ['gl', 'tb-balances', today],
    queryFn: () => glApi.trialBalance({ from: OPENING_DATE, to: today, by: 'account' }).then(r => r.data),
    staleTime: 60 * 1000,
  })
  const balanceByCode = useMemo(() => {
    const rows = Array.isArray(tbQ.data) ? tbQ.data : (tbQ.data?.rows || [])
    return Object.fromEntries(rows.filter(r => r.code).map(r =>
      [String(r.code), Number(r.closing_debit || 0) - Number(r.closing_credit || 0)]))
  }, [tbQ.data])

  const rows = useMemo(() => (accountsQ.data || []).map(a => ({
    ...a, _balance: tbQ.data ? (balanceByCode[String(a.code)] ?? 0) : undefined,
  })), [accountsQ.data, balanceByCode, tbQ.data])
  const { sorted, headerProps } = useSortableRows(rows, {
    getValue, persistKey: 'gl-accounts', defaultSort: { key: 'code', dir: 'asc', type: 'text' },
  })

  // tree: groups in section/order, each holding its (sorted) accounts
  const tree = useMemo(() => {
    const groups = groupsQ.data || []
    const meta = Object.fromEntries(groups.map(g => [String(g.id), g]))
    const buckets = new Map()
    for (const a of sorted) {
      const g = groupOf(a)
      const key = String(g.id ?? g.name)
      if (!buckets.has(key)) buckets.set(key, { group: { ...g, ...(meta[key] || {}) }, accounts: [] })
      buckets.get(key).accounts.push(a)
    }
    const rank = (g) => [SECTION_ORDER.indexOf(g.section), g.order ?? 0]
    return [...buckets.values()].sort((x, y) => {
      const [s1, o1] = rank(x.group); const [s2, o2] = rank(y.group)
      return s1 - s2 || o1 - o2 || String(x.group.name).localeCompare(String(y.group.name), 'ar')
    })
  }, [sorted, groupsQ.data])

  const toStatement = (code) => navigate(`/finance/ledger?code=${encodeURIComponent(code)}`)
  const rowFor = (a) => (
    <AccountRow key={a.code} a={a} canEdit={!!perms.edit} editing={editing === a.code}
                onEdit={() => setEditing(a.code)} onCancel={() => setEditing(null)} onStatement={toStatement} />
  )
  const groupBalance = (accs) => accs.reduce((s, a) => s + (a._balance || 0), 0)

  return (
    <div className="space-y-4" dir="rtl" data-tour="finance-coa-view">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-lg border border-gray-300 overflow-hidden text-sm">
          {[['tree', 'شجرة'], ['flat', 'قائمة']].map(([k, l]) => (
            <button key={k} type="button" onClick={() => setView(k)}
                    className={`px-3 py-1.5 ${view === k ? 'bg-green-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>{l}</button>
          ))}
        </div>
        <input className={`${inputCls} w-64`} placeholder="بحث بالكود أو الاسم (* أو % للبدل)" value={q}
               onChange={e => setQ(e.target.value)} />
        <select className={inputCls} value={group} onChange={e => setGroup(e.target.value)}>
          <option value="">كل المجموعات</option>
          {(groupsQ.data || []).map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
        </select>
        <select className={inputCls} value={active} onChange={e => setActive(e.target.value)}>
          <option value="true">النشطة</option>
          <option value="false">الموقوفة</option>
          <option value="">الكل</option>
        </select>
        <span className="text-xs text-gray-500 ms-auto">
          {accountsQ.data ? `${accountsQ.data.length} حساب` : ''} · الرصيد حتى {today}
        </span>
      </div>

      {perms.edit && <ImportBox onDone={(r) => {
        setImportMsg(`تم الاستيراد: ${r?.created ?? 0} جديد، ${r?.updated ?? 0} تحديث`)
        qc.invalidateQueries({ queryKey: ['gl'] })
      }} />}
      {importMsg && <div className="text-sm text-green-700">{importMsg}</div>}

      <ErrorBox>{accountsQ.isError ? errOf(accountsQ.error, 'تعذّر تحميل دليل الحسابات') : ''}</ErrorBox>
      {tbQ.isError && <div className="text-xs text-amber-700">تعذّر حساب الأرصدة: {errOf(tbQ.error)}</div>}

      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="finance-gl-accounts-tree">
        {accountsQ.isLoading ? <SkeletonTable rows={8} cols={7} /> : !sorted.length ? (
          <EmptyState title="لا توجد حسابات" sub={perms.edit ? 'استورد دليل الحسابات من ميزان المراجعة' : 'لم يُستورد دليل الحسابات بعد'} />
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600 text-xs">
              <tr>
                <SortTh {...headerProps('code', 'text')} className="text-right px-3 py-2">الكود</SortTh>
                <SortTh {...headerProps('name')} className="text-right px-3 py-2">اسم الحساب</SortTh>
                <SortTh {...headerProps('group')} className="text-right px-3 py-2">المجموعة</SortTh>
                <SortTh {...headerProps('nature')} className="text-right px-3 py-2">الطبيعة</SortTh>
                <SortTh {...headerProps('statement_line')} className="text-right px-3 py-2">بند القائمة</SortTh>
                <SortTh {...headerProps('party_type')} className="text-right px-3 py-2">الطرف</SortTh>
                <SortTh {...headerProps('is_active')} className="text-right px-3 py-2">نشط</SortTh>
                <SortTh {...headerProps('balance', 'number')} className="text-left px-3 py-2">الرصيد حتى اليوم</SortTh>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {view === 'flat' ? sorted.map(rowFor) : tree.map(({ group: g, accounts }) => {
                const key = String(g.id ?? g.name)
                const closed = !!collapsed[key]
                const gb = groupBalance(accounts)
                return (
                  <Fragment key={key}>
                    <tr className="bg-gray-50 border-t border-gray-200 cursor-pointer select-none"
                        onClick={() => setCollapsed(c => ({ ...c, [key]: !c[key] }))}>
                      <td className="px-3 py-2 font-bold text-gray-800" colSpan={7}>
                        <span className="inline-block w-4 text-gray-400">{closed ? '◂' : '▾'}</span>
                        {g.name}
                        <span className="ms-2 text-xs font-normal text-gray-500">
                          {SECTION[g.section] || ''} · {accounts.length} حساب
                        </span>
                      </td>
                      <td className="px-3 py-2 text-left font-mono tabular-nums font-bold" dir="ltr">
                        {tbQ.data ? `${money(Math.abs(gb))} ${gb === 0 ? '' : gb > 0 ? 'Dr' : 'Cr'}` : ''}
                      </td>
                      <td />
                    </tr>
                    {!closed && accounts.map(rowFor)}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
