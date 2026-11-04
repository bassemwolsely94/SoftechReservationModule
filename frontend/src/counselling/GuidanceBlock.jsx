/**
 * GuidanceBlock — renders one counselling sheet (approved, or a draft for pharmacists only).
 * Shared by the drug assistant, the send drawer preview and the public card page.
 */
export const GUIDANCE_FIELDS = [
  ['what_for_ar', 'يستخدم في'],
  ['how_to_use_ar', 'طريقة الاستخدام'],
  ['dose_ar', 'الجرعة'],
  ['frequency_ar', 'عدد المرات'],
  ['duration_ar', 'المدة'],
  ['warnings_ar', 'تحذيرات'],
  ['storage_ar', 'الحفظ'],
  ['missed_dose_ar', 'عند نسيان جرعة'],
]

const FOOD = { before: 'قبل الأكل', after: 'بعد الأكل', any: 'مع الأكل أو بدونه' }

export default function GuidanceBlock({ content, compact = false }) {
  if (!content) return null
  const rows = GUIDANCE_FIELDS.filter(([k]) => (content[k] || '').trim())
  return (
    <dl className={`space-y-1.5 ${compact ? 'text-xs' : 'text-sm'}`}>
      {content.with_food && FOOD[content.with_food] && (
        <div className="inline-flex rounded-full bg-sky-50 text-sky-800 border border-sky-200 px-2 py-0.5 text-xs">
          {FOOD[content.with_food]}
        </div>
      )}
      {rows.map(([k, label]) => (
        <div key={k} className={k === 'warnings_ar' ? 'rounded-md bg-amber-50 border border-amber-200 p-2' : ''}>
          <dt className="text-[11px] text-gray-500">{label}</dt>
          <dd className="text-gray-900 whitespace-pre-line leading-relaxed">{content[k]}</dd>
        </div>
      ))}
    </dl>
  )
}
