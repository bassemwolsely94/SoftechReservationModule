/**
 * MarketShortagePage — نواقص السوق (Market Shortage detector + revision workflow)
 *
 * Tabs: التغييرات (delta since last run) · المرشحون · المؤكدة · المستبعدة.
 * Confirm / revert / dismiss-with-reason (+ matching product) / retrieve,
 * filter by general classification, Excel export, WhatsApp copy, recovery &
 * auto-detectable flags.
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { purchasingApi } from '../api/client'

const daysBehind = (d) => { if (!d) return null; const ms = Date.now() - new Date(d).getTime(); return Math.max(0, Math.floor(ms / 86400000)) }

/* ── Run status + engine controls (reuses the purchasing demand engine) ──── */
function RunControls() {
  const qc = useQueryClient()
  const [details, setDetails] = useState(false)
  const { data: active } = useQuery({
    queryKey: ['purchasing-active-run'],
    queryFn: () => purchasingApi.activeRun().then(r => r.data).catch(() => null),
    refetchInterval: (q) => (q.state.data && q.state.data.id ? 4000 : false),
  })
  const { data: last } = useQuery({
    queryKey: ['purchasing-latest-run'],
    queryFn: () => purchasingApi.latestRun().then(r => r.data).catch(() => null),
  })
  const running = !!(active && active.id && ['running', 'pending', 'started'].includes(active.status))
  const wasRunning = useRef(running)
  useEffect(() => {
    if (wasRunning.current && !running) {   // a run just finished → refresh everything
      ;['purchasing-latest-run', 'shortage-candidates', 'shortage-deltas', 'shortage-confirmed', 'shortage-dismissed']
        .forEach(k => qc.invalidateQueries({ queryKey: [k] }))
    }
    wasRunning.current = running
  }, [running, qc])
  const run = useMutation({ mutationFn: () => purchasingApi.triggerRun({}), onSuccess: () => qc.invalidateQueries({ queryKey: ['purchasing-active-run'] }) })
  const sync = useMutation({ mutationFn: () => purchasingApi.catchupSync(), onSuccess: () => qc.invalidateQueries({ queryKey: ['purchasing-active-run'] }) })

  const behind = daysBehind(last?.data_through_date)
  const okData = behind !== null && behind <= 1
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 mb-5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {running ? (
          <span className="text-sm text-brand-600 font-semibold flex items-center gap-2">
            <span className="inline-block w-2 h-2 rounded-full bg-brand-600 animate-pulse" /> جارٍ تشغيل المحرك…{active?.progress ? ` ${active.progress}%` : ''}
          </span>
        ) : last ? (
          <span className="text-sm text-gray-600">
            آخر تشغيل: <b>{(last.calc_date || last.started_at || '').slice(0, 10)}</b>
            <span className={last.status === 'success' ? 'text-emerald-600' : 'text-red-600'}> · {last.status_display || last.status}</span>
            {last.data_through_date && <span className={okData ? 'text-gray-500' : 'text-amber-600 font-semibold'}> · المبيعات حتى {last.data_through_date.slice(0, 10)}{!okData && behind !== null ? ` (متأخرة ${behind} يوم)` : ''}</span>}
          </span>
        ) : <span className="text-sm text-gray-400">لا يوجد تشغيل سابق</span>}

        <div className="mr-auto flex gap-2">
          <button onClick={() => setDetails(d => !d)} className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">تفاصيل آخر تشغيل</button>
          {!okData && <button onClick={() => sync.mutate()} disabled={running || sync.isPending} className="px-3 py-1.5 text-sm border border-amber-300 text-amber-700 rounded-lg hover:bg-amber-50 disabled:opacity-50">{sync.isPending ? '…' : '⏬ مزامنة المبيعات'}</button>}
          <button onClick={() => run.mutate()} disabled={running || run.isPending} className="px-4 py-1.5 text-sm bg-brand-600 text-white rounded-lg hover:opacity-90 disabled:opacity-50">{run.isPending || running ? 'جارٍ…' : '🔄 تشغيل المحرك ومزامنة البيانات'}</button>
        </div>
      </div>
      {details && last && (
        <div className="mt-3 pt-3 border-t border-gray-100 grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
          <div><p className="text-gray-400">الحالة</p><p className="font-semibold">{last.status_display || last.status}</p></div>
          <div><p className="text-gray-400">المبيعات حتى</p><p className="font-semibold">{last.data_through_date?.slice(0, 10) || '—'}</p></div>
          <div><p className="text-gray-400">SOFTECH متاح</p><p className="font-semibold">{last.softech_available ? 'نعم' : 'لا (احتياطي PG)'}</p></div>
          <div><p className="text-gray-400">أصناف/صفوف</p><p className="font-semibold tabular-nums">{(last.items_processed ?? 0).toLocaleString()} / {(last.rows_written ?? 0).toLocaleString()}</p></div>
          <div><p className="text-gray-400">المدة</p><p className="font-semibold tabular-nums">{last.duration_seconds ? `${Math.round(last.duration_seconds)}s` : '—'}</p></div>
          {last.error_message && <div className="col-span-full text-red-600">خطأ: {last.error_message}</div>}
        </div>
      )}
    </div>
  )
}

