/**
 * AvailabilityInboxTab.jsx — «صندوق الإتاحة»: the supplier-PUSH workflow (doc 24 §2–§19).
 *
 *   paste a WhatsApp list / upload a screenshot or Excel
 *     → parsed + matched on the server (shared matcher + vendor-scoped aliases)
 *     → exception-driven review grid: what is it, do we need it, how many, at what cost
 *     → select what is actually needed (never "everything the supplier offered", §7)
 *     → order panel: copy / WhatsApp / Excel / record
 *
 * The backend owns every number (need, internal cover, residual gap, effective cost,
 * scarcity). This screen displays them and sends the operator's decisions back.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { supplyApi } from '../../api/client'
import ItemSearchInput from '../../components/ItemSearchInput'
import OrderPanel from './OrderPanel'
import { FreshnessBar, LockBar, ScopeBar } from './AvailabilityControls'
import ColumnMapper from './ColumnMapper'
import SupplierCodeReport from './SupplierCodeReport'
import { Chip, btnGhost, btnPrimary, errText, fmtDate, inputCls, money, pct, q } from './supplyUi'
import { wildcardMatch } from '../../utils/wildcard'
import useGridKeyboard, { GRID_KEYS_HINT } from '../../hooks/useGridKeyboard'

const SOURCES = [['whatsapp', 'واتساب'], ['text', 'نص'], ['email', 'بريد'], ['manual', 'يدوي']]
const PLACEHOLDER = 'الصق رسالة/رسائل الواتساب هنا كما هي — سطر لكل صنف\nمثال:\nRecormon 4000 available 10\nكريون ٢٥٠٠٠ متاح ٢٠\nZinnat 250 10+2 @ 90'

function rows(data) { return Array.isArray(data) ? data : (data?.results || []) }

export default function AvailabilityInboxTab() {
  const qc = useQueryClient()
  const [selected, setSelected] = useState(null)
  const [supplierName, setSupplierName] = useState('')
  const [source, setSource] = useState('whatsapp')
  const [raw, setRaw] = useState('')
  const [notice, setNotice] = useState(null)
  const imgRef = useRef(null)
  const fileRef = useRef(null)

  const listQ = useQuery({ queryKey: ['supply-avail-list'],
    queryFn: () => supplyApi.availList().then(r => r.data) })

  const afterImport = (batchId, extra) => {
    setSelected(batchId)
    qc.invalidateQueries({ queryKey: ['supply-avail-list'] })
    qc.invalidateQueries({ queryKey: ['supply-avail-analysis', batchId] })
    setNotice(extra || null)
  }

  const createM = useMutation({
    mutationFn: () => supplyApi.availCreate({ source, supplier_name: supplierName, raw_content: raw })
      .then(r => r.data),
    onSuccess: (d) => {
      setRaw('')
      afterImport(d.id, d.duplicate_of
        ? { tone: 'amber', text: `تنبيه: نفس هذا المحتوى أُضيف من قبل (دفعة #${d.duplicate_of}). حُفظ كدفعة جديدة — راجع قبل الطلب.` }
        : (!d.supplier && supplierName
          ? { tone: 'gray', text: 'لم يُتعرَّف على المورد تلقائياً — المطابقة تعمل، لكن بدون أسماء المورد الخاصة.' }
          : null))
    },
  })

  // Screenshot / Excel: open a batch for the file, then send the file into it. A spreadsheet
  // whose column layout isn't known for this supplier comes back as a column preview
  // (`mapping`) — confirmed once, remembered after.
  const [mapping, setMapping] = useState(null)      // { batchId, file, preview }
  const imported = (batchId, res) => {
    const lay = res.layout
    afterImport(batchId, { tone: 'gray', layoutId: lay?.remembered ? lay.id : null,
      text: `تم استخراج ${res.created} سطر.` + (lay?.remembered ? ' (بترتيب الأعمدة المحفوظ لهذا المورد)'
        : lay?.saved ? ' — حُفظ ترتيب الأعمدة، ملفاته القادمة تُستورد مباشرة.' : '') })
  }
  const uploadM = useMutation({
    mutationFn: async ({ kind, file }) => {
      const src = kind === 'image' ? 'image' : (file.name.toLowerCase().endsWith('.csv') ? 'csv' : 'excel')
      const b = (await supplyApi.availCreate({ source: src, supplier_name: supplierName, raw_content: '' })).data
      const res = kind === 'image' ? await supplyApi.availOcr(b.id, file) : await supplyApi.availImport(b.id, file)
      return { batchId: b.id, file, res: res.data }
    },
    onSuccess: ({ batchId, file, res }) => {
      if (res.needs_mapping) { setMapping({ batchId, file, preview: res }); return }
      imported(batchId, res)
    },
  })
  const mapM = useMutation({
    mutationFn: (extra) => supplyApi.availImport(mapping.batchId, mapping.file, extra).then(r => r.data),
    onSuccess: (res) => { const id = mapping.batchId; setMapping(null); imported(id, res) },
  })
  const cancelMapping = async () => {           // the empty list opened for the file goes away
    const id = mapping?.batchId
    setMapping(null)
    if (id) { try { await supplyApi.availDelete(id) } catch { /* already gone */ } }
    qc.invalidateQueries({ queryKey: ['supply-avail-list'] })
  }
  const forgetM = useMutation({
    mutationFn: (lid) => supplyApi.availForgetLayout(lid),
    onSuccess: () => setNotice(n => (n ? { ...n, layoutId: null, text: `${n.text} — نُسي ترتيب الأعمدة، الملف القادم سيُعرض للمراجعة.` } : n)),
  })

  const onPasteKey = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && raw.trim()) { e.preventDefault(); createM.mutate() }
  }
  // With a list open, the paste box folds away so the review grid gets the whole screen.
  const [showImport, setShowImport] = useState(false)
  const [showCodes, setShowCodes] = useState(false)       // supplier-code coverage report
  const importOpen = !selected || showImport
  const batches = rows(listQ.data)

  return (
    <div className="space-y-3">
      {/* Batches — a compact strip (full width left to the review grid) */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-content/60 shrink-0">القوائم:</span>
        <div className="flex gap-2 overflow-x-auto pb-1 grow">
          {listQ.isLoading && <span className="text-sm text-content/50">جارٍ التحميل…</span>}
          {batches.length === 0 && !listQ.isLoading && (
            <span className="text-sm text-content/50">لا توجد قوائم بعد — الصق أول قائمة.</span>)}
          {batches.map(b => (
            <button key={b.id} type="button" onClick={() => { setSelected(b.id); setShowImport(false) }}
              className={`shrink-0 text-right rounded-lg border px-2.5 py-1.5 transition ${
                selected === b.id ? 'border-primary bg-primary/5' : 'border-line bg-surface hover:border-primary/40'}`}>
              <div className="flex items-center gap-2">
                <span className="font-medium text-content text-sm whitespace-nowrap">{b.supplier_display || 'مورد غير محدد'}</span>
                <span className="text-[11px] text-content/50">#{b.id}</span>
                {b.is_locked && <span title="قائمة نهائية (مقفلة)">🔒</span>}
                {b.branch_scope?.length > 0 && (
                  <span className="text-[10px] text-content/50" title="محسوبة لفروع محددة">{b.branch_scope.length} فرع</span>)}
              </div>
              <div className="text-[11px] text-content/60 whitespace-nowrap">
                {b.line_count} سطر · مطابق {b.matched_count} · مؤكد {b.confirmed_count} · {fmtDate(b.created_at)}
              </div>
            </button>
          ))}
        </div>
        <button type="button" className={`${btnGhost} shrink-0`} onClick={() => setShowCodes(s => !s)}
          title="كم سطراً من أسطر الموردين يُطابَق بكود المورد (المطابقات المؤكدة + نسخة SOFTECH)">
          📊 مطابقة الأكواد</button>
        {selected && (
          <button type="button" className={`${btnPrimary} shrink-0`} onClick={() => setShowImport(s => !s)}>
            {showImport ? 'إخفاء الإدخال' : '+ قائمة جديدة'}
          </button>
        )}
      </div>

      {showCodes && <SupplierCodeReport onClose={() => setShowCodes(false)} />}

      {/* Import bar */}
      {importOpen && <div className="rounded-lg border border-line bg-surface p-3 space-y-2">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label className="text-xs text-content/60 mb-1">المورد (كما في الرسالة)</label>
            <input value={supplierName} onChange={e => setSupplierName(e.target.value)}
              placeholder="ابن سينا / Pharma Overseas…" className={`${inputCls} w-56`} />
          </div>
          <div className="flex flex-col">
            <label className="text-xs text-content/60 mb-1">المصدر</label>
            <select value={source} onChange={e => setSource(e.target.value)} className={`${inputCls} w-32`}>
              {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="flex gap-2 mr-auto">
            <button type="button" className={btnGhost} onClick={() => imgRef.current?.click()}
              disabled={uploadM.isPending}>📷 صورة / لقطة شاشة</button>
            <button type="button" className={btnGhost} onClick={() => fileRef.current?.click()}
              disabled={uploadM.isPending}>📄 Excel / CSV</button>
            <input ref={imgRef} type="file" accept="image/*" hidden
              onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) uploadM.mutate({ kind: 'image', file: f }) }} />
            <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" hidden
              onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) uploadM.mutate({ kind: 'file', file: f }) }} />
          </div>
        </div>
        <textarea value={raw} onChange={e => setRaw(e.target.value)} onKeyDown={onPasteKey} rows={5}
          dir="auto" placeholder={PLACEHOLDER}
          className={`${inputCls} w-full font-mono text-[13px] leading-relaxed`} />
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => createM.mutate()} disabled={!raw.trim() || createM.isPending}
            className={btnPrimary} title="Ctrl+Enter">
            {createM.isPending ? 'جارٍ التحليل…' : 'تحليل القائمة'}
          </button>
          <span className="text-[11px] text-content/50">Ctrl+Enter للتحليل · يُحفظ النص الأصلي كما هو للمراجعة</span>
          {uploadM.isPending && <span className="text-xs text-content/60">جارٍ قراءة الملف…</span>}
          {(createM.isError || uploadM.isError) && (
            <span className="text-xs text-rose-600">{errText(createM.error || uploadM.error)}</span>)}
        </div>
        {mapping && (
          <ColumnMapper preview={mapping.preview} busy={mapM.isPending} error={mapM.isError ? errText(mapM.error) : null}
            onImport={(extra) => mapM.mutate(extra)} onCancel={cancelMapping} />
        )}
        {notice && (
          <div className={`text-xs rounded px-2 py-1 border ${notice.tone === 'amber'
            ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-line bg-primary/5 text-content/70'}`}>
            {notice.text}
            {notice.layoutId && (
              <button type="button" className="underline ms-2 hover:text-primary" disabled={forgetM.isPending}
                onClick={() => forgetM.mutate(notice.layoutId)}
                title="إذا تغيّر شكل ملف هذا المورد: انسَ الترتيب المحفوظ وراجع الأعمدة في الملف القادم">نسيان ترتيب الأعمدة</button>)}
          </div>
        )}
      </div>}

      {/* Review — full width */}
      {selected
        ? <BatchReview key={selected} batchId={selected} />
        : <div className="text-sm text-content/50 p-2">اختر قائمة من الشريط أعلاه أو الصق قائمة جديدة.</div>}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Review grid for one batch
