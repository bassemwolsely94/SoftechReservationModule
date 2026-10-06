/**
 * IngredientSearchPage.jsx — Structured Active-Ingredient Search (/ingredient-search)
 *
 * The Track-A payoff: find every medicine containing a molecule, at a specific
 * concentration, in a dosage form, or in a pharmacological class — over the
 * materialized item↔molecule index. Read-only; never touches SOFTECH.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { compositionApi } from '../api/client'

export default function IngredientSearchPage() {
  const [molecule, setMolecule] = useState('')
  const [strengthValue, setStrengthValue] = useState('')
  const [strengthUnit, setStrengthUnit] = useState('')
  const [dosageForm, setDosageForm] = useState('')
  const [classKey, setClassKey] = useState('')
  const [source, setSource] = useState('')
  const [page, setPage] = useState(1)

  const { data: facets } = useQuery({
    queryKey: ['ai-facets'],
    queryFn: () => compositionApi.searchFacets().then(r => r.data),
  })
  const { data: suggestions = [] } = useQuery({
    queryKey: ['ai-molecules', molecule],
    queryFn: () => compositionApi.searchMolecules(molecule).then(r => r.data),
    enabled: molecule.length >= 2,
  })

  const params = { page }
  if (molecule) params.molecule = molecule
  if (strengthValue) params.strength_value = strengthValue
  if (strengthUnit) params.strength_unit = strengthUnit
  if (dosageForm) params.dosage_form = dosageForm
  if (classKey) params.class_key = classKey
  if (source) params.source = source
  const hasQuery = molecule || dosageForm || classKey

  const { data: results, isFetching } = useQuery({
    queryKey: ['ai-search', params],
    queryFn: () => compositionApi.search(params).then(r => r.data),
    enabled: !!hasQuery,
    placeholderData: keepPreviousData,
  })

  const rows = results?.results || []
  const reset = () => { setStrengthValue(''); setStrengthUnit(''); setDosageForm(''); setClassKey(''); setSource(''); setPage(1) }

  return (
    <div className="p-4 space-y-4" dir="rtl">
      <div>
        <h1 className="text-xl font-bold text-content">بحث المواد الفعّالة</h1>
        <p className="text-sm text-muted">ابحث عن كل الأدوية التي تحتوي على مادة فعّالة أو تركيز أو شكل صيدلي أو تصنيف معيّن.</p>
      </div>

      {/* Search + filters */}
      <div className="rounded-lg border border-line bg-surface p-3 space-y-2">
        <div className="relative">
          <input
            value={molecule}
            onChange={e => { setPage(1); setMolecule(e.target.value.toUpperCase()) }}
            placeholder="المادة الفعّالة (مثال: AMLODIPINE)"
            className="w-full rounded border border-line bg-surface px-3 py-2 text-sm text-content"
            list="molecule-suggestions"
          />
          <datalist id="molecule-suggestions">
            {suggestions.map(s => <option key={s.molecule} value={s.molecule}>{`${s.molecule} — ${s.items} صنف`}</option>)}
          </datalist>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={strengthValue} onChange={e => { setPage(1); setStrengthValue(e.target.value) }}
            placeholder="التركيز" type="number" step="any"
            className="w-24 rounded border border-line bg-surface px-2 py-1.5 text-sm text-content"
          />
          <select value={strengthUnit} onChange={e => { setPage(1); setStrengthUnit(e.target.value) }}
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm text-content">
            <option value="">كل الوحدات</option>
            {(facets?.units || []).map(u => <option key={u} value={u}>{u}</option>)}
          </select>
          <select value={dosageForm} onChange={e => { setPage(1); setDosageForm(e.target.value) }}
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm text-content">
            <option value="">كل الأشكال الصيدلية</option>
            {(facets?.dosage_forms || []).map(f => <option key={f} value={f}>{f}</option>)}
          </select>
          <select value={classKey} onChange={e => { setPage(1); setClassKey(e.target.value) }}
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm text-content max-w-[220px]">
            <option value="">كل التصنيفات</option>
            {(facets?.classes || []).map(c => <option key={c.id} value={c.key}>{c.name_ar ? `${c.name} — ${c.name_ar}` : c.name}</option>)}
          </select>
          <select value={source} onChange={e => { setPage(1); setSource(e.target.value) }}
            className="rounded border border-line bg-surface px-2 py-1.5 text-sm text-content">
            <option value="">معتمد + مقترح</option>
            <option value="approved">معتمد فقط</option>
            <option value="parsed">مقترح فقط</option>
          </select>
          <button onClick={reset} className="rounded border border-line px-3 py-1.5 text-sm text-muted hover:bg-bg">مسح</button>
        </div>
      </div>

      {/* Results */}
      {!hasQuery && <div className="text-center text-muted py-10">ابدأ بكتابة مادة فعّالة أو اختر شكلاً/تصنيفاً.</div>}
      {hasQuery && (
        <div className="rounded-lg border border-line bg-surface overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-3 py-2 text-sm">
            <span className="text-content font-medium">{results ? `${results.count} نتيجة` : '…'}</span>
            {isFetching && <span className="text-muted text-xs">جارٍ البحث…</span>}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-bg text-muted text-xs">
                <tr>
                  <th className="px-3 py-2 text-right">الصنف</th>
                  <th className="px-3 py-2 text-right">المادة الفعّالة</th>
                  <th className="px-3 py-2 text-right">التركيز</th>
                  <th className="px-3 py-2 text-right">الشكل</th>
                  <th className="px-3 py-2 text-right">التصنيف</th>
                  <th className="px-3 py-2 text-right">المصدر</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr key={r.id} className="border-t border-line hover:bg-bg">
                    <td className="px-3 py-2">
                      {r.item
                        ? <Link to={`/products/${r.item}`} className="text-primary hover:underline">{r.item_name}</Link>
                        : <span className="text-content">{r.item_name || '—'}</span>}
                      <span className="block text-[11px] text-muted">#{r.item_softech_id}</span>
                    </td>
                    <td className="px-3 py-2 font-medium text-content">{r.molecule}</td>
                    <td className="px-3 py-2 text-primary">{r.strength_value != null ? `${Number(r.strength_value)}${r.strength_unit}` : '—'}</td>
                    <td className="px-3 py-2 text-content">{r.dosage_form || '—'}</td>
                    <td className="px-3 py-2 text-content">{r.class_name || r.class_name_ar || '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded px-1.5 text-[11px] ${r.source === 'approved' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                        {r.source === 'approved' ? 'معتمد' : 'مقترح'}
                      </span>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && !isFetching && (
                  <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">لا توجد نتائج</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {results && (results.next || results.previous) && (
            <div className="flex items-center justify-center gap-3 border-t border-line py-2">
              <button disabled={!results.previous} onClick={() => setPage(p => Math.max(1, p - 1))}
                className="rounded border border-line px-3 py-1 text-sm disabled:opacity-40">السابق</button>
              <span className="text-sm text-muted">صفحة {page}</span>
              <button disabled={!results.next} onClick={() => setPage(p => p + 1)}
                className="rounded border border-line px-3 py-1 text-sm disabled:opacity-40">التالي</button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
