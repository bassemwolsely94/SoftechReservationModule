/**
 * Item mapping. Three independent questions, each saved on its own: ETA coding (`edit`), VAT
 * classification (`approve`) and invoice disposition (`approve`). The list status is an input to the
 * accountant's decision and never removes a line by itself.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { ActionMsg, Badge, Btn, Failed, Field, fmtTime, Grid, INPUT, Loading, Section, useAction } from './ui'

const CODING = [['approved', 'كود معتمد'], ['missing', 'بدون كود'], ['pending', 'قيد الاعتماد'], ['rejected', 'كود مرفوض']]
const TREATMENT = [['taxable', 'خاضع'], ['exempt', 'معفى'], ['zero_rated', 'نسبة صفر'], ['unclassified', 'غير مصنف']]
const DISPOSITION = [['include', 'يُدرج في الفاتورة'], ['review', 'يحتاج مراجعة المحاسب'], ['exclusion', 'طلب استبعاد لكل بند']]
const LIST = [['none', 'غير مدرج'], ['white', 'القائمة البيضاء'], ['black', 'القائمة السوداء']]
const CODING_TONE = { approved: 'bg-emerald-50 text-emerald-700 border-emerald-200', missing: 'bg-red-50 text-red-700 border-red-200',
                      pending: 'bg-amber-50 text-amber-800 border-amber-200', rejected: 'bg-red-50 text-red-700 border-red-200' }
const options = rows => rows.map(([k, l]) => <option key={k} value={k}>{l}</option>)

function Column({ title, who, can, children, onSave, pending, saveLabel = 'حفظ', ...rest }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-2" {...rest}>
      <div className="font-bold text-sm text-gray-900">{title}</div>
      {children}
      {can
        ? <Btn variant="primary" disabled={pending} onClick={onSave}>{saveLabel}</Btn>
        : <p className="text-[11px] text-gray-500">{who}</p>}
    </div>
  )
}

function ItemEditor({ item, isNew, me, onCreated }) {
  const act = useAction()
  const [coding, setCoding] = useState({
    code_type: item.code_type || '', eta_code: item.eta_code || '', coding_status: item.coding_status || 'missing',
    unit_type: item.unit_type || '', list_status: item.list_status || 'none', listed_reason: item.listed_reason || '',
  })
  const [vat, setVat] = useState({
    tax_treatment: item.tax_treatment || 'unclassified', vat_rate: item.vat_rate ?? '0', treatment_reference: item.treatment_reference || '',
  })
  const [disposition, setDisposition] = useState(item.disposition || 'include')
  const setC = (k, v) => setCoding(p => ({ ...p, [k]: v }))
  const setV = (k, v) => setVat(p => ({ ...p, [k]: v }))
  const save = (fields, ok) => act.run(
    () => (isNew ? taxInvoicingApi.createItem({ itemcode: item.itemcode, ...fields }) : taxInvoicingApi.updateItem(item.id, fields)),
    d => `${ok}${d.revalidated_drafts ? ` · أُعيد فحص ${d.revalidated_drafts} مسودة` : ''}`,
    d => { if (isNew) onCreated?.(d) },
  )
  return (
    <div className="space-y-2">
    <div className="grid gap-3 md:grid-cols-3">
      <Column title="ترميز المصلحة" can={me.can_edit} who="الترميز لمن يملك صلاحية التعديل."
        pending={act.pending} onSave={() => save(coding, 'حُفظ الترميز')} data-tour="tax-invoicing-main-items-coding">
        <div className="grid grid-cols-2 gap-2">
          <Field label="نوع الكود">
            <select value={coding.code_type} disabled={!me.can_edit} onChange={e => setC('code_type', e.target.value)} className={INPUT}>
              <option value="">—</option><option value="EGS">EGS</option><option value="GS1">GS1</option>
            </select>
          </Field>
          <Field label="الحالة">
            <select value={coding.coding_status} disabled={!me.can_edit} onChange={e => setC('coding_status', e.target.value)} className={INPUT}>{options(CODING)}</select>
          </Field>
        </div>
        <Field label="كود المصلحة">
          <input dir="ltr" value={coding.eta_code} disabled={!me.can_edit} onChange={e => setC('eta_code', e.target.value)} className={INPUT} />
        </Field>
        <Field label="الوحدة">
          <input dir="ltr" value={coding.unit_type} disabled={!me.can_edit} onChange={e => setC('unit_type', e.target.value)} className={INPUT} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="القائمة">
            <select value={coding.list_status} disabled={!me.can_edit} onChange={e => setC('list_status', e.target.value)} className={INPUT}>{options(LIST)}</select>
          </Field>
          <Field label="سبب القائمة">
            <input value={coding.listed_reason} disabled={!me.can_edit} onChange={e => setC('listed_reason', e.target.value)} className={INPUT} />
          </Field>
        </div>
      </Column>

      <Column title="التصنيف الضريبي" can={me.can_approve} who="التصنيف الضريبي قرار المحاسب."
        pending={act.pending} onSave={() => save(vat, 'حُفظ التصنيف')} data-tour="tax-invoicing-main-items-vat">
        <Field label="المعاملة">
          <select value={vat.tax_treatment} disabled={!me.can_approve} onChange={e => setV('tax_treatment', e.target.value)} className={INPUT}>{options(TREATMENT)}</select>
        </Field>
        <Field label="نسبة الضريبة %">
          <input type="number" min="0" max="100" step="0.01" value={vat.vat_rate} disabled={!me.can_approve} onChange={e => setV('vat_rate', e.target.value)} className={INPUT} />
        </Field>
        <Field label="المرجع" hint="مطلوب للمعفى والنسبة الصفرية.">
          <input value={vat.treatment_reference} disabled={!me.can_approve} onChange={e => setV('treatment_reference', e.target.value)} className={INPUT} />
        </Field>
        {item.source_vat_code || item.source_vat_rate != null ? (
          <p className="text-[11px] text-gray-500">
            في الملف، للمراجعة فقط: كود {item.source_vat_code || '—'} · نسبة {item.source_vat_rate != null ? `${Number(item.source_vat_rate)}%` : '—'}
          </p>
        ) : null}
        <p className="text-[11px] text-gray-500">
          {item.treatment_confirmed_at ? `أكده ${item.treatment_confirmed_by || '—'} · ${fmtTime(item.treatment_confirmed_at)}` : 'لم يؤكده المحاسب بعد'}
        </p>
      </Column>

      <Column title="قرار الإدراج في الفاتورة" can={me.can_approve} who="قرار الإدراج للمحاسب."
        pending={act.pending} onSave={() => save({ disposition }, 'حُفظ القرار')} data-tour="tax-invoicing-main-items-disposition">
        <Field label="القرار">
          <select value={disposition} disabled={!me.can_approve} onChange={e => setDisposition(e.target.value)} className={INPUT}>{options(DISPOSITION)}</select>
        </Field>
        <p className="text-[11px] text-gray-500">القائمة السوداء تحول الصنف للمراجعة ولا تحذف أي بند من تلقاء نفسها.</p>
      </Column>
    </div>
    <ActionMsg msg={act.msg} />
    </div>
  )
}

function ConfirmVat({ rows }) {
  const act = useAction()
  // Suggestions from the items on screen; the server applies the code to every unconfirmed item.
  const codes = [...new Set(rows.filter(r => !r.treatment_confirmed_at && r.source_vat_code).map(r => r.source_vat_code))]
  const [f, setF] = useState({ vat_code: '', tax_treatment: 'taxable', treatment_reference: '' })
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  return (
    <Section title="تأكيد الضريبة بكود الضريبة" hint="يؤكد المعاملة لكل الأصناف التي يحمل ملفها هذا الكود ولم تُؤكد بعد." data-tour="tax-invoicing-main-items-confirm-vat">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="كود الضريبة في الملف">
          <input dir="ltr" list="tax-vat-codes" value={f.vat_code} onChange={e => set('vat_code', e.target.value)} className={INPUT} />
          <datalist id="tax-vat-codes">{codes.map(c => <option key={c} value={c} />)}</datalist>
        </Field>
        <Field label="المعاملة">
          <select value={f.tax_treatment} onChange={e => set('tax_treatment', e.target.value)} className={INPUT}>
            {options(TREATMENT.filter(([k]) => k !== 'unclassified'))}
          </select>
        </Field>
        <Field label="المرجع" className="grow min-w-[220px]">
          <input value={f.treatment_reference} onChange={e => set('treatment_reference', e.target.value)} className={INPUT} />
        </Field>
        <Btn variant="primary" disabled={act.pending || !f.vat_code.trim() || !f.treatment_reference.trim()}
          onClick={() => act.run(() => taxInvoicingApi.confirmVat(f), d => `تم تأكيد ${d.confirmed} صنف`)}>
          تأكيد
        </Btn>
      </div>
      <div className="mt-2"><ActionMsg msg={act.msg} /></div>
    </Section>
  )
}

export default function ItemsTab({ me, initialQ = '', newCode = '', go }) {
  const [f, setF] = useState({ q: initialQ, coding_status: '', treatment: '', list: '', disposition: '' })
  const [open, setOpen] = useState(null)
  const [code, setCode] = useState(newCode)
  const [adding, setAdding] = useState(newCode)
  const set = (k, v) => setF(p => ({ ...p, [k]: v }))
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v.trim()))
  const { data, isLoading, error } = useQuery({
    queryKey: ['tax-invoicing', 'items', params],
    queryFn: () => taxInvoicingApi.items(params).then(r => r.data),
    placeholderData: prev => prev,
  })
  const columns = [
    { key: 'itemcode', label: 'الكود', className: 'whitespace-nowrap' },
    { key: 'item_name', label: 'الصنف', render: r => r.item_name || '—', className: 'max-w-[240px] truncate' },
    { key: 'coding', label: 'ترميز المصلحة', value: r => r.coding_status_label, render: r => (
      <><Badge tone={CODING_TONE[r.coding_status]}>{r.coding_status_label}</Badge>
        <div dir="ltr" className="text-[11px] text-gray-500 mt-0.5 text-right">{[r.code_type, r.eta_code].filter(Boolean).join(' ') || '—'}</div></>) },
    { key: 'vat', label: 'التصنيف الضريبي', value: r => r.tax_treatment_label, render: r => (
      <>{r.tax_treatment_label}{r.tax_treatment === 'taxable' && ` ${Number(r.vat_rate)}%`}
        <div className="text-[11px] text-gray-500">
          {r.treatment_confirmed_at ? 'مؤكد' : 'غير مؤكد'}{r.source_vat_code ? ` · كود الملف ${r.source_vat_code}` : ''}
        </div></>) },
    { key: 'disposition_label', label: 'قرار الإدراج' },
    { key: 'list_status_label', label: 'القائمة', render: r => (
      <>{r.list_status_label}{r.listed_reason && <div className="text-[11px] text-gray-500 max-w-[180px] truncate">{r.listed_reason}</div>}</>) },
  ]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2" data-tour="tax-invoicing-main-items-filters">
        <Field label="بحث" className="grow min-w-[200px]">
          <input value={f.q} onChange={e => set('q', e.target.value)} placeholder="كود، اسم، أو كود المصلحة…" className={INPUT} />
        </Field>
        <Field label="الترميز">
          <select value={f.coding_status} onChange={e => set('coding_status', e.target.value)} className={INPUT}><option value="">الكل</option>{options(CODING)}</select>
        </Field>
        <Field label="المعاملة">
          <select value={f.treatment} onChange={e => set('treatment', e.target.value)} className={INPUT}><option value="">الكل</option>{options(TREATMENT)}</select>
        </Field>
        <Field label="القائمة">
          <select value={f.list} onChange={e => set('list', e.target.value)} className={INPUT}><option value="">الكل</option>{options(LIST)}</select>
        </Field>
        <Field label="القرار">
          <select value={f.disposition} onChange={e => set('disposition', e.target.value)} className={INPUT}><option value="">الكل</option>{options(DISPOSITION)}</select>
        </Field>
        {me.can_edit && (
          <Field label="صنف غير مسجل">
            <span className="flex gap-1">
              <input dir="ltr" value={code} onChange={e => setCode(e.target.value)} placeholder="كود الصنف" className={`${INPUT} w-28`} />
              <Btn disabled={!code.trim()} onClick={() => setAdding(code.trim())}>＋ إضافة</Btn>
            </span>
          </Field>
        )}
      </div>

      {adding && (
        <Section title={`صنف جديد: ${adding}`} actions={<Btn onClick={() => setAdding('')}>إغلاق</Btn>}>
          <ItemEditor key={adding} item={{ itemcode: adding }} isNew me={me}
            onCreated={d => { setAdding(''); setCode(''); go('items', { q: d.itemcode }) }} />
        </Section>
      )}

      {isLoading ? <Loading /> : error ? <Failed error={error} /> : (
        <Grid columns={columns} rows={data} data-tour="tax-invoicing-main-items-grid" empty="لا توجد أصناف بهذه الفلاتر"
          onOpen={r => setOpen(o => (o === r.id ? null : r.id))} openKey={open}
          renderOpen={r => <ItemEditor key={r.id} item={r} me={me} />} />
      )}

      {me.can_approve && <ConfirmVat rows={data || []} />}
    </div>
  )
}
