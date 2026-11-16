/**
 * SearchTierChip — one small chip saying WHY a search row matched when it is not an exact hit.
 * Shared by the item pickers and the POS result rows. At most one chip, by priority:
 * learned > ingredient > sound > approx > code_part. Synonym / exact rows get none.
 */
const CHIPS = [
  { key: 'learned', cls: 'bg-teal-100 text-teal-800', title: 'أكّد شخصٌ هذا الصنف لهذا الاسم من قبل',
    label: () => 'من الذاكرة' },
  { key: 'ingredient', cls: 'bg-violet-100 text-violet-800', title: 'تطابق المادة الفعالة وليس اسم الصنف',
    label: (row) => `مادة فعالة: ${row.ingredient_name || ''}`.trim() },
  { key: 'sound', cls: 'bg-sky-100 text-sky-800', title: 'الاسم العربي المكتوب يُنطق مثل اسم هذا الصنف',
    label: () => 'بالنطق' },
  { key: 'approx', cls: 'bg-amber-100 text-amber-800',
    title: 'لا يوجد صنف يطابق ما كُتب بالضبط — هذه أقرب الأصناف (خطأ إملائي محتمل)',
    label: () => 'تقريبي' },
  { key: 'code_part', cls: 'bg-gray-100 text-gray-700', title: 'تطابق جزءًا من كود الصنف',
    label: () => 'جزء من الكود' },
]

export default function SearchTierChip({ row }) {
  const chip = row && CHIPS.find(c => row[c.key])
  if (!chip) return null
  return (
    <span className={`ms-1.5 align-middle text-[10px] px-1.5 py-0.5 rounded-full ${chip.cls}`} title={chip.title}>
      {chip.label(row)}
    </span>
  )
}
