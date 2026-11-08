/**
 * IssuesTab — what needs a person's decision, grouped by what it is:
 *   name conflicts · unknown fingerprint IDs (ONE row per ID) · held employees · bad dates · machine clocks.
 * Decisions (add as employee, ignore with a reason, confirm a conflict, release a hold) happen inline,
 * for the Manage level only; the server checks the level again on every call.
 */
import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { hrAttendanceApi } from '../../api/client'
import SortTh from '../../components/SortTh'
import useSortableRows from '../../hooks/useSortableRows'
import { BTN, Empty, Notice, ReasonRow, TH, errText } from './shared'

const KEYS = ['user_code', 'count', 'last_punch']
const DEFAULT_SORT = { key: 'count', dir: 'desc', type: 'number' }

function Section({ title, count, tour, children }) {
  if (!count) return null
  return (
    <section className="mb-5" data-tour={tour}>
      <h2 className="text-sm font-bold text-gray-800 mb-2">{title} <span className="text-gray-400 font-normal">({count})</span></h2>
      {children}
    </section>
  )
}

function ConflictRow({ c, canManage, onDone }) {
  const [asking, setAsking] = useState(false)
  const m = useMutation({
    mutationFn: reason => hrAttendanceApi.confirmConflict(c.user_code, { employee: c.employee, reason }),
    onSuccess: () => { setAsking(false); onDone() },
  })
  return (
    <li className="px-3 py-2 border-b border-gray-100 last:border-0">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="tabular-nums font-bold">{c.user_code}</span>
        <span className="text-gray-700">{c.employee_name || 'ليس على قائمة الموظفين'}</span>
        <span className="text-xs text-gray-500">
          {c.by_machine.map(b => `${b.machine}: ${b.name}`).join(' · ')}
        </span>
        {canManage && c.employee && !asking && (
          <button type="button" onClick={() => setAsking(true)}
            className={`${BTN} ms-auto bg-white border border-gray-200 hover:bg-gray-50`}>هذا هو الموظف…</button>
        )}
      </div>
      {asking && (
        <div className="mt-2">
          <ReasonRow placeholder={`لماذا الأسماء المختلفة هي ${c.employee_name}؟ (مطلوب)`} confirmLabel="تأكيد"
            busy={m.isPending} error={m.isError ? errText(m.error) : ''}
            onConfirm={r => m.mutate(r)} onCancel={() => setAsking(false)} />
        </div>
      )}
    </li>
  )
}

function UnknownRow({ u, canManage, onDone }) {
  const [mode, setMode] = useState(null)               // null | 'add' | 'ignore'
  const [name, setName] = useState(u.roster_names?.[0] || '')
  const create = useMutation({
    mutationFn: () => hrAttendanceApi.createEmployee(u.user_code, { name_ar: name.trim() }),
    onSuccess: () => { setMode(null); onDone() },
  })
  const ignore = useMutation({
    mutationFn: reason => hrAttendanceApi.ignoreUnknown(u.user_code, reason),
    onSuccess: () => { setMode(null); onDone() },
  })
  return (
    <>
      <tr className="border-b border-gray-100">
        <td className="px-3 py-2 tabular-nums font-bold">{u.user_code}</td>
        <td className="px-3 py-2 tabular-nums">{u.count}</td>
        <td className="px-3 py-2 tabular-nums text-gray-600">{u.last_punch ? u.last_punch.slice(0, 10) : '—'}</td>
        <td className="px-3 py-2 text-gray-600">{u.machines.join('، ') || '—'}</td>
        <td className="px-3 py-2 text-gray-600">{u.roster_names.join('، ') || '—'}</td>
        <td className="px-3 py-2 whitespace-nowrap">
          {canManage && !mode && (
            <span className="flex gap-1">
              {u.slot_only
                ? <span className="text-xs text-gray-400">رقم مكان على الماكينة فقط</span>
                : <button type="button" onClick={() => setMode('add')}
                    className={`${BTN} bg-primary text-white`}>إضافة كموظف</button>}
              <button type="button" onClick={() => setMode('ignore')}
                className={`${BTN} bg-white border border-gray-200 hover:bg-gray-50`}>تجاهل…</button>
            </span>
          )}
        </td>
      </tr>
      {mode === 'add' && (
        <tr className="bg-gray-50/70 border-b border-gray-100">
          <td colSpan={6} className="px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <input value={name} onChange={e => setName(e.target.value)} placeholder="اسم الموظف (مطلوب)" maxLength={150}
                className="flex-1 min-w-[12rem] border border-gray-200 rounded-md px-2 py-1 bg-white" />
              <span className="text-gray-500">يُضاف بدون راتب (غير مُدرج في كشف الرواتب)</span>
              <button type="button" disabled={create.isPending || !name.trim()} onClick={() => create.mutate()}
                className={`${BTN} bg-primary text-white`}>إضافة</button>
              <button type="button" onClick={() => setMode(null)} className="px-2 py-1 text-gray-500 hover:bg-gray-100 rounded-md">إلغاء</button>
              <Notice>{create.isError ? errText(create.error) : ''}</Notice>
            </div>
          </td>
        </tr>
      )}
      {mode === 'ignore' && (
        <tr className="bg-gray-50/70 border-b border-gray-100">
          <td colSpan={6} className="px-3 py-2">
            <ReasonRow placeholder="سبب التجاهل (مطلوب) — مثال: زائر" confirmLabel="تجاهل"
              busy={ignore.isPending} error={ignore.isError ? errText(ignore.error) : ''}
              onConfirm={r => ignore.mutate(r)} onCancel={() => setMode(null)} />
          </td>
        </tr>
      )}
    </>
  )
}

