/**
 * MobileStockCountDetailPage.jsx — stock-count session (route: /m/stock-count/:id).
 *
 * Live aisle counting: scan/search an item → enter counted qty → instant variance
 * vs the frozen snapshot (count-item endpoint). Plus a read-only variance list
 * (search + filter). expected_qty is never mutated.
 */
import { useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { stockCountApi } from '../../api/client'
import { queuedPost } from '../../api/offlineQueue'
import ItemSearchWidget from '../../components/ItemSearchWidget'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'

function toLatin(s) {
  return s ? String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)) : s
}
const VAR_CLASS = { ok: 'text-green-600', surplus: 'text-amber-600', deficit: 'text-red-600' }

export default function MobileStockCountDetailPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const qc       = useQueryClient()
  const qtyRef   = useRef(null)

  const [search, setSearch]     = useState('')
  const [variance, setVariance] = useState('all')
  const [item, setItem]         = useState(null)
  const [qty, setQty]           = useState('')
  const [busy, setBusy]         = useState(false)
  const [error, setError]       = useState('')
  const [last, setLast]         = useState(null)   // last count result

  const session = useQuery({
    queryKey: ['m-stockcount', id],
    queryFn: () => stockCountApi.get(id).then(r => r.data),
  })
  const s = session.data
  const canCount = s && !['draft', 'closed'].includes(s.status)

  const snaps = useQuery({
    queryKey: ['m-stockcount-snaps', id, variance, search],
    queryFn: () => stockCountApi.snapshots(id, {
      variance_type: variance, search: search || undefined, page_size: 50,
    }).then(r => r.data).catch(() => null),
    enabled: !!id && !!s && !['draft', 'snapshot_taken', 'exported'].includes(s.status),
  })
  const rows = Array.isArray(snaps.data) ? snaps.data : (snaps.data?.results || [])

  async function submitCount() {
    if (!item) { setError('اختر صنفاً'); return }
    if (qty === '' || Number(qty) < 0) { setError('أدخل كمية صحيحة'); return }
    setBusy(true); setError('')
    try {
      const res = await queuedPost(`/stockcount/sessions/${id}/count-item/`,
        { item_code: item.softech_id, counted_qty: qty }, { label: 'تسجيل جرد' })
      if (res.queued) {
        // No instant variance offline — the count is replayed on reconnect.
        setLast({ item_name: item.name, queued: true })
      } else {
        setLast(res.data)
        qc.invalidateQueries({ queryKey: ['m-stockcount', id] })
        qc.invalidateQueries({ queryKey: ['m-stockcount-snaps', id] })
      }
      setItem(null); setQty('')
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر تسجيل الجرد')
    } finally {
      setBusy(false)
    }
  }

  if (session.isLoading) return <MobileLoading />
  if (session.isError || !s) return <MobileError text="تعذّر تحميل الجلسة" onRetry={session.refetch} />

  const counted = (s.ok_count || 0) + (s.surplus_count || 0) + (s.deficit_count || 0)
  const total   = s.item_count || 0
  const pct     = total ? Math.round((counted / total) * 100) : 0
  const FILTERS = [{ v: 'all', l: 'الكل' }, { v: 'deficit', l: 'عجز' }, { v: 'surplus', l: 'فائض' }, { v: 'ok', l: 'مطابق' }]

  return (
    <div className="p-3 space-y-3">
      <button onClick={() => navigate('/m/stock-count')} className="text-sm text-gray-500">→ الرجوع للجلسات</button>

      <div className="bg-white rounded-2xl border border-gray-200 p-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="font-bold text-base text-gray-900">{s.name || s.title || `جرد #${s.id}`}</h1>
          <span className="text-[11px] px-2 py-0.5 rounded-full font-medium bg-gray-100 text-gray-700">{s.status_label || s.status}</span>
        </div>
        <div className="text-xs text-gray-400 mt-1">{s.branch_name || s.branch_name_ar || ''}</div>
        {total > 0 && (
          <div className="mt-2.5">
            <div className="flex justify-between text-[11px] text-gray-500 mb-1">
              <span>تم جرد {toLatin(counted)} من {toLatin(total)}</span><span>{toLatin(pct)}%</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden"><div className="h-full bg-brand-500" style={{ width: `${pct}%` }} /></div>
          </div>
        )}
      </div>

      {/* Live count entry */}
      {canCount ? (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 space-y-2.5">
          <h2 className="font-semibold text-gray-700 text-sm">📷 جرد صنف (مسح/بحث)</h2>
          <ItemSearchWidget selected={item} onSelect={(it) => { setItem(it); setError(''); setTimeout(() => qtyRef.current?.focus(), 50) }} onClear={() => setItem(null)} />
          {item && (
            <div className="flex gap-2 items-end">
              <div className="flex-1">
                <label className="label">الكمية المعدودة</label>
                <input ref={qtyRef} type="number" min="0" inputMode="decimal" className="input-field w-full"
                  value={qty} onChange={e => setQty(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') submitCount() }} />
              </div>
              <button onClick={submitCount} disabled={busy} className="btn-primary px-5 py-2.5 disabled:opacity-50">
                {busy ? '...' : 'تسجيل'}
              </button>
            </div>
          )}
          {error && <div className="text-sm text-red-600">{error}</div>}
          {last && (
            <div className="rounded-xl bg-gray-50 border border-gray-200 p-3 text-sm">
              <div className="font-medium text-gray-800 break-words">{last.item_name}</div>
              {last.queued ? (
                <div className="text-xs mt-1 text-blue-600">📴 سيُسجَّل عند عودة الاتصال</div>
              ) : (
                <div className="flex items-center gap-3 text-xs mt-1">
                  <span className="text-gray-500">متوقع: {toLatin(last.expected_qty)}</span>
                  <span className="text-gray-500">معدود: {toLatin(last.counted_qty)}</span>
                  <span className={`font-bold ${VAR_CLASS[last.variance_type] || 'text-gray-600'}`}>
                    {last.variance_label}{last.difference ? ` (${last.difference > 0 ? '+' : ''}${toLatin(last.difference)})` : ''}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="bg-white rounded-2xl border border-gray-200 p-4 text-sm text-gray-500 text-center">
          {s.status === 'draft' ? 'خذ اللقطة أولاً من النظام لبدء الجرد' : 'الجلسة مغلقة'}
        </div>
      )}

      {/* Variance list */}
      {!['draft', 'snapshot_taken', 'exported'].includes(s.status) && (
        <>
          <input className="input-field w-full" placeholder="بحث في الأصناف..." value={search} onChange={e => setSearch(e.target.value)} />
          <div className="flex gap-2">
            {FILTERS.map(f => (
              <button key={f.v} onClick={() => setVariance(f.v)}
                className={`flex-1 px-2 py-1.5 rounded-full text-xs font-medium ${variance === f.v ? 'bg-brand-600 text-white' : 'bg-white border border-gray-200 text-gray-600'}`}>{f.l}</button>
            ))}
          </div>

          {snaps.isLoading ? <MobileLoading />
            : rows.length === 0 ? <MobileEmpty icon="📦" text="لا توجد أصناف مطابقة" />
            : (
              <div className="space-y-1.5">
                {rows.map((r, i) => {
                  const cnt = r.counted_qty ?? r.actual_qty, varc = r.difference
                  return (
                    <div key={r.id || i} className="bg-white border border-gray-200 rounded-xl p-3">
                      <div className="text-sm font-medium text-gray-800 break-words">{r.item_name || r.item_code}</div>
                      <div className="flex items-center gap-3 text-xs text-gray-500 mt-1">
                        <span>متوقع: {toLatin(r.expected_qty)}</span>
                        {cnt != null && <span>معدود: {toLatin(cnt)}</span>}
                        {varc != null && varc !== 0 && (
                          <span className={`font-bold ${varc < 0 ? 'text-red-600' : 'text-amber-600'}`}>فرق: {toLatin(varc)}</span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
        </>
      )}
    </div>
  )
}
