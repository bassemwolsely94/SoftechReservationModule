import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { reservationsApi } from '../api/client'
import { format } from 'date-fns'
import { ar } from 'date-fns/locale'

const ACTIVITY_OPTIONS = [
  { group: 'مكالمات', options: [
    { value: 'call_answered',           label: '📞 اتصل — رد العميل' },
    { value: 'call_no_answer',          label: '📵 اتصل — لم يرد' },
    { value: 'call_busy',               label: '🔴 اتصل — مشغول' },
    { value: 'call_wrong_number',       label: '❌ رقم خاطئ' },
    { value: 'call_callback_requested', label: '🔁 طلب معاودة الاتصال' },
  ]},
  { group: 'استجابة العميل', options: [
    { value: 'customer_coming_today',      label: '✅ العميل قادم اليوم' },
    { value: 'customer_coming_date',       label: '📅 العميل حدد موعد' },
    { value: 'customer_not_interested',    label: '🚫 غير مهتم' },
    { value: 'customer_wants_alternative', label: '🔄 يريد بديل' },
  ]},
  { group: 'مخزون وتوريد', options: [
    { value: 'item_ordered_supplier', label: '🏭 تم طلب الصنف من المورد' },
    { value: 'item_expected_date',    label: '📦 تاريخ وصول الصنف متوقع' },
    { value: 'item_arrived',          label: '✅ وصل الصنف' },
  ]},
  { group: 'عام', options: [
    { value: 'note_added',     label: '📝 ملاحظة' },
    { value: 'follow_up_set',  label: '📅 تحديد موعد متابعة' },
  ]},
]

const TYPE_ICONS = {
  call_answered:           '📞',
  call_no_answer:          '📵',
  call_busy:               '🔴',
  call_wrong_number:       '❌',
  call_callback_requested: '🔁',
  customer_coming_today:   '✅',
  customer_coming_date:    '📅',
  customer_not_interested: '🚫',
  customer_wants_alternative: '🔄',
  item_ordered_supplier:   '🏭',
  item_expected_date:      '📦',
  item_arrived:            '✅',
  note_added:              '📝',
  follow_up_set:           '📅',
  status_updated:          '🔄',
}

export default function ActivityLogPanel({ reservationId }) {
  const qc = useQueryClient()
  const [activityType, setActivityType] = useState('')
  const [note, setNote] = useState('')
  const [callbackDatetime, setCallbackDatetime] = useState('')
  const [expectedDate, setExpectedDate] = useState('')
  const [showForm, setShowForm] = useState(false)

  const { data: logs, isLoading } = useQuery({
    queryKey: ['activity', reservationId],
    queryFn: () => reservationsApi.activity(reservationId).then(r => r.data),
  })

  const mutation = useMutation({
    mutationFn: () => reservationsApi.logActivity(reservationId, {
      activity_type: activityType,
      note,
      callback_datetime: callbackDatetime || null,
      expected_date: expectedDate || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries(['activity', reservationId])
      qc.invalidateQueries(['reservation', String(reservationId)])
      setActivityType('')
      setNote('')
      setCallbackDatetime('')
      setExpectedDate('')
      setShowForm(false)
    },
  })

  const needsCallback = activityType === 'call_callback_requested'
  const needsExpectedDate = activityType === 'item_expected_date'
  const needsCustomerDate = activityType === 'customer_coming_date'

  return (
    <div className="card" dir="rtl">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-bold text-gray-700 text-sm">سجل النشاط</h3>
        <button
          onClick={() => setShowForm(v => !v)}
          className="btn-primary text-xs"
        >
          {showForm ? 'إخفاء' : '+ تسجيل نشاط'}
        </button>
      </div>

      {/* Log form */}
      {showForm && (
        <div className="card bg-gray-50 border border-gray-200 mb-4 animate-fade-in">
          <div className="mb-3">
            <label className="label">نوع النشاط *</label>
            <select
              className="input-field"
              value={activityType}
              onChange={e => setActivityType(e.target.value)}
            >
              <option value="">اختر...</option>
              {ACTIVITY_OPTIONS.map(group => (
                <optgroup key={group.group} label={group.group}>
                  {group.options.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          {needsCallback && (
            <div className="mb-3">
              <label className="label">موعد معاودة الاتصال</label>
              <input
                type="datetime-local"
                className="input-field"
                value={callbackDatetime}
                onChange={e => setCallbackDatetime(e.target.value)}
              />
            </div>
          )}

          {(needsExpectedDate || needsCustomerDate) && (
            <div className="mb-3">
              <label className="label">
                {needsCustomerDate ? 'تاريخ قدوم العميل' : 'تاريخ وصول الصنف المتوقع'}
              </label>
              <input
                type="date"
                className="input-field"
                value={expectedDate}
                onChange={e => setExpectedDate(e.target.value)}
              />
            </div>
          )}

          <div className="mb-3">
            <label className="label">ملاحظة (اختياري)</label>
            <textarea
              rows={2}
              className="input-field"
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder="تفاصيل إضافية..."
            />
          </div>

          {mutation.isError && (
            <div className="text-red-600 text-xs mb-2">
              {mutation.error?.response?.data?.detail || 'حدث خطأ'}
            </div>
          )}

          <button
            disabled={!activityType || mutation.isPending}
            onClick={() => mutation.mutate()}
            className="btn-primary text-sm disabled:opacity-50"
          >
            {mutation.isPending ? 'جارٍ الحفظ...' : 'حفظ النشاط'}
          </button>
        </div>
      )}

      {/* Log entries */}
      {isLoading ? (
        <div className="text-gray-400 text-sm text-center py-4">جارٍ التحميل...</div>
      ) : logs?.length === 0 ? (
        <div className="text-gray-400 text-sm text-center py-6">
          لا يوجد نشاط مسجل بعد
        </div>
      ) : (
        <div className="space-y-3">
          {logs?.map(log => (
            <div key={log.id} className="flex gap-3 text-sm">
              <div className="text-lg flex-shrink-0 mt-0.5">
                {TYPE_ICONS[log.activity_type] || '📝'}
              </div>
              <div className="flex-1">
                <div className="font-semibold text-gray-800">
                  {log.activity_type_display}
                </div>
                {log.note && (
                  <div className="text-gray-600 text-xs mt-0.5">{log.note}</div>
                )}
                {log.callback_datetime && (
                  <div className="text-blue-600 text-xs mt-0.5">
                    موعد: {format(new Date(log.callback_datetime), 'd MMM yyyy HH:mm', { locale: ar })}
                  </div>
                )}
                {log.expected_date && (
                  <div className="text-green-600 text-xs mt-0.5">
                    تاريخ متوقع: {format(new Date(log.expected_date), 'd MMM yyyy', { locale: ar })}
                  </div>
                )}
                <div className="text-gray-400 text-xs mt-1">
                  {log.logged_by_name} — {format(new Date(log.logged_at), 'd MMM HH:mm', { locale: ar })}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
