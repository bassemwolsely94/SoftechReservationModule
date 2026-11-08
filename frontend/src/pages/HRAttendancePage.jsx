/**
 * HRAttendancePage — الحضور والبصمة (HR attendance, stage 1). Route /hr/attendance.
 *
 * Fingerprint machines → punches → days, shown for the HR head. Display only: no pay, no
 * deductions, and the page never says «absent» — a day without punches is just «بدون بصمات».
 * The server decides who sees and changes what (view / export / manage / admin, checked on every
 * route); the controls this page hides are a convenience, not the authorization.
 *
 * Tabs: month · days · issues · employees · devices.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { hrAttendanceApi } from '../api/client'
import DataFreshnessBar from '../components/DataFreshnessBar'
import useHelpTab from '../help/useHelpTab'
import DaysTab from './hr-attendance/DaysTab'
import AccessTab from './hr-attendance/AccessTab'
import DevicesTab from './hr-attendance/DevicesTab'
import EmployeesTab from './hr-attendance/EmployeesTab'
import IssuesTab from './hr-attendance/IssuesTab'
import MonthTab from './hr-attendance/MonthTab'
import { thisMonth } from './hr-attendance/shared'

const TABS = [
  { key: 'month',     label: '📅 الشهر' },
  { key: 'days',      label: '🗓️ الأيام' },
  { key: 'issues',    label: '⚠️ مشاكل' },
  { key: 'employees', label: '👥 الموظفون' },
  { key: 'devices',   label: '🖐️ الماكينات' },
  { key: 'access',    label: '🔑 الصلاحيات', admin: true },
]

export default function HRAttendancePage() {
  const [tab, setTab] = useState('month')
  useHelpTab(tab)
  const [month, setMonth] = useState(thisMonth)
  const [employeeId, setEmployeeId] = useState(null)
  const me = useQuery({ queryKey: ['hr-attendance', 'me'], retry: false,
                        queryFn: () => hrAttendanceApi.me().then(r => r.data) })
  const access = me.data
  const roster = useQuery({
    queryKey: ['hr-attendance', 'roster'], enabled: !!access?.can_view,
    queryFn: () => hrAttendanceApi.employees({ status: 'active' }).then(r => r.data.rows),
  })
  const issueCount = useQuery({
    queryKey: ['hr-attendance', 'issues'], enabled: !!access?.can_view,
    queryFn: () => hrAttendanceApi.issues().then(r => r.data),
  }).data?.rows?.length

  if (me.isLoading) return <div className="p-6 text-gray-400" dir="rtl">جاري التحميل…</div>
  if (me.isError && me.error?.response?.status !== 403) {
    return (
      <div className="p-6 max-w-3xl mx-auto text-center" dir="rtl">
        <p className="text-red-600 mb-3">تعذّر تحميل الشاشة — تحقق من الاتصال وحاول مرة أخرى.</p>
        <button type="button" onClick={() => me.refetch()}
          className="px-3 py-1.5 rounded-md bg-primary text-white text-sm font-bold">إعادة المحاولة</button>
      </div>
    )
  }
  if (!access?.can_view) {
    return (
      <div className="p-6 max-w-3xl mx-auto text-center" dir="rtl">
        <div className="text-4xl mb-2">🔒</div>
        <p className="text-gray-600">هذه الشاشة للإدارة والأشخاص المسموح لهم بالحضور والبصمة فقط.</p>
      </div>
    )
  }

  const openDays = id => { setEmployeeId(id); setTab('days') }

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto" dir="rtl">
      <div className="mb-3">
        <h1 className="text-2xl font-bold text-gray-900">الحضور والبصمة</h1>
        <p className="text-sm text-gray-500 mt-1">
          بصمات ماكينات الحضور مجمّعة في أيام. للعرض فقط — لا رواتب ولا خصومات، واليوم بلا بصمات يظهر «بدون بصمات» دون حكم.</p>
      </div>
      {/* the refresh button asks every agent to collect now: Manage only (the server checks too) */}
      <DataFreshnessBar domains={['attendance']} canEdit={!!access.can_manage}
        onRefresh={() => hrAttendanceApi.collectNow()} />
      <div className="flex flex-wrap gap-1 bg-gray-100 rounded-lg p-1 w-fit mb-4" data-tour="hr-attendance-tabs">
        {TABS.filter(t => !t.admin || access.can_admin).map(t => (
          <button key={t.key} type="button" onClick={() => setTab(t.key)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition ${tab === t.key ? 'bg-white shadow text-gray-900' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label}
            {t.key === 'issues' && issueCount > 0 && <span className="ms-1 text-xs text-amber-700 font-bold">{issueCount}</span>}
          </button>
        ))}
      </div>
      {tab === 'month' && <MonthTab month={month} setMonth={setMonth} access={access} onOpen={openDays} />}
      {tab === 'days' && <DaysTab employeeId={employeeId} month={month} setMonth={setMonth}
        employees={roster.data || []} onPick={setEmployeeId} />}
      {tab === 'issues' && <IssuesTab access={access} />}
      {tab === 'employees' && <EmployeesTab access={access} onOpenDays={openDays} />}
      {tab === 'devices' && <DevicesTab access={access} />}
      {tab === 'access' && access.can_admin && <AccessTab />}
    </div>
  )
}
