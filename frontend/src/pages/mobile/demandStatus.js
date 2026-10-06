// Demand (lost-sales) status styling + filter chips for the mobile intake surface.
const DEMAND_STATUS_CLASS = {
  new:                 'bg-gray-100 text-gray-700',
  assigned:            'bg-blue-100 text-blue-700',
  follow_up:           'bg-amber-100 text-amber-700',
  stock_eta:           'bg-indigo-100 text-indigo-700',
  transfer_suggested:  'bg-purple-100 text-purple-700',
  purchasing_flagged:  'bg-purple-100 text-purple-700',
  fulfilled:           'bg-green-100 text-green-700',
  lost:                'bg-red-100 text-red-700',
  cancelled:           'bg-gray-100 text-gray-600',
}

export function demandBadgeClass(status) {
  return DEMAND_STATUS_CLASS[status] || 'bg-gray-100 text-gray-700'
}

export const DEMAND_FILTERS = [
  { value: 'new',       label: 'جديد' },
  { value: '',          label: 'الكل' },
  { value: 'follow_up', label: 'متابعة' },
  { value: 'stock_eta', label: 'انتظار مخزون' },
  { value: 'fulfilled', label: 'تم التسليم' },
  { value: 'lost',      label: 'ضائعة' },
]

export const DEMAND_PRIORITIES = [
  { value: 'normal',  label: 'عادية' },
  { value: 'high',    label: 'مرتفعة' },
  { value: 'urgent',  label: 'عاجلة' },
  { value: 'chronic', label: 'مزمن' },
]

export const DEMAND_SOURCES = [
  { value: 'walk_in',  label: 'زيارة' },
  { value: 'phone',    label: 'هاتف' },
  { value: 'whatsapp', label: 'واتساب' },
  { value: 'delivery', label: 'توصيل' },
]
