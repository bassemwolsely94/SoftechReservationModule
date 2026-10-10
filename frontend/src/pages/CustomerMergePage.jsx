/**
 * CustomerMergePage — «دمج الأكواد المكررة» (B7 merge queue).
 *
 * Duplicate customer codes found weekly at HQ (same / similar name on a real shared phone; families never
 * proposed). The backend picks the main code (older creation → higher points → latest sale) and enforces
 * maker-checker: one reviewer marks, a different reviewer approves. Approving does not touch SOFTECH — the
 * merge write is a separate, gated step. This page only shows decisions and sends the reviewer's choice.
 */
import { useCallback, useEffect, useState } from 'react'
import { customerMergeApi } from '../api/client'

const errMsg = (e) => e?.response?.data?.detail || e?.message || 'حدث خطأ'
const STATUSES = [['proposed', 'مقترح'], ['marked', 'بانتظار الاعتماد'], ['approved', 'معتمد'],
  ['merged', 'تم الدمج'], ['failed', 'فشل الدمج'], ['rejected', 'مرفوض'], ['stale', 'لم يعد مكررًا'], ['all', 'الكل']]
const STRENGTHS = [['', 'كل الدرجات'], ['strong', 'قوي'], ['medium', 'نفس الاسم'], ['review', 'للمراجعة']]
const TONE = { strong: 'bg-emerald-50 text-emerald-700', medium: 'bg-sky-50 text-sky-700', review: 'bg-amber-50 text-amber-700' }
const STATUS_TEXT = { '0': 'مغلق', '1': 'نشط', '': 'نشط', '5': 'متوفى' }

function CodeCard({ title, pic, name, card = {} }) {
  return (
    <div className="flex-1 min-w-[12rem]">
      <div className="text-[11px] text-gray-400">{title}</div>
      <span className="font-mono font-semibold text-gray-900 select-all">{pic}</span>
      <span className="text-sm text-gray-600 mr-2">{name}</span>
      <div className="text-[11px] text-gray-500 mt-0.5">
        فرع {card.branch || '—'} · أُنشئ {card.created || '—'} · نقاط {card.balance ?? 0} · آخر بيع {card.last_sale || '—'}
        {' · '}{STATUS_TEXT[card.status] ?? card.status}{card.points_enrolled === false ? ' · خارج النقاط' : ''}
      </div>
    </div>
  )
}

function Row({ r, me, onAct, busy }) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  const f = r.facts || {}
  const open = r.status === 'proposed' || r.status === 'marked'
  const ownMark = r.status === 'marked' && r.marked_by_id === me
  return (
    <div className="bg-white rounded-xl border border-gray-200 px-4 py-3">
      <div className="flex flex-wrap items-start gap-4">
        <CodeCard title="الكود المكرر (يُغلق)" pic={r.old_pic} name={r.old_name} card={f.old} />
        <div className="self-center text-gray-400">←</div>
        <CodeCard title={`الكود الرئيسي${r.main_swapped ? ' (بدّله مراجع)' : ''}`} pic={r.main_pic} name={r.main_name} card={f.main} />
        <div className="text-left space-y-1">
          <span className={`inline-block text-xs px-2 py-0.5 rounded ${TONE[r.strength] || ''}`}>{r.strength_label}</span>
          <div className="text-[11px] text-gray-500">هاتف مشترك {(f.shared_phones || []).join('، ')}</div>
          <div className="text-[11px] text-gray-500">{r.status_label}{r.marked_by ? ` · علّمه ${r.marked_by}` : ''}
            {r.approved_by ? ` · اعتمده ${r.approved_by}` : ''}{r.rejected_by ? ` · رفضه ${r.rejected_by}: ${r.reason}` : ''}</div>
          {r.error && <div className="text-[11px] text-red-600 max-w-xs">{r.error}</div>}
        </div>
      </div>
      {open && (
        <div className="flex flex-wrap items-center gap-2 mt-3 text-sm">
          {r.status === 'proposed' && (
            <button disabled={busy} onClick={() => onAct(r.id, 'mark')} className="px-3 py-1 rounded-lg bg-gray-900 text-white disabled:opacity-50">تعليم للدمج</button>
          )}
          {r.status === 'marked' && (
            <button disabled={busy || ownMark} title={ownMark ? 'يعتمده مراجع آخر' : ''} onClick={() => onAct(r.id, 'approve')}
              className="px-3 py-1 rounded-lg bg-emerald-600 text-white disabled:opacity-40">اعتماد</button>
          )}
          <button disabled={busy} onClick={() => onAct(r.id, 'swap')} className="px-3 py-1 rounded-lg border border-gray-300">اجعل {r.old_pic} الرئيسي</button>
          {!rejecting ? (
            <button disabled={busy} onClick={() => setRejecting(true)} className="px-3 py-1 rounded-lg text-red-600">ليس نفس العميل</button>
          ) : (
            <span className="flex items-center gap-2">
              <input autoFocus value={reason} onChange={e => setReason(e.target.value)} placeholder="السبب"
                className="border border-gray-300 rounded-lg px-2 py-1 text-sm w-48" />
              <button disabled={busy || !reason.trim()} onClick={() => onAct(r.id, 'reject', { reason })}
                className="px-3 py-1 rounded-lg bg-red-600 text-white disabled:opacity-40">رفض</button>
              <button onClick={() => setRejecting(false)} className="text-gray-500">إلغاء</button>
            </span>
          )}
          {ownMark && <span className="text-[11px] text-gray-400">علّمته أنت — يعتمده مراجع آخر</span>}
        </div>
      )}
    </div>
  )
}

