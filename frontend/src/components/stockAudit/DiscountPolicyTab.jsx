/**
 * C07 — «💸 خصم فوق السياسة» (stock-audit check 12), UNVALIDATED preview.
 *
 * The server computes the check live for the chosen period (≤ 31 days) and the user's branches and
 * stores nothing. Every number here is labelled «غير معتمد» until finance checks the samples; the rule
 * itself stays off until management switches it on in settings. Nothing here changes a discount.
 */
import { useQuery } from '@tanstack/react-query'
import { stockAuditApi } from '../../api/client'
import DataTable from '../DataTable'

const fmt = v => (v == null || v === '' ? '—'
  : Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))

const GROUP_COLUMNS = label => [
  { key: 'label', label, width: 220, cellClass: 'font-medium text-gray-900' },
  { key: 'lines', label: 'سطور', type: 'integer', width: 90, align: 'center' },
  { key: 'excess_egp', label: 'الزيادة (ج.م)', type: 'currency', width: 130, align: 'left', cellClass: 'font-bold', render: v => fmt(v) },
]

const SAMPLE_COLUMNS = [
  { key: 'branch_name', label: 'الفرع', width: 140 },
  { key: 'docnumber', label: 'الفاتورة', type: 'integer', width: 100 },
  { key: 'docdate', label: 'التاريخ', width: 100 },
  { key: 'item_name', label: 'الصنف', width: 220 },
  { key: 'softech_user', label: 'المستخدم', width: 80 },
  { key: 'channel', label: 'القناة', width: 70 },
  { key: 'actual_pct', label: 'الخصم %', type: 'number', width: 80, align: 'center', render: v => fmt(v) },
  { key: 'expected_pct', label: 'المسموح %', type: 'number', width: 90, align: 'center', render: v => fmt(v) },
  { key: 'item_ceiling_pct', label: 'سقف الصنف %', type: 'number', width: 100, align: 'center', render: v => fmt(v) },
  { key: 'excess_egp', label: 'الزيادة (ج.م)', type: 'currency', width: 110, align: 'left', render: v => fmt(v) },
]

function Box({ title, rows, label, tour }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200" data-tour={tour}>
      <h3 className="font-bold text-gray-900 text-sm px-3 pt-3">{title}</h3>
      <DataTable columns={GROUP_COLUMNS(label)} rows={rows || []} rowKey={r => r.key || '—'} stickyHeader={false}
        defaultSort={{ key: 'excess_egp', dir: 'desc' }} emptyLabel="لا شيء" />
    </div>
  )
}

export default function DiscountPolicyTab({ f }) {
  const params = { from: f.from, to: f.to, branch: (f.branch || []).join(',') }
  const { data, isLoading, error } = useQuery({
    queryKey: ['stock-audit', 'discount-policy', params],
    queryFn: () => stockAuditApi.discountPolicy(params).then(r => r.data),
    retry: false,
  })
  if (isLoading) return <div className="p-6 text-gray-400">جاري الحساب…</div>
  if (error) return <div className="p-4 text-sm text-red-600">{error.response?.data?.detail || 'تعذّر الحساب'}</div>
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900" data-tour="stock-audit-main-discount-banner">
        <div className="font-bold">⚠️ غير معتمد — للمراجعة فقط</div>
        <div>الأرقام دي محسوبة مباشرة ومش محفوظة. الفحص متوقف{data.rule_enabled ? ' (اتشغّل من الإعدادات)' : ''} لحد ما المالية تراجع العينات.
          المسموح = الأعلى من سقف خصم الصنف، وخصم فئة العميل للقناة (من الإعدادات)، وخصم العميل نفسه. التعاقدات والتبرعات والتعويضات مستبعدة. مفيش أي تغيير في الخصومات.</div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-white rounded-xl border border-gray-200 p-3"><div className="text-xs text-gray-500">سطور عليها خصم عميل</div><div className="text-xl font-bold">{data.lines_with_discount.toLocaleString('en-US')}</div></div>
        <div className="bg-white rounded-xl border border-gray-200 p-3"><div className="text-xs text-gray-500">فوق السياسة (غير معتمد)</div><div className="text-xl font-bold text-amber-700">{data.breach_lines.toLocaleString('en-US')}</div></div>
        <div className="bg-white rounded-xl border border-gray-200 p-3"><div className="text-xs text-gray-500">قيمة الزيادة (ج.م)</div><div className="text-xl font-bold text-amber-700">{fmt(data.excess_egp)}</div></div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Box title="حسب الفرع" label="الفرع" rows={data.by_branch} tour="stock-audit-main-discount-branch" />
        <Box title="حسب المستخدم (أعلى 30)" label="المستخدم" rows={data.by_user} />
        <Box title="حسب الصنف (أعلى 30)" label="الصنف" rows={data.by_item} />
      </div>
      <div className="bg-white rounded-xl border border-gray-200" data-tour="stock-audit-main-discount-samples">
        <h3 className="font-bold text-gray-900 text-sm px-3 pt-3">عينات للمراجعة في SOFTECH ({data.samples.length})</h3>
        <DataTable columns={SAMPLE_COLUMNS} rows={data.samples} rowKey={r => `${r.branchcode}-${r.docnumber}-${r.itemcode}`}
          stickyHeader={false} emptyLabel="لا توجد سطور فوق السياسة في الفترة" />
      </div>
      <div className="bg-white rounded-xl border border-gray-200 p-3 text-sm">
        <h3 className="font-bold text-gray-900 mb-2">خطوات الاعتماد</h3>
        <ol className="list-decimal pr-5 space-y-1 text-gray-700">
          {data.validation_steps.map((s, i) => <li key={i}>{s.ar}</li>)}
        </ol>
      </div>
    </div>
  )
}