function IgnoredRow({ g, canManage, onDone }) {
  const m = useMutation({
    mutationFn: () => hrAttendanceApi.unignoreUnknown(g.user_code),
    onSuccess: onDone,
  })
  return (
    <li className="px-3 py-2 border-b border-gray-100 last:border-0 flex flex-wrap items-center gap-2 text-sm">
      <span className="tabular-nums font-bold">{g.user_code}</span>
      <span className="text-xs text-gray-500">{g.reason}</span>
      <span className="text-xs text-gray-400">{g.decided_at ? g.decided_at.slice(0, 10) : ''}</span>
      {canManage && (
        <button type="button" disabled={m.isPending} onClick={() => m.mutate()}
          className={`${BTN} ms-auto bg-white border border-gray-200 hover:bg-gray-50`}>إلغاء التجاهل</button>
      )}
      <Notice>{m.isError ? errText(m.error) : ''}</Notice>
    </li>
  )
}

function HeldRow({ h, canManage, onDone }) {
  const m = useMutation({
    mutationFn: () => hrAttendanceApi.hold(h.employee, { hold: false }),
    onSuccess: onDone,
  })
  return (
    <li className="px-3 py-2 border-b border-gray-100 last:border-0 flex flex-wrap items-center gap-2 text-sm">
      <span className="tabular-nums font-bold">{h.user_code}</span>
      <span>{h.name}</span>
      <span className="text-xs text-gray-500">{h.reason}</span>
      <span className="text-xs text-gray-500">{h.count} بصمة بانتظار الإفراج</span>
      {canManage && (
        <button type="button" disabled={m.isPending} onClick={() => m.mutate()}
          className={`${BTN} ms-auto bg-white border border-gray-200 hover:bg-gray-50`}>إفراج عن البصمات</button>
      )}
      <Notice>{m.isError ? errText(m.error) : ''}</Notice>
    </li>
  )
}

