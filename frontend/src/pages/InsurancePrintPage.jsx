/**
 * InsurancePrintPage.jsx
 * Template selector and export for insurance claims.
 *
 * Shows a preview of each template and allows Excel download.
 */
import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { insuranceApi } from '../api/client'

const fmt = (n) => Number(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })

const TEMPLATES = [
  {
    id: 'daily_detail',
    name: 'يوميات',
    desc: 'روشتة تفصيلية مُجمَّعة حسب اليوم مع إجمالى كل يوم و4 أسطر فراغ',
    icon: '📋',
    color: 'border-blue-200 bg-blue-50',
  },
  {
    id: 'daily_summary',
    name: 'مجمل اليوميات',
    desc: 'صف واحد لكل يوم: التاريخ، عدد الروشتات، المحلى، المستورد، الإجمالى، الصافى',
    icon: '📊',
    color: 'border-purple-200 bg-purple-50',
  },
  {
    id: 'grand_total',
    name: 'الفاتورة النهائية المجمعة',
    desc: 'صف واحد شامل: رقم المطالبة، الجهة، الفترة، عدد الروشتات، كل الإجماليات',
    icon: '🧾',
    color: 'border-green-200 bg-green-50',
  },
  {
    id: 'cover',
    name: 'الغلاف',
    desc: 'صفحة الغلاف الرسمية: جدول تفصيل الخصومات (محلى / مستورد / ترسية) ومعلومات المطالبة',
    icon: '📄',
    color: 'border-amber-200 bg-amber-50',
  },
]

