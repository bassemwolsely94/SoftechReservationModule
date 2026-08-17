/**
 * pages/CallCenterAnalyticsPage.jsx
 *
 * Call Center Supervisor / QA Dashboard
 * Route: /callcenter/analytics
 * Access: admin, supervisor, quality_manager
 *
 * Panels:
 *   📊 Live KPIs       — calls today, answered rate, AHT, quality avg, callbacks
 *   📞 Calls Log       — searchable call list with inline QA scoring
 *   📋 Cases Board     — cases KPIs + open/escalated list
 *   👤 Agent Report    — per-agent call volume + quality ranking
 *   😊 Sentiment       — AI sentiment distribution + trend
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { callCenterApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { formatDistanceToNow, format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt  = (n, d = 0) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: d })
const fmtP = (n)        => Number(n || 0).toFixed(1) + '%'

function timeAgo(dt) {
  if (!dt) return '—'
  try { return formatDistanceToNow(new Date(dt), { addSuffix: true, locale: ar }) } catch { return dt }
}
function fmtDate(dt) {
  if (!dt) return '—'
  try { return format(new Date(dt), 'dd/MM HH:mm') } catch { return dt }
}
function fmtDuration(secs) {
  if (!secs) return '—'
  const m = Math.floor(secs / 60)
  const s = secs % 60
  return m ? `${m}د ${s}ث` : `${s}ث`
}

// ── Purpose labels ────────────────────────────────────────────────────────────

const PURPOSE_META = {
  reservation: { label: 'استفسار حجز',   icon: '📋', cls: 'bg-indigo-50 text-indigo-700' },
  delivery:    { label: 'متابعة توصيل',  icon: '🚚', cls: 'bg-sky-50 text-sky-700' },
  refill:      { label: 'إعادة صرف',      icon: '💊', cls: 'bg-emerald-50 text-emerald-700' },
  complaint:   { label: 'شكوى',           icon: '⚠️', cls: 'bg-red-50 text-red-700' },
  new_order:   { label: 'طلب جديد',       icon: '🛒', cls: 'bg-green-50 text-green-700' },
  address:     { label: 'تحديث عنوان',   icon: '📍', cls: 'bg-amber-50 text-amber-700' },
  followup:    { label: 'متابعة مزمن',   icon: '🔔', cls: 'bg-purple-50 text-purple-700' },
  demand:      { label: 'صنف غير متوفر', icon: '🔍', cls: 'bg-orange-50 text-orange-700' },
  general:     { label: 'استفسار عام',   icon: '💬', cls: 'bg-gray-50 text-gray-700' },
}

const SENTIMENT_META = {
  positive: { label: 'إيجابي',  icon: '😊', cls: 'bg-green-50 text-green-700',  bar: 'bg-green-500' },
  neutral:  { label: 'محايد',   icon: '😐', cls: 'bg-gray-50 text-gray-700',    bar: 'bg-gray-400' },
  negative: { label: 'سلبي',    icon: '😟', cls: 'bg-red-50 text-red-700',      bar: 'bg-red-500' },
}

const CALL_STATUS_META = {
  answered:  { label: 'تمت',      cls: 'bg-green-100 text-green-700' },
  no_answer: { label: 'لا رد',    cls: 'bg-red-100 text-red-700' },
  busy:      { label: 'مشغول',    cls: 'bg-amber-100 text-amber-700' },
  voicemail: { label: 'بريد صوتي',cls: 'bg-blue-100 text-blue-700' },
  callback:  { label: 'معاودة',   cls: 'bg-purple-100 text-purple-700' },
}

const CASE_STATUS_META = {
  open:      { label: 'مفتوحة',      cls: 'bg-blue-100 text-blue-800' },
  working:   { label: 'قيد المعالجة',cls: 'bg-indigo-100 text-indigo-800' },
  waiting:   { label: 'انتظار',       cls: 'bg-yellow-100 text-yellow-800' },
  escalated: { label: 'مُصعَّدة',    cls: 'bg-red-100 text-red-800', pulse: true },
  resolved:  { label: 'محلولة',       cls: 'bg-green-100 text-green-800' },
  closed:    { label: 'مغلقة',        cls: 'bg-gray-100 text-gray-700' },
}

// ── Shared components ─────────────────────────────────────────────────────────

function KpiCard({ icon, label, value, sub, color = 'indigo', pulse = false }) {
  const colors = {
    indigo:  'border-indigo-100 bg-indigo-50',
    emerald: 'border-emerald-100 bg-emerald-50',
    sky:     'border-sky-100 bg-sky-50',
    amber:   'border-amber-100 bg-amber-50',
    red:     'border-red-100 bg-red-50',
    gray:    'border-gray-100 bg-gray-50',
  }
  const textColors = {
    indigo:  'text-indigo-700', emerald: 'text-emerald-700',
    sky:     'text-sky-700',    amber:   'text-amber-700',
    red:     'text-red-700',    gray:    'text-gray-700',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]} ${pulse ? 'ring-2 ring-red-300 animate-pulse' : ''}`}>
      <div className="text-xl mb-1">{icon}</div>
      <div className={`text-xs font-medium opacity-70 ${textColors[color]}`}>{label}</div>
      <div className={`text-2xl font-black mt-0.5 ${textColors[color]}`}>{value}</div>
      {sub && <div className={`text-xs opacity-60 mt-0.5 ${textColors[color]}`}>{sub}</div>}
    </div>
  )
}

function StatusBadge({ status, meta }) {
  const m = meta[status]
  if (!m) return null
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${m.cls}
                      ${m.pulse ? 'ring-1 ring-red-300 animate-pulse' : ''}`}>
      {m.label}
    </span>
  )
}

// ── QA Scoring Modal ──────────────────────────────────────────────────────────

function QAScoreModal({ call, onClose }) {
  const qc = useQueryClient()
  const [scores, setScores] = useState({
    greeting: 0, resolution: 0, communication: 0, accuracy: 0,
  })
  const [notes, setNotes] = useState('')

  const { data: existing } = useQuery({
    queryKey: ['call-quality', call.id],
    queryFn:  () => callCenterApi.getQuality(call.id).then(r => r.data),
    onSuccess: q => {
      if (q) {
        setScores({ greeting: q.greeting, resolution: q.resolution,
                    communication: q.communication, accuracy: q.accuracy })
        setNotes(q.notes || '')
      }
    },
    retry: false,
  })

  const mutation = useMutation({
    mutationFn: (data) => existing
      ? callCenterApi.updateQuality(call.id, data)
      : callCenterApi.createQuality(call.id, data),
    onSuccess: () => {
      qc.invalidateQueries(['callcenter-calls'])
      qc.invalidateQueries(['callcenter-dashboard'])
      qc.invalidateQueries(['call-quality', call.id])
      onClose()
    },
  })

  const total = scores.greeting + scores.resolution + scores.communication + scores.accuracy

  const RUBRIC = [
    { key: 'greeting',      label: 'الترحيب والتعريف',  max: 20 },
    { key: 'resolution',    label: 'حل المشكلة',         max: 30 },
    { key: 'communication', label: 'وضوح التواصل',       max: 25 },
    { key: 'accuracy',      label: 'دقة المعلومات',      max: 25 },
  ]

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="font-bold text-gray-900">تقييم جودة المكالمة</h3>
            <p className="text-xs text-gray-500 mt-0.5">
              {call.caller_name || call.phone_number} · {fmtDate(call.called_at)}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {/* Score sliders */}
        <div className="space-y-4">
          {RUBRIC.map(({ key, label, max }) => (
            <div key={key}>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-medium text-gray-700">{label}</label>
                <span className="text-sm font-bold text-indigo-700">{scores[key]} / {max}</span>
              </div>
              <input type="range" min={0} max={max} value={scores[key]}
                onChange={e => setScores(p => ({ ...p, [key]: +e.target.value }))}
                className="w-full accent-indigo-600 h-1.5" />
            </div>
          ))}
        </div>

        {/* Total */}
        <div className={`mt-4 rounded-xl p-3 text-center font-black text-2xl
                         ${total >= 80 ? 'bg-green-50 text-green-700' : total >= 60 ? 'bg-amber-50 text-amber-700' : 'bg-red-50 text-red-700'}`}>
          {total} / 100
          <div className="text-xs font-normal opacity-70 mt-0.5">
            {total >= 80 ? 'ممتاز' : total >= 60 ? 'جيد' : total >= 40 ? 'مقبول' : 'يحتاج تحسين'}
          </div>
        </div>

        {/* Notes */}
        <textarea
          value={notes} onChange={e => setNotes(e.target.value)}
          placeholder="ملاحظات التقييم (اختياري)…"
          rows={2}
          className="mt-3 w-full border border-gray-200 rounded-xl px-3 py-2 text-sm
                     focus:outline-none focus:border-indigo-400 resize-none"
        />

        {/* Actions */}
        <div className="mt-4 flex gap-2">
          <button onClick={onClose}
            className="flex-1 px-4 py-2 rounded-xl border border-gray-200 text-sm text-gray-600 hover:bg-gray-50 transition-colors">
            إلغاء
          </button>
          <button onClick={() => mutation.mutate({ ...scores, notes })}
            disabled={mutation.isLoading}
            className="flex-1 px-4 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium
                       hover:bg-indigo-700 disabled:opacity-50 transition-colors">
            {mutation.isLoading ? 'جارٍ الحفظ…' : existing ? 'تحديث التقييم' : 'حفظ التقييم'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Tab: Live KPIs ────────────────────────────────────────────────────────────

function KpiTab() {
  const qc = useQueryClient()

  const { data: callStats, isLoading: callsLoading } = useQuery({
    queryKey: ['callcenter-dashboard'],
    queryFn:  () => callCenterApi.dashboard().then(r => r.data),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const { data: caseStats, isLoading: casesLoading } = useQuery({
    queryKey: ['callcenter-cases-dashboard'],
    queryFn:  () => callCenterApi.cases.dashboard().then(r => r.data),
    staleTime: 30_000,
  })

  const s = callStats || {}
  const c = caseStats || {}

  const totalSentiment = (s.sentiment?.positive || 0) + (s.sentiment?.neutral || 0) + (s.sentiment?.negative || 0)
  const answeredPct    = s.total_calls ? Math.round(s.answered / s.total_calls * 100) : 0

  return (
    <div dir="rtl" className="p-4 space-y-6">

      {/* Main KPI row */}
      {callsLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[...Array(6)].map((_, i) => <div key={i} className="h-24 rounded-xl bg-gray-100 animate-pulse" />)}
        </div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <KpiCard icon="📞" label="مكالمات اليوم"    value={fmt(s.today)}                color="indigo" />
          <KpiCard icon="✅" label="نسبة الإجابة"     value={fmtP(answeredPct)}           color="emerald"
                   sub={`${fmt(s.answered)} مكالمة`} />
          <KpiCard icon="⏱️" label="متوسط المدة"     value={fmtDuration(Math.round(s.avg_duration_seconds))} color="sky" />
          <KpiCard icon="⭐" label="متوسط جودة"       value={s.avg_quality_score ? s.avg_quality_score.toFixed(1) : '—'}
                   sub={`${fmt(s.scored_calls_pct)}% مُقيَّمة`} color="amber" />
          <KpiCard icon="🔄" label="معاودات متأخرة"  value={fmt(s.pending_callbacks)}     color={s.pending_callbacks > 0 ? 'red' : 'gray'}
                   pulse={s.pending_callbacks > 5} />
          <KpiCard icon="📍" label="تحديثات عنوان"   value={fmt(s.address_updates_pending)} color="amber" />
        </div>
      )}

      {/* Two-column: Purpose + Sentiment */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Purpose breakdown */}
        <div className="rounded-xl border border-gray-100 bg-white p-4">
          <h3 className="font-bold text-gray-800 mb-3 text-sm">توزيع أغراض المكالمات (30 يوم)</h3>
          {callsLoading ? (
            <div className="space-y-2">
              {[...Array(5)].map((_, i) => <div key={i} className="h-6 bg-gray-100 animate-pulse rounded" />)}
            </div>
          ) : (
            <div className="space-y-2">
              {(s.by_purpose || []).map(p => {
                const meta = PURPOSE_META[p.purpose] || { label: p.purpose, icon: '💬', cls: 'bg-gray-50 text-gray-700' }
                const pct  = s.total_calls ? (p.count / s.total_calls * 100).toFixed(1) : 0
                return (
                  <div key={p.purpose} className="flex items-center gap-2">
                    <span className="text-sm w-4">{meta.icon}</span>
                    <span className="text-xs text-gray-600 w-28 shrink-0">{meta.label}</span>
                    <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div className="h-full bg-indigo-400 rounded-full"
                           style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-xs tabular-nums text-gray-500 w-16 text-right">
                      {fmt(p.count)} ({pct}%)
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Sentiment */}
        <div className="rounded-xl border border-gray-100 bg-white p-4">
          <h3 className="font-bold text-gray-800 mb-3 text-sm">تحليل مشاعر العملاء (AI)</h3>
          {callsLoading ? (
            <div className="space-y-2">
              {[...Array(3)].map((_, i) => <div key={i} className="h-12 bg-gray-100 animate-pulse rounded" />)}
            </div>
          ) : totalSentiment === 0 ? (
            <div className="py-6 text-center text-gray-400 text-sm">
              لا توجد بيانات مشاعر حتى الآن
            </div>
          ) : (
            <div className="space-y-3">
              {['positive', 'neutral', 'negative'].map(key => {
                const meta = SENTIMENT_META[key]
                const cnt  = s.sentiment?.[key] || 0
                const pct  = totalSentiment ? (cnt / totalSentiment * 100).toFixed(1) : 0
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm">{meta.icon} {meta.label}</span>
                      <span className="text-xs font-semibold text-gray-700">{fmt(cnt)} ({pct}%)</span>
                    </div>
                    <div className="h-2.5 bg-gray-100 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${meta.bar}`}
                           style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Cases KPIs */}
      {caseStats && (
        <div className="rounded-xl border border-gray-100 bg-white p-4">
          <h3 className="font-bold text-gray-800 mb-3 text-sm">حالات العملاء</h3>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <KpiCard icon="🆕" label="مفتوحة" value={fmt(c.open_cases)}       color={c.open_cases > 20 ? 'amber' : 'sky'} />
            <KpiCard icon="🔴" label="مُصعَّدة" value={fmt(c.escalated_cases)} color={c.escalated_cases > 0 ? 'red' : 'gray'} pulse={c.escalated_cases > 0} />
            <KpiCard icon="✅" label="حُلَّت اليوم" value={fmt(c.resolved_today)} color="emerald" />
            <KpiCard icon="⏱️" label="متوسط حل (ساعة)" value={c.avg_resolution_hours ? c.avg_resolution_hours.toFixed(1) : '—'} color="indigo" />
          </div>
        </div>
      )}
    </div>
  )
}

// ── Tab: Calls Log ────────────────────────────────────────────────────────────

function CallsTab() {
  const [search,     setSearch]     = useState('')
  const [statusF,    setStatusF]    = useState('')
  const [purposeF,   setPurposeF]   = useState('')
  const [directionF, setDirectionF] = useState('')
  const [scoringCall, setScoringCall] = useState(null)
  const timer = useRef(null)

  const [debouncedSearch, setDebouncedSearch] = useState('')
  const handleSearch = e => {
    setSearch(e.target.value)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setDebouncedSearch(e.target.value), 350)
  }

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['callcenter-calls', debouncedSearch, statusF, purposeF, directionF],
    queryFn: () => callCenterApi.list({
      search:    debouncedSearch || undefined,
      status:    statusF    || undefined,
      purpose:   purposeF   || undefined,
      direction: directionF || undefined,
      page_size: 50,
    }).then(r => r.data),
    staleTime: 30_000,
  })

  const rows = data?.results || data || []

  return (
    <div dir="rtl">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 p-4 border-b border-gray-100">
        <div className="relative flex-1 min-w-40">
          <span className="absolute inset-y-0 right-3 flex items-center text-gray-400 pointer-events-none text-sm">🔍</span>
          <input value={search} onChange={handleSearch}
            placeholder="بحث باسم / هاتف / ملاحظات…"
            className="w-full border border-gray-200 rounded-xl pr-9 pl-3 py-2 text-sm focus:outline-none focus:border-indigo-400" />
        </div>
        <select value={statusF} onChange={e => setStatusF(e.target.value)}
          className="border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-indigo-400">
          <option value="">كل الحالات</option>
          {Object.entries(CALL_STATUS_META).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        <select value={purposeF} onChange={e => setPurposeF(e.target.value)}
          className="border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-indigo-400">
          <option value="">كل الأغراض</option>
          {Object.entries(PURPOSE_META).map(([k, v]) => (
            <option key={k} value={k}>{v.icon} {v.label}</option>
          ))}
        </select>
        <select value={directionF} onChange={e => setDirectionF(e.target.value)}
          className="border border-gray-200 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-indigo-400">
          <option value="">كل الاتجاهات</option>
          <option value="inbound">واردة 📲</option>
          <option value="outbound">صادرة 📞</option>
          <option value="whatsapp">واتساب 💬</option>
        </select>
        {isFetching && <span className="text-xs text-indigo-500 animate-pulse">تحميل…</span>}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="p-12 text-center text-gray-400">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center text-gray-400">لا توجد مكالمات</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100 text-gray-500 text-xs">
                <th className="text-right px-4 py-3 font-medium">المتصل</th>
                <th className="text-right px-4 py-3 font-medium">التوقيت</th>
                <th className="text-right px-4 py-3 font-medium">الغرض</th>
                <th className="text-right px-4 py-3 font-medium">الحالة</th>
                <th className="text-right px-4 py-3 font-medium">المدة</th>
                <th className="text-right px-4 py-3 font-medium">المندوب</th>
                <th className="text-right px-4 py-3 font-medium">المشاعر</th>
                <th className="text-right px-4 py-3 font-medium">جودة</th>
                <th className="text-right px-4 py-3 font-medium w-10"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((call, i) => {
                const purpose = PURPOSE_META[call.purpose]
                const sent    = SENTIMENT_META[call.ai_sentiment]
                return (
                  <tr key={call.id}
                    className={`border-b border-gray-50 hover:bg-indigo-50/30 transition-colors
                                ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/40'}`}>
                    <td className="px-4 py-2.5">
                      <div className="font-medium text-gray-800 leading-tight">
                        {call.caller_name || call.phone_number}
                      </div>
                      {call.customer_name && call.caller_name !== call.customer_name && (
                        <div className="text-xs text-gray-400">{call.customer_name}</div>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500">
                      {fmtDate(call.called_at)}
                    </td>
                    <td className="px-4 py-2.5">
                      {purpose && (
                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs ${purpose.cls}`}>
                          {purpose.icon} {purpose.label}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={call.status} meta={CALL_STATUS_META} />
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 tabular-nums">
                      {fmtDuration(call.duration_seconds)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">
                      {call.handled_by_name || '—'}
                    </td>
                    <td className="px-4 py-2.5 text-sm">
                      {sent ? <span title={sent.label}>{sent.icon}</span> : '—'}
                    </td>
                    <td className="px-4 py-2.5">
                      {call.quality_score !== null && call.quality_score !== undefined ? (
                        <span className={`text-xs font-bold px-1.5 py-0.5 rounded
                          ${call.quality_score >= 80 ? 'bg-green-100 text-green-700'
                          : call.quality_score >= 60 ? 'bg-amber-100 text-amber-700'
                          : 'bg-red-100 text-red-700'}`}>
                          {call.quality_score}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <button
                        onClick={() => setScoringCall(call)}
                        className="text-xs text-indigo-500 hover:text-indigo-700 hover:bg-indigo-50
                                   px-1.5 py-1 rounded transition-colors"
                        title="تقييم جودة المكالمة"
                      >
                        ⭐
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* QA Modal */}
      {scoringCall && (
        <QAScoreModal call={scoringCall} onClose={() => setScoringCall(null)} />
      )}
    </div>
  )
}

// ── Tab: Agent Report ─────────────────────────────────────────────────────────

function AgentTab() {
  const { data: stats } = useQuery({
    queryKey: ['callcenter-dashboard'],
    queryFn:  () => callCenterApi.dashboard().then(r => r.data),
    staleTime: 60_000,
  })

  const agents = stats?.by_staff || []
  if (!agents.length) return (
    <div className="p-12 text-center text-gray-400">لا توجد بيانات مندوبين</div>
  )

  const maxCount = Math.max(...agents.map(a => a.count), 1)

  return (
    <div dir="rtl" className="p-4">
      <h3 className="font-bold text-gray-800 mb-4 text-sm">أداء المندوبين — آخر 30 يوم</h3>
      <div className="space-y-3">
        {agents.map((agent, i) => {
          const name = [
            agent['handled_by__user__first_name'],
            agent['handled_by__user__last_name'],
          ].filter(Boolean).join(' ') || 'غير محدد'
          const pct = (agent.count / maxCount * 100).toFixed(1)
          return (
            <div key={i} className="bg-white rounded-xl border border-gray-100 p-3">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold
                    ${i === 0 ? 'bg-yellow-400 text-yellow-900'
                    : i === 1 ? 'bg-gray-300 text-gray-700'
                    : i === 2 ? 'bg-amber-600 text-white'
                    : 'bg-gray-100 text-gray-600'}`}>
                    {i + 1}
                  </span>
                  <span className="font-medium text-gray-800 text-sm">{name}</span>
                </div>
                <span className="text-sm font-bold text-indigo-700">{fmt(agent.count)} مكالمة</span>
              </div>
              <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-indigo-500 rounded-full transition-all"
                     style={{ width: `${pct}%` }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Tab: Cases Board ──────────────────────────────────────────────────────────

function CasesBoardTab() {
  const [statusF, setStatusF] = useState('open')

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ['callcenter-cases-list', statusF],
    queryFn: () => callCenterApi.cases.list({
      status:    statusF || undefined,
      ordering:  '-created_at',
      page_size: 50,
    }).then(r => r.data),
    staleTime: 30_000,
  })

  const rows = data?.results || data || []

  return (
    <div dir="rtl">
      {/* Filter strip */}
      <div className="flex flex-wrap items-center gap-2 p-4 border-b border-gray-100">
        {Object.entries(CASE_STATUS_META).map(([k, v]) => (
          <button key={k} onClick={() => setStatusF(k)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
              ${statusF === k ? `${v.cls} ring-2 ring-offset-1 ring-indigo-400` : 'bg-gray-50 text-gray-600 hover:bg-gray-100'}`}>
            {v.label}
          </button>
        ))}
        <button onClick={() => setStatusF('')}
          className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors
            ${!statusF ? 'bg-gray-800 text-white' : 'bg-gray-50 text-gray-600 hover:bg-gray-100'}`}>
          الكل
        </button>
        {isFetching && <span className="text-xs text-indigo-500 animate-pulse">تحميل…</span>}
      </div>

      {/* Cases table */}
      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="p-12 text-center text-gray-400">جارٍ التحميل…</div>
        ) : rows.length === 0 ? (
          <div className="p-12 text-center text-gray-400">لا توجد حالات</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100 text-gray-500 text-xs">
                <th className="text-right px-4 py-3 font-medium">رقم الحالة</th>
                <th className="text-right px-4 py-3 font-medium">العميل</th>
                <th className="text-right px-4 py-3 font-medium">الموضوع</th>
                <th className="text-right px-4 py-3 font-medium">التصنيف</th>
                <th className="text-right px-4 py-3 font-medium">الأولوية</th>
                <th className="text-right px-4 py-3 font-medium">الحالة</th>
                <th className="text-right px-4 py-3 font-medium">المعيَّن له</th>
                <th className="text-right px-4 py-3 font-medium">منذ</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.id}
                  className={`border-b border-gray-50 hover:bg-indigo-50/30 transition-colors
                              ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/40'}
                              ${c.status === 'escalated' ? 'ring-inset ring-1 ring-red-200' : ''}`}>
                  <td className="px-4 py-2.5">
                    <span className="text-xs font-mono text-indigo-600">{c.case_number}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="font-medium text-gray-800 leading-tight">{c.customer_name}</div>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="text-gray-700 text-xs leading-tight max-w-48 truncate">{c.title}</div>
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-600">{c.category_label || c.category}</td>
                  <td className="px-4 py-2.5">
                    <span className={`text-xs font-semibold ${
                      c.priority === 'urgent' ? 'text-red-600'
                      : c.priority === 'high' ? 'text-orange-600'
                      : 'text-gray-500'
                    }`}>
                      {c.priority === 'urgent' ? 'عاجلة 🔴'
                       : c.priority === 'high' ? 'مرتفعة'
                       : c.priority === 'normal' ? 'عادية'
                       : 'منخفضة'}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <StatusBadge status={c.status} meta={CASE_STATUS_META} />
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-600">
                    {c.assigned_to_name || <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-gray-400">
                    {timeAgo(c.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Root Page ─────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'kpi',    label: '📊 مؤشرات الأداء' },
  { id: 'calls',  label: '📞 سجل المكالمات' },
  { id: 'cases',  label: '📋 لوحة الحالات' },
  { id: 'agents', label: '👤 أداء المندوبين' },
]

export default function CallCenterAnalyticsPage() {
  const [activeTab, setActiveTab] = useState('kpi')
  const { user } = useAuthStore()

  // Access guard — supervisor/admin/quality_manager only
  const allowed = ['admin', 'supervisor', 'quality_manager', 'call_center'].includes(user?.role)
  if (!allowed) return (
    <div className="flex flex-col items-center justify-center h-full py-24 text-gray-400">
      <div className="text-4xl mb-2">🔒</div>
      <div>هذه الصفحة للمشرفين فقط</div>
    </div>
  )

  return (
    <div dir="rtl" className="flex flex-col h-full bg-gray-50 min-h-screen">
      {/* Page header */}
      <div className="bg-white border-b border-gray-100 px-6 py-5">
        <h1 className="text-xl font-black text-gray-900">لوحة مركز الاتصال</h1>
        <p className="text-xs text-gray-500 mt-0.5">
          مراقبة جودة المكالمات · إدارة الحالات · أداء المندوبين
        </p>
      </div>

      {/* Tab bar */}
      <div className="bg-white border-b border-gray-100 px-6">
        <div className="flex gap-1 -mb-px">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)}
              className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors
                ${activeTab === t.id
                  ? 'border-indigo-500 text-indigo-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-200'}`}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto bg-white">
        {activeTab === 'kpi'    && <KpiTab />}
        {activeTab === 'calls'  && <CallsTab />}
        {activeTab === 'cases'  && <CasesBoardTab />}
        {activeTab === 'agents' && <AgentTab />}
      </div>
    </div>
  )
}
