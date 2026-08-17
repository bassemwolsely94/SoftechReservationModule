/**
 * MyIncentivesPage.jsx
 *
 * Feature 1 — Employee Live Progress Dashboard
 *
 * Each employee sees their own real-time incentive progress mid-period.
 * Runs a silent simulation (no DB write) from period_start to today.
 *
 * Route: /my-incentives
 * Sidebar: all roles (every employee needs this)
 */
import { useState, useEffect, useCallback } from 'react'
import { incentivesApi } from '../api/client'

// ── Tiny helpers ──────────────────────────────────────────────────────────────

const fmt = (n, dp = 2) =>
  Number(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: dp,
    maximumFractionDigits: dp,
  })

function Spinner() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="w-10 h-10 border-4 border-brand-200 border-t-brand-600 rounded-full animate-spin" />
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ pct, color = 'bg-brand-500', label }) {
  const clamped = Math.min(Math.max(pct, 0), 100)
  return (
    <div className="space-y-1">
      {label && <div className="flex justify-between text-xs text-gray-500">
        <span>{label}</span>
        <span>{Math.round(clamped)}%</span>
      </div>}
      <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  )
}

// ── Slab / target progress card ───────────────────────────────────────────────

function SlabCard({ slab }) {
  if (slab.type === 'tiered') {
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="text-sm font-semibold text-gray-700 mb-3">{slab.rule_name}</div>
        <div className="grid grid-cols-2 gap-3 text-sm mb-3">
          <div className="bg-blue-50 rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-blue-700">{fmt(slab.current_qty, 0)}</div>
            <div className="text-xs text-blue-500 mt-0.5">وحدة مباعة</div>
          </div>
          <div className="bg-green-50 rounded-lg p-3 text-center">
            <div className="text-xl font-bold text-green-700">{slab.current_rate}</div>
            <div className="text-xs text-green-500 mt-0.5">السعر الحالي</div>
          </div>
        </div>

        {slab.next_slab_at !== null && (
          <>
            <ProgressBar
              pct={(slab.current_qty / slab.next_slab_at) * 100}
              color="bg-brand-500"
              label={`التقدم نحو المستوى التالي (${slab.next_rate})`}
            />
            <div className="mt-2 text-xs text-orange-700 bg-orange-50 rounded-lg p-2 text-center font-semibold">
              تحتاج {fmt(slab.units_needed, 0)} وحدة إضافية للوصول لمعدل {slab.next_rate}
            </div>
          </>
        )}
        {slab.next_slab_at === null && (
          <div className="mt-2 text-xs text-green-700 bg-green-50 rounded-lg p-2 text-center font-semibold">
            أنت في أعلى مستوى
          </div>
        )}
      </div>
    )
  }

  if (slab.type === 'target_based') {
    const pct = slab.achievement_pct || 0
    const barColor =
      pct >= 100 ? 'bg-green-500' :
      pct >= 80  ? 'bg-yellow-400' :
                   'bg-red-400'
    return (
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="text-sm font-semibold text-gray-700 mb-3">{slab.rule_name}</div>
        <div className="text-center mb-3">
          <div className={`text-4xl font-bold ${pct >= 100 ? 'text-green-600' : pct >= 80 ? 'text-yellow-600' : 'text-red-500'}`}>
            {pct}%
          </div>
          <div className="text-xs text-gray-400 mt-0.5">نسبة الإنجاز</div>
        </div>
        <ProgressBar pct={pct} color={barColor} />
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
          <div className="bg-gray-50 rounded-lg p-2 text-center">
            <div className="font-bold text-gray-800">{fmt(slab.current_qty, 0)}</div>
            <div className="text-gray-500">مُنجَز</div>
          </div>
          <div className="bg-gray-50 rounded-lg p-2 text-center">
            <div className="font-bold text-gray-800">{fmt(slab.target_qty, 0)}</div>
            <div className="text-gray-500">الهدف</div>
          </div>
        </div>
        {slab.units_to_100pct > 0 && (
          <div className="mt-2 text-xs text-orange-700 bg-orange-50 rounded-lg p-2 text-center font-semibold">
            تحتاج {fmt(slab.units_to_100pct, 0)} وحدة لإتمام 100%
          </div>
        )}
      </div>
    )
  }
  return null
}

// ── Program progress card ─────────────────────────────────────────────────────

