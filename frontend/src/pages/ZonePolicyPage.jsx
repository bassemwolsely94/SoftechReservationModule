/**
 * ZonePolicyPage.jsx — سياسة الشبكات (admin only, security N3)
 *
 * The role × zone grid: what each role may do from Z1 (inside, approved device), Z2 (inside,
 * unapproved), Z3 (outside, approved) and Z4 (outside, unapproved). The policy only narrows the
 * role's own module matrix. Each cell shows its access level (a select that saves on change);
 * «⚙» opens the cell's details under the table (screens, view-only, export, 2FA, session hours,
 * SOFTECH read/write) — no modal; every field saves as you change it and is audited.
 * Whether the policy is only logged or really enforced is the owner's server setting, not here.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { accessApi } from '../api/client'

const ZONES = [
  { key: 'Z1', label: 'داخل الشبكة — جهاز معتمد' },
  { key: 'Z2', label: 'داخل الشبكة — جهاز غير معتمد' },
  { key: 'Z3', label: 'خارج الشبكة — جهاز معتمد' },
  { key: 'Z4', label: 'خارج الشبكة — جهاز غير معتمد' },
]
const TONE = {
  full: 'text-emerald-700 dark:text-emerald-300',
  listed: 'text-sky-700 dark:text-sky-300',
  rider: 'text-sky-700 dark:text-sky-300',
  read_only: 'text-amber-700 dark:text-amber-300',
  none: 'text-red-700 dark:text-red-300',
}

function errText(e) {
  const d = e?.response?.data
  if (!d) return 'تعذّر الحفظ'
  if (typeof d === 'string') return d
  return d.error || d.detail || Object.values(d).flat().join(' · ') || 'تعذّر الحفظ'
}

function Check({ label, checked, onChange }) {
  return (
    <label className="flex items-center gap-2 text-sm cursor-pointer">
      <input type="checkbox" className="accent-brand-600" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  )
}

function Details({ row, choices, onPatch, saving, error }) {
  const mods = new Set(row.modules || [])
  const toggleMod = v => {
    const n = new Set(mods)
    if (n.has(v)) n.delete(v); else n.add(v)
    onPatch({ modules: [...n] })
  }
  const listed = row.access === 'listed'
  return (
    <div data-tour="admin-zone-details" className="card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="font-bold">{row.role_label} — {row.zone_label}</h2>
        <span className="text-xs text-muted">
          {saving ? 'جارٍ الحفظ…' : row.updated_by_name ? `آخر تعديل: ${row.updated_by_name}` : ''}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2">
        <Check label="عرض فقط (مع «شاشات محددة»)" checked={!!row.view_only} onChange={v => onPatch({ view_only: v })} />
        <Check label="التصدير" checked={!!row.export} onChange={v => onPatch({ export: v })} />
        <Check label="إلزام التحقق بخطوتين" checked={!!row.require_mfa} onChange={v => onPatch({ require_mfa: v })} />
        <Check label="قراءة SOFTECH" checked={!!row.softech_read} onChange={v => onPatch({ softech_read: v })} />
        <Check label="كتابة SOFTECH" checked={!!row.softech_write} onChange={v => onPatch({ softech_write: v })} />
        <label className="flex items-center gap-2 text-sm">
          <span>أقصى مدة جلسة (ساعات)</span>
          <input key={`${row.id}-${row.max_session_hours}`} type="number" min={1} max={72} className="input w-20"
                 defaultValue={row.max_session_hours ?? ''} placeholder="—"
                 onBlur={e => {
                   const v = e.target.value === '' ? null : Number(e.target.value)
                   if (v !== row.max_session_hours) onPatch({ max_session_hours: v })
                 }} />
        </label>
      </div>
      <div>
        <div className="text-sm font-semibold mb-1">
          الشاشات {listed ? '' : <span className="text-xs text-muted font-normal">(تُستخدم عند «شاشات محددة» فقط)</span>}
        </div>
        <div className={`flex flex-wrap gap-1.5 ${listed ? '' : 'opacity-50'}`}>
          {(choices?.modules || []).map(m => {
            const on = mods.has(m.value)
            return (
              <button type="button" key={m.value} onClick={() => toggleMod(m.value)}
                      className={`text-xs px-2 py-1 rounded border ${on ? 'bg-brand-600 text-white border-brand-600' : 'bg-surface text-muted border-line'}`}>
                {m.label}
              </button>
            )
          })}
        </div>
      </div>
      {error && <div className="text-sm text-red-600">{error}</div>}
    </div>
  )
}

export default function ZonePolicyPage() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['access-zone-policies'], queryFn: () => accessApi.zonePolicies().then(r => r.data) })
  const ch = useQuery({ queryKey: ['access-zone-policy-choices'], queryFn: () => accessApi.zonePolicyChoices().then(r => r.data), staleTime: 10 * 60 * 1000 })
  const rows = useMemo(() => (Array.isArray(list.data) ? list.data : (list.data?.results || [])), [list.data])
  const [open, setOpen] = useState(null)       // row id whose details are shown
  const [error, setError] = useState('')

  const byRole = useMemo(() => {
    const m = new Map()
    rows.forEach(r => {
      if (!m.has(r.role)) m.set(r.role, { label: r.role_label, cells: {} })
      m.get(r.role).cells[r.zone] = r
    })
    return [...m.entries()]
  }, [rows])

  const save = useMutation({
    mutationFn: ({ id, data }) => accessApi.updateZonePolicy(id, data),
    onSuccess: () => { setError(''); qc.invalidateQueries({ queryKey: ['access-zone-policies'] }) },
    onError: e => { setError(errText(e)); qc.invalidateQueries({ queryKey: ['access-zone-policies'] }) },
  })
  const patch = (id, data) => save.mutate({ id, data })
  const accessLabel = Object.fromEntries((ch.data?.access || []).map(a => [a.value, a.label]))
  const current = rows.find(r => r.id === open)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold">🛰️ سياسة الشبكات</h1>
          <p className="text-sm text-muted">إيه اللي يقدر كل دور يعمله حسب مكان الاتصال وحالة الجهاز. السياسة بتضيّق صلاحيات الدور بس، ما بتزوّدها. التعديل بيتحفظ فوراً ومتسجل في المراجعة.</p>
        </div>
        {list.isFetching && <span className="text-xs text-muted">جارٍ التحديث…</span>}
      </div>

      {error && !current && <div className="text-sm text-red-600">{error}</div>}

      <div data-tour="admin-zone-grid" className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <th className="p-2 text-start">الدور</th>
              {ZONES.map(z => <th key={z.key} className="p-2 text-start" title={z.label}>{z.key} <span className="text-xs font-normal">{z.label}</span></th>)}
            </tr>
          </thead>
          <tbody>
            {byRole.map(([role, g]) => (
              <tr key={role} className="border-b border-line last:border-0">
                <td className="p-2 font-semibold whitespace-nowrap">{g.label}</td>
                {ZONES.map(z => {
                  const c = g.cells[z.key]
                  if (!c) return <td key={z.key} className="p-2 text-muted">—</td>
                  return (
                    <td key={z.key} className={`p-2 ${open === c.id ? 'bg-surface-2' : ''}`}>
                      <div className="flex items-center gap-1">
                        <select className={`input text-xs py-1 ${TONE[c.access] || ''}`} value={c.access}
                                aria-label={`${g.label} ${z.key}`}
                                onChange={e => patch(c.id, { access: e.target.value })}>
                          {(ch.data?.access || []).map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                        </select>
                        <button className="text-xs px-1 text-muted hover:text-brand-600" title="تفاصيل"
                                onClick={() => setOpen(o => (o === c.id ? null : c.id))}>⚙</button>
                      </div>
                      <div className="text-[11px] text-muted mt-0.5">
                        {[c.export && 'تصدير', c.view_only && 'عرض فقط', c.require_mfa && '2FA',
                          c.max_session_hours && `${c.max_session_hours} س`].filter(Boolean).join(' · ') || accessLabel[c.access] || ''}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {current && (
        <Details row={current} choices={ch.data} onPatch={d => patch(current.id, d)}
                 saving={save.isPending} error={error} />
      )}
    </div>
  )
}
