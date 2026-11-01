/**
 * DevicesPage.jsx — الأجهزة (admin only, security N2)
 *
 * The device registry: every browser/PC a user signed in from. New devices arrive «بانتظار الاعتماد»;
 * the admin approves (one by one or a whole branch at once), blocks (with a reason, typed inline —
 * no modal) or retires them. Blocked / retired devices lose their sessions server-side.
 * Name, kind and branch are edited in the row itself.
 *
 * Keys (useGridKeyboard): ↑↓ move · Space select · Enter approve the focused row · M edit the device · Ctrl+A select all (pending).
 * The grid stays mounted while the list refetches (the refetch state shows in the header).
 */
import { useCallback, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { accessApi, branchesApi } from '../api/client'
import useGridKeyboard from '../hooks/useGridKeyboard'
import useHelpTab from '../help/useHelpTab'

const KINDS = [
  { value: 'branch_pc', label: 'جهاز فرع' },
  { value: 'personal_laptop', label: 'لابتوب شخصي' },
  { value: 'phone', label: 'موبايل' },
  { value: 'rider_phone', label: 'موبايل طيار' },
  { value: 'kiosk', label: 'كشك' },
]
const TABS = [
  { key: 'pending', label: 'بانتظار الاعتماد', match: s => s === 'pending' },
  { key: 'approved', label: 'المعتمدة', match: s => s === 'approved' },
  { key: 'closed', label: 'المحظورة والمتقاعدة', match: s => s === 'blocked' || s === 'retired' },
]
const STATUS_TONE = {
  pending: 'bg-amber-500/10 text-amber-700 dark:text-amber-300',
  approved: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  blocked: 'bg-red-500/10 text-red-700 dark:text-red-300',
  retired: 'bg-surface-2 text-muted',
}
const HINT = '⌨ ↑↓ تنقل · مسافة تحديد · Enter اعتماد الصف · M تعديل الجهاز · Ctrl+A تحديد الكل'

function errText(e) {
  const d = e?.response?.data
  if (!d) return 'تعذّر تنفيذ الطلب'
  if (typeof d === 'string') return d
  if (d.error) return d.error
  return Object.values(d).flat().join(' · ') || 'تعذّر تنفيذ الطلب'
}
const fmt = v => (v ? new Date(v).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—')

export default function DevicesPage() {
  const qc = useQueryClient()
  const [tab, setTab] = useState('pending')
  useHelpTab(tab)
  const [branch, setBranch] = useState('')
  const [kind, setKind] = useState('')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const [retireArm, setRetireArm] = useState(null)   // device id waiting for the second click on تقاعد
  const [notes, setNotes] = useState({})            // device id -> block reason being typed
  const [errors, setErrors] = useState({})          // device id -> message
  const [banner, setBanner] = useState('')

  const params = useMemo(() => {
    const p = {}
    if (branch) p.branch = branch
    if (kind) p.kind = kind
    if (q.trim()) p.q = q.trim()
    return p
  }, [branch, kind, q])

  const list = useQuery({
    queryKey: ['access-devices', params],
    queryFn: () => accessApi.devices(params).then(r => r.data),
    placeholderData: prev => prev,              // keep the rows on screen while refetching
  })
  const bq = useQuery({ queryKey: ['branches-all'], queryFn: () => branchesApi.listAll().then(r => r.data), staleTime: 10 * 60 * 1000 })
  const all = useMemo(() => (Array.isArray(list.data) ? list.data : (list.data?.results || [])), [list.data])
  const branches = useMemo(() => (Array.isArray(bq.data) ? bq.data : (bq.data?.results || [])), [bq.data])

  const counts = useMemo(() => Object.fromEntries(TABS.map(t => [t.key, all.filter(d => t.match(d.status)).length])), [all])
  const cur = TABS.find(t => t.key === tab)
  const rows = useMemo(() => all.filter(d => cur.match(d.status)), [all, cur])

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['access-devices'] })
    qc.invalidateQueries({ queryKey: ['access-whoami'] })
  }, [qc])
  const setErr = (id, msg) => setErrors(e => ({ ...e, [id]: msg }))

  const act = useMutation({
    mutationFn: ({ id, kind: k, note }) => (
      k === 'approve' ? accessApi.approveDevice(id)
        : k === 'block' ? accessApi.blockDevice(id, note)
          : accessApi.retireDevice(id)
    ),
    onSuccess: (_r, v) => {
      setErr(v.id, '')
      setSelected(s => { const n = new Set(s); n.delete(v.id); return n })
      setNotes(n => ({ ...n, [v.id]: '' }))
      refresh()
    },
    onError: (e, v) => setErr(v.id, errText(e)),
  })
  const bulk = useMutation({
    mutationFn: ids => accessApi.bulkApproveDevices(ids).then(r => r.data),
    onSuccess: r => {
      setBanner(`تم اعتماد ${r.approved} جهاز${r.skipped ? ` · تخطّي ${r.skipped}` : ''}`)
      setSelected(new Set())
      refresh()
    },
    onError: e => setBanner(errText(e)),
  })
  const edit = useMutation({
    mutationFn: ({ id, data }) => accessApi.updateDevice(id, data),
    onSuccess: (_r, v) => { setErr(v.id, ''); refresh() },
    onError: (e, v) => { setErr(v.id, errText(e)); refresh() },
  })

  const toggle = useCallback(r => setSelected(s => {
    if (r.status !== 'pending') return s
    const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n
  }), [])
  // M: jump into the focused row's inline editor (its name field)
  const editRow = useCallback(r => {
    document.querySelector(`[data-device-name="${r.id}"]`)?.focus()
  }, [])
  const armRetire = useCallback(id => {
    setRetireArm(id)
    setTimeout(() => setRetireArm(a => (a === id ? null : a)), 4000)
  }, [])
  const approveRow = useCallback(r => {
    if (r.status === 'pending' || r.status === 'blocked') act.mutate({ id: r.id, kind: 'approve' })
  }, [act])
  const selectAll = useCallback(() => setSelected(s => {
    const ids = rows.filter(r => r.status === 'pending').map(r => r.id)
    return ids.every(i => s.has(i)) ? new Set() : new Set(ids)
  }), [rows])

  const kb = useGridKeyboard({
    rows, getKey: r => r.id, onToggle: toggle, onConfirm: approveRow, onOpen: editRow, onSelectAll: selectAll,
  })

  const pickedPending = rows.filter(r => selected.has(r.id) && r.status === 'pending').map(r => r.id)

  function switchTab(k) { setTab(k); setSelected(new Set()); setBanner('') }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">💻 الأجهزة</h1>
          <p className="text-sm text-muted">كل جهاز دخل منه موظف. اعتمد أجهزة الفروع، واحظر أو تقاعد أي جهاز مش مطلوب — الحظر يقطع جلساته فوراً.</p>
        </div>
        <div className="flex items-center gap-2">
          {list.isFetching && <span className="text-xs text-muted">جارٍ التحديث…</span>}
          <button className="btn-secondary text-sm" onClick={refresh} title="تحديث">⟳ تحديث</button>
        </div>
      </div>

      <div data-tour="admin-devices-tabs" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map(t => (
          <button key={t.key} onClick={() => switchTab(t.key)}
                  className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === t.key ? 'border-brand-600 text-brand-600 font-semibold' : 'border-transparent text-muted'}`}>
            {t.label} <span className="text-xs">({counts[t.key]})</span>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input className="input" placeholder="بحث: اسم، مستخدم، IP…" value={q} onChange={e => setQ(e.target.value)} />
        <select className="input" value={branch} onChange={e => setBranch(e.target.value)}>
          <option value="">كل الفروع</option>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
        </select>
        <select className="input" value={kind} onChange={e => setKind(e.target.value)}>
          <option value="">كل الأنواع</option>
          {KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
        </select>
        {tab === 'pending' && (
          <button data-tour="admin-devices-approve" className="btn-primary text-sm"
                  disabled={!pickedPending.length || bulk.isPending}
                  onClick={() => bulk.mutate(pickedPending)}>
            ✓ اعتماد المحدد ({pickedPending.length})
          </button>
        )}
        {banner && <span className="text-sm text-muted">{banner}</span>}
      </div>

      <div data-tour="admin-devices-table" className="card p-0 overflow-x-auto" {...kb.containerProps}>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <th className="p-2 w-8" />
              <th className="p-2 text-start">الجهاز</th>
              <th className="p-2 text-start">النوع</th>
              <th className="p-2 text-start">الفرع</th>
              <th className="p-2 text-start">المستخدمون</th>
              <th className="p-2 text-start">الشبكة / IP</th>
              <th className="p-2 text-start">أول ظهور</th>
              <th className="p-2 text-start">آخر ظهور</th>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const rp = kb.rowProps(r)
              const editable = r.status !== 'retired'
              const canBlock = r.status === 'pending' || r.status === 'approved'
              return (
                <RowFragment key={r.id}>
                  <tr {...rp} className={`border-b border-line align-top ${rp.className} ${r.status === 'retired' ? 'opacity-60' : ''}`}>
                    <td className="p-2">
                      {r.status === 'pending' && (
                        <input type="checkbox" className="accent-brand-600"
                               checked={selected.has(r.id)} onChange={() => toggle(r)} aria-label="تحديد" />
                      )}
                    </td>
                    <td className="p-2">
                      <div className="flex items-center gap-1">
                        <input className="input w-44" key={`n${r.id}-${r.name}`} data-device-name={r.id} defaultValue={r.name} disabled={!editable}
                               aria-label="اسم الجهاز"
                               onBlur={e => { const v = e.target.value.trim(); if (v && v !== r.name) edit.mutate({ id: r.id, data: { name: v } }) }} />
                      </div>
                      <span className={`inline-block mt-1 text-xs rounded px-1.5 py-0.5 ${STATUS_TONE[r.status]}`}>{r.status_label}</span>
                      {r.status_note && <span className="text-xs text-muted ms-2">{r.status_note}</span>}
                    </td>
                    <td className="p-2">
                      <select className="input" value={r.kind} disabled={!editable}
                              onChange={e => edit.mutate({ id: r.id, data: { kind: e.target.value } })}>
                        {KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
                      </select>
                    </td>
                    <td className="p-2">
                      <select className="input" value={r.branch ?? ''} disabled={!editable}
                              onChange={e => edit.mutate({ id: r.id, data: { branch: e.target.value === '' ? null : Number(e.target.value) } })}>
                        <option value="">— بدون فرع —</option>
                        {branches.map(b => <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>)}
                      </select>
                    </td>
                    <td className="p-2">
                      {r.users?.length ? r.users.map(u => (
                        <div key={u.id} className="whitespace-nowrap">
                          {u.name}{u.mfa_remembered && <span title="التحقق بخطوتين محفوظ"> 🔐</span>}
                        </div>
                      )) : <span className="text-muted">—</span>}
                    </td>
                    <td className="p-2">
                      <div>{r.last_network_label || '—'}</div>
                      <div className="font-mono text-xs text-muted" dir="ltr">{r.last_ip || ''}</div>
                    </td>
                    <td className="p-2 whitespace-nowrap">{fmt(r.first_seen)}</td>
                    <td className="p-2 whitespace-nowrap">{fmt(r.last_seen)}</td>
                    <td className="p-2 text-end">
                      <div className="flex items-center gap-1 justify-end flex-wrap">
                        {(r.status === 'pending' || r.status === 'blocked') && (
                          <button className="btn-primary text-xs px-3 py-1" disabled={act.isPending}
                                  onClick={() => act.mutate({ id: r.id, kind: 'approve' })}>اعتماد</button>
                        )}
                        {canBlock && (
                          <>
                            <input className="input w-36 text-xs" placeholder="سبب الحظر" aria-label="سبب الحظر" value={notes[r.id] || ''}
                                   onChange={e => setNotes(n => ({ ...n, [r.id]: e.target.value }))}
                                   onKeyDown={e => { if (e.key === 'Enter') act.mutate({ id: r.id, kind: 'block', note: notes[r.id] || '' }) }} />
                            <button data-tour="admin-devices-block" className="text-xs text-red-600 font-semibold px-2" disabled={act.isPending}
                                    onClick={() => act.mutate({ id: r.id, kind: 'block', note: notes[r.id] || '' })}>حظر</button>
                          </>
                        )}
                        {editable && (
                          retireArm === r.id ? (
                            <button className="text-xs text-red-600 font-semibold px-2" disabled={act.isPending}
                                    onClick={() => { setRetireArm(null); act.mutate({ id: r.id, kind: 'retire' }) }}>تأكيد التقاعد؟</button>
                          ) : (
                            <button className="text-xs text-muted px-2" disabled={act.isPending}
                                    onClick={() => armRetire(r.id)}>تقاعد</button>
                          )
                        )}
                      </div>
                    </td>
                  </tr>
                  {errors[r.id] && (
                    <tr><td colSpan={9} className="px-3 pb-2 text-xs text-red-600">{errors[r.id]}</td></tr>
                  )}
                </RowFragment>
              )
            })}
            {!rows.length && !list.isLoading && (
              <tr><td colSpan={9} className="p-6 text-center text-muted">
                {tab === 'pending' ? 'لا توجد أجهزة بانتظار الاعتماد.' : 'لا توجد أجهزة هنا.'}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-faint">{HINT}</div>
    </div>
  )
}

// A keyed fragment around a row and its optional error row.
function RowFragment({ children }) { return <>{children}</> }
