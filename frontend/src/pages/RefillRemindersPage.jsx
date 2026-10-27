/**
 * RefillRemindersPage — «تذكيرات الصرف (واتساب)» (B1).
 *
 * Review screen for the daily WhatsApp refill reminders (template `refill_reminder`): what was sent,
 * who replied and how (branch pickup / delivery / stop), and a live preview of the next run with the
 * reason every other due task is skipped. The backend owns every rule and the send switch
 * (REFILL_REMINDER_SEND_ENABLED); this page only shows and, for admin/supervisor, runs it now.
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { refillRemindersApi } from '../api/client'
import useHelpTab from '../help/useHelpTab'

const STATUS_TONE = { sent: 'bg-sky-50 text-sky-700', replied: 'bg-emerald-50 text-emerald-700', failed: 'bg-red-50 text-red-700' }
const errMsg = (e) => e?.response?.data?.detail || e?.message || 'حدث خطأ'

function Card({ label, value, sub, tone = 'text-gray-900' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3 min-w-[9rem]">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-lg font-bold ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-400 mt-0.5">{sub}</div>}
    </div>
  )
}

export default function RefillRemindersPage() {
  const [ov, setOv] = useState(null)
  const [pv, setPv] = useState(null)
  const [view, setView] = useState('log')
  useHelpTab(view)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)
  const [runMsg, setRunMsg] = useState('')

  const load = useCallback(() => {
    refillRemindersApi.overview().then(r => setOv(r.data)).catch(e => setError(errMsg(e)))
    refillRemindersApi.preview().then(r => setPv(r.data)).catch(() => {})
  }, [])
  useEffect(load, [load])

  const run = async () => {
    setRunning(true); setRunMsg('')
    try {
      const r = (await refillRemindersApi.run()).data
      setRunMsg(r.send_enabled
        ? `أُرسل ${r.sent} · فشل ${r.failed}${r.busy ? ' · تشغيل آخر يعمل الآن' : ''}`
        : `الإرسال متوقف — كان سيُرسل ${r.candidates} تذكير`)
      load()
    } catch (e) { setRunMsg(errMsg(e)) } finally { setRunning(false) }
  }

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!ov) return <div className="p-6 text-sm text-gray-400">جارٍ التحميل…</div>

  return (
    <div className="p-6 space-y-4" dir="rtl">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-xl font-bold text-gray-900">💬 تذكيرات الصرف عبر واتساب</h1>
          <p className="text-sm text-gray-500">
            رسالة واحدة لكل عميل قبل موعد صرفه — يختار التجهيز في الفرع أو التوصيل، ويؤكد الصيدلي الأصناف قبل التجهيز.
            {' '}<Link to="/followups" className="text-brand-600">متابعة المزمن ←</Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span data-tour="followups-reminders-send-status" className={`text-xs px-2 py-1 rounded ${ov.send_enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
            {ov.send_enabled ? 'الإرسال مفعّل' : 'الإرسال متوقف (معاينة فقط)'}
          </span>
          {ov.can_run && (
            <button onClick={run} disabled={running} data-tour="followups-reminders-run"
              className="px-3 py-1.5 text-sm rounded-lg bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-40">
              {running ? '…' : 'تشغيل الآن'}
            </button>
          )}
        </div>
      </div>
      {runMsg && <div className="text-sm text-gray-600">{runMsg}</div>}

      <div className="flex flex-wrap gap-3" data-tour="followups-reminders-kpis">
        <Card label="أُرسل (30 يوم)" value={ov.sent} />
        <Card label="نسبة الرد" value={`${ov.reply_rate}%`} />
        <Card label="تجهيز في الفرع" value={ov.by_choice.branch || 0} tone="text-emerald-700" />
        <Card label="توصيل للمنزل" value={ov.by_choice.delivery || 0} tone="text-emerald-700" />
        <Card label="حجوزات أُنشئت" value={ov.reservations} />
        <Card label="فشل الإرسال" value={ov.by_status.failed || 0} tone={ov.by_status.failed ? 'text-red-700' : 'text-gray-900'} />
        <Card label="أوقفوا التذكيرات" value={ov.opt_outs} sub="الإجمالي" />
      </div>

      <div className="flex gap-1" data-tour="followups-reminders-tabs">
        {[['log', 'سجل التذكيرات'], ['preview', `التشغيل القادم (${pv ? pv.to_send.length : '…'})`]].map(([k, l]) => (
          <button key={k} onClick={() => setView(k)}
            className={`px-3 py-1.5 text-sm rounded-lg ${view === k ? 'bg-gray-800 text-white' : 'text-gray-600 hover:bg-gray-100'}`}>{l}</button>
        ))}
      </div>

      {view === 'log' && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto" data-tour="followups-reminders-log">
          <table className="w-full text-sm text-right">
            <thead className="text-xs text-gray-500 border-b">
              <tr><th className="py-2 px-3">العميل</th><th>الرقم</th><th>الفرع</th><th>موعد الصرف</th><th>الحالة</th><th>الرد</th><th>الحجز</th><th>أُرسل</th></tr>
            </thead>
            <tbody>
              {ov.rows.map(r => (
                <tr key={r.id} className="border-b border-gray-50">
                  <td className="py-1.5 px-3">{r.customer}<div className="text-[11px] text-gray-400">{r.item}</div></td>
                  <td className="font-mono" dir="ltr">{r.phone}</td>
                  <td>{r.branch}</td>
                  <td>{r.due_date}</td>
                  <td><span className={`text-xs px-2 py-0.5 rounded ${STATUS_TONE[r.status] || ''}`}>{r.status_label}</span>
                    {r.error && <div className="text-[11px] text-red-600">{r.error}</div>}</td>
                  <td>{r.reply_label || '—'}</td>
                  <td>{r.reservation_id ? <Link to={`/reservations/${r.reservation_id}`} className="text-brand-600">#{r.reservation_id}</Link> : '—'}</td>
                  <td className="text-xs text-gray-500">{r.sent_at ? new Date(r.sent_at).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' }) : '—'}</td>
                </tr>
              ))}
              {!ov.rows.length && <tr><td colSpan={8} className="py-6 text-center text-gray-400">لم يُرسل أي تذكير بعد.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {view === 'preview' && pv && (
        <div className="space-y-3" data-tour="followups-reminders-preview">
          <div className="flex flex-wrap gap-2">
            {Object.entries(pv.skipped).map(([k, n]) => (
              <span key={k} className="text-xs bg-white border border-gray-200 rounded-lg px-2 py-1">
                {pv.skip_labels[k] || k}: <b>{n}</b>
              </span>
            ))}
          </div>
          <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
            <table className="w-full text-sm text-right">
              <thead className="text-xs text-gray-500 border-b">
                <tr><th className="py-2 px-3">العميل</th><th>الرقم</th><th>الفرع</th><th>موعد الصرف</th><th>الصنف (لا يُذكر في الرسالة)</th></tr>
              </thead>
              <tbody>
                {pv.to_send.map(r => (
                  <tr key={r.task_id} className="border-b border-gray-50">
                    <td className="py-1.5 px-3">{r.customer}</td>
                    <td className="font-mono" dir="ltr">{r.phone}</td>
                    <td>{r.branch}</td>
                    <td>{r.due_date}</td>
                    <td className="text-gray-500">{r.item}</td>
                  </tr>
                ))}
                {!pv.to_send.length && <tr><td colSpan={5} className="py-6 text-center text-gray-400">لا يوجد عملاء مستحقون للتذكير اليوم.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