const TIERS = [
  { key: '1', label: '١ — نفاد مؤكد', cls: 'bg-red-100 text-red-700 border-red-200' },
  { key: '2', label: '٢ — نقص حاد',   cls: 'bg-orange-100 text-orange-700 border-orange-200' },
  { key: '3', label: '٣ — مراقبة',    cls: 'bg-amber-100 text-amber-700 border-amber-200' },
]
const tierMeta = (t) => TIERS.find(x => t?.startsWith(x.key)) || TIERS[2]
const egp = (n) => (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const invalidate = (qc) => ['shortage-candidates', 'shortage-confirmed', 'shortage-dismissed',
  'shortage-deltas', 'shortage-medtypes'].forEach(k => qc.invalidateQueries({ queryKey: [k] }))

// ── Sortable-table helpers (shared) ──────────────────────────────────────────
function useSort(initKey = '', initDir = 'desc') {
  const [key, setKey] = useState(initKey)
  const [dir, setDir] = useState(initDir)
  const toggle = (k, numeric = true) => {
    if (k === key) setDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setKey(k); setDir(numeric ? 'desc' : 'asc') }   // numeric → biggest first; text → A→Z
  }
  return { key, dir, toggle }
}
function applySort(rows, sort, acc) {
  if (!sort.key || !acc[sort.key]) return rows
  const f = acc[sort.key]
  const out = [...rows].sort((a, b) => {
    const x = f(a), y = f(b)
    if (typeof x === 'number' && typeof y === 'number') return x - y
    return String(x ?? '').localeCompare(String(y ?? ''), 'ar')
  })
  return sort.dir === 'asc' ? out : out.reverse()
}
function Th({ label, k, sort, numeric = true, cls = '' }) {
  const on = sort.key === k
  return (
    <th onClick={() => sort.toggle(k, numeric)}
      className={`px-3 py-2 font-semibold cursor-pointer select-none whitespace-nowrap hover:text-brand-600 ${cls}`}>
      {label}<span className={on ? 'text-brand-600' : 'text-gray-300'}>{on ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ' ⇅'}</span>
    </th>
  )
}

// Client-side filter shared by every tab (instant, no refetch).
const matchFilter = (r, med, q) => {
  if (med && (r.med_type_code || '') !== med) return false
  if (q) {
    const s = q.trim().toLowerCase()
    if (!(`${r.name}`.toLowerCase().includes(s) || `${r.code}`.toLowerCase().includes(s))) return false
  }
  return true
}

function downloadArrayBuffer(data, filename) {
  const blob = new Blob([data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: filename })
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}

