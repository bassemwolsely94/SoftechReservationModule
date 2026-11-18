/**
 * «الجهاز المحلي (192.168.1.8)» — the seal PC's agent and the live Invoicer sheet in D:\invoicer_mini (batch S5),
 * inside «ملف أكواد الإيصالات (المحصّل)». Display only: the server decides everything — whether a write is real or a
 * preview (the owner's switch), whether it is held on hand edits, what an import may drop. This part shows the
 * agent's last poll and version, the last read of the live file and how it differs from our latest version, the
 * hold with its two ways out, and the recent jobs. It polls only while a job waits for the seal PC.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { ActionMsg, Badge, Btn, Failed, fmtInt, fmtTime, Grid, INPUT, Loading, Notice, useAction } from './ui'

const POLL_MS = 4000
export const OUTDATED = 'حدّث برنامج الختم على جهاز الختم — هذا الإصدار لا يستلم مهام الملف'
export const SWITCH_OFF = 'الكتابة مغلقة — معاينة فقط'
const KIND = { egs_fetch: 'قراءة الملف', egs_write: 'كتابة نسخة' }
const MODE = { preview: 'معاينة', write: 'كتابة' }
const STATUS = {
  pending: 'بالانتظار', claimed: 'لدى جهاز الختم', done: 'تم', failed: 'فشل',
  busy: 'الملف مفتوح في المحصّل', held: 'موقوف: تعديلات يدوية',
}
const STATUS_TONE = {
  pending: 'bg-amber-50 text-amber-800 border-amber-200',
  claimed: 'bg-sky-50 text-sky-700 border-sky-200',
  done: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
  busy: 'bg-amber-50 text-amber-800 border-amber-300',
  held: 'bg-amber-50 text-amber-800 border-amber-300',
}

const diff = (a, r) => `+${fmtInt(a)} / −${fmtInt(r)}`

/** One line for a job's outcome, from the few fields the server sends. */
export function jobResult(j) {
  const r = j.result || {}
  if (j.error) return j.error
  if (j.status === 'held') return `${diff(r.added, r.removed)} عن آخر نسخة`
  if (j.status !== 'done') return '—'
  if (j.kind === 'egs_fetch') {
    const what = r.matches_version ? `= النسخة ${r.matches_version}` : r.hand_edits ? 'تعديلات يدوية' : ''
    return [`مكوّد ${fmtInt(r.coded_rows)} من ${fmtInt(r.total_rows)}`, what,
      r.added || r.removed ? diff(r.added, r.removed) : ''].filter(Boolean).join(' · ')
  }
  if (r.written) return `كُتب الملف${r.backup ? ` · نسخة احتياطية ${r.backup}` : ''}`
  if (r.preview) {
    return [r.would_write ? 'معاينة: كان سيُكتب' : 'معاينة: لن يُكتب',
      r.live_changed ? 'الملف تغيّر منذ آخر قراءة' : '', r.locked ? 'الملف مفتوح' : '',
      r.backup_dir_writable === false ? 'مجلد النسخ الاحتياطية غير قابل للكتابة' : ''].filter(Boolean).join(' · ')
  }
  return 'تم'
}

function CodeList({ label, codes }) {
  const [open, setOpen] = useState(false)
  const n = codes?.count || 0
  return (
    <div>
      <button type="button" className="text-primary disabled:text-gray-400" disabled={!n} onClick={() => setOpen(x => !x)}>
        {label} <b>{fmtInt(n)}</b>{n ? (open ? ' ▲' : ' ▼') : ''}
      </button>
      {open && n > 0 && (
        <div aria-label={label} className="mt-1 max-h-40 overflow-y-auto border border-gray-200 rounded-md p-2 text-xs font-mono flex flex-wrap gap-x-3 gap-y-1">
          {codes.items.map(c => <span key={c}>{c}</span>)}
          {n > codes.items.length && <span className="font-sans text-gray-400">… أول {fmtInt(codes.items.length)} فقط</span>}
        </div>
      )}
    </div>
  )
}

