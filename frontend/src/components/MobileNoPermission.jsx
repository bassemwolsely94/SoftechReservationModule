/** Calm line instead of a form the server would refuse (UAT W8): the role lacks the write grant. */
export default function MobileNoPermission({ text = 'ليس لديك صلاحية الإنشاء هنا', hint = 'يمكنك عرض البيانات فقط. اطلب الصلاحية من المدير إن احتجتها.' }) {
  return (
    <div data-tour="mobile-no-create" className="bg-white rounded-2xl border border-gray-200 p-5 text-center space-y-1.5">
      <div className="text-2xl">🔒</div>
      <div className="text-sm font-medium text-gray-700">{text}</div>
      {hint && <div className="text-xs text-gray-400">{hint}</div>}
    </div>
  )
}
