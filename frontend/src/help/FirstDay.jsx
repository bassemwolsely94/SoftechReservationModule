/**
 * FirstDay — «أول يوم في النظام»: cards at the top of the home page (desktop
 * /dashboard, mobile «لوحتي») until the person's training path is complete or they
 * hide it. Calm by design — cards on the page, never a popup; every card starts on a
 * click. Data and the "done" ticks come from /api/help/first-day/.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { helpApi } from '../api/client'
import useHelpStore from './helpStore'
import { startScreenTour } from './Tour'
import { pick } from './text'

export default function FirstDay({ mobile = false }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const startTour = useHelpStore((s) => s.startTour)
  const { data } = useQuery({
    queryKey: ['help', 'first-day', mobile],
    queryFn: () => helpApi.firstDay(mobile).then((r) => r.data),
    staleTime: 60_000,
  })
  if (!data?.show) return null
  const hide = async () => { await helpApi.hideFirstDay(true); qc.invalidateQueries({ queryKey: ['help', 'first-day'] }) }
  const p = data.progress
  const next = data.next_screen
  const openNext = () => {
    const route = next.routes.find((r) => !r.includes(':') && (mobile ? r.startsWith('/m/') : !r.startsWith('/m/')))
      || next.routes.find((r) => !r.includes(':'))
    if (route) {
      navigate(route)
      if (next.has_tour) setTimeout(() => startScreenTour(next.key).catch(() => {}), 600)
    } else navigate(`/help?tab=browse&screen=${next.key}`)
  }

  const Card = ({ icon, title, sub, note, done, onClick, cta, primary }) => (
    <button type="button" onClick={onClick}
            className={`text-start rounded-xl border p-4 space-y-1.5 transition hover:shadow-sm ${primary
              ? 'border-brand-300 bg-brand-50 hover:border-brand-400' : 'border-line bg-surface hover:border-brand-300'}`}>
      <div className="flex items-center gap-2">
        <span className="text-2xl">{icon}</span>
        <span className="flex-1 font-semibold text-content text-sm leading-6">{title}</span>
        {done && <span className="text-[11px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1.5">✓ تم</span>}
      </div>
      {sub && <div className="text-xs text-muted leading-5 line-clamp-2">{sub}</div>}
      {note && <div className="text-[11px] text-brand-700 leading-5">✨ اتحدّث: {note}</div>}
      <div className="text-xs font-semibold text-brand-700">{cta} ←</div>
    </button>
  )

  return (
    <section data-tour="general-first-day" className="rounded-2xl border border-brand-200 bg-surface p-4 sm:p-5 space-y-4" dir="rtl">
      <div className="flex items-start gap-3 flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <h2 className="text-base font-bold text-content">👋 أهلاً بيك — ابدأ من هنا</h2>
          <p className="text-xs text-muted leading-6">
            خطوات قصيرة تعرّفك على النظام وعلى شغلك فيه. كل كارت بيبدأ لما تضغطه، وتقدر تكمّل في أي وقت.
          </p>
        </div>
        <div className="flex items-center gap-2 min-w-[160px]">
          <div className="flex-1 h-2 rounded-full bg-surface-3 overflow-hidden">
            <div className="h-full bg-brand-600" style={{ width: `${p.percent}%` }} />
          </div>
          <span className="text-sm font-bold text-brand-700 tabnum">{p.percent}%</span>
        </div>
        <button type="button" onClick={hide} className="text-xs text-faint hover:text-content"
                title="تقدر ترجع لها من «دليل الاستخدام» ← «مساري التدريبي»">إخفاء ✕</button>
      </div>

      <div className={`grid gap-3 ${mobile ? 'grid-cols-1' : 'sm:grid-cols-2 lg:grid-cols-4'}`}>
        {data.system_tour && (
          <Card icon="🧭" primary={!data.system_tour.done} done={data.system_tour.done}
                title="جولة تعريفية بالنظام" sub="القائمة، البحث، المساعدة، الإشعارات — في دقيقتين."
                cta={data.system_tour.done ? 'شوفها تاني' : 'ابدأ الجولة'}
                onClick={() => startTour(data.system_tour.id, data.system_tour.steps)} />
        )}
        {next && (
          <Card icon="🎓" primary={!!data.system_tour?.done || !data.system_tour}
                title={`مسارك: ${pick(next.title, 'ar')}`}
                sub={`${p.learned}/${p.screens} شاشة اتفهمت — الشاشة الجاية في مسار دورك.`}
                cta={next.has_tour ? 'افتحها واعرض لي' : 'افتح الشرح'} onClick={openNext} />
        )}
        {data.flows.map((f) => (
          <Card key={f.id} icon={mobile ? '📱' : '👆'} done={f.done} title={pick(f.title, 'ar')} sub={pick(f.summary, 'ar')}
                note={f.change_note && pick(f.change_note, 'ar')}
                cta={f.done ? 'شوفها تاني' : 'ابدأ الجولة'} onClick={() => startTour(f.id, f.steps)} />
        ))}
        {data.quiz && (
          <Card icon="📝" title={`اختبار قصير: ${pick(data.quiz.title, 'ar')}`} sub={`${data.quiz.questions} أسئلة — النجاح من 80%.`}
                cta="ادخل الاختبار" onClick={() => navigate(`/help?tab=path&quiz=${data.quiz.module}`)} />
        )}
      </div>
      <button type="button" onClick={() => navigate('/help?tab=path')} className="text-xs text-brand-600 hover:underline">
        🎓 مساري التدريبي كامل ←
      </button>
    </section>
  )
}

/** Mobile landing (الحجوزات): one calm line pointing to the cards on «لوحتي». */
export function FirstDayStrip() {
  const navigate = useNavigate()
  const { data } = useQuery({
    queryKey: ['help', 'first-day', true],
    queryFn: () => helpApi.firstDay(true).then((r) => r.data),
    staleTime: 60_000,
  })
  if (!data?.show) return null
  return (
    <button type="button" onClick={() => navigate('/m/me')} dir="rtl"
            className="w-full text-start rounded-xl border border-brand-200 bg-brand-50 px-3 py-2.5 flex items-center gap-2 mb-3">
      <span className="text-lg">👋</span>
      <span className="flex-1 text-sm font-semibold text-brand-800">أول مرة؟ ابدأ من هنا — جولات قصيرة ومسارك التدريبي</span>
      <span className="text-xs font-bold text-brand-700 tabnum">{data.progress.percent}% ←</span>
    </button>
  )
}
