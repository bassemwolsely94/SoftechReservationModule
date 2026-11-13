/**
 * The taxpayer's details and accountant decisions, buyers, documented bases, and the seal's status.
 * Issuer, bases and signing need `finalize`; buyers need `edit`; the server refuses the rest.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import {
  ActionMsg, Badge, Btn, Failed, Field, fmtDate, fmtTime, Grid, INPUT, Loading, Notice, Section, useAction,
} from './ui'

const ISSUER_GROUPS = [
  ['بيانات الممول', [
    ['name', 'الاسم'], ['tax_id', 'رقم التسجيل الضريبي'], ['activity_code', 'كود النشاط'], ['branch_id', 'كود الفرع لدى المصلحة'],
    ['country', 'الدولة'], ['governate', 'المحافظة'], ['region_city', 'المدينة'], ['street', 'الشارع'], ['building_number', 'رقم المبنى'],
    ['default_unit_type', 'الوحدة الافتراضية'],
  ]],
  ['أنواع الضريبة لدى المصلحة', [
    ['vat_tax_type', 'نوع الضريبة'], ['subtype_taxable', 'النوع الفرعي: خاضع'], ['subtype_exempt', 'النوع الفرعي: معفى'], ['subtype_zero_rated', 'النوع الفرعي: صفر'],
  ]],
  ['قاعدة السطر الواحد للمصلحة', [
    ['summary_code_type', 'نوع الكود'], ['summary_item_code', 'الكود'], ['summary_description', 'البيان'], ['summary_vat_rate', 'نسبة الضريبة %'],
  ]],
]
const TREATMENT = [['taxable', 'خاضع'], ['exempt', 'معفى'], ['zero_rated', 'نسبة صفر']]
const BUYER_FIELDS = [
  ['legal_name', 'الاسم القانوني'], ['tax_id', 'رقم التسجيل الضريبي'], ['governate', 'المحافظة'],
  ['region_city', 'المدينة'], ['street', 'الشارع'], ['building_number', 'رقم المبنى'],
]
const MODES = [['summary', 'سطر واحد (مطالبة مالية)'], ['detailed', 'تفصيلي']]

function issuerForm(i) {
  return {
    ...Object.fromEntries(ISSUER_GROUPS.flatMap(([, fields]) => fields).map(([k]) => [k, i[k] ?? ''])),
    summary_treatment: i.summary_treatment || '',
    prices_include_vat: !!i.prices_include_vat,
    vat_basis_confirmed: !!i.vat_basis_confirmed_at,
    summary_validated: !!i.summary_validated_at,
    reconcile_tolerance: i.reconcile_tolerance ?? '',
    exclusion_second_person: !!i.exclusion_second_person,
  }
}

function IssuerForm({ issuer, me }) {
  const act = useAction()
  const start = issuerForm(issuer)
  const [f, setF] = useState(start)
  const can = me.can_finalize
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  // Only what changed goes out: re-sending a confirmation would re-stamp who confirmed it and when.
  const changes = Object.fromEntries(Object.entries(f).filter(([k, v]) => v !== start[k]))
  return (
    <Section title="بيانات الممول وقرارات المحاسب" data-tour="tax-invoicing-main-settings-issuer"
      hint={can ? 'كل تغيير يُسجل ويعيد فحص كل المسودات.' : 'عرض فقط. التعديل لمن يملك صلاحية الاعتماد النهائي.'}>
      <div className="space-y-4">
        {ISSUER_GROUPS.map(([title, fields]) => (
          <div key={title}>
            <div className="text-xs font-bold text-gray-700 mb-1">{title}</div>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {fields.map(([k, label]) => (
                <Field key={k} label={label}>
                  <input value={f[k]} disabled={!can} onChange={e => set(k, e.target.value)} className={INPUT} />
                </Field>
              ))}
              {title.startsWith('قاعدة') && (
                <Field label="المعاملة">
                  <select value={f.summary_treatment} disabled={!can} onChange={e => set('summary_treatment', e.target.value)} className={INPUT}>
                    <option value="">—</option>
                    {TREATMENT.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                  </select>
                </Field>
              )}
            </div>
          </div>
        ))}
        <div className="grid gap-2 sm:grid-cols-2 text-xs text-gray-700">
          <label className="flex items-center gap-1.5"><input type="checkbox" disabled={!can} checked={f.prices_include_vat} onChange={e => set('prices_include_vat', e.target.checked)} /> الأسعار شاملة الضريبة</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" disabled={!can} checked={f.vat_basis_confirmed} onChange={e => set('vat_basis_confirmed', e.target.checked)} />
            تأكيد المحاسب لأساس الضريبة {issuer.vat_basis_confirmed_at && <span className="text-gray-400">({issuer.vat_basis_confirmed_by} · {fmtTime(issuer.vat_basis_confirmed_at)})</span>}</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" disabled={!can} checked={f.summary_validated} onChange={e => set('summary_validated', e.target.checked)} />
            قاعدة السطر الواحد معتمدة {issuer.summary_validated_at && <span className="text-gray-400">({issuer.summary_validated_by} · {fmtTime(issuer.summary_validated_at)})</span>}</label>
          <label className="flex items-center gap-1.5"><input type="checkbox" disabled={!can} checked={f.exclusion_second_person} onChange={e => set('exclusion_second_person', e.target.checked)} /> الاستبعاد يحتاج شخصاً ثانياً</label>
          <Field label="أقصى فرق غير مفسر (ج.م)" className="max-w-[200px]">
            <input type="number" min="0" step="0.01" value={f.reconcile_tolerance} disabled={!can} onChange={e => set('reconcile_tolerance', e.target.value)} className={INPUT} />
          </Field>
        </div>
        {can && (
          <div className="flex items-center gap-2">
            <Btn variant="primary" disabled={act.pending || !Object.keys(changes).length} onClick={() => act.run(() => taxInvoicingApi.updateIssuer(changes), 'تم الحفظ')}>حفظ</Btn>
            <ActionMsg msg={act.msg} />
          </div>
        )}
      </div>
    </Section>
  )
}

function BuyerEditor({ buyer, me, zeroBases, onDone }) {
  const act = useAction()
  const [f, setF] = useState({
    presentation_mode: buyer.presentation_mode || 'summary',
    ...Object.fromEntries(BUYER_FIELDS.map(([k]) => [k, buyer[k] || ''])),
  })
  const recorded = buyer.zero_vat_basis_id ? String(buyer.zero_vat_basis_id) : ''
  const [zero, setZero] = useState(recorded)
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  // Sent only when it changes: changing it needs `finalize`, saving the rest of the buyer does not.
  const body = () => ({
    client_id: buyer.client_id, ...f,
    ...(zero === recorded ? {} : { zero_vat_basis_id: zero ? Number(zero) : null }),
  })
  // A recorded basis may have been stopped since, so it is no longer among the active options.
  const options = recorded && !zeroBases.some(b => String(b.id) === recorded)
    ? [{ id: recorded, label: `${buyer.zero_vat_basis} (موقوف)` }, ...zeroBases]
    : zeroBases
  return (
    <div className="space-y-2">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {BUYER_FIELDS.map(([k, label]) => (
          <Field key={k} label={label}><input value={f[k]} disabled={!me.can_edit} onChange={e => set(k, e.target.value)} className={INPUT} /></Field>
        ))}
        <Field label="طريقة العرض">
          <select value={f.presentation_mode} disabled={!me.can_edit} onChange={e => set('presentation_mode', e.target.value)} className={INPUT}>
            {MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        {me.can_finalize && (
          <Field label="عدم استحقاق ضريبة" hint="يحتاج أساساً موثقاً من نوع «عدم استحقاق ضريبة».">
            <select value={zero} onChange={e => setZero(e.target.value)} className={INPUT}>
              <option value="">لا يوجد: الضريبة تتبع كل صنف</option>
              {options.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
            </select>
          </Field>
        )}
      </div>
      {me.can_edit && (
        <Btn variant="primary" disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.saveBuyer(body()), 'تم الحفظ', onDone)}>حفظ المشتري</Btn>
      )}
      <ActionMsg msg={act.msg} />
    </div>
  )
}

function Buyers({ me }) {
  const [open, setOpen] = useState(null)
  const list = useQuery({ queryKey: ['tax-invoicing', 'buyers'], queryFn: () => taxInvoicingApi.buyers().then(r => r.data) })
  const opts = useQuery({ queryKey: ['tax-invoicing', 'basis-options'], queryFn: () => taxInvoicingApi.basisOptions().then(r => r.data) })
  const zeroBases = (opts.data || []).filter(b => b.kind === 'zero_vat')
  return (
    <Section title="المشترون" hint="بيانات الجهة على الفاتورة وطريقة عرض فاتورتها." data-tour="tax-invoicing-main-settings-buyers">
      {list.isLoading ? <Loading /> : list.error ? <Failed error={list.error} /> : (
        <Grid rows={list.data} getKey={b => b.client_id} empty="لا توجد جهات"
          onOpen={b => setOpen(o => (o === b.client_id ? null : b.client_id))} openKey={open}
          renderOpen={b => <BuyerEditor key={b.client_id} buyer={b} me={me} zeroBases={zeroBases} onDone={() => setOpen(null)} />}
          columns={[
            { key: 'client', label: 'الجهة' },
            { key: 'legal_name', label: 'الاسم القانوني', render: b => b.legal_name || <span className="text-red-600 text-xs">ناقص</span> },
            { key: 'tax_id', label: 'الرقم الضريبي', render: b => b.tax_id || <span className="text-red-600 text-xs">ناقص</span> },
            { key: 'presentation_mode', label: 'طريقة العرض', value: b => MODES.find(([k]) => k === b.presentation_mode)?.[1], render: b => MODES.find(([k]) => k === b.presentation_mode)?.[1] },
            { key: 'zero_vat_basis', label: 'عدم استحقاق ضريبة', render: b => b.zero_vat_basis || '—' },
          ]} />
      )}
    </Section>
  )
}

function BasisForm() {
  const act = useAction()
  const blank = { kind: 'exclusion', title: '', reference_number: '', issued_by: '', document_url: '', applies_to: '' }
  const [f, setF] = useState(blank)
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  return (
    <div className="mb-3 space-y-2">
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <Field label="النوع">
          <select value={f.kind} onChange={e => set('kind', e.target.value)} className={INPUT}>
            <option value="exclusion">استبعاد بند</option>
            <option value="zero_vat">عدم استحقاق ضريبة</option>
          </select>
        </Field>
        <Field label="العنوان"><input value={f.title} onChange={e => set('title', e.target.value)} className={INPUT} /></Field>
        <Field label="رقم المرجع"><input value={f.reference_number} onChange={e => set('reference_number', e.target.value)} className={INPUT} /></Field>
        <Field label="جهة الإصدار"><input value={f.issued_by} onChange={e => set('issued_by', e.target.value)} className={INPUT} /></Field>
        <Field label="رابط المستند"><input dir="ltr" value={f.document_url} onChange={e => set('document_url', e.target.value)} className={INPUT} /></Field>
        <Field label="نطاق التطبيق"><input value={f.applies_to} onChange={e => set('applies_to', e.target.value)} className={INPUT} /></Field>
      </div>
      <div className="flex items-center gap-2">
        <Btn variant="primary" disabled={act.pending} onClick={() => act.run(() => taxInvoicingApi.createBasis(f), 'سُجل الأساس', () => setF(blank))}>تسجيل الأساس</Btn>
        <ActionMsg msg={act.msg} />
      </div>
    </div>
  )
}

function DeactivateBasis({ basis }) {
  const act = useAction()
  const [reason, setReason] = useState('')
  if (!basis.is_active) return <span className="text-xs text-gray-400">موقوف</span>
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <input value={reason} onChange={e => setReason(e.target.value)} placeholder="السبب" className={`${INPUT} w-32`} />
      <Btn disabled={act.pending || !reason.trim()} onClick={() => act.run(() => taxInvoicingApi.deactivateBasis(basis.id, reason), 'أُوقف')}>إيقاف</Btn>
      <ActionMsg msg={act.msg} />
    </span>
  )
}

function Bases({ me }) {
  const { data, isLoading, error } = useQuery({ queryKey: ['tax-invoicing', 'bases'], queryFn: () => taxInvoicingApi.bases().then(r => r.data) })
  return (
    <Section title="الأسس الموثقة" hint="لا يُقبل استبعاد بند أو عدم استحقاق ضريبة بدون أساس موثق ساري. لا يوجد أساس جاهز مسبقاً." data-tour="tax-invoicing-main-settings-bases">
      {me.can_finalize && <BasisForm />}
      {isLoading ? <Loading /> : error ? <Failed error={error} /> : (
        <Grid rows={data} empty="لم يُسجل أي أساس بعد، فكل طلبات الاستبعاد تبقى موقوفة" columns={[
          { key: 'kind', label: 'النوع', value: b => (b.kind === 'zero_vat' ? 'عدم استحقاق ضريبة' : 'استبعاد بند'), render: b => (b.kind === 'zero_vat' ? 'عدم استحقاق ضريبة' : 'استبعاد بند') },
          { key: 'reference_number', label: 'المرجع' },
          { key: 'title', label: 'العنوان' },
          { key: 'issued_by', label: 'جهة الإصدار' },
          { key: 'applies_to', label: 'نطاق التطبيق', className: 'max-w-[260px]' },
          { key: 'created_at', label: 'سجله', type: 'date', render: b => <>{b.created_by}<div className="text-[11px] text-gray-400">{fmtTime(b.created_at)}</div></> },
          ...(me.can_finalize ? [{ key: 'off', label: '', sortable: false, render: b => <DeactivateBasis basis={b} /> }] : []),
        ]} />
      )}
    </Section>
  )
}

function Signing() {
  const act = useAction()
  const { data: s, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'signing'],
    queryFn: () => taxInvoicingApi.signingStatus().then(r => r.data),
    // the agent on the workstation answers on its own time
    refetchInterval: q => (q.state.data?.pending_jobs ? 4000 : false),
  })
  const c = s?.certification
  return (
    <Section title="التوقيع الإلكتروني" hint="حالة الختم على جهاز التوقيع." data-tour="tax-invoicing-main-settings-signing"
      actions={(
        <Btn disabled={act.pending} data-tour="tax-invoicing-main-settings-smoke"
          onClick={() => act.run(() => taxInvoicingApi.signingSmokeTest(), d => `طُلب الاختبار رقم ${d.job_id}، بانتظار جهاز التوقيع`)}>
          اختبار الختم
        </Btn>
      )}>
      {isLoading ? <Loading /> : error ? <Failed error={error} /> : (
        <div className="space-y-2 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={s.ready_for_live ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-amber-50 text-amber-800 border-amber-200'}>
              {s.ready_for_live ? 'جاهز للتوقيع الفعلي' : 'غير جاهز للتوقيع الفعلي'}
            </Badge>
            <span className="text-xs text-gray-500">جهاز التوقيع: {s.agent_configured ? 'مضبوط' : 'غير مضبوط'}</span>
            <span className="text-xs text-gray-500">طلبات منتظرة: {s.pending_jobs}</span>
            {s.is_mock && <Badge>توقيع تجريبي</Badge>}
          </div>
          {s.why_not && <Notice tone="amber">{s.why_not}</Notice>}
          {c ? (
            <div className="text-xs text-gray-700 space-y-0.5">
              <div>آخر اختبار: <b className={c.passed ? 'text-emerald-700' : 'text-red-700'}>{c.passed ? 'نجح' : 'فشل'}</b> · {fmtTime(c.created_at)}{c.requested_by ? ` · ${c.requested_by}` : ''}</div>
              {c.subject && <div dir="ltr" className="text-right">{c.subject}</div>}
              {c.not_after && <div>الشهادة سارية حتى {fmtDate(c.not_after)}</div>}
              {c.detail && <div>{c.detail}</div>}
            </div>
          ) : <p className="text-xs text-gray-500">لم يُجرَ اختبار على الختم بعد.</p>}
          <ActionMsg msg={act.msg} />
        </div>
      )}
    </Section>
  )
}

export default function SettingsTab({ me }) {
  const issuer = useQuery({ queryKey: ['tax-invoicing', 'issuer'], queryFn: () => taxInvoicingApi.issuer().then(r => r.data) })
  return (
    <div className="space-y-3">
      {issuer.isLoading ? <Loading /> : issuer.error ? <Failed error={issuer.error} /> : (
        <IssuerForm key={JSON.stringify(issuer.data)} issuer={issuer.data} me={me} />
      )}
      <Buyers me={me} />
      <Bases me={me} />
      {me.can_finalize && <Signing />}
    </div>
  )
}
