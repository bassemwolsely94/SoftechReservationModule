/**
 * Coded-items workbook, loaded through an explicit column mapping: nothing is guessed from header
 * names and no column starts selected. Steps: inspect (real headers) → map → preview (dry run, writes
 * nothing) → apply. Apply sends the hash the preview returned, so what is applied is what was
 * reviewed; any change to the file or the mapping drops the preview here too.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { taxInvoicingApi } from '../../api/client'
import { Btn, errText, Field, fmtInt, Grid, INPUT, Notice, Section } from './ui'

const COUNT_LABELS = [
  ['rows', 'صفوف'], ['valid', 'صالحة'], ['errors', 'أخطاء'], ['warnings', 'تحذيرات'], ['new', 'جديد'], ['updated', 'تحديث'],
  ['conflicts', 'تعارضات'], ['duplicates', 'مكررات'], ['coded', 'مرمز'], ['not_coded', 'غير مرمز'], ['black', 'أسود'], ['white', 'أبيض'], ['unlisted', 'غير مدرج'],
]
const ISSUE_LABELS = {
  no_itemcode: 'بدون كود صنف', long_itemcode: 'كود صنف طويل', duplicate_item: 'كود صنف مكرر', duplicate_eta_code: 'كود مصلحة مكرر',
  long_eta_code: 'كود مصلحة طويل', bad_code_type: 'نوع كود غير معروف', egs_format: 'صيغة EGS', code_mismatch: 'الكود لا يطابق الصنف',
  not_in_catalog: 'ليس في الكتالوج', numeric_code: 'كود مخزن كرقم', numeric_itemcode: 'كود صنف رقمي', bad_list_flag: 'قيمة قائمة غير معروفة',
  bad_date: 'تاريخ غير صحيح', bad_vat: 'نسبة ضريبة غير صحيحة', code_without_type: 'كود بدون نوع', black_but_coded: 'أسود ومرمز',
  white_not_coded: 'أبيض وغير مرمز', no_gpc: 'بدون GPC', conflict: 'تعارض مع المسجل',
}
const FIELD_LABELS = { eta_code: 'كود المصلحة', code_type: 'نوع الكود', list_status: 'القائمة', source_vat_code: 'كود الضريبة' }

const columnLetter = i => {
  let n = i + 1
  let out = ''
  while (n > 0) { const m = (n - 1) % 26; out = String.fromCharCode(65 + m) + out; n = Math.floor((n - 1) / 26) }
  return out
}
const splitValues = text => text.split(',').map(v => v.trim()).filter(Boolean)

/** The `options` JSON the server expects. Exported for the test: only what the user mapped goes out. */
export function buildOptions({ sheet, headerRow, mapping, blackText, whiteText, codedStatus, overwrite }) {
  return {
    sheet, header_row: Number(headerRow) || 1,
    mapping: Object.fromEntries(Object.entries(mapping).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])),
    black_values: splitValues(blackText), white_values: splitValues(whiteText),
    coded_status: codedStatus, overwrite_conflicts: overwrite,
  }
}

const ISSUE_COLUMNS = [
  { key: 'row', label: 'الصف', type: 'number' },
  { key: 'level', label: 'المستوى', render: r => (r.level === 'error' ? <span className="text-red-700 font-bold">خطأ</span> : <span className="text-amber-800">تحذير</span>) },
  { key: 'itemcode', label: 'الصنف', render: r => r.itemcode || '—' },
  { key: 'code', label: 'النوع', value: r => ISSUE_LABELS[r.code] || r.code, render: r => ISSUE_LABELS[r.code] || r.code },
  { key: 'message', label: 'التفاصيل' },
]