// ══════════════════════════════════════════════════════════════════════════════

const FILTERS = [
  ['all', 'الكل'], ['buy', 'مطلوب شراؤه'], ['needs_match', 'يحتاج مطابقة'],
  ['not_needed', 'غير مطلوب'], ['urgent', 'عاجل'], ['price_above_history', 'سعر أعلى من سابق'],
]
const STATE_ORDER = { buy: 0, needs_match: 1, not_needed: 2 }

// The filter-chip counts, recomputed from the rows after an in-place swap (same rule as
// the server's analyze_batch summary: one per state + one per flag).
function summarize(lines) {
  const s = { total: lines.length }
  for (const r of lines) {
    s[r.state] = (s[r.state] || 0) + 1
    for (const f of r.flags) s[f] = (s[f] || 0) + 1
  }
  return s
}

// Sortable columns of the review grid: key → value getter (strings sort A→Z / أ→ي).
const SORT_COLS = {
  raw_text:   r => r.raw_text || '',
  item_name:  r => r.item_name || '',
  trust:      r => (r.item_id ? r.trust : null),
  approvals:  r => (r.item_id ? r.approvals : null),
  supplier_qty: r => r.supplier_qty,
  price:      r => r.price,
  offer_effective_cost: r => r.offer_effective_cost,
  required:   r => r.required,
  current_stock: r => r.current_stock,
  internal_cover: r => r.internal_cover,
  suggested_buy: r => (r.item_id && r.state !== 'needs_match') ? r.suggested_buy : null,
  flags:      r => STATE_ORDER[r.state] * 100 - r.flags.length,
}