export default function InsurancePrintPage() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const [claim, setClaim]     = useState(null)
  const [dataset, setDataset] = useState(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(null)
  // Layout/sort for the يوميات sheet (day-grouped default, or flat custom-sorted)
  const [layout, setLayout]   = useState('daily')   // 'daily' | 'flat'
  const [sortBy, setSortBy]   = useState('patient_name')
  const [sortDir, setSortDir] = useState('asc')

  useEffect(() => {
    Promise.all([
      insuranceApi.claimDetail(id),
      insuranceApi.invoiceDataset(id),
    ]).then(([c, d]) => {
      setClaim(c.data)
      setDataset(d.data)
      setLoading(false)
    })
  }, [id])

  const exportExcel = async (template) => {
    setExporting(template)
    try {
      // The flat/sort options only affect the يوميات (daily_detail) sheet
      const opts = (template === 'daily_detail' || template === 'all')
        ? { layout, sort_by: sortBy, sort_dir: sortDir } : undefined
      const { data } = await insuranceApi.exportExcel(id, template, opts)
      // data is already a Blob (responseType: 'blob') — use it directly
      const blob = new Blob([data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url  = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href  = url
      link.download = `مطالبة_${claim?.claim_number || id}_${template}.xlsx`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      alert('فشل التصدير: ' + (err?.message || 'خطأ غير متوقع'))
    } finally {
      setExporting(null)
    }
  }

  if (loading) return <div className="p-8 text-center text-gray-400">جارٍ تحميل بيانات الفاتورة...</div>

  const cover = dataset?.cover || {}
  const claimMeta = dataset?.claim || {}

  return (
    <div className="min-h-screen bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center gap-3 mb-2">
          <button onClick={() => navigate(`/insurance/claims/${id}`)}
            className="text-blue-600 text-sm hover:underline">
            ← {claim?.claim_number}
          </button>
          <span className="text-gray-300">/</span>
          <span className="text-gray-600 text-sm">طباعة وتصدير</span>
        </div>
        <div className="flex justify-between items-start">
          <div>
            <h1 className="text-xl font-bold text-gray-900">طباعة وتصدير الفواتير</h1>
            <p className="text-sm text-gray-500">{claim?.client_name} — {claim?.subclient_name}</p>
          </div>
          <button
            onClick={() => exportExcel('all')}
            disabled={!!exporting}
            className="px-5 py-2.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50">
            {exporting === 'all' ? 'جارٍ التصدير...' : '⬇ تصدير كل الفواتير (Excel)'}
          </button>
        </div>
      </div>

      <div className="px-6 py-6 grid grid-cols-3 gap-6">
        {/* Left: Cover summary */}
        <div className="col-span-1">
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="font-bold text-gray-800 mb-4 text-base">ملخص الغلاف</h2>

            <div className="space-y-2 text-sm mb-5">
              <div className="flex justify-between">
                <span className="text-gray-500">رقم المطالبة</span>
                <span className="font-mono font-semibold">{claimMeta.claim_number}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">الجهة</span>
                <span>{claimMeta.client_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">الفئة</span>
                <span>{claimMeta.subclient_name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">الفترة</span>
                <span className="font-mono text-xs">{claimMeta.period_from} → {claimMeta.period_to}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">عدد الروشتات</span>
                <span className="font-semibold">{cover.rx_count}</span>
              </div>
            </div>

            {/* Discount breakdown table */}
            <table className="w-full text-xs border border-gray-200 rounded overflow-hidden">
              <thead className="bg-blue-700 text-white">
                <tr>
                  <th className="text-right px-2 py-1.5">البيان</th>
                  <th className="text-center px-2 py-1.5">الخصم</th>
                  <th className="text-left px-2 py-1.5">قبل</th>
                  <th className="text-left px-2 py-1.5">بعد</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ['محلى',   cover.local_disc_pct,    cover.local_before,    cover.local_net],
                  ['مستورد', cover.imported_disc_pct, cover.imported_before, cover.imported_net],
                  ['ترسية',  cover.tarsia_disc_pct,   cover.tarsia_before,   cover.tarsia_net],
                ].map(([label, pct, before, after]) => (
                  <tr key={label} className="border-b border-gray-100">
                    <td className="px-2 py-1.5 font-medium">{label}</td>
                    <td className="px-2 py-1.5 text-center text-gray-500">{pct}%</td>
                    <td className="px-2 py-1.5 text-left font-mono">{fmt(before)}</td>
                    <td className="px-2 py-1.5 text-left font-mono">{fmt(after)}</td>
                  </tr>
                ))}
                <tr className="bg-green-50 font-bold">
                  <td className="px-2 py-2">الإجمالى</td>
                  <td className="px-2 py-2 text-center text-red-600 font-mono text-xs">{fmt(cover.total_discount)}</td>
                  <td className="px-2 py-2 text-left font-mono">{fmt(cover.gross_before)}</td>
                  <td className="px-2 py-2 text-left font-mono text-green-700">{fmt(cover.net_after)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Template cards */}
        <div className="col-span-2 space-y-4">
          <h2 className="font-bold text-gray-800 text-base">اختر نموذج الطباعة</h2>
          {TEMPLATES.map(t => (
            <div key={t.id} className={`border-2 rounded-xl p-5 ${t.color}`}>
              <div className="flex justify-between items-start">
                <div className="flex gap-3">
                  <span className="text-3xl">{t.icon}</span>
                  <div>
                    <h3 className="font-bold text-gray-800 text-base">{t.name}</h3>
                    <p className="text-sm text-gray-600 mt-1">{t.desc}</p>
                  </div>
                </div>
                <button
                  onClick={() => exportExcel(t.id)}
                  disabled={!!exporting}
                  className="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap">
                  {exporting === t.id ? 'جارٍ التصدير...' : '⬇ Excel'}
                </button>
              </div>

              {/* Layout + sort controls for the يوميات sheet */}
              {t.id === 'daily_detail' && (
                <div className="mt-3 pt-3 border-t border-gray-200 space-y-2">
                  <div className="flex items-center gap-2 flex-wrap text-sm">
                    <span className="text-gray-500">الترتيب:</span>
                    <button onClick={() => setLayout('daily')}
                      className={`px-2.5 py-1 rounded text-xs border ${layout === 'daily' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white border-gray-300 text-gray-600'}`}>
                      مُجمَّع حسب اليوم
                    </button>
                    <button onClick={() => setLayout('flat')}
                      className={`px-2.5 py-1 rounded text-xs border ${layout === 'flat' ? 'bg-blue-600 text-white border-blue-600' : 'bg-white border-gray-300 text-gray-600'}`}>
                      قائمة مسطحة (بدون تجميع يومى)
                    </button>
                  </div>
                  {layout === 'flat' && (
                    <div className="flex items-center gap-2 flex-wrap text-sm">
                      <span className="text-gray-500">فرز حسب:</span>
                      <select value={sortBy} onChange={e => setSortBy(e.target.value)}
                        className="border border-gray-300 rounded px-2 py-1 text-xs">
                        <option value="patient_name">اسم المريض</option>
                        <option value="date">تاريخ الصرف</option>
                        <option value="net">الصافى</option>
                        <option value="gross">الإجمالى</option>
                        <option value="docnumber">رقم الفاتورة</option>
                      </select>
                      <select value={sortDir} onChange={e => setSortDir(e.target.value)}
                        className="border border-gray-300 rounded px-2 py-1 text-xs">
                        <option value="asc">تصاعدى (أ → ي)</option>
                        <option value="desc">تنازلى (ي → أ)</option>
                      </select>
                      <span className="text-[11px] text-blue-600">
                        قائمة واحدة متصلة، كل الأعمدة، بإجمالى كلى واحد.
                      </span>
                    </div>
                  )}
                </div>
              )}

              {/* Mini preview of day counts */}
              {t.id === 'daily_detail' && layout === 'daily' && dataset?.days && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <p className="text-xs text-gray-500 mb-2">معاينة الأيام:</p>
                  <div className="flex flex-wrap gap-1">
                    {dataset.days.slice(0, 10).map((d, i) => (
                      <span key={i} className={`text-xs px-2 py-0.5 rounded ${d.is_supplement ? 'bg-amber-100 text-amber-700' : 'bg-white border border-gray-200 text-gray-600'}`}>
                        {d.is_supplement ? '📎' : ''}{d.date?.slice(5) || d.date} ({d.day_totals?.rx_count})
                      </span>
                    ))}
                    {dataset.days.length > 10 && <span className="text-xs text-gray-400">+{dataset.days.length - 10} أيام</span>}
                  </div>
                </div>
              )}

              {t.id === 'daily_summary' && dataset?.days && (
                <div className="mt-3 pt-3 border-t border-gray-200">
                  <div className="text-xs text-gray-500 flex gap-4">
                    <span>{dataset.days.length} يوم</span>
                    <span>{dataset.claim_totals?.rx_count} روشتة</span>
                    <span className="font-mono font-semibold text-gray-800">{fmt(dataset.claim_totals?.net_after)} ج.م</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
