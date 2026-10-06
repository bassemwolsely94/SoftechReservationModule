/**
 * CustomerMomentBar — the customer's decision-moment context, surfaced on the POS.
 *
 * Reuses the existing /customers/{id}/pos-summary payload (crm + health + loyalty) and
 * renders it as ONE calm, non-modal strip (rule 11): who this customer is, retention risk,
 * lifetime value, loyalty, and — safety-first (rule 4) — chronic + allergy flags that an
 * upsell must never bury. Read-only intelligence; the cashier decides.
 */
import { useEffect, useState } from 'react'
import { customersApi } from '../api/client'
import { money } from '../hooks/usePosOrder'
import { LoyaltyBadge, MetricChip, Badge } from '../pos/design'

const SEG = {
  vip:     'bg-violet-100 text-violet-700 border-violet-200',
  loyal:   'bg-emerald-100 text-emerald-700 border-emerald-200',
  regular: 'bg-gray-100 text-gray-600 border-gray-200',
  at_risk: 'bg-amber-100 text-amber-800 border-amber-200',
  dormant: 'bg-red-100 text-red-700 border-red-200',
  new:     'bg-sky-100 text-sky-700 border-sky-200',
}

export default function CustomerMomentBar({ customerId }) {
  const [s, setS] = useState(null)
  useEffect(() => {
    if (!customerId) { setS(null); return }
    let alive = true
    customersApi.posSummary(customerId)
      .then(({ data }) => { if (alive) setS(data) })
      .catch(() => { if (alive) setS(null) })
    return () => { alive = false }
  }, [customerId])

  if (!s) return null
  const crm = s.crm || {}, health = s.health || {}, loy = s.loyalty || {}
  // Stay calm (rule 11): only surface when there's real intelligence — never a bare
  // name strip for an anonymous walk-in.
  const hasSignal = crm.segment || crm.churn_segment || loy.enrolled ||
    health.is_chronic || (health.allergies?.length > 0) || health.pregnancy || health.lactation ||
    (Number(crm.ltv) > 0)
  if (!hasSignal) return null
  const days = crm.days_since_last_visit
  const atRisk = ['at_risk', 'dormant'].includes(crm.churn_segment)
  const dueRepeat = days != null && days >= 30 && (crm.purchase_count_90d > 0 || crm.last_visit_date)

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] bg-indigo-50/70 border border-indigo-100 rounded-lg px-2.5 py-1.5">
      <span className="font-bold text-gray-800">👤 {crm.name || 'العميل'}</span>

      {crm.segment_label && (
        <span className={`text-[10px] border rounded px-1.5 py-0.5 font-semibold ${SEG[crm.segment] || SEG.regular}`}>
          {crm.segment_label}
        </span>
      )}

      {/* retention risk */}
      {atRisk && (
        <Badge tone="oos" icon="alert" size="sm" title="عميل عرضة للفقد — فرصة احتفاظ"
               label={`عرضة للفقد${crm.churn_segment_label ? ` · ${crm.churn_segment_label}` : ''}`} />
      )}

      {/* loyalty · LTV · last-visit · repeat-due — as semantic chips */}
      {loy.enrolled && <LoyaltyBadge tier={loy.tier_label || loy.tier} points={loy.points_balance} />}
      {crm.ltv != null && Number(crm.ltv) > 0 && <MetricChip icon="trending" label="قيمة العميل" value={money(crm.ltv)} />}
      {days != null && <MetricChip icon="clock" label="آخر زيارة" value={`${days} يوم`} />}
      {dueRepeat && <Badge meaning="repeat" size="sm" label="حان وقت التكرار" title="مرّ وقت كافٍ على آخر شراء" />}

      {/* SAFETY — never buried under an upsell (rule 4) */}
      {health.is_chronic && <Badge tone="ok" icon="pill" size="sm" label="مزمن" title="مريض مزمن" />}
      {health.allergies?.length > 0 && (
        <span className="text-red-600 font-bold bg-red-50 border border-red-200 rounded px-1.5" title="حساسية دوائية">
          ⚠ حساسية: {health.allergies.join('، ')}
        </span>
      )}
      {(health.pregnancy || health.lactation) && (
        <span className="text-pink-700 font-semibold">{health.pregnancy ? '🤰 حمل' : ''}{health.lactation ? ' 🍼 رضاعة' : ''}</span>
      )}
    </div>
  )
}
