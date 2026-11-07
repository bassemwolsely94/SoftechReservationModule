/**
 * DevicesTab — the fingerprint machines and the collection programs (agents) that read them:
 * clock drift, last contact, last run, and «collect now» with a progress bar (machines finished
 * out of machines assigned). IP/port and agent controls are for the admin only.
 *
 * An agent's secret is shown ONCE, right after it is issued, held in this component's memory only
 * (never in browser storage) and gone when dismissed or when the page is left.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import ProgressBar from '../../components/ProgressBar'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import { BTN, Empty, Notice, TH, errText, stamp } from './shared'

const KEYS = ['name', 'location_label', 'branch_name', 'last_contact_at', 'last_drift_seconds']
const DRIFT_WARN = 300
const COLLECT_WAIT_MS = 10 * 60 * 1000
const SLACK_MS = 60 * 1000          // this PC's clock vs the server's

const getValue = (r, key) => r[key]

function Drift({ s }) {
  if (s == null) return <span className="text-gray-400">—</span>
  const mins = Math.round(Math.abs(s) / 60)
  return Math.abs(s) > DRIFT_WARN
    ? <span className="text-amber-700 font-bold">{mins} دقيقة</span>
    : <span className="text-gray-600">{Math.abs(s) < 60 ? 'مضبوطة' : `${mins} دقيقة`}</span>
}

function RunCell({ run, admin }) {
  if (!run) return <span className="text-gray-400">—</span>
  return (
    <div className="text-xs">
      <span className={run.status === 'failed' ? 'text-red-600 font-bold' : 'text-gray-700'}>
        {run.status === 'failed' ? 'فشلت' : 'نجحت'}</span>
      <span className="text-gray-500"> · {stamp(run.started_at)}</span>
      <div className="text-gray-500">قرأت {run.records_read}{run.new_count != null ? ` · جديد ${run.new_count}` : ''}
        {run.spool_waiting ? ` · بانتظار الإرسال ${run.spool_waiting}` : ''}</div>
      {admin && run.status === 'failed' && run.error && <div className="text-red-600">{run.error}</div>}
    </div>
  )
}

function CollectNow({ rows, onStart, onEnd }) {
  const [since, setSince] = useState(null)
  const qc = useQueryClient()
  const assigned = rows.filter(r => r.is_active && r.agent)
  const finished = since == null ? 0 : assigned.filter(r =>
    r.last_run?.started_at && Date.parse(r.last_run.started_at) >= since - SLACK_MS).length
  const waiting = since != null && finished < assigned.length && Date.now() - since < COLLECT_WAIT_MS
  const start = useMutation({
    mutationFn: () => hrAttendanceApi.collectNow(),
    onSuccess: () => { setSince(Date.now()); onStart(); qc.invalidateQueries({ queryKey: ['hr-attendance', 'devices'] }) },
  })
  useEffect(() => { if (since != null && !waiting) onEnd() }, [since, waiting, onEnd])
  return (
    <div className="mb-3" data-tour="hr-attendance-collect">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" disabled={start.isPending || waiting} onClick={() => start.mutate()}
          className={`${BTN} bg-primary text-white py-1.5`}>
          {waiting ? '⏳ جارٍ التجميع…' : '🔄 تجميع الآن'}</button>
        <span className="text-xs text-gray-500">يبدأ التجميع عند أول اتصال لبرنامج التجميع، وقد يستغرق دقائق.</span>
        <Notice>{start.isError ? errText(start.error) : ''}</Notice>
      </div>
      {since != null && (
        <ProgressBar className="mt-2 max-w-md" pct={assigned.length ? (finished / assigned.length) * 100 : 0}
          label="تجميع البصمات" message={`${finished} من ${assigned.length} ماكينة`} since={waiting ? since : undefined} />
      )}
    </div>
  )
}

function Agents() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [secret, setSecret] = useState(null)       // { name, value } — memory only
  const [copied, setCopied] = useState(false)
  const list = useQuery({ queryKey: ['hr-attendance', 'agents'], queryFn: () => hrAttendanceApi.agents().then(r => r.data.rows) })
  const refresh = () => qc.invalidateQueries({ queryKey: ['hr-attendance'] })
  const issue = useMutation({
    mutationFn: () => hrAttendanceApi.issueAgent(name.trim()),
    onSuccess: res => { setSecret({ name: res.data.name, value: res.data.secret }); setCopied(false); setName(''); refresh() },
  })
  const revoke = useMutation({ mutationFn: id => hrAttendanceApi.revokeAgent(id), onSuccess: refresh })
  const copy = async () => {
    try { await navigator.clipboard.writeText(secret.value); setCopied(true) } catch { setCopied(false) }
  }
  const rows = list.data || []
  return (
    <div className="mt-6" data-tour="hr-attendance-agents">
      <h2 className="text-sm font-bold text-gray-800 mb-2">برامج التجميع (للمدير فقط)</h2>
      {secret && (
        <div className="mb-3 rounded-lg border-2 border-amber-400 bg-amber-50 p-3" role="alert" data-tour="hr-attendance-agent-secret">
          <div className="font-bold text-amber-900 text-sm">السر الخاص بـ «{secret.name}» — يظهر مرة واحدة فقط</div>
          <p className="text-xs text-amber-800 mt-1">انسخه الآن وضعه في إعدادات البرنامج. لن يُعرض مرة أخرى ولا يُحفظ في المتصفح؛ لو ضاع أصدر برنامجاً جديداً وألغِ هذا.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code dir="ltr" className="flex-1 min-w-[16rem] break-all bg-white border border-amber-300 rounded px-2 py-1 text-xs select-all">{secret.value}</code>
            <button type="button" onClick={copy} className={`${BTN} bg-amber-600 text-white`}>{copied ? 'تم النسخ' : 'نسخ'}</button>
            <button type="button" onClick={() => setSecret(null)} className={`${BTN} bg-white border border-amber-300`}>نسخته — إخفاء</button>
          </div>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 mb-2 text-xs">
        <input value={name} onChange={e => setName(e.target.value)} placeholder="اسم البرنامج الجديد" maxLength={120}
          className="border border-gray-200 rounded-md px-2 py-1 bg-white" />
        <button type="button" disabled={issue.isPending || !name.trim()} onClick={() => issue.mutate()}
          className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>إصدار سر جديد</button>
        <Notice>{issue.isError ? errText(issue.error) : ''}{revoke.isError ? errText(revoke.error) : ''}</Notice>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <th className={TH}>البرنامج</th><th className={TH}>آخر اتصال</th><th className={TH}>الماكينات</th>
              <th className={TH}>الحالة</th><th className={TH}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(a => (
              <tr key={a.id} className="border-b border-gray-100">
                <td className="px-3 py-2 font-medium">{a.name}</td>
                <td className="px-3 py-2 text-gray-600">{stamp(a.last_seen_at)}</td>
                <td className="px-3 py-2 text-gray-600">{a.devices.join('، ') || '—'}</td>
                <td className="px-3 py-2 text-xs">{a.revoked_at ? <span className="text-gray-400">ملغى</span> : 'يعمل'}</td>
                <td className="px-3 py-2">
                  {!a.revoked_at && (
                    <button type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(a.id)}
                      className={`${BTN} bg-white border border-red-200 text-red-700 hover:bg-red-50`}>إلغاء</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && !list.isLoading && <Empty>لا توجد برامج تجميع بعد</Empty>}
      </div>
    </div>
  )
}

export default function DevicesTab({ access }) {
  const [collecting, setCollecting] = useState(false)
  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-attendance', 'devices'],
    queryFn: () => hrAttendanceApi.devices().then(r => r.data),
    refetchInterval: collecting ? 4000 : 60000,
  })
  const rows = useMemo(() => data?.rows || [], [data])
  const { sorted, headerProps } = useSortableRows(rows, {
    defaultSort: { key: 'name', dir: 'asc', type: 'text' }, getValue, persistKey: 'hr-attendance-devices', keys: KEYS })
  const admin = access.can_admin
  const stopCollecting = useCallback(() => setCollecting(false), [])

  return (
    <div>
      {access.can_manage && (
        <CollectNow rows={rows} onStart={() => setCollecting(true)} onEnd={stopCollecting} />
      )}
      <div data-tour="hr-attendance-devices-grid" className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
              <SortTh className={TH} {...headerProps('name', 'text')}>الماكينة</SortTh>
              <SortTh className={TH} {...headerProps('location_label', 'text')}>المكان</SortTh>
              <SortTh className={TH} {...headerProps('branch_name', 'text')}>الفرع</SortTh>
              <SortTh className={TH} {...headerProps('last_contact_at', 'date')}>آخر اتصال</SortTh>
              <SortTh className={TH} {...headerProps('last_drift_seconds', 'number')}>فرق الساعة</SortTh>
              <th className={TH}>آخر تجميع</th>
              {admin && <th className={TH}>العنوان</th>}
              {admin && <th className={TH}>البرنامج</th>}
            </tr>
          </thead>
          <tbody>
            {sorted.map(d => (
              <tr key={d.id} className={`border-b border-gray-100 align-top ${d.is_active ? '' : 'opacity-50'}`}>
                <td className="px-3 py-2 font-medium">{d.name}
                  {!d.is_active && <span className="ms-1 text-xs text-gray-400">متوقفة</span>}
                  {d.model_name && <div className="text-xs text-gray-400">{d.model_name}</div>}</td>
                <td className="px-3 py-2 text-gray-600">{d.location_label || '—'}</td>
                <td className="px-3 py-2 text-gray-600">{d.branch_name || '—'}</td>
                <td className="px-3 py-2 text-gray-600">{stamp(d.last_contact_at)}
                  {d.last_status && <div className="text-xs text-gray-400">{d.last_status}</div>}</td>
                <td className="px-3 py-2 tabular-nums"><Drift s={d.last_drift_seconds} /></td>
                <td className="px-3 py-2"><RunCell run={d.last_run} admin={admin} /></td>
                {admin && <td className="px-3 py-2 tabular-nums text-xs" dir="ltr">{d.ip ? `${d.ip}:${d.port}` : '—'}</td>}
                {admin && <td className="px-3 py-2 text-gray-600 text-xs">{d.agent_name || '—'}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {isLoading && <Empty>جاري التحميل…</Empty>}
        {error && <div className="py-10 text-center text-sm text-red-600">{errText(error)}</div>}
        {!isLoading && !error && rows.length === 0 && <Empty>لا توجد ماكينات مسجّلة</Empty>}
      </div>
      {admin && <Agents />}
    </div>
  )
}
