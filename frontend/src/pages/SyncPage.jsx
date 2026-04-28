import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { syncApi } from '../api/client'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'
import { SkeletonCard, EmptyState, PageHeader, SectionTitle, Spinner } from '../components/ui'

const STATUS_CFG = {
  success: { cls: 'bg-green-100 text-green-700', dot: 'bg-green-500', label: 'نجح' },
  failed:  { cls: 'bg-red-100 text-red-700',     dot: 'bg-red-500',   label: 'فشل' },
  running: { cls: 'bg-yellow-100 text-yellow-700', dot: 'bg-yellow-400 animate-pulse', label: 'جارٍ' },
}

function StatusPill({ status }) {
  const cfg = STATUS_CFG[status] || { cls: 'bg-gray-100 text-gray-600', dot: 'bg-gray-400', label: status }
  return (
    <span className={`badge ${cfg.cls} gap-1.5`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}

export default function SyncPage() {
  const qc = useQueryClient()

  const { data: status, isLoading: statusLoading } = useQuery({
    queryKey: ['syncStatus'],
    queryFn: () => syncApi.status().then(r => r.data),
    refetchInterval: 15_000,
  })

  const { data: logs, isLoading: logsLoading } = useQuery({
    queryKey: ['syncLogs'],
    queryFn: () => syncApi.logs().then(r => r.data),
    refetchInterval: 30_000,
  })

  const triggerMutation = useMutation({
    mutationFn: (full) => syncApi.trigger(full),
    onSuccess: () => {
      setTimeout(() => {
        qc.invalidateQueries(['syncStatus'])
        qc.invalidateQueries(['syncLogs'])
      }, 2000)
    },
  })

  const isBusy = triggerMutation.isPending || status?.status === 'running'

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      <PageHeader
        title="المزامنة مع SOFTECH"
        subtitle="تحديث تلقائي كل 5 دقائق · Sybase ASE 12.5"
        actions={
          <div className="flex gap-2">
            <button
              disabled={isBusy}
              onClick={() => triggerMutation.mutate(false)}
              className="btn-secondary text-sm disabled:opacity-50"
            >
              {isBusy ? <Spinner size="sm" /> : '↻'}
              {isBusy ? 'جارٍ...' : 'مزامنة الآن'}
            </button>
            <button
              disabled={isBusy}
              onClick={() => triggerMutation.mutate(true)}
              className="btn-primary text-sm disabled:opacity-50"
            >
              مزامنة كاملة (90 يوم)
            </button>
          </div>
        }
      />

      <div className="page-body space-y-5">

        {/* Status card */}
        {statusLoading ? (
          <SkeletonCard lines={3} />
        ) : status ? (
          <div
            className="card border-r-4"
            style={{
              borderRightColor:
                status.status === 'success' ? '#10b981' :
                status.status === 'failed'  ? '#ef4444' : '#f59e0b',
            }}
          >
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <div className={`w-3 h-3 rounded-full shrink-0 ${
                  status.status === 'success' ? 'bg-green-500' :
                  status.status === 'running' ? 'bg-yellow-400 animate-pulse' : 'bg-red-500'
                }`} />
                <div>
                  <div className="font-bold text-gray-800 text-sm">
                    {status.status === 'success' ? 'المزامنة تعمل بشكل طبيعي' :
                     status.status === 'running' ? 'جارٍ المزامنة الآن...' :
                     status.status === 'failed'  ? 'فشلت آخر مزامنة' :
                     'لم تتم مزامنة بعد'}
                  </div>
                  {status.last_at && (
                    <div className="text-xs text-gray-500 mt-0.5">
                      آخر مزامنة:{' '}
                      {format(new Date(status.last_at), 'd MMM yyyy — HH:mm', { locale: ar })}
                    </div>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-4 text-sm flex-wrap">
                {status.records > 0 && (
                  <div className="text-center">
                    <div className="font-black text-gray-800 tabnum">
                      {status.records?.toLocaleString('ar-EG')}
                    </div>
                    <div className="text-xs text-gray-400">سجل</div>
                  </div>
                )}
                {status.duration && (
                  <div className="text-center">
                    <div className="font-black text-gray-800 tabnum">{status.duration}ث</div>
                    <div className="text-xs text-gray-400">المدة</div>
                  </div>
                )}
                <StatusPill status={status.status} />
              </div>
            </div>
            {status.error && (
              <div className="mt-3 bg-red-50 border border-red-200 rounded-xl px-3 py-2 text-xs text-red-700 font-mono">
                {status.error}
              </div>
            )}
          </div>
        ) : null}

        {/* Logs */}
        <div>
          <SectionTitle icon="📋">سجل المزامنة</SectionTitle>

          {logsLoading ? (
            <div className="space-y-2">
              {[1,2,3].map(i => <SkeletonCard key={i} lines={2} />)}
            </div>
          ) : !logs?.length ? (
            <div className="card">
              <EmptyState
                icon={<span className="text-5xl">📭</span>}
                title="لا يوجد سجل بعد"
                sub="ستظهر هنا نتائج كل عملية مزامنة"
              />
            </div>
          ) : (
            <div className="space-y-2">
              {logs.map((run, i) => (
                <div key={run.id || i} className="card p-4">
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="flex items-center gap-3">
                      <StatusPill status={run.status} />
                      <div>
                        <div className="text-sm font-semibold text-gray-800">
                          {run.started_at
                            ? format(new Date(run.started_at), 'd MMM yyyy — HH:mm', { locale: ar })
                            : '—'}
                        </div>
                        {run.completed_at && (
                          <div className="text-xs text-gray-400 mt-0.5">
                            انتهت:{' '}
                            {format(new Date(run.completed_at), 'HH:mm:ss', { locale: ar })}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-4 text-sm">
                      {run.records_synced > 0 && (
                        <div className="text-center">
                          <div className="font-black text-gray-800 tabnum">
                            {run.records_synced?.toLocaleString('ar-EG')}
                          </div>
                          <div className="text-xs text-gray-400">سجل</div>
                        </div>
                      )}
                      {run.duration_seconds && (
                        <div className="text-center">
                          <div className="font-black text-gray-800 tabnum">
                            {run.duration_seconds}ث
                          </div>
                          <div className="text-xs text-gray-400">مدة</div>
                        </div>
                      )}
                    </div>
                  </div>
                  {run.error_message && (
                    <div className="mt-2 text-xs text-red-600 bg-red-50 rounded-lg px-3 py-2 font-mono">
                      {run.error_message}
                    </div>
                  )}
                  {/* Per-table log */}
                  {run.logs?.length > 0 && (
                    <div className="mt-3 border-t border-gray-100 pt-3 grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {run.logs.map((log, j) => (
                        <div key={j} className="bg-gray-50 rounded-lg px-2.5 py-1.5 text-xs">
                          <div className="text-gray-500 truncate">{log.table_name}</div>
                          <div className="font-bold text-gray-800 tabnum">
                            {log.records_processed?.toLocaleString('ar-EG')}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