function SortTh({ k, sort, onSort, className = '', title, children }) {
  const on = sort?.key === k
  return (
    <th title={title} onClick={() => onSort(k)} aria-sort={on ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}
      className={`py-2 px-2 cursor-pointer select-none whitespace-nowrap hover:text-primary ${on ? 'text-primary' : ''} ${className}`}>
      {children}<span className="ms-1 text-[10px]">{on ? (sort.dir === 1 ? '▲' : '▼') : '↕'}</span>
    </th>
  )
}

function BatchReview({ batchId }) {
  const qc = useQueryClient()
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [picked, setPicked] = useState({})          // line_id → true
  const [open, setOpen] = useState(null)            // expanded line_id
  const [ordering, setOrdering] = useState(false)

  const batchQ = useQuery({ queryKey: ['supply-avail', batchId],
    queryFn: () => supplyApi.availGet(batchId).then(r => r.data) })
  const anQ = useQuery({ queryKey: ['supply-avail-analysis', batchId],
    queryFn: () => supplyApi.availAnalysis(batchId).then(r => r.data) })

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['supply-avail-analysis', batchId] })
    qc.invalidateQueries({ queryKey: ['supply-avail', batchId] })
    qc.invalidateQueries({ queryKey: ['supply-avail-list'] })
  }
  const confirmAllM = useMutation({ mutationFn: () => supplyApi.availConfirm(batchId), onSuccess: refresh })
  // confirm exactly the ticked rows (each teaches the memory for this supplier)
  const confirmPickedM = useMutation({
    mutationFn: (ids) => supplyApi.availConfirm(batchId, ids), onSuccess: refresh })
  const reanalyse = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['supply-avail-analysis', batchId] })
    qc.invalidateQueries({ queryKey: ['supply-avail-history', batchId] })
    qc.invalidateQueries({ queryKey: ['supply-avail', batchId] })
    qc.invalidateQueries({ queryKey: ['supply-avail-list'] })
  }, [qc, batchId])
  // A tick / confirm changes ONE line (or one split group): the server returns just those
  // review rows and we swap them in place — no full re-analysis of the whole list.
  const swapRows = (newRows, groupId) => {
    qc.setQueryData(['supply-avail-analysis', batchId], old => {
      if (!old) return old
      const ids = new Set(newRows.map(r => r.line_id))
      const gone = r => ids.has(r.line_id) || (groupId != null && r.group_id === groupId)
      const at = old.lines.findIndex(gone)
      const kept = old.lines.filter(r => !gone(r))
      const lines = at < 0 ? [...kept, ...newRows] : [...kept.slice(0, at), ...newRows, ...kept.slice(at)]
      return { ...old, lines, summary: summarize(lines) }
    })
    qc.invalidateQueries({ queryKey: ['supply-avail-list'] })        // counts on the batch strip
  }
  const lineM = useMutation({
    mutationFn: ({ lid, data }) => supplyApi.availLine(batchId, lid, data),
    onSuccess: (res) => (res.data?.rows ? swapRows(res.data.rows, null) : refresh()) })
  // one supplier line → one or several items (several split the line into sibling rows)
  const itemsM = useMutation({
    mutationFn: ({ lid, ids }) => supplyApi.availItems(batchId, lid, ids),
    onSuccess: (res) => (res.data?.rows ? swapRows(res.data.rows, res.data.group_id) : refresh()) })

  const summary = anQ.data?.summary || {}
  const all = anQ.data?.lines || []
  const [sort, setSort] = useState(null)            // {key, dir: 1|-1} — null = default order
  const onSort = (key) => setSort(s => (!s || s.key !== key) ? { key, dir: 1 }
    : s.dir === 1 ? { key, dir: -1 } : null)       // asc → desc → default
  const visible = useMemo(() => {
    const s = search.trim().toLowerCase()
    const out = all
      .filter(r => filter === 'all' ? true
        : (filter === r.state || r.flags.includes(filter)))
      .filter(r => !s || wildcardMatch([r.raw_text, r.item_name], s) || (r.item_softech_id || '').includes(s))
    const byDefault = (a, b) => (Number(b.flags.includes('urgent')) - Number(a.flags.includes('urgent')))
      || (STATE_ORDER[a.state] - STATE_ORDER[b.state])
      || ((b.residual_gap || 0) - (a.residual_gap || 0))
    if (!sort) return out.sort(byDefault)
    const col = SORT_COLS[sort.key]
    return out.sort((a, b) => {
      const va = col(a), vb = col(b)
      const ea = va === null || va === undefined || va === '', eb = vb === null || vb === undefined || vb === ''
      if (ea || eb) return ea === eb ? byDefault(a, b) : (ea ? 1 : -1)      // blanks always last
      const c = typeof va === 'string' ? va.localeCompare(vb, 'ar') : va - vb
      return (c * sort.dir) || byDefault(a, b)
    })
  }, [all, filter, search, sort])

  const pickedRows = all.filter(r => picked[r.line_id] && r.item_id)
  // select-all works on what is VISIBLE (current filter + search), matched rows only
  const selectable = visible.filter(r => r.item_id)
  const allOn = selectable.length > 0 && selectable.every(r => picked[r.line_id])
  const someOn = selectable.some(r => picked[r.line_id])
  const headRef = useRef(null)
  useEffect(() => { if (headRef.current) headRef.current.indeterminate = someOn && !allOn }, [someOn, allOn])
  const toggleAll = () => setPicked(p => {
    const n = { ...p }
    for (const r of selectable) { if (allOn) delete n[r.line_id]; else n[r.line_id] = true }
    return n
  })
  const pickedUnconfirmed = pickedRows.filter(r => !r.is_confirmed).map(r => r.line_id)
  const lockedNow = !!anQ.data?.locked
  // keyboard: ↑↓ move · Space tick · Enter confirm the match · M open the match picker
  const kb = useGridKeyboard({
    rows: visible, getKey: r => r.line_id, advanceOnConfirm: true,
    onToggle: r => r.item_id && setPicked(p => { const n = { ...p }; if (n[r.line_id]) delete n[r.line_id]; else n[r.line_id] = true; return n }),
    onConfirm: r => { if (!lockedNow && r.item_id && !r.is_confirmed) lineM.mutate({ lid: r.line_id, data: { item: r.item_id, is_confirmed: true } }) },
    onOpen: r => setOpen(o => (o === r.line_id ? null : r.line_id)),
    onClose: () => setOpen(null),
    onSelectAll: toggleAll,
  })
  const pickNeeded = () => setPicked(Object.fromEntries(
    all.filter(r => r.state === 'buy' && r.suggested_buy > 0).map(r => [r.line_id, true])))

  if (anQ.isLoading) return <div className="text-sm text-content/50 p-4">جارٍ تحليل القائمة…</div>
  if (anQ.isError) return <div className="text-sm text-rose-600 p-4">{errText(anQ.error)}</div>

  const batch = batchQ.data
  const locked = !!anQ.data?.locked
  const orderLines = pickedRows.map(r => ({
    key: r.line_id, item_id: r.item_id, availability_line_id: r.line_id,
    qty: r.suggested_buy || r.supplier_qty || 1,
    label: `${r.item_name} (${r.item_softech_id})`,
  }))

  return (
    <div className="space-y-3">
      {/* Context: data freshness · which branches · finalized or draft (+ audit trail) */}
      <div className="rounded-lg border border-line bg-surface px-3 py-2 space-y-2">
        <FreshnessBar onRefreshed={reanalyse} />
        <ScopeBar batchId={batchId} scope={anQ.data?.scope} locked={locked} onChanged={reanalyse} />
        {batch && <LockBar batch={batch} onChanged={reanalyse} />}
      </div>

      {/* Summary = filters */}
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map(([k, l]) => {
          const count = k === 'all' ? summary.total : summary[k]
          return (
            <button key={k} type="button" onClick={() => setFilter(k)}
              className={`text-xs px-2.5 py-1 rounded-full border transition ${filter === k
                ? 'border-primary bg-primary text-white' : 'border-line bg-surface text-content/70 hover:border-primary/50'}`}>
              {l} <span className="opacity-70">{count ?? 0}</span>
            </button>
          )
        })}
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="بحث…"
          className={`${inputCls} text-xs w-40 mr-auto`} />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        <button type="button" className={btnGhost} onClick={() => confirmAllM.mutate()}
          disabled={confirmAllM.isPending || locked}
          title="تأكيد كل المطابقات عالية الثقة دفعة واحدة — يتعلّمها النظام لهذا المورد">
          ✓ تأكيد المطابقات الواضحة
        </button>
        <button type="button" className={btnGhost} onClick={pickNeeded}>تحديد المطلوب فقط</button>
        {Object.keys(picked).length > 0 && (
          <button type="button" className="text-content/50 hover:text-primary" onClick={() => setPicked({})}>إلغاء التحديد</button>)}
        {confirmAllM.data && <span className="text-emerald-700">أُكّد {confirmAllM.data.data.confirmed} سطر</span>}
        {confirmPickedM.data && <span className="text-emerald-700">أُكّد {confirmPickedM.data.data.confirmed} سطر محدد</span>}
        {locked && <span className="text-content/60">🔒 القائمة نهائية — العرض والطلب متاحان، التعديل بعد الفتح.</span>}
        {(confirmAllM.isError || confirmPickedM.isError || lineM.isError || itemsM.isError) && (
          <span className="text-rose-600">{errText(confirmAllM.error || confirmPickedM.error || lineM.error || itemsM.error)}</span>)}
      </div>

      {/* ONE scroll area sized to the screen; the header row stays visible while scrolling */}
      <div {...kb.containerProps}
        className={`rounded-lg border border-line bg-surface overflow-auto max-h-[calc(100vh-17rem)] min-h-[20rem] ${kb.containerProps.className}`}>
        <table className="w-full text-sm min-w-[72rem]">
          <thead className="sticky top-0 z-10 text-[11px] text-content/70 border-b border-line bg-surface shadow-sm">
            <tr>
              <th className="w-8 py-2">
                <input ref={headRef} type="checkbox" checked={allOn} onChange={toggleAll}
                  disabled={!selectable.length} title="تحديد / إلغاء تحديد كل الأسطر الظاهرة" />
              </th>
              <SortTh k="raw_text" sort={sort} onSort={onSort} className="text-right min-w-[13rem]">كما ورد</SortTh>
              <SortTh k="item_name" sort={sort} onSort={onSort} className="text-right min-w-[22rem]">الصنف المطابق</SortTh>
              <SortTh k="trust" sort={sort} onSort={onSort}
                title="درجة الثقة في الصنف المطابق (0–100): مؤكد = 100، باركود 97، كود المورد 95، وإلا درجة المطابقة − إشارات الخطر + الاعتمادات السابقة">الثقة</SortTh>
              <SortTh k="approvals" sort={sort} onSort={onSort}
                title="كم مرة اعتمد المستخدمون هذا الاسم لهذا الصنف من قبل">اعتمادات</SortTh>
              <SortTh k="supplier_qty" sort={sort} onSort={onSort} title="الكمية المتاحة لدى المورد">متاح</SortTh>
              <SortTh k="price" sort={sort} onSort={onSort}>السعر / بونص</SortTh>
              <SortTh k="offer_effective_cost" sort={sort} onSort={onSort} title="السعر × الكمية ÷ (الكمية + البونص)">تكلفة فعلية</SortTh>
              <SortTh k="required" sort={sort} onSort={onSort}
                title={anQ.data?.scope?.all ? 'احتياج الشركة الصافي (كل الفروع)' : 'احتياج الفروع المحددة فقط'}>
                الاحتياج{anQ.data?.scope?.all ? '' : ' *'}</SortTh>
              <SortTh k="current_stock" sort={sort} onSort={onSort}>الرصيد</SortTh>
              <SortTh k="internal_cover" sort={sort} onSort={onSort} title="مخزون فوق الهدف بفروع أخرى يغطي الاحتياج قبل الشراء">داخلي</SortTh>
              <SortTh k="suggested_buy" sort={sort} onSort={onSort} className="font-bold" title="الكمية المقترح شراؤها من هذا العرض">للشراء</SortTh>
              <SortTh k="flags" sort={sort} onSort={onSort} className="text-right min-w-[12rem]">إشارات</SortTh>
            </tr>
          </thead>
          <tbody>
            {visible.map(r => {
              // every row of the same supplier line (split into one row per item)
              const group = all.filter(x => x.group_id === r.group_id)
              return (
                <Row key={r.line_id} r={r} picked={!!picked[r.line_id]} batchId={batchId}
                  group={group} saving={itemsM.isPending} locked={locked} kb={kb.rowProps(r)}
                  onPick={v => setPicked(p => { const n = { ...p }; if (v) n[r.line_id] = true; else delete n[r.line_id]; return n })}
                  expanded={open === r.line_id} onToggle={() => setOpen(o => (o === r.line_id ? null : r.line_id))}
                  onConfirm={() => lineM.mutate({ lid: r.line_id, data: { item: r.item_id, is_confirmed: true } })}
                  onSetItems={(ids) => itemsM.mutate({ lid: r.group_id, ids })} />
              )
            })}
            {visible.length === 0 && (
              <tr><td colSpan={13} className="text-center text-content/50 py-6">لا توجد أسطر في هذا التصنيف.</td></tr>)}
          </tbody>
        </table>
      </div>

      <div className="text-[11px] text-content/45">{GRID_KEYS_HINT}</div>

      {/* Sticky action bar */}
      {pickedRows.length > 0 && !ordering && (
        <div className="sticky bottom-2 z-10 rounded-lg border border-primary/40 bg-surface shadow-lg p-2 flex items-center gap-3">
          <span className="text-sm text-content">{pickedRows.length} صنف محدد</span>
          <span className="text-xs text-content/60">
            إجمالي مقترح {q(pickedRows.reduce((s, r) => s + (r.suggested_buy || 0), 0))} وحدة
          </span>
          {pickedUnconfirmed.length > 0 && !locked && (
            <button type="button" className={btnGhost} disabled={confirmPickedM.isPending}
              onClick={() => confirmPickedM.mutate(pickedUnconfirmed)}
              title="تأكيد مطابقة الأسطر المحددة غير المؤكدة — يتعلّمها النظام لهذا المورد">
              ✓ تأكيد المحدد ({pickedUnconfirmed.length})</button>)}
          <button type="button" className="text-content/50 hover:text-primary text-xs" onClick={() => setPicked({})}>إلغاء التحديد</button>
          <button type="button" className={`${btnPrimary} mr-auto`} onClick={() => setOrdering(true)}>
            بناء طلب الشراء ←
          </button>
        </div>
      )}

      {ordering && (
        <OrderPanel lines={orderLines} supplierId={batch?.supplier} supplierName={batch?.supplier_display}
          onClose={() => setOrdering(false)}
          onCommitted={() => { refresh(); setPicked({}) }} />
      )}
    </div>
  )
}

