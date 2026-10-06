/* Offers preview (read-only) — surfaces which offers the deterministic engine says apply to
 * the live basket + gift items to suggest. Does NOT change the order total: applying an
 * offer's discount is a separate, gated step (POS_OFFERS_EXECUTION_ENABLED). Shared web+mobile. */
import { money } from '../hooks/usePosOrder'

const OFFER_TYPE_LABEL = {
  percent: 'نسبة', fixed: 'مبلغ', bxgy: 'اشترِ واحصل', qty_tier: 'متدرّج',
  gift: 'هدية', spend_threshold: 'مكافأة', bundle: 'باقة', mix_match: 'اختر N',
}

export default function OffersPanel({ P }) {
  const plan = P.offersPlan
  if (!plan) return null
  const applied = plan.applied || []
  const suggestions = plan.suggestions || []
  const completions = plan.completions || []
  if (!applied.length && !suggestions.length && !completions.length) return null
  const saving = Number(plan.total_discount || 0)
  return (
    <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50/60 p-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-bold text-emerald-800">🎁 عروض متاحة لهذه السلة</span>
        {saving > 0 && <span className="text-[11px] text-emerald-700">توفير محتمَل: <b>{money(saving)}</b> ج</span>}
      </div>

      {applied.map(a => (
        <div key={a.offer_id} className="flex items-center gap-2 text-[11px] bg-white/70 border border-emerald-100 rounded px-2 py-1 mb-1">
          <span className="badge bg-emerald-100 text-emerald-700">{OFFER_TYPE_LABEL[a.offer_type] || a.offer_type}</span>
          <span className="font-semibold text-gray-800 flex-1 truncate">{a.name}</span>
          <span className="tabnum text-emerald-700">−{money(a.discount)}</span>
          {a.requires_approval
            ? <span className="text-amber-600" title="خصم من العرض — يتطلب موافقة قبل الترحيل">🔒 موافقة</span>
            : <span className="text-gray-400" title="مصرّح من كارت الصنف">✓ كارت</span>}
        </div>
      ))}

      {suggestions.map((s, i) => (
        <div key={i} className="flex items-center gap-2 text-[11px] bg-white/70 border border-sky-100 rounded px-2 py-1 mb-1">
          <span>🎁</span>
          <span className="flex-1 truncate text-gray-800">{s.item_name} <span className="text-gray-400">({s.softech_id})</span> ×{s.qty}</span>
          <button className="text-sky-600 hover:text-sky-800 font-semibold" onClick={() => P.addGift(s)}>+ أضف الهدية</button>
        </div>
      ))}

      {/* near-miss offers — "this can be completed with another item" (read-only hint) */}
      {completions.map((c, i) => (
        <div key={`c${i}`} className="flex items-start gap-2 text-[11px] bg-amber-50/70 border border-amber-200 rounded px-2 py-1 mb-1">
          <span title="عرض قريب — يمكن إكماله">🔓</span>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-amber-800 truncate">{c.name}</div>
            <div className="text-amber-700">{c.message}</div>
          </div>
        </div>
      ))}

      <div className="text-[10px] text-gray-400 mt-1">معاينة فقط — لا تُطبَّق تلقائيًا على الفاتورة (التطبيق مُقيَّد بمفتاح).</div>
    </div>
  )
}
