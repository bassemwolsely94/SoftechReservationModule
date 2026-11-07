/**
 * One tax document: totals, counts, blockers, reconciliation, affected SKUs, lines, reviews, attempts,
 * audit. "Show all source lines" changes only what is displayed: counts and totals come from the
 * server and are the same in both views, and the payload is never touched by it.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { taxInvoicingApi } from '../../api/client'
import useBranchLabels from '../../hooks/useBranchLabels'
import {
  ActionMsg, Badge, Btn, DOC_STATUS_TONE, Failed, Field, fmt, fmtDate, fmtInt, fmtTime, Grid, INPUT, LINE_STATUS_TONE,
  Loading, Notice, Section, useAction,
} from './ui'

const COUNT_CELLS = [
  ['approved', 'معتمد'], ['exempt', 'معفى'], ['uncoded', 'غير مُرمَّز'], ['pending', 'قيد المراجعة'], ['excluded', 'مستبعد'],
]
const REVIEW_CATEGORIES = [
  ['coding', 'مشكلة ترميز مؤقتة'], ['exempt', 'صنف معفى'], ['include', 'يُدرج في الفاتورة'], ['exclusion', 'طلب استبعاد من المستند'],
]
const FLIPS = { summary: 'detailed', detailed: 'summary' }
const MODE_LABEL = { summary: 'سطر واحد (مطالبة مالية)', detailed: 'تفصيلي' }

function Stat({ label, value, tone = 'text-gray-900' }) {
  return (
    <div className="min-w-[110px]">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`font-bold ${tone}`}>{value}</div>
    </div>
  )
}

// ── Actions ──────────────────────────────────────────────────────────────────────────────────────

function ReasonAction({ label, placeholder, variant, disabled, onSubmit, ...rest }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  if (!open) return <Btn variant={variant} disabled={disabled} onClick={() => setOpen(true)} {...rest}>{label}</Btn>
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <input autoFocus value={reason} onChange={e => setReason(e.target.value)} placeholder={placeholder} className={`${INPUT} min-w-[220px]`} />
      <Btn variant="primary" disabled={disabled || !reason.trim()} onClick={() => onSubmit(reason, () => { setOpen(false); setReason('') })}>تأكيد</Btn>
      <Btn onClick={() => setOpen(false)}>إلغاء</Btn>
    </span>
  )
}

function SubmitPanel({ doc, me, act }) {
  const [confirm, setConfirm] = useState('')
  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-2" data-tour="tax-invoicing-main-doc-submit">
      <div className="text-sm font-bold text-gray-800">الإرسال للمصلحة</div>
      {!me.submit_enabled && (
        <Notice tone="gray">🔕 الإرسال الفعلي مغلق حالياً، فلن يخرج هذا المستند للمصلحة. تقدر تعاين ما سيُرسل بزر «معاينة بدون إرسال».</Notice>
      )}
      {me.can_finalize ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label={`اكتب رقم المستند للتأكيد: ${doc.internal_id}`}>
            <input value={confirm} onChange={e => setConfirm(e.target.value)} dir="ltr" autoComplete="off" className={`${INPUT} min-w-[220px]`} />
          </Field>
          <Btn variant="danger" disabled={act.pending || !me.submit_enabled || !confirm.trim()}
            onClick={() => act.run(() => taxInvoicingApi.submit(doc.id, confirm), 'تم الطلب، راجع حالة المستند', () => setConfirm(''))}>
            إرسال للمصلحة
          </Btn>
        </div>
      ) : (
        <p className="text-xs text-gray-500">الإرسال لمن يملك صلاحية الاعتماد النهائي.</p>
      )}
    </div>
  )
}

function NoteForm({ doc, act }) {
  const [type, setType] = useState('c')
  const [reason, setReason] = useState('')
  const [amounts, setAmounts] = useState({})
  // The whole source is needed here: exempt lines are on the invoice too. A note needs `approve`,
  // the same action this view needs.
  const all = useQuery({
    queryKey: ['tax-invoicing', 'document', String(doc.id), 'all'],
    queryFn: () => taxInvoicingApi.document(doc.id, { view: 'all' }).then(r => r.data),
  })
  const lines = (all.data?.lines || []).filter(l => l.status === 'approved' || l.status === 'exempt')
  const items = Object.entries(amounts).filter(([, v]) => v.trim()).map(([line_id, amount]) => ({ line_id: Number(line_id), amount }))
  const columns = [
    { key: 'docnumber', label: 'الروشتة' },
    { key: 'item_name', label: 'الصنف', value: l => l.item_name || l.itemcode, render: l => l.item_name || l.itemcode },
    { key: 'net', label: 'صافي البند', type: 'number', render: l => fmt(l.net) },
    { key: 'amount', label: 'مبلغ الإشعار', sortable: false, render: l => (
      <input type="number" min="0" step="0.01" value={amounts[l.id] ?? ''} className={`${INPUT} w-28`}
        onChange={e => setAmounts(a => ({ ...a, [l.id]: e.target.value }))} />) },
  ]
  return (
    <div className="mt-3 pt-3 border-t border-gray-100 space-y-2" data-tour="tax-invoicing-main-doc-note">
      <div className="text-sm font-bold text-gray-800">إشعار على الفاتورة</div>
      <p className="text-xs text-gray-500">الفاتورة الأصلية لا تتغير أبداً. يُنشأ مستند جديد يشير إليها، ويراجعه النظام مثل أي مستند.</p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="النوع">
          <select value={type} onChange={e => setType(e.target.value)} className={INPUT}>
            <option value="c">إشعار دائن</option>
            <option value="d">إشعار مدين</option>
          </select>
        </Field>
        <Field label="السبب" className="grow min-w-[240px]">
          <input value={reason} onChange={e => setReason(e.target.value)} className={INPUT} />
        </Field>
        <Btn variant="primary" disabled={act.pending || !reason.trim() || !items.length}
          onClick={() => act.run(() => taxInvoicingApi.createNote(doc.id, { type, reason, items }),
            d => `أُنشئ الإشعار ${d.internal_id}`, () => { setReason(''); setAmounts({}) })}>
          إنشاء الإشعار
        </Btn>
      </div>
      {all.isLoading ? <Loading /> : <Grid columns={columns} rows={lines} empty="لا توجد بنود على الفاتورة" />}
    </div>
  )
}

function Actions({ doc, me, showPrint }) {
  const act = useAction()
  const [preview, setPreview] = useState(null)
  const [noteOpen, setNoteOpen] = useState(false)
  const id = doc.id
  const draft = doc.status === 'draft'
  const isInvoice = doc.doc_type === 'i'
  const blocked = doc.blockers.length > 0
  const reopenable = ['approved', 'invalid', 'rejected'].includes(doc.status)
  const askable = ['uncertain', 'submitting', 'submitted'].includes(doc.status)

  return (
    <Section title="الإجراءات" data-tour="tax-invoicing-main-doc-actions">
      <div className="flex flex-wrap items-center gap-2">
        {draft && me.can_create && (
          <Btn disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.revalidate(id), 'أُعيد الفحص')}>🔁 إعادة الفحص</Btn>
        )}
        {draft && isInvoice && me.can_approve && (
          <ReasonAction label="⟳ تحديث من المطالبة" placeholder="سبب تحديث المصدر (مطلوب)" disabled={act.pending}
            data-tour="tax-invoicing-main-doc-refresh"
            onSubmit={(reason, done) => act.run(() => taxInvoicingApi.refreshSource(id, reason), 'تم تحديث المصدر', done)} />
        )}
        {draft && isInvoice && me.can_approve && (
          <Btn disabled={act.pending} data-tour="tax-invoicing-main-doc-presentation"
            onClick={() => act.run(() => taxInvoicingApi.presentation(id, FLIPS[doc.presentation_mode]), 'تغيرت طريقة العرض')}>
            طريقة العرض: {MODE_LABEL[doc.presentation_mode]} ← {MODE_LABEL[FLIPS[doc.presentation_mode]]}
          </Btn>
        )}
        {draft && me.can_approve && (
          <Btn variant="success" disabled={act.pending || blocked} data-tour="tax-invoicing-main-doc-approve"
            title={blocked ? 'يوجد ما يمنع الاعتماد، راجع الموانع' : ''}
            onClick={() => act.run(() => taxInvoicingApi.approve(id), 'تم الاعتماد وتجميد المحتوى')}>
            ✔ اعتماد المستند
          </Btn>
        )}
        {reopenable && me.can_approve && (
          <ReasonAction label="↺ إعادة فتح" placeholder="سبب إعادة الفتح (مطلوب)" disabled={act.pending}
            data-tour="tax-invoicing-main-doc-reopen"
            onSubmit={(reason, done) => act.run(() => taxInvoicingApi.reopen(id, reason), 'أُعيد فتح المستند', done)} />
        )}
        {doc.status === 'approved' && me.can_approve && (
          <Btn disabled={act.pending} data-tour="tax-invoicing-main-doc-preview"
            onClick={() => act.run(() => taxInvoicingApi.preview(id), null, setPreview)}>👁 معاينة بدون إرسال</Btn>
        )}
        {askable && me.can_finalize && (
          <Btn disabled={act.pending} data-tour="tax-invoicing-main-doc-reconcile"
            onClick={() => act.run(() => taxInvoicingApi.reconcile(id), 'تم الاستعلام من المصلحة')}>❓ استعلام من المصلحة</Btn>
        )}
        {doc.status === 'valid' && isInvoice && me.can_approve && (
          <Btn onClick={() => setNoteOpen(o => !o)}>{noteOpen ? 'إخفاء الإشعار' : '＋ إشعار دائن / مدين'}</Btn>
        )}
        <Btn onClick={showPrint}>🖨️ النسخة المطبوعة</Btn>
      </div>
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
      {preview && (
        <div className="mt-3 space-y-1">
          <div className="text-xs text-gray-600">
            معاينة فقط، لم يُرسل ولم يُوقَّع شيء. البصمة: <span dir="ltr" className="font-mono">{preview.payload_hash}</span>
          </div>
          <pre dir="ltr" className="max-h-72 overflow-auto bg-gray-50 border border-gray-200 rounded-lg p-2 text-[11px] whitespace-pre-wrap break-all">{preview.payload_text}</pre>
        </div>
      )}
      {doc.status === 'approved' && <SubmitPanel doc={doc} me={me} act={act} />}
      {noteOpen && <NoteForm doc={doc} act={act} />}
    </Section>
  )
}

// ── Line review ──────────────────────────────────────────────────────────────────────────────────

function LineReviewForm({ docId, line, onDone }) {
  const act = useAction()
  const [f, setF] = useState({ category: 'exclusion', reason: '', supporting_reference: '', basis_id: '' })
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  const bases = useQuery({ queryKey: ['tax-invoicing', 'basis-options'], queryFn: () => taxInvoicingApi.basisOptions().then(r => r.data) })
  const options = (bases.data || []).filter(b => b.kind === 'exclusion')
  return (
    <div className="space-y-2">
      {line.reason && <div className="text-xs text-gray-600">السبب الحالي: {line.reason}</div>}
      <div className="flex flex-wrap items-end gap-2">
        <Field label="نوع المراجعة">
          <select value={f.category} onChange={e => set('category', e.target.value)} className={INPUT}>
            {REVIEW_CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <Field label="السبب" className="grow min-w-[220px]">
          <input value={f.reason} onChange={e => set('reason', e.target.value)} className={INPUT} />
        </Field>
        {f.category === 'exclusion' && (
          <>
            <Field label="الأساس الموثق">
              <select value={f.basis_id} onChange={e => set('basis_id', e.target.value)} className={`${INPUT} max-w-[260px]`}>
                <option value="">— بدون أساس —</option>
                {options.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
              </select>
            </Field>
            <Field label="مرجع داعم">
              <input value={f.supporting_reference} onChange={e => set('supporting_reference', e.target.value)} className={INPUT} />
            </Field>
          </>
        )}
        <Btn variant="primary" disabled={act.pending || !f.reason.trim()}
          onClick={() => act.run(() => taxInvoicingApi.requestReview(docId, line.id, { ...f, basis_id: f.basis_id || null }), 'سُجل طلب المراجعة', onDone)}>
          تسجيل المراجعة
        </Btn>
      </div>
      {f.category === 'exclusion' && options.length === 0 && (
        <p className="text-xs text-amber-800">لا يوجد أساس استبعاد موثق بعد. بدونه لن يُقبل الطلب ويبقى البند محجوزاً والمستند موقوفاً.</p>
      )}
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function ReviewDecision({ review, draft }) {
  const act = useAction()
  const [note, setNote] = useState('')
  if (review.state !== 'open' || !draft) return null
  return (
    <div className="flex flex-wrap items-center gap-1" data-tour="tax-invoicing-main-doc-review-decide">
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="ملاحظة (مطلوبة للرفض)" className={`${INPUT} min-w-[160px]`} />
      <Btn variant="success" disabled={act.pending}
        onClick={() => act.run(() => taxInvoicingApi.decideReview(review.id, { accept: true, note }), 'تم القبول')}>قبول</Btn>
      <Btn variant="danger" disabled={act.pending}
        onClick={() => act.run(() => taxInvoicingApi.decideReview(review.id, { accept: false, note }), 'تم الرفض')}>رفض</Btn>
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function JsonCell({ value }) {
  const empty = !value || !Object.keys(value).length
  if (empty) return <span className="text-gray-300">—</span>
  return <pre dir="ltr" className="text-[11px] whitespace-pre-wrap break-all max-w-[280px] font-mono">{JSON.stringify(value, null, 0)}</pre>
}

// ── Page ─────────────────────────────────────────────────────────────────────────────────────────

export default function DocumentDetail({ id, me, go }) {
  const bl = useBranchLabels()
  const [showAll, setShowAll] = useState(false)
  const [openLine, setOpenLine] = useState(null)
  const view = showAll && me.can_view_all_lines ? 'all' : 'approved'
  const { data: doc, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'document', String(id), view],
    queryFn: () => taxInvoicingApi.document(id, view === 'all' ? { view: 'all' } : {}).then(r => r.data),
    placeholderData: prev => prev,
  })
  const back = <Btn onClick={() => go('documents')}>← كل المستندات</Btn>
  if (isLoading) return <Loading />
  if (error) return <div className="space-y-3">{back}<Failed error={error} /></div>

  const draft = doc.status === 'draft'
  const rec = doc.reconciliation
  const c = doc.counts
  const lineColumns = [
    { key: 'docnumber', label: 'الروشتة', className: 'whitespace-nowrap' },
    { key: 'docdate', label: 'التاريخ', type: 'date', render: l => fmtDate(l.docdate), className: 'whitespace-nowrap' },
    { key: 'branch', label: 'الفرع', value: l => bl(l.branch), render: l => bl(l.branch), className: 'whitespace-nowrap' },
    { key: 'item_name', label: 'الصنف', value: l => l.item_name || l.itemcode, render: l => (
      <><div className="font-medium text-gray-900 max-w-[240px] truncate" dir="auto">{l.item_name || l.itemcode}</div>
        <div className="text-[11px] text-gray-400">{l.itemcode}</div></>) },
    { key: 'quantity', label: 'الكمية', type: 'number', render: l => fmt(l.quantity, 3) },
    { key: 'net', label: 'صافي المصدر', type: 'number', render: l => fmt(l.net) },
    { key: 'net_ex_vat', label: 'قبل الضريبة', type: 'number', render: l => fmt(l.net_ex_vat) },
    { key: 'vat_amount', label: 'الضريبة', type: 'number', render: l => fmt(l.vat_amount) },
    { key: 'total_incl_vat', label: 'الإجمالي', type: 'number', render: l => fmt(l.total_incl_vat), className: 'font-bold' },
    { key: 'status_label', label: 'الحالة', render: l => <Badge tone={LINE_STATUS_TONE[l.status]}>{l.status_label}</Badge> },
    { key: 'eta_code', label: 'كود المصلحة', render: l => <span dir="ltr" className="text-xs">{l.eta_code || '—'}</span> },
  ]
  const reviewColumns = [
    { key: 'itemcode', label: 'الصنف' },
    { key: 'category_label', label: 'النوع' },
    { key: 'state_label', label: 'الحالة' },
    { key: 'reason', label: 'السبب', className: 'max-w-[220px]' },
    { key: 'basis', label: 'الأساس', render: r => r.basis || '—', className: 'max-w-[180px]' },
    { key: 'effect_net', label: 'أثر الصافي', type: 'number', render: r => fmt(r.effect_net) },
    { key: 'effect_vat', label: 'أثر الضريبة', type: 'number', render: r => fmt(r.effect_vat) },
    { key: 'effect_gross', label: 'أثر الإجمالي', type: 'number', render: r => fmt(r.effect_gross), className: 'font-bold' },
    { key: 'requested_by', label: 'طلبها', render: r => <>{r.requested_by}<div className="text-[11px] text-gray-400">{fmtTime(r.requested_at)}</div></> },
    { key: 'reviewed_by', label: 'بت فيها', render: r => (r.reviewed_by
      ? <>{r.reviewed_by}<div className="text-[11px] text-gray-400">{fmtTime(r.reviewed_at)}</div>{r.review_note && <div className="text-[11px]">{r.review_note}</div>}</>
      : '—') },
    ...(me.can_approve ? [{ key: 'decide', label: '', sortable: false, render: r => <ReviewDecision review={r} draft={draft} /> }] : []),
  ]

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {back}
        <h2 className="text-lg font-bold text-gray-900">{doc.doc_type_label} {doc.internal_id}</h2>
        <Badge tone={DOC_STATUS_TONE[doc.status]}>{doc.status_label}</Badge>
        <span className="text-sm text-gray-600">{doc.client}</span>
        <Link to={`/insurance/claims/${doc.claim_id}`} className="text-sm text-primary font-bold hover:underline" data-tour="tax-invoicing-main-doc-claim-link">
          المطالبة {doc.claim_number}
        </Link>
        {doc.original_id && (
          <button type="button" onClick={() => go('documents', { doc: doc.original_id })} className="text-sm text-primary font-bold hover:underline">
            الأصل {doc.original_internal_id}
          </button>
        )}
      </div>

      <Section>
        <div className="flex flex-wrap gap-x-6 gap-y-3" data-tour="tax-invoicing-main-doc-totals">
          <Stat label="المبيعات" value={fmt(doc.totals.sales)} />
          <Stat label="الخصم" value={fmt(doc.totals.discount)} />
          <Stat label="الصافي" value={fmt(doc.totals.net)} />
          <Stat label="الضريبة" value={fmt(doc.totals.vat)} />
          <Stat label="الإجمالي" value={fmt(doc.totals.total)} tone="text-primary" />
          <div className="min-w-[180px]">
            <div className="text-[11px] text-gray-500">ما يذهب للمصلحة</div>
            <div className="text-sm font-medium text-gray-800">{doc.fiscal_mode === 'summary' ? 'سطر واحد' : 'تفصيلي'}</div>
            <div className="text-[11px] text-gray-500">{doc.fiscal_mode_reason}</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-2 mt-3 pt-3 border-t border-gray-100" data-tour="tax-invoicing-main-doc-counts">
          {COUNT_CELLS.map(([k, l]) => (
            <Stat key={k} label={l} value={fmtInt(c[k])}
              tone={c[k] > 0 && (k === 'uncoded' || k === 'pending') ? 'text-red-700' : k === 'excluded' && c[k] > 0 ? 'text-amber-800' : 'text-gray-900'} />
          ))}
          <Stat label="غير محسوم" value={fmtInt(c.unresolved)} tone={c.unresolved > 0 ? 'text-red-700' : 'text-emerald-700'} />
          <Stat label="كل البنود" value={fmtInt(c.total)} />
        </div>
        {(doc.eta_uuid || doc.eta_status_reason) && (
          <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-600 space-y-0.5">
            {doc.eta_uuid && <div>رقم المصلحة: <span dir="ltr" className="font-mono">{doc.eta_uuid}</span></div>}
            {doc.eta_status_reason && <div>رد المصلحة: {doc.eta_status_reason}</div>}
            {doc.eta_checked_at && <div>آخر استعلام: {fmtTime(doc.eta_checked_at)}</div>}
          </div>
        )}
      </Section>

      {doc.blockers.length > 0 && (
        <Notice tone="red" data-tour="tax-invoicing-main-doc-blockers">
          <div className="font-bold mb-1">🚫 لا يُعتمد هذا المستند قبل حل ما يلي (البند المحجوز يوقف المستند كله):</div>
          <ul className="list-disc ms-5 space-y-0.5">
            {doc.blockers.map((b, i) => <li key={i}>{b.message}</li>)}
          </ul>
          {c.unresolved > 0 && (
            <button type="button" className="mt-1 text-xs font-bold underline" onClick={() => go('exceptions')}>افتح الاستثناءات لحلها</button>
          )}
        </Notice>
      )}

      <Actions doc={doc} me={me} showPrint={() => go('print', { doc: doc.id })} />

      <Section title="مطابقة المطالبة مع الفاتورة" data-tour="tax-invoicing-main-doc-recon">
        {rec.source_total == null ? (
          <p className="text-xs text-gray-500">الإشعار لا يُطابق على المطالبة مباشرة؛ إجماليه {fmt(rec.proposed_total)}.</p>
        ) : (
          <>
            <div className="flex flex-wrap gap-x-6 gap-y-2 mb-3">
              <Stat label="إجمالي المطالبة" value={fmt(rec.source_total)} />
              <Stat label="إجمالي الفاتورة المقترح" value={fmt(rec.proposed_total)} />
              <Stat label="الفرق" value={fmt(rec.difference)} />
              <Stat label="مستبعد" value={fmt(rec.excluded_total)} />
              <Stat label="غير محسوم" value={fmt(rec.unresolved_total)} />
              <Stat label="فرق غير مفسر" value={fmt(rec.unexplained)} tone={rec.within_tolerance ? 'text-emerald-700' : 'text-red-700'} />
            </div>
            <Grid getKey={r => `${r.kind}|${r.ref}|${r.label}|${r.amount}`} rows={rec.rows} empty="لا يوجد فرق"
              columns={[
                { key: 'label', label: 'البند' },
                { key: 'ref', label: 'المرجع', render: r => r.ref || '—' },
                { key: 'amount', label: 'المبلغ', type: 'number', render: r => fmt(r.amount), className: 'font-bold' },
                { key: 'reason', label: 'السبب', render: r => r.reason || '—' },
              ]} />
          </>
        )}
      </Section>

      {doc.affected_skus.length > 0 && (
        <Section title="الأصناف المتأثرة" hint="أصناف عليها بنود ليست على الفاتورة حالياً." data-tour="tax-invoicing-main-doc-skus">
          <Grid getKey={r => r.itemcode} rows={doc.affected_skus} defaultSort={{ key: 'net', dir: 'desc', type: 'number' }}
            columns={[
              { key: 'itemcode', label: 'الكود' },
              { key: 'item_name', label: 'الصنف', render: r => r.item_name || '—' },
              { key: 'status', label: 'الحالة', render: r => <Badge tone={LINE_STATUS_TONE[r.status]}>{COUNT_CELLS.find(([k]) => k === r.status)?.[1] || r.status}</Badge> },
              { key: 'reason', label: 'السبب', className: 'max-w-[280px]' },
              { key: 'lines', label: 'بنود', type: 'number' },
              { key: 'net', label: 'الصافي', type: 'number', render: r => fmt(r.net) },
              { key: 'go', label: '', sortable: false, render: r => <Btn onClick={() => go('items', { q: r.itemcode })}>فتح الصنف</Btn> },
            ]} />
        </Section>
      )}

      <Section
        title={view === 'all' ? `كل بنود المصدر (${fmtInt(doc.lines.length)})` : `البنود المعتمدة (${fmtInt(doc.lines.length)} من ${fmtInt(c.total)})`}
        hint={`غير محسوم: ${fmtInt(c.unresolved)} · مستبعد: ${fmtInt(c.excluded)} · الفلتر يغير المعروض فقط، ولا يغير الإجماليات ولا ما يُرسل.`}
        data-tour="tax-invoicing-main-doc-lines">
        {me.can_view_all_lines && (
          <details className="mb-3 text-xs text-gray-600" data-tour="tax-invoicing-main-doc-advanced">
            <summary className="cursor-pointer font-bold">فلاتر متقدمة</summary>
            <label className="flex items-center gap-2 mt-2">
              <input type="checkbox" checked={showAll} onChange={e => setShowAll(e.target.checked)} data-tour="tax-invoicing-main-doc-show-all" />
              عرض كل بنود المصدر
            </label>
          </details>
        )}
        <Grid key={view} columns={lineColumns} rows={doc.lines} empty="لا توجد بنود في هذا العرض"
          onOpen={draft && me.can_create ? l => setOpenLine(o => (o === l.id ? null : l.id)) : undefined}
          openKey={openLine}
          renderOpen={l => <LineReviewForm docId={doc.id} line={l} onDone={() => setOpenLine(null)} />} />
      </Section>

      <Section title="المراجعات والاستبعادات" hint="كل طلب بأثره على الصافي والضريبة والإجمالي." data-tour="tax-invoicing-main-doc-reviews">
        <Grid columns={reviewColumns} rows={doc.reviews} empty="لا توجد مراجعات" />
      </Section>

      {doc.notes.length > 0 && (
        <Section title="إشعارات على هذه الفاتورة">
          <Grid rows={doc.notes} onOpen={n => go('documents', { doc: n.id })} columns={[
            { key: 'internal_id', label: 'الرقم' },
            { key: 'doc_type_label', label: 'النوع' },
            { key: 'status_label', label: 'الحالة', render: n => <Badge tone={DOC_STATUS_TONE[n.status]}>{n.status_label}</Badge> },
            { key: 'total_amount', label: 'الإجمالي', type: 'number', render: n => fmt(n.total_amount) },
            { key: 'created_at', label: 'التاريخ', type: 'date', render: n => fmtTime(n.created_at) },
          ]} />
        </Section>
      )}

      <Section title="المحاولات وسجل التدقيق" data-tour="tax-invoicing-main-doc-audit">
        <details className="text-xs text-gray-600 mb-3" open={doc.attempts.length > 0}>
          <summary className="cursor-pointer font-bold">محاولات الإرسال ({fmtInt(doc.attempts.length)})</summary>
          <div className="mt-2">
            <Grid rows={doc.attempts} empty="لم تحدث أي محاولة إرسال" columns={[
              { key: 'state_label', label: 'النتيجة' },
              { key: 'http_status', label: 'HTTP', type: 'number', render: a => a.http_status ?? '—' },
              { key: 'error', label: 'الخطأ', render: a => a.error || '—' },
              { key: 'started_at', label: 'بدأت', type: 'date', render: a => fmtTime(a.started_at) },
              { key: 'finished_at', label: 'انتهت', type: 'date', render: a => fmtTime(a.finished_at) },
            ]} />
          </div>
        </details>
        <details className="text-xs text-gray-600">
          <summary className="cursor-pointer font-bold">سجل التدقيق ({fmtInt(doc.events.length)})</summary>
          <div className="mt-2">
            <Grid rows={doc.events} empty="لا توجد أحداث" defaultSort={{ key: 'created_at', dir: 'desc', type: 'date' }} columns={[
              { key: 'created_at', label: 'الوقت', type: 'date', render: e => fmtTime(e.created_at), className: 'whitespace-nowrap' },
              { key: 'action', label: 'الحدث' },
              { key: 'actor', label: 'بواسطة', render: e => e.actor || 'النظام' },
              { key: 'reason', label: 'السبب', render: e => e.reason || '—', className: 'max-w-[220px]' },
              { key: 'before', label: 'قبل', sortable: false, render: e => <JsonCell value={e.before} /> },
              { key: 'after', label: 'بعد', sortable: false, render: e => <JsonCell value={e.after} /> },
            ]} />
          </div>
        </details>
      </Section>
    </div>
  )
}
