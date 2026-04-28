const STATUS_MAP = {
  pending:   { label: 'قيد الانتظار',    bg: 'bg-gray-100',   text: 'text-gray-700' },
  available: { label: 'المخزون متاح',    bg: 'bg-orange-100', text: 'text-orange-700' },
  contacted: { label: 'تم التواصل',      bg: 'bg-blue-100',   text: 'text-blue-700' },
  confirmed: { label: 'مؤكد',            bg: 'bg-indigo-100', text: 'text-indigo-700' },
  fulfilled: { label: 'تم التسليم',      bg: 'bg-green-100',  text: 'text-green-700' },
  cancelled: { label: 'ملغي',            bg: 'bg-red-100',    text: 'text-red-700' },
  expired:   { label: 'منتهي',           bg: 'bg-red-100',    text: 'text-red-700' },
}

const PRIORITY_MAP = {
  normal:  { label: 'عادي',        bg: 'bg-gray-100',   text: 'text-gray-600' },
  urgent:  { label: 'عاجل',        bg: 'bg-red-100',    text: 'text-red-700' },
  chronic: { label: 'مريض مزمن',   bg: 'bg-purple-100', text: 'text-purple-700' },
}

export function StatusBadge({ status }) {
  const m = STATUS_MAP[status] || { label: status, bg: 'bg-gray-100', text: 'text-gray-600' }
  return (
    <span className={`badge ${m.bg} ${m.text}`}>{m.label}</span>
  )
}

export function PriorityBadge({ priority }) {
  const m = PRIORITY_MAP[priority] || { label: priority, bg: 'bg-gray-100', text: 'text-gray-600' }
  return (
    <span className={`badge ${m.bg} ${m.text}`}>{m.label}</span>
  )
}

export const STATUS_OPTIONS = Object.entries(STATUS_MAP).map(([value, { label }]) => ({ value, label }))
export const PRIORITY_OPTIONS = Object.entries(PRIORITY_MAP).map(([value, { label }]) => ({ value, label }))