function LastFetch({ f }) {
  if (!f) return <p className="text-xs text-gray-500">لم يُقرأ الملف الحالي بعد.</p>
  const match = f.matches_version ? `مطابق للنسخة ${f.matches_version}`
    : f.hand_edits ? 'فيه تعديلات يدوية (لا يطابق أي نسخة لدينا)' : ''
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-gray-700">
        <span>آخر قراءة <b>{fmtTime(f.finished_at)}</b></span>
        <span>صفوف مكوّدة <b>{fmtInt(f.live?.coded_rows)}</b> من {fmtInt(f.live?.total_rows)}</span>
        {match && <span className={f.hand_edits ? 'text-amber-800' : 'text-emerald-700'}>{match}</span>}
        {!f.current && <span className="text-gray-400">(كُتبت نسخة بعدها)</span>}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <CodeList label={`في الملف الحالي وليس في النسخة ${f.latest ?? ''}`} codes={f.added_vs_latest} />
        <CodeList label={`في النسخة ${f.latest ?? ''} وليس في الملف الحالي`} codes={f.removed_vs_latest} />
      </div>
    </div>
  )
}

/** Hand edits in the live file: import them as the next version, or write over them with a reason. */
function HandEdits({ d, act }) {
  const f = d.last_fetch
  const [allow, setAllow] = useState(false)
  const [over, setOver] = useState(false)
  const [note, setNote] = useState('')
  const removes = f?.import_removes || 0
  const held = d.held
  return (
    <Notice tone="amber" data-testid="egs-agent-held">
      <div className="font-semibold">
        {held ? `الكتابة موقوفة: الملف الحالي على جهاز الختم فيه تعديلات يدوية (${diff(held.added.count, held.removed.count)} عن النسخة ${held.version})`
          : 'الملف الحالي على جهاز الختم فيه تعديلات يدوية — أي كتابة ستُوقف حتى تقرر'}
      </div>
      {d.can_approve && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {f?.importable && (
            <>
              <Btn variant="primary" disabled={act.pending || (removes > 0 && !allow)}
                onClick={() => act.run(() => taxInvoicingApi.egsAgentImport({ job: f.id, allow_removals: allow }),
                  r => `استُوردت التعديلات كنسخة ${r.version?.number}`)}>استورد التعديلات</Btn>
              {removes > 0 && (
                <label className="flex items-center gap-1 text-xs">
                  <input type="checkbox" checked={allow} onChange={e => setAllow(e.target.checked)} />
                  أقبل حذف أصناف ({fmtInt(removes)}) مكوّدة في آخر نسخة وليست في الملف الحالي
                </label>
              )}
            </>
          )}
          {!over ? (
            <Btn variant="danger" disabled={act.pending} onClick={() => setOver(true)}>اكتب فوقها</Btn>
          ) : (
            <span className="flex flex-wrap items-center gap-2">
              <input className={`${INPUT} w-64`} aria-label="سبب الكتابة فوق التعديلات" placeholder="السبب (يُسجّل)"
                value={note} onChange={e => setNote(e.target.value)} />
              <Btn variant="danger" disabled={act.pending || !note.trim()}
                onClick={() => act.run(() => taxInvoicingApi.egsAgentWrite({ override: true, note: note.trim() }),
                  r => (r.job ? `طُلبت ${MODE[r.job.mode]} فوق التعديلات اليدوية` : 'لا شيء يُكتب'),
                  () => { setOver(false); setNote('') })}>
                {d.switch ? 'تأكيد الكتابة فوقها' : 'تأكيد المعاينة فوقها'}
              </Btn>
              <Btn onClick={() => { setOver(false); setNote('') }}>إلغاء</Btn>
            </span>
          )}
        </div>
      )}
    </Notice>
  )
}

