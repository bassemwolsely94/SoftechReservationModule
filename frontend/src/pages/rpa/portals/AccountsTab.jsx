/**
 * AccountsTab — الحسابات (admin only; the server refuses anyone else and audits every change):
 * per site «مفعّل», basket size and «فعلي» (the ONLY place live entry is switched on — an inline
 * confirm, no popup), and the site accounts. An account holds a label, the name the robot checks
 * on the site and the paper branch: never a password or cookie.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { branchesApi, rpaPortalApi } from '../../../api/client'
import useBranchLabels from '../../../hooks/useBranchLabels'
import useSortableRows from '../../../hooks/useSortableRows'
import useHelpTab from '../../../help/useHelpTab'
import SortTh from '../../../components/SortTh'
import { ModeBadge, asList, credit, errText } from './shared.jsx'

function PortalRow({ p, onDone }) {
  const [size, setSize] = useState(String(p.basket_size))
  const [askLive, setAskLive] = useState(false)
  const [err, setErr] = useState('')
  const save = useMutation({
    mutationFn: data => rpaPortalApi.setPortal(p.key, data),
    onSuccess: () => { setErr(''); setAskLive(false); onDone() },
    onError: e => setErr(errText(e)),
  })
  return (
    <tr className="border-b border-line align-top">
      <td className="p-2 font-medium">{p.title} <span className="text-xs text-muted" dir="ltr">{p.supplier_code}</span></td>
      <td className="p-2">
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={p.enabled} disabled={save.isPending}
                 onChange={e => save.mutate({ enabled: e.target.checked })} /> مفعّل
        </label>
      </td>
      <td className="p-2">
        <div className="flex items-center gap-1">
          <input type="number" min="1" max="50" step="1" className="input-field w-20 text-sm" value={size}
                 aria-label="حجم السلة" onChange={e => setSize(e.target.value)} />
          {String(p.basket_size) !== size && (
            <button type="button" className="btn-secondary text-xs" disabled={save.isPending}
                    onClick={() => save.mutate({ basket_size: Number(size) })}>حفظ</button>
          )}
        </div>
      </td>
      <td className="p-2" data-tour="rpa-portals-live">
        <div className="flex flex-wrap items-center gap-2">
          <ModeBadge dryRun={!p.live} />
          {p.live ? (
            <button type="button" className="btn-ghost text-xs" disabled={save.isPending}
                    onClick={() => save.mutate({ live: false })}>رجوع للتجربة</button>
          ) : askLive ? (
            <>
              <span className="text-xs text-amber-700 dark:text-amber-300">الروبوت سيملأ السلة الحقيقية ويقف عند Submit.</span>
              <button type="button" className="btn-primary text-xs" disabled={save.isPending}
                      onClick={() => save.mutate({ live: true })}>تأكيد التشغيل الفعلي</button>
              <button type="button" className="btn-ghost text-xs" onClick={() => setAskLive(false)}>تراجع</button>
            </>
          ) : (
            <button type="button" className="btn-secondary text-xs" onClick={() => setAskLive(true)}>تشغيل فعلي…</button>
          )}
        </div>
        {err && <div className="text-xs text-red-600">{err}</div>}
      </td>
    </tr>
  )
}

function AccountRow({ a, branches, bl, onDone }) {
  const [label, setLabel] = useState(a.label)
  const [identity, setIdentity] = useState(a.identity_text)
  const [branch, setBranch] = useState(a.paper_branch ? String(a.paper_branch) : '')
  const [err, setErr] = useState('')
  const save = useMutation({
    mutationFn: data => rpaPortalApi.editAccount(a.id, data),
    onSuccess: () => { setErr(''); onDone() },
    onError: e => setErr(errText(e)),
  })
  const dirty = label !== a.label || identity !== a.identity_text || branch !== (a.paper_branch ? String(a.paper_branch) : '')
  return (
    <tr className="border-b border-line align-top">
      <td className="p-2 text-xs text-muted">{a.portal}</td>
      <td className="p-2"><input className="input-field text-sm w-36" value={label} maxLength={120} aria-label="اسم الحساب"
                                 onChange={e => setLabel(e.target.value)} /></td>
      <td className="p-2"><input className="input-field text-sm w-48" value={identity} maxLength={255} aria-label="الاسم كما يظهر في الموقع"
                                 onChange={e => setIdentity(e.target.value)} /></td>
      <td className="p-2">
        <select className="input-field text-sm" value={branch} aria-label="فرع الورق" onChange={e => setBranch(e.target.value)}>
          <option value="">—</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.softech_branch_id ? bl(b.softech_branch_id) : (b.name_ar || b.name)}</option>)}
        </select>
      </td>
      <td className="p-2 text-xs text-muted">{credit(a.last_credit)}</td>
      <td className="p-2">
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={a.active} disabled={save.isPending} onChange={e => save.mutate({ active: e.target.checked })} /> نشط
        </label>
      </td>
      <td className="p-2">
        {dirty && <button type="button" className="btn-secondary text-xs" disabled={save.isPending}
                          onClick={() => save.mutate({ label: label.trim(), identity_text: identity.trim(), paper_branch: branch ? Number(branch) : null })}>حفظ</button>}
        {err && <div className="text-xs text-red-600">{err}</div>}
      </td>
    </tr>
  )
}

export default function AccountsTab() {
  useHelpTab('accounts')
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [newPortal, setNewPortal] = useState('pharma_overseas')
  const [newLabel, setNewLabel] = useState('')
  const [newIdentity, setNewIdentity] = useState('')
  const [err, setErr] = useState('')
  const portalsQ = useQuery({ queryKey: ['rpa-portal', 'portals'], queryFn: () => rpaPortalApi.portals().then(r => r.data) })
  const accountsQ = useQuery({ queryKey: ['rpa-portal', 'accounts'], queryFn: () => rpaPortalApi.accounts().then(r => r.data) })
  const branchesQ = useQuery({ queryKey: ['rpa', 'branches'], queryFn: () => branchesApi.list({ page_size: 500 }).then(r => r.data),
                               staleTime: 30 * 60 * 1000 })
  const branches = useMemo(() => asList(branchesQ.data), [branchesQ.data])
  const portals = portalsQ.data?.portals || []
  const accounts = useMemo(() => asList(accountsQ.data), [accountsQ.data])
  const { sorted, headerProps } = useSortableRows(accounts, { persistKey: 'portal-accounts',
    getValue: (r, k) => (k === 'paper_branch' ? r.paper_branch_code : r[k]) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['rpa-portal'] })
  const add = useMutation({
    mutationFn: () => rpaPortalApi.addAccount({ portal: newPortal, label: newLabel.trim(), identity_text: newIdentity.trim() }),
    onSuccess: () => { setErr(''); setNewLabel(''); setNewIdentity(''); refresh() },
    onError: e => setErr(errText(e)),
  })

  return (
    <div data-tour="rpa-portals-accounts" className="space-y-4">
      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <th className="p-2 text-start">الموقع</th><th className="p-2 text-start">الحالة</th>
            <th className="p-2 text-start">حجم السلة</th><th className="p-2 text-start">تجربة / فعلي</th>
          </tr></thead>
          <tbody>{portals.map(p => <PortalRow key={`${p.key}-${p.basket_size}-${p.live}-${p.enabled}`} p={p} onDone={refresh} />)}</tbody>
        </table>
      </div>
      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-muted border-b border-line">
            <SortTh {...headerProps('portal')} className="p-2 text-start">الموقع</SortTh>
            <SortTh {...headerProps('label')} className="p-2 text-start">اسم الحساب</SortTh>
            <SortTh {...headerProps('identity_text')} className="p-2 text-start">الاسم كما يظهر في الموقع</SortTh>
            <SortTh {...headerProps('paper_branch')} className="p-2 text-start">فرع الورق</SortTh>
            <th className="p-2 text-start">آخر رصيد</th>
            <SortTh {...headerProps('active')} className="p-2 text-start">نشط</SortTh>
            <th className="p-2" />
          </tr></thead>
          <tbody>
            {sorted.map(a => <AccountRow key={a.id} a={a} branches={branches} bl={bl} onDone={refresh} />)}
            {!accounts.length && <tr><td colSpan={7} className="p-4 text-center text-muted">لا توجد حسابات.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="card p-3 flex flex-wrap items-end gap-2 text-sm">
        <div>
          <label className="label" htmlFor="pa-new-portal">الموقع</label>
          <select id="pa-new-portal" className="input-field text-sm" value={newPortal} onChange={e => setNewPortal(e.target.value)}>
            {portals.map(p => <option key={p.key} value={p.key}>{p.title}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="pa-new-label">اسم الحساب</label>
          <input id="pa-new-label" className="input-field text-sm" maxLength={120} value={newLabel} onChange={e => setNewLabel(e.target.value)} />
        </div>
        <div>
          <label className="label" htmlFor="pa-new-identity">الاسم كما يظهر في الموقع</label>
          <input id="pa-new-identity" className="input-field text-sm" maxLength={255} value={newIdentity} onChange={e => setNewIdentity(e.target.value)} />
        </div>
        <button type="button" className="btn-primary text-sm" disabled={!newLabel.trim() || add.isPending} onClick={() => add.mutate()}>إضافة حساب</button>
        <span className="text-xs text-muted">لا تُحفظ كلمة سر: تسجّل الدخول للموقع بنفسك على جهازك.</span>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    </div>
  )
}
