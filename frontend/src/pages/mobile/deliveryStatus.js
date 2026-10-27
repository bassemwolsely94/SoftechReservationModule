// Delivery status styling + labels for the mobile order-status board.
// The API returns status_label (Arabic + emoji) for the current status; for
// status-log from/to codes we map the raw code to a short Arabic label here.

export const DELIVERY_STATUS_LABEL = {
  created:              'جديد',
  pending_review:       'بانتظار المراجعة',
  preparing:            'جاري التحضير',
  ready:                'جاهز',
  assigned:             'تم التكليف',
  driver_accepted:      'السائق قبِل',
  out_for_delivery:     'في الطريق',
  delivered:            'تم التسليم',
  partial_delivery:     'تسليم جزئي',
  customer_unavailable: 'العميل غير متاح',
  failed:               'فشل التسليم',
  returned:             'مُعاد',
  cancelled:            'ملغى',
  closed:               'مغلق',
}

const DELIVERY_STATUS_CLASS = {
  created:              'bg-gray-100 text-gray-700',
  pending_review:       'bg-amber-100 text-amber-700',
  preparing:            'bg-amber-100 text-amber-700',
  ready:                'bg-blue-100 text-blue-700',
  assigned:             'bg-indigo-100 text-indigo-700',
  driver_accepted:      'bg-indigo-100 text-indigo-700',
  out_for_delivery:     'bg-purple-100 text-purple-700',
  delivered:            'bg-green-100 text-green-700',
  partial_delivery:     'bg-amber-100 text-amber-700',
  customer_unavailable: 'bg-orange-100 text-orange-700',
  failed:               'bg-red-100 text-red-700',
  returned:             'bg-orange-100 text-orange-700',
  cancelled:            'bg-gray-100 text-gray-600',
  closed:               'bg-green-100 text-green-700',
}

export function deliveryBadgeClass(status) {
  return DELIVERY_STATUS_CLASS[status] || 'bg-gray-100 text-gray-700'
}

export function deliveryStatusLabel(code) {
  return DELIVERY_STATUS_LABEL[code] || code || '—'
}

// Board filter chips. 'active' uses the server `active=true` (excludes terminal).
export const DELIVERY_FILTERS = [
  { value: 'active',           label: 'النشطة',     param: { active: 'true' } },
  { value: 'ready',            label: 'جاهز',       param: { status: 'ready' } },
  { value: 'out_for_delivery', label: 'في الطريق',  param: { status: 'out_for_delivery' } },
  { value: 'delivered',        label: 'تم التسليم', param: { status: 'delivered' } },
  { value: '',                 label: 'الكل',       param: {} },
]
