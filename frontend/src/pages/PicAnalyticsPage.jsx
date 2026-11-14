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
import { useEffect, useMemo, useRef, useState } from 'react'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { branchesApi, picAnalyticsApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import ProgressBar from '../components/ProgressBar'
import useBranchLabels from '../hooks/useBranchLabels'
import useClosedBranches from '../hooks/useClosedBranches'
import useHelpTab from '../help/useHelpTab'
import Filters from '../components/pic-analytics/Filters'
import KpiCards from '../components/pic-analytics/KpiCards'
import PicTable from '../components/pic-analytics/PicTable'
import GroupTable from '../components/pic-analytics/GroupTable'
import RetentionPanel from '../components/pic-analytics/RetentionPanel'
import AccessPanel from '../components/pic-analytics/AccessPanel'
import Explain from '../components/pic-analytics/Explain'
import ExclusionsPanel from '../components/pic-analytics/ExclusionsPanel'
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

// the running export survives a page reload (sessionStorage may be blocked: never fatal)
const JOB_KEY = 'pic-analytics-export-job'
const readJob = () => { try { return Number(sessionStorage.getItem(JOB_KEY)) || null } catch { return null } }
const saveJob = id => {
  try { if (id) sessionStorage.setItem(JOB_KEY, String(id)); else sessionStorage.removeItem(JOB_KEY) } catch { /* ignore */ }
}
const RUNNING = ['queued', 'running']

// the server names the file (it knows the effective, clamped period)
function fileNameOf(r, fallback) {
  const cd = r.headers?.['content-disposition'] || ''
  const star = cd.match(/filename\*=UTF-8''([^;]+)/i)
  const plain = cd.match(/filename="?([^";]+)"?/i)
  try { return (star ? decodeURIComponent(star[1]) : (plain ? plain[1] : '')) || fallback } catch { return (plain ? plain[1] : '') || fallback }
}