export default function ImportTab({ me }) {
  const qc = useQueryClient()
  const [file, setFile] = useState(null)
  const [headerRow, setHeaderRow] = useState(1)
  const [info, setInfo] = useState(null)
  const [sheet, setSheet] = useState('')
  const [mapping, setMapping] = useState({})
  const [blackText, setBlackText] = useState('')
  const [whiteText, setWhiteText] = useState('')
  const [codedStatus, setCodedStatus] = useState('pending')
  const [overwrite, setOverwrite] = useState(false)
  const [preview, setPreview] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const options = buildOptions({ sheet, headerRow, mapping, blackText, whiteText, codedStatus, overwrite })
  // overwrite_conflicts is outside the server's hash: it decides what apply does with the conflicts it listed.
  const signature = JSON.stringify({ ...options, overwrite_conflicts: undefined, file: file?.name, size: file?.size, modified: file?.lastModified })
  const shownPreview = preview?.signature === signature ? preview.data : null
  const sheetInfo = info?.sheets.find(s => s.name === sheet)
  const fields = useMemo(() => Object.entries(info?.fields || {}), [info])

  const inspect = useMutation({
    mutationFn: () => taxInvoicingApi.importInspect(file, headerRow).then(r => r.data),
    onMutate: () => { setError(''); setResult(null) },
    onSuccess: d => { setInfo(d); setSheet(d.sheets.some(s => s.name === sheet) ? sheet : (d.sheets[0]?.name || '')); setMapping({}) },
    onError: e => setError(errText(e)),
  })
  const runPreview = useMutation({
    mutationFn: () => taxInvoicingApi.importPreview(file, options).then(r => r.data),
    onMutate: () => { setError(''); setResult(null) },
    onSuccess: d => setPreview({ signature, data: d }),
    onError: e => setError(errText(e)),
  })
  const apply = useMutation({
    mutationFn: () => taxInvoicingApi.importApply(file, options, shownPreview.preview_hash).then(r => r.data),
    onMutate: () => setError(''),
    onSuccess: d => { setResult(d); setPreview(null); qc.invalidateQueries({ queryKey: ['tax-invoicing'] }) },
    onError: e => setError(errText(e)),
  })

  return (
    <div className="space-y-3">
      <Section title="١. الملف" hint="ملف Excel بصيغة xlsx. الأعمدة تُحدد يدوياً ولا تُستنتج من أسمائها." data-tour="tax-invoicing-main-import-file">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="الملف">
            <input type="file" accept=".xlsx" onChange={e => { setFile(e.target.files?.[0] || null); setInfo(null); setPreview(null); setResult(null); setMapping({}) }} className="text-sm" />
          </Field>
          <Field label="صف العناوين">
            <input type="number" min="1" value={headerRow} onChange={e => { setHeaderRow(e.target.value); setInfo(null) }} className={`${INPUT} w-24`} />
          </Field>
          <Btn variant="primary" disabled={!file || inspect.isPending} onClick={() => inspect.mutate()}>
            {inspect.isPending ? 'جارٍ القراءة…' : 'قراءة الأعمدة'}
          </Btn>
        </div>
      </Section>

      {info && (
        <Section title="٢. ربط الأعمدة" hint="لكل حقل اختر عمود الملف الذي يحمله، أو اتركه فارغاً. كود الصنف مطلوب." data-tour="tax-invoicing-main-import-mapping">
          <div className="flex flex-wrap items-end gap-2 mb-3">
            <Field label="الورقة">
              <select value={sheet} onChange={e => { setSheet(e.target.value); setMapping({}) }} className={INPUT}>
                {info.sheets.map(s => <option key={s.name} value={s.name}>{s.name} ({fmtInt(s.rows)} صف)</option>)}
              </select>
            </Field>
            <Field label="حالة الأكواد المرمزة بعد الاستيراد">
              <select value={codedStatus} onChange={e => setCodedStatus(e.target.value)} className={INPUT}>
                <option value="pending">قيد الاعتماد</option>
                <option value="approved">معتمد</option>
              </select>
            </Field>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {fields.map(([key, label]) => {
              const picked = mapping[key] ?? ''
              const col = picked === '' ? null : sheetInfo?.columns.find(c => c.index === Number(picked))
              return (
                <Field key={key} label={label} hint={col?.samples?.length ? `مثال: ${col.samples.filter(Boolean).slice(0, 2).join(' · ') || '—'}` : ''}>
                  <select value={picked} aria-label={label} onChange={e => setMapping(m => ({ ...m, [key]: e.target.value }))} className={INPUT}>
                    <option value="">— غير مربوط —</option>
                    {(sheetInfo?.columns || []).map(c => (
                      <option key={c.index} value={c.index}>{columnLetter(c.index)}: {c.header || '(بدون عنوان)'}</option>
                    ))}
                  </select>
                </Field>
              )
            })}
          </div>
          {mapping.list_flag !== undefined && mapping.list_flag !== '' && (
            <div className="grid gap-2 sm:grid-cols-2 mt-3">
              <Field label="قيم تعني القائمة السوداء" hint="افصل بفاصلة، بالنص كما في الملف.">
                <input value={blackText} onChange={e => setBlackText(e.target.value)} className={INPUT} />
              </Field>
              <Field label="قيم تعني القائمة البيضاء" hint="أي قيمة أخرى تظهر خطأً في المعاينة.">
                <input value={whiteText} onChange={e => setWhiteText(e.target.value)} className={INPUT} />
              </Field>
            </div>
          )}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Btn variant="primary" disabled={runPreview.isPending || mapping.itemcode === undefined || mapping.itemcode === ''} onClick={() => runPreview.mutate()} data-tour="tax-invoicing-main-import-preview">
              {runPreview.isPending ? 'جارٍ الفحص…' : 'معاينة بدون حفظ'}
            </Btn>
            {preview && !shownPreview && <span className="text-xs text-amber-800">تغير الربط بعد المعاينة، أعد المعاينة.</span>}
          </div>
        </Section>
      )}

      {error && <Notice tone="red">{error}</Notice>}

      {shownPreview && (
        <Section title="٣. نتيجة المعاينة" hint="لم يُكتب شيء بعد.">
          <div className="flex flex-wrap gap-x-5 gap-y-2 mb-3">
            {COUNT_LABELS.map(([k, l]) => (
              <div key={k} className="min-w-[64px]">
                <div className="text-[11px] text-gray-500">{l}</div>
                <div className={`font-bold ${k === 'errors' && shownPreview.counts[k] ? 'text-red-700' : k === 'conflicts' && shownPreview.counts[k] ? 'text-amber-800' : 'text-gray-900'}`}>{fmtInt(shownPreview.counts[k])}</div>
              </div>
            ))}
          </div>
          {Object.keys(shownPreview.issue_counts).length > 0 && (
            <div className="flex flex-wrap gap-1 mb-3">
              {Object.entries(shownPreview.issue_counts).map(([k, n]) => (
                <span key={k} className="px-2 py-0.5 rounded-full border border-gray-200 text-[11px] text-gray-700">{ISSUE_LABELS[k] || k}: {fmtInt(n)}</span>
              ))}
            </div>
          )}
          {shownPreview.issues_truncated && <p className="text-xs text-amber-800 mb-2">عُرض جزء من الملاحظات الكثيرة من كل نوع؛ الأعداد أعلاه كاملة.</p>}
          <Grid columns={ISSUE_COLUMNS} rows={shownPreview.issues} getKey={r => `${r.row}|${r.code}|${r.message}`} empty="✅ لا توجد ملاحظات على الصفوف" />

          {shownPreview.sample.some(r => r.conflicts?.length) && (
            <div className="mt-3">
              <div className="text-sm font-bold text-gray-800 mb-1">تعارضات مع المسجل (من أول 25 صفاً)</div>
              <Grid getKey={r => `${r.row}|${r.field}`}
                rows={shownPreview.sample.flatMap(r => r.conflicts.map(c => ({ row: r.row, itemcode: r.itemcode, ...c })))}
                columns={[
                  { key: 'row', label: 'الصف', type: 'number' },
                  { key: 'itemcode', label: 'الصنف' },
                  { key: 'field', label: 'الحقل', render: c => FIELD_LABELS[c.field] || c.field },
                  { key: 'current', label: 'المسجل' },
                  { key: 'file', label: 'في الملف' },
                ]} />
            </div>
          )}

          <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap items-center gap-3" data-tour="tax-invoicing-main-import-apply">
            {me.can_approve ? (
              <>
                {shownPreview.counts.conflicts > 0 && (
                  <label className="flex items-center gap-1.5 text-xs text-gray-700">
                    <input type="checkbox" checked={overwrite} onChange={e => setOverwrite(e.target.checked)} />
                    استبدال المسجل في الصفوف المتعارضة ({fmtInt(shownPreview.counts.conflicts)})، وإلا تُترك كما هي
                  </label>
                )}
                <Btn variant="success" disabled={apply.isPending} onClick={() => apply.mutate()}>
                  {apply.isPending ? 'جارٍ الحفظ…' : `اعتماد الاستيراد (${fmtInt(shownPreview.counts.valid)} صف صالح)`}
                </Btn>
              </>
            ) : <span className="text-xs text-gray-500">اعتماد الاستيراد لمن يملك صلاحية المراجعة.</span>}
          </div>
        </Section>
      )}

      {result && (
        <Notice tone="green">
          ✔ كُتب {fmtInt(result.written)} صنف · تُرك {fmtInt(result.conflicts_skipped)} متعارض · أُعيد فحص {fmtInt(result.revalidated_drafts)} مسودة.
          الضريبة في الملف تبقى مدخلاً حتى يؤكدها المحاسب في تبويب الأصناف.
        </Notice>
      )}
    </div>
  )
}
