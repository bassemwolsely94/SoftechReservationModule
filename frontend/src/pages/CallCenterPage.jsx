/**
 * CallCenterPage.jsx  —  /callcenter
 * Call center operator screen: enter phone → get full patient context
 */
import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { callCenterApi, branchesApi } from '../api/client'
import useAuthStore from '../store/authStore'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

const PURPOSE_OPTIONS = [
  { value: 'reservation',  label: '📋 استفسار حجز' },
  { value: 'delivery',     label: '🚚 متابعة توصيل' },
  { value: 'refill',       label: '💊 إعادة صرف' },
  { value: 'complaint',    label: '⚠️ شكوى' },
  { value: 'new_order',    label: '🛒 طلب جديد' },
  { value: 'address',      label: '📍 تحديث عنوان' },
  { value: 'followup',     label: '🔔 متابعة مزمن' },
  { value: 'demand',       label: '🔍 صنف غير متوفر' },
  { value: 'general',      label: '💬 استفسار عام' },
]

export default function CallCenterPage() {
  const { user }  = useAuthStore()
  const qc        = useQueryClient()
  const [phone, setPhone]           = useState('')
  const [searchPhone, setSearchPhone] = useState('')
  const [logForm, setLogForm]       = useState({
    purpose: 'general', direction: 'inbound',
    status: 'answered', duration_seconds: 0,
    notes: '', summary: '', payment_method: '',
  })
  const [saved, setSaved] = useState(false)

  // ✅ ADD THIS BLOCK HERE
useEffect(() => {
  const delay = setTimeout(() => {
    if (phone.trim().length >= 8) {
      handleSearch()
    }
  }, 400)

  return () => clearTimeout(delay)
}, [phone])

  const { data: lookupData, isLoading: lookupLoading, isFetching } = useQuery({
    queryKey: ['cc-lookup', searchPhone],
    queryFn:  () => callCenterApi.lookup(searchPhone).then(r => r.data),
    enabled: !!searchPhone && searchPhone.trim().length >= 8,
    staleTime: 30_000,
  })

  function normalizePhone(phone) {
  let p = phone.trim().replace(/\s+/g, '')

  // Convert international formats to local
  if (p.startsWith('+20')) p = '0' + p.slice(3)
  if (p.startsWith('0020')) p = '0' + p.slice(4)

  return p
}

function handleSearch() {
  const clean = normalizePhone(phone)

  if (clean === searchPhone) return  // 🔥 prevent duplicate

  setSearchPhone(clean)
  setSaved(false)
}

async function handleSaveLog() {
  try {
    const customer = lookupData?.customer

    await callCenterApi.create({
      ...logForm,
      phone_number: searchPhone,
      caller_name: lookupData?.customer?.name || '',
      customer: customer?.id || null,
    })

    qc.invalidateQueries(['cc-calls'])
    setSaved(true)

  } catch (err) {
    console.error('Save failed:', err)
    alert('حدث خطأ أثناء حفظ المكالمة')
  }
}

  const data = lookupData
  const customer = data?.customer
  const lc       = data?.local_customer

  return (
    <div className="min-h-full bg-gray-50" dir="rtl">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 sticky top-0 z-20">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-lg font-black text-gray-900">مركز الاتصال</h1>
          <p className="text-xs text-gray-400 mt-0.5">ادخل رقم الهاتف لعرض بيانات المتصل</p>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-5">
        {/* Phone search */}
        <div className="card mb-5">
          <div className="flex gap-3 items-end flex-wrap">
            <div className="flex-1 min-w-52">
              <label className="label text-sm">رقم الهاتف</label>
              <input
                className="input-field font-mono text-lg"
                placeholder="010xxxxxxxx"
                dir="ltr"
                value={phone}
                onChange={e => setPhone(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSearch()}
                autoFocus
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={phone.length < 8}
              className="btn-primary text-sm px-6 py-2.5 disabled:opacity-50">
              🔍 بحث
            </button>
            <button
              onClick={() => { setPhone(''); setSearchPhone(''); setSaved(false) }}
              className="btn-secondary text-sm">
              مسح
            </button>
          </div>
        </div>

        {lookupLoading || isFetching ? (
          <div className="space-y-3 animate-pulse">
            <div className="h-32 bg-gray-100 rounded-2xl" />
            <div className="h-24 bg-gray-100 rounded-2xl" />
          </div>
        ) : data ? (
          <div className="grid md:grid-cols-3 gap-5">

            {/* Left: Patient info */}
            <div className="md:col-span-2 space-y-4">

              {/* Customer identity */}
              {(customer || lc) ? (
                <div className="card">
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                    هوية المتصل
                  </div>
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 rounded-full bg-brand-100 flex items-center
                      justify-center text-brand-700 font-black text-xl shrink-0">
                      {(customer?.name || lc?.name || '?')[0]}
                    </div>
                    <div className="flex-1">
                      <div className="font-black text-gray-900 text-lg">
                        {customer?.name || lc?.name || '—'}
                      </div>
                      <div className="flex items-center gap-3 mt-1 flex-wrap">
                        <span className="font-mono text-gray-600" dir="ltr">
                          {customer?.phone || lc?.phone}
                        </span>
                        {customer?.type_label && (
                          <span className="badge bg-blue-100 text-blue-700">
                            {customer.type_label}
                          </span>
                        )}
                        {lc?.phcode && (
                          <span className="badge bg-purple-100 text-purple-700 font-mono">
                            {lc.phcode}
                          </span>
                        )}
                      </div>
                      {customer?.branch && (
                        <div className="text-xs text-gray-400 mt-1">
                          🏥 {customer.branch}
                          {customer.discount > 0 && ` · خصم ${customer.discount}%`}
                        </div>
                      )}
                      {customer?.chronic_conditions && (
                        <div className="mt-2 text-xs bg-purple-50 text-purple-700
                          border border-purple-100 rounded-lg px-2 py-1">
                          💊 {customer.chronic_conditions}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Default location + WhatsApp */}
                  {customer?.default_location && (
                    <div className="mt-3 bg-blue-50 border border-blue-100 rounded-xl p-3">
                      <div className="text-xs font-bold text-blue-700 mb-1">📍 عنوان التوصيل</div>
                      <div className="text-sm text-gray-700">{customer.default_location.address}</div>
                      <div className="flex gap-2 mt-2">
                        {customer.default_location.maps_url && (
                          <a href={customer.default_location.maps_url} target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-blue-600 hover:underline">
                            🗺️ الخريطة
                          </a>
                        )}
                        {customer.default_location.whatsapp_url && (
                          <a href={customer.default_location.whatsapp_url} target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-green-600 hover:underline">
                            💬 واتساب
                          </a>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="card text-center py-6">
                  <div className="text-3xl mb-2">👤</div>
                  <div className="text-gray-500 font-semibold">عميل جديد — لا توجد بيانات سابقة</div>
                  <div className="text-xs text-gray-400 mt-1 font-mono" dir="ltr">{searchPhone}</div>
                </div>
              )}

              {/* Open follow-ups */}
              {data.open_followups?.length > 0 && (
                <div className="card">
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                    💊 مهام المتابعة المفتوحة ({data.open_followups.length})
                  </div>
                  <div className="space-y-2">
                    {data.open_followups.map(f => (
                      <div key={f.id}
                        className="flex items-center gap-3 bg-orange-50 border border-orange-100 rounded-xl px-3 py-2">
                        <div className="flex-1">
                          <div className="font-semibold text-sm text-gray-800">{f.item}</div>
                          <div className="text-xs text-gray-500">استحقاق: {f.due_date}</div>
                        </div>
                        <span className="badge bg-orange-100 text-orange-700 text-xs">
                          {f.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Open reservations */}
              {data.open_reservations?.length > 0 && (
                <div className="card">
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                    📋 الحجوزات المفتوحة ({data.open_reservations.length})
                  </div>
                  <div className="space-y-2">
                    {data.open_reservations.map(r => (
                      <div key={r.id}
                        className="flex items-center gap-3 bg-blue-50 border border-blue-100 rounded-xl px-3 py-2">
                        <div className="flex-1">
                          <div className="font-semibold text-sm text-gray-800">{r.item}</div>
                          <div className="text-xs text-gray-500">{r.branch}</div>
                        </div>
                        <span className="badge bg-blue-100 text-blue-700 text-xs">
                          {r.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recent calls */}
              {data.recent_calls?.length > 0 && (
                <div className="card">
                  <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                    📞 آخر المكالمات
                  </div>
                  <div className="space-y-2">
                    {data.recent_calls.map(c => (
                      <div key={c.id}
                        className="flex items-center gap-3 text-sm border-b border-gray-50 pb-2 last:pb-0 last:border-0">
                        <span className="text-gray-400 tabular-nums text-xs">
                          {c.called_at ? format(new Date(c.called_at), 'd MMM HH:mm', { locale: ar }) : '—'}
                        </span>
                        <span className="flex-1 text-gray-600 truncate">{c.summary || c.purpose_label}</span>
                        <span className="text-xs text-gray-400">{c.handled_by_name}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right: Log call */}
            <div className="space-y-4">
              <div className="card">
                <div className="text-xs font-bold text-gray-400 uppercase tracking-wide mb-3">
                  📝 تسجيل المكالمة
                </div>

                {saved ? (
                  <div className="text-center py-6">
                    <div className="text-3xl mb-2">✅</div>
                    <div className="font-semibold text-green-700">تم التسجيل</div>
                    <button onClick={() => setSaved(false)}
                      className="btn-secondary text-sm mt-3">
                      تسجيل مكالمة أخرى
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div>
                      <label className="label text-xs">الغرض</label>
                      <select className="input-field text-sm"
                        value={logForm.purpose}
                        onChange={e => setLogForm(p => ({ ...p, purpose: e.target.value }))}>
                        {PURPOSE_OPTIONS.map(o => (
                          <option key={o.value} value={o.value}>{o.label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="label text-xs">الاتجاه</label>
                        <select className="input-field text-sm"
                          value={logForm.direction}
                          onChange={e => setLogForm(p => ({ ...p, direction: e.target.value }))}>
                          <option value="inbound">📲 واردة</option>
                          <option value="outbound">📞 صادرة</option>
                          <option value="whatsapp">💬 واتساب</option>
                        </select>
                      </div>
                      <div>
                        <label className="label text-xs">الحالة</label>
                        <select className="input-field text-sm"
                          value={logForm.status}
                          onChange={e => setLogForm(p => ({ ...p, status: e.target.value }))}>
                          <option value="answered">✅ أجاب</option>
                          <option value="no_answer">📵 لا رد</option>
                          <option value="busy">📶 مشغول</option>
                          <option value="callback">🔄 معاودة</option>
                        </select>
                      </div>
                    </div>
                    <div>
                      <label className="label text-xs">ملخص سريع</label>
                      <input className="input-field text-sm"
                        placeholder="موضوع المكالمة..."
                        value={logForm.summary}
                        onChange={e => setLogForm(p => ({ ...p, summary: e.target.value }))} />
                    </div>
                    <div>
                      <label className="label text-xs">ملاحظات تفصيلية</label>
                      <textarea rows={3} className="input-field resize-none text-sm"
                        value={logForm.notes}
                        onChange={e => setLogForm(p => ({ ...p, notes: e.target.value }))} />
                    </div>
                    <button onClick={handleSaveLog} disabled={!searchPhone} className="btn-primary w-full text-sm disabled:opacity-50">
                      💾 حفظ المكالمة
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : searchPhone.length >= 8 ? (
          <div className="card text-center py-10">
            <div className="text-3xl mb-2">🔍</div>
            <div className="text-gray-500">لم يتم العثور على بيانات للرقم {searchPhone}</div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
