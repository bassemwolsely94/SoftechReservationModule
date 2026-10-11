/**
 * NotesLog — «إيه الجديد» for trainers: every one-line «what changed» note of the last
 * 30 days in one list — screen help, role paths, quizzes and workflow tours, from
 * trainers and from the developers' repo notes — so trainers keep the wording
 * consistent. Each row opens the thing it describes (screen editor / training editor).
 * Data: GET /api/help/notes-log/ (help/edit only).
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { helpApi } from '../api/client'
import { pick } from './text'

const KINDS = [['', 'الكل'], ['screen', 'شاشات'], ['path', 'مسارات'], ['quiz', 'اختبارات'], ['flow', 'جولات']]
const KIND_LABEL = { screen: '📄 شاشة', path: '🎓 مسار', quiz: '📝 اختبار', flow: '🧭 جولة' }
const STATE = {
  shown: ['ظاهر للناس', 'text-emerald-700 border-emerald-200 bg-emerald-50'],
  sent: ['اتبعت في الإشعار', 'text-brand-700 border-brand-200 bg-brand-50'],
  replaced: ['اتغطّى بتعديل أحدث', 'text-faint border-line'],
}

export default function NotesLog({ go }) {
  const [kind, setKind] = useState('')
  const { data } = useQuery({
    queryKey: ['help', 'notes-log'],
    queryFn: () => helpApi.notesLog().then((r) => r.data),
  })
  const items = (data?.items || []).filter((n) => !kind || n.kind === kind)
  const open = (n) => {
    if (n.kind === 'screen') go({ tab: 'browse', screen: n.key, ...(n.source === 'trainer' ? { edit: '1' } : {}) })
    else go({ tab: 'trainers', tkind: n.kind, tkey: n.key })
  }
  return (
    <div className="rounded-xl border border-line bg-surface p-4 space-y-2" dir="rtl" data-tour="general-help-notes-log">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-bold text-content flex-1">📝 إيه الجديد — ملاحظات آخر {data?.days || 30} يوم</h3>
        <div className="flex border border-line rounded-lg overflow-hidden text-xs">
          {KINDS.map(([k, t]) => (
            <button key={k} type="button" onClick={() => setKind(k)}
                    className={`px-2.5 py-1 ${kind === k ? 'bg-brand-600 text-white' : 'text-muted hover:bg-surface-3'}`}>{t}</button>
          ))}
        </div>
      </div>
      <p className="text-xs text-faint">السطر اللي بيشوفه الناس مع كل تعديل — راجعه عشان الصياغة تفضل موحّدة. اضغط أي سطر تفتح اللي اتعدّل.</p>
      {data && items.length === 0 && <div className="text-sm text-faint">مفيش ملاحظات في الفترة دي.</div>}
      <div className="divide-y divide-line max-h-96 overflow-y-auto">
        {items.map((n, i) => (
          <button key={i} type="button" onClick={() => open(n)}
                  className="w-full text-start py-2 flex flex-wrap items-start gap-x-3 gap-y-1 text-sm hover:bg-surface-2">
            <span className="text-[11px] text-faint tabnum w-20 shrink-0">{n.at.slice(0, 10)}</span>
            <span className="text-[11px] text-muted w-16 shrink-0">{KIND_LABEL[n.kind]}</span>
            <span className="flex-1 min-w-[180px]">
              <span className="font-semibold text-content">{pick(n.title, 'ar')}</span>
              <span className="text-content"> — «{n.note}»</span>
              <span className="block text-[11px] text-faint">{n.source === 'repo' ? 'من المطوّرين' : n.staff}</span>
            </span>
            <span className={`text-[10px] border rounded px-1.5 ${STATE[n.state]?.[1] || ''}`}>{STATE[n.state]?.[0]}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
