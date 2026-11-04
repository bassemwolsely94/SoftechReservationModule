/**
 * PhoneAlertsPage.jsx  —  تنبيهات الموبايل (واتساب)
 *
 * Admin + supervisor console (the API enforces the same). Tabs:
 *   • السياسات   — per event: never / optional / always + remind / escalate timing + escalation people
 *   • المسؤولون  — who owns reservation sourcing / HQ transfer dispatch (and who is the escalation)
 *   • الفروع     — the staff-alerts WhatsApp account, each branch's shared mobile, test message
 *   • السجل      — every alert with its status, remark and delivery attempts
 *
 * A banner reads «وضع تجريبي — لا يتم الإرسال» while the send switch is off or no account is chosen:
 * every step still runs but nothing leaves the server.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { phoneAlertsApi, usersApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'
import useSortableRows from '../hooks/useSortableRows'
import SortTh from '../components/SortTh'
import { PHONE_ALERT_STATUS } from '../components/PhoneAlertStatusChip'
import PhoneAlertStatusChip from '../components/PhoneAlertStatusChip'

const TABS = [
  { key: 'policy',   label: '⚙️ السياسات' },
  { key: 'owners',   label: '👥 المسؤولون' },
  { key: 'branches', label: '🏪 الفروع' },
  { key: 'log',      label: '📜 السجل' },
]

const MODES = [
  { value: 'never',    label: 'لا' },
  { value: 'optional', label: 'اختياري' },
  { value: 'always',   label: 'دائماً' },
]

const OWNER_KINDS = [
  { value: 'reservation_sourcing', label: 'توفير الحجوزات' },
  { value: 'hq_transfer_dispatch', label: 'صرف تحويلات المخزن الرئيسي' },
  { value: 'callcenter_callbacks', label: 'معاودة الاتصال (الكول سنتر)' },
]

const INPUT = 'border border-gray-300 rounded-lg px-2.5 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand-400'
const BTN = 'px-3 py-1.5 rounded-lg text-sm font-semibold bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50'

/** First readable message of a DRF 400 body (string, list or {field: msg}). */
function errText(e, field) {
  const d = e?.response?.data
  if (!d) return 'تعذّر الاتصال بالسيرفر'
  const pick = v => (Array.isArray(v) ? v[0] : v)
  if (typeof d === 'string') return /<[a-z!][^>]*>/i.test(d) ? 'حدث خطأ في السيرفر — حاول مرة أخرى' : d
  if (field && d[field]) return pick(d[field])
  const first = Object.values(d)[0]
  return pick(first) || 'حدث خطأ'
}

/** Staff list for pickers: regular + alerts-only members. */
function useStaff() {
  return useQuery({
    queryKey: ['phone-alert-staff'],
    queryFn: async () => {
      // follow `next` so a long staff list is never silently cut off
      const get = async p => {
        let out = []
        for (let page = 1; page <= 50; page++) {
          const data = (await usersApi.list({ page_size: 200, page, is_active: true, ...p })).data
          if (Array.isArray(data)) return data
          out = out.concat(data?.results || [])
          if (!data?.next) break
        }
        return out
      }
      const [a, b] = await Promise.all([get({}), get({ alerts_only: 1 })])
      return [...a, ...b]
    },
    staleTime: 60_000,
  })
}

const staffLabel = s => `${s.full_name || s.username}${s.alerts_only ? ' (تنبيهات فقط)' : ''}`

// ── Policies ──────────────────────────────────────────────────────────────────

