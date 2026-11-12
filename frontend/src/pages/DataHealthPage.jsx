/**
 * DataHealthPage — صحة البيانات (data lifecycle Stage 5, doc 36). Route /data-health.
 *
 * What is growing, what the retention rules did, which files are held, and which data problems are open.
 * The server decides everything: who sees which tab (admin all; supervisor + quality Growth and Problems),
 * every rule refusal, and which held file may show a thumbnail. This page only shows and sends choices.
 * The screen reads stored snapshots; «تحديث الآن» starts one background measurement and polls until done.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { dataHealthApi } from '../api/client'
import RefreshButton from '../components/RefreshButton'
import useHelpTab from '../help/useHelpTab'
import useAuthStore from '../store/authStore'
import GrowthTab from './dataHealth/GrowthTab'
import RulesTab from './dataHealth/RulesTab'
import HeldFilesTab from './dataHealth/HeldFilesTab'
import ProblemsTab from './dataHealth/ProblemsTab'
import { errText, fmtDate } from './dataHealth/format'

const TABS = [
  { key: 'growth',   label: '📈 النمو' },
  { key: 'rules',    label: '📜 القواعد', admin: true },
  { key: 'held',     label: '🗄️ الملفات المحجوزة', admin: true },
  { key: 'problems', label: '🧩 المشكلات' },
]
const POLL_MS = 4000

export default function DataHealthPage() {
  const isAdmin = useAuthStore(s => s.user?.role) === 'admin'
  const tabs = TABS.filter(t => !t.admin || isAdmin)
  const [tab, setTab] = useState('growth')
  useHelpTab(tab)
  const qc = useQueryClient()

  const growth = useQuery({
    queryKey: ['data-health', 'growth'],
    queryFn: () => dataHealthApi.growth().then(r => r.data),
    refetchInterval: q => (q.state.data?.refreshing ? POLL_MS : false),
  })
  const refreshing = !!growth.data?.refreshing

  // when a measurement finishes, reload the other tabs once so Problems shows the new counts
  const wasRefreshing = useRef(false)
  useEffect(() => {
    if (wasRefreshing.current && !refreshing) qc.invalidateQueries({ queryKey: ['data-health', 'problems'] })
    wasRefreshing.current = refreshing
  }, [refreshing, qc])

  const refresh = useMutation({
    mutationFn: () => dataHealthApi.refresh(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['data-health'] }),
  })

  return (
    <div className="p-4 md:p-6 space-y-4" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-gray-900">🩺 صحة البيانات</h1>
          <p className="text-xs text-gray-500 mt-1">
            آخر قياس: {fmtDate(growth.data?.as_of, true)}
            {refreshing && <span className="ms-2 text-brand-700">· جارٍ القياس…</span>}
          </p>
        </div>
        <div className="flex items-center gap-2" data-tour="data-health-main-refresh">
          <RefreshButton loading={refreshing || refresh.isPending} onClick={() => refresh.mutate()} size="sm">
            🔄 تحديث الآن
          </RefreshButton>
          {refresh.isError && <span className="text-xs text-red-600">{errText(refresh.error)}</span>}
        </div>
      </div>

      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit" data-tour="data-health-main-tabs" role="tablist">
        {tabs.map(t => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
                  className={`px-3 py-1.5 rounded-md text-sm ${tab === t.key ? 'bg-white shadow text-brand-700 font-semibold' : 'text-gray-600 hover:text-gray-900'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'growth' && <GrowthTab query={growth} />}
      {tab === 'rules' && isAdmin && <RulesTab />}
      {tab === 'held' && isAdmin && <HeldFilesTab />}
      {tab === 'problems' && <ProblemsTab refreshing={refreshing} />}
    </div>
  )
}
