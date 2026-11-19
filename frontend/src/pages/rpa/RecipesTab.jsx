/**
 * RecipesTab — الوصفات (admin only): the recorded SOFTECH screen recipes. A draft recipe is
 * uploaded from a .dld recording with its field map; an admin completes the DRAFT inline (cancel
 * keys, popup rules, checklist, reference cells — a .dld carries none of them) and a SECOND admin
 * approves it (four-eyes, enforced by the server: neither the importer nor anyone who ever edited it
 * may approve — «آخر من عدّلها» shows the latest editor; it also refuses a recipe that cannot end a
 * dry run safely). Approved content is frozen; this screen never edits it. The screen switch only
 * enables or stops the robot for the screen; live entry cannot be turned on in Stage 1.
 */
import { Fragment, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { rpaApi } from '../../api/client'
import useSortableRows from '../../hooks/useSortableRows'
import SortTh from '../../components/SortTh'
import { Badge, RECIPE_STATUS, SCREEN_LABEL, asList, errText, fmtTime } from './shared.jsx'

const recValue = (r, k) => (k === 'status' ? (RECIPE_STATUS[r.status]?.label || r.status) : r[k])
const keysText = cells => asList(cells).filter(c => c?.kind === 'keys').map(c => c.value).join('')
const keysCell = text => (text.trim() ? [{ kind: 'keys', value: text.trim() }] : [])

function refParts(cells) {
  const list = asList(cells)
  const at = list.findIndex(c => c?.kind === 'field')
  if (at < 0) return { on: false, before: '', after: '' }
  return { on: true, before: keysText(list.slice(0, at)), after: keysText(list.slice(at + 1)) }
}

function ScreenSwitch() {
  const qc = useQueryClient()
  const [err, setErr] = useState('')
  const q = useQuery({ queryKey: ['rpa', 'status'], queryFn: () => rpaApi.status().then(r => r.data) })
  const screen = (q.data?.screens || []).find(s => s.key === 'issue_125')
  const toggle = useMutation({
    mutationFn: enabled => rpaApi.setScreen('issue_125', enabled),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa'] }) },
    onError: e => setErr(errText(e)),
  })
  if (!screen) return null
  return (
    <div className="card p-3 flex flex-wrap items-center gap-3 text-sm">
      <span className="font-semibold">{screen.title_ar || SCREEN_LABEL.issue_125}</span>
      <span className={screen.enabled ? 'text-green-700 dark:text-green-300' : 'text-muted'}>
        {screen.enabled ? 'الروبوت يستلم مستنداتها (تجربة بدون حفظ)' : 'موقوفة: لا يستلم الروبوت مستنداتها'}
      </span>
      <button type="button" className="btn-secondary text-sm ms-auto" disabled={toggle.isPending}
              onClick={() => toggle.mutate(!screen.enabled)}>
        {toggle.isPending ? 'جارٍ الحفظ…' : (screen.enabled ? 'إيقاف الشاشة' : 'تفعيل الشاشة')}
      </button>
      {err && <span className="w-full text-xs text-red-600">{err}</span>}
    </div>
  )
}

function DraftEditor({ recipe, onDone }) {
  const qc = useQueryClient()
  const ref0 = refParts(recipe.ref_cells)
  const [cancelKeys, setCancelKeys] = useState(keysText(recipe.cancel_keys))
  const [checklist, setChecklist] = useState(asList(recipe.header_checklist).join('\n'))
  const [refOn, setRefOn] = useState(ref0.on)
  const [refBefore, setRefBefore] = useState(ref0.before)
  const [refAfter, setRefAfter] = useState(ref0.after)
  const [popups, setPopups] = useState(asList(recipe.popups).map(p => ({
    title_contains: p.title_contains || '', text_contains: p.text_contains || '', answer_keys: p.answer_keys || '' })))
  const [err, setErr] = useState('')
  const setPopup = (i, k, v) => setPopups(ps => ps.map((p, j) => (j === i ? { ...p, [k]: v } : p)))

  const save = useMutation({
    mutationFn: () => rpaApi.editRecipe(recipe.id, {
      cancel_keys: keysCell(cancelKeys),
      header_checklist: checklist.split('\n').map(t => t.trim()).filter(Boolean),
      ref_cells: refOn ? [...keysCell(refBefore), { kind: 'field', value: 'reference' }, ...keysCell(refAfter)] : [],
      popups: popups.filter(p => p.title_contains.trim() || p.text_contains.trim() || p.answer_keys.trim()),
    }),
    onSuccess: () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa'] }); onDone() },
    onError: e => setErr(errText(e)),
  })

  const id = `rpa-recipe-${recipe.id}`
  return (
    <div className="space-y-3 p-3 bg-surface-2 rounded-lg text-sm">
      <div className="text-xs text-muted">
        المفاتيح الخاصة بصيغة DataLoad: <span dir="ltr" className="font-mono">{'\\{ESC}'}</span>،{' '}
        <span dir="ltr" className="font-mono">{'\\{TAB}'}</span>، <span dir="ltr" className="font-mono">{'\\{ENTER}'}</span>.
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <label className="label" htmlFor={`${id}-cancel`}>مفاتيح الإلغاء بدون حفظ (مطلوبة)</label>
          <input id={`${id}-cancel`} className="input-field w-full font-mono" dir="ltr" value={cancelKeys}
                 onChange={e => setCancelKeys(e.target.value)} placeholder="\{ESC}" />
        </div>
        <div>
          <label className="label" htmlFor={`${id}-check`}>قائمة المراجعة قبل البدء (سطر لكل بند)</label>
          <textarea id={`${id}-check`} className="input-field w-full" rows={3} value={checklist}
                    onChange={e => setChecklist(e.target.value)} />
        </div>
      </div>
      <div className="space-y-1">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={refOn} onChange={e => setRefOn(e.target.checked)} />
          يكتب الروبوت المرجع RPA-رقم المستند في خانة الملاحظات
        </label>
        {refOn && (
          <div className="grid gap-2 md:grid-cols-2">
            <input aria-label="مفاتيح قبل المرجع" className="input-field font-mono" dir="ltr" value={refBefore}
                   onChange={e => setRefBefore(e.target.value)} placeholder="مفاتيح قبل المرجع" />
            <input aria-label="مفاتيح بعد المرجع" className="input-field font-mono" dir="ltr" value={refAfter}
                   onChange={e => setRefAfter(e.target.value)} placeholder="مفاتيح بعد المرجع" />
          </div>
        )}
      </div>
      <div className="space-y-1">
        <div className="label">النوافذ المنبثقة المعروفة (جزء من العنوان أو النص، ومفاتيح الرد)</div>
        {popups.map((p, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2">
            <input aria-label="العنوان يحتوي" className="input-field w-40" value={p.title_contains}
                   onChange={e => setPopup(i, 'title_contains', e.target.value)} placeholder="العنوان يحتوي" />
            <input aria-label="النص يحتوي" className="input-field w-48" value={p.text_contains}
                   onChange={e => setPopup(i, 'text_contains', e.target.value)} placeholder="النص يحتوي" />
            <input aria-label="مفاتيح الرد" className="input-field w-32 font-mono" dir="ltr" value={p.answer_keys}
                   onChange={e => setPopup(i, 'answer_keys', e.target.value)} placeholder="\{ENTER}" />
            <button type="button" className="btn-ghost text-xs" onClick={() => setPopups(ps => ps.filter((_, j) => j !== i))}>حذف</button>
          </div>
        ))}
        <button type="button" className="btn-ghost text-xs"
                onClick={() => setPopups(ps => [...ps, { title_contains: '', text_contains: '', answer_keys: '' }])}>
          + نافذة منبثقة
        </button>
      </div>
      <div className="flex items-center gap-2">
        <button type="button" className="btn-primary text-sm" disabled={!cancelKeys.trim() || save.isPending}
                onClick={() => save.mutate()}>
          {save.isPending ? 'جارٍ الحفظ…' : 'حفظ المسودة'}
        </button>
        <button type="button" className="btn-ghost text-sm" onClick={onDone}>إغلاق</button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    </div>
  )
}

export default function RecipesTab() {
  const qc = useQueryClient()
  const [file, setFile] = useState(null)
  const [fieldMap, setFieldMap] = useState('')
  const [err, setErr] = useState('')
  const [editing, setEditing] = useState(null)
  const q = useQuery({ queryKey: ['rpa', 'recipes'], queryFn: () => rpaApi.recipes().then(r => r.data) })
  const rows = useMemo(() => asList(q.data), [q.data])
  const { sorted, headerProps } = useSortableRows(rows, { getValue: recValue, persistKey: 'rpa-recipes' })
  const refresh = () => { setErr(''); qc.invalidateQueries({ queryKey: ['rpa'] }) }

  const create = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('screen', 'issue_125')
      fd.append('file', file)
      fd.append('field_map', fieldMap.trim())
      return rpaApi.createRecipe(fd)
    },
    onSuccess: () => { setFile(null); setFieldMap(''); refresh() },
    onError: e => setErr(errText(e)),
  })
  const approve = useMutation({ mutationFn: id => rpaApi.approveRecipe(id), onSuccess: refresh, onError: e => setErr(errText(e)) })

  return (
    <div className="space-y-4">
      <ScreenSwitch />

      <div className="card p-4 space-y-3 max-w-2xl">
        <h2 className="font-bold text-sm">رفع وصفة جديدة ({SCREEN_LABEL.issue_125})</h2>
        <div>
          <label className="label" htmlFor="rpa-dld">ملف التسجيل (.dld)</label>
          <input id="rpa-dld" type="file" accept=".dld" className="block text-sm" onChange={e => setFile(e.target.files?.[0] || null)} />
        </div>
        <div>
          <label className="label" htmlFor="rpa-fieldmap">خريطة الحقول (JSON)</label>
          <textarea id="rpa-fieldmap" className="input-field w-full font-mono text-xs" dir="ltr" rows={4}
                    placeholder='["itemcode", "qty", "expiry"]'
                    value={fieldMap} onChange={e => setFieldMap(e.target.value)} />
        </div>
        <button type="button" className="btn-primary text-sm" disabled={!file || !fieldMap.trim() || create.isPending}
                onClick={() => create.mutate()}>
          {create.isPending ? 'جارٍ الرفع…' : 'رفع كمسودة'}
        </button>
        {err && <div className="text-sm text-red-600">{err}</div>}
      </div>

      <div data-tour="rpa-main-recipes" className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted border-b border-line">
              <SortTh {...headerProps('screen_title')} className="p-2 text-start">الشاشة</SortTh>
              <SortTh {...headerProps('version', 'number')} className="p-2 text-start">الإصدار</SortTh>
              <SortTh {...headerProps('status')} className="p-2 text-start">الحالة</SortTh>
              <SortTh {...headerProps('source_filename')} className="p-2 text-start">الملف</SortTh>
              <SortTh {...headerProps('created_by_name')} className="p-2 text-start">رفعها</SortTh>
              <SortTh {...headerProps('edited_by_name')} className="p-2 text-start">آخر من عدّلها</SortTh>
              <SortTh {...headerProps('approved_by_name')} className="p-2 text-start">اعتمدها</SortTh>
              <SortTh {...headerProps('approved_at', 'date')} className="p-2 text-start">وقت الاعتماد</SortTh>
              <th className="p-2" />
            </tr>
          </thead>
          <tbody>
            {sorted.map(r => (
              <Fragment key={r.id}>
                <tr className="border-b border-line">
                  <td className="p-2">{r.screen_title || SCREEN_LABEL[r.screen_key || r.screen] || '—'}</td>
                  <td className="p-2 tabular-nums">v{r.version}</td>
                  <td className="p-2"><Badge map={RECIPE_STATUS} value={r.status} /></td>
                  <td className="p-2 text-muted" dir="ltr">{r.source_filename || '—'}</td>
                  <td className="p-2">{r.created_by_name || '—'}</td>
                  <td className="p-2" title={r.edited_at ? fmtTime(r.edited_at) : undefined}>{r.edited_by_name || '—'}</td>
                  <td className="p-2">{r.approved_by_name || '—'}</td>
                  <td className="p-2 text-xs whitespace-nowrap">{fmtTime(r.approved_at)}</td>
                  <td className="p-2 text-end whitespace-nowrap">
                    {r.status === 'draft' && (
                      <div className="flex justify-end gap-2">
                        <button type="button" className="btn-ghost text-sm"
                                onClick={() => setEditing(editing === r.id ? null : r.id)}>
                          {editing === r.id ? 'إغلاق' : 'إكمال المسودة'}
                        </button>
                        <button type="button" className="btn-secondary text-sm" disabled={approve.isPending} onClick={() => approve.mutate(r.id)}>
                          اعتماد الوصفة
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
                {editing === r.id && r.status === 'draft' && (
                  <tr className="border-b border-line">
                    <td colSpan={9} className="p-2"><DraftEditor recipe={r} onDone={() => setEditing(null)} /></td>
                  </tr>
                )}
              </Fragment>
            ))}
            {q.isLoading && <tr><td colSpan={9} className="p-6 text-center text-muted">جارٍ التحميل…</td></tr>}
            {q.isError && <tr><td colSpan={9} className="p-6 text-center text-red-600">تعذّر تحميل الوصفات.</td></tr>}
            {!q.isLoading && !q.isError && !rows.length && <tr><td colSpan={9} className="p-6 text-center text-muted">لا توجد وصفات.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}
