/**
 * PurchasingPage.jsx
 * Route: /purchasing
 * Roles: admin, purchasing only
 *
 * Sections:
 *  1. KPI strip
 *  2. Daily trend — SVG area chart
 *  3. Weekly status breakdown — horizontal bar chart
 *  4. Top 10 items — ranked bar table
 *  5. Rejection reasons — donut (SVG)
 *  6. Branch rankings — requestors + sources side by side
 *  7. Flagged transfers — action table
 *  8. Recommended for regular order — highlighted table
 *  9. Inter-branch flow matrix
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { purchasingApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Design tokens
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const BRAND   = '#1B6B3A'
const BRAND_L = '#f0f9f4'
const GREEN   = '#10b981'
const BLUE    = '#3b82f6'
const ORANGE  = '#f59e0b'
const RED     = '#ef4444'
const PURPLE  = '#8b5cf6'
const GRAY    = '#9ca3af'

const STATUS_COLORS = {
  sent:      ORANGE,
  accepted:  GREEN,
  partial:   BLUE,
  rejected:  RED,
  fulfilled: BRAND,
  cancelled: GRAY,
  draft:     GRAY,
}

const STATUS_LABELS = {
  sent:      'بانتظار الرد',
  accepted:  'مقبول',
  partial:   'جزئي',
  rejected:  'مرفوض',
  fulfilled: 'منفَّذ',
  cancelled: 'ملغي',
  draft:     'مسودة',
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Shared primitives
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function SectionTitle({ icon, children }) {
  return (
    <h2 className="text-sm font-bold text-gray-700 flex items-center gap-2 mb-4">
      <span className="w-1 h-4 rounded-full inline-block" style={{ background: BRAND }} />
      {icon && <span>{icon}</span>}
      {children}
    </h2>
  )
}

function Card({ children, className = '' }) {
  return (
    <div className={`bg-white rounded-2xl shadow-sm border border-gray-100 p-5 ${className}`}>
      {children}
    </div>
  )
}

function SkeletonCard() {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 p-5 animate-pulse">
      <div className="h-3 bg-gray-100 rounded w-1/3 mb-3" />
      <div className="h-8 bg-gray-100 rounded w-1/2 mb-2" />
      <div className="h-2 bg-gray-100 rounded w-2/3" />
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 1. KPI Card
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function KpiCard({ label, value, sub, color = BRAND, bg = BRAND_L, icon }) {
  return (
    <div
      className="rounded-2xl p-4 flex flex-col gap-1 border"
      style={{ background: bg, borderColor: color + '33' }}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold" style={{ color }}>{label}</span>
        {icon && <span className="text-lg">{icon}</span>}
      </div>
      <div className="text-3xl font-black tabular-nums" style={{ color }}>
        {value ?? '—'}
      </div>
      {sub && <div className="text-xs opacity-70" style={{ color }}>{sub}</div>}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 2. SVG Area Chart — daily trend
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function AreaChart({ data, color = BRAND, height = 120 }) {
  if (!data || data.length < 2) return (
    <div className="flex items-center justify-center h-28 text-gray-300 text-xs">
      لا توجد بيانات كافية
    </div>
  )

  const W = 600
  const H = height
  const PAD = { top: 8, right: 8, bottom: 24, left: 28 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const counts = data.map(d => d.count)
  const maxV = Math.max(...counts, 1)

  const xScale = (i) => PAD.left + (i / (data.length - 1)) * innerW
  const yScale = (v) => PAD.top + innerH - (v / maxV) * innerH

  const points = data.map((d, i) => `${xScale(i)},${yScale(d.count)}`).join(' ')
  const areaPoints = [
    `${xScale(0)},${PAD.top + innerH}`,
    ...data.map((d, i) => `${xScale(i)},${yScale(d.count)}`),
    `${xScale(data.length - 1)},${PAD.top + innerH}`,
  ].join(' ')

  // Show a label every ~7 points
  const step = Math.max(1, Math.floor(data.length / 6))
  const labelIdxs = data.map((_, i) => i).filter(i => i % step === 0)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0.01" />
        </linearGradient>
      </defs>
      {/* Area fill */}
      <polygon points={areaPoints} fill="url(#areaGrad)" />
      {/* Line */}
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* Dots */}
      {data.map((d, i) => (
        d.count > 0 && (
          <circle
            key={i}
            cx={xScale(i)} cy={yScale(d.count)}
            r="3"
            fill={color}
          />
        )
      ))}
      {/* X axis labels */}
      {labelIdxs.map(i => (
        <text
          key={i}
          x={xScale(i)} y={H - 4}
          textAnchor="middle"
          fontSize="9"
          fill="#9ca3af"
        >
          {data[i].date.slice(5)} {/* MM-DD */}
        </text>
      ))}
      {/* Y axis max */}
      <text x={PAD.left - 4} y={PAD.top + 4} textAnchor="end" fontSize="9" fill="#9ca3af">
        {maxV}
      </text>
    </svg>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 3. Horizontal bar chart — weekly breakdown
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function HorizontalBarChart({ data }) {
  if (!data || data.length === 0) return (
    <div className="text-gray-300 text-xs text-center py-6">لا توجد بيانات</div>
  )
  const maxV = Math.max(...data.map(d => d.count), 1)
  return (
    <div className="space-y-2.5">
      {data.map(row => {
        const color = STATUS_COLORS[row.status] || GRAY
        const label = STATUS_LABELS[row.status] || row.status
        const pct = (row.count / maxV) * 100
        return (
          <div key={row.status}>
            <div className="flex items-center justify-between text-xs mb-1">
              <div className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                <span className="text-gray-600 font-medium">{label}</span>
              </div>
              <span className="font-bold tabular-nums" style={{ color }}>{row.count}</span>
            </div>
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${pct}%`, background: color }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 5. SVG Donut — rejection reasons
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const DONUT_COLORS = [RED, ORANGE, PURPLE, BLUE, GRAY]

function DonutChart({ data, size = 140 }) {
  if (!data || data.length === 0) return (
    <div className="text-gray-300 text-xs text-center py-8">لا يوجد رفض</div>
  )

  const total = data.reduce((s, d) => s + d.count, 0)
  if (total === 0) return null

  const R = size / 2
  const r_inner = R * 0.58
  let angle = -Math.PI / 2

  const slices = data.map((d, i) => {
    const sweep = (d.count / total) * 2 * Math.PI
    const x1 = R + R * Math.cos(angle)
    const y1 = R + R * Math.sin(angle)
    angle += sweep
    const x2 = R + R * Math.cos(angle)
    const y2 = R + R * Math.sin(angle)
    const large = sweep > Math.PI ? 1 : 0
    return {
      ...d,
      color: DONUT_COLORS[i % DONUT_COLORS.length],
      path: `M ${R} ${R} L ${x1} ${y1} A ${R} ${R} 0 ${large} 1 ${x2} ${y2} Z`,
      pct: Math.round(d.count / total * 100),
    }
  })

  return (
    <div className="flex items-center gap-4 flex-wrap">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="flex-shrink-0">
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} opacity={0.88} />
        ))}
        {/* Inner circle cutout */}
        <circle cx={R} cy={R} r={r_inner} fill="white" />
        {/* Centre label */}
        <text x={R} y={R - 4} textAnchor="middle" fontSize="11" fontWeight="bold" fill="#374151">
          {total}
        </text>
        <text x={R} y={R + 11} textAnchor="middle" fontSize="8" fill="#9ca3af">
          رفض
        </text>
      </svg>
      {/* Legend */}
      <div className="space-y-1.5 flex-1 min-w-0">
        {slices.map((s, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: s.color }} />
            <span className="text-gray-600 flex-1 truncate">{s.label}</span>
            <span className="font-bold tabular-nums" style={{ color: s.color }}>
              {s.count} <span className="text-gray-400 font-normal">({s.pct}%)</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 4. Top items ranked table
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function TopItemsTable({ items }) {
  if (!items || items.length === 0) return (
    <div className="text-gray-300 text-xs text-center py-8">لا توجد بيانات</div>
  )
  const maxCount = Math.max(...items.map(i => i.request_count), 1)

  return (
    <div className="space-y-1">
      {items.map((item, idx) => {
        const barPct = (item.request_count / maxCount) * 100
        const accColor = item.acceptance_rate >= 70 ? GREEN
                       : item.acceptance_rate >= 40 ? ORANGE : RED
        return (
          <div key={item['item__id'] || idx} className="group">
            <div className="flex items-center gap-3 py-2 px-2 rounded-lg group-hover:bg-gray-50 transition-colors">
              {/* Rank */}
              <span className="text-xs font-black text-gray-300 tabular-nums w-5 text-center flex-shrink-0">
                {idx + 1}
              </span>
              {/* Item name */}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-gray-800 truncate">
                  {item['item__name']}
                </div>
                <div className="text-xs text-gray-400 font-mono">
                  كود: {item['item__softech_id']}
                </div>
                {/* Bar */}
                <div className="h-1 bg-gray-100 rounded-full mt-1 overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${barPct}%`, background: BRAND }}
                  />
                </div>
              </div>
              {/* Stats */}
              <div className="text-left flex-shrink-0 space-y-0.5">
                <div className="text-xs font-bold tabular-nums text-gray-800">
                  {item.request_count} طلب
                </div>
                <div
                  className="text-xs font-semibold tabular-nums"
                  style={{ color: accColor }}
                >
                  {item.acceptance_rate}% قبول
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 6. Branch ranking table (requestors or sources)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function BranchRankTable({ branches, rateLabel, rateKey, rateColorFn }) {
  if (!branches || branches.length === 0) return (
    <div className="text-gray-300 text-xs text-center py-6">لا توجد بيانات</div>
  )
  const maxCount = Math.max(...branches.map(b => b.count), 1)

  return (
    <div className="space-y-2">
      {branches.map((b, i) => {
        const barPct = (b.count / maxCount) * 100
        const rate = b[rateKey] ?? 0
        const rateColor = rateColorFn(rate)
        return (
          <div key={b.branch_id || i} className="rounded-xl bg-gray-50 px-3 py-2">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-semibold text-gray-700 truncate">
                {b.branch_name}
              </span>
              <div className="flex items-center gap-2 flex-shrink-0">
                <span className="text-xs tabular-nums text-gray-500">{b.count} طلب</span>
                <span
                  className="text-xs font-bold tabular-nums px-1.5 py-0.5 rounded"
                  style={{ color: rateColor, background: rateColor + '18' }}
                >
                  {rate}% {rateLabel}
                </span>
              </div>
            </div>
            <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${barPct}%`, background: BRAND }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 7. Flagged transfers table
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function FlaggedTable({ flagged, onRowClick }) {
  if (!flagged || flagged.length === 0) return (
    <div className="flex flex-col items-center justify-center py-10 text-center">
      <div className="text-4xl mb-2">✅</div>
      <div className="text-sm text-gray-500 font-medium">لا توجد تحويلات غير مُصرَّفة</div>
      <div className="text-xs text-gray-400 mt-1">
        جميع التحويلات المقبولة لها مبيعات مسجلة
      </div>
    </div>
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100">
            <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">#</th>
            <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الصنف</th>
            <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الفرع الطالب</th>
            <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">الكمية</th>
            <th className="text-right pb-2 px-2 text-xs font-semibold text-gray-400">أيام بلا مبيعات</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {flagged.map(f => (
            <tr
              key={f.id}
              onClick={() => onRowClick(f.id)}
              className="cursor-pointer hover:bg-red-50 transition-colors"
            >
              <td className="py-2.5 px-2 text-xs text-gray-400 font-mono">{f.id}</td>
              <td className="py-2.5 px-2">
                <div className="font-semibold text-gray-800 text-xs">{f.item_name}</div>
                <div className="text-gray-400 font-mono text-xs">{f.softech_id}</div>
              </td>
              <td className="py-2.5 px-2 text-xs text-gray-600">{f.branch_name}</td>
              <td className="py-2.5 px-2 text-xs font-bold tabular-nums text-gray-800">
                {f.qty}
              </td>
              <td className="py-2.5 px-2">
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold"
                  style={{
                    background: (f.days_since || 0) > 21 ? '#fef2f2' : '#fff7ed',
                    color: (f.days_since || 0) > 21 ? RED : ORANGE,
                  }}
                >
                  ⚠ {f.days_since ?? '?'} يوم
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 8. Recommended for order widget
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function RecommendedTable({ items }) {
  if (!items || items.length === 0) return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <div className="text-3xl mb-2">📦</div>
      <div className="text-sm text-gray-500">لا توجد أصناف تستوجب الإضافة للأوردر الدوري</div>
      <div className="text-xs text-gray-400 mt-1">
        تظهر هنا الأصناف التي طُلب تحويلها 3 مرات أو أكثر
      </div>
    </div>
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-brand-100">
            <th className="text-right pb-3 px-3 text-xs font-bold text-brand-700">الصنف</th>
            <th className="text-right pb-3 px-3 text-xs font-bold text-brand-700">كود سوفتك</th>
            <th className="text-right pb-3 px-3 text-xs font-bold text-brand-700">عدد الطلبات</th>
            <th className="text-right pb-3 px-3 text-xs font-bold text-brand-700">إجمالي الكميات</th>
            <th className="text-right pb-3 px-3 text-xs font-bold text-brand-700">نسبة القبول</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-brand-50">
          {items.map((item, i) => (
            <tr key={item.item_id || i} className="hover:bg-brand-50 transition-colors">
              <td className="py-3 px-3">
                <div className="font-bold text-gray-900 text-xs">{item.item_name}</div>
                <div className="text-xs text-brand-600 mt-0.5">{item.reason}</div>
              </td>
              <td className="py-3 px-3 font-mono text-xs text-gray-500">
                {item.softech_id}
              </td>
              <td className="py-3 px-3">
                <span
                  className="inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-black text-white"
                  style={{ background: BRAND }}
                >
                  {item.request_count}
                </span>
              </td>
              <td className="py-3 px-3 text-xs font-semibold tabular-nums text-gray-700">
                {item.total_qty?.toFixed(1)} وحدة
              </td>
              <td className="py-3 px-3">
                <div className="flex items-center gap-2">
                  <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden max-w-16">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${item.accept_rate}%`,
                        background: item.accept_rate >= 70 ? GREEN
                                  : item.accept_rate >= 40 ? ORANGE : RED,
                      }}
                    />
                  </div>
                  <span className="text-xs font-bold tabular-nums">
                    {item.accept_rate}%
                  </span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 9. Flow matrix
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function FlowMatrix({ matrix }) {
  if (!matrix || matrix.length === 0) return (
    <div className="text-gray-300 text-xs text-center py-6">لا توجد بيانات</div>
  )
  const maxCount = Math.max(...matrix.map(r => r.count), 1)
  return (
    <div className="space-y-1.5">
      {matrix.map((row, i) => {
        const pct = (row.count / maxCount) * 100
        return (
          <div key={i} className="flex items-center gap-3 text-xs">
            <span className="w-24 text-right font-medium text-brand-700 truncate flex-shrink-0">
              {row.from}
            </span>
            <span className="text-gray-400 flex-shrink-0">→</span>
            <span className="w-24 text-gray-600 truncate flex-shrink-0">{row.to}</span>
            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{ width: `${pct}%`, background: BRAND, opacity: 0.7 }}
              />
            </div>
            <span className="font-bold tabular-nums w-6 text-right text-gray-700 flex-shrink-0">
              {row.count}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Main Page
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function PurchasingPage() {
  const { user } = useAuthStore()
  const navigate = useNavigate()
  const [days, setDays] = useState(30)

  // Role guard
  if (user && !['admin', 'purchasing'].includes(user.role)) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-8 text-center" dir="rtl">
        <div className="text-5xl mb-4">🔒</div>
        <div className="text-lg font-bold text-gray-700">غير مصرح بالدخول</div>
        <div className="text-sm text-gray-400 mt-2">
          هذه الصفحة مخصصة لقسم المشتريات والمديرين فقط
        </div>
        <button onClick={() => navigate('/dashboard')} className="btn-secondary mt-6 text-sm">
          ← الرئيسية
        </button>
      </div>
    )
  }

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['purchasing-dashboard', days],
    queryFn: () => purchasingApi.dashboard(days).then(r => r.data),
    refetchInterval: 120_000,
  })

  const kpis = data?.kpis || {}

  return (
    <div className="min-h-full bg-gray-50 pb-10" dir="rtl">

      {/* ── Page header ─────────────────────────────────────────── */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto flex items-center gap-4 flex-wrap">
          <div>
            <h1 className="text-xl font-black text-gray-900 flex items-center gap-2">
              <span>📊</span> لوحة المشتريات والتحويلات
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">
              تحليل طلبات التحويل بين الفروع وإدارة الأوردر الدوري
              {data?.generated_at && (
                <span className="mr-2">
                  · تحديث:{' '}
                  {format(new Date(data.generated_at), 'HH:mm', { locale: ar })}
                </span>
              )}
            </p>
          </div>

          <div className="flex-1" />

          {/* Window selector */}
          <div className="flex items-center gap-1 border border-gray-200 rounded-lg overflow-hidden text-xs">
            {[7, 14, 30, 60, 90].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-3 py-1.5 font-semibold transition-colors ${
                  days === d
                    ? 'text-white'
                    : 'text-gray-500 hover:bg-gray-50'
                }`}
                style={days === d ? { background: BRAND } : {}}
              >
                {d} يوم
              </button>
            ))}
          </div>

          <button
            onClick={() => navigate('/transfers')}
            className="btn-secondary text-xs"
          >
            🔀 طلبات التحويل
          </button>
          <button onClick={() => refetch()} className="btn-secondary text-xs">
            ↻ تحديث
          </button>
        </div>
      </div>

      {/* ── Body ────────────────────────────────────────────────── */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">

        {/* Error state */}
        {isError && (
          <div className="card border border-red-200 bg-red-50 text-red-700 text-sm text-center py-6">
            حدث خطأ في تحميل البيانات.{' '}
            <button onClick={() => refetch()} className="underline">أعد المحاولة</button>
          </div>
        )}

        {/* ── 1. KPI Strip ──────────────────────────────────────── */}
        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {[1,2,3,4,5].map(i => <SkeletonCard key={i} />)}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
            <KpiCard
              label="إجمالي الطلبات"
              value={kpis.total}
              sub={`آخر ${days} يوم`}
              color={BRAND} bg={BRAND_L}
              icon="📦"
            />
            <KpiCard
              label="بانتظار الرد"
              value={kpis.pending}
              sub="حالياً"
              color={ORANGE} bg="#fffbeb"
              icon="⏳"
            />
            <KpiCard
              label="نسبة القبول"
              value={`${kpis.accept_rate ?? 0}%`}
              sub={`${kpis.accepted} مقبول + ${kpis.partial} جزئي`}
              color={GREEN} bg="#f0fdf4"
              icon="✅"
            />
            <KpiCard
              label="مرفوض"
              value={kpis.rejected}
              sub={`${days} يوم`}
              color={RED} bg="#fef2f2"
              icon="❌"
            />
            <KpiCard
              label="غير مُصرَّف ⚠"
              value={kpis.flagged}
              sub="تحويل بلا مبيعات +14 يوم"
              color={RED} bg="#fef2f2"
              icon="⚠️"
            />
          </div>
        )}

        {/* Secondary KPIs row */}
        {!isLoading && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <KpiCard
              label="تم القبول الجزئي"
              value={kpis.partial}
              color={BLUE} bg="#eff6ff"
              icon="⚠️"
            />
            <KpiCard
              label="تم التنفيذ"
              value={kpis.fulfilled}
              color={BRAND} bg={BRAND_L}
              icon="🏁"
            />
            <KpiCard
              label="متوسط وقت الرد"
              value={kpis.avg_response_hrs != null ? `${kpis.avg_response_hrs} ساعة` : '—'}
              sub="من الإرسال حتى الرد"
              color={PURPLE} bg="#f5f3ff"
              icon="⏱️"
            />
            <KpiCard
              label="يُنصح بإضافتها للأوردر"
              value={data?.recommended?.length ?? 0}
              sub="صنف بتكرار طلب ≥3 مرات"
              color={ORANGE} bg="#fffbeb"
              icon="📋"
            />
          </div>
        )}

        {/* ── 2+3. Trend + Weekly breakdown ─────────────────────── */}
        {!isLoading && (
          <div className="grid md:grid-cols-3 gap-5">
            <Card className="md:col-span-2">
              <SectionTitle icon="📈">
                حجم الطلبات اليومي — آخر {days} يوم
              </SectionTitle>
              <AreaChart data={data?.daily_trend} color={BRAND} height={130} />
            </Card>
            <Card>
              <SectionTitle icon="📊">تفصيل هذا الأسبوع</SectionTitle>
              <HorizontalBarChart data={data?.weekly_breakdown} />
            </Card>
          </div>
        )}

        {/* ── 4+5. Top items + Rejection donut ──────────────────── */}
        {!isLoading && (
          <div className="grid md:grid-cols-3 gap-5">
            <Card className="md:col-span-2">
              <SectionTitle icon="🏆">أكثر الأصناف طلباً للتحويل</SectionTitle>
              <TopItemsTable items={data?.top_items} />
            </Card>
            <Card>
              <SectionTitle icon="❌">أسباب الرفض</SectionTitle>
              <DonutChart data={data?.rejection_reasons} size={150} />
            </Card>
          </div>
        )}

        {/* ── 6. Branch rankings ────────────────────────────────── */}
        {!isLoading && (
          <div className="grid md:grid-cols-2 gap-5">
            <Card>
              <SectionTitle icon="🏥">الفروع الأكثر طلباً للتحويل</SectionTitle>
              <BranchRankTable
                branches={data?.top_requestors}
                rateLabel="رفض"
                rateKey="rejection_rate"
                rateColorFn={r => r > 40 ? RED : r > 20 ? ORANGE : GREEN}
              />
            </Card>
            <Card>
              <SectionTitle icon="📤">الفروع الأكثر استقباباً للطلبات</SectionTitle>
              <BranchRankTable
                branches={data?.top_sources}
                rateLabel="قبول"
                rateKey="acceptance_rate"
                rateColorFn={r => r >= 70 ? GREEN : r >= 40 ? ORANGE : RED}
              />
            </Card>
          </div>
        )}

        {/* ── 7. Flagged transfers ───────────────────────────────── */}
        {!isLoading && (
          <Card>
            <div className="flex items-center justify-between mb-4">
              <SectionTitle icon="⚠️">
                تحويلات مقبولة بلا مبيعات (أكثر من 14 يوم)
              </SectionTitle>
              {(data?.flagged_list?.length ?? 0) > 0 && (
                <span
                  className="text-xs font-bold px-2 py-0.5 rounded-full"
                  style={{ background: '#fef2f2', color: RED }}
                >
                  {data.flagged_list.length} حالة
                </span>
              )}
            </div>
            <FlaggedTable
              flagged={data?.flagged_list}
              onRowClick={id => navigate(`/transfers/${id}`)}
            />
          </Card>
        )}

        {/* ── 8. Recommended for regular order ──────────────────── */}
        {!isLoading && (
          <Card style={{ borderColor: BRAND + '33', borderWidth: 2 }}>
            <div className="flex items-start justify-between mb-4">
              <div>
                <SectionTitle icon="📋">
                  أصناف يُنصح بإضافتها للأوردر الدوري
                </SectionTitle>
                <p className="text-xs text-gray-400 -mt-2 mb-3">
                  أصناف طُلب تحويلها 3 مرات أو أكثر خلال آخر {days} يوم —
                  يُشير ذلك إلى نقص مزمن ينبغي معالجته من الأوردر الرئيسي
                </p>
              </div>
              {(data?.recommended?.length ?? 0) > 0 && (
                <span
                  className="text-xs font-black px-3 py-1 rounded-full text-white flex-shrink-0"
                  style={{ background: BRAND }}
                >
                  {data.recommended.length} صنف
                </span>
              )}
            </div>
            <RecommendedTable items={data?.recommended} />
          </Card>
        )}

        {/* ── 9. Flow matrix ─────────────────────────────────────── */}
        {!isLoading && (data?.flow_matrix?.length ?? 0) > 0 && (
          <Card>
            <SectionTitle icon="🔀">أكثر مسارات التحويل تكراراً</SectionTitle>
            <p className="text-xs text-gray-400 -mt-2 mb-4">
              الفرع الطالب ← الفرع المصدر
            </p>
            <FlowMatrix matrix={data?.flow_matrix} />
          </Card>
        )}

      </div>
    </div>
  )
}
