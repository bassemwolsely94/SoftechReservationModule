// Shared transfer-status styling for the mobile surfaces. The API returns
// status_color (one of these keys) + status_label (Arabic); we map the colour to
// Tailwind classes so the mobile cards/badges match the desktop palette.
export const TRANSFER_STATUS_CLASS = {
  gray:   'bg-gray-100 text-gray-700',
  orange: 'bg-orange-100 text-orange-700',
  blue:   'bg-blue-100 text-blue-700',
  red:    'bg-red-100 text-red-700',
  yellow: 'bg-yellow-100 text-yellow-700',
  purple: 'bg-purple-100 text-purple-700',
  green:  'bg-green-100 text-green-700',
}

export function transferBadgeClass(color) {
  return TRANSFER_STATUS_CLASS[color] || TRANSFER_STATUS_CLASS.gray
}

export const TRANSFER_FILTERS = [
  { value: 'pending',        label: 'بانتظار الموافقة' },
  { value: '',               label: 'الكل' },
  { value: 'draft',          label: 'مسودة' },
  { value: 'approved',       label: 'معتمد' },
  { value: 'needs_revision', label: 'يحتاج تعديل' },
  { value: 'sent_to_erp',    label: 'أُرسل للـ ERP' },
  { value: 'completed',      label: 'مكتمل' },
  { value: 'rejected',       label: 'مرفوض' },
]
