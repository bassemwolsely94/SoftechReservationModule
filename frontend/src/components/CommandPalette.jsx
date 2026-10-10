/**
 * CommandPalette — global Ctrl+K (⌘K) launcher: one box for cross-domain search
 * (items / customers / orders / reservations) + navigation & actions.
 *
 * Consumes GET /api/search/universal (searchApi.universal). Backend owns the
 * safety rule (exact identity vs fuzzy names); this UI only renders and routes.
 * Theme-aware via the surface tokens (batch 1). Mounted once in Layout.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchApi, helpApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { useThemeMode } from '../theme/useThemeMode'
import { buildCommands, matchScore } from '../shortcuts/commands'
import { normalizeSearch } from '../shortcuts/normalize'
import Highlight from './Highlight'

const SECTION_LABEL = {
  commands: 'أوامر', items: 'الأصناف', customers: 'العملاء',
  orders: 'طلبات POS', reservations: 'الحجوزات', help: 'دليل الاستخدام',
}

export default function CommandPalette() {
  const [open, setOpen]   = useState(false)
  const [q, setQ]         = useState('')
  const [remote, setRemote] = useState({ items: [], customers: [], orders: [], reservations: [] })
  const [helpHits, setHelpHits] = useState([])
  const [loading, setLoading] = useState(false)
  const [active, setActive] = useState(0)
  const inputRef = useRef(null)

  const navigate = useNavigate()
  const logout = useAuthStore((s) => s.logout)
  const user = useAuthStore((s) => s.user)
  const { cycle: cycleMode } = useThemeMode()
  const allCommands = useMemo(() => buildCommands(), [])

  // ── open / close via Ctrl+K (⌘K) ──
  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault()
        setOpen((v) => !v)
      }
      if (e.key === 'Escape') setOpen(false)
    }
    const onOpen = () => setOpen(true)
    window.addEventListener('keydown', onKey)
    window.addEventListener('palette:open', onOpen)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('palette:open', onOpen) }
  }, [])

  useEffect(() => {
    if (open) { setQ(''); setActive(0); setRemote({ items: [], customers: [], orders: [], reservations: [] }); setHelpHits([]); setTimeout(() => inputRef.current?.focus(), 30) }
  }, [open])

  // ── debounced universal search ──
  useEffect(() => {
    if (!open) return
    const term = q.trim()
    if (term.length < 2) { setRemote({ items: [], customers: [], orders: [], reservations: [] }); setHelpHits([]); setLoading(false); return }
    setLoading(true)
    const id = setTimeout(async () => {
      try {
        const params = {}
        if (user?.branch_id) params.branch = user.branch_id
        // help articles ride along (not logged as a help search — this box is mostly items)
        const helpReq = helpApi.search(term, { log: 0 }).then((r) => r.data.slice(0, 4)).catch(() => [])
        const { data } = await searchApi.universal(term, params)
        setRemote(data.results || { items: [], customers: [], orders: [], reservations: [] })
        setHelpHits(await helpReq)
      } catch { /* keep last */ } finally { setLoading(false) }
    }, 180)
    return () => clearTimeout(id)
  }, [q, open, user?.branch_id])

  // ── local command matches ──
  const commandMatches = useMemo(() => {
    const nq = normalizeSearch(q)
    return allCommands
      .map((c) => ({ c, s: matchScore(c, nq) }))
      .filter((x) => x.s >= 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, nq ? 6 : 8)
      .map((x) => x.c)
  }, [q, allCommands])

  // ── flatten into a single navigable list ──
  const flat = useMemo(() => {
    const rows = []
    commandMatches.forEach((c) => rows.push({ kind: 'command', section: 'commands', cmd: c }))
    remote.items.forEach((it) => rows.push({ kind: 'item', section: 'items', data: it }))
    remote.customers.forEach((c) => rows.push({ kind: 'customer', section: 'customers', data: c }))
    remote.orders.forEach((o) => rows.push({ kind: 'order', section: 'orders', data: o }))
    remote.reservations.forEach((r) => rows.push({ kind: 'reservation', section: 'reservations', data: r }))
    helpHits.forEach((h) => rows.push({ kind: 'help', section: 'help', data: { ...h, id: h.key } }))
    return rows
  }, [commandMatches, remote, helpHits])

  useEffect(() => { setActive(0) }, [flat.length])

  const runRow = useCallback((row) => {
    if (!row) return
    setOpen(false)
    if (row.kind === 'command') { row.cmd.run({ navigate, logout, cycleMode }); return }
    const d = row.data
    if (row.kind === 'item')        navigate(`/products/${d.id}`)
    else if (row.kind === 'customer')    window.dispatchEvent(new CustomEvent('customer360:open', { detail: { id: d.id } }))
    else if (row.kind === 'reservation') navigate(`/reservations/${d.id}`)
    else if (row.kind === 'order')       navigate('/pos')
    else if (row.kind === 'help')        window.dispatchEvent(new CustomEvent('help:open', { detail: { key: d.key } }))
  }, [navigate, logout, cycleMode])

  const onKeyNav = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((i) => Math.min(i + 1, flat.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); runRow(flat[active]) }
  }

  if (!open) return null

  // group rows for rendering while keeping a global index for highlight
  let idx = -1
  const sections = ['commands', 'items', 'customers', 'orders', 'reservations', 'help']

  return (
    <div className="fixed inset-0 z-[9998] flex items-start justify-center pt-[12vh] px-4"
         onMouseDown={() => setOpen(false)}>
      <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" />
      <div dir="rtl"
           className="relative w-full max-w-xl bg-surface border border-line rounded-2xl shadow-2xl overflow-hidden animate-scale-in"
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-line">
          <span className="text-faint text-lg">🔎</span>
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyNav}
            placeholder="ابحث عن صنف، عميل، طلب، حجز… أو اكتب أمرًا"
            className="flex-1 bg-transparent outline-none text-content placeholder-faint text-sm"
          />
          {loading && <span className="text-[11px] text-faint">…</span>}
          <kbd className="text-[10px] text-faint border border-line rounded px-1.5 py-0.5">Esc</kbd>
        </div>

        <div className="max-h-[55vh] overflow-y-auto py-1">
          {flat.length === 0 && (
            <div className="px-4 py-8 text-center text-sm text-faint">
              {q.trim().length < 2 ? 'ابدأ الكتابة للبحث…' : 'لا نتائج'}
            </div>
          )}
          {sections.map((sec) => {
            const rows = flat.filter((r) => r.section === sec)
            if (!rows.length) return null
            return (
              <div key={sec}>
                <div className="px-4 pt-2 pb-1 text-[10px] font-bold text-faint uppercase tracking-wide">
                  {SECTION_LABEL[sec]}
                </div>
                {rows.map((row) => {
                  idx += 1
                  const i = idx
                  const isActive = i === active
                  return (
                    <button
                      key={`${row.kind}-${row.cmd?.id || row.data?.id}-${i}`}
                      onMouseEnter={() => setActive(i)}
                      onClick={() => runRow(row)}
                      className={`w-full text-right flex items-center gap-3 px-4 py-2 text-sm transition-colors
                        ${isActive ? 'bg-brand-50 text-brand-700' : 'text-content hover:bg-surface-3'}`}
                    >
                      <Row row={row} q={q} />
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
        <div className="px-4 py-2 border-t border-line text-[10px] text-faint flex items-center gap-3">
          <span>↑↓ للتنقل</span><span>↵ للفتح</span><span className="ms-auto">Ctrl/⌘ + K</span>
        </div>
      </div>
    </div>
  )
}

function Row({ row, q }) {
  if (row.kind === 'command') {
    return (<><span className="text-base">{row.cmd.icon}</span><span className="flex-1">{row.cmd.title}</span>
      <span className="text-[10px] text-faint">{row.cmd.section === 'action' ? 'أمر' : 'انتقال'}</span></>)
  }
  const d = row.data
  if (row.kind === 'item') {
    const blocking = (d.safety_flags || []).some((f) => f.severity === 'block')
    return (<><span className="text-base">💊</span>
      <span className="flex-1 truncate"><Highlight text={d.name} query={q} />
        <span className="text-[11px] text-faint"> · {d.softech_id}{d.barcode ? ` · ${d.barcode}` : ''}</span></span>
      {d.exact && <span className="text-[10px] text-brand-600 border border-brand-200 rounded px-1">مطابقة تامة</span>}
      {d.learned && <span className="text-[10px] text-teal-700 border border-teal-200 rounded px-1">من الذاكرة</span>}
      {d.sound && <span className="text-[10px] text-sky-700 border border-sky-200 rounded px-1">بالنطق</span>}
      {d.approx && <span className="text-[10px] text-amber-700 border border-amber-200 rounded px-1"
        title="لا يوجد صنف يطابق ما كُتب بالضبط — أقرب الأصناف">تقريبي</span>}
      {blocking && <span className="text-[10px] text-brand-red">⛔</span>}
      {typeof d.qty_at_branch === 'number' && <span className="text-[11px] tabnum text-faint">{d.qty_at_branch}</span>}</>)
  }
  if (row.kind === 'customer') {
    return (<><span className="text-base">👤</span>
      <span className="flex-1 truncate">{d.name}<span className="text-[11px] text-faint"> · {d.phone}</span></span></>)
  }
  if (row.kind === 'order') {
    return (<><span className="text-base">🧾</span>
      <span className="flex-1 truncate">{d.customer_name || `طلب #${d.id}`}
        <span className="text-[11px] text-faint"> · {d.status_label}</span></span></>)
  }
  if (row.kind === 'help') {
    return (<><span className="text-base">📖</span>
      <span className="flex-1 truncate">{d.title?.ar}<span className="text-[11px] text-faint"> · {d.module_title?.ar}</span></span>
      <span className="text-[10px] text-faint">شرح</span></>)
  }
  return (<><span className="text-base">📌</span>
    <span className="flex-1 truncate">{d.contact_name}<span className="text-[11px] text-faint"> · {d.item_name} · {d.status_label}</span></span></>)
}