export default function PicAnalyticsPage() {
  const qc = useQueryClient()
  const bl = useBranchLabels()
  const [sp, setSp] = useSearchParams()
  const [order, setOrder] = useState('-net')
  const [picPage, setPicPage] = useState(1)
  const [overduePage, setOverduePage] = useState(1)
  const [overdueOrdering, setOverdueOrdering] = useState('')
  const [jobId, setJobId] = useState(readJob)
  const [starting, setStarting] = useState(false)
  const [exportErr, setExportErr] = useState('')
  const downloaded = useRef(null)
  const urlQ = sp.get('q') || ''
  const [qText, setQText] = useState(urlQ)            // typed text; the URL param follows after a pause

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
  const { data: baseBranches = [] } = useQuery({
    queryKey: ['branches'],
    queryFn: () => branchesApi.list().then(r => r.data.results || r.data),
    staleTime: 5 * 60_000,
  })

  const { branches, showClosed, toggle: closedToggle } = useClosedBranches(baseBranches)
  const tabs = [...SALES_TABS, ...(access?.sees_calls_tabs ? CALLS_TABS : [])]
  const tab = tabs.some(t => t.key === sp.get('tab')) ? sp.get('tab') : 'overview'
  useHelpTab(tab)

  const setParam = (k, v) => {
    // start from the live URL, not a render's `sp`: a delayed call (the search debounce) must not
    // overwrite a filter changed meanwhile (react-router's functional form also sees the stale params)
    const next = new URLSearchParams(window.location.search)
    if (v) next.set(k, v); else next.delete(k)
    setSp(next, { replace: true })
    setPicPage(1); setOverduePage(1)
  }
  const clear = () => { const next = new URLSearchParams(); if (sp.get('tab')) next.set('tab', sp.get('tab')); setSp(next, { replace: true }); setQText(''); setPicPage(1); setOverduePage(1) }

  // a locked branch manager with one branch: show that branch, the server scopes anyway
  const lockedBranch = access?.branch_manager && (access.branch_ids || []).length === 1 ? String(access.branch_ids[0]) : ''
  const shown = { ...values, branch: values.branch || lockedBranch }

  const params = Object.fromEntries(
    FILTER_KEYS.map(k => [k, values[k] || undefined]))
  const picParams = { ...params, q: urlQ || undefined }       // the search belongs to the PIC list (and its export)
  const ready = !!access?.can_view
  const useGroup = (key, fn, enabled = true) => useQuery({
    queryKey: ['pic-analytics', key, params], queryFn: fn, enabled: ready && enabled,
    staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })

  const overview = useGroup('overview', () => picAnalyticsApi.overview(params).then(r => r.data), tab === 'overview')
  const pics = useQuery({
    queryKey: ['pic-analytics', 'pics', picParams, order, picPage],
    queryFn: () => picAnalyticsApi.pics({ ...picParams, ordering: order, page: picPage, page_size: 50 }).then(r => r.data),
    enabled: ready && tab === 'pics', staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })
  const branchG = useGroup('g-branch', () => picAnalyticsApi.groups('branch', params).then(r => r.data), tab === 'branches')
  const salesG = useGroup('g-sales', () => picAnalyticsApi.groups('salesperson', params).then(r => r.data), tab === 'salespeople')
  const chanG = useGroup('g-channel', () => picAnalyticsApi.groups('channel', params).then(r => r.data), tab === 'channels')
  const catG = useGroup('g-category', () => picAnalyticsApi.groups('category', params).then(r => r.data), tab === 'channels')
  const retention = useGroup('retention', () => picAnalyticsApi.retention(params).then(r => r.data), tab === 'retention')
  const overdue = useQuery({
    queryKey: ['pic-analytics', 'overdue', params, overduePage, overdueOrdering],
    queryFn: () => picAnalyticsApi.overdue({ ...params, page: overduePage, page_size: 50, ...(overdueOrdering ? { ordering: overdueOrdering } : {}) }).then(r => r.data),
    enabled: ready && tab === 'retention', staleTime: 2 * 60_000, placeholderData: keepPreviousData,
  })
  const center = useGroup('calls-center', () => picAnalyticsApi.callCenter(params).then(r => r.data), tab === 'calls')
  const active = { overview, pics, branches: branchG, salespeople: salesG, channels: chanG, retention, calls: center }[tab]

  const branchName = pk => {
    const b = branches.find(x => x.id === pk)
    return b ? bl(b.softech_branch_id ?? b.code) : String(pk)
  }

  // debounce the search box into the URL (?q=) and back to page 1
  useEffect(() => {
    if (qText.trim() === urlQ) return undefined
    const t = setTimeout(() => setParam('q', qText.trim()), 350)
    return () => clearTimeout(t)
  }, [qText]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = () => { qc.invalidateQueries({ queryKey: ['pic-analytics'] }) }
  // Excel: the server builds the file in the background; we poll it, then download it once
  const attachJob = id => { saveJob(id); setJobId(id) }
  const dropJob = () => { saveJob(null); setJobId(null) }
  const job = useQuery({
    queryKey: ['pic-analytics-export-job', jobId],
    queryFn: () => picAnalyticsApi.exportJob(jobId).then(r => r.data),
    enabled: !!jobId, retry: (n, e) => n < 2 && ![403, 404].includes(e?.response?.status), gcTime: 0,  // retry rides out a deploy blip, not a gone job
    refetchInterval: q => (!q.state.data || RUNNING.includes(q.state.data.status) ? 1500 : false),
  })
  const jobData = job.data
  useEffect(() => {
    if (!jobId) return
    if (job.isError) {                       // gone (older than 48 h) or not ours: forget it quietly
      dropJob()
      if (job.error?.response?.status !== 404) setExportErr(errText(job.error, 'تعذّر متابعة التصدير'))
      return
    }
    if (jobData?.status === 'failed') { dropJob(); setExportErr(jobData.error || 'تعذّر إنشاء الملف — حاول مرة أخرى'); return }
    if (jobData?.status === 'done' && downloaded.current !== jobId) {
      downloaded.current = jobId
      picAnalyticsApi.exportJobFile(jobId)
        .then(r => downloadBlob(r.data, fileNameOf(r, jobData.file_name || 'pic-analytics.xlsx')))
        .catch(e => setExportErr(errText(e, 'تعذّر تنزيل الملف')))
        .finally(dropJob)
    }
  }, [jobId, jobData, job.isError]) // eslint-disable-line react-hooks/exhaustive-deps

  const exportBusy = starting || (!!jobId && (!jobData || RUNNING.includes(jobData.status) || jobData.status === 'done'))
  const doExport = async () => {
    if (exportBusy) return
    setStarting(true); setExportErr('')
    try {
      const r = await picAnalyticsApi.startExport(tab === 'pics' ? picParams : params)
      attachJob(r.data.id)
    } catch (e) {
      if (e?.response?.status === 409 && e.response.data?.id) attachJob(e.response.data.id)   // one already running
      else setExportErr(errText(e, 'تعذّر تصدير الملف'))
    } finally { setStarting(false) }
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
        <div className="flex flex-col items-end gap-1.5">
          <div className="flex gap-2 items-center">
            <button onClick={refresh} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-refresh">🔄 تحديث</button>
            {access?.can_export && (
              <button onClick={doExport} disabled={exportBusy} className="btn-secondary text-xs py-1.5" data-tour="pic-analytics-export">
                {exportBusy ? '… جارٍ تجهيز الملف' : '⬇ تصدير Excel'}
              </button>
            )}
          </div>
          {jobId && (!jobData || RUNNING.includes(jobData.status)) && (
            <ProgressBar className="w-72" pct={jobData?.progress_pct ?? null} label="تجهيز ملف Excel"
              message={jobData?.progress_msg || 'في الانتظار…'}
              since={jobData?.created_at ? Date.parse(jobData.created_at) : undefined} />
          )}
          {exportErr && (
            <p className="text-xs text-red-700" role="alert">
              {exportErr}{' '}
              <button type="button" onClick={doExport} className="underline font-medium">إعادة المحاولة</button>
            </p>
          )}
        </div>
      </div>

      <DataFreshnessBar domains={['sales', 'customers', 'calls']} compact invalidateKeys={[['pic-analytics']]} />

      <Filters values={shown} onChange={setParam} onClear={clear} branches={branches} showClosed={showClosed} closedToggle={closedToggle} access={access} options={options} />

      {CALLS_TABS.some(t => t.key === tab) ? (
        // call tabs read the PBX mirror (every 10 min), not the nightly sales facts
        <p className="text-xs text-gray-500 -mt-2" data-tour="pic-analytics-data-to">
          المكالمات محدّثة كل 10 دقائق — حتى اليوم
        </p>
      ) : period?.data_to && (
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

      {error && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">{error}</div>}
      {pending && <p className="text-xs text-gray-400">… جارٍ التحميل</p>}

      {tab === 'overview' && <KpiCards data={overview.data} management={!!access?.management} />}
      {tab === 'pics' && (
        <div className="flex items-center gap-2" data-tour="pic-analytics-search">
          <input className="input text-sm w-full max-w-md" value={qText} maxLength={100}
                 onChange={e => setQText(e.target.value)}
                 placeholder="ابحث بالاسم أو كود PIC أو رقم الهاتف" />
          {qText && <button className="btn-secondary text-xs py-1" onClick={() => setQText('')}>مسح</button>}
        </div>
      )}
      {tab === 'pics' && (
        <>
        <Explain id="pics" className="-mt-2"
                 hint="كل صف = عميل (PIC) اشترى في الفترة. المبالغ والزيارات على فروعك، أما الشريحة وأ/ب/ج و«متأخر» فمحسوبة على كل الفروع."
                 lines={['أ/ب/ج = شهور الشراء / أطول تتابع شهري / دورة الشراء (تفاصيلها في تبويب «الولاء والتكرار»).',
                         'المكالمات (وارد، صادر، فائتة، آخر مكالمة، مدة الحديث، مكالمة ← شراء) للإدارة بس، والمكالمة على رقم مشترك بتتحسب مرة واحدة.',
                         'مرّر على عنوان أي عمود تلاقي شرحه. «استبعاد» بيخرج العميل من كل الأرقام وتقدر ترجّعه من قسم المستبعدين.']} />
        <PicTable data={pics.data} order={order} onOrder={o => { setOrder(o); setPicPage(1) }}
                  page={picPage} onPage={setPicPage} branchName={branchName}
                  onExclude={access?.can_manage_exclusions
                    ? async (pic, reason) => { await picAnalyticsApi.exclude({ pic, reason }); refresh() } : undefined} />
        </>
      )}
      {tab === 'branches' && (
        <div data-tour="pic-analytics-branches-grid">
          <GroupTable data={branchG.data} firstLabel="الفرع" note="زيارة نفس اليوم في فرعين تُحسب لكل فرع"
                      explain={{ id: 'br', hint: 'كل سطر = عملاء الفرع ومبيعاته في الفترة؛ مجموع الفروع ممكن يزيد عن الإجمالي.',
                                 lines: ['العميل الجديد بيتنسب لفرع أول فاتورة له في الفترة. العميل العائد بيتحسب لكل فرع اشترى منه (مرة واحدة جوه نفس الفرع).',
                                         'الزيارة = فواتير العميل في نفس اليوم. زيارة نفس اليوم في فرعين = زيارة لكل فرع، وزيارة واحدة في الإجمالي.',
                                         'تصنيف جديد/عائد/مُعاد تنشيطه محسوب على كل الفروع، أما الصافي والسلة فعلى الفرع.'],
                                 example: 'عميل زار فرع أ وفرع ب في نفس اليوم ← زيارة في كل فرع، وزيارة واحدة في الإجمالي' }} />
        </div>
      )}
      {tab === 'salespeople' && (
        <div data-tour="pic-analytics-sales-grid">
          <GroupTable data={salesG.data} firstLabel="البائع" note="العميل الجديد يُنسب لبائع أول فاتورة له في الفترة"
                      explain={{ id: 'sp', hint: 'كل سطر = العملاء اللي خدمهم البائع ومبيعاته في الفترة.',
                                 lines: ['العميل الجديد جديد للكل، ويتنسب لبائع أول فاتورة له بس. العائد = اشترى في الفترة وليس جديد، ويتحسب عند كل بائع باع له (مرة واحدة جوه نفس البائع).',
                                         'استخدمه تعرف مين بيجيب عملاء جدد ومين بيحافظ على العائدين.'],
                                 example: 'عميل جديد أول فاتورة له مع أحمد ← يتحسب جديد لأحمد بس؛ لو اشترى بعدها من منى يتحسب عميل عند منى (مش جديد ومش عائد). عميل قديم اشترى من أحمد ومنى ← عائد عند الاتنين' }} />
        </div>
      )}
      {tab === 'channels' && (
        <div className="grid lg:grid-cols-2 gap-4">
          <div data-tour="pic-analytics-channels-grid">
            <GroupTable data={chanG.data} title="القنوات" firstLabel="القناة"
                        explain={{ id: 'ch', hint: 'نفس تقسيم القنوات في لوحة KPI، فالأرقام تطابقها.',
                                   lines: ['القناة بتتحدد من قناة الفاتورة بنفس خريطة لوحة KPI؛ غير المربوط = أخرى، والقنوات المستبعدة من KPI بتظهر سطر لوحدها.',
                                           'العميل الجديد بيتنسب لقناة أول فاتورة له.'] }} />
          </div>
          <div className="space-y-1">
            <div data-tour="pic-analytics-categories-grid">
              <GroupTable data={catG.data} title="الأصناف" firstLabel="الفئة"
                          explain={{ id: 'cat', hint: 'صافي كل فئة (دواء، مستحضرات، مكملات…) من مشتريات العملاء في الفترة.',
                                     lines: ['العميل بيظهر في كل فئة اشترى منها. السلة كاملة، فلو فلترت بفئة ما بيتعرضش الربح ولا الأصناف.',
                                             'نسبة الزيارات بأكتر من فئة = الزيارات اللي فيها فئتين أو أكتر ÷ كل الزيارات.'],
                                     example: '40 زيارة من 100 فيها دواء ومستحضرات ← 40%' }} />
            </div>
            {catG.data?.cross_category_rate != null && (
              <p className="text-xs text-gray-500 px-1">نسبة الزيارات بأكثر من فئة: {(catG.data.cross_category_rate * 100).toFixed(1)}%</p>
            )}
          </div>
        </div>
      )}
      {tab === 'retention' && (
        <RetentionPanel data={retention.data} overdue={overdue.data}
                        overduePage={overduePage} onOverduePage={setOverduePage}
                        overdueOrdering={overdueOrdering} onOverdueOrdering={o => { setOverdueOrdering(o); setOverduePage(1) }} />
      )}

      {tab === 'calls' && <CallCenterTab data={center.data} />}
      {tab === 'missed' && <MissedTab params={params} ready={ready} />}
      {tab === 'numbers' && <NumbersTab params={params} ready={ready} />}

      {access?.can_manage_exclusions && <ExclusionsPanel params={params} ready={ready} />}
      {access?.can_manage_access && <AccessPanel />}
    </div>
  )
}