export default function CustomerMergePage() {
  const [status, setStatus] = useState('proposed')
  const [strength, setStrength] = useState('')
  const [q, setQ] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    customerMergeApi.list({ status, strength: strength || undefined, q: q || undefined })
      .then(r => { setData(r.data); setError(null) }).catch(e => setError(errMsg(e)))
  }, [status, strength, q])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  const act = async (id, action, body) => {
    setBusy(true); setMsg('')
    try { await customerMergeApi.act(id, action, body); load() } catch (e) { setMsg(errMsg(e)) } finally { setBusy(false) }
  }
  const bulk = async (action) => {
    setBusy(true); setMsg('')
    try {
      const r = await customerMergeApi.bulk(action, 'strong', 100)
      setMsg(`${action === 'mark' ? 'تم تعليم' : 'تم اعتماد'} ${r.data.done}`); load()
    } catch (e) { setMsg(errMsg(e)) } finally { setBusy(false) }
  }

  const s = data?.summary || {}
  const count = (st) => Object.values(s[st] || {}).reduce((a, b) => a + b, 0)

  return (
    <div className="p-4 md:p-6 space-y-4" dir="rtl">
      <div>
        <h1 className="text-xl font-bold text-gray-900">دمج الأكواد المكررة</h1>
        <p className="text-sm text-gray-500 mt-1">
          أكواد لنفس العميل على رقم هاتف واحد (الأسماء المختلفة على نفس الرقم = أسرة، لا تُقترح). يعلّم مراجع ويعتمد مراجع آخر.
          الاعتماد لا يكتب في SOFTECH — الدمج ينفذه المدير لاحقًا للأزواج المعتمدة (نقل النقاط وغلق الكود المكرر).
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUSES.map(([k, label]) => (
          <button key={k} onClick={() => setStatus(k)}
            className={`px-3 py-1.5 rounded-lg text-sm border ${status === k ? 'bg-gray-900 text-white border-gray-900' : 'bg-white border-gray-200 text-gray-700'}`}>
            {label}{k !== 'all' && data ? ` (${count(k)})` : ''}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select value={strength} onChange={e => setStrength(e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm">
          {STRENGTHS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="بحث بالكود"
          className="border border-gray-300 rounded-lg px-2 py-1.5 text-sm w-40" />
        <span className="flex-1" />
        {status === 'proposed' && (
          <button disabled={busy} onClick={() => bulk('mark')} className="px-3 py-1.5 rounded-lg border border-gray-300 text-sm">تعليم القوية (حتى 100)</button>
        )}
        {status === 'marked' && (
          <button disabled={busy} onClick={() => bulk('approve')} className="px-3 py-1.5 rounded-lg border border-emerald-300 text-emerald-700 text-sm">اعتماد القوية التي علّمها غيري (حتى 100)</button>
        )}
      </div>

      {msg && <div className="text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-lg px-3 py-2">{msg}</div>}
      {error && <div className="text-sm text-red-700 bg-red-50 rounded-lg px-3 py-2">{error}</div>}
      {!data && !error && <div className="text-sm text-gray-400">جارٍ التحميل…</div>}
      {data && data.rows.length === 0 && <div className="text-sm text-gray-400">لا يوجد</div>}
      {data && data.total > data.rows.length && (
        <div className="text-[11px] text-gray-400">يظهر {data.rows.length} من {data.total} — استخدم البحث أو الدرجة للتضييق</div>
      )}
      <div className="space-y-2">
        {data?.rows.map(r => <Row key={r.id} r={r} me={data.me} onAct={act} busy={busy} />)}
      </div>
    </div>
  )
}