function PolicyRow({ policy, staff }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(policy)
  const [err, setErr] = useState({})
  const [saved, setSaved] = useState(false)
  const dirty = draft.mode !== policy.mode
    || ['remind_after_min', 'escalate_after_min', 'max_reminders'].some(k => Number(draft[k]) !== Number(policy[k]))
    || JSON.stringify([...(draft.escalate_to || [])].sort()) !== JSON.stringify([...(policy.escalate_to || [])].sort())

  const save = useMutation({
    mutationFn: () => phoneAlertsApi.savePolicies({
      event: policy.event, mode: draft.mode,
      remind_after_min: Number(draft.remind_after_min),
      escalate_after_min: Number(draft.escalate_after_min),
      max_reminders: Number(draft.max_reminders),
      escalate_to: draft.escalate_to || [],
    }),
    onSuccess: () => {
      setErr({}); setSaved(true); setTimeout(() => setSaved(false), 2500)
      qc.invalidateQueries({ queryKey: ['phone-alert-policies'] })
      qc.invalidateQueries({ queryKey: ['phone-alert-modes'] })
    },
    onError: e => setErr(e?.response?.data && typeof e.response.data === 'object' ? e.response.data : { _: errText(e) }),
  })

  const set = (k, v) => setDraft(d => ({ ...d, [k]: v }))
  const msg = k => err[k] && <p className="text-xs text-red-600 mt-0.5">{Array.isArray(err[k]) ? err[k][0] : err[k]}</p>
  const num = k => (
    <div>
      <input type="number" min={0} className={`${INPUT} w-20`} value={draft[k]}
        onChange={e => set(k, e.target.value)} />
      {msg(k)}
    </div>
  )

  return (
    <tr className="align-top">
      <td className="px-3 py-2.5 font-medium text-gray-800">{policy.label}</td>
      <td className="px-3 py-2.5">
        <select className={INPUT} value={draft.mode} onChange={e => set('mode', e.target.value)}>
          {MODES.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
        </select>
        {msg('mode')}
      </td>
      <td className="px-3 py-2.5">{num('remind_after_min')}</td>
      {/* an escalation never escalates again: its timing field would do nothing */}
      <td className="px-3 py-2.5">{policy.event === 'escalation'
        ? <span className="text-xs text-gray-400">لا يُصعَّد</span> : num('escalate_after_min')}</td>
      <td className="px-3 py-2.5">{num('max_reminders')}</td>
      <td className="px-3 py-2.5">
        <select multiple size={3} className={`${INPUT} w-48`} value={(draft.escalate_to || []).map(String)}
          onChange={e => set('escalate_to', [...e.target.selectedOptions].map(o => Number(o.value)))}>
          {staff.map(s => <option key={s.id} value={s.id}>{staffLabel(s)}</option>)}
        </select>
        {msg('escalate_to')}
      </td>
      <td className="px-3 py-2.5 whitespace-nowrap">
        {(dirty || saved) && (
          <button className={BTN} disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
            {saved ? '✓ تم' : save.isPending ? '...' : 'حفظ'}
          </button>
        )}
        {err._ && <p className="text-xs text-red-600 mt-0.5">{err._}</p>}
      </td>
    </tr>
  )
}

function PolicyTab() {
  const { data: policies = [], isLoading } = useQuery({
    queryKey: ['phone-alert-policies'],
    queryFn: () => phoneAlertsApi.policies().then(r => r.data),
  })
  const { data: staff = [] } = useStaff()
  if (isLoading) return <p className="text-gray-400 py-8 text-center">جارٍ التحميل…</p>
  return (
    <div data-tour="phone-alerts-policy" className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-x-auto">
      <p className="text-xs text-gray-500 px-4 pt-3">
        «لا» = لا يصل تنبيه · «اختياري» = يصل لو علّم الموظف «نبّه على الموبايل» · «دائماً» = يصل في كل مرة.
        التذكير والتصعيد بالدقائق من وقت الإرسال.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-right text-xs text-gray-500 font-semibold border-b">
            <th className="px-3 py-2">الحدث</th>
            <th className="px-3 py-2">التنبيه</th>
            <th className="px-3 py-2">تذكير بعد (د)</th>
            <th className="px-3 py-2">تصعيد بعد (د)</th>
            <th className="px-3 py-2">أقصى تذكيرات</th>
            <th className="px-3 py-2">يُصعَّد إلى</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {policies.map(p => <PolicyRow key={p.event} policy={p} staff={staff} />)}
        </tbody>
      </table>
    </div>
  )
}

// ── Owners ────────────────────────────────────────────────────────────────────

function OwnersTab() {
  const qc = useQueryClient()
  const { data: owners = [], isLoading } = useQuery({
    queryKey: ['phone-alert-owners'],
    queryFn: () => phoneAlertsApi.owners().then(r => r.data),
  })
  const { data: staff = [] } = useStaff()
  const [form, setForm] = useState({ kind: 'reservation_sourcing', staff: '', is_escalation: false })
  const [err, setErr] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: ['phone-alert-owners'] })

  const add = useMutation({
    mutationFn: () => phoneAlertsApi.addOwner({ ...form, staff: Number(form.staff), active: true }),
    onSuccess: () => { setErr(''); setForm(f => ({ ...f, staff: '' })); refresh() },
    onError: e => setErr(errText(e)),
  })
  const patch = useMutation({
    mutationFn: ({ id, data }) => phoneAlertsApi.updateOwner(id, data),
    onSuccess: () => { setErr(''); refresh() },
    onError: e => setErr(errText(e)),
  })
  const [confirmDel, setConfirmDel] = useState(null)
  const del = useMutation({
    mutationFn: id => phoneAlertsApi.deleteOwner(id),
    onSuccess: refresh,
    onError: e => setErr(errText(e)),
  })

  const { sorted, headerProps } = useSortableRows(owners, {
    defaultSort: { key: 'kind_label', dir: 'asc', type: 'text' }, persistKey: 'phone-alert-owners',
  })

  return (
    <div data-tour="phone-alerts-owners" className="space-y-4">
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 flex flex-wrap gap-3 items-end">
        <label className="text-xs text-gray-500">نوع الشغل
          <select className={`${INPUT} block mt-1`} value={form.kind} onChange={e => setForm(f => ({ ...f, kind: e.target.value }))}>
            {OWNER_KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </label>
        <label className="text-xs text-gray-500">الموظف
          <select className={`${INPUT} block mt-1 min-w-56`} value={form.staff} onChange={e => setForm(f => ({ ...f, staff: e.target.value }))}>
            <option value="">— اختر —</option>
            {staff.map(s => <option key={s.id} value={s.id}>{staffLabel(s)}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700 pb-1.5">
          <input type="checkbox" checked={form.is_escalation}
            onChange={e => setForm(f => ({ ...f, is_escalation: e.target.checked }))} />
          للتصعيد فقط
        </label>
        <button className={BTN} disabled={!form.staff || add.isPending} onClick={() => add.mutate()}>+ إضافة</button>
        {err && <p className="text-sm text-red-600 w-full">{err}</p>}
      </div>

      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-right text-xs text-gray-500 font-semibold border-b">
              <SortTh {...headerProps('kind_label', 'text')} className="px-4 py-2">نوع الشغل</SortTh>
              <SortTh {...headerProps('staff_name', 'text')} className="px-4 py-2">الموظف</SortTh>
              <SortTh {...headerProps('is_escalation', 'number')} className="px-4 py-2">الدور</SortTh>
              <SortTh {...headerProps('active', 'number')} className="px-4 py-2">مفعّل</SortTh>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? <tr><td colSpan={5} className="py-8 text-center text-gray-400">جارٍ التحميل…</td></tr>
              : !sorted.length ? <tr><td colSpan={5} className="py-8 text-center text-gray-400">لا يوجد مسؤولون بعد</td></tr>
              : sorted.map(o => (
                <tr key={o.id}>
                  <td className="px-4 py-2">{o.kind_label}</td>
                  <td className="px-4 py-2">{o.staff_name}</td>
                  <td className="px-4 py-2 text-gray-600">{o.is_escalation ? 'تصعيد' : 'مسؤول'}</td>
                  <td className="px-4 py-2">
                    <input type="checkbox" checked={o.active}
                      onChange={e => patch.mutate({ id: o.id, data: { active: e.target.checked } })} />
                  </td>
                  <td className="px-4 py-2 text-left">
                    {confirmDel === o.id ? (
                      <span className="text-xs space-x-2 space-x-reverse">
                        <button className="text-red-700 font-semibold hover:underline"
                          onClick={() => { del.mutate(o.id); setConfirmDel(null) }}>تأكيد الحذف</button>
                        <button className="text-gray-500 hover:underline" onClick={() => setConfirmDel(null)}>إلغاء</button>
                      </span>
                    ) : (
                      <button className="text-xs text-red-600 hover:underline" onClick={() => setConfirmDel(o.id)}>حذف</button>
                    )}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Branches + channel ────────────────────────────────────────────────────────

function ChannelCard() {
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['phone-alert-channel'],
    queryFn: () => phoneAlertsApi.channel().then(r => r.data),
  })
  const [pick, setPick] = useState(null)
  const [err, setErr] = useState('')
  const current = pick ?? (data?.channel_account_id ?? '')
  const canChange = !!data?.can_change
  // the server decides which numbers may carry staff alerts (never the customer number)
  const choices = (data?.accounts || []).filter(a => a.eligible)
  const hidden = (data?.accounts || []).length - choices.length
  const save = useMutation({
    mutationFn: () => phoneAlertsApi.saveChannel(current === '' ? null : Number(current)),
    onSuccess: () => {
      setErr(''); setPick(null)
      qc.invalidateQueries({ queryKey: ['phone-alert-channel'] })
      qc.invalidateQueries({ queryKey: ['phone-alert-switches'] })
    },
    onError: e => setErr(errText(e, 'channel_account_id')),
  })
  return (
    <div data-tour="phone-alerts-channel" className="bg-white rounded-2xl border border-gray-100 shadow-sm p-4 flex flex-wrap items-end gap-3">
      <label className="text-xs text-gray-500">حساب واتساب الذي تخرج منه التنبيهات
        <select className={`${INPUT} block mt-1 min-w-64`} value={current} disabled={!canChange}
          onChange={e => setPick(e.target.value)}>
          <option value="">— لم يُحدَّد (وضع تجريبي) —</option>
          {choices.map(a => (
            <option key={a.id} value={a.id}>{a.name} · {a.phone_or_handle}{a.is_active ? '' : ' (موقوف)'}</option>
          ))}
        </select>
      </label>
      {canChange && (
        <button className={BTN} disabled={pick === null || save.isPending} onClick={() => save.mutate()}>حفظ</button>
      )}
      <p className="text-xs text-amber-700 w-full">
        رقم مخصص للموظفين فقط — رسائله لا تدخل صندوق العملاء، فلا تختر رقم العملاء
        {hidden > 0 ? ` (أُخفي ${hidden} رقم عليه محادثات عملاء أو هو رقم العملاء الأساسي).` : '.'}
        {!canChange && ' التغيير للمدير فقط.'}
      </p>
      {err && <p className="text-sm text-red-600 w-full">{err}</p>}
    </div>
  )
}

function BranchRow({ row }) {
  const qc = useQueryClient()
  const [val, setVal] = useState(row.alert_mobile)
  const [err, setErr] = useState('')
  const [note, setNote] = useState('')
  const dirty = val !== row.alert_mobile

  const save = useMutation({
    mutationFn: () => phoneAlertsApi.saveBranchMobile({ branch_id: row.branch_id, alert_mobile: val }),
    onSuccess: r => {
      setErr(''); setVal(r.data.alert_mobile)
      qc.invalidateQueries({ queryKey: ['phone-alert-branch-mobiles'] })
    },
    onError: e => setErr(errText(e, 'alert_mobile')),
  })
  const test = useMutation({
    mutationFn: () => phoneAlertsApi.testBranchMobile(row.branch_id),
    onSuccess: r => {
      setErr('')
      setNote(r.data.dry_run ? 'سُجّل في السجل (وضع تجريبي — لم يُرسل)' : `أُرسل (${r.data.status})`)
      qc.invalidateQueries({ queryKey: ['phone-alert-log'] })
    },
    onError: e => { setNote(''); setErr(errText(e)) },
  })

  return (
    <tr className="align-top">
      <td className="px-4 py-2.5 font-medium text-gray-800">{row.branch_name}</td>
      <td className="px-4 py-2.5">
        <input dir="ltr" inputMode="tel" className={`${INPUT} w-44`} placeholder="01012345678" value={val}
          onChange={e => { setVal(e.target.value); setNote('') }} />
        {err && <p className="text-xs text-red-600 mt-0.5">{err}</p>}
        {note && <p className="text-xs text-emerald-700 mt-0.5">{note}</p>}
      </td>
      <td className="px-4 py-2.5 whitespace-nowrap space-x-2 space-x-reverse">
        {dirty && <button className={BTN} disabled={save.isPending} onClick={() => save.mutate()}>حفظ</button>}
        <button className="px-3 py-1.5 rounded-lg text-sm border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          disabled={!row.alert_mobile || dirty || test.isPending} onClick={() => test.mutate()}>
          إرسال تجريبي
        </button>
      </td>
    </tr>
  )
}

function BranchesTab() {
  const { data: rows = [], isLoading } = useQuery({
    queryKey: ['phone-alert-branch-mobiles'],
    queryFn: () => phoneAlertsApi.branchMobiles().then(r => r.data),
  })
  return (
    <div className="space-y-4">
      <ChannelCard />
      <div data-tour="phone-alerts-branches" className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-x-auto">
        <p className="text-xs text-gray-500 px-4 pt-3">موبايل الفرع المشترك يستقبل تنبيهات تغيّر حالة تحويلات وحجوزات الفرع.</p>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-right text-xs text-gray-500 font-semibold border-b">
              <th className="px-4 py-2">الفرع</th><th className="px-4 py-2">موبايل التنبيهات</th><th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? <tr><td colSpan={3} className="py-8 text-center text-gray-400">جارٍ التحميل…</td></tr>
              : rows.map(r => <BranchRow key={`${r.branch_id}:${r.alert_mobile}`} row={r} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Log ───────────────────────────────────────────────────────────────────────

// events that have no policy row but still appear in the log
const EXTRA_EVENTS = [['escalation', 'تصعيد تنبيه لم يُستلم'], ['morning_brief', 'ملخص الصباح'],
  ['expiry_worklist', 'قائمة الصلاحيات'], ['test', 'تنبيه تجريبي']]

const cursorOf = url => { try { return new URL(url).searchParams.get('cursor') } catch { return null } }
const fmt = iso => (iso ? new Date(iso).toLocaleString('ar-EG-u-nu-latn', { dateStyle: 'short', timeStyle: 'short' }) : '—')

function LogDetail({ id }) {
  const { data } = useQuery({
    queryKey: ['phone-alert-log-detail', id],
    queryFn: () => phoneAlertsApi.logDetail(id).then(r => r.data),
  })
  if (!data) return <p className="text-xs text-gray-400 py-2">جارٍ التحميل…</p>
  return (
    <div className="text-xs text-gray-600 space-y-1 py-2">
      {data.remark && <p><b>ملاحظة المستلم:</b> {data.remark}</p>}
      {data.ack_at && <p><b>وقت الاستلام:</b> {fmt(data.ack_at)}</p>}
      {data.escalated_at && <p><b>وقت التصعيد:</b> {fmt(data.escalated_at)}</p>}
      <p className="font-semibold pt-1">محاولات الإرسال</p>
      {(data.attempts || []).length === 0 ? <p className="text-gray-400">لا توجد محاولات</p> : (
        <ul className="space-y-0.5">
          {data.attempts.map(a => (
            <li key={a.id}>{fmt(a.created_at)} · {a.channel} · {a.result}{a.error ? ` — ${a.error}` : ''}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function LogTab({ events }) {
  const [f, setF] = useState({ status: '', event: '', date: '' })
  const [cursor, setCursor] = useState(null)
  const [open, setOpen] = useState(null)
  const params = { status: f.status || undefined, event: f.event || undefined, date: f.date || undefined, cursor: cursor || undefined }
  const { data, isLoading, error } = useQuery({
    queryKey: ['phone-alert-log', params],
    queryFn: () => phoneAlertsApi.log(params).then(r => r.data),
    keepPreviousData: true,
  })
  const rows = data?.results || []
  const { sorted, headerProps } = useSortableRows(rows, { defaultSort: null, persistKey: 'phone-alert-log' })
  const set = (k, v) => { setF(x => ({ ...x, [k]: v })); setCursor(null) }

  return (
    <div data-tour="phone-alerts-log" className="space-y-3">
      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-3 flex flex-wrap gap-3 items-center">
        <select className={INPUT} value={f.status} onChange={e => set('status', e.target.value)}>
          <option value="">كل الحالات</option>
          {Object.entries(PHONE_ALERT_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <select className={INPUT} value={f.event} onChange={e => set('event', e.target.value)}>
          <option value="">كل الأحداث</option>
          {events.filter(p => !EXTRA_EVENTS.some(([k]) => k === p.event))
            .map(p => <option key={p.event} value={p.event}>{p.label}</option>)}
          {EXTRA_EVENTS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <input type="date" className={INPUT} value={f.date} onChange={e => set('date', e.target.value)} />
        {error && <span className="text-sm text-red-600">{errText(error, 'date')}</span>}
      </div>

      <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-right text-xs text-gray-500 font-semibold border-b">
              <SortTh {...headerProps('created_at', 'date')} className="px-3 py-2">الوقت</SortTh>
              <SortTh {...headerProps('event_label', 'text')} className="px-3 py-2">الحدث</SortTh>
              <SortTh {...headerProps('source_text', 'text')} className="px-3 py-2">السجل المرتبط</SortTh>
              <SortTh {...headerProps('recipient_name', 'text')} className="px-3 py-2">المستلم</SortTh>
              <SortTh {...headerProps('phone', 'text')} className="px-3 py-2">الموبايل</SortTh>
              <SortTh {...headerProps('status', 'text')} className="px-3 py-2">الحالة</SortTh>
              <SortTh {...headerProps('reminders_sent', 'number')} className="px-3 py-2">تذكيرات</SortTh>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? <tr><td colSpan={7} className="py-8 text-center text-gray-400">جارٍ التحميل…</td></tr>
              : !sorted.length ? <tr><td colSpan={7} className="py-8 text-center text-gray-400">لا توجد تنبيهات</td></tr>
              : sorted.flatMap(a => [
                <tr key={a.id} className="hover:bg-gray-50 cursor-pointer" onClick={() => setOpen(open === a.id ? null : a.id)}>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-600">{fmt(a.created_at)}</td>
                  <td className="px-3 py-2">{a.event_label}{a.kind === 'brief' ? ' (ملخص)' : ''}</td>
                  <td className="px-3 py-2 text-gray-600">{a.source_text || '—'}</td>
                  <td className="px-3 py-2">{a.recipient_name || '—'}</td>
                  <td className="px-3 py-2 font-mono text-xs" dir="ltr">{a.phone}</td>
                  <td className="px-3 py-2"><PhoneAlertStatusChip status={a.status} remark={a.remark} /></td>
                  <td className="px-3 py-2 text-center">{a.reminders_sent}</td>
                </tr>,
                open === a.id && (
                  <tr key={`${a.id}-d`} className="bg-gray-50"><td colSpan={7} className="px-4"><LogDetail id={a.id} /></td></tr>
                ),
              ])}
          </tbody>
        </table>
      </div>

      <div className="flex gap-3 justify-center">
        <button className="px-3 py-1.5 rounded-lg text-sm border border-gray-300 disabled:opacity-40"
          disabled={!cursor} onClick={() => setCursor(null)}>الأحدث</button>
        <button className="px-3 py-1.5 rounded-lg text-sm border border-gray-300 disabled:opacity-40"
          disabled={!data?.next} onClick={() => setCursor(cursorOf(data.next))}>الأقدم ←</button>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PhoneAlertsPage() {
  const [tab, setTab] = useState('policy')
  useHelpTab(tab)

  const { data: sw } = useQuery({
    queryKey: ['phone-alert-switches'],
    queryFn: () => phoneAlertsApi.switches().then(r => r.data),
    staleTime: 30_000,
  })
  const { data: policies = [] } = useQuery({
    queryKey: ['phone-alert-policies'],
    queryFn: () => phoneAlertsApi.policies().then(r => r.data),
  })
  const dryRun = sw && (!sw.send_enabled || !sw.account_set)

  return (
    <div className="p-6 max-w-7xl mx-auto" dir="rtl">
      <div className="mb-4">
        <h1 className="text-2xl font-bold font-cairo text-gray-900">📲 تنبيهات الموبايل</h1>
        <p className="text-sm text-gray-500 mt-0.5">تنبيهات واتساب للأحداث العاجلة: استلام بضغطة، تذكير، وتصعيد.</p>
      </div>

      {dryRun && (
        <div data-tour="phone-alerts-banner" className="mb-4 bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-xl px-4 py-3">
          🧪 وضع تجريبي — لا يتم الإرسال
          <span className="text-xs text-amber-700 me-2">
            {!sw.account_set ? ' (لم يُختَر حساب واتساب بعد) ' : ' (مفتاح الإرسال مغلق على السيرفر) '}
            — كل الخطوات تعمل وتُسجَّل في السجل.
          </span>
        </div>
      )}

      <div className="flex border-b border-gray-200 gap-5 mb-4" data-tour="phone-alerts-tabs">
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`pb-2.5 text-sm font-semibold border-b-2 transition-colors ${
              tab === t.key ? 'border-brand-600 text-brand-700' : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'policy' && <PolicyTab />}
      {tab === 'owners' && <OwnersTab />}
      {tab === 'branches' && <BranchesTab />}
      {tab === 'log' && <LogTab events={policies} />}
    </div>
  )
}