function TierBadge({ tier }) {
  const m = tierMeta(tier)
  return <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${m.cls} whitespace-nowrap`}>{m.label}</span>
}

/* ── Dismiss modal (reason + note + matching product) ────────────────────── */
function DismissModal({ item, onClose }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('variant')
  const [note, setNote] = useState('')
  const [matchQ, setMatchQ] = useState('')
  const [matches, setMatches] = useState([])   // up to 2 matching products
  const REASONS = [
    ['variant', 'مقاس/شكل بديل لمنتج متاح'],
    ['on_request', 'يُطلب عند الحاجة فقط'],
    ['obsolete', 'غير متوفر بالسوق المصري'],
    ['not_shortage', 'ليس نقصًا (موقوف/موسمي)'],
    ['other', 'أخرى'],
  ]
  const { data: search } = useQuery({
    queryKey: ['shortage-search', matchQ],
    queryFn: () => purchasingApi.shortageSearch(matchQ).then(r => r.data),
    enabled: reason === 'variant' && matchQ.trim().length >= 2,
  })
  const { data: sugg } = useQuery({
    queryKey: ['shortage-suggest', item.item_id],
    queryFn: () => purchasingApi.shortageSuggestMatches(item.item_id).then(r => r.data),
    enabled: reason === 'variant',
  })
  const addMatch = (it) => { setMatches(m => m.find(x => x.item_id === it.item_id) || m.length >= 2 ? m : [...m, it]); setMatchQ('') }
  const dismiss = useMutation({
    mutationFn: () => purchasingApi.shortageDismiss({
      item_id: item.item_id, reason, note, matching_item_ids: matches.map(m => m.item_id),
    }),
    onSuccess: () => { invalidate(qc); onClose() },
  })
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6">
        <h3 className="text-lg font-bold mb-1">استبعاد من النواقص</h3>
        <p className="text-sm text-gray-500 mb-4">{item.code} — {item.name}</p>
        <label className="block text-xs font-semibold text-gray-600 mb-1">السبب</label>
        <select value={reason} onChange={e => setReason(e.target.value)}
          className="w-full border rounded-lg px-3 py-2 text-sm mb-3">
          {REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {reason === 'variant' && (
          <div className="mb-3">
            <label className="block text-xs font-semibold text-gray-600 mb-1">المنتج/المنتجات البديلة المتاحة (حتى صنفين)</label>
            {matches.map(m => (
              <div key={m.item_id} className="flex items-center justify-between border rounded-lg px-3 py-2 text-sm bg-emerald-50 mb-1">
                <span><span className="font-mono text-xs text-gray-400">{m.code}</span> — {m.name}</span>
                <button onClick={() => setMatches(x => x.filter(i => i.item_id !== m.item_id))} className="text-xs text-red-600">إزالة</button>
              </div>
            ))}
            {matches.length < 2 && (sugg?.suggestions?.length > 0) && (
              <div className="mb-2">
                <p className="text-xs text-emerald-700 mb-1">💡 بدائل متوفرة مقترحة (نفس الاسم/العائلة):</p>
                <div className="flex flex-wrap gap-1">
                  {sugg.suggestions.slice(0, 6).filter(s => !matches.find(m => m.item_id === s.item_id)).map(s => (
                    <button key={s.item_id} onClick={() => addMatch({ item_id: s.item_id, code: s.code, name: s.name })}
                      className="px-2 py-1 text-xs bg-emerald-50 border border-emerald-200 rounded hover:bg-emerald-100">
                      + {s.name.slice(0, 28)} {s.availability?.ok ? '✓' : `⚠${(s.availability?.missing || []).length}`}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {matches.length < 2 && (
              <>
                <input value={matchQ} onChange={e => setMatchQ(e.target.value)} placeholder="أو ابحث يدويًا…"
                  className="w-full border rounded-lg px-3 py-2 text-sm" />
                {matchQ.trim().length >= 2 && (
                  <div className="mt-1 border rounded-lg divide-y max-h-40 overflow-y-auto">
                    {(search?.items || []).map(it => (
                      <button key={it.item_id} onClick={() => addMatch(it)}
                        className="w-full text-right px-3 py-2 text-sm hover:bg-gray-50">
                        <span className="font-mono text-xs text-gray-400">{it.code}</span> — {it.name}
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
        <label className="block text-xs font-semibold text-gray-600 mb-1">ملاحظة</label>
        <input value={note} onChange={e => setNote(e.target.value)} placeholder="تفاصيل إضافية…"
          className="w-full border rounded-lg px-3 py-2 text-sm mb-4" />
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إلغاء</button>
          <button onClick={() => dismiss.mutate()} disabled={dismiss.isPending}
            className="px-5 py-2 text-sm bg-brand-600 text-white rounded-lg hover:opacity-90 disabled:opacity-50">
            {dismiss.isPending ? 'جارٍ…' : 'استبعاد'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── WhatsApp copy modal ─────────────────────────────────────────────────── */
function WhatsAppModal({ params, onClose }) {
  const [copied, setCopied] = useState(false)
  const [num, setNum] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['shortage-wa', params],
    queryFn: () => purchasingApi.shortageWhatsapp(params).then(r => r.data),
  })
  const copy = async () => {
    try { await navigator.clipboard.writeText(data.text); setCopied(true); setTimeout(() => setCopied(false), 2000) }
    catch { /* clipboard blocked */ }
  }
  const openWa = () => {
    const digits = num.replace(/\D/g, '')
    const url = `https://wa.me/${digits}?text=${encodeURIComponent(data?.text || '')}`
    window.open(url, '_blank', 'noopener')
  }
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" dir="rtl">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-lg font-bold mb-3">📱 إرسال للواتساب</h3>
        <textarea readOnly value={isLoading ? 'جارٍ…' : data?.text || ''}
          className="w-full border rounded-lg p-3 text-sm h-56 resize-none font-mono" dir="rtl" />
        <div className="flex items-center gap-2 mt-3">
          <input value={num} onChange={e => setNum(e.target.value)} placeholder="رقم المورد (مع كود الدولة، مثال 2010…)"
            className="flex-1 border rounded-lg px-3 py-2 text-sm" dir="ltr" />
          <button onClick={openWa} disabled={isLoading} className="px-4 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:opacity-90 disabled:opacity-50 whitespace-nowrap">فتح واتساب</button>
        </div>
        <div className="flex gap-3 justify-end mt-4">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">إغلاق</button>
          <button onClick={copy} disabled={isLoading}
            className="px-5 py-2 text-sm bg-gray-700 text-white rounded-lg hover:opacity-90 disabled:opacity-50">
            {copied ? '✓ تم النسخ' : 'نسخ النص'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Shared toolbar (filter + export + whatsapp) ─────────────────────────── */
function Toolbar({ med, setMed, q, setQ, view }) {
  const [wa, setWa] = useState(false)
  const { data: mt } = useQuery({ queryKey: ['shortage-medtypes'],
    queryFn: () => purchasingApi.shortageMedTypes().then(r => r.data) })
  const exp = useMutation({
    mutationFn: () => purchasingApi.shortageExport({ view, ...(med ? { med } : {}), ...(q ? { q } : {}) }),
    onSuccess: (r) => downloadArrayBuffer(r.data, `market-shortage-${view}.xlsx`),
  })
  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <select value={med} onChange={e => setMed(e.target.value)} className="border rounded-lg px-3 py-1.5 text-sm">
        <option value="">كل التصنيفات</option>
        {(mt?.med_types || []).map(m => <option key={m.code} value={m.code}>{m.label}</option>)}
      </select>
      <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالكود/الاسم…"
        className="border rounded-lg px-3 py-1.5 text-sm w-44" />
      <div className="mr-auto flex gap-2">
        <button onClick={() => exp.mutate()} disabled={exp.isPending}
          className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50">
          {exp.isPending ? '…' : '📥 Excel'}
        </button>
        <button onClick={() => setWa(true)}
          className="px-3 py-1.5 text-sm border border-emerald-300 text-emerald-700 rounded-lg hover:bg-emerald-50">
          📱 واتساب
        </button>
      </div>
      {wa && <WhatsAppModal params={{ view, ...(med ? { med } : {}), ...(q ? { q } : {}) }} onClose={() => setWa(false)} />}
    </div>
  )
}

