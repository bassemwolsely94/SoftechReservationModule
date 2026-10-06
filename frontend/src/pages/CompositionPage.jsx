/**
 * CompositionPage.jsx — Active-Ingredient Reconciliation (/composition)
 *
 * Review-and-approve workbench for cleaning SOFTECH's dirty `activeingredients`.
 * Per row you can: expand the linked catalog items, edit/clean the molecule text
 * and keep/drop each component, pick a class (English labels), then approve /
 * reject / mark non-drug. Read + approve only — nothing writes to SOFTECH.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { compositionApi } from '../api/client'

const NON_DRUG = [
  { key: 'cosmetics',        label: 'Cosmetic / مستحضر تجميل' },
  { key: 'medical_supplies', label: 'Medical supply / مستلزم طبي' },
  { key: 'infant_formula',   label: 'Infant formula / لبن أطفال' },
]

const STATUS_META = {
  pending:      { label: 'بانتظار المراجعة', cls: 'bg-amber-100 text-amber-800' },
  needs_review: { label: 'يحتاج مراجعة',      cls: 'bg-orange-100 text-orange-800' },
  approved:     { label: 'معتمد',             cls: 'bg-green-100 text-green-800' },
  rejected:     { label: 'مرفوض',             cls: 'bg-red-100 text-red-700' },
}

const confColor = c => c >= 0.9 ? 'bg-green-100 text-green-700' : c >= 0.7 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700'
const classLabel = c => c.name_ar ? `${c.name} — ${c.name_ar}` : c.name

function Stat({ label, value, tone = '' }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-center">
      <div className={`text-lg font-bold ${tone || 'text-content'}`}>{value}</div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

function LinkedItems({ candId }) {
  const { data = [], isLoading } = useQuery({
    queryKey: ['comp-items', candId],
    queryFn: () => compositionApi.candidateItems(candId).then(r => r.data),
  })
  if (isLoading) return <div className="text-xs text-muted py-1">…</div>
  if (!data.length) return <div className="text-xs text-muted py-1">لا أصناف مرتبطة</div>
  return (
    <div className="mt-2 rounded border border-line bg-bg p-2">
      <div className="text-[11px] text-muted mb-1">الأصناف المرتبطة ({data.length})</div>
      <div className="flex flex-wrap gap-1.5">
        {data.map(it => (
          it.item_id
            ? <Link key={it.softech_id} to={`/products/${it.item_id}`} className="rounded bg-surface border border-line px-2 py-0.5 text-xs text-primary hover:underline">{it.name || it.softech_id}{it.shape ? ` · ${it.shape}` : ''}</Link>
            : <span key={it.softech_id} className="rounded bg-surface border border-line px-2 py-0.5 text-xs text-muted">#{it.softech_id}</span>
        ))}
      </div>
    </div>
  )
}

function ComponentEditor({ initial, onSave, onCancel, saving }) {
  const [rows, setRows] = useState(
    (initial.length ? initial : [{ molecule: '', strength_value: '', strength_unit: '', include: true }])
      .map(c => ({
        molecule: c.molecule || '', salt: c.salt || '',
        strength_value: c.strength_value ?? '', strength_unit: c.strength_unit || '',
        include: c.include !== false,
      }))
  )
  const upd = (i, k, v) => setRows(rs => rs.map((r, j) => j === i ? { ...r, [k]: v } : r))
  return (
    <div className="mt-2 rounded border border-primary bg-bg p-2 space-y-1.5">
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1.5">
          <label className="flex items-center gap-1 text-[11px] text-muted">
            <input type="checkbox" checked={r.include} onChange={e => upd(i, 'include', e.target.checked)} />
            إبقاء
          </label>
          <input value={r.molecule} onChange={e => upd(i, 'molecule', e.target.value.toUpperCase())}
            placeholder="المادة الفعّالة" className="flex-1 min-w-[140px] rounded border border-line bg-surface px-2 py-1 text-xs text-content" />
          <input value={r.strength_value} onChange={e => upd(i, 'strength_value', e.target.value)}
            placeholder="تركيز" type="number" step="any" className="w-16 rounded border border-line bg-surface px-2 py-1 text-xs text-content" />
          <input value={r.strength_unit} onChange={e => upd(i, 'strength_unit', e.target.value)}
            placeholder="وحدة" className="w-16 rounded border border-line bg-surface px-2 py-1 text-xs text-content" />
          <button onClick={() => setRows(rs => rs.filter((_, j) => j !== i))} className="text-red-500 text-xs px-1">✕</button>
        </div>
      ))}
      <div className="flex items-center gap-2 pt-1">
        <button onClick={() => setRows(rs => [...rs, { molecule: '', strength_value: '', strength_unit: '', include: true }])}
          className="text-xs text-primary">+ إضافة مادة</button>
        <div className="flex-1" />
        <button onClick={onCancel} className="rounded border border-line px-2 py-1 text-xs text-muted">إلغاء</button>
        <button onClick={() => onSave(rows)} disabled={saving}
          className="rounded bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50">حفظ</button>
      </div>
    </div>
  )
}

function CandidateRow({ cand, classes, onApprove, onReject, onNonDrug, onSetClass, onEdit, savingEdit }) {
  const [showItems, setShowItems] = useState(false)
  const [editing, setEditing] = useState(false)
  const st = STATUS_META[cand.status] || {}
  const selectedClass = cand.proposed_class || ''
  const comps = cand.parsed_components || []

  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-content">{cand.raw_ainame}</span>
            <span className="text-[11px] text-muted">#{cand.raw_aicode}</span>
            {cand.is_combination && <span className="rounded bg-indigo-100 text-indigo-700 px-1.5 text-[11px]">مركّب</span>}
            {cand.is_non_drug && <span className="rounded bg-gray-200 text-gray-700 px-1.5 text-[11px]">غير دوائي</span>}
            <span className={`rounded px-1.5 text-[11px] ${confColor(cand.confidence)}`}>{Math.round(cand.confidence * 100)}%</span>
            {st.label && <span className={`rounded px-1.5 text-[11px] ${st.cls}`}>{st.label}</span>}
            {cand.item_count > 0 && (
              <button onClick={() => setShowItems(s => !s)} className="text-[11px] text-primary hover:underline">
                {cand.item_count} صنف {showItems ? '▲' : '▼'}
              </button>
            )}
          </div>
          {!editing && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {comps.map((c, i) => (
                <span key={i} className={`rounded-full border px-2 py-0.5 text-xs ${c.include === false ? 'border-line bg-bg text-muted line-through' : 'border-line bg-bg text-content'}`}>
                  {c.molecule}
                  {c.salt ? <span className="text-muted"> ({c.salt})</span> : null}
                  {c.strength_value != null ? <b className="text-primary"> {c.strength_value}{c.strength_unit}</b> : null}
                </span>
              ))}
              {comps.length === 0 && <span className="text-xs text-muted">لا مادة فعّالة مُستخرَجة</span>}
              <button onClick={() => setEditing(true)} className="text-[11px] text-primary hover:underline ms-1">✎ تعديل</button>
            </div>
          )}
          {editing && (
            <ComponentEditor
              initial={comps} saving={savingEdit}
              onCancel={() => setEditing(false)}
              onSave={rows => onEdit(cand.id, rows, () => setEditing(false))}
            />
          )}
          {showItems && <LinkedItems candId={cand.id} />}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <select value={selectedClass || ''} onChange={e => onSetClass(cand.id, e.target.value ? Number(e.target.value) : '')}
            className="rounded border border-line bg-surface px-2 py-1 text-xs text-content max-w-[210px]" title="Class / التصنيف">
            <option value="">— no class / بدون —</option>
            {classes.map(c => <option key={c.id} value={c.id}>{classLabel(c)}</option>)}
          </select>
          <button onClick={() => onApprove(cand.id, selectedClass || undefined)}
            className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700">اعتماد</button>
          <select value="" onChange={e => e.target.value && onNonDrug(cand.id, e.target.value)}
            className="rounded border border-line bg-surface px-2 py-1 text-xs text-muted" title="non-drug">
            <option value="">غير دوائي…</option>
            {NON_DRUG.map(n => <option key={n.key} value={n.key}>{n.label}</option>)}
          </select>
          <button onClick={() => onReject(cand.id)}
            className="rounded border border-red-300 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50">رفض</button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export default function CompositionPage() {
  const qc = useQueryClient()
  const [filters, setFilters] = useState({ status: 'needs_review', q: '', combos: false })
  const [page, setPage] = useState(1)

  const params = { page }
  if (filters.status !== 'all') params.status = filters.status
  if (filters.q) params.q = filters.q
  if (filters.combos) params.combos = 1

  const { data: summary } = useQuery({ queryKey: ['comp-summary'], queryFn: () => compositionApi.summary().then(r => r.data) })
  const { data: classes = [] } = useQuery({ queryKey: ['comp-classes'], queryFn: () => compositionApi.classes().then(r => r.data) })
  const { data: list, isLoading } = useQuery({
    queryKey: ['comp-cands', params],
    queryFn: () => compositionApi.candidates(params).then(r => r.data),
    placeholderData: keepPreviousData,
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['comp-cands'] })
    qc.invalidateQueries({ queryKey: ['comp-summary'] })
  }
  const approveM  = useMutation({ mutationFn: ({ id, classId }) => compositionApi.approve(id, classId), onSuccess: invalidate })
  const rejectM   = useMutation({ mutationFn: (id) => compositionApi.reject(id), onSuccess: invalidate })
  const nonDrugM  = useMutation({ mutationFn: ({ id, key }) => compositionApi.nonDrug(id, key), onSuccess: invalidate })
  const setClassM = useMutation({ mutationFn: ({ id, classId }) => compositionApi.setClass(id, classId), onSuccess: invalidate })
  const editM     = useMutation({ mutationFn: ({ id, components }) => compositionApi.editCandidate(id, components), onSuccess: invalidate })
  const createClassM = useMutation({
    mutationFn: (data) => compositionApi.createClass(data).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['comp-classes'] }),
  })

  const rebuildM = useMutation({ mutationFn: () => compositionApi.rebuildIndex().then(r => r.data) })

  const [showNewClass, setShowNewClass] = useState(false)
  const [nc, setNc] = useState({ name: '', name_ar: '' })
  const addClass = () => {
    if (!nc.name.trim()) return
    createClassM.mutate(nc, { onSuccess: () => { setNc({ name: '', name_ar: '' }); setShowNewClass(false) } })
  }

  const rows = list?.results || []
  const pct = summary && summary.candidates ? Math.round(100 * (summary.by_status?.approved || 0) / summary.candidates) : 0

  return (
    <div className="p-4 space-y-4" dir="rtl">
      <div>
        <h1 className="text-xl font-bold text-content">تنقية المواد الفعّالة</h1>
        <p className="text-sm text-muted">مراجعة واعتماد تحليل المواد الفعّالة من سوفتك — لا يتم أي تعديل على سوفتك.</p>
      </div>

      {/* Action toolbar — full-width buttons so nothing can be clipped off-edge */}
      <button onClick={() => setShowNewClass(s => !s)}
        style={{ backgroundColor: '#022871' }}
        className="block w-full rounded-lg px-4 py-3 text-center text-base font-bold text-white hover:opacity-90">
        ＋ إضافة تصنيف جديد
      </button>
      <button onClick={() => rebuildM.mutate()} disabled={rebuildM.isPending}
        className="block w-full rounded-lg border border-line px-4 py-2 text-center text-sm font-medium text-content hover:bg-bg disabled:opacity-50">
        {rebuildM.isPending ? '… جارٍ التحديث' : '🔄 تحديث فهرس البحث'}
      </button>

      {rebuildM.isSuccess && (
        <div className="rounded-lg border border-green-300 bg-green-50 px-3 py-2 text-sm text-green-800">
          تم تحديث الفهرس: {rebuildM.data.rows} سطر · {rebuildM.data.items} صنف · {rebuildM.data.molecules} مادة ({rebuildM.data.approved} معتمد)
        </div>
      )}

      {summary && (
        <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
          <Stat label="سطور سوفتك" value={summary.raw_rows} />
          <Stat label="تركيبات مركّبة" value={summary.combinations} />
          <Stat label="قيم عامة/فارغة" value={summary.placeholders} />
          <Stat label="جزيئات مقترحة" value={summary.distinct_proposed_molecules} tone="text-primary" />
          <Stat label="أصناف مغطّاة" value={summary.item_links_covered} />
          <Stat label="نسبة الاعتماد" value={`${pct}%`} tone="text-green-600" />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-surface p-2">
        <input value={filters.q} onChange={e => { setPage(1); setFilters(f => ({ ...f, q: e.target.value })) }}
          placeholder="بحث بالاسم..." className="flex-1 min-w-[180px] rounded border border-line bg-surface px-3 py-1.5 text-sm text-content" />
        <select value={filters.status} onChange={e => { setPage(1); setFilters(f => ({ ...f, status: e.target.value })) }}
          className="rounded border border-line bg-surface px-2 py-1.5 text-sm text-content">
          <option value="needs_review">يحتاج مراجعة</option>
          <option value="pending">بانتظار المراجعة</option>
          <option value="approved">معتمد</option>
          <option value="rejected">مرفوض</option>
          <option value="all">الكل</option>
        </select>
        <label className="flex items-center gap-1 text-sm text-content">
          <input type="checkbox" checked={filters.combos} onChange={e => { setPage(1); setFilters(f => ({ ...f, combos: e.target.checked })) }} />
          تركيبات فقط
        </label>
      </div>

      {showNewClass && (
        <div className="rounded-lg border border-primary bg-surface p-3 space-y-2">
          <input value={nc.name} onChange={e => setNc(v => ({ ...v, name: e.target.value }))}
            placeholder="Class name (English) — required"
            className="block w-full rounded border border-line bg-surface px-3 py-2 text-sm text-content" />
          <input value={nc.name_ar} onChange={e => setNc(v => ({ ...v, name_ar: e.target.value }))}
            placeholder="الاسم بالعربية (اختياري)"
            className="block w-full rounded border border-line bg-surface px-3 py-2 text-sm text-content" dir="rtl" />
          <div className="flex items-center gap-2">
            <button onClick={addClass} disabled={!nc.name.trim() || createClassM.isPending}
              style={{ backgroundColor: '#16a34a' }}
              className="rounded-lg px-6 py-2 text-sm font-bold text-white disabled:opacity-50">
              {createClassM.isPending ? '… جارٍ الحفظ' : '✓ حفظ التصنيف'}
            </button>
            <button onClick={() => { setShowNewClass(false); setNc({ name: '', name_ar: '' }) }}
              className="rounded-lg border border-line px-4 py-2 text-sm text-muted hover:bg-bg">إلغاء</button>
            {createClassM.isError && <span className="text-xs text-red-600">{createClassM.error?.response?.data?.detail || 'تعذّر الإضافة'}</span>}
            {createClassM.isSuccess && <span className="text-xs text-green-600">تمت الإضافة ✓</span>}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {isLoading && <div className="text-center text-muted py-8">جارٍ التحميل…</div>}
        {!isLoading && rows.length === 0 && <div className="text-center text-muted py-8">لا توجد نتائج</div>}
        {rows.map(cand => (
          <CandidateRow
            key={cand.id} cand={cand} classes={classes} savingEdit={editM.isPending}
            onApprove={(id, classId) => approveM.mutate({ id, classId })}
            onReject={id => rejectM.mutate(id)}
            onNonDrug={(id, key) => nonDrugM.mutate({ id, key })}
            onSetClass={(id, classId) => setClassM.mutate({ id, classId })}
            onEdit={(id, components, done) => editM.mutate({ id, components }, { onSuccess: () => { invalidate(); done && done() } })}
          />
        ))}
      </div>

      {list && (list.next || list.previous) && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <button disabled={!list.previous} onClick={() => setPage(p => Math.max(1, p - 1))}
            className="rounded border border-line px-3 py-1 text-sm disabled:opacity-40">السابق</button>
          <span className="text-sm text-muted">صفحة {page} — {list.count} إجمالاً</span>
          <button disabled={!list.next} onClick={() => setPage(p => p + 1)}
            className="rounded border border-line px-3 py-1 text-sm disabled:opacity-40">التالي</button>
        </div>
      )}
    </div>
  )
}