function ProgramProgressCard({ prog }) {
  const [expanded, setExpanded] = useState(false)

  const periodPct = prog.period_days_total > 0
    ? (prog.period_days_elapsed / prog.period_days_total) * 100
    : 0

  const earningPct = prog.projected_total > 0
    ? (prog.earned_to_date / prog.projected_total) * 100
    : 0

  return (
    <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-l from-brand-600 to-brand-700 px-6 py-5 text-white">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-lg font-bold">{prog.program_name}</div>
            <div className="text-sm opacity-75 mt-0.5">
              {prog.period_start} → {prog.period_end}
            </div>
          </div>
          <div className="text-left">
            <div className="text-3xl font-bold">{fmt(prog.earned_to_date)} <span className="text-sm font-normal">ج.م</span></div>
            <div className="text-xs opacity-75 text-left">مكتسب حتى الآن</div>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          <ProgressBar
            pct={periodPct}
            color="bg-white/40"
            label={`تقدم الفترة — ${prog.period_days_elapsed} من ${prog.period_days_total} يوم`}
          />
        </div>
      </div>

      {/* Projection & top items */}
      <div className="p-5 space-y-4">
        {/* Projection */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-brand-50 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-brand-700">{fmt(prog.projected_total)}</div>
            <div className="text-xs text-brand-500 mt-0.5">المتوقع نهاية الشهر ج.م</div>
          </div>
          <div className="bg-gray-50 rounded-xl p-4 text-center">
            <div className="text-2xl font-bold text-gray-700">{prog.period_days_remaining}</div>
            <div className="text-xs text-gray-500 mt-0.5">يوم متبقٍ</div>
          </div>
        </div>

        {/* Top items */}
        {prog.top_items?.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-gray-500 mb-2">أعلى الأصناف تحقيقاً</div>
            <div className="space-y-1.5">
              {prog.top_items.map(item => (
                <div key={item.item_code}
                  className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                  <span className="text-sm text-gray-700 break-words max-w-[65%]">{item.item_name || item.item_code}</span>
                  <span className="text-sm font-bold text-green-600 whitespace-nowrap">{fmt(item.incentive)} ج.م</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Slab / target progress */}
        {prog.slab_progress?.length > 0 && (
          <div>
            <button
              className="w-full text-xs font-semibold text-brand-600 hover:text-brand-700 flex items-center gap-1 py-1"
              onClick={() => setExpanded(e => !e)}
            >
              <span>{expanded ? '▾' : '▸'}</span>
              <span>تفاصيل مستهدفات السلاب ({prog.slab_progress.length})</span>
            </button>
            {expanded && (
              <div className="mt-2 space-y-3">
                {prog.slab_progress.map((slab, i) => (
                  <SlabCard key={`${slab.rule_id}-${i}`} slab={slab} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* Rule breakdown (collapsed) */}
        {prog.rule_breakdown?.length > 1 && (
          <details className="text-xs">
            <summary className="text-gray-500 cursor-pointer">تفاصيل القواعد</summary>
            <div className="mt-2 space-y-1">
              {prog.rule_breakdown.map(rb => (
                <div key={rb.rule_id} className="flex justify-between px-2 py-1 bg-gray-50 rounded">
                  <span className="text-gray-600">{rb.rule_name || `قاعدة #${rb.rule_id}`}</span>
                  <span className="font-semibold text-gray-800">{fmt(rb.incentive)} ج.م</span>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MyIncentivesPage() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState('')

  const load = useCallback(async () => {
    setLoading(true); setErr('')
    try {
      const { data: res } = await incentivesApi.myProgress()
      setData(res)
    } catch (e) {
      setErr(e.response?.data?.detail || 'فشل تحميل بيانات الحوافز')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  if (loading) return (
    <div className="min-h-screen bg-gray-50">
      <Spinner />
    </div>
  )

  if (err) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="bg-white rounded-2xl shadow p-8 max-w-md text-center space-y-4">
        <div className="text-5xl">⚠️</div>
        <div className="text-red-600 font-semibold">{err}</div>
        <button className="btn-primary" onClick={load}>إعادة المحاولة</button>
      </div>
    </div>
  )

  const employee = data?.employee
  const programs = data?.programs || []
  const asOf     = data?.as_of_date

  const totalEarned    = programs.reduce((s, p) => s + p.earned_to_date, 0)
  const totalProjected = programs.reduce((s, p) => s + p.projected_total, 0)

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-3xl mx-auto space-y-6">

        {/* Page header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">حوافزي</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {employee?.name} — {asOf ? `حتى ${asOf}` : ''}
            </p>
          </div>
          <button
            className="btn-secondary text-sm flex items-center gap-1"
            onClick={load}
          >
            <span>↻</span> تحديث
          </button>
        </div>

        {/* Grand total banner */}
        {programs.length > 0 && (
          <div className="bg-gradient-to-l from-green-600 to-green-700 rounded-2xl p-6 text-white">
            <div className="grid grid-cols-2 gap-6 text-center">
              <div>
                <div className="text-4xl font-bold">{fmt(totalEarned)}</div>
                <div className="text-sm opacity-80 mt-1">ج.م مكتسبة حتى الآن</div>
              </div>
              <div>
                <div className="text-4xl font-bold">{fmt(totalProjected)}</div>
                <div className="text-sm opacity-80 mt-1">ج.م متوقعة نهاية الشهر</div>
              </div>
            </div>
          </div>
        )}

        {/* No programs */}
        {programs.length === 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 p-12 text-center">
            <div className="text-5xl mb-4">💰</div>
            <div className="text-lg font-semibold text-gray-700">لا توجد برامج حوافز نشطة</div>
            <div className="text-sm text-gray-400 mt-1">لا يوجد برنامج حوافز يشمل تاريخ اليوم</div>
          </div>
        )}

        {/* Per-program cards */}
        {programs.map(prog => (
          <ProgramProgressCard key={prog.program_id} prog={prog} />
        ))}

        <p className="text-center text-xs text-gray-400 pb-4">
          * التوقعات تعتمد على متوسط يومي خطي — قد تختلف عن النتائج الفعلية
        </p>
      </div>
    </div>
  )
}
