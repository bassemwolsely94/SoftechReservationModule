/**
 * EGS item-code requests to ETA (doc 36 §coding). Display only: the server builds each request, sends it
 * behind its switches and permission, and moves the item's coding only from ETA's answer.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { ActionMsg, Badge, Btn, Failed, Field, fmtInt, fmtTime, Grid, INPUT, Loading, Notice, Section, useAction } from './ui'

const TONE = {
  prepared: 'bg-gray-100 text-gray-700 border-gray-200',
  sending: 'bg-amber-50 text-amber-800 border-amber-200',
  submitted: 'bg-sky-50 text-sky-700 border-sky-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  rejected: 'bg-red-50 text-red-700 border-red-200',
  failed: 'bg-red-50 text-red-700 border-red-200',
  uncertain: 'bg-amber-50 text-amber-800 border-amber-300',
  cancelled: 'bg-gray-100 text-gray-500 border-gray-200',
}

export function EtaConnection({ me }) {
  const q = useQuery({ queryKey: ['tax-invoicing', 'eta-status'], queryFn: () => taxInvoicingApi.etaStatus().then(r => r.data) })
  const act = useAction()
  if (q.isLoading) return <Loading />
  if (q.error) return <Failed error={q.error} />
  const s = q.data
  return (
    <Section title="منظومة المصلحة" data-tour="tax-invoicing-main-eta-connection"
      hint="أي منظومة يتصل بها هذا السيرفر. التجريبية أولاً؛ الفعلية تحتاج موافقة المالك."
      actions={me.can_finalize && (
        <Btn disabled={act.pending || !s.api_base} data-tour="tax-invoicing-main-eta-check-login"
          onClick={() => act.run(() => taxInvoicingApi.etaCheckLogin(), d => d.detail)}>اختبار الدخول</Btn>
      )}>
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge tone={s.is_production ? 'bg-red-50 text-red-700 border-red-200' : 'bg-sky-50 text-sky-700 border-sky-200'}>
          {s.api_base ? s.label : 'غير محددة'}
        </Badge>
        {s.is_production && <Badge>{s.production_allowed ? 'الإرسال للفعلية مسموح' : 'الإرسال للفعلية موقوف'}</Badge>}
        <Badge>{s.erp_client_configured ? 'بيانات دخول النظام موجودة' : 'بيانات دخول النظام ناقصة'}</Badge>
        <Badge>{s.invoice_submit_enabled ? 'إرسال الفواتير مفتوح' : 'إرسال الفواتير مغلق'}</Badge>
        <Badge>{s.receipt_submit_enabled ? 'إرسال الإيصالات مفتوح' : 'إرسال الإيصالات مغلق'}</Badge>
        <Badge>{s.coding_send_enabled ? 'طلب الأكواد مفتوح' : 'طلب الأكواد مغلق'}</Badge>
      </div>
      {s.api_base && <div className="text-[11px] text-gray-400 mt-2 font-mono" dir="ltr">{s.api_base}</div>}
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
    </Section>
  )
}

function Candidates({ me }) {
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState([])
  const [gpc, setGpc] = useState('')
  const act = useAction()
  const list = useQuery({ queryKey: ['tax-invoicing', 'code-candidates', q], queryFn: () => taxInvoicingApi.codeCandidates({ q }).then(r => r.data) })
  const toggle = id => setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]))
  const columns = [
    { key: 'pick', label: '', sortable: false, render: r => (
      <input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`اختيار ${r.itemcode}`} />) },
    { key: 'itemcode', label: 'الكود', className: 'whitespace-nowrap' },
    { key: 'item_name', label: 'الاسم الإنجليزي', render: r => r.item_name || '—', className: 'max-w-[220px] truncate' },
    { key: 'item_name_ar', label: 'الاسم العربي', render: r => r.item_name_ar || '—', className: 'max-w-[220px] truncate' },
    { key: 'gpc_code', label: 'GPC', render: r => r.gpc_code || '—' },
    { key: 'coding_status', label: 'الترميز', value: r => r.coding_status_label, render: r => <Badge>{r.coding_status_label}</Badge> },
  ]
  return (
    <Section title="أصناف تحتاج كوداً" hint="بلا كود، أو رفضت المصلحة كودها السابق، ولا يوجد لها طلب مفتوح."
      actions={me.can_edit && (
        <>
          <Field label="كود GPC للمختار (اختياري)" hint="8 أرقام؛ فارغ = كود الصنف المسجل">
            <input className={`${INPUT} w-28`} value={gpc} onChange={e => setGpc(e.target.value.trim())} dir="ltr" inputMode="numeric" />
          </Field>
          <Btn variant="primary" disabled={!picked.length || act.pending} data-tour="tax-invoicing-main-codes-prepare"
            onClick={() => act.run(() => taxInvoicingApi.codesPrepare({ ids: picked, parent_code: gpc }),
              d => `جُهّز ${fmtInt(d.created.length)} طلب${d.skipped.length ? ` — تُرك ${fmtInt(d.skipped.length)}: ${d.skipped.slice(0, 3).map(s => `${s.itemcode} (${s.why})`).join('، ')}` : ''}`,
              () => setPicked([]))}>
            تجهيز طلبات ({fmtInt(picked.length)})
          </Btn>
        </>
      )}>
      <div className="mb-2"><input className={`${INPUT} w-64`} placeholder="بحث بالكود أو الاسم" value={q} onChange={e => setQ(e.target.value)} /></div>
      {list.isLoading ? <Loading /> : list.error ? <Failed error={list.error} /> : (
        <Grid columns={columns} rows={list.data} onOpen={r => toggle(r.id)} empty="✅ لا توجد أصناف تحتاج كوداً" />
      )}
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
    </Section>
  )
}

function EditRequest({ row }) {
  const [f, setF] = useState({ parent_code: row.parent_code, code_name: row.code_name, code_name_ar: row.code_name_ar,
    description: row.description, description_ar: row.description_ar })
  const [reason, setReason] = useState('')
  const act = useAction()
  const set = k => e => setF(v => ({ ...v, [k]: e.target.value }))
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
        <Field label="GPC"><input className={INPUT} value={f.parent_code} onChange={set('parent_code')} dir="ltr" /></Field>
        <Field label="الاسم الإنجليزي"><input className={INPUT} value={f.code_name} onChange={set('code_name')} dir="ltr" /></Field>
        <Field label="الاسم العربي"><input className={INPUT} value={f.code_name_ar} onChange={set('code_name_ar')} /></Field>
        <Field label="وصف إنجليزي"><input className={INPUT} value={f.description} onChange={set('description')} dir="ltr" /></Field>
        <Field label="وصف عربي"><input className={INPUT} value={f.description_ar} onChange={set('description_ar')} /></Field>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Btn variant="primary" disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.codeUpdate(row.id, f), 'تم الحفظ')}>حفظ</Btn>
        <Field label="سبب الإلغاء"><input className={`${INPUT} w-56`} value={reason} onChange={e => setReason(e.target.value)} /></Field>
        <Btn variant="danger" disabled={act.pending || !reason.trim()}
          onClick={() => act.run(() => taxInvoicingApi.codeCancel(row.id, reason), 'أُلغي الطلب')}>إلغاء الطلب</Btn>
      </div>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function Requests({ me }) {
  const [status, setStatus] = useState('')
  const [picked, setPicked] = useState([])
  const [confirm, setConfirm] = useState('')
  const [open, setOpen] = useState(null)
  const act = useAction()
  const list = useQuery({ queryKey: ['tax-invoicing', 'codes', status], queryFn: () => taxInvoicingApi.codes({ status }).then(r => r.data) })
  if (list.isLoading) return <Loading />
  if (list.error) return <Failed error={list.error} />
  const { summary, rows } = list.data
  const sendable = rows.filter(r => ['prepared', 'failed'].includes(r.status))
  const toggle = id => setPicked(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]))
  const columns = [
    { key: 'pick', label: '', sortable: false, render: r => (['prepared', 'failed'].includes(r.status)
      ? <input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`اختيار ${r.item_code}`} /> : null) },
    { key: 'itemcode', label: 'صنف SOFTECH', className: 'whitespace-nowrap' },
    { key: 'item_code', label: 'كود المصلحة', className: 'font-mono text-xs whitespace-nowrap', render: r => <span dir="ltr">{r.item_code}</span> },
    { key: 'code_name', label: 'الاسم', render: r => r.code_name_ar || r.code_name, className: 'max-w-[220px] truncate' },
    { key: 'parent_code', label: 'GPC' },
    { key: 'status', label: 'الحالة', value: r => r.status_label, render: r => <Badge tone={TONE[r.status]}>{r.status_label}</Badge> },
    { key: 'error', label: 'ملاحظة', render: r => r.error || r.eta_status || '—', className: 'max-w-[260px] text-xs text-gray-500' },
    { key: 'sent_at', label: 'أُرسل', type: 'date', render: r => (r.sent_at ? `${fmtTime(r.sent_at)} · ${r.sent_by}` : '—') },
    { key: 'checked_at', label: 'آخر استعلام', type: 'date', render: r => fmtTime(r.checked_at) },
  ]
  const counts = summary.by_status || {}
  return (
    <Section title="طلبات الأكواد" data-tour="tax-invoicing-main-codes-requests"
      hint={`${fmtInt(summary.candidates)} صنف ينتظر طلباً · لدى المصلحة ${fmtInt(counts.submitted || 0)} · معتمد ${fmtInt(counts.approved || 0)} · مرفوض ${fmtInt(counts.rejected || 0)} · غير مؤكد ${fmtInt(counts.uncertain || 0)}`}
      actions={(
        <>
          <select className={INPUT} value={status} onChange={e => setStatus(e.target.value)} aria-label="الحالة">
            <option value="">كل الحالات</option>
            {(me.code_request_statuses || []).map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
          {me.can_edit && (
            <Btn disabled={act.pending} data-tour="tax-invoicing-main-codes-refresh"
              onClick={() => act.run(() => taxInvoicingApi.codesRefresh({}), d => d.detail || `تم الاستعلام عن ${fmtInt(d.checked)} طلب — اعتُمد ${fmtInt(d.approved)} ورُفض ${fmtInt(d.rejected)}`)}>
              تحديث الحالة من المصلحة
            </Btn>
          )}
        </>
      )}>
      {me.can_finalize && sendable.length > 0 && (
        <div className="flex flex-wrap items-end gap-2 mb-3" data-tour="tax-invoicing-main-codes-send">
          {!me.coding_send_enabled && <Notice tone="gray">🔕 طلب الأكواد من المصلحة مغلق (TAX_ETA_CODING_ENABLED).</Notice>}
          <Field label={`اكتب عدد المختار (${picked.length}) للتأكيد`}>
            <input className={`${INPUT} w-20`} value={confirm} onChange={e => setConfirm(e.target.value)} inputMode="numeric" />
          </Field>
          <Btn variant="primary" disabled={!picked.length || !me.coding_send_enabled || act.pending}
            onClick={() => act.run(() => taxInvoicingApi.codesSend({ ids: picked, confirm }),
              d => `أُرسل ${fmtInt(d.submitted)} · لم يُقبل ${fmtInt(d.failed)} · غير مؤكد ${fmtInt(d.uncertain)}${d.stopped ? ` — ${d.stopped}` : ''}`,
              () => { setPicked([]); setConfirm('') })}>
            إرسال للمصلحة
          </Btn>
        </div>
      )}
      <Grid columns={columns} rows={rows} openKey={open}
        onOpen={r => setOpen(o => (o === r.id || r.status !== 'prepared' || !me.can_edit ? null : r.id))}
        renderOpen={r => <EditRequest row={r} />} empty="لا توجد طلبات" />
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
    </Section>
  )
}

export default function CodesTab({ me }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        الصنف بلا كود معتمد يوقف كل مستند هو عليه. هنا نطلب من المصلحة تسجيل كودنا الداخلي (EG-رقم التسجيل-كود الصنف)،
        ثم نتابع الطلب حتى تعتمده المصلحة أو ترفضه. حالة ترميز الصنف تتغير من رد المصلحة فقط.
      </p>
      <EtaConnection me={me} />
      <Requests me={me} />
      <Candidates me={me} />
    </div>
  )
}
