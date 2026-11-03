/**
 * Heatmap — missed calls by weekday × hour (doc 33 §7). Pure CSS grid, no chart library.
 * `cells` = [[weekday, hour, count]] where weekday 0 = Saturday … 6 = Friday (the Egyptian week).
 */
const DAYS = ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة']
const HOURS = Array.from({ length: 24 }, (_, i) => i)

export default function Heatmap({ cells = [] }) {
  const grid = new Map(cells.map(([d, h, n]) => [`${d}-${h}`, n]))
  const max = Math.max(1, ...cells.map(c => c[2]))
  return (
    <div className="overflow-x-auto" dir="ltr">
      <div className="grid gap-px text-[10px] text-gray-500 min-w-[640px]" style={{ gridTemplateColumns: '64px repeat(24, minmax(0, 1fr))' }}>
        <div />
        {HOURS.map(h => <div key={h} className="text-center tabular-nums">{h}</div>)}
        {DAYS.map((name, d) => (
          <div key={name} className="contents">
            <div className="text-right pr-2 self-center text-gray-600" dir="rtl">{name}</div>
            {HOURS.map(h => {
              const n = grid.get(`${d}-${h}`) || 0
              return (
                <div key={h} title={`${name} ${h}:00 — ${n}`}
                     className="h-6 rounded-sm flex items-center justify-center tabular-nums text-gray-700"
                     style={{ background: n ? `rgba(220, 38, 38, ${(0.12 + 0.78 * n / max).toFixed(2)})` : 'rgba(0,0,0,0.04)' }}>
                  {n || ''}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