/* ── Candidate table (shared by candidates + delta sections) ─────────────── */
function CandidateTable({ rows, onConfirm, onDismiss, onNotShortage, confirming }) {
  const sort = useSort()
  const sorted = applySort(rows, sort, {
    tier: r => r.tier, code: r => r.code, name: r => r.name, med: r => r.med_type,
    lost: r => r.lost_monthly, cov: r => r.coverage, supp: r => r.suppression, sod: r => r.stockout_days,
  })
  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[900px]">
        <thead>
          <tr className="text-xs text-gray-500 bg-gray-50 text-right">
            <Th label="التصنيف" k="tier" sort={sort} numeric={false} />
            <Th label="الكود" k="code" sort={sort} numeric={false} />
            <Th label="الصنف" k="name" sort={sort} numeric={false} />
            <Th label="التصنيف العام" k="med" sort={sort} numeric={false} />
            <Th label="خسارة/شهر (ج.م)" k="lost" sort={sort} cls="text-center" />
            <Th label="تغطية" k="cov" sort={sort} cls="text-center" />
            <Th label="قمع" k="supp" sort={sort} cls="text-center" />
            <Th label="أيام نفاد" k="sod" sort={sort} cls="text-center" />
            <th className="px-3 py-2 font-semibold">إجراء</th>
          </tr>
        </thead>
        <tbody>
          {!sorted.length && <tr><td colSpan={9} className="px-3 py-8 text-center text-gray-400">لا توجد أصناف</td></tr>}
          {sorted.map(c => (
            <tr key={c.item_id} className={`border-t border-gray-100 ${c.already_flagged ? 'bg-emerald-50/40' : 'hover:bg-gray-50'}`}>
              <td className="px-3 py-2"><TierBadge tier={c.tier} /></td>
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{c.code}</td>
              <td className="px-3 py-2 font-medium text-gray-800">{c.name}</td>
              <td className="px-3 py-2 text-xs text-gray-500">{c.med_type}</td>
              <td className="px-3 py-2 text-center tabular-nums font-bold text-red-600">{egp(c.lost_monthly)}</td>
              <td className="px-3 py-2 text-center tabular-nums font-semibold text-red-600">{c.coverage.toFixed(2)}</td>
              <td className="px-3 py-2 text-center tabular-nums">{Math.round(c.suppression * 100)}%</td>
              <td className="px-3 py-2 text-center tabular-nums text-gray-500">{c.stockout_days || '—'}</td>
              <td className="px-3 py-2">
                {c.already_flagged ? <span className="text-xs text-emerald-600 font-semibold">✓ مؤكَّد</span> : (
                  <div className="flex items-center gap-1">
                    <button onClick={() => onConfirm(c.item_id)} disabled={confirming}
                      className="px-3 py-1 text-xs bg-brand-600 text-white rounded hover:opacity-90 disabled:opacity-50 whitespace-nowrap">تأكيد</button>
                    <button onClick={() => onNotShortage(c.item_id)}
                      className="px-3 py-1 text-xs text-amber-700 border border-amber-300 rounded hover:bg-amber-50 whitespace-nowrap" title="ليس نقص سوق — ينتقل لقائمة المُراجعة">ليس نقصًا</button>
                    <button onClick={() => onDismiss(c)}
                      className="px-3 py-1 text-xs text-gray-500 border border-gray-300 rounded hover:bg-gray-100 whitespace-nowrap">استبعاد</button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Tab: Candidates ─────────────────────────────────────────────────────── */
function CandidatesTab({ med, q }) {
  const qc = useQueryClient()
  const [tier, setTier] = useState('')
  const [dismissItem, setDismissItem] = useState(null)
  const { data, isLoading } = useQuery({
    queryKey: ['shortage-candidates'],
    queryFn: () => purchasingApi.shortageCandidates({ include_flagged: '0' }).then(r => r.data),
  })
  const confirm = useMutation({ mutationFn: (id) => purchasingApi.shortageFlag({ item_id: id, source: 'auto' }), onSuccess: () => invalidate(qc) })
  const notShortage = useMutation({ mutationFn: (id) => purchasingApi.shortageDismiss({ item_id: id, reason: 'not_shortage' }), onSuccess: () => invalidate(qc) })
  const [sortBy, setSortBy] = useState('severity')
  const counts = data?.tier_counts || {}
  let rows = (data?.candidates || []).filter(c => (!tier || c.tier.startsWith(tier)) && matchFilter(c, med, q))
  if (sortBy === 'lost') rows = [...rows].sort((a, b) => b.lost_monthly - a.lost_monthly)
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-3">
        <button onClick={() => setTier('')} className={`px-3 py-1.5 text-sm rounded-lg border ${!tier ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>الكل ({data?.total ?? '—'})</button>
        {TIERS.map(t => (
          <button key={t.key} onClick={() => setTier(t.key)} className={`px-3 py-1.5 text-sm rounded-lg border ${tier === t.key ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>
            {t.label} ({counts[Object.keys(counts).find(k => k.startsWith(t.key))] ?? 0})
          </button>
        ))}
        <div className="mr-auto flex items-center gap-1 text-sm">
          <span className="text-gray-400 text-xs">ترتيب:</span>
          <button onClick={() => setSortBy('severity')} className={`px-2.5 py-1 text-xs rounded-lg border ${sortBy === 'severity' ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>الأشد</button>
          <button onClick={() => setSortBy('lost')} className={`px-2.5 py-1 text-xs rounded-lg border ${sortBy === 'lost' ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>الأعلى خسارة</button>
        </div>
      </div>
      {isLoading ? <p className="text-gray-400 py-8 text-center">جارٍ التحميل…</p> :
        <CandidateTable rows={rows} confirming={confirm.isPending}
          onConfirm={id => confirm.mutate(id)} onNotShortage={id => notShortage.mutate(id)} onDismiss={setDismissItem} />}
      <p className="text-xs text-gray-400 mt-2">التغطية = المخزون ÷ متوسط الطلب الشهري. قمع = انخفاض مبيعات آخر ٣٠ يوم عن المعدل السنوي. «ليس نقصًا» ينقل الصنف لقائمة المُراجعة.</p>
      {dismissItem && <DismissModal item={dismissItem} onClose={() => setDismissItem(null)} />}
    </div>
  )
}

/* ── Tab: Changes (delta) ────────────────────────────────────────────────── */
function DeltaSection({ title, hint, rows, tone, children }) {
  return (
    <div className="mb-6">
      <h3 className={`text-sm font-bold mb-1 ${tone}`}>{title} <span className="text-gray-400 font-normal">({rows.length})</span></h3>
      <p className="text-xs text-gray-400 mb-2">{hint}</p>
      {children}
    </div>
  )
}
function ChangesTab({ med, q }) {
  const qc = useQueryClient()
  const [dismissItem, setDismissItem] = useState(null)
  const { data, isLoading } = useQuery({ queryKey: ['shortage-deltas'],
    queryFn: () => purchasingApi.shortageDeltas().then(r => r.data) })
  const confirm = useMutation({ mutationFn: (id) => purchasingApi.shortageFlag({ item_id: id, source: 'auto' }), onSuccess: () => invalidate(qc) })
  const notShortage = useMutation({ mutationFn: (id) => purchasingApi.shortageDismiss({ item_id: id, reason: 'not_shortage' }), onSuccess: () => invalidate(qc) })
  const clear = useMutation({ mutationFn: (id) => purchasingApi.shortageUnflag(id), onSuccess: () => invalidate(qc) })
  const retrieve = useMutation({ mutationFn: (id) => purchasingApi.shortageRetrieve(id), onSuccess: () => invalidate(qc) })
  if (isLoading) return <p className="text-gray-400 py-8 text-center">جارٍ التحميل…</p>
  const flt = (arr) => (arr || []).filter(c => matchFilter(c, med, q))
  const newRows = flt(data.new), recovering = flt(data.recovering), reEntered = flt(data.re_entered)
  return (
    <div>
      {!data?.has_baseline && <div className="mb-4 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">أول لقطة للمقارنة — كل المرشحين يظهرون كـ"جديد". ستظهر الفروق الحقيقية بعد تشغيل المحرك مرة أخرى.</div>}
      <DeltaSection title="🆕 نواقص جديدة" tone="text-red-600" rows={newRows}
        hint="أصناف دخلت النقص منذ آخر تشغيل — للمراجعة والتأكيد.">
        <CandidateTable rows={newRows} confirming={confirm.isPending} onConfirm={id => confirm.mutate(id)} onNotShortage={id => notShortage.mutate(id)} onDismiss={setDismissItem} />
      </DeltaSection>
      <DeltaSection title="🔄 قد يكون توفّر" tone="text-emerald-600" rows={recovering}
        hint="أصناف مؤكدة عاد مخزونها ومبيعاتها للطبيعي — راجِعها وأزِل النقص إن توفّرت.">
        <div className="bg-white rounded-xl border border-gray-200 divide-y">
          {!recovering.length && <p className="px-3 py-4 text-sm text-gray-400 text-center">لا شيء</p>}
          {recovering.map(c => (
            <div key={c.item_id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span><span className="font-mono text-xs text-gray-400">{c.code}</span> — {c.name}
                <span className="text-xs text-emerald-600 mr-2">تغطية {c.coverage.toFixed(1)} شهر</span></span>
              <button onClick={() => clear.mutate(c.item_id)} className="px-3 py-1 text-xs text-emerald-700 border border-emerald-300 rounded hover:bg-emerald-50">أزل النقص (توفّر)</button>
            </div>
          ))}
        </div>
      </DeltaSection>
      <DeltaSection title="↩️ عاد للنقص (كان مُستبعدًا)" tone="text-orange-600" rows={reEntered}
        hint="أصناف كنت استبعدتها لكنها تُظهر إشارة نقص قوية جديدة — راجِع إن كانت عادت فعلاً.">
        <div className="bg-white rounded-xl border border-gray-200 divide-y">
          {!reEntered.length && <p className="px-3 py-4 text-sm text-gray-400 text-center">لا شيء</p>}
          {reEntered.map(c => (
            <div key={c.item_id} className="flex items-center justify-between px-4 py-2 text-sm">
              <span><TierBadge tier={c.tier} /> <span className="font-mono text-xs text-gray-400 mr-1">{c.code}</span> — {c.name}</span>
              <button onClick={() => retrieve.mutate(c.item_id)} className="px-3 py-1 text-xs text-orange-700 border border-orange-300 rounded hover:bg-orange-50">استرجاع للمراجعة</button>
            </div>
          ))}
        </div>
      </DeltaSection>
      {dismissItem && <DismissModal item={dismissItem} onClose={() => setDismissItem(null)} />}
    </div>
  )
}

/* ── Manual add box (confirmed tab) ──────────────────────────────────────── */
function ManualAdd() {
  const qc = useQueryClient()
  const [q, setQ] = useState(''); const [note, setNote] = useState('')
  const { data } = useQuery({ queryKey: ['shortage-search', q],
    queryFn: () => purchasingApi.shortageSearch(q).then(r => r.data), enabled: q.trim().length >= 2 })
  const add = useMutation({ mutationFn: (id) => purchasingApi.shortageFlag({ item_id: id, note, source: 'manual' }),
    onSuccess: () => { setQ(''); setNote(''); invalidate(qc) } })
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
      <p className="text-sm font-semibold text-gray-700 mb-2">➕ إضافة صنف ناقص يدويًا (كوتة / لا يوجد بالموردين)</p>
      <div className="flex flex-wrap gap-2">
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="ابحث بالكود أو الاسم…" className="border rounded-lg px-3 py-2 text-sm flex-1 min-w-[200px]" />
        <input value={note} onChange={e => setNote(e.target.value)} placeholder="ملاحظة" className="border rounded-lg px-3 py-2 text-sm w-40" />
      </div>
      {q.trim().length >= 2 && (
        <div className="mt-2 border rounded-lg divide-y max-h-56 overflow-y-auto">
          {(data?.items || []).map(it => (
            <div key={it.item_id} className="flex items-center justify-between px-3 py-2 text-sm hover:bg-gray-50">
              <span><span className="font-mono text-xs text-gray-400">{it.code}</span> — {it.name}</span>
              {it.in_shortage ? <span className="text-xs text-emerald-600 font-semibold">مُضاف</span>
                : <button onClick={() => add.mutate(it.item_id)} disabled={add.isPending} className="px-3 py-1 text-xs bg-brand-600 text-white rounded hover:opacity-90 disabled:opacity-50">إضافة</button>}
            </div>
          ))}
          {data && !data.items.length && <div className="px-3 py-3 text-xs text-gray-400">لا نتائج</div>}
        </div>
      )}
    </div>
  )
}

/* ── Tab: Confirmed ──────────────────────────────────────────────────────── */
function ConfirmedTab({ med, q }) {
  const qc = useQueryClient()
  const [dismissItem, setDismissItem] = useState(null)
  const { data, isLoading } = useQuery({ queryKey: ['shortage-confirmed', ''],
    queryFn: () => purchasingApi.shortageConfirmed().then(r => r.data) })
  const clear = useMutation({ mutationFn: (id) => purchasingApi.shortageUnflag(id), onSuccess: () => invalidate(qc) })
  const sort = useSort()
  const items = applySort((data?.items || []).filter(r => matchFilter(r, med, q)), sort, {
    code: r => r.code, name: r => r.name, med: r => r.med_type,
    lost: r => r.lost_monthly, source: r => r.source, waiting: r => r.waiting_customers || 0,
  })
  return (
    <div>
      <ManualAdd />
      <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
        <table className="w-full text-sm min-w-[760px]">
          <thead>
            <tr className="text-xs text-gray-500 bg-gray-50 text-right">
              <Th label="الكود" k="code" sort={sort} numeric={false} /><Th label="الصنف" k="name" sort={sort} numeric={false} />
              <Th label="التصنيف العام" k="med" sort={sort} numeric={false} />
              <Th label="خسارة/شهر" k="lost" sort={sort} cls="text-center" />
              <Th label="المصدر" k="source" sort={sort} numeric={false} />
              <th className="px-3 py-2 font-semibold">الحالة</th><th className="px-3 py-2 font-semibold">ملاحظة</th>
              <th className="px-3 py-2 font-semibold">إجراء</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">جارٍ…</td></tr>}
            {!isLoading && !items.length && <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">لا توجد أصناف مؤكدة</td></tr>}
            {items.map(it => (
              <tr key={it.item_id} className="border-t border-gray-100 hover:bg-gray-50">
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{it.code}</td>
                <td className="px-3 py-2 font-medium text-gray-800">{it.name}</td>
                <td className="px-3 py-2 text-xs text-gray-500">{it.med_type}</td>
                <td className="px-3 py-2 text-center tabular-nums font-bold text-red-600">{it.lost_monthly ? egp(it.lost_monthly) : '—'}</td>
                <td className="px-3 py-2"><span className={`text-xs px-2 py-0.5 rounded-full ${it.source === 'manual' ? 'bg-sky-100 text-sky-700' : 'bg-gray-100 text-gray-600'}`}>{it.source === 'manual' ? 'يدوي' : 'من المحرك'}</span></td>
                <td className="px-3 py-2">
                  {it.possibly_resolved && <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 whitespace-nowrap">🔄 قد يكون توفّر</span>}
                  {it.autodetectable > 0 && <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-700 whitespace-nowrap block mt-0.5">أصبح قابلاً للاكتشاف</span>}
                  {data?.softech_write_enabled && !it.softech_synced && <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 whitespace-nowrap block mt-0.5" title="لم يصل بعد إلى سوفتك — سيُعاد المحاولة">⏳ بانتظار سوفتك</span>}
                  {it.waiting_customers > 0 && <span className="text-xs px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 whitespace-nowrap block mt-0.5" title="حجوزات قيد الانتظار لهذا الصنف">👥 {it.waiting_customers} عميل منتظر</span>}
                </td>
                <td className="px-3 py-2 text-gray-500 text-xs">{it.note || '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex gap-1">
                    <button onClick={() => clear.mutate(it.item_id)} className="px-3 py-1 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50 whitespace-nowrap">تراجع</button>
                    <button onClick={() => setDismissItem({ item_id: it.item_id, code: it.code, name: it.name })} className="px-3 py-1 text-xs text-gray-500 border border-gray-300 rounded hover:bg-gray-100 whitespace-nowrap">استبعاد</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {dismissItem && <DismissModal item={dismissItem} onClose={() => setDismissItem(null)} />}
    </div>
  )
}

/* ── Tab: Dismissed ──────────────────────────────────────────────────────── */
function DismissedTab({ med, q }) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const { data, isLoading } = useQuery({ queryKey: ['shortage-dismissed'],
    queryFn: () => purchasingApi.shortageDismissed().then(r => r.data) })
  const retrieve = useMutation({ mutationFn: (id) => purchasingApi.shortageRetrieve(id), onSuccess: () => invalidate(qc) })
  const sort = useSort('', 'asc')
  const items = applySort((data?.items || []).filter(r => (!reason || r.reason === reason) && matchFilter(r, med, q)), sort, {
    code: r => r.code, name: r => r.name, reason: r => r.reason_label,
  })
  const reasonCounts = (data?.items || []).reduce((a, r) => { a[r.reason] = (a[r.reason] || 0) + 1; return a }, {})
  return (
    <div>
    <div className="flex flex-wrap gap-2 mb-3">
      <button onClick={() => setReason('')} className={`px-3 py-1.5 text-sm rounded-lg border ${!reason ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>الكل ({data?.count ?? 0})</button>
      {(data?.reasons || []).map(([v, l]) => (
        <button key={v} onClick={() => setReason(v)} className={`px-3 py-1.5 text-sm rounded-lg border ${reason === v ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-600'}`}>{l} ({reasonCounts[v] || 0})</button>
      ))}
    </div>
    <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
      <table className="w-full text-sm min-w-[820px]">
        <thead>
          <tr className="text-xs text-gray-500 bg-gray-50 text-right">
            <Th label="الكود" k="code" sort={sort} numeric={false} /><Th label="الصنف" k="name" sort={sort} numeric={false} />
            <Th label="السبب" k="reason" sort={sort} numeric={false} /><th className="px-3 py-2 font-semibold">المنتج البديل</th>
            <th className="px-3 py-2 font-semibold">ملاحظة</th><th className="px-3 py-2 font-semibold">إجراء</th>
          </tr>
        </thead>
        <tbody>
          {isLoading && <tr><td colSpan={6} className="px-3 py-8 text-center text-gray-400">جارٍ…</td></tr>}
          {!isLoading && !items.length && <tr><td colSpan={6} className="px-3 py-8 text-center text-gray-400">لا توجد أصناف مُستبعدة</td></tr>}
          {items.map(it => (
            <tr key={it.item_id} className="border-t border-gray-100 hover:bg-gray-50">
              <td className="px-3 py-2 font-mono text-xs text-gray-500">{it.code}</td>
              <td className="px-3 py-2 font-medium text-gray-800">{it.name}</td>
              <td className="px-3 py-2"><span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">{it.reason_label}</span></td>
              <td className="px-3 py-2 text-xs">
                {!it.matching?.length ? <span className="text-gray-400">—</span> : (
                  <div className="space-y-0.5">
                    {it.matching.map(m => (
                      <div key={m.item_id} className="flex items-center gap-1">
                        <span className="text-gray-600"><span className="font-mono text-gray-400">{m.code}</span> {m.name}</span>
                        {m.availability?.ok
                          ? <span className="text-emerald-600" title="متوفر بكل الفروع">✓</span>
                          : <span className="text-red-600" title={`ناقص بفروع: ${(m.availability?.missing || []).join('، ')}`}>⚠ {(m.availability?.missing || []).length} فرع</span>}
                      </div>
                    ))}
                  </div>
                )}
              </td>
              <td className="px-3 py-2 text-xs text-gray-500">{it.note || '—'}</td>
              <td className="px-3 py-2"><button onClick={() => retrieve.mutate(it.item_id)} className="px-3 py-1 text-xs text-brand-600 border border-brand-200 rounded hover:bg-brand-50 whitespace-nowrap">استرجاع</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </div>
  )
}

/* ── Tab: Trends (#9) ────────────────────────────────────────────────────── */
function TrendsTab() {
  const { data } = useQuery({ queryKey: ['shortage-trends'], queryFn: () => purchasingApi.shortageTrends().then(r => r.data) })
  if (!data) return <p className="text-gray-400 py-8 text-center">جارٍ التحميل…</p>
  const maxClass = Math.max(1, ...data.by_class.map(c => c.count))
  const maxSeries = Math.max(1, ...data.series.map(s => s.candidates))
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-red-50/40 rounded-xl border border-red-200 p-4"><p className="text-xs text-gray-500">💸 إجمالي الخسارة الشهرية</p><p className="text-2xl font-bold text-red-600 tabular-nums">{egp(data.total_lost)}</p></div>
        {data.by_tier.map(t => (
          <div key={t.tier} className="bg-white rounded-xl border border-gray-200 p-4"><p className="text-xs text-gray-500">{tierMeta(t.tier).label}</p><p className="text-2xl font-bold tabular-nums text-gray-800">{t.count}</p></div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <p className="font-semibold text-gray-700 mb-3">النواقص حسب التصنيف العام</p>
        {data.by_class.map(c => (
          <div key={c.label} className="mb-2.5">
            <div className="flex justify-between text-sm mb-0.5"><span className="text-gray-700">{c.label}</span><span className="text-gray-500 tabular-nums">{c.count} صنف · <span className="text-red-600 font-semibold">{egp(c.lost)}</span> ج.م/شهر</span></div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden"><div className="h-2 bg-brand-600 rounded-full" style={{ width: `${(c.count / maxClass) * 100}%` }} /></div>
          </div>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <p className="font-semibold text-gray-700 mb-3">تطوّر عدد النواقص (لكل تشغيل للمحرك)</p>
        {data.series.length < 2 ? (
          <p className="text-sm text-gray-400">تتراكم البيانات مع كل تشغيل — ستظهر الاتجاهات بعد عدة تشغيلات للمحرك.</p>
        ) : (
          <div className="flex items-end gap-1 h-32" dir="ltr">
            {data.series.map((s, i) => (
              <div key={i} className="flex-1 flex flex-col items-center justify-end gap-0.5" title={`${s.date}: ${s.candidates} مرشح / ${s.confirmed} مؤكد`}>
                <div className="w-full bg-brand-400 rounded-t" style={{ height: `${(s.candidates / maxSeries) * 100}%`, minHeight: 2 }} />
              </div>
            ))}
          </div>
        )}
        <p className="text-xs text-gray-400 mt-2">كل عمود = عدد المرشحين في تشغيل. مرِّر لرؤية المؤكدة.</p>
      </div>
    </div>
  )
}

export default function MarketShortagePage() {
  const [tab, setTab] = useState('changes')
  const [med, setMed] = useState('')
  const [q, setQ] = useState('')
  const { data: confirmed } = useQuery({ queryKey: ['shortage-confirmed', ''],
    queryFn: () => purchasingApi.shortageConfirmed().then(r => r.data) })
  const { data: cand } = useQuery({ queryKey: ['shortage-candidates', '', '', ''],
    queryFn: () => purchasingApi.shortageCandidates({ include_flagged: '0' }).then(r => r.data) })
  const { data: deltas } = useQuery({ queryKey: ['shortage-deltas'],
    queryFn: () => purchasingApi.shortageDeltas().then(r => r.data) })
  const { data: dismissed } = useQuery({ queryKey: ['shortage-dismissed'],
    queryFn: () => purchasingApi.shortageDismissed().then(r => r.data) })

  const TABS = [
    ['changes', `التغييرات${deltas ? ` (${deltas.counts.new + deltas.counts.recovering + deltas.counts.re_entered})` : ''}`],
    ['candidates', `المرشحون (${cand?.total ?? 0})`],
    ['confirmed', `المؤكدة (${confirmed?.count ?? 0})`],
    ['dismissed', `المستبعدة (${dismissed?.count ?? 0})`],
    ['trends', '📈 الاتجاهات'],
  ]
  const exportView = tab === 'changes' ? 'candidates' : tab   // export/whatsapp map

  return (
    <div dir="rtl" className="p-4 md:p-6 max-w-7xl mx-auto">
      <div className="mb-5">
        <h1 className="text-2xl font-bold text-brand-600 flex items-center gap-2">📉 نواقص السوق</h1>
        <p className="text-sm text-gray-500 mt-1">أصناف مرتفعة الطلب يصعب توريدها أو تأتي بكمية محدودة (كوتة). يكتشفها المحرك ثم تُراجَع وتُؤكَّد يدويًا.</p>
      </div>

      <RunControls />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <div className="bg-white rounded-xl border border-gray-200 p-4"><p className="text-xs text-gray-500">مؤكدة (في نقص)</p><p className="text-2xl font-bold text-red-600 tabular-nums">{confirmed?.count ?? '—'}</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4"><p className="text-xs text-gray-500">🆕 نواقص جديدة</p><p className="text-2xl font-bold text-red-600 tabular-nums">{deltas?.counts.new ?? '—'}</p></div>
        <div className="bg-white rounded-xl border border-gray-200 p-4"><p className="text-xs text-gray-500">🔄 قد توفّرت</p><p className="text-2xl font-bold text-emerald-600 tabular-nums">{deltas?.counts.recovering ?? '—'}</p></div>
        <div className="bg-white rounded-xl border border-red-200 bg-red-50/40 p-4"><p className="text-xs text-gray-500">💸 خسارة شهرية (مؤكدة)</p><p className="text-2xl font-bold text-red-600 tabular-nums">{confirmed?.total_lost_monthly != null ? egp(confirmed.total_lost_monthly) : '—'}</p><p className="text-xs text-gray-400 mt-0.5">ج.م/شهر طلب غير مُلبَّى</p></div>
      </div>

      <div className="flex gap-2 mb-4 border-b border-gray-200 flex-wrap">
        {TABS.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`px-4 py-2 text-sm font-medium -mb-px border-b-2 ${tab === k ? 'border-brand-600 text-brand-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>{l}</button>
        ))}
      </div>

      {tab !== 'trends' && <Toolbar med={med} setMed={setMed} q={q} setQ={setQ} view={exportView} />}

      {tab === 'changes' && <ChangesTab med={med} q={q} />}
      {tab === 'candidates' && <CandidatesTab med={med} q={q} />}
      {tab === 'confirmed' && <ConfirmedTab med={med} q={q} />}
      {tab === 'dismissed' && <DismissedTab med={med} q={q} />}
      {tab === 'trends' && <TrendsTab />}
    </div>
  )
}
