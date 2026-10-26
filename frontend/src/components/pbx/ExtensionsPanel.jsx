import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { pbxApi } from '../../api/client'

const TYPES = [
  ['agent', 'مركز اتصال'], ['branch', 'فرع'], ['hq', 'إداري'], ['gateway', 'بوابة خارجية'], ['other', 'أخرى'],
]

function MapEditor({ row, onDone }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [type, setType] = useState(row.mapping?.type || 'agent')
  const { data: staff = [] } = useQuery({
    queryKey: ['pbx-staff-choices', q],
    queryFn: () => pbxApi.staffChoices(q).then(r => r.data),
  })
  const save = useMutation({
    mutationFn: (staff_id) => pbxApi.mapExtension({ extension: row.extension, staff_id, extension_type: type }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['pbx-extensions'] }); onDone() },
  })

  return (
    <div className="mt-2 p-2 rounded-lg bg-gray-50 dark:bg-gray-800 space-y-2 text-xs">
      <div className="flex gap-2 items-center flex-wrap">
        <select value={type} onChange={e => setType(e.target.value)} className="input text-xs py-1">
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="ابحث باسم الموظف…"
          className="input text-xs py-1 flex-1 min-w-[10rem]" autoFocus />
        {row.mapping?.staff_id && (
          <button onClick={() => save.mutate(null)} className="btn-secondary text-xs px-2 py-1 text-red-600">فك الربط</button>
        )}
        <button onClick={onDone} className="btn-secondary text-xs px-2 py-1">إلغاء</button>
      </div>
      <div className="max-h-48 overflow-auto divide-y divide-gray-100 dark:divide-gray-700">
        {staff.map(s => (
          <button key={s.id} onClick={() => save.mutate(s.id)} disabled={save.isPending}
            className="w-full text-right px-2 py-1.5 hover:bg-white dark:hover:bg-gray-700 flex justify-between">
            <span>{s.name}</span>
            <span className="text-gray-400">{s.role}{s.branch ? ` · ${s.branch}` : ''}</span>
          </button>
        ))}
        {staff.length === 0 && <div className="text-gray-400 px-2 py-2">لا نتائج</div>}
      </div>
      {save.isError && <div className="text-red-600">{save.error?.response?.data?.detail || 'فشل الحفظ'}</div>}
    </div>
  )
}

export default function ExtensionsPanel() {
  const [editing, setEditing] = useState(null)
  const [filter, setFilter] = useState('all')
  const { data, isFetching, refetch, isError, error } = useQuery({
    queryKey: ['pbx-extensions'],
    queryFn: () => pbxApi.extensionStatus().then(r => r.data),
    refetchInterval: 60_000,
  })

  const rows = (data?.rows || []).filter(r =>
    filter === 'all' ? true
      : filter === 'problems' ? !!r.problem
      : filter === 'offline' ? !r.online
      : filter === 'unmapped' ? !r.mapping : true)

  return (
    <section className="card space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-gray-600 dark:text-gray-300">التحويلات والهواتف</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            حالة تسجيل كل تحويلة في السنترال لحظياً ({data?.tech || '—'}) وربطها بالموظفين. القراءة فقط من Issabel — الربط يُحفظ عندنا.
          </p>
        </div>
        <button onClick={() => refetch()} disabled={isFetching} className="btn-secondary text-xs px-3 py-1">
          {isFetching ? '⏳' : '🔄'} تحديث
        </button>
      </div>

      {isError && <div className="text-sm text-red-600">{error?.response?.data?.detail || 'تعذر التحميل'}</div>}
      {data?.error && (
        <div className="text-xs rounded-lg border border-red-200 bg-red-50 dark:bg-red-900/20 p-2 text-red-700 dark:text-red-300">
          تعذر قراءة الحالة من السنترال — المعروض آخر حالة معروفة. السبب: <span dir="ltr">{data.error}</span>. استخدم «🩺 فحص الاتصال» أعلاه.
        </div>
      )}

      {data && (
        <div className="flex flex-wrap gap-2 text-xs">
          {[
            ['all', `الكل ${data.summary.total}`],
            ['problems', `مشاكل ${data.rows.filter(r => r.problem).length}`],
            ['offline', `غير متصل ${data.summary.offline}`],
            ['unmapped', `غير مرتبطة ${data.summary.unmapped}`],
          ].map(([k, l]) => (
            <button key={k} onClick={() => setFilter(k)}
              className={`px-3 py-1 rounded-full border ${filter === k
                ? 'bg-gray-800 text-white border-gray-800 dark:bg-gray-200 dark:text-gray-900'
                : 'border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-300'}`}>{l}</button>
          ))}
          <span className="text-gray-400 self-center">متصل {data.summary.online} · في مكالمة {data.summary.on_call}</span>
        </div>
      )}

      <div className="divide-y divide-gray-100 dark:divide-gray-700">
        {rows.map(r => (
          <div key={r.extension} className="py-2 text-sm">
            <div className="flex items-center gap-3">
              <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${r.on_call ? 'bg-blue-500 animate-pulse' : r.online ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-600'}`}
                title={r.on_call ? 'في مكالمة' : r.online ? 'متصل' : 'غير متصل'} />
              <span className="font-mono font-bold w-14">{r.extension}</span>
              <span className="flex-1 min-w-0 truncate">
                {r.mapping?.staff_name
                  ? <>{r.mapping.staff_name} <span className="text-xs text-gray-400">· {r.mapping.type_label}{r.mapping.branch ? ` · ${r.mapping.branch}` : ''}</span></>
                  : <span className="text-gray-400">{r.mapping ? `${r.mapping.type_label} — بدون موظف` : 'غير مرتبطة'}</span>}
              </span>
              <span className="text-xs text-gray-500 font-mono hidden md:inline" dir="ltr">{r.ip || '—'}</span>
              <span className="text-xs tabular-nums w-16 text-left" dir="ltr">{r.rtt_ms != null ? `${r.rtt_ms} ms` : ''}</span>
              <span className="text-xs text-gray-500 w-24 truncate" dir="ltr" title={r.user_agent}>{r.status}</span>
              <button onClick={() => setEditing(editing === r.extension ? null : r.extension)}
                className="text-xs text-brand-600 hover:underline shrink-0">ربط</button>
            </div>
            {r.problem && <div className="text-xs text-amber-700 dark:text-amber-400 mt-1 pr-5">⚠️ {r.problem}</div>}
            {editing === r.extension && <MapEditor row={r} onDone={() => setEditing(null)} />}
          </div>
        ))}
        {data && rows.length === 0 && <div className="text-xs text-gray-400 py-4 text-center">لا توجد تحويلات</div>}
      </div>
    </section>
  )
}
