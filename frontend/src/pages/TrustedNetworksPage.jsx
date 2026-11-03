/**
 * TrustedNetworksPage.jsx — الشبكات الموثوقة (admin only, security N1)
 *
 * The networks we recognise (branch LANs, the staff VPN, the server). Log only: a request from
 * a listed network is labelled with its site; nothing is refused because of its network.
 * One table with inline add / edit rows; delete asks for a second click on the row (no modal).
 * The caller's own «من أين أتصل؟» result sits at the top.
 *
 * Keys (useGridKeyboard): ↑↓ move · Enter edit the row · Esc cancel the delete prompt.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { accessApi, branchesApi } from '../api/client'
import useGridKeyboard from '../hooks/useGridKeyboard'
import useSortableRows from '../hooks/useSortableRows'
import SortTh from '../components/SortTh'
import { networkBadgeParts } from '../components/NetworkBadge'

const KINDS = [
  { value: 'branch_lan', label: 'شبكة فرع' },
  { value: 'staff_vpn', label: 'VPN الموظفين' },
  { value: 'server', label: 'سيرفر' },
]
const KIND_LABEL = Object.fromEntries(KINDS.map(k => [k.value, k.label]))
const BLANK = { name: '', cidr: '', kind: 'branch_lan', branch: '', is_active: true, notes: '' }

function errText(e) {
  const d = e?.response?.data
  if (!d) return 'تعذّر الحفظ'
  if (typeof d === 'string') return d
  return Object.values(d).flat().join(' · ') || 'تعذّر الحفظ'
}

function EditRow({ draft, setDraft, branches, onSave, onCancel, saving, error }) {
  const set = (k, v) => setDraft(d => ({ ...d, [k]: v }))
  const key = e => { if (e.key === 'Enter') onSave(); if (e.key === 'Escape') onCancel() }
  return (
    <>
      <tr className="bg-surface-2/60" onKeyDown={key}>
        <td className="p-2"><input className="input w-full" value={draft.name} autoFocus placeholder="الاسم"
                                   onChange={e => set('name', e.target.value)} /></td>
        <td className="p-2"><input className="input w-full font-mono" dir="ltr" value={draft.cidr} placeholder="192.168.3.0/24"
                                   onChange={e => set('cidr', e.target.value)} /></td>
        <td className="p-2">
          <select className="input w-full" value={draft.kind} onChange={e => set('kind', e.target.value)}>
            {KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </td>
        <td className="p-2">
          <select className="input w-full" value={draft.branch ?? ''} onChange={e => set('branch', e.target.value)}>
            <option value="">— بدون فرع —</option>
            {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
          </select>
        </td>
        <td className="p-2 text-center">
          <input type="checkbox" className="accent-brand-600" checked={!!draft.is_active}
                 onChange={e => set('is_active', e.target.checked)} />
        </td>
        <td className="p-2"><input className="input w-full" value={draft.notes} placeholder="ملاحظات"
                                   onChange={e => set('notes', e.target.value)} /></td>
        <td className="p-2 whitespace-nowrap text-end">
          <button className="btn-primary text-xs px-3 py-1" disabled={saving} onClick={onSave}>حفظ</button>
          <button className="text-xs text-muted px-2" onClick={onCancel}>إلغاء</button>
        </td>
      </tr>
      {error && <tr><td colSpan={7} className="px-3 pb-2 text-xs text-red-600">{error}</td></tr>}
    </>
  )
}

export default function TrustedNetworksPage() {
  const qc = useQueryClient()
  const me = useQuery({ queryKey: ['access-whoami'], queryFn: () => accessApi.whoami().then(r => r.data), retry: false })
  const list = useQuery({ queryKey: ['access-networks'], queryFn: () => accessApi.networks().then(r => r.data) })
  const bq = useQuery({ queryKey: ['branches-all'], queryFn: () => branchesApi.listAll().then(r => r.data), staleTime: 10 * 60 * 1000 })
  const rows = useMemo(() => (Array.isArray(list.data) ? list.data : (list.data?.results || [])), [list.data])
  const branches = useMemo(() => (Array.isArray(bq.data) ? bq.data : (bq.data?.results || [])), [bq.data])

  const [editing, setEditing] = useState(null)      // 'new' | row id | null
  const [draft, setDraft] = useState(BLANK)
  const [error, setError] = useState('')
  const [armed, setArmed] = useState(null)          // row id waiting for the second click on حذف

  const refresh = () => { qc.invalidateQueries({ queryKey: ['access-networks'] }); qc.invalidateQueries({ queryKey: ['access-whoami'] }) }
  const save = useMutation({
    mutationFn: () => {
      const body = { ...draft, branch: draft.branch === '' ? null : Number(draft.branch) }
      return editing === 'new' ? accessApi.createNetwork(body) : accessApi.updateNetwork(editing, body)
    },
    onSuccess: () => { setEditing(null); setError(''); refresh() },
    onError: e => setError(errText(e)),
  })
  const remove = useMutation({
    mutationFn: id => accessApi.deleteNetwork(id),
    onSuccess: () => { setArmed(null); refresh() },
    onError: e => { setArmed(null); setError(errText(e)) },
  })
  const toggle = useMutation({
    mutationFn: r => accessApi.updateNetwork(r.id, { is_active: !r.is_active }),
    onSuccess: refresh,
    onError: e => setError(errText(e)),
  })

  function startEdit(r) {
    setEditing(r.id); setError(''); setArmed(null)
    setDraft({ name: r.name, cidr: r.cidr, kind: r.kind, branch: r.branch ?? '', is_active: r.is_active, notes: r.notes || '' })
  }
  function startNew() { setEditing('new'); setError(''); setArmed(null); setDraft(BLANK) }
  function cancel() { setEditing(null); setError('') }

  const { sorted, headerProps } = useSortableRows(rows, {
    getValue: (r, k) => (k === 'kind' ? (KIND_LABEL[r.kind] || r.kind) : k === 'branch' ? r.branch_label : r[k]),
  })
  const kb = useGridKeyboard({
    rows: sorted, getKey: r => r.id, enabled: editing == null,
    onConfirm: startEdit, onClose: () => setArmed(null),
  })
  const mine = networkBadgeParts(me.data)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">🌐 الشبكات الموثوقة</h1>
          <p className="text-sm text-muted">الشبكات اللي النظام يعرفها (فروع، VPN، سيرفر). للتسجيل فقط — لا يُرفض أي طلب بسبب الشبكة.</p>
        </div>
        <button data-tour="admin-networks-add" className="btn-primary" onClick={startNew} disabled={editing === 'new'}>➕ إضافة شبكة</button>
      </div>

      <div data-tour="admin-networks-mine" className="card p-3 text-sm flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-semibold">أنت الآن:</span>
        {mine ? (
          <>
            <span>{mine.icon} {mine.text}</span>
            {me.data?.ip && <span className="font-mono text-muted" dir="ltr">{me.data.ip}</span>}
          </>
        ) : <span className="text-muted">…</span>}
      </div>

      {error && editing == null && <div className="text-sm text-red-600">{error}</div>}

      <div data-tour="admin-networks-table" className="card p-0 overflow-x-auto" {...kb.containerProps}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <SortTh {...headerProps('name')} className="p-2 text-start">الاسم</SortTh>
              <SortTh {...headerProps('cidr')} className="p-2 text-start">النطاق (CIDR)</SortTh>
              <SortTh {...headerProps('kind')} className="p-2 text-start">النوع</SortTh>
              <SortTh {...headerProps('branch')} className="p-2 text-start">الفرع</SortTh>
              <SortTh {...headerProps('is_active', 'number')} className="p-2 text-center">مفعّل</SortTh>
              <SortTh {...headerProps('notes')} className="p-2 text-start">ملاحظات</SortTh>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {editing === 'new' && (
              <EditRow draft={draft} setDraft={setDraft} branches={branches} saving={save.isPending}
                       onSave={() => save.mutate()} onCancel={cancel} error={error} />
            )}
            {sorted.map(r => editing === r.id ? (
              <EditRow key={r.id} draft={draft} setDraft={setDraft} branches={branches} saving={save.isPending}
                       onSave={() => save.mutate()} onCancel={cancel} error={error} />
            ) : (() => {
              const rp = kb.rowProps(r)
              return (
                <tr key={r.id} {...rp} className={`border-b border-line ${rp.className} ${r.is_active ? '' : 'opacity-50'}`}
                    onDoubleClick={() => startEdit(r)}>
                  <td className="p-2 font-medium">{r.name}</td>
                  <td className="p-2 font-mono" dir="ltr">{r.cidr}</td>
                  <td className="p-2">{KIND_LABEL[r.kind] || r.kind}</td>
                  <td className="p-2">{r.branch_label || '—'}</td>
                  <td className="p-2 text-center">
                    <input type="checkbox" className="accent-brand-600" checked={r.is_active}
                           onChange={() => toggle.mutate(r)} aria-label="مفعّل" />
                  </td>
                  <td className="p-2 text-muted">{r.notes}</td>
                  <td className="p-2 whitespace-nowrap text-end">
                    {armed === r.id ? (
                      <>
                        <span className="text-xs text-red-600 me-2">حذف «{r.name}»؟</span>
                        <button className="text-xs text-red-600 font-semibold px-2" disabled={remove.isPending}
                                onClick={() => remove.mutate(r.id)}>نعم، احذف</button>
                        <button className="text-xs text-muted px-2" onClick={() => setArmed(null)}>لا</button>
                      </>
                    ) : (
                      <>
                        <button className="text-xs text-brand-600 px-2" onClick={() => startEdit(r)}>✎ تعديل</button>
                        <button data-tour="admin-networks-delete" className="text-xs text-red-600 px-2" onClick={() => setArmed(r.id)}>حذف</button>
                      </>
                    )}
                  </td>
                </tr>
              )
            })())}
            {!rows.length && editing !== 'new' && !list.isLoading && (
              <tr><td colSpan={7} className="p-6 text-center text-muted">
                لا توجد شبكات بعد. شغّل أمر seed_trusted_networks لإضافة شبكات الفروع، أو أضف شبكة يدوياً.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-faint">⌨ ↑↓ تنقل · Enter تعديل · Esc إلغاء</div>
    </div>
  )
}
