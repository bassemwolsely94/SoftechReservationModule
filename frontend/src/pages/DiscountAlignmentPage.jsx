import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../api/client'

const FLAG_META = {
  origin_vs_discount: { label: 'الخصم ≠ نسبة المنشأ',       cls: 'bg-red-100 text-red-700' },
  store_vs_discount:  { label: 'الخصم ≠ نسبة التعاقد',      cls: 'bg-orange-100 text-orange-700' },
  origin_vs_store:    { label: 'المنشأ ≠ التعاقد',          cls: 'bg-amber-100 text-amber-800' },
  master_vs_discount: { label: 'الخصم ≠ السياسة الرئيسية',  cls: 'bg-purple-100 text-purple-700' },
}
const FLAG_OPTIONS = [{ value: '', label: 'كل التنبيهات' },
  ...Object.entries(FLAG_META).map(([v, m]) => ({ value: v, label: m.label }))]

// Target % the classification labels SHOULD reflect (master-policy direction:
// the real discount is the truth, labels get fixed to match).
const targetPct = r => (r.master_pct != null ? Number(r.master_pct) : Number(r.pharmacy_discp))

function Pct({ v }) {
  if (v == null || v === '') return <span className="text-gray-300">—</span>
  return <span className="tabular-nums">{Number(v)}%</span>
}

