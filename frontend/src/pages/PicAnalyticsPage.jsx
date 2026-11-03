/**
 * PicAnalyticsPage — تحليلات العملاء (PIC). Route /customers/pic-analytics (doc 33).
 *
 * A PIC-centric dashboard over the sales facts. The server owns every rule (who sees which
 * branch, cost/GP, calls, thresholds, definitions); this page only shows the answer. The
 * filter bar and tab live in the URL (?tab=&from=&to=&branch=…) so a view can be shared.
 *
 * Tabs here: overview · pics · branches · salespeople · channels · retention.
 * Call tabs (calls · missed · numbers): management only — shown when access.sees_calls_tabs, and the
 * server refuses them (403) to anyone else. The tab key equals the help tab key.
 */
import { useMemo, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { branchesApi, picAnalyticsApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import useBranchLabels from '../hooks/useBranchLabels'
import useHelpTab from '../help/useHelpTab'
import Filters from '../components/pic-analytics/Filters'
import KpiCards from '../components/pic-analytics/KpiCards'
import PicTable from '../components/pic-analytics/PicTable'
import GroupTable from '../components/pic-analytics/GroupTable'
import RetentionPanel from '../components/pic-analytics/RetentionPanel'
import AccessPanel from '../components/pic-analytics/AccessPanel'
import CallCenterTab from '../components/pic-analytics/CallCenterTab'
import MissedTab from '../components/pic-analytics/MissedTab'
import NumbersTab from '../components/pic-analytics/NumbersTab'
import { downloadBlob, errText } from './supply/supplyUi'

const SALES_TABS = [
  { key: 'overview',    label: '📊 نظرة عامة' },
  { key: 'pics',        label: '👥 العملاء' },
  { key: 'branches',    label: '🏬 الفروع' },
  { key: 'salespeople', label: '🧑‍💼 البائعون' },
  { key: 'channels',    label: '🧭 القنوات والأصناف' },
  { key: 'retention',   label: '🔁 الولاء والتكرار' },
]
const CALLS_TABS = [
  { key: 'calls',   label: '☎️ مركز الاتصال' },
  { key: 'missed',  label: '📵 المكالمات الفائتة' },
  { key: 'numbers', label: '🆕 أرقام جديدة' },
]
const FILTER_KEYS = ['from', 'to', 'branch', 'salesperson', 'channel', 'category', 'segment', 'customer_type', 'frequency', 'agent']

const pad = n => String(n).padStart(2, '0')
const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
function defaultRange() {                     // first day of the month → yesterday
  const y = new Date(); y.setDate(y.getDate() - 1)
  return { from: iso(new Date(y.getFullYear(), y.getMonth(), 1)), to: iso(y) }
}

export default function PicAnalyticsPage() {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [sp, setSp] = useSearchParams()
  const [order, setOrder] = useState('-net')
  const [picPage, setPicPage] = useState(1)
  const [overduePage, setOverduePage] = useState(1)
  const [exporting, setExporting] = useState(false)
  const [msg, setMsg] = useState('')

  const dflt = useMemo(defaultRange, [])
  const values = {
    from: sp.get('from') || dflt.from, to: sp.get('to') || dflt.to,
    ...Object.fromEntries(FILTER_KEYS.slice(2).map(k => [k, sp.get(k) || ''])),
  }

  const { data: access, error: accessError } = useQuery({
    queryKey: ['pic-analytics', 'access'],
    queryFn: () => picAnalyticsApi.access().then(r => r.data),
    staleTime: 5 * 60_000,
  })
  const { data: options } = useQuery({
    queryKey: ['pic-analytics', 'options', values.from, values.to],
    queryFn: () => picAnalyticsApi.options({ from: values.from, to: values.to }).then(r => r.data),
    enabled: !!access?.can_view, staleTime: 5 * 60_000, placeholderData: keepPreviousData,
  })
  const { data: branches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
    staleTime: 5 * 60_000,
  })

  const tabs = [...SALES_TABS, ...(access?.sees_calls_tabs ? CALLS_TABS : [])]
  const tab = tabs.some(t => t.key === sp.get('tab')) ? sp.get('tab') : 'overview'
  useHelpTab(tab)

  const setParam = (k, v) => {
    const next = new URLSearchParams(sp)
    if (v) next.set(k, v); else next.delete(k)
    setSp(next, { replace: true })
    setPicPage(1); setOverduePage(1)
  }
  const clear = () => { const next = new URLSearchParams(); if (sp.get('tab')) next.set('tab', sp.get('tab')); setSp(next, { replace: true }); setPicPage(1); setOverduePage(1) }

  // a locked branch manager with one branch: show that branch, the server scopes anyway
  const lockedBranch = access?.branch_manager && (access.branch_ids || []).length === 1 ? String(access.branch_ids[0]) : ''
  const shown = { ...values, branch: values.branch || lockedBranch }

  const params = Object.fromEntries(
    FILTER_KEYS.map(k => [k, values[k] || undefined]))
  const ready = !!access?.can_view
  const useGroup = (key, fn, enabled = true) => useQuery({
    queryKey: ['pic-analytics', key, params], queryFn: fn, enabled: ready && enabled,
    staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })

  const overview = useGroup('overview', () => picAnalyticsApi.overview(params).then(r => r.data), tab === 'overview')
  const pics = useQuery({
    queryKey: ['pic-analytics', 'pics', params, order, picPage],
    queryFn: () => picAnalyticsApi.pics({ ...params, order, page: picPage, page_size: 50 }).then(r => r.data),
    enabled: ready && tab === 'pics', staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })
  const branchG = useGroup('g-branch', () => picAnalyticsApi.groups('branch', params).then(r => r.data), tab === 'branches')
  const salesG = useGroup('g-sales', () => picAnalyticsApi.groups('salesperson', params).then(r => r.data), tab === 'salespeople')
  const chanG = useGroup('g-channel', () => picAnalyticsApi.groups('channel', params).then(r => r.data), tab === 'channels')
  const catG = useGroup('g-category', () => picAnalyticsApi.groups('category', params).then(r => r.data), tab === 'channels')
  const retention = useGroup('retention', () => picAnalyticsApi.retention(params).then(r => r.data), tab === 'retention')
  const overdue = useQuery({
    queryKey: ['pic-analytics', 'overdue', params, overduePage],
    queryFn: () => picAnalyticsApi.overdue({ ...params, page: overduePage, page_size: 50 }).then(r => r.data),
    enabled: ready && tab === 'retention', staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })
  const center = useGroup('calls-center', () => picAnalyticsApi.callCenter(params).then(r => r.data), tab === 'calls')
  const active = { overview, pics, branches: branchG, salespeople: salesG, channels: chanG, retention, calls: center }[tab]

  const branchName = pk => {
    const b = branches.find(x => x.id === pk)
    return b ? bl(b.softech_branch_id ?? b.code) : String(pk)
  }

  const refresh = () => { qc.invalidateQueries({ queryKey: ['pic-analytics'] }) }
  const doExport = async () => {
    setExporting(true); setMsg('')
    try {
      const r = await picAnalyticsApi.exportXlsx(params)
      downloadBlob(r.data, `pic-analytics_${values.from}_${values.to}.xlsx`)
    } catch (e) {
      setMsg(errText(e, 'تعذّر تصدير الملف'))
    } finally { setExporting(false) }
  }

  const error = active?.isError ? errText(active.error, 'تعذّر تحميل البيانات') : ''
  const pending = ready && active?.isLoading

  const noAccess = (access && !access.can_view) || accessError?.response?.status === 403
  if (noAccess) {
    return (
      <div className="p-6 max-w-7xl mx-auto" dir="rtl">
        <p className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-6 text-center text-sm text-gray-600">
          ليس لديك صلاحية على هذه الشاشة
        </p>
      </div>
    )
  }
  const period = active?.data?.period || options?.period

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-4" dir="rtl">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-black text-gray-800">تحليلات العملاء</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            العميل = كود الـPIC · الزيارة = يوم شراء واحد
            {access?.branch_manager && ' · فروعك فقط'}
          </p>
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={refresh} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-refresh">🔄 تحديث</button>
          {access?.can_export && (
            <button onClick={doExport} disabled={exporting} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-export">
              {exporting ? '… جارٍ التصدير' : '⬇ تصدير Excel'}
            </button>
          )}
        </div>
      </div>

      <DataFreshnessBar domains={['sales', 'customers', 'calls']} compact invalidateKeys={[['pic-analytics']]} />

      <Filters values={shown} onChange={setParam} onClear={clear} branches={branches} access={access} options={options} />

      {period?.data_to && (
        <p className="text-xs text-gray-500 -mt-2" data-tour="pic-analytics-data-to">
          البيانات حتى {String(period.data_to).slice(0, 10)}
          {period.clamped && ' · تم ضبط الفترة على البيانات المتاحة'}
        </p>
      )}

      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto" data-tour="pic-analytics-tabs">
        {tabs.map(t => (
          <button key={t.key} onClick={() => setParam('tab', t.key === 'overview' ? '' : t.key)}
                  className={`px-3 py-2 text-sm whitespace-nowrap border-b-2 ${tab === t.key ? 'border-brand-600 text-brand-700 font-bold' : 'border-transparent text-gray-500 hover:text-gray-800'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {msg && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{msg}</div>}
      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
      {pending && <p className="text-xs text-gray-400">… جارٍ التحميل</p>}

      {tab === 'overview' && <KpiCards data={overview.data} management={!!access?.management} />}
      {tab === 'pics' && (
        <PicTable data={pics.data} order={order} onOrder={o => { setOrder(o); setPicPage(1) }}
                  page={picPage} onPage={setPicPage} branchName={branchName} />
      )}
      {tab === 'branches' && (
        <div data-tour="pic-analytics-branches-grid">
          <GroupTable data={branchG.data} firstLabel="الفرع" note="زيارة نفس اليوم في فرعين تُحسب لكل فرع" />
        </div>
      )}
      {tab === 'salespeople' && (
        <div data-tour="pic-analytics-sales-grid">
          <GroupTable data={salesG.data} firstLabel="البائع" note="العميل الجديد يُنسب لبائع أول فاتورة له في الفترة" />
        </div>
      )}
      {tab === 'channels' && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div data-tour="pic-analytics-channels-grid">
            <GroupTable data={chanG.data} title="القنوات" firstLabel="القناة" />
          </div>
          <div className="space-y-1">
            <div data-tour="pic-analytics-categories-grid">
              <GroupTable data={catG.data} title="الأصناف" firstLabel="الفئة" />
            </div>
            {catG.data?.cross_category_rate != null && (
              <p className="text-xs text-gray-500 px-1">نسبة الزيارات بأكثر من فئة: {(catG.data.cross_category_rate * 100).toFixed(1)}%</p>
            )}
          </div>
        </div>
      )}
      {tab === 'retention' && (
        <RetentionPanel data={retention.data} overdue={overdue.data}
                        overduePage={overduePage} onOverduePage={setOverduePage} />
      )}

      {tab === 'calls' && <CallCenterTab data={center.data} />}
      {tab === 'missed' && <MissedTab params={params} ready={ready} />}
      {tab === 'numbers' && <NumbersTab params={params} ready={ready} />}

      {access?.can_manage_access && <AccessPanel />}
    </div>
  )
}
