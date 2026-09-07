/**
 * WhatsAppCampaignPage.jsx
 *
 * Full campaign management UI:
 *  - Left panel  : campaign list with status filter tabs
 *  - Right panel : campaign detail (create / edit / view)
 *    - Tabs: Overview | Audience | Messages
 *    - Approval workflow action bar
 */
import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { campaignsApi, branchesApi, itemsApi } from '../api/client'

// ── Status config ─────────────────────────────────────────────────────────────
const STATUS_META = {
  draft:            { label: 'مسودة',            color: 'bg-gray-100 text-gray-700' },
  pending_approval: { label: 'بانتظار الموافقة', color: 'bg-yellow-100 text-yellow-800' },
  approved:         { label: 'معتمدة',           color: 'bg-green-100 text-green-700' },
  scheduled:        { label: 'مجدولة',           color: 'bg-blue-100 text-blue-700' },
  running:          { label: 'جارية',            color: 'bg-indigo-100 text-indigo-700' },
  paused:           { label: 'موقوفة',           color: 'bg-orange-100 text-orange-700' },
  completed:        { label: 'مكتملة',           color: 'bg-teal-100 text-teal-700' },
  cancelled:        { label: 'ملغاة',            color: 'bg-red-100 text-red-600' },
  rejected:         { label: 'مرفوضة',           color: 'bg-red-100 text-red-700' },
}

const STATUS_TABS = [
  { key: '',                 label: 'الكل' },
  { key: 'draft',            label: 'مسودة' },
  { key: 'pending_approval', label: 'بانتظار الموافقة' },
  { key: 'approved',         label: 'معتمدة' },
  { key: 'running',          label: 'جارية' },
  { key: 'completed',        label: 'مكتملة' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────
const StatusBadge = ({ status }) => {
  const meta = STATUS_META[status] || { label: status, color: 'bg-gray-100 text-gray-600' }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}>
      {meta.label}
    </span>
  )
}

