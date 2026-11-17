/**
 * RpaPage.jsx — روبوت الإدخال (SOFTECH screen robot, Stage 1: dry-run only)
 *
 * A Windows agent types into the SOFTECH screen under an approved recipe; this page uploads the
 * sheet, shows the jobs and their documents, and manages the agent devices. Tabs:
 *   jobs الأوامر · upload رفع ملف · devices أجهزتي · recipes الوصفات (admin only)
 * The page makes no decisions: every button calls the API and the server enforces the module
 * grant, four-eyes approval and branch scope.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { rpaApi } from '../api/client'
import useAuthStore from '../store/authStore'
import useHelpTab from '../help/useHelpTab'
import JobsTab from './rpa/JobsTab'
import UploadTab from './rpa/UploadTab'
import DevicesTab from './rpa/DevicesTab'
import RecipesTab from './rpa/RecipesTab'
import { DRY_RUN_TEXT, SCREEN_LABEL } from './rpa/shared.jsx'

const TABS = [
  { key: 'jobs', label: 'الأوامر' },
  { key: 'upload', label: 'رفع ملف' },
  { key: 'devices', label: 'أجهزتي' },
  { key: 'recipes', label: 'الوصفات', adminOnly: true },
]

function StatusStrip() {
  const q = useQuery({ queryKey: ['rpa', 'status'], queryFn: () => rpaApi.status().then(r => r.data), refetchInterval: 30000 })
  const s = q.data
  const online = s?.my_devices_online || []
  const screens = (s?.screens || []).filter(x => x.enabled !== false)
  return (
    <div data-tour="rpa-main-status" className="card p-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
      {q.isLoading && <span className="text-muted">جارٍ التحميل…</span>}
      {q.isError && <span className="text-red-600">تعذّر قراءة حالة الروبوت.</span>}
      {s && (s.switch_on
        ? <span className="text-green-700 dark:text-green-300 font-semibold">الروبوت شغّال</span>
        : <span className="text-red-700 dark:text-red-300 font-semibold">الروبوت متوقف من الإعدادات</span>)}
      {s && <span className="text-xs rounded px-1.5 py-0.5 bg-brand-600/10 text-brand-700 dark:text-brand-300">{DRY_RUN_TEXT}</span>}
      {s && (
        <span className="text-muted">
          {online.length ? `أجهزتي المتصلة: ${online.length}` : 'لا يوجد جهاز متصل لك الآن'}
        </span>
      )}
      {screens.length > 0 && (
        <span className="text-muted">
          الشاشات: {screens.map(x => x.title_ar || SCREEN_LABEL[x.key] || x.key).join('، ')}
        </span>
      )}
    </div>
  )
}

export default function RpaPage() {
  const isAdmin = useAuthStore(s => s.user?.role) === 'admin'
  const tabs = TABS.filter(t => !t.adminOnly || isAdmin)
  const [tab, setTab] = useState('jobs')
  useHelpTab(tab)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">🤖 روبوت الإدخال</h1>
        <p className="text-sm text-muted">
          يكتب الروبوت في شاشة SOFTECH نيابةً عنك، وكل الأوامر الآن تجريبية بدون حفظ. الاعتماد من شخص غير الرافع.
        </p>
      </div>

      <StatusStrip />

      <div data-tour="rpa-main-tabs" className="flex flex-wrap gap-1 border-b border-line">
        {tabs.map(t => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)}
                  className={`px-3 py-2 text-sm -mb-px border-b-2 ${tab === t.key ? 'border-brand-600 text-brand-600 font-semibold' : 'border-transparent text-muted'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'jobs' && <JobsTab />}
      {tab === 'upload' && <UploadTab onUploaded={() => setTab('jobs')} />}
      {tab === 'devices' && <DevicesTab />}
      {tab === 'recipes' && isAdmin && <RecipesTab />}
    </div>
  )
}
