/**
 * AvailabilityControls.jsx — the context strip above a supplier availability list:
 *
 *   • FreshnessBar — when sales rates / stock / sales / item data were last pulled from
 *     SOFTECH, stale ones highlighted, with the refresh buttons the user is allowed to use
 *   • ScopeBar     — which branches the offer serves (default: all = company total need)
 *   • LockBar      — finalize the list / unlock it with a reason, and its full audit trail
 *
 * The backend owns every rule (who may sync, what a lock blocks, how scoped need is
 * computed). These controls only display and send decisions.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { purchasingApi, supplyApi } from '../../api/client'
import { Chip, btnGhost, btnPrimary, errText, fmtDate, inputCls } from './supplyUi'
import ProgressBar from '../../components/ProgressBar'

export function fmtAge(min) {
  if (min === null || min === undefined) return 'لم تتم بعد'
  if (min < 1) return 'الآن'
  if (min < 60) return `منذ ${min} د`
  if (min < 1440) return `منذ ${Math.round(min / 60)} س`
  return `منذ ${Math.round(min / 1440)} يوم`
}

const FRESH = [
  ['rates', 'معدلات البيع', 'آخر تشغيل لمحرك الاحتياج (معدل البيع والهدف والفجوة لكل فرع)'],
  ['stock', 'الأرصدة', 'آخر مزامنة لأرصدة الفروع (stkbal)'],
  ['sales', 'المبيعات', 'آخر مزامنة لحركات البيع (stktrans)'],
  ['items', 'بيانات الأصناف', 'آخر مزامنة لكتالوج الأصناف والباركود'],
]

export function useFreshness() {
  return useQuery({
    queryKey: ['supply-freshness'],
    queryFn: () => supplyApi.freshness().then(r => r.data),
    // poll fast only while a sync / engine run is in flight
    refetchInterval: (query) => {
      const d = query?.state?.data
      return d && (d.engine_running || d.sync_running) ? 8000 : 120000
    },
  })
}

export function FreshnessBar({ onRefreshed }) {
  const qc = useQueryClient()
  const fq = useFreshness()
  const d = fq.data
  const busy = !!(d && (d.engine_running || d.sync_running))
  const wasBusy = useRef(false)
  useEffect(() => {                     // a sync / run just finished → re-analyse with fresh data
    if (wasBusy.current && !busy) onRefreshed?.()
    wasBusy.current = busy
  }, [busy, onRefreshed])
  const after = () => qc.invalidateQueries({ queryKey: ['supply-freshness'] })
  const stockM = useMutation({ mutationFn: () => supplyApi.syncStock(), onSuccess: after })
  const engineM = useMutation({ mutationFn: () => purchasingApi.triggerRun({}), onSuccess: after })
  const itemsM = useMutation({ mutationFn: () => purchasingApi.syncItems(), onSuccess: after })
  if (!d) return null
  const err = stockM.error || engineM.error || itemsM.error
  // a button was just pressed but the job hasn't shown up in the next poll yet
  const starting = (stockM.isPending || engineM.isPending || itemsM.isPending) && !busy
  return (
    <div className="space-y-1.5">
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
      <span className="text-content/60">البيانات:</span>
      {FRESH.map(([k, label, title]) => (
        <span key={k} title={`${title}${d[k]?.at ? ` — ${fmtDate(d[k].at)}` : ''}`}
          className={`px-2 py-0.5 rounded-full border whitespace-nowrap ${d[k]?.stale
            ? 'border-amber-300 bg-amber-50 text-amber-800' : 'border-line bg-surface text-content/70'}`}>
          {d[k]?.stale ? '⚠ ' : ''}{label} {fmtAge(d[k]?.age_min)}
          {k === 'rates' && d.rates?.data_through ? ` · حتى ${d.rates.data_through}` : ''}
        </span>
      ))}
      {d.can?.sync_stock && (
        <button type="button" className="underline text-content/70 hover:text-primary disabled:opacity-40"
          disabled={busy || stockM.isPending} onClick={() => stockM.mutate()}
          title="سحب الأرصدة والمبيعات من SOFTECH الآن (قراءة فقط)">⟳ الأرصدة والمبيعات</button>)}
      {d.can?.run_engine && (
        <button type="button" className="underline text-content/70 hover:text-primary disabled:opacity-40"
          disabled={busy || engineM.isPending} onClick={() => engineM.mutate()}
          title="تشغيل سريع لمحرك الاحتياج — يحدّث معدلات البيع والفجوة لكل فرع">▶ تحديث معدلات البيع</button>)}
      {d.can?.sync_items && (
        <button type="button" className="underline text-content/70 hover:text-primary disabled:opacity-40"
          disabled={busy || itemsM.isPending} onClick={() => itemsM.mutate()}
          title="مزامنة الأصناف الجديدة والأسعار والباركود">⟳ الأصناف</button>)}
      {busy && <span className="text-primary">سيُعاد التحليل تلقائياً عند الانتهاء</span>}
      {err && <span className="text-rose-600">{errText(err)}</span>}
    </div>
    {(d.progress || []).map(p => (
      <ProgressBar key={p.kind} pct={p.pct} label={p.label} message={p.message} elapsed={p.elapsed_s} />
    ))}
    {starting && <ProgressBar label="بدء التحديث" message="جارٍ الإرسال…" />}
    </div>
  )
}

export function ScopeBar({ batchId, scope, locked, onChanged }) {
  const fq = useFreshness()
  const branches = fq.data?.branches || []
  const ids = scope?.branch_ids || []
  const m = useMutation({ mutationFn: (next) => supplyApi.availScope(batchId, next), onSuccess: onChanged })
  const toggle = (id) => {
    const next = ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id]
    // every branch ticked = the company total ("all")
    m.mutate(next.length >= branches.length ? [] : next)
  }
  const chip = (on) => `text-[11px] px-2 py-0.5 rounded-full border transition disabled:opacity-50 ${on
    ? 'border-primary bg-primary text-white' : 'border-line bg-surface text-content/70 hover:border-primary/50'}`
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] text-content/60"
        title="فروع يخدمها هذا المورد (مخزن قريب من بعض الفروع فقط). الاحتياج والشراء المقترح يُحسبان لها وحدها.">
        الاحتياج لـ:</span>
      <button type="button" disabled={locked || m.isPending} className={chip(!ids.length)}
        onClick={() => ids.length && m.mutate([])}>كل الفروع (إجمالي)</button>
      {branches.map(b => (
        <button key={b.id} type="button" disabled={locked || m.isPending} className={chip(ids.includes(b.id))}
          onClick={() => toggle(b.id)} title={b.name}>{b.code} · {b.name.split(',')[0]}</button>
      ))}
      {m.isPending && <span className="text-[11px] text-content/50">جارٍ إعادة الحساب…</span>}
      {m.isError && <span className="text-[11px] text-rose-600">{errText(m.error)}</span>}
    </div>
  )
}

const EVENT_LABEL = {
  created: 'إنشاء القائمة', ocr_import: 'استيراد من صورة', file_import: 'استيراد ملف',
  bulk_confirm: 'تأكيد جماعي', line_added: 'إضافة سطر', line_updated: 'تعديل سطر',
  line_items: 'تغيير أصناف السطر', line_deleted: 'حذف سطر', scope_changed: 'تغيير الفروع',
  locked: '🔒 إقفال (نهائية)', unlocked: '🔓 فتح للتعديل',
}
const FIELD_LABEL = { item: 'الصنف', confirmed: 'مؤكد', qty: 'الكمية', price: 'السعر', foc: 'البونص',
  discount: 'الخصم', expiry: 'الصلاحية', code: 'كود المورد', items: 'الأصناف', branch_scope: 'الفروع' }

function fmtVal(v) {
  if (v === null || v === undefined || v === '') return '—'
  if (v === true) return 'نعم'
  if (v === false) return 'لا'
  if (Array.isArray(v)) return v.length ? v.join('، ') : 'الكل'
  if (typeof v === 'object') return v.item || '…'
  return String(v)
}

function History({ batchId }) {
  const hq = useQuery({ queryKey: ['supply-avail-history', batchId],
    queryFn: () => supplyApi.availHistory(batchId).then(r => r.data) })
  if (hq.isLoading) return <div className="text-xs text-content/50 p-2">جارٍ تحميل السجل…</div>
  const rows = hq.data || []
  return (
    <div className="rounded-lg border border-line bg-surface max-h-72 overflow-auto">
      <table className="w-full text-xs">
        <tbody>
          {rows.length === 0 && <tr><td className="p-2 text-content/50">لا توجد أحداث بعد.</td></tr>}
          {rows.map(r => (
            <tr key={r.id} className="border-b border-line/60 align-top">
              <td className="px-2 py-1 whitespace-nowrap text-content/60">{fmtDate(r.at)}</td>
              <td className="px-2 py-1 whitespace-nowrap">{r.user}</td>
              <td className="px-2 py-1 whitespace-nowrap font-medium">{EVENT_LABEL[r.event] || r.label}</td>
              <td className="px-2 py-1 text-content/70">
                {r.extra?.raw_text && <span dir="auto">«{r.extra.raw_text}» </span>}
                {Object.entries(r.changes || {}).map(([k, [a, b]]) => (
                  <span key={k} className="me-2">{FIELD_LABEL[k] || k}: {fmtVal(a)} ← {fmtVal(b)}</span>
                ))}
                {r.extra?.count ? <span>{r.extra.count} سطر </span> : null}
                {r.extra?.lines !== undefined && r.event !== 'locked' ? <span>{r.extra.lines} سطر </span> : null}
                {r.event === 'locked' && <span>{r.extra?.confirmed}/{r.extra?.lines} مؤكد </span>}
                {r.note && <span className="text-content">— {r.note}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function LockBar({ batch, onChanged }) {
  const qc = useQueryClient()
  const [mode, setMode] = useState(null)          // 'lock' | 'unlock' — inline, no modal
  const [text, setText] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const done = () => {
    setMode(null); setText('')
    qc.invalidateQueries({ queryKey: ['supply-avail-history', batch.id] })
    onChanged?.()
  }
  const lockM = useMutation({ mutationFn: () => supplyApi.availLock(batch.id, text), onSuccess: done })
  const unlockM = useMutation({ mutationFn: () => supplyApi.availUnlock(batch.id, text), onSuccess: done })
  const m = mode === 'unlock' ? unlockM : lockM
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {batch.is_locked
          ? <Chip tone="emerald" title={batch.lock_note || ''}>
              🔒 نهائية — {batch.locked_by_name || '—'} · {fmtDate(batch.locked_at)}
            </Chip>
          : <Chip>مسودة — قابلة للتعديل</Chip>}
        {!mode && (batch.is_locked
          ? <button type="button" className={btnGhost} onClick={() => setMode('unlock')}>🔓 فتح للتعديل</button>
          : <button type="button" className={btnGhost} onClick={() => setMode('lock')}
              title="تثبيت المطابقات والفروع — لا تعديل حتى تُفتح بسبب مكتوب">🔒 إقفال القائمة</button>)}
        {mode && (
          <>
            <input autoFocus value={text} onChange={e => setText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && (mode === 'lock' || text.trim().length >= 3)) m.mutate()
                                if (e.key === 'Escape') setMode(null) }}
              placeholder={mode === 'unlock' ? 'سبب الفتح (مطلوب — يُحفظ في السجل)' : 'ملاحظة (اختياري)'}
              className={`${inputCls} text-xs w-72`} />
            <button type="button" className={btnPrimary}
              disabled={m.isPending || (mode === 'unlock' && text.trim().length < 3)} onClick={() => m.mutate()}>
              {mode === 'unlock' ? 'فتح' : 'تأكيد الإقفال'}</button>
            <button type="button" className="text-content/50 hover:text-primary" onClick={() => setMode(null)}>إلغاء</button>
          </>
        )}
        <button type="button" className="underline text-content/60 hover:text-primary"
          onClick={() => setShowHistory(s => !s)}>{showHistory ? 'إخفاء السجل' : 'السجل'}</button>
        {m.isError && <span className="text-rose-600">{errText(m.error)}</span>}
      </div>
      {showHistory && <History batchId={batch.id} />}
    </div>
  )
}