// Which catalog items this supplier line offers — ONE control: tick = add, untick = remove,
// several ticks split the line (one row per item, same price / bonus / expiry). The vendor
// spelling is learned only for a one-to-one match.
function ItemPicks({ r, batchId, group, saving, onSetItems, locked }) {
  const picks = group.filter(x => x.item_id).map(x => ({ id: x.item_id, name: x.item_name, code: x.item_softech_id }))
  const ids = picks.map(p => p.id)
  const matchesQ = useQuery({
    queryKey: ['supply-avail-matches', batchId, r.group_id],
    queryFn: () => supplyApi.availMatches(batchId, r.group_id).then(res => res.data),
  })
  const cands = [...picks.map(p => ({ item_id: p.id, item_name: p.name, item_softech_id: p.code, score: null })),
    ...(matchesQ.data || []).filter(m => !ids.includes(m.item_id))]
  const toggle = (iid) => !locked && onSetItems(ids.includes(iid) ? ids.filter(x => x !== iid) : [...ids, iid])
  if (locked) {
    return (
      <div className="text-xs text-content/70">
        أصناف هذا السطر: {picks.map(p => `${p.code} ${p.name}`).join(' · ') || '—'}
        <span className="text-content/50"> · 🔒 القائمة نهائية — افتحها لتغيير المطابقة</span>
      </div>
    )
  }
  return (
    <div className="space-y-2 max-w-3xl">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-content/60">أصناف هذا السطر:</span>
        {picks.length === 0 && <span className="text-amber-700">لا شيء بعد — علِّم صنفاً أو أكثر</span>}
        {picks.map(p => (
          <span key={p.id} className="inline-flex items-center gap-1 rounded-full border border-primary/40 bg-primary/5 px-2 py-0.5">
            <span className="font-mono text-content/50">{p.code}</span>{p.name}
            <button type="button" disabled={saving} onClick={() => toggle(p.id)} title="إزالة"
              className="text-content/50 hover:text-rose-700 disabled:opacity-40">✕</button>
          </span>
        ))}
        {picks.length > 1 && <span className="text-content/50">· السطر مقسوم: صف لكل صنف بنفس السعر والبونص</span>}
        {saving && <span className="text-content/50">جاري الحفظ…</span>}
      </div>
      <table className="w-full text-xs bg-surface rounded border border-line">
        <tbody>
          {matchesQ.isLoading && <tr><td className="p-2 text-content/50">جاري البحث عن الأصناف المحتملة…</td></tr>}
          {cands.map(c => {
            const on = ids.includes(c.item_id)
            return (
              <tr key={c.item_id} onClick={() => !saving && toggle(c.item_id)}
                className={`border-t border-line cursor-pointer hover:bg-surface-2 ${on ? 'bg-primary/10' : ''}`}>
                <td className="px-2 py-1 w-8 text-center">
                  <input type="checkbox" readOnly checked={on} disabled={saving}
                    className="h-4 w-4 pointer-events-none accent-[rgb(var(--c-brand-600))]" />
                </td>
                <td className="px-2 py-1 font-mono w-20">{c.item_softech_id}</td>
                <td className="px-2 py-1">{c.item_name}</td>
                <td className="px-2 py-1 w-14 text-center text-content/50">{c.score == null ? '' : pct(c.score)}</td>
                <td className="px-2 py-1 w-16 text-center">
                  {!(on && ids.length === 1) && (
                    <button type="button" disabled={saving} title="هذا الصنف وحده بدل المختار"
                      onClick={e => { e.stopPropagation(); onSetItems([c.item_id]) }}
                      className="underline text-content/60 hover:text-primary disabled:opacity-40">فقط هذا</button>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="max-w-md">
        <label className="text-[11px] text-content/60">إضافة صنف آخر لهذا السطر</label>
        <ItemSearchInput onSelect={item => item?.item_id && !ids.includes(item.item_id) && onSetItems([...ids, item.item_id])}
          placeholder="ابحث بالاسم أو الكود…" />
      </div>
    </div>
  )
}

const TRUST_TONE = (t) => (t >= 90 ? 'bg-emerald-500' : t >= 70 ? 'bg-amber-400' : 'bg-rose-500')

function Row({ r, picked, onPick, expanded, onToggle, onConfirm, onSetItems, batchId, group, saving, locked, kb }) {
  const muted = r.state === 'not_needed'
  const needsMatch = r.state === 'needs_match'
  return (
    <>
      <tr ref={kb?.ref} onMouseDown={kb?.onMouseDown} data-kb-active={kb?.['data-kb-active']}
        className={`border-b border-line/60 ${needsMatch ? 'bg-amber-50/60' : ''} ${muted ? 'opacity-60' : ''} ${kb?.className || ''}`}>
        <td className="text-center py-1.5">
          <input type="checkbox" checked={picked} disabled={!r.item_id} onChange={e => onPick(e.target.checked)} />
        </td>
        <td className="py-1.5 px-2 align-top">
          <button type="button" onClick={onToggle} dir="auto"
            className="text-right text-content/80 hover:text-primary whitespace-normal break-words block w-full">{r.raw_text}</button>
        </td>
        <td className="py-1.5 px-2 align-top">
          {r.item_id ? (
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <span className="text-content whitespace-normal break-words">{r.item_name}</span>
              <span className="font-mono text-[11px] text-content/45">{r.item_softech_id}</span>
              {r.is_confirmed
                ? <Chip tone="emerald" title="مطابقة مؤكدة">مؤكد</Chip>
                : <>
                    <span className="text-[11px] text-content/50">{pct(r.match_score)}</span>
                    {!locked && (
                      <button type="button" onClick={onConfirm} title="تأكيد المطابقة (يتعلّمها النظام لهذا المورد)"
                        className="text-[11px] px-1.5 rounded border border-line hover:border-primary whitespace-nowrap">تأكيد</button>)}
                  </>}
            </div>
          ) : (
            <button type="button" onClick={onToggle} className="text-xs text-amber-700 underline">اختر الصنف…</button>
          )}
        </td>
        <td className="py-1.5 px-2 text-center">
          {r.item_id ? (
            <div className="flex items-center gap-1 justify-center" title={`الثقة ${r.trust}/100`}>
              <span className="tabular-nums text-xs w-7">{r.trust}</span>
              <span className="h-1.5 w-10 rounded-full bg-line overflow-hidden">
                <span className={`block h-full ${TRUST_TONE(r.trust)}`} style={{ width: `${r.trust}%` }} />
              </span>
            </div>
          ) : '—'}
        </td>
        <td className="py-1.5 px-2 text-center text-xs tabular-nums">{r.item_id && r.approvals ? r.approvals : '—'}</td>
        <td className="py-1.5 px-2 text-center">{q(r.supplier_qty)}</td>
        <td className="py-1.5 px-2 text-center text-xs">
          {money(r.price)}{r.foc_qty ? <span className="text-emerald-700"> +{q(r.foc_qty)}</span> : ''}
        </td>
        <td className="py-1.5 px-2 text-center text-xs">{money(r.offer_effective_cost)}</td>
        <td className="py-1.5 px-2 text-center">{q(r.required)}</td>
        <td className="py-1.5 px-2 text-center">{q(r.current_stock)}</td>
        <td className="py-1.5 px-2 text-center">{r.internal_cover ? q(r.internal_cover) : '—'}</td>
        {/* A buy figure is only meaningful once the match is trusted. */}
        <td className="py-1.5 px-2 text-center font-bold text-primary">
          {r.item_id && !needsMatch ? q(r.suggested_buy) : '—'}
        </td>
        <td className="py-1.5 px-2">
          <div className="flex flex-wrap gap-1">
            {group.length > 1 && (
              <Chip tone="teal" title={`سطر المورد «${r.raw_text}» مطابق لـ ${group.length} أصناف — صف لكل صنف`}>
                سطر مقسوم {group.findIndex(x => x.line_id === r.line_id) + 1}/{group.length}
              </Chip>)}
            {r.learned && !r.is_confirmed && (
              <Chip tone="teal" title="طابق من ذاكرة النظام — أكّده شخص لهذا الاسم من قبل">
                {r.learned_group ? 'من الذاكرة · عدة أصناف' : 'من الذاكرة'}
              </Chip>)}
            {r.via === 'barcode' && <Chip tone="emerald" title="طابق بباركود الصنف الموجود في سطر المورد">باركود</Chip>}
            {r.via === 'vendor_code' && (
              <Chip tone="emerald" title={`كود المورد ${r.supplier_item_code} اعتُمد لهذا الصنف من قبل`}>كود المورد</Chip>)}
            {r.flags.includes('vendor_code_conflict') && (
              <Chip tone="rose" title={`كود المورد ${r.vendor_code_conflict?.code || r.supplier_item_code} معتمد لصنف آخر: ${r.vendor_code_conflict?.item_name || ''}`}>
                كود المورد لصنف آخر</Chip>)}
            {r.main_supplier && <Chip tone="indigo" title="هذا المورد هو المورد الأساسي للصنف في SOFTECH">المورد الأساسي</Chip>}
            {r.flags.includes('urgent') && <Chip tone="rose">عاجل</Chip>}
            {r.flags.includes('unmatched') && <Chip tone="rose">غير مطابق</Chip>}
            {r.flags.includes('low_confidence') && <Chip tone="amber">ثقة منخفضة</Chip>}
            {r.flags.includes('strength_mismatch') && (
              <Chip tone="rose" title="رقم التركيز في رسالة المورد غير موجود في اسم الصنف المطابق">تركيز مختلف</Chip>)}
            {r.flags.includes('form_mismatch') && (
              <Chip tone="rose" title="الشكل الصيدلي في الرسالة يختلف عن الصنف المطابق">شكل صيدلي مختلف</Chip>)}
            {r.flags.includes('head_mismatch') && (
              <Chip tone="rose" title="اسم الدواء في الرسالة لا يطابق بداية اسم الصنف">قد يكون صنفاً آخر</Chip>)}
            {r.flags.includes('ambiguous') && (
              <Chip tone="amber" title="صنف من علامة تجارية أخرى حصل على درجة مقاربة — اختر يدوياً">أكثر من صنف محتمل</Chip>)}
            {r.flags.includes('price_above_history') && (
              <Chip tone="amber" title={`أفضل صفقة سابقة ${money(r.better_historical_deal?.effective_cost)} (${r.better_historical_deal?.date || ''})`}>
                أغلى من السابق {r.better_historical_deal?.gap_pct}%
              </Chip>)}
            {r.waiting_customers_qty > 0 && <Chip tone="violet">عملاء منتظرون {q(r.waiting_customers_qty)}</Chip>}
            {r.state === 'not_needed' && <Chip>غير مطلوب</Chip>}
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-line bg-primary/5">
          <td />
          <td colSpan={12} className="py-2 px-2 space-y-2">
            <ItemPicks r={r} batchId={batchId} group={group} saving={saving} onSetItems={onSetItems} locked={locked} />
            {r.branches?.length > 0 && (
              <div className="flex flex-wrap gap-1.5 text-xs">
                <span className="text-content/60">احتياج الفروع المحددة:</span>
                {r.branches.map(b => (
                  <span key={b.branch_id} className="rounded border border-line px-1.5 py-0.5">
                    {b.branch_name.split(',')[0]}: <b>{q(b.required)}</b>
                    <span className="text-content/50"> (رصيد {q(b.current_stock)})</span>
                  </span>
                ))}
              </div>
            )}
            {r.reasons?.length > 0 && (
              <ul className="text-xs text-content/80 list-disc pr-5 space-y-0.5">
                {r.reasons.map((x, i) => <li key={i}>{x}</li>)}
              </ul>
            )}
            {r.historical_best && (
              <div className="text-xs text-content/60">
                أفضل تكلفة فعلية سابقة: {money(r.historical_best.effective_cost)}
                {r.historical_best.foc ? ` (مع بونص ${q(r.historical_best.foc)})` : ''} — {r.historical_best.date || ''}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}