// Create a NEW classification tier in a SOFTECH lookup table (Phase 3).
// Preview-first: shows the exact proposed row (copied from a template) before writing.
function CreateTierModal({ onClose, onCreated }) {
  const [kind, setKind]   = useState('store')       // 'store' | 'origin'
  const [label, setLabel] = useState('')
  const [code, setCode]   = useState('')
  const [preview, setPreview] = useState(null)
  const [busy, setBusy]   = useState(false)

  const doPreview = async () => {
    if (!label.trim()) { alert('أدخل اسم التصنيف (يُفضّل أن يتضمن النسبة، مثال: Med: Imported 20%)'); return }
    setBusy(true); setPreview(null)
    try {
      const r = await pricingApprovalsApi.tierPreview({ kind, label, code: code || undefined })
      setPreview(r.data)
    } catch (e) { alert(e?.response?.data?.detail || 'تعذّرت المعاينة (تأكد من اتصال SOFTECH)') }
    finally { setBusy(false) }
  }

  const doCreate = async () => {
    if (!preview) { alert('اعرض المعاينة أولاً'); return }
    if (preview.code_exists) { alert('الكود مستخدم بالفعل — غيّر الكود'); return }
    if (!window.confirm(
      `إنشاء تصنيف جديد فى SOFTECH (${preview.table}):\n` +
      `• الكود: ${preview.new_code}\n• الاسم: ${label}\n\n` +
      `سيُنسخ صف موجود كقالب مع تغيير الكود والاسم فقط. متابعة؟`
    )) return
    setBusy(true)
    try {
      const r = await pricingApprovalsApi.tierCreate({ kind, label, code: code || undefined })
      alert(`✓ تم الإنشاء — الكود ${r.data.code}. يمكنك الآن توجيه الأصناف إليه.`)
      onCreated?.(); onClose()
    } catch (e) { alert(e?.response?.data?.detail || 'فشل الإنشاء') }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xl max-h-[85vh] overflow-hidden flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-black text-gray-900">➕ تصنيف جديد فى SOFTECH</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-lg">✕</button>
        </div>
        <div className="p-5 space-y-3 overflow-y-auto">
          <div className="flex gap-2">
            <label className="flex-1">
              <span className="text-xs text-gray-500 block mb-1">النوع</span>
              <select value={kind} onChange={e => { setKind(e.target.value); setPreview(null) }}
                className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm">
                <option value="store">تصنيف خصم التعاقدات (custdiscpclassif)</option>
                <option value="origin">المنشأ (itemsorigin)</option>
              </select>
            </label>
            <label className="w-28">
              <span className="text-xs text-gray-500 block mb-1">الكود (اختياري)</span>
              <input value={code} onChange={e => { setCode(e.target.value); setPreview(null) }} placeholder="تلقائى"
                className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm text-center" />
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-gray-500 block mb-1">الاسم (يتضمن النسبة)</span>
            <input value={label} onChange={e => { setLabel(e.target.value); setPreview(null) }}
              placeholder="مثال: Med: Imported 20%"
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm" />
          </label>

          <button onClick={doPreview} disabled={busy}
            className="text-xs px-3 py-1.5 rounded-lg bg-gray-700 text-white font-semibold hover:bg-gray-800 disabled:opacity-50">
            {busy ? '⏳...' : '👁 معاينة'}
          </button>

          {preview && (
            <div className="border border-gray-200 rounded-lg p-3 bg-gray-50 text-xs space-y-1.5">
              <div className="flex items-center gap-2">
                <span className="font-semibold">الجدول:</span> <code>{preview.table}</code>
                <span className="font-semibold mr-2">الكود الجديد:</span> <b>{preview.new_code}</b>
                {preview.code_exists && <span className="text-red-600 font-semibold">⚠ الكود مستخدم!</span>}
              </div>
              <div className="text-gray-500">أعمدة الاسم: {preview.desc_cols.join('، ') || '—'} · إجمالى الأعمدة: {preview.columns.length}</div>
              <div className="font-semibold text-gray-700 pt-1">الصف المقترح:</div>
              <div className="max-h-40 overflow-y-auto bg-white rounded border border-gray-100 p-2 grid grid-cols-2 gap-x-3 gap-y-0.5">
                {Object.entries(preview.proposed_row).map(([k, v]) => (
                  <div key={k} className={preview.desc_cols.includes(k) || k === preview.code_col ? 'text-indigo-700 font-semibold' : 'text-gray-500'}>
                    <span className="text-gray-400">{k}:</span> {v ?? '∅'}
                  </div>
                ))}
              </div>
              <p className="text-[10px] text-gray-400">الأعمدة الأخرى مأخوذة من صف قالب موجود (لضمان القيم الإلزامية).</p>
            </div>
          )}
        </div>
        <div className="px-5 py-3 border-t border-gray-100 flex gap-2 justify-end">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600">إلغاء</button>
          <button onClick={doCreate} disabled={busy || !preview || preview.code_exists}
            className="text-xs px-4 py-1.5 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-40">
            {busy ? '⏳ جارٍ...' : '✔ إنشاء فى SOFTECH'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function DiscountAlignmentPage() {
  const qc = useQueryClient()
  const [search, setSearch]     = useState('')
  const [flag, setFlag]         = useState('')
  const [onlyMis, setOnlyMis]   = useState(true)
  const [inclInactive, setIncl] = useState(false)
  const [sel, setSel]           = useState(() => new Set())
  const [newOrigin, setNewOrigin] = useState('')
  const [newStore, setNewStore]   = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['discount-alignment', search, flag, onlyMis, inclInactive],
    queryFn: () => pricingApprovalsApi.alignmentScan({
      search: search || undefined, flag: flag || undefined,
      only_misaligned: onlyMis ? '1' : '0',
      include_inactive: inclInactive ? '1' : undefined, limit: 3000,
    }).then(r => r.data),
    keepPreviousData: true,
  })
  const { data: tiers } = useQuery({
    queryKey: ['alignment-tiers'],
    queryFn: () => pricingApprovalsApi.alignmentTiers().then(r => r.data),
    staleTime: 10 * 60_000,
  })

  const rows  = data?.rows  || []
  const stats = data?.stats || {}
  const origins = tiers?.origins || []
  const stores  = tiers?.store_classifs || []

  const selRows = useMemo(() => rows.filter(r => sel.has(r.item_id)), [rows, sel])
  // Distinct target %s among the selected rows (to guide/validate the fix)
  const targets = useMemo(() => [...new Set(selRows.map(targetPct).filter(Number.isFinite))], [selRows])
  const oneTarget = targets.length === 1 ? targets[0] : null

  const toggle = id => setSel(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allVisible = rows.length > 0 && rows.every(r => sel.has(r.item_id))
  const toggleAll = () => setSel(allVisible ? new Set() : new Set(rows.map(r => r.item_id)))
  const clearSel = () => { setSel(new Set()); setNewOrigin(''); setNewStore('') }

  // Selected rows that carry a family-aware suggestion (for per-row apply)
  const selWithSugg = useMemo(
    () => selRows.filter(r => r.suggested_origin_code || r.suggested_store_code),
    [selRows])

  const applyMut = useMutation({
    mutationFn: (payload) => pricingApprovalsApi.alignmentApply(payload).then(r => r.data),
    onSuccess: (res) => {
      alert(`تم التطبيق: ${res.applied} نجح · ${res.failed} فشل.\n${res.note || ''}`)
      clearSel()
      qc.invalidateQueries(['discount-alignment'])
    },
    onError: (err) => alert(err?.response?.data?.detail || 'فشل التطبيق'),
  })

  // Uniform: one target tier for all selected
  const doApply = () => {
    if (!newOrigin && !newStore) { alert('اختر المنشأ الجديد و/أو تصنيف الخصم الجديد'); return }
    const oLbl = origins.find(o => o.code === newOrigin)?.name || '—'
    const sLbl = stores.find(s => s.code === newStore)?.name || '—'
    if (!window.confirm(
      `تطبيق مُوحَّد على ${sel.size} صنف في SOFTECH:\n` +
      (newOrigin ? `• المنشأ ← ${oLbl}\n` : '') +
      (newStore  ? `• تصنيف الخصم ← ${sLbl}\n` : '') +
      `\nستُكتب على HQ وتنتشر للفروع خلال ~30 دقيقة. متابعة؟`
    )) return
    applyMut.mutate({ item_ids: [...sel], origin_code: newOrigin || undefined, store_classif: newStore || undefined })
  }

  // Per-row: apply each selected item's OWN family-aware suggestion
  const doApplySuggestions = () => {
    if (selWithSugg.length === 0) { alert('لا توجد اقتراحات للأصناف المحددة'); return }
    if (!window.confirm(
      `تطبيق الاقتراح المناسب لكل صنف (${selWithSugg.length} صنف) في SOFTECH:\n` +
      `يُعيَّن لكل صنف المنشأ/تصنيف الخصم المطابق لفئته ونسبته.\n` +
      `ستُكتب على HQ وتنتشر للفروع خلال ~30 دقيقة. متابعة؟`
    )) return
    applyMut.mutate({
      changes: selWithSugg.map(r => ({
        item_id: r.item_id,
        origin_code:  r.suggested_origin_code  || undefined,
        store_classif: r.suggested_store_code  || undefined,
      })),
    })
  }

  const tierOpt = t => `${t.name}${t.pct != null ? ` · ${Number(t.pct)}%` : ''}`

  return (
    <div dir="rtl" className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-lg font-black text-gray-900">🎯 مطابقة الخصومات</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            الخصم الفعلى هو المرجع — تُصحَّح تسميات التصنيف/المنشأ القديمة لتطابقه (تُكتب على SOFTECH)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-xs px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 font-semibold">
            مفحوص: <b>{(stats.checked || 0).toLocaleString('en-US')}</b>
          </div>
          <div className="text-xs px-3 py-1.5 rounded-lg bg-red-50 text-red-700 font-semibold ring-1 ring-red-200">
            غير متوافق: <b>{(stats.flagged || 0).toLocaleString('en-US')}</b>
          </div>
          {isFetching && <span className="text-xs text-gray-400 animate-pulse">جارٍ الفحص...</span>}
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 bg-white border border-gray-200 rounded-xl px-3 py-2">
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="🔍 ابحث باسم الصنف..."
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-64 focus:outline-none focus:border-brand-400" />
        <select value={flag} onChange={e => setFlag(e.target.value)}
          className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:border-brand-400">
          {FLAG_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <label className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
          <input type="checkbox" checked={onlyMis} onChange={e => setOnlyMis(e.target.checked)} className="rounded" /> غير المتوافقة فقط
        </label>
        <label className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
          <input type="checkbox" checked={inclInactive} onChange={e => setIncl(e.target.checked)} className="rounded" /> تضمين الموقوفة
        </label>
        <button onClick={() => setShowCreate(true)}
          className="text-xs px-3 py-1.5 rounded-lg border border-indigo-300 bg-indigo-50 text-indigo-700 font-semibold hover:bg-indigo-100"
          title="إنشاء تصنيف/منشأ جديد فى SOFTECH عند عدم توفّر تصنيف مطابق">
          ➕ تصنيف جديد
        </button>
        <span className="text-xs text-gray-400 mr-auto">{rows.length} صف معروض</span>
      </div>

      {showCreate && (
        <CreateTierModal
          onClose={() => setShowCreate(false)}
          onCreated={() => { qc.invalidateQueries(['alignment-tiers']); qc.invalidateQueries(['discount-alignment']) }}
        />
      )}

      {/* Bulk-fix bar */}
      {sel.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2 sticky top-0 z-20">
          <span className="text-sm font-bold text-emerald-800">✎ {sel.size} صنف محدد</span>

          {/* Lead action — apply each item's own family-aware suggestion */}
          <button onClick={doApplySuggestions} disabled={applyMut.isLoading || selWithSugg.length === 0}
            className="text-xs px-3 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 disabled:opacity-40"
            title="يُعيَّن لكل صنف المنشأ/تصنيف الخصم المطابق لفئته (محلى/مستورد…) ونسبته">
            {applyMut.isLoading ? '⏳ جارٍ...' : `✨ تطبيق المقترح لكل صنف (${selWithSugg.length})`}
          </button>
          <span className="text-gray-300">|</span>
          <span className="text-[11px] text-gray-500">أو تعيين مُوحَّد:</span>
          {oneTarget != null
            ? <span className="text-[11px] text-emerald-700">الهدف <b>{oneTarget}%</b></span>
            : targets.length > 1 && <span className="text-[11px] text-amber-700">⚠ خصومات مختلفة ({targets.map(t=>t+'%').join('، ')})</span>}
          <select value={newOrigin} onChange={e => setNewOrigin(e.target.value)}
            className="border border-emerald-300 rounded-lg px-2 py-1 text-xs bg-white max-w-[240px]">
            <option value="">المنشأ الجديد (اختياري)…</option>
            {origins.map(o => (
              <option key={o.code} value={o.code}>
                {oneTarget != null && o.pct != null && Number(o.pct) === oneTarget ? '✓ ' : ''}{tierOpt(o)}
              </option>
            ))}
          </select>
          <select value={newStore} onChange={e => setNewStore(e.target.value)}
            className="border border-emerald-300 rounded-lg px-2 py-1 text-xs bg-white max-w-[240px]">
            <option value="">تصنيف الخصم الجديد (اختياري)…</option>
            {stores.map(s => (
              <option key={s.code} value={s.code}>
                {oneTarget != null && s.pct != null && Number(s.pct) === oneTarget ? '✓ ' : ''}{tierOpt(s)}
              </option>
            ))}
          </select>
          <button onClick={doApply} disabled={applyMut.isLoading}
            className="text-xs px-3 py-1.5 rounded-lg bg-emerald-600 text-white font-semibold hover:bg-emerald-700 disabled:opacity-50">
            {applyMut.isLoading ? '⏳ جارٍ الكتابة...' : '✔ تطبيق على SOFTECH'}
          </button>
          <button onClick={clearSel} className="text-xs text-gray-500 hover:text-gray-700">إلغاء التحديد</button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="overflow-x-auto" style={{ maxHeight: 'calc(100vh - 260px)' }}>
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 text-gray-500 text-xs font-bold z-10">
              <tr>
                <th className="px-2 py-2 w-8 text-center">
                  <input type="checkbox" checked={allVisible} onChange={toggleAll} className="rounded" />
                </th>
                <th className="px-3 py-2 text-right">الصنف</th>
                <th className="px-3 py-2 text-right">المورد</th>
                <th className="px-3 py-2 text-right">المنشأ (الحالى)</th>
                <th className="px-3 py-2 text-center">خصم أساسى</th>
                <th className="px-3 py-2 text-center">منشأ %</th>
                <th className="px-3 py-2 text-center">تعاقد %</th>
                <th className="px-3 py-2 text-center">الهدف</th>
                <th className="px-3 py-2 text-right">التنبيهات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {isLoading && <tr><td colSpan={9} className="text-center py-12 text-gray-400">جارٍ التحميل...</td></tr>}
              {!isLoading && rows.length === 0 && (
                <tr><td colSpan={9} className="text-center py-12 text-green-600 font-semibold">✓ لا توجد أصناف غير متوافقة</td></tr>
              )}
              {rows.map(r => {
                const tp = targetPct(r)
                return (
                  <tr key={r.item_id} className={`hover:bg-gray-50 ${sel.has(r.item_id) ? 'bg-emerald-50/60' : r.misaligned ? 'bg-red-50/40' : ''}`}>
                    <td className="px-2 py-2 text-center">
                      <input type="checkbox" checked={sel.has(r.item_id)} onChange={() => toggle(r.item_id)} className="rounded" />
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900 whitespace-nowrap">{r.name}</div>
                      <div className="text-[11px] text-gray-400">{r.softech_id}{r.no_more_use && <span className="text-red-400"> · موقوف</span>}</div>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">{r.supplier_name || r.supplier_code}</td>
                    <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">{r.origin_name}</td>
                    <td className="px-3 py-2 text-center font-bold text-gray-800"><Pct v={r.pharmacy_discp} /></td>
                    <td className="px-3 py-2 text-center text-gray-500"><Pct v={r.origin_pct} /></td>
                    <td className="px-3 py-2 text-center text-gray-500"><Pct v={r.store_pct} /></td>
                    <td className="px-3 py-2">
                      <div className="text-center font-bold text-emerald-700 tabular-nums">
                        {Number.isFinite(tp) ? `${tp}%` : '—'}
                      </div>
                      {(r.suggested_origin_name || r.suggested_store_name) ? (
                        <div className="text-[10px] text-emerald-600 leading-tight mt-0.5 whitespace-nowrap">
                          {r.suggested_origin_name && <div>منشأ ← {r.suggested_origin_name}</div>}
                          {r.suggested_store_name && <div>خصم ← {r.suggested_store_name}</div>}
                        </div>
                      ) : r.misaligned && (
                        <div className="text-[10px] text-amber-500 mt-0.5 whitespace-nowrap" title="لا يوجد تصنيف مطابق — يلزم إنشاؤه (المرحلة 3)">
                          لا تصنيف مطابق
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {r.flags.map(f => (
                          <span key={f} className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${FLAG_META[f]?.cls || 'bg-gray-100 text-gray-500'}`}>
                            {FLAG_META[f]?.label || f}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[11px] text-gray-400">
        «الهدف» = الخصم الفعلى (خصم أساسى) وهو المرجع. حدِّد الأصناف واختر المنشأ/تصنيف الخصم الذى يطابق الهدف ثم «تطبيق على SOFTECH».
        القادم (المرحلة 3): إنشاء تصنيفات/نسب جديدة داخل جداول SOFTECH عند عدم توفّرها.
      </p>
    </div>
  )
}