const formatDate = (dt) => {
  if (!dt) return '—'
  return new Date(dt).toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// ── Campaign list ─────────────────────────────────────────────────────────────
function CampaignList({ selectedId, onSelect, onNew }) {
  const [tab, setTab] = useState('')
  const [q, setQ] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['campaigns', tab, q],
    queryFn: () => campaignsApi.list({ status: tab || undefined, q: q || undefined })
      .then(r => r.data),
  })

  const campaigns = Array.isArray(data) ? data : (data?.results ?? [])

  return (
    <div className="flex flex-col h-full bg-white border-r border-gray-200">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-bold text-gray-800">حملات واتساب</h2>
          <button
            onClick={onNew}
            className="px-3 py-1.5 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700"
          >
            + حملة جديدة
          </button>
        </div>
        <input
          type="text"
          placeholder="بحث باسم الحملة..."
          value={q}
          onChange={e => setQ(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-400"
          dir="rtl"
        />
      </div>

      {/* Status tabs */}
      <div className="flex overflow-x-auto border-b border-gray-200 bg-gray-50">
        {STATUS_TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-shrink-0 px-3 py-2 text-xs font-medium transition-colors ${
              tab === t.key
                ? 'border-b-2 border-green-600 text-green-700 bg-white'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading && (
          <div className="p-6 text-center text-gray-400 text-sm">جارٍ التحميل...</div>
        )}
        {!isLoading && campaigns.length === 0 && (
          <div className="p-6 text-center text-gray-400 text-sm">لا توجد حملات</div>
        )}
        {campaigns.map(c => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={`w-full text-right px-4 py-3 border-b border-gray-100 hover:bg-gray-50 transition-colors ${
              selectedId === c.id ? 'bg-green-50 border-r-4 border-r-green-500' : ''
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-900 truncate">{c.name}</p>
                <p className="text-xs text-gray-500 mt-0.5">{formatDate(c.created_at)}</p>
                {c.messages_sent > 0 && (
                  <p className="text-xs text-gray-400 mt-0.5">
                    {c.messages_sent} مُرسَلة · {c.messages_delivered} مُسلَّمة
                  </p>
                )}
              </div>
              <StatusBadge status={c.status} />
            </div>
            {c.estimated_reach > 0 && (
              <p className="text-xs text-green-600 mt-1 font-medium">
                الوصول المقدَّر: {c.estimated_reach.toLocaleString('en-US')}
              </p>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Campaign form (create / edit) ─────────────────────────────────────────────
const EMPTY_FORM = {
  name: '',
  description: '',
  message_template: '',
  featured_item: '',
  scheduled_at: '',
  target_filter: {
    segment: [],
    churn_segment: [],
    has_condition: '',
    chronic_category: '',        // legacy free-text, kept for compatibility
    last_purchase_days_max: '',
    last_purchase_days_min: '',
    branch_id: '',
    min_ltv: '',
    has_whatsapp: false,
  },
}

function CampaignForm({ campaign, onSave, onCancel }) {
  const qc = useQueryClient()
  const [form, setForm] = useState(EMPTY_FORM)
  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  const { data: branchesData } = useQuery({
    queryKey: ['branches-simple'],
    queryFn: () => branchesApi.list({ page_size: 100 }).then(r => r.data?.results ?? r.data),
  })
  const branches = Array.isArray(branchesData) ? branchesData : []

  useEffect(() => {
    if (campaign) {
      setForm({
        name: campaign.name || '',
        description: campaign.description || '',
        message_template: campaign.message_template || '',
        featured_item: campaign.featured_item || '',
        scheduled_at: campaign.scheduled_at
          ? campaign.scheduled_at.slice(0, 16) : '',
        target_filter: {
          segment:               campaign.target_filter?.segment || [],
          churn_segment:         campaign.target_filter?.churn_segment || [],
          has_condition:         campaign.target_filter?.has_condition || '',
          chronic_category:      campaign.target_filter?.chronic_category || '',
          last_purchase_days_max: campaign.target_filter?.last_purchase_days_max || '',
          last_purchase_days_min: campaign.target_filter?.last_purchase_days_min || '',
          branch_id:             campaign.target_filter?.branch_id || '',
          min_ltv:               campaign.target_filter?.min_ltv || '',
          has_whatsapp:          campaign.target_filter?.has_whatsapp || false,
        },
      })
    } else {
      setForm(EMPTY_FORM)
    }
  }, [campaign])

  const saveMutation = useMutation({
    mutationFn: (data) => campaign
      ? campaignsApi.update(campaign.id, data)
      : campaignsApi.create(data),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['campaign', res.data.id] })
      onSave(res.data.id)
    },
  })

  const buildPayload = () => {
    const tf = {}
    if (form.target_filter.segment?.length)           tf.segment = form.target_filter.segment
    if (form.target_filter.churn_segment?.length)     tf.churn_segment = form.target_filter.churn_segment
    if (form.target_filter.has_condition)             tf.has_condition = form.target_filter.has_condition
    if (form.target_filter.chronic_category)          tf.chronic_category = form.target_filter.chronic_category
    if (form.target_filter.last_purchase_days_max)    tf.last_purchase_days_max = Number(form.target_filter.last_purchase_days_max)
    if (form.target_filter.last_purchase_days_min)    tf.last_purchase_days_min = Number(form.target_filter.last_purchase_days_min)
    if (form.target_filter.branch_id)                 tf.branch_id = Number(form.target_filter.branch_id)
    if (form.target_filter.min_ltv)                   tf.min_ltv = Number(form.target_filter.min_ltv)
    if (form.target_filter.has_whatsapp)              tf.has_whatsapp = true

    return {
      name: form.name,
      description: form.description,
      message_template: form.message_template,
      featured_item: form.featured_item ? Number(form.featured_item) : null,
      scheduled_at: form.scheduled_at || null,
      target_filter: tf,
    }
  }

  const toggleChurnSegment = (seg) => {
    const segs = form.target_filter.churn_segment || []
    setFilter('churn_segment', segs.includes(seg) ? segs.filter(s => s !== seg) : [...segs, seg])
  }

  const CHURN_SEGMENTS = [
    { key: 'medium',   label: '⚠️ خطر متوسط' },
    { key: 'high',     label: '🔴 خطر مرتفع' },
    { key: 'critical', label: '🚨 خطر حرج' },
  ]

  const HEALTH_CONDITIONS = [
    { key: 'diabetes',       label: '🩸 السكري' },
    { key: 'hypertension',   label: '❤️ ضغط الدم' },
    { key: 'cardiovascular', label: '🫀 أمراض القلب' },
    { key: 'cholesterol',    label: '🧪 الكوليسترول' },
    { key: 'thyroid',        label: '🦋 الغدة الدرقية' },
    { key: 'asthma',         label: '🫁 الربو' },
    { key: 'osteoporosis',   label: '🦴 هشاشة العظام' },
    { key: '',               label: 'بدون تحديد' },
  ]

  const handlePreview = async () => {
    if (!campaign) return
    setPreviewLoading(true)
    try {
      const r = await campaignsApi.previewAudience(campaign.id, buildPayload().target_filter)
      setPreview(r.data)
      qc.invalidateQueries({ queryKey: ['campaign', campaign.id] })
    } finally {
      setPreviewLoading(false)
    }
  }

  const setFilter = (key, val) =>
    setForm(f => ({ ...f, target_filter: { ...f.target_filter, [key]: val } }))

  const toggleSegment = (seg) => {
    const segs = form.target_filter.segment || []
    setFilter('segment', segs.includes(seg) ? segs.filter(s => s !== seg) : [...segs, seg])
  }

  const SEGMENTS = [
    { key: 'vip', label: 'VIP 👑' },
    { key: 'loyal', label: 'وفي ❤️' },
    { key: 'regular', label: 'عادي' },
    { key: 'occasional', label: 'عَرَضي' },
    { key: 'at_risk', label: 'في خطر ⚠️' },
    { key: 'churned', label: 'مفقود ❌' },
  ]

  const TEMPLATE_VARS = ['{{customer_name}}', '{{item_name}}', '{{branch_name}}', '{{phone}}']

  return (
    <div className="flex flex-col h-full overflow-y-auto p-6 space-y-6" dir="rtl">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-800">
          {campaign ? 'تعديل الحملة' : 'حملة جديدة'}
        </h2>
        <button onClick={onCancel} className="text-gray-400 hover:text-gray-600 text-2xl leading-none">&times;</button>
      </div>

      {/* Basic info */}
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">اسم الحملة *</label>
          <input
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
            placeholder="مثال: عروض رمضان 2025"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">وصف (اختياري)</label>
          <input
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
          />
        </div>
      </div>

      {/* Message template */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">نص الرسالة *</label>
        <div className="flex flex-wrap gap-1 mb-2">
          {TEMPLATE_VARS.map(v => (
            <button
              key={v}
              type="button"
              onClick={() => setForm(f => ({ ...f, message_template: f.message_template + v }))}
              className="px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded hover:bg-green-200"
            >
              {v}
            </button>
          ))}
        </div>
        <textarea
          value={form.message_template}
          onChange={e => setForm(f => ({ ...f, message_template: e.target.value }))}
          rows={5}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-green-400"
          placeholder="مرحباً {{customer_name}}، ..."
        />
        <p className="text-xs text-gray-400 mt-1">انقر على متغير لإضافته للرسالة</p>
      </div>

      {/* Target audience */}
      <div className="space-y-4 border border-gray-200 rounded-xl p-4">
        <h3 className="font-semibold text-gray-700 text-sm">🎯 الجمهور المستهدف</h3>

        {/* Segments */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-2">الشرائح</label>
          <div className="flex flex-wrap gap-2">
            {SEGMENTS.map(s => (
              <button
                key={s.key}
                type="button"
                onClick={() => toggleSegment(s.key)}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  (form.target_filter.segment || []).includes(s.key)
                    ? 'bg-green-600 text-white border-green-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-green-400'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Churn Risk Segments — new */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-2">
            خطر انقطاع العملاء (Churn)
            <span className="text-gray-400 font-normal mr-1">— استهدف العملاء المعرضين للمغادرة</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {CHURN_SEGMENTS.map(s => (
              <button key={s.key} type="button"
                onClick={() => toggleChurnSegment(s.key)}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                  (form.target_filter.churn_segment || []).includes(s.key)
                    ? 'bg-red-600 text-white border-red-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-red-400'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Health Condition — new */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            حالة صحية مزمنة
            <span className="text-gray-400 font-normal mr-1">— من الملف الصحي المنظَّم</span>
          </label>
          <select
            value={form.target_filter.has_condition}
            onChange={e => setFilter('has_condition', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
          >
            {HEALTH_CONDITIONS.map(c => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
        </div>

        {/* Has WhatsApp — new */}
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="has_whatsapp"
            checked={form.target_filter.has_whatsapp}
            onChange={e => setFilter('has_whatsapp', e.target.checked)}
            className="w-4 h-4 accent-green-600"
          />
          <label htmlFor="has_whatsapp" className="text-xs font-medium text-gray-600 cursor-pointer">
            لديهم رقم واتساب مسجَّل فقط
          </label>
        </div>

        {/* Chronic (legacy free-text — kept for backward compat) */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            تصنيف مزمن (نص حر — قديم)
          </label>
          <input
            value={form.target_filter.chronic_category}
            onChange={e => setFilter('chronic_category', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
            placeholder="مثال: ضغط الدم — يستخدم فقط إذا لم يُحدَّد التصنيف الصحي أعلاه"
          />
        </div>

        {/* Branch */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">الفرع المفضَّل</label>
          <select
            value={form.target_filter.branch_id}
            onChange={e => setFilter('branch_id', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
          >
            <option value="">كل الفروع</option>
            {branches.map(b => (
              <option key={b.id} value={b.id}>{b.name_ar || b.name}</option>
            ))}
          </select>
        </div>

        {/* Purchase recency */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">اشترى خلال آخر (يوم)</label>
            <input
              type="number" min="1"
              value={form.target_filter.last_purchase_days_max}
              onChange={e => setFilter('last_purchase_days_max', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
              placeholder="مثال: 90"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">لم يشترِ منذ (يوم)</label>
            <input
              type="number" min="1"
              value={form.target_filter.last_purchase_days_min}
              onChange={e => setFilter('last_purchase_days_min', e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
              placeholder="مثال: 30"
            />
          </div>
        </div>

        {/* Min LTV */}
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">حد أدنى لقيمة العميل (LTV)</label>
          <input
            type="number" min="0"
            value={form.target_filter.min_ltv}
            onChange={e => setFilter('min_ltv', e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
            placeholder="مثال: 1000"
          />
        </div>

        {/* Preview button */}
        {campaign && (
          <button
            type="button"
            onClick={handlePreview}
            disabled={previewLoading}
            className="w-full py-2 bg-blue-50 text-blue-700 border border-blue-200 rounded-lg text-sm font-medium hover:bg-blue-100 disabled:opacity-50"
          >
            {previewLoading ? 'جارٍ الحساب...' : '👥 معاينة الجمهور'}
          </button>
        )}
        {preview && (
          <div className="bg-blue-50 rounded-lg p-3 text-sm">
            <p className="font-semibold text-blue-800">
              إجمالي العملاء: {preview.total_customers?.toLocaleString('en-US')}
            </p>
            <p className="text-blue-700">
              لديهم رقم هاتف: <strong>{preview.has_phone?.toLocaleString('en-US')}</strong>
            </p>
            {preview.sample_names?.length > 0 && (
              <p className="text-blue-600 text-xs mt-1">
                أمثلة: {preview.sample_names.slice(0, 5).join('، ')}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Schedule */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          موعد الإرسال (اختياري — فارغ = يدوي)
        </label>
        <input
          type="datetime-local"
          value={form.scheduled_at}
          onChange={e => setForm(f => ({ ...f, scheduled_at: e.target.value }))}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-green-400"
        />
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button
          onClick={() => saveMutation.mutate(buildPayload())}
          disabled={!form.name || !form.message_template || saveMutation.isPending}
          className="flex-1 py-2.5 bg-green-600 text-white rounded-lg font-medium text-sm hover:bg-green-700 disabled:opacity-50"
        >
          {saveMutation.isPending ? 'جارٍ الحفظ...' : 'حفظ الحملة'}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2.5 bg-gray-100 text-gray-700 rounded-lg text-sm hover:bg-gray-200"
        >
          إلغاء
        </button>
      </div>
      {saveMutation.isError && (
        <p className="text-red-600 text-xs">
          {saveMutation.error?.response?.data?.detail || 'حدث خطأ أثناء الحفظ'}
        </p>
      )}
    </div>
  )
}

// ── Workflow action bar ───────────────────────────────────────────────────────
function WorkflowBar({ campaign, onAction }) {
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectBox, setShowRejectBox] = useState(false)
  const [scheduledAt, setScheduledAt] = useState('')

  if (!campaign) return null
  const { status } = campaign

  return (
    <div className="border-t border-gray-200 bg-gray-50 px-6 py-3 flex flex-wrap items-center gap-2" dir="rtl">
      {status === 'draft' && campaign.can_request_approval && (
        <button
          onClick={() => onAction('request-approval')}
          className="px-4 py-2 bg-yellow-500 text-white text-sm rounded-lg hover:bg-yellow-600 font-medium"
        >
          📤 طلب الموافقة
        </button>
      )}

      {status === 'pending_approval' && (
        <>
          <button
            onClick={() => onAction('approve')}
            className="px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 font-medium"
          >
            ✅ اعتماد
          </button>
          {!showRejectBox ? (
            <button
              onClick={() => setShowRejectBox(true)}
              className="px-4 py-2 bg-red-500 text-white text-sm rounded-lg hover:bg-red-600 font-medium"
            >
              ❌ رفض
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <input
                value={rejectReason}
                onChange={e => setRejectReason(e.target.value)}
                placeholder="سبب الرفض..."
                className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm w-48"
              />
              <button
                onClick={() => { onAction('reject', rejectReason); setShowRejectBox(false) }}
                disabled={!rejectReason}
                className="px-3 py-1.5 bg-red-600 text-white text-sm rounded-lg disabled:opacity-50"
              >
                تأكيد الرفض
              </button>
              <button
                onClick={() => setShowRejectBox(false)}
                className="text-gray-400 text-sm hover:text-gray-600"
              >
                إلغاء
              </button>
            </div>
          )}
        </>
      )}

      {status === 'approved' && campaign.can_queue && (
        <div className="flex items-center gap-2">
          <input
            type="datetime-local"
            value={scheduledAt}
            onChange={e => setScheduledAt(e.target.value)}
            className="px-2 py-1.5 border border-gray-300 rounded-lg text-sm"
          />
          <button
            onClick={() => onAction('queue', { scheduled_at: scheduledAt || undefined })}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 font-medium"
          >
            🚀 {scheduledAt ? 'جدولة الإرسال' : 'إرسال فوري'}
          </button>
        </div>
      )}

      {campaign.can_cancel && (
        <button
          onClick={() => onAction('cancel')}
          className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded-lg hover:bg-gray-300 font-medium mr-auto"
        >
          🚫 إلغاء الحملة
        </button>
      )}
    </div>
  )
}

// ── Messages tab ──────────────────────────────────────────────────────────────
function MessagesTab({ campaign }) {
  const [statusFilter, setStatusFilter] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['campaign-messages', campaign.id, statusFilter],
    queryFn: () => campaignsApi.messages(campaign.id, { status: statusFilter || undefined })
      .then(r => r.data),
    enabled: !!campaign.id,
  })

  const messages = Array.isArray(data) ? data : (data?.results ?? [])

  const MSG_STATUS_COLOR = {
    pending:   'bg-gray-100 text-gray-600',
    sent:      'bg-blue-100 text-blue-700',
    delivered: 'bg-green-100 text-green-700',
    failed:    'bg-red-100 text-red-600',
    opted_out: 'bg-orange-100 text-orange-700',
    skipped:   'bg-gray-100 text-gray-400',
  }

  return (
    <div className="flex flex-col h-full">
      {/* Filter */}
      <div className="flex gap-2 p-4 border-b border-gray-100">
        {[
          { key: '', label: 'الكل' },
          { key: 'pending', label: 'في الانتظار' },
          { key: 'sent', label: 'مُرسَلة' },
          { key: 'delivered', label: 'مُسلَّمة' },
          { key: 'failed', label: 'فاشلة' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setStatusFilter(t.key)}
            className={`px-3 py-1 text-xs rounded-full border transition-colors ${
              statusFilter === t.key
                ? 'bg-green-600 text-white border-green-600'
                : 'border-gray-200 text-gray-600 hover:border-green-400'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading && <div className="p-4 text-center text-gray-400 text-sm">جارٍ التحميل...</div>}
        {!isLoading && messages.length === 0 && (
          <div className="p-6 text-center text-gray-400 text-sm">لا توجد رسائل</div>
        )}
        {messages.map(msg => (
          <div
            key={msg.id}
            className="px-4 py-3 border-b border-gray-100 hover:bg-gray-50"
            dir="rtl"
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-800">{msg.customer_name || msg.phone_number}</p>
                <p className="text-xs text-gray-500 font-mono">{msg.phone_number}</p>
                <p className="text-xs text-gray-600 mt-1 line-clamp-2">{msg.message_text}</p>
              </div>
              <div className="flex flex-col items-end gap-1 flex-shrink-0">
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${MSG_STATUS_COLOR[msg.status] || 'bg-gray-100 text-gray-600'}`}>
                  {msg.status_label}
                </span>
                {msg.whatsapp_url && (
                  <a
                    href={msg.whatsapp_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-green-600 hover:underline"
                  >
                    📱 فتح واتساب
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Campaign detail panel ─────────────────────────────────────────────────────
function CampaignDetail({ campaignId, onClose }) {
  const [tab, setTab] = useState('overview')
  const [editing, setEditing] = useState(false)
  const qc = useQueryClient()

  const { data: campaign, isLoading } = useQuery({
    queryKey: ['campaign', campaignId],
    queryFn: () => campaignsApi.get(campaignId).then(r => r.data),
    enabled: !!campaignId,
  })

  const { data: stats } = useQuery({
    queryKey: ['campaign-stats', campaignId],
    queryFn: () => campaignsApi.stats(campaignId).then(r => r.data),
    enabled: !!campaignId && !editing,
    refetchInterval: campaign?.status === 'running' ? 10000 : false,
  })

  const actionMutation = useMutation({
    mutationFn: ({ type, payload }) => {
      switch (type) {
        case 'request-approval': return campaignsApi.requestApproval(campaignId)
        case 'approve':          return campaignsApi.approve(campaignId)
        case 'reject':           return campaignsApi.reject(campaignId, payload)
        case 'queue':            return campaignsApi.queue(campaignId, payload)
        case 'cancel':           return campaignsApi.cancel(campaignId)
        default:                 throw new Error(`Unknown action: ${type}`)
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['campaigns'] })
      qc.invalidateQueries({ queryKey: ['campaign', campaignId] })
    },
  })

  const handleAction = (type, payload) => actionMutation.mutate({ type, payload })

  if (!campaignId) return null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        جارٍ تحميل الحملة...
      </div>
    )
  }

  if (!campaign) return null

  if (editing) {
    return (
      <CampaignForm
        campaign={campaign}
        onSave={(id) => { setEditing(false); qc.invalidateQueries({ queryKey: ['campaign', id] }) }}
        onCancel={() => setEditing(false)}
      />
    )
  }

  return (
    <div className="flex flex-col h-full" dir="rtl">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-bold text-gray-800 truncate">{campaign.name}</h2>
              <StatusBadge status={campaign.status} />
            </div>
            {campaign.description && (
              <p className="text-sm text-gray-500 mt-0.5">{campaign.description}</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {(campaign.status === 'draft' || campaign.status === 'rejected') && (
              <button
                onClick={() => setEditing(true)}
                className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg hover:bg-gray-50"
              >
                ✏️ تعديل
              </button>
            )}
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
            >
              &times;
            </button>
          </div>
        </div>

        {/* KPI row */}
        {stats && (
          <div className="flex gap-4 mt-3 text-xs">
            <span className="text-gray-600">
              إجمالي الرسائل: <strong>{stats.total || 0}</strong>
            </span>
            <span className="text-blue-600">
              مُرسَلة: <strong>{stats.sent || 0}</strong>
            </span>
            <span className="text-green-600">
              مُسلَّمة: <strong>{stats.delivered || 0}</strong>
            </span>
            <span className="text-red-500">
              فاشلة: <strong>{stats.failed || 0}</strong>
            </span>
            {stats.delivery_rate != null && (
              <span className="text-teal-600">
                معدل التسليم: <strong>{stats.delivery_rate}%</strong>
              </span>
            )}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200 bg-gray-50">
        {[
          { key: 'overview', label: 'نظرة عامة' },
          { key: 'audience', label: 'الجمهور' },
          { key: 'messages', label: 'الرسائل' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-5 py-2.5 text-sm font-medium transition-colors ${
              tab === t.key
                ? 'border-b-2 border-green-600 text-green-700 bg-white'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {tab === 'overview' && (
          <div className="p-6 space-y-5">
            {/* Message template */}
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">نص الرسالة</h3>
              <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm whitespace-pre-wrap font-sans leading-relaxed text-gray-800">
                {campaign.message_template}
              </pre>
            </div>

            {/* Timeline */}
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">المواعيد</h3>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500">تاريخ الإنشاء</span>
                  <span className="font-medium">{formatDate(campaign.created_at)}</span>
                </div>
                {campaign.approved_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">تاريخ الاعتماد</span>
                    <span className="font-medium">{formatDate(campaign.approved_at)}</span>
                  </div>
                )}
                {campaign.scheduled_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">موعد الإرسال</span>
                    <span className="font-medium text-indigo-700">{formatDate(campaign.scheduled_at)}</span>
                  </div>
                )}
                {campaign.completed_at && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">تاريخ الاكتمال</span>
                    <span className="font-medium">{formatDate(campaign.completed_at)}</span>
                  </div>
                )}
              </div>
            </div>

            {/* People */}
            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-2">الفريق</h3>
              <div className="space-y-1.5 text-sm">
                {campaign.created_by_name && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">أنشأ</span>
                    <span className="font-medium">{campaign.created_by_name}</span>
                  </div>
                )}
                {campaign.approved_by_name && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">اعتمد</span>
                    <span className="font-medium text-green-700">{campaign.approved_by_name}</span>
                  </div>
                )}
                {campaign.rejected_by_name && (
                  <div className="flex justify-between">
                    <span className="text-gray-500">رفض</span>
                    <span className="font-medium text-red-700">{campaign.rejected_by_name}</span>
                  </div>
                )}
              </div>
            </div>

            {/* Rejection reason */}
            {campaign.status === 'rejected' && campaign.rejection_reason && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <p className="text-sm font-semibold text-red-700 mb-1">سبب الرفض</p>
                <p className="text-sm text-red-600">{campaign.rejection_reason}</p>
              </div>
            )}
          </div>
        )}

        {tab === 'audience' && (
          <div className="p-6 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-green-50 rounded-xl p-4 text-center">
                <p className="text-2xl font-bold text-green-700">
                  {(campaign.estimated_reach || 0).toLocaleString('en-US')}
                </p>
                <p className="text-sm text-green-600 mt-1">الوصول المقدَّر</p>
              </div>
              <div className="bg-blue-50 rounded-xl p-4 text-center">
                <p className="text-2xl font-bold text-blue-700">
                  {(campaign.messages_queued || 0).toLocaleString('en-US')}
                </p>
                <p className="text-sm text-blue-600 mt-1">رسائل في الانتظار</p>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-gray-700 mb-3">الفلاتر المطبَّقة</h3>
              {Object.keys(campaign.target_filter || {}).length === 0 ? (
                <p className="text-sm text-gray-400">لا توجد فلاتر — كل العملاء</p>
              ) : (
                <div className="space-y-2 text-sm">
                  {campaign.target_filter.segment?.length > 0 && (
                    <div className="flex gap-2 items-center">
                      <span className="text-gray-500 w-28 flex-shrink-0">الشرائح:</span>
                      <span className="font-medium">{campaign.target_filter.segment.join('، ')}</span>
                    </div>
                  )}
                  {campaign.target_filter.chronic_category && (
                    <div className="flex gap-2 items-center">
                      <span className="text-gray-500 w-28 flex-shrink-0">التصنيف المزمن:</span>
                      <span className="font-medium">{campaign.target_filter.chronic_category}</span>
                    </div>
                  )}
                  {campaign.target_filter.last_purchase_days_max && (
                    <div className="flex gap-2 items-center">
                      <span className="text-gray-500 w-28 flex-shrink-0">اشترى خلال:</span>
                      <span className="font-medium">{campaign.target_filter.last_purchase_days_max} يوم</span>
                    </div>
                  )}
                  {campaign.target_filter.last_purchase_days_min && (
                    <div className="flex gap-2 items-center">
                      <span className="text-gray-500 w-28 flex-shrink-0">لم يشترِ منذ:</span>
                      <span className="font-medium">{campaign.target_filter.last_purchase_days_min} يوم</span>
                    </div>
                  )}
                  {campaign.target_filter.min_ltv && (
                    <div className="flex gap-2 items-center">
                      <span className="text-gray-500 w-28 flex-shrink-0">الحد الأدنى LTV:</span>
                      <span className="font-medium">{campaign.target_filter.min_ltv}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'messages' && <MessagesTab campaign={campaign} />}
      </div>

      {/* Workflow action bar */}
      {actionMutation.isError && (
        <div className="px-6 py-2 bg-red-50 border-t border-red-200">
          <p className="text-red-600 text-xs">
            {actionMutation.error?.response?.data?.detail || 'حدث خطأ في العملية'}
          </p>
        </div>
      )}
      <WorkflowBar campaign={campaign} onAction={handleAction} />
    </div>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────
export default function WhatsAppCampaignPage() {
  const [selectedId, setSelectedId] = useState(null)
  const [creating, setCreating] = useState(false)
  const qc = useQueryClient()

  const handleNew = () => {
    setSelectedId(null)
    setCreating(true)
  }

  const handleSelect = (id) => {
    setCreating(false)
    setSelectedId(id)
  }

  const handleCreated = (id) => {
    setCreating(false)
    setSelectedId(id)
    qc.invalidateQueries({ queryKey: ['campaigns'] })
  }

  return (
    <div className="flex h-screen bg-gray-50" dir="rtl">
      {/* Left: campaign list */}
      <div className="w-80 flex-shrink-0 h-full overflow-hidden border-r border-gray-200 shadow-sm">
        <CampaignList
          selectedId={selectedId}
          onSelect={handleSelect}
          onNew={handleNew}
        />
      </div>

      {/* Right: detail / create */}
      <div className="flex-1 h-full overflow-hidden bg-white">
        {creating && (
          <CampaignForm
            campaign={null}
            onSave={handleCreated}
            onCancel={() => setCreating(false)}
          />
        )}
        {!creating && selectedId && (
          <CampaignDetail
            campaignId={selectedId}
            onClose={() => setSelectedId(null)}
          />
        )}
        {!creating && !selectedId && (
          <div className="flex flex-col items-center justify-center h-full text-gray-400">
            <div className="text-6xl mb-4">📱</div>
            <p className="text-lg font-medium">اختر حملة لعرض تفاصيلها</p>
            <p className="text-sm mt-2">أو انقر "+ حملة جديدة" لإنشاء حملة واتساب</p>
          </div>
        )}
      </div>
    </div>
  )
}
