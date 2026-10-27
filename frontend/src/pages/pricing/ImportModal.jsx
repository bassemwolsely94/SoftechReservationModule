/** ImportModal — bulk-create pricing requests from a CSV/XLSX upload. */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { pricingApprovalsApi } from '../../api/client'

export default function ImportModal({ onClose }) {
  const qc = useQueryClient()
  const [file, setFile] = useState(null)
  const [result, setResult] = useState(null)

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData()
      fd.append('file', file)
      return pricingApprovalsApi.import(fd)
    },
    onSuccess: (r) => { setResult(r.data); qc.invalidateQueries(['pricing-approvals']); qc.invalidateQueries(['pricing-sla']) },
    onError: (e) => setResult({ error: e?.response?.data?.detail || 'فشل الرفع' }),
  })

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" dir="rtl">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg">
        <div className="p-5 border-b flex items-center justify-between">
          <h2 className="text-lg font-bold text-gray-900">استيراد طلبات من ملف</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
        </div>
        <div className="p-5 space-y-4">
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-xs text-blue-700">
            الأعمدة المطلوبة (صف العناوين): <b>itemcode</b> + حقل واحد على الأقل من:
            pack_price، pharmacy_discp، additional_discp، special_discp، pos_discp، واختيارياً reason.
            <br />الصيغ المدعومة: CSV أو XLSX.
          </div>

          <input type="file" accept=".csv,.xlsx,.xlsm"
            onChange={e => { setFile(e.target.files[0]); setResult(null) }}
            className="block w-full text-sm border border-gray-300 rounded-lg p-2" />

          {result && !result.error && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-sm text-emerald-800">
              ✓ تم إنشاء {result.created} طلب معلّق.
              {result.skipped?.length > 0 && (
                <div className="mt-1 text-amber-700">
                  تم تخطّي {result.skipped.length} صف:
                  <ul className="list-disc pr-5 mt-1 max-h-32 overflow-y-auto">
                    {result.skipped.map((s, i) => <li key={i}>صف {s.row} ({s.itemcode}): {s.reason}</li>)}
                  </ul>
                </div>
              )}
            </div>
          )}
          {result?.error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">{result.error}</div>
          )}

          <div className="flex gap-2 justify-end">
            <button onClick={onClose} className="px-4 py-2 rounded-lg border text-sm text-gray-600 hover:bg-gray-50">
              {result && !result.error ? 'إغلاق' : 'إلغاء'}
            </button>
            <button onClick={() => upload.mutate()} disabled={!file || upload.isPending}
              className="px-5 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-60">
              {upload.isPending ? 'جاري الرفع…' : 'رفع وإنشاء الطلبات'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