function writeMsg(r) {
  const j = r.job
  if (!j) return 'الملف الحالي هو آخر نسخة — لا شيء يُكتب'
  if (j.status === 'held') return 'لم تُطلب الكتابة: الملف الحالي فيه تعديلات يدوية'
  return j.mode === 'write' ? 'طُلبت الكتابة — تتم عند اتصال جهاز الختم' : 'طُلبت المعاينة — لا يُكتب شيء في الملف'
}

const JOB_COLUMNS = [
  { key: 'kind', label: 'المهمة', render: j => KIND[j.kind] || j.kind, value: j => KIND[j.kind] || j.kind },
  { key: 'mode', label: 'النوع', value: j => (j.kind === 'egs_write' ? MODE[j.mode] : ''),
    render: j => (j.kind === 'egs_write' ? `${MODE[j.mode] || j.mode}${j.override ? ' (فوق التعديلات)' : ''}` : '—') },
  { key: 'status', label: 'الحالة', value: j => STATUS[j.status] || j.status,
    render: j => <Badge tone={STATUS_TONE[j.status]}>{STATUS[j.status] || j.status}</Badge> },
  { key: 'created_at', label: 'الوقت', type: 'date', render: j => fmtTime(j.created_at) },
  { key: 'result', label: 'النتيجة', value: jobResult,
    render: j => <span className={j.error ? 'text-red-700 text-xs' : 'text-xs'}>{jobResult(j)}</span> },
]

export default function EgsAgentPart() {
  const act = useAction()
  const q = useQuery({
    queryKey: ['tax-invoicing', 'egs-agent'],
    queryFn: () => taxInvoicingApi.egsAgent().then(r => r.data),
    refetchInterval: query => (query.state.data?.busy ? POLL_MS : false),
  })
  const d = q.data
  if (q.isLoading) return <Loading />
  if (q.error) return <Failed error={q.error} />
  const a = d.agent || {}
  const handEdits = d.held || d.last_fetch?.hand_edits
  return (
    <div className="space-y-2 text-sm border-t border-gray-100 pt-3" data-tour="tax-invoicing-queue-egs-agent">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="font-semibold text-gray-900">الجهاز المحلي (192.168.1.8)</h4>
        {d.switch ? <Badge tone="bg-emerald-50 text-emerald-700 border-emerald-200">الكتابة مفتوحة</Badge>
          : <Badge tone="bg-gray-100 text-gray-700 border-gray-300">{SWITCH_OFF}</Badge>}
        {d.busy && <span role="status" className="text-xs text-primary">⏳ مهمة بانتظار جهاز الختم…</span>}
        {d.can_approve && (
          <span className="ms-auto flex flex-wrap gap-2">
            <Btn disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.egsAgentFetch(),
              'طُلبت قراءة الملف — تتم عند اتصال جهاز الختم')}>اقرأ الملف الحالي</Btn>
            <Btn variant="primary" disabled={act.pending || !d.has_version}
              title={d.switch ? '' : 'مفتاح الكتابة مغلق: يتحقق جهاز الختم من الملف ولا يكتب شيئاً'}
              onClick={() => act.run(() => taxInvoicingApi.egsAgentWrite({}), writeMsg)}>
              {d.switch ? 'اكتب الآن' : 'معاينة الآن'}
            </Btn>
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-gray-700">
        {a.at ? (
          <>
            <span>آخر اتصال <b>{fmtTime(a.at)}</b></span>
            <span>إصدار البرنامج <b>{a.version ?? '—'}</b></span>
          </>
        ) : <span className="text-gray-500">لم يتصل برنامج جهاز الختم بعد</span>}
      </div>
      {a.at && a.outdated && <Notice tone="amber">{OUTDATED}</Notice>}
      <LastFetch f={d.last_fetch} />
      {handEdits && <HandEdits d={d} act={act} />}
      <ActionMsg msg={act.msg} />
      {d.jobs?.length > 0 && (
        <Grid rows={d.jobs} columns={JOB_COLUMNS} aria-label="مهام جهاز الختم"
          defaultSort={{ key: 'created_at', dir: 'desc', type: 'date' }} />
      )}
    </div>
  )
}