export default function IssuesTab({ access }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-attendance', 'issues'],
    queryFn: () => hrAttendanceApi.issues().then(r => r.data),
  })
  const done = () => qc.invalidateQueries({ queryKey: ['hr-attendance'] })
  const rows = data?.rows
  const by = kind => (rows || []).filter(r => r.kind === kind)
  const conflicts = by('conflict'), held = by('held'), bad = by('bad_date'), drift = by('drift')
  const outside = by('outside_dates')
  const ignored = data?.ignored || []
  const unknown = useMemo(() => (rows || []).filter(r => r.kind === 'unknown_id'), [rows])
  const { sorted, headerProps } = useSortableRows(unknown, {
    defaultSort: DEFAULT_SORT, persistKey: 'hr-attendance-unknown', keys: KEYS })

  if (isLoading) return <Empty>جاري التحميل…</Empty>
  if (error) return <div className="py-10 text-center text-sm text-red-600">{errText(error)}</div>
  if (!rows.length && !ignored.length) return <Empty>✅ لا توجد بنود تحتاج قراراً</Empty>

  return (
    <div>
      <Section title="تعارض أسماء على نفس الرقم" count={conflicts.length} tour="hr-attendance-issues-conflicts">
        <ul className="bg-white rounded-xl border border-gray-200">
          {conflicts.map(c => <ConflictRow key={c.user_code} c={c} canManage={access.can_manage} onDone={done} />)}
        </ul>
      </Section>

      <Section title="أرقام بصمة غير معروفة" count={unknown.length} tour="hr-attendance-issues-unknown">
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200 text-gray-600 text-xs">
                <SortTh className={TH} {...headerProps('user_code', 'text')}>الرقم</SortTh>
                <SortTh className={TH} {...headerProps('count', 'number')}>عدد البصمات</SortTh>
                <SortTh className={TH} {...headerProps('last_punch', 'date')}>آخر بصمة</SortTh>
                <th className={TH}>الماكينات</th>
                <th className={TH}>الاسم على الماكينة</th>
                <th className={TH}></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(u => <UnknownRow key={u.user_code} u={u} canManage={access.can_manage} onDone={done} />)}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="بصمات معلّقة بقرار" count={held.length} tour="hr-attendance-issues-held">
        <ul className="bg-white rounded-xl border border-gray-200">
          {held.map(h => <HeldRow key={h.employee} h={h} canManage={access.can_manage} onDone={done} />)}
        </ul>
      </Section>

      <Section title="بصمات خارج فترة عمل الموظف (محفوظة وخارج الحساب)" count={outside.length} tour="hr-attendance-issues-outside">
        <ul className="bg-white rounded-xl border border-gray-200">
          {outside.map(o => (
            <li key={o.employee} className="px-3 py-2 border-b border-gray-100 last:border-0 text-sm">
              <span className="tabular-nums font-bold">{o.user_code}</span> {o.name} · {o.count} بصمة من {o.oldest?.slice(0, 10) || '—'} إلى {o.newest?.slice(0, 10) || '—'}
              <span className="text-xs text-gray-500"> · فترة العمل المسجلة: {o.start_date || '—'} إلى {o.end_date || '—'}.
                صحّح تاريخ البداية أو النهاية في تبويب «الموظفون» إن كان خطأ.</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="بصمات بتاريخ غير ممكن (محفوظة وخارج الحساب)" count={bad.length} tour="hr-attendance-issues-dates">
        <ul className="bg-white rounded-xl border border-gray-200">
          {bad.map(b => (
            <li key={b.machine} className="px-3 py-2 border-b border-gray-100 last:border-0 text-sm">
              {b.machine} · {b.count} بصمة · من {b.oldest?.slice(0, 10) || '—'} إلى {b.newest?.slice(0, 10) || '—'}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="ساعة ماكينة غير مضبوطة" count={drift.length} tour="hr-attendance-issues-drift">
        <ul className="bg-white rounded-xl border border-gray-200">
          {drift.map(d => (
            <li key={d.device} className="px-3 py-2 border-b border-gray-100 last:border-0 text-sm">
              {d.machine} · الفرق عن الوقت الصحيح {Math.max(1, Math.round(Math.abs(d.seconds) / 60))} دقيقة
            </li>
          ))}
        </ul>
      </Section>

      <Section title="أرقام بصمة مستبعدة بقرار (بصماتها خارج الحساب)" count={ignored.length} tour="hr-attendance-issues-ignored">
        <ul className="bg-white rounded-xl border border-gray-200">
          {ignored.map(g => <IgnoredRow key={g.user_code} g={g} canManage={access.can_manage} onDone={done} />)}
        </ul>
      </Section>
    </div>
  )
}
