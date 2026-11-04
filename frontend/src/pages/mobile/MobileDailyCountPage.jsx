/**
 * MobileDailyCountPage.jsx — «جردي اليوم» (route: /m/daily-count). Small daily counts, Project 2.
 *
 * The salesperson's own list for today (≈20 items chosen by the server) + any recount a manager
 * handed them. BLIND: the server never sends the expected quantity or the difference — the phone
 * only records what is on the shelf. Scan with the camera (stays open between items) or tap a line.
 * Packs + strips/units for items sold in units. Offline → queued and replayed (client_token keeps a
 * replay from counting twice). Hidden while DAILY_COUNT_ENABLED is off.
 */
import { useMemo, useRef, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { dailyCountApi } from '../../api/client'
import { queuedPost } from '../../api/offlineQueue'
import BarcodeScanner, { cameraAvailable } from '../../components/BarcodeScanner'
import { MobileLoading, MobileError, MobileEmpty } from '../../components/mobileUi'
import useFeatures from '../../hooks/useFeatures'

function toLatin(s) {
  return s == null ? '' : String(s).replace(/[٠-٩]/g, d => String.fromCharCode(d.charCodeAt(0) - 0x660)).replace('٫', '.')
}

function newToken() {
  try { return crypto.randomUUID() } catch { return `${Date.now()}-${Math.random().toString(36).slice(2)}` }
}

export default function MobileDailyCountPage() {
  const { dailyCount, cameraScan } = useFeatures()
  const qc = useQueryClient()
  const packsRef = useRef(null)
  const [current, setCurrent] = useState(null)
  const [packs, setPacks]     = useState('')
  const [units, setUnits]     = useState('')
  const [expiry, setExpiry]   = useState('')
  const [busy, setBusy]       = useState(false)
  const [error, setError]     = useState('')
  const [note, setNote]       = useState('')
  const [scanning, setScanning] = useState(false)
  const [doneLocal, setDoneLocal] = useState({})     // pick_id → true (queued offline / just saved)

  const q = useQuery({
    queryKey: ['m-daily-count'],
    queryFn: () => dailyCountApi.my().then(r => r.data),
    enabled: dailyCount,
  })
  const picks = q.data?.picks || []
  const done = picks.filter(p => p.done || doneLocal[p.pick_id]).length

  const byCode = useMemo(() => {
    const m = new Map()
    for (const p of picks) {
      m.set(String(p.item_code), p)
      for (const b of p.barcodes || []) m.set(String(b), p)
    }
    return m
  }, [picks])

  if (!dailyCount) return <Navigate to="/m/me" replace />

  function open(p) {
    setCurrent(p); setPacks(''); setUnits(''); setExpiry(''); setError(''); setNote('')
    setTimeout(() => packsRef.current?.focus(), 50)
  }

  function onScan(code) {
    const p = byCode.get(String(code).trim())
    if (!p) { setNote(`هذا الصنف ليس ضمن جردك اليوم (${code})`); return }
    if (!p.can_count) { setNote(`«${p.item_name}» تم جرده`); return }
    setScanning(false)
    open(p)
  }

  async function submit() {
    const pq = Math.max(1, Number(current.pack_qty) || 1)
    const nPacks = Number(toLatin(packs) || 0)
    const nUnits = pq > 1 ? Number(toLatin(units) || 0) : 0
    if (packs === '' && units === '') { setError('أدخل الكمية الموجودة (ولو صفر)'); return }
    if (!Number.isFinite(nPacks) || !Number.isFinite(nUnits) || nPacks < 0 || nUnits < 0) { setError('كمية غير صالحة'); return }
    if (current.ask_expiry && !expiry) { setError('أدخل أقرب تاريخ صلاحية على الرف'); return }
    const qty = Math.round((nPacks + nUnits / pq) * 1000) / 1000
    setBusy(true); setError('')
    try {
      const res = await queuedPost('/stockcount/daily/my/count/', {
        pick_id: current.pick_id, counted_qty: qty, client_token: newToken(),
        ...(current.ask_expiry && expiry ? { physical_expiry: expiry } : {}),
      }, { label: 'جرد يومي' })
      setDoneLocal(d => ({ ...d, [current.pick_id]: true }))
      setNote(res.queued ? `«${current.item_name}» محفوظ — هيتبعت لما النت يرجع` : `✓ «${current.item_name}»`)
      setCurrent(null)
      if (!res.queued) qc.invalidateQueries({ queryKey: ['m-daily-count'] })
      if (cameraScan && cameraAvailable()) setScanning(true)
    } catch (e) {
      setError(e.response?.data?.detail || 'تعذّر الحفظ')
    } finally {
      setBusy(false)
    }
  }

  if (q.isLoading) return <MobileLoading />
  if (q.isError) return <MobileError text="تعذّر تحميل جرد اليوم" onRetry={q.refetch} />

  return (
    <div className="p-3 space-y-3 pb-24">
      <div className="flex items-center justify-between gap-2">
        <h1 data-tour="dailycount-mobile-title" className="text-base font-bold text-gray-900">جردي اليوم</h1>
        {picks.length > 0 && (
          <span data-tour="dailycount-mobile-progress" className="text-sm font-semibold text-brand-700 tabular-nums">{done} / {picks.length}</span>
        )}
      </div>
      {picks.length > 0 && (
        <>
          <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
            <div className="h-full bg-brand-500 transition-all" style={{ width: `${Math.round(100 * done / picks.length)}%` }} />
          </div>
          <p data-tour="dailycount-mobile-reminder" className="text-xs text-gray-600 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            {q.data?.reminder}
          </p>
        </>
      )}
      {note && <p className="text-xs text-gray-700 bg-gray-50 rounded-lg px-3 py-2">{note}</p>}

      {current && (
        <div data-tour="dailycount-mobile-entry" className="bg-white rounded-2xl border-2 border-brand-300 p-4 space-y-3">
          <div className="font-bold text-sm text-gray-900 break-words">{current.item_name}</div>
          <div className="text-[11px] text-gray-400" dir="ltr">{current.item_code}</div>
          <div className="flex gap-2">
            <label className="flex-1 text-xs text-gray-600">علب
              <input ref={packsRef} type="number" min="0" step="1" inputMode="numeric" className="input-field w-full mt-1"
                value={packs} onChange={e => setPacks(e.target.value)} />
            </label>
            {Number(current.pack_qty) > 1 && (
              <label className="flex-1 text-xs text-gray-600">شرائط / وحدات (العلبة = {current.pack_qty})
                <input type="number" min="0" step="1" inputMode="numeric" className="input-field w-full mt-1"
                  value={units} onChange={e => setUnits(e.target.value)} />
              </label>
            )}
          </div>
          {current.ask_expiry && (
            <label className="block text-xs text-gray-600">أقرب تاريخ صلاحية على الرف
              <input type="date" className="input-field w-full mt-1" value={expiry} onChange={e => setExpiry(e.target.value)} />
            </label>
          )}
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button type="button" disabled={busy} onClick={submit} className="btn-primary flex-1">{busy ? '...' : 'حفظ'}</button>
            <button type="button" onClick={() => setCurrent(null)} className="btn-secondary">إلغاء</button>
          </div>
        </div>
      )}

      {picks.length === 0 ? (
        <MobileEmpty icon="🧮" text="مفيش جرد ليك النهارده" />
      ) : (
        <div data-tour="dailycount-mobile-list" className="space-y-2">
          {picks.map(p => {
            const isDone = p.done || doneLocal[p.pick_id]
            return (
              <button key={p.pick_id} type="button" disabled={!p.can_count}
                onClick={() => open(p)}
                className={`w-full text-right rounded-xl border p-3 flex items-center gap-3 ${
                  isDone ? 'bg-gray-50 border-gray-100' : p.is_recount ? 'bg-amber-50 border-amber-200' : 'bg-white border-gray-200 active:bg-gray-50'}`}>
                <span className={`text-lg ${isDone ? 'text-green-600' : 'text-gray-300'}`}>{isDone ? '✓' : '○'}</span>
                <span className="flex-1 min-w-0">
                  <span className={`block text-sm break-words ${isDone ? 'text-gray-500' : 'text-gray-900 font-medium'}`}>{p.item_name}</span>
                  {p.is_recount && <span className="text-[11px] text-amber-700">إعادة جرد مطلوبة</span>}
                  {p.ask_expiry && !isDone && <span className="text-[11px] text-gray-500"> · سجّل الصلاحية</span>}
                </span>
              </button>
            )
          })}
        </div>
      )}

      {cameraScan && cameraAvailable() && picks.some(p => p.can_count) && !current && (
        <button data-tour="dailycount-mobile-scan" type="button" onClick={() => { setNote(''); setScanning(true) }}
          className="fixed bottom-20 inset-x-4 z-30 btn-primary py-3 text-base shadow-lg">📷 امسح الصنف</button>
      )}
      {scanning && (
        <BarcodeScanner continuous onScan={onScan} onClose={() => setScanning(false)}
          hint={note || 'امسح باركود الصنف اللي قدامك'} />
      )}
    </div>
  )
}
