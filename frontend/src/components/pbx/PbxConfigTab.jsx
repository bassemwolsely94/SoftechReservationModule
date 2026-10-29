import { useMutation, useQuery } from '@tanstack/react-query'
import { pbxApi } from '../../api/client'
import WhisperPanel from './WhisperPanel'
import ExtensionsPanel from './ExtensionsPanel'

const STATUS_META = {
  ok:   { icon: '✅', cls: 'border-green-200 bg-green-50 dark:bg-green-900/20 dark:border-green-800' },
  warn: { icon: '⚠️', cls: 'border-amber-200 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-800' },
  fail: { icon: '❌', cls: 'border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-800' },
  skip: { icon: '⏭️', cls: 'border-gray-200 bg-gray-50 dark:bg-gray-800 dark:border-gray-700 opacity-60' },
}

const OVERALL = {
  ok:   'كل الفحوصات سليمة',
  warn: 'يعمل مع ملاحظات',
  fail: 'يوجد عطل — أول خطوة حمراء هي السبب',
}

const fmt = (dt) => dt ? new Date(dt).toLocaleString('ar-EG', {
  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit',
}) : '—'

export function PbxStatusBadge() {
  const { data } = useQuery({
    queryKey: ['pbx-status'],
    queryFn: () => pbxApi.status().then(r => r.data),
    refetchInterval: 30_000,
  })
  if (!data) return null
  const ok = data.alive && data.state === 'connected'
  return (
    <span title={data.last_error || ''}
      className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${
        ok ? 'border-green-200 text-green-700 dark:text-green-300'
           : 'border-red-200 text-red-700 dark:text-red-300'}`}>
      <span className={`w-2 h-2 rounded-full ${ok ? 'bg-green-500' : 'bg-red-500 animate-pulse'}`} />
      السنترال: {data.label}
    </span>
  )
}

export default function PbxConfigTab() {
  const { data: status, refetch } = useQuery({
    queryKey: ['pbx-status'],
    queryFn: () => pbxApi.status().then(r => r.data),
    refetchInterval: 30_000,
  })
  const diag = useMutation({
    mutationFn: () => pbxApi.diagnostics().then(r => r.data),
    onSettled: () => refetch(),
  })

  return (
    <div className="space-y-6 max-w-4xl">
      <section className="card">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-600 dark:text-gray-300">حالة الربط مع السنترال</h2>
          <PbxStatusBadge />
        </div>
        {status && (
          <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-2 text-sm">
            <div><dt className="text-xs text-gray-400">السيرفر</dt><dd className="font-mono" dir="ltr">{status.host || '—'}:{status.port}</dd></div>
            <div><dt className="text-xs text-gray-400">الإصدار</dt><dd className="font-mono text-xs" dir="ltr">{status.banner || '—'}</dd></div>
            <div><dt className="text-xs text-gray-400">متصل منذ</dt><dd>{fmt(status.connected_since)}</dd></div>
            <div><dt className="text-xs text-gray-400">آخر نبضة</dt><dd>{fmt(status.last_heartbeat_at)}</dd></div>
            <div><dt className="text-xs text-gray-400">آخر حدث مكالمة</dt><dd>{fmt(status.last_event_at)}</dd></div>
            <div><dt className="text-xs text-gray-400">مرات إعادة الاتصال</dt><dd>{status.reconnect_count ?? '—'}</dd></div>
            {status.last_error && (
              <div className="col-span-full">
                <dt className="text-xs text-gray-400">آخر خطأ ({fmt(status.last_error_at)})</dt>
                <dd className="font-mono text-xs text-red-600 dark:text-red-400 break-all" dir="ltr">{status.last_error}</dd>
              </div>
            )}
          </dl>
        )}
      </section>

      <section className="card">
        <div className="flex items-center justify-between mb-3 gap-3">
          <div>
            <h2 className="text-sm font-semibold text-gray-600 dark:text-gray-300">فحص الاتصال خطوة بخطوة</h2>
            <p className="text-xs text-gray-400 mt-0.5">يفحص الإعدادات ← الشبكة ← AMI ← الدخول ← عملية الأحداث ← التسجيلات، ويشرح سبب أي عطل.</p>
          </div>
          <button data-tour="callcenter-pbx-diagnose" onClick={() => diag.mutate()} disabled={diag.isPending}
            className="btn-primary text-sm px-4 py-1.5 shrink-0 disabled:opacity-50">
            {diag.isPending ? '⏳ جارٍ الفحص…' : '🩺 فحص الاتصال'}
          </button>
        </div>

        {diag.isError && (
          <div className="text-sm text-red-600">{diag.error?.response?.data?.detail || 'تعذر تشغيل الفحص'}</div>
        )}

        {diag.data && (
          <div className="space-y-2">
            <div className="text-sm font-medium">
              {STATUS_META[diag.data.overall]?.icon} {OVERALL[diag.data.overall]}
            </div>
            {diag.data.steps.map(s => (
              <div key={s.key} className={`rounded-lg border px-3 py-2 ${STATUS_META[s.status]?.cls}`}>
                <div className="flex items-center gap-2 text-sm">
                  <span>{STATUS_META[s.status]?.icon}</span>
                  <span className="font-medium text-gray-800 dark:text-gray-100">{s.label}</span>
                  <span className="text-gray-500 dark:text-gray-400 text-xs truncate" dir="auto">{s.detail}</span>
                  {s.ms != null && <span className="mr-auto text-xs text-gray-400 tabular-nums">{s.ms} ms</span>}
                </div>
                {s.hint && <div className="text-xs text-gray-600 dark:text-gray-300 mt-1 pr-6">💡 {s.hint}</div>}
              </div>
            ))}
          </div>
        )}
      </section>

      <div data-tour="callcenter-pbx-extensions"><ExtensionsPanel /></div>

      <div data-tour="callcenter-pbx-whisper"><WhisperPanel /></div>
    </div>
  )
}
