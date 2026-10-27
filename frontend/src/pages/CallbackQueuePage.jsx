import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { callCenterApi, pbxApi } from '../api/client'
import { formatDistanceToNow, format, isPast, parseISO } from 'date-fns'
import { ar } from 'date-fns/locale'

// ── helpers ───────────────────────────────────────────────────────────────────

function dueBadge(dueDateStr) {
  if (!dueDateStr) return null
  const d = parseISO(dueDateStr)
  const overdue = isPast(d)
  const rel = formatDistanceToNow(d, { addSuffix: true, locale: ar })
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
      overdue
        ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
        : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
    }`}>
      {overdue ? '⚠ ' : '⏰ '}{rel}
    </span>
  )
}

function purposeLabel(p) {
  const MAP = {
    reservation: 'حجز',
    follow_up:   'متابعة',
    complaint:   'شكوى',
    inquiry:     'استفسار',
    other:       'أخرى',
  }
  return MAP[p] || p || '—'
}

// ── main component ────────────────────────────────────────────────────────────

export default function CallbackQueuePage() {
  const navigate    = useNavigate()
  const qc          = useQueryClient()
  const [mode, setMode]             = useState('all')        // 'overdue' | 'all'
  const [dialLoading, setDialLoading] = useState(null)       // call id being dialled
  const [doneLoading, setDoneLoading] = useState(null)       // call id being marked done
  const [toast, setToast]           = useState(null)

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3500)
  }, [])

  const { data: callbacks = [], isLoading, isError, refetch } = useQuery({
    queryKey: ['callbacks', mode],
    queryFn:  () => callCenterApi.pendingCallbacks(mode).then(r => r.data),
    refetchInterval: 60_000,
  })

  // ── overdue count badge (always 'overdue' mode, short poll) ──────────────
  const { data: overdueData = [] } = useQuery({
    queryKey: ['callbacks', 'overdue'],
    queryFn:  () => callCenterApi.pendingCallbacks('overdue').then(r => r.data),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
  const overdueCount = overdueData.length

  // ── dial ──────────────────────────────────────────────────────────────────
  async function handleDial(phone, callId) {
    if (!phone) return showToast('لا يوجد رقم هاتف مسجل', 'error')
    setDialLoading(callId)
    try {
      await pbxApi.dial({ destination: phone })
      showToast('سيرن هاتفك الآن — عند الرد سيُحوَّل للعميل', 'success')
    } catch (e) {
      showToast(e?.response?.data?.detail || 'فشل بدء المكالمة', 'error')
    } finally {
      setDialLoading(null)
    }
  }

  // ── mark done ─────────────────────────────────────────────────────────────
  async function handleMarkDone(callId) {
    setDoneLoading(callId)
    try {
      await callCenterApi.markCallbackDone(callId)
      showToast('تم تحديث حالة المكالمة', 'success')
      qc.invalidateQueries({ queryKey: ['callbacks'] })
    } catch (e) {
      showToast(e?.response?.data?.detail || 'فشل التحديث', 'error')
    } finally {
      setDoneLoading(null)
    }
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-4" dir="rtl">

      {/* ── Toast ── */}
      {toast && (
        <div className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-xl shadow-lg text-sm font-medium text-white transition-all ${
          toast.type === 'success' ? 'bg-green-600'
          : toast.type === 'error' ? 'bg-red-600'
          : 'bg-blue-600'
        }`}>
          {toast.msg}
        </div>
      )}

      {/* ── Header ── */}
      <div className="max-w-5xl mx-auto mb-4 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <button data-tour="callcenter-callbacks-back"
            onClick={() => navigate('/callcenter')}
            className="text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
          >
            ← مركز الاتصال
          </button>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">
            طابور المعاودة
            {overdueCount > 0 && (
              <span className="mr-2 bg-red-600 text-white text-xs font-bold px-2 py-0.5 rounded-full">
                {overdueCount} متأخر
              </span>
            )}
          </h1>
        </div>

        {/* mode toggle */}
        <div data-tour="callcenter-callbacks-mode" className="flex bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden text-sm">
          {['overdue', 'all'].map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-4 py-1.5 transition-colors ${
                mode === m
                  ? 'bg-navy-600 text-white'
                  : 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700'
              }`}
            >
              {m === 'overdue' ? '⚠ متأخرة فقط' : '📋 الكل'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Content ── */}
      <div className="max-w-5xl mx-auto">
        {isLoading && (
          <div className="text-center py-16 text-gray-400">جاري التحميل…</div>
        )}
        {isError && (
          <div className="text-center py-16 text-red-500">
            حدث خطأ — <button onClick={refetch} className="underline">إعادة المحاولة</button>
          </div>
        )}
        {!isLoading && !isError && callbacks.length === 0 && (
          <div className="text-center py-16 text-gray-400 dark:text-gray-500">
            <div className="text-4xl mb-3">✅</div>
            <div className="text-lg font-medium">لا توجد مكالمات معلقة</div>
            <div className="text-sm mt-1">
              {mode === 'overdue' ? 'لا توجد مكالمات متأخرة' : 'لا توجد مكالمات مجدولة للمعاودة'}
            </div>
          </div>
        )}

        {!isLoading && callbacks.length > 0 && (
          <div className="space-y-3">
            {callbacks.map(call => {
              const phone    = call.customer?.phone || call.caller_number || null
              const name     = call.customer?.name  || call.caller_name  || 'غير محدد'
              const isOverdue = call.callback_due && isPast(parseISO(call.callback_due))

              return (
                <div
                  key={call.id}
                  data-tour="callcenter-callbacks-card"
                  className={`bg-white dark:bg-gray-800 rounded-xl border p-4 flex gap-4 items-start transition-colors ${
                    isOverdue
                      ? 'border-red-300 dark:border-red-700'
                      : 'border-gray-200 dark:border-gray-700'
                  }`}
                >
                  {/* overdue stripe */}
                  {isOverdue && (
                    <div className="absolute right-0 top-0 bottom-0 w-1 rounded-r-xl bg-red-500" />
                  )}

                  {/* left: customer info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-gray-900 dark:text-gray-100">{name}</span>
                      {call.purpose && (
                        <span className="text-xs bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-2 py-0.5 rounded-full">
                          {purposeLabel(call.purpose)}
                        </span>
                      )}
                      {dueBadge(call.callback_due)}
                    </div>

                    {phone && (
                      <div className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 font-mono ltr">
                        {phone}
                      </div>
                    )}

                    {call.notes && (
                      <div className="text-sm text-gray-600 dark:text-gray-300 mt-1 line-clamp-2">
                        {call.notes}
                      </div>
                    )}

                    <div className="mt-2 flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
                      {call.handled_by_name && <span>👤 {call.handled_by_name}</span>}
                      {call.called_at && (
                        <span>
                          📞 {format(parseISO(call.called_at), 'dd/MM HH:mm')}
                        </span>
                      )}
                      {call.callback_due && (
                        <span>
                          🎯 {format(parseISO(call.callback_due), 'dd/MM HH:mm')}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* right: actions */}
                  <div className="flex flex-col gap-2 shrink-0">
                    <button data-tour="callcenter-callbacks-dial"
                      onClick={() => handleDial(phone, call.id)}
                      disabled={!phone || dialLoading === call.id}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-700 text-white text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {dialLoading === call.id ? '⏳' : '📞'} اتصال
                    </button>

                    <button data-tour="callcenter-callbacks-view"
                      onClick={() => navigate(`/callcenter?call=${call.id}`)}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 text-sm transition-colors"
                    >
                      📋 عرض
                    </button>

                    <button data-tour="callcenter-callbacks-done"
                      onClick={() => handleMarkDone(call.id)}
                      disabled={doneLoading === call.id}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-green-200 dark:border-green-700 hover:bg-green-50 dark:hover:bg-green-900/30 text-green-700 dark:text-green-400 text-sm disabled:opacity-50 transition-colors"
                    >
                      {doneLoading === call.id ? '⏳' : '✓'} تم
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
